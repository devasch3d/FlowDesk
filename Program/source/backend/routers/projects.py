"""Project REST API router. 维护人：机器 B（Project 挂入 Workspace 改造在此文件内进行）。

M4 权限模型：
- 项目挂入空间（workspace_id 非空）时，权限沿 memberships 下推：
  空间成员可读、可改；空间 Owner/Admin 可删。
- 存量项目（workspace_id 为空）退化为 owner_id 归属，仅 owner 本人可见可改。
"""
from datetime import date, datetime, timezone
from typing import Literal
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import inspect, or_, select, text
from sqlalchemy.orm import Session

from ..models import Membership, Project, User

Status = Literal['Planning', 'Active', 'Paused', 'Completed', 'Archived']

class ProjectInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    workspace_id: int | None = None
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
    owner_id: int | None = None
    created_at: datetime
    updated_at: datetime
    version: int

def build_projects_router(engine, current_user):
    """工厂函数：把 engine 与 current_user 依赖注入每个 handler。"""
    # M4 幂等补列：老库已有 projects 表但缺 workspace_id 列时补上（migrations.py 由 A 维护）。
    insp = inspect(engine)
    if insp.has_table('projects') and 'workspace_id' not in {c['name'] for c in insp.get_columns('projects')}:
        with engine.begin() as conn:
            conn.execute(text('ALTER TABLE projects ADD COLUMN workspace_id INTEGER REFERENCES workspaces(id)'))
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_projects_workspace_id ON projects (workspace_id)'))

    router = APIRouter(prefix='/api')

    def visible_filter(user_id):
        """返回用户可见的项目条件：自己所在空间的项目 + 自己名下的存量项目。"""
        return or_(
            Project.workspace_id.in_(
                select(Membership.workspace_id).where(Membership.user_id == user_id)
            ),
            Project.workspace_id.is_(None) & (Project.owner_id == user_id),
        )

    def find(db, project_id, user_id):
        """取项目并校验访问权。返回 (item, my_role)。
        my_role 为 'Owner'/'Admin'/'Member'（空间项目）或 'owner'（存量项目）。"""
        item = db.get(Project, project_id)
        if not item:
            raise HTTPException(404, '项目不存在或你没有访问权限')
        if item.workspace_id is not None:
            m = db.get(Membership, (user_id, item.workspace_id))
            if not m:
                raise HTTPException(404, '项目不存在或你没有访问权限')
            return item, m.role
        # 存量项目：仅 owner 本人
        if item.owner_id != user_id:
            raise HTTPException(404, '项目不存在或你没有访问权限')
        return item, 'owner'

    def require_deletable(role):
        if role not in ('Owner', 'Admin', 'owner'):
            raise HTTPException(403, '只有空间 Owner 或 Admin 可以删除项目')

    @router.get('/projects', response_model=list[ProjectOutput])
    def list_projects(user: User = Depends(current_user)):
        with Session(engine) as db:
            return db.scalars(
                select(Project).where(visible_filter(user.id))
                .order_by(Project.updated_at.desc(), Project.id.desc())
            ).all()

    @router.get('/projects/{project_id}', response_model=ProjectOutput)
    def get_project(project_id: int, user: User = Depends(current_user)):
        with Session(engine) as db:
            item, _role = find(db, project_id, user.id)
            return item

    @router.post('/projects', response_model=ProjectOutput, status_code=201)
    def create_project(body: ProjectInput, user: User = Depends(current_user)):
        now = datetime.now(timezone.utc)
        with Session(engine) as db:
            if body.workspace_id is not None:
                m = db.get(Membership, (user.id, body.workspace_id))
                if not m:
                    raise HTTPException(403, '你不是该空间的成员，无法在此空间创建项目')
            item = Project(**body.model_dump(), owner_id=user.id, created_at=now, updated_at=now)
            db.add(item)
            db.commit()
            db.refresh(item)
            return item

    def match_version(request, item):
        expected = request.headers.get('if-match')
        if expected and expected != str(item.version):
            raise HTTPException(409, '项目已在其他页面修改，请重新打开项目后再编辑')

    @router.patch('/projects/{project_id}', response_model=ProjectOutput)
    def update_project(project_id: int, body: ProjectPatch, request: Request, user: User = Depends(current_user)):
        from sqlalchemy.orm.exc import StaleDataError
        from pydantic import ValidationError
        with Session(engine) as db:
            item, _role = find(db, project_id, user.id)
            match_version(request, item)
            values = {k: getattr(item, k) for k in ('workspace_id', 'name', 'description', 'status', 'start_date', 'deadline')}
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

    @router.delete('/projects/{project_id}', status_code=204)
    def delete_project(project_id: int, request: Request, user: User = Depends(current_user)):
        from sqlalchemy.orm.exc import StaleDataError
        with Session(engine) as db:
            item, role = find(db, project_id, user.id)
            require_deletable(role)
            match_version(request, item)
            db.delete(item)
            try:
                db.commit()
            except StaleDataError:
                raise HTTPException(409, '项目已被修改，请刷新后重试')
        return Response(status_code=204)

    @router.get('/export')
    def export(user: User = Depends(current_user)):
        with Session(engine) as db:
            projects = [ProjectOutput.model_validate(p).model_dump(mode='json') for p in db.scalars(
                select(Project).where(visible_filter(user.id)).order_by(Project.id)
            ).all()]
        data = json.dumps({'application': 'FlowDesk', 'schema_version': 2, 'exported_at': datetime.now(timezone.utc).isoformat(), 'projects': projects}, ensure_ascii=False, indent=2)
        return Response(data, media_type='application/json', headers={'Content-Disposition': 'attachment; filename="FlowDesk-projects.json"'})

    return router
