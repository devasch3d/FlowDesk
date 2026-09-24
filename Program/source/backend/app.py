"""FlowDesk M2: application entry. Mounts security middleware, auth and project routers."""
from pathlib import Path
import os
import secrets

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .migrations import migrate
from .auth import install_auth
from .routers.projects import build_projects_router
from .routers.workspaces import build_workspaces_router
from .routers.tasks import build_tasks_router
from .routers.files import build_files_router
from .routers.collaboration import build_collaboration_router
from .routers.dashboard import build_dashboard_router
from .routers.ai import build_ai_router

def create_app(database_url: str, static_dir: Path | None = None, token: str | None = None,
               allowed_origins: list[str] | None = None, allowed_hosts: list[str] | None = None):
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
    # 跨源白名单（M9 服务端化）：显式参数优先，其次环境变量 FLOWDESK_ALLOWED_ORIGINS（逗号分隔）。
    # 空白名单 = 本地单机模式（仅允许与 base_url 同源的浏览器请求）。
    if allowed_origins is None:
        env_origins = os.environ.get('FLOWDESK_ALLOWED_ORIGINS', '')
        allowed_origins = [o.strip().rstrip('/') for o in env_origins.split(',') if o.strip()] if env_origins else []
    app.state.allowed_origins = [o.rstrip('/') for o in allowed_origins]
    # 允许的 Host 头（M9 服务端化）：默认本地三件套；FLOWDESK_ALLOWED_HOSTS 可覆盖，'*' = 任意（局域网/公网部署）
    if allowed_hosts is None:
        env_hosts = os.environ.get('FLOWDESK_ALLOWED_HOSTS', '')
        allowed_hosts = [h.strip() for h in env_hosts.split(',') if h.strip()] if env_hosts else ['127.0.0.1', 'localhost', 'testserver']
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.middleware('http')
    async def local_security(request: Request, call_next):
        if request.method in ('POST', 'PATCH', 'DELETE', 'PUT'):
            origin = request.headers.get('origin')
            if origin:
                origin = origin.rstrip('/')
                allowed = app.state.allowed_origins
                if allowed:
                    # 服务端模式：来源必须在白名单内（SameSite=Strict Cookie 之外的第二道防线）
                    if origin not in allowed:
                        return JSONResponse({'detail': '请求来源不在允许列表'}, status_code=403)
                elif origin != str(request.base_url).rstrip('/'):
                    # 本地单机模式：拒绝跨源（CSRF 防护），保持 M2 行为不变
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
    app.include_router(build_projects_router(engine, current_user))
    app.include_router(build_workspaces_router(engine, current_user))
    app.include_router(build_tasks_router(engine, current_user))
    app.include_router(build_files_router(engine, current_user))
    app.include_router(build_collaboration_router(engine, current_user))
    app.include_router(build_dashboard_router(engine, current_user))
    app.include_router(build_ai_router(engine, current_user))

    @app.get('/api/health')
    def health():
        with Session(engine) as db:
            db.execute(select(1))
        return {'status': 'ok', 'app': 'FlowDesk', 'version': '0.2.0'}

    if static_dir and static_dir.exists():
        app.mount('/assets', StaticFiles(directory=static_dir / 'assets'), name='assets')

        @app.get('/', response_class=HTMLResponse)
        def index():
            return (static_dir / 'index.html').read_text(encoding='utf-8').replace('__FLOWDESK_TOKEN__', token)

    return app
