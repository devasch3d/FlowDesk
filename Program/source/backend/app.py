"""FlowDesk M2: authenticated, owner-scoped Project REST API."""
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal
import json
import secrets

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .models import Base, Project, User
from .migrations import migrate
from .auth import install_auth

Status = Literal['Planning', 'Active', 'Paused', 'Completed', 'Archived']

class ProjectInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=10000)
    status: Status = 'Planning'
    start_date: date | None = None
    deadline: date | None = None

    @model_validator(mode='after')
    def valid_dates(self):
        if self.start_date and self.deadline and self.deadline < self.start_date:
            raise ValueError('截止日期不能早于开始日期')
        return self

class ProjectPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=10000)
    status: Status | None = None
    start_date: date | None = None
    deadline: date | None = None

    @field_validator('name', 'description', 'status')
    @classmethod
    def not_null(cls, value):
        if value is None:
            raise ValueError('此字段不能为 null')
        return value

class ProjectOutput(ProjectInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
    version: int

def create_app(database_url: str, static_dir: Path | None = None, token: str | None = None):
    token = token or secrets.token_urlsafe(32)
    engine = create_engine(database_url, connect_args={'check_same_thread': False, 'timeout': 20} if database_url.startswith('sqlite') else {})
    if engine.dialect.name == 'sqlite':
        @event.listens_for(engine, 'connect')
        def foreign_keys(connection, record):
            connection.execute('PRAGMA foreign_keys=ON')
    migration_backup = migrate(engine)
    app = FastAPI(title='FlowDesk Account & Project API', version='0.2.0', docs_url='/api/docs', redoc_url=None)
    app.state.engine = engine
    app.state.token = token
    app.state.migration_backup = migration_backup
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])

    @app.middleware('http')
    async def local_security(request: Request, call_next):
        if request.method in ('POST', 'PATCH', 'DELETE', 'PUT'):
            origin = request.headers.get('origin')
            if origin and origin != str(request.base_url).rstrip('/'):
                return JSONResponse({'detail': '请从 FlowDesk 本地页面操作'}, status_code=403)
            if not secrets.compare_digest(request.headers.get('x-flowdesk-token', '').encode('utf-8'), token.encode('utf-8')):
                return JSONResponse({'detail': '程序已重启，请刷新页面后重试'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Cache-Control'] = 'no-store'
        if request.url.path == '/':
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        errors = [{'field': '.'.join(map(str, e['loc'][1:])), 'message': e['msg']} for e in exc.errors()]
        message = '输入无效，请检查名称、状态和日期'
        if request.url.path.startswith('/api/auth/'):
            fields = {e['field'] for e in errors}
            if 'password' in fields:
                message = '注册密码需要 10–128 个字符，且不能只包含空格' if request.url.path.endswith('/register') else '请输入密码（最多 128 个字符）'
            elif 'email' in fields:
                message = '请输入有效的邮箱地址'
            elif 'username' in fields:
                message = '用户名称需要 1–40 个字符，且不能只包含空格'
            else:
                message = '输入无效，请检查账号信息'
        return JSONResponse({'detail': message, 'errors': errors}, status_code=422)

    current_user = install_auth(app, engine)

    @app.get('/api/health')
    def health():
        with Session(engine) as db:
            db.execute(select(1))
        return {'status': 'ok', 'app': 'FlowDesk', 'version': '0.2.0'}

    @app.get('/api/projects', response_model=list[ProjectOutput])
    def list_projects(user: User = Depends(current_user)):
        with Session(engine) as db:
            return db.scalars(select(Project).where(Project.owner_id == user.id).order_by(Project.updated_at.desc(), Project.id.desc())).all()

    def find(db, project_id, user_id):
        item = db.scalar(select(Project).where(Project.id == project_id, Project.owner_id == user_id))
        if not item:
            raise HTTPException(404, '项目不存在或你没有访问权限')
        return item

    @app.get('/api/projects/{project_id}', response_model=ProjectOutput)
    def get_project(project_id: int, user: User = Depends(current_user)):
        with Session(engine) as db:
            return find(db, project_id, user.id)

    @app.post('/api/projects', response_model=ProjectOutput, status_code=201)
    def create_project(body: ProjectInput, user: User = Depends(current_user)):
        now = datetime.now(timezone.utc)
        with Session(engine) as db:
            item = Project(**body.model_dump(), owner_id=user.id, created_at=now, updated_at=now)
            db.add(item)
            db.commit()
            db.refresh(item)
            return item

    def match_version(request, item):
        expected = request.headers.get('if-match')
        if expected and expected != str(item.version):
            raise HTTPException(409, '项目已在其他页面修改，请重新打开项目后再编辑')

    @app.patch('/api/projects/{project_id}', response_model=ProjectOutput)
    def update_project(project_id: int, body: ProjectPatch, request: Request, user: User = Depends(current_user)):
        from sqlalchemy.orm.exc import StaleDataError
        from pydantic import ValidationError
        with Session(engine) as db:
            item = find(db, project_id, user.id)
            match_version(request, item)
            values = {k: getattr(item, k) for k in ProjectInput.model_fields}
            changes = body.model_dump(exclude_unset=True)
            values.update(changes)
            try:
                ProjectInput.model_validate(values)
            except ValidationError:
                raise HTTPException(422, '截止日期不能早于开始日期')
            for key, value in changes.items():
                setattr(item, key, value)
            item.updated_at = datetime.now(timezone.utc)
            try:
                db.commit()
            except StaleDataError:
                raise HTTPException(409, '项目已被修改，请刷新后重试')
            db.refresh(item)
            return item

    @app.delete('/api/projects/{project_id}', status_code=204)
    def delete_project(project_id: int, request: Request, user: User = Depends(current_user)):
        from sqlalchemy.orm.exc import StaleDataError
        with Session(engine) as db:
            item = find(db, project_id, user.id)
            match_version(request, item)
            db.delete(item)
            try:
                db.commit()
            except StaleDataError:
                raise HTTPException(409, '项目已被修改，请刷新后重试')
        return Response(status_code=204)

    @app.get('/api/export')
    def export(user: User = Depends(current_user)):
        with Session(engine) as db:
            projects = [ProjectOutput.model_validate(p).model_dump(mode='json') for p in db.scalars(select(Project).where(Project.owner_id == user.id).order_by(Project.id)).all()]
        data = json.dumps({'application': 'FlowDesk', 'schema_version': 2, 'exported_at': datetime.now(timezone.utc).isoformat(), 'projects': projects}, ensure_ascii=False, indent=2)
        return Response(data, media_type='application/json', headers={'Content-Disposition': 'attachment; filename="FlowDesk-projects.json"'})

    if static_dir and static_dir.exists():
        app.mount('/assets', StaticFiles(directory=static_dir / 'assets'), name='assets')

        @app.get('/', response_class=HTMLResponse)
        def index():
            return (static_dir / 'index.html').read_text(encoding='utf-8').replace('__FLOWDESK_TOKEN__', token)

    return app
