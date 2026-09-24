"""File REST API router (M5). 维护人：机器 C。

接口：
- POST   /api/files                       multipart 上传（挂在空间/项目/任务之一）
- GET    /api/files/{file_id}             下载附件
- DELETE /api/files/{file_id}             删除附件（仅空间 Owner/Admin）
- GET    /api/workspaces/{id}/files       列出空间下的附件
- GET    /api/projects/{id}/files         列出项目下的附件

权限沿空间成员关系下推：
- 空间成员可上传、可下载
- 空间 Owner/Admin 可删除
- 存量文件（无任何挂载）仅上传者本人可访问，视为 'owner' 角色

存储：Program/source/uploads/（仓库根 .gitignore 已排除）。单文件上限 20MB。
文件落盘使用服务端生成的随机文件名，展示名只用于响应与 Content-Disposition。
"""
from datetime import datetime, timezone
from pathlib import Path
import re
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Membership, Project, Task, User, Workspace
from ..models.file import File as FileModel  # 直接从子模块导入，触发 File 表注册；models/__init__.py 由 A 统一导出

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
CHUNK_SIZE = 1024 * 1024

def default_uploads_dir() -> Path:
    """Program/source/uploads/（backend/routers 往上三级）。"""
    return Path(__file__).resolve().parents[2] / 'uploads'

class FileOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    workspace_id: int | None
    project_id: int | None
    task_id: int | None
    filename: str
    mime_type: str
    size: int
    uploaded_by: int
    created_at: datetime

def build_files_router(engine, current_user, uploads_dir: Path | None = None):
    uploads = (uploads_dir or default_uploads_dir()).resolve()
    uploads.mkdir(parents=True, exist_ok=True)
    router = APIRouter(prefix='/api')

    def workspace_or_404(db, workspace_id):
        ws = db.get(Workspace, workspace_id)
        if not ws:
            raise HTTPException(404, '空间不存在')
        return ws

    def membership_or_404(db, workspace_id, user_id):
        m = db.get(Membership, (user_id, workspace_id))
        if not m:
            raise HTTPException(404, '你不是该空间的成员')
        return m

    def project_access(db, project_id, user_id):
        """取项目并校验访问权。返回 (project, my_role)。
        my_role: 'Owner'/'Admin'/'Member'（空间项目）或 'owner'（存量项目）。"""
        project = db.get(Project, project_id)
        if not project:
            raise HTTPException(404, '项目不存在或你没有访问权限')
        if project.workspace_id is not None:
            m = db.get(Membership, (user_id, project.workspace_id))
            if not m:
                raise HTTPException(404, '项目不存在或你没有访问权限')
            return project, m.role
        if project.owner_id != user_id:
            raise HTTPException(404, '项目不存在或你没有访问权限')
        return project, 'owner'

    def check_anchor(db, workspace_id, project_id, task_id, user_id):
        """校验挂载点：必须且只能挂在一个层级，且当前用户有权访问该层级。
        返回空间角色（'Owner'/'Admin'/'Member'/'owner'）。"""
        anchors = [x for x in (workspace_id, project_id, task_id) if x is not None]
        if len(anchors) != 1:
            raise HTTPException(422, '文件必须且只能挂在一个层级：空间、项目或任务')
        if workspace_id is not None:
            return membership_or_404(db, workspace_id, user_id).role
        if project_id is not None:
            _project, role = project_access(db, project_id, user_id)
            return role
        task = db.get(Task, task_id)
        if not task:
            raise HTTPException(404, '任务不存在或你没有访问权限')
        _project, role = project_access(db, task.project_id, user_id)
        return role

    def file_access(db, file_id, user_id):
        """取文件并校验访问权。返回 (file, my_role)。"""
        item = db.get(FileModel, file_id)
        if not item:
            raise HTTPException(404, '文件不存在或你没有访问权限')
        if item.workspace_id is not None:
            return item, membership_or_404(db, item.workspace_id, user_id).role
        if item.project_id is not None:
            _project, role = project_access(db, item.project_id, user_id)
            return item, role
        if item.task_id is not None:
            task = db.get(Task, item.task_id)
            if not task:
                raise HTTPException(404, '文件不存在或你没有访问权限')
            _project, role = project_access(db, task.project_id, user_id)
            return item, role
        if item.uploaded_by != user_id:
            raise HTTPException(404, '文件不存在或你没有访问权限')
        return item, 'owner'

    def require_delete(role):
        if role not in ('Owner', 'Admin', 'owner'):
            raise HTTPException(403, '只有空间 Owner 或 Admin 可以删除文件')

    def stored_path_or_500(stored):
        """把库中相对路径解析回 uploads 目录内，防止越界。"""
        path = (uploads / stored).resolve()
        if not path.is_relative_to(uploads):
            raise HTTPException(500, '文件存储路径异常')
        return path

    def clean_filename(raw):
        """清理上传文件名：去目录部分、去空白、限长。"""
        text = (raw or '').replace('\\', '/').strip()
        name = text.rsplit('/', 1)[-1].strip()
        if not name:
            raise HTTPException(422, '文件名不能为空')
        return name[:255]

    @router.post('/files', response_model=FileOutput, status_code=201)
    async def upload_file(
        file: UploadFile = File(...),
        workspace_id: int | None = Form(default=None),
        project_id: int | None = Form(default=None),
        task_id: int | None = Form(default=None),
        user: User = Depends(current_user),
    ):
        display_name = clean_filename(file.filename)
        ext = Path(display_name).suffix.lower()
        if len(ext) > 16 or not re.fullmatch(r'\.[a-z0-9]+', ext):
            ext = ''
        stored = f'{uuid.uuid4().hex}{ext}'

        with Session(engine) as db:
            check_anchor(db, workspace_id, project_id, task_id, user.id)

            size = 0
            parts: list[bytes] = []
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_FILE_SIZE:
                    raise HTTPException(413, '文件不能超过 20MB')
                parts.append(chunk)

            dest = uploads / stored
            with dest.open('wb') as fh:
                for chunk in parts:
                    fh.write(chunk)

            now = datetime.now(timezone.utc)
            item = FileModel(
                workspace_id=workspace_id,
                project_id=project_id,
                task_id=task_id,
                filename=display_name,
                stored_path=stored,
                mime_type=file.content_type or 'application/octet-stream',
                size=size,
                uploaded_by=user.id,
                created_at=now,
            )
            db.add(item)
            try:
                db.commit()
            except Exception:
                dest.unlink(missing_ok=True)
                raise
            db.refresh(item)
            return item

    @router.get('/files/{file_id}')
    def download_file(file_id: int, user: User = Depends(current_user)):
        with Session(engine) as db:
            item, _role = file_access(db, file_id, user.id)
            path = stored_path_or_500(item.stored_path)
            if not path.exists():
                raise HTTPException(404, '文件内容已丢失，请联系管理员')
            return FileResponse(path, media_type=item.mime_type, filename=item.filename)

    @router.delete('/files/{file_id}', status_code=204)
    def delete_file(file_id: int, user: User = Depends(current_user)):
        with Session(engine) as db:
            item, role = file_access(db, file_id, user.id)
            require_delete(role)
            path = stored_path_or_500(item.stored_path)
            db.delete(item)
            db.commit()
        path.unlink(missing_ok=True)
        return Response(status_code=204)

    @router.get('/workspaces/{workspace_id}/files', response_model=list[FileOutput])
    def list_workspace_files(workspace_id: int, user: User = Depends(current_user)):
        with Session(engine) as db:
            workspace_or_404(db, workspace_id)
            membership_or_404(db, workspace_id, user.id)
            return db.scalars(
                select(FileModel).where(FileModel.workspace_id == workspace_id)
                .order_by(FileModel.created_at.desc(), FileModel.id.desc())
            ).all()

    @router.get('/projects/{project_id}/files', response_model=list[FileOutput])
    def list_project_files(project_id: int, user: User = Depends(current_user)):
        with Session(engine) as db:
            project_access(db, project_id, user.id)
            return db.scalars(
                select(FileModel).where(FileModel.project_id == project_id)
                .order_by(FileModel.created_at.desc(), FileModel.id.desc())
            ).all()

    return router
