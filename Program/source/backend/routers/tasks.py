"""Task REST API router (M4). 维护人：机器 B。

接口：
- GET    /api/projects/{project_id}/tasks   列出项目下任务
- POST   /api/projects/{project_id}/tasks   在项目下建任务
- GET    /api/tasks/{task_id}               任务详情
- PATCH  /api/tasks/{task_id}               更新任务（If-Match 乐观锁，409）
- DELETE /api/tasks/{task_id}               删除任务（仅空间 Owner/Admin）

权限沿项目 → 空间 → 成员关系下推：
- 空间成员可读、可建、可改任务
- 空间 Owner/Admin 可删任务
- 指派人必须在项目所属空间内
存量项目（无空间）仅 owner 本人可操作。
"""
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Membership, Project, User
from ..models.task import Task  # 直接从子模块导入，触发 Task 表注册；models/__init__.py 由 A 统一导出

TaskStatus = Literal['Todo', 'In Progress', 'Review', 'Done']
TaskPriority = Literal['Low', 'Medium', 'High', 'Urgent']

class TaskInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=10000)
    status: TaskStatus = 'Todo'
    priority: TaskPriority = 'Medium'
    assignee_id: int | None = None
    due_date: date | None = None

class TaskPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    assignee_id: int | None = None
    due_date: date | None = None

    @field_validator('title', 'description', 'status', 'priority')
    @classmethod
    def not_null(cls, value):
        if value is None:
            raise ValueError('此字段不能为 null')
        return value

class TaskOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    title: str
    description: str
    status: str
    priority: str
    assignee_id: int | None
    creator_id: int
    due_date: date | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    version: int

def build_tasks_router(engine, current_user):
    router = APIRouter(prefix='/api')

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

    def task_access(db, task_id, user_id):
        """取任务并校验访问权。返回 (task, project, my_role)。"""
        task = db.get(Task, task_id)
        if not task:
            raise HTTPException(404, '任务不存在或你没有访问权限')
        project, role = project_access(db, task.project_id, user_id)
        return task, project, role

    def require_delete(role):
        if role not in ('Owner', 'Admin', 'owner'):
            raise HTTPException(403, '只有空间 Owner 或 Admin 可以删除任务')

    def validate_assignee(db, project, assignee_id):
        if assignee_id is None:
            return
        if project.workspace_id is None:
            raise HTTPException(422, '存量项目不能指派任务')
        if not db.get(Membership, (assignee_id, project.workspace_id)):
            raise HTTPException(422, '指派人不在该项目所属的空间内')

    def touch_completed_at(item):
        """状态流转到 Done 时记录完成时间；离开 Done 时清空。"""
        if item.status == 'Done' and item.completed_at is None:
            item.completed_at = datetime.now(timezone.utc)
        elif item.status != 'Done' and item.completed_at is not None:
            item.completed_at = None

    @router.get('/projects/{project_id}/tasks', response_model=list[TaskOutput])
    def list_tasks(project_id: int, user: User = Depends(current_user)):
        with Session(engine) as db:
            project_access(db, project_id, user.id)
            return db.scalars(
                select(Task).where(Task.project_id == project_id)
                .order_by(Task.created_at.desc(), Task.id.desc())
            ).all()

    @router.post('/projects/{project_id}/tasks', response_model=TaskOutput, status_code=201)
    def create_task(project_id: int, body: TaskInput, user: User = Depends(current_user)):
        now = datetime.now(timezone.utc)
        with Session(engine) as db:
            project, _role = project_access(db, project_id, user.id)
            validate_assignee(db, project, body.assignee_id)
            item = Task(
                project_id=project_id,
                title=body.title,
                description=body.description,
                status=body.status,
                priority=body.priority,
                assignee_id=body.assignee_id,
                creator_id=user.id,
                due_date=body.due_date,
                created_at=now,
                updated_at=now,
            )
            touch_completed_at(item)
            db.add(item)
            db.commit()
            db.refresh(item)
            return item

    @router.get('/tasks/{task_id}', response_model=TaskOutput)
    def get_task(task_id: int, user: User = Depends(current_user)):
        with Session(engine) as db:
            task, _project, _role = task_access(db, task_id, user.id)
            return task

    @router.patch('/tasks/{task_id}', response_model=TaskOutput)
    def update_task(task_id: int, body: TaskPatch, request: Request, user: User = Depends(current_user)):
        from sqlalchemy.orm.exc import StaleDataError
        with Session(engine) as db:
            task, project, _role = task_access(db, task_id, user.id)
            # 乐观锁
            expected = request.headers.get('if-match')
            if expected and expected != str(task.version):
                raise HTTPException(409, '任务已在其他页面修改，请刷新后重试')
            changes = body.model_dump(exclude_unset=True)
            if 'assignee_id' in changes:
                validate_assignee(db, project, changes['assignee_id'])
            for key, value in changes.items():
                setattr(task, key, value)
            touch_completed_at(task)
            task.updated_at = datetime.now(timezone.utc)
            try:
                db.commit()
            except StaleDataError:
                raise HTTPException(409, '任务已被修改，请刷新后重试')
            db.refresh(task)
            return task

    @router.delete('/tasks/{task_id}', status_code=204)
    def delete_task(task_id: int, request: Request, user: User = Depends(current_user)):
        from sqlalchemy.orm.exc import StaleDataError
        with Session(engine) as db:
            task, _project, role = task_access(db, task_id, user.id)
            require_delete(role)
            expected = request.headers.get('if-match')
            if expected and expected != str(task.version):
                raise HTTPException(409, '任务已在其他页面修改，请刷新后重试')
            db.delete(task)
            try:
                db.commit()
            except StaleDataError:
                raise HTTPException(409, '任务已被修改，请刷新后重试')
        return Response(status_code=204)

    return router
