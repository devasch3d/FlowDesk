"""Collaboration REST API router (M7). 维护人：机器 E。

接口：
- GET    /api/tasks/{task_id}/comments      列出任务下的评论（按时间正序）
- POST   /api/tasks/{task_id}/comments      在任务下发表评论（同时写入活动流）
- PATCH  /api/comments/{id}                 修改评论（仅作者本人）
- DELETE /api/comments/{id}                 删除评论（作者本人；空间 Owner/Admin 可删任意）
- GET    /api/workspaces/{id}/activities    空间活动流（时间倒序、limit/offset 分页）

权限沿任务 → 项目 → 空间成员关系下推：
- 空间成员可读、可评论；存量项目（无空间）仅 owner 本人可操作
- 评论归属校验：作者本人可改删；空间 Owner/Admin（存量项目 owner）可删任意评论
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Membership, Project, User, Workspace
from ..models.collaboration import Activity, Comment  # 直接子模块导入，触发两张表注册
from ..models.task import Task

class CommentInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    body: str = Field(min_length=1, max_length=10000)

class CommentPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    body: str = Field(min_length=1, max_length=10000)

class CommentOutput(BaseModel):
    id: int
    task_id: int
    author_id: int
    author_username: str
    body: str
    created_at: datetime
    updated_at: datetime

class ActivityOutput(BaseModel):
    id: int
    workspace_id: int
    actor_id: int
    actor_username: str
    action: str
    target_type: str
    target_id: int
    created_at: datetime

def build_collaboration_router(engine, current_user):
    router = APIRouter(prefix='/api')

    def task_and_role(db, task_id, user_id):
        """取任务并校验访问权。返回 (task, project, my_role)。
        my_role: 'Owner'/'Admin'/'Member'（空间项目）或 'owner'（存量项目）。"""
        task = db.get(Task, task_id)
        if not task:
            raise HTTPException(404, '任务不存在或你没有访问权限')
        project = db.get(Project, task.project_id)
        if project is None:
            raise HTTPException(404, '任务不存在或你没有访问权限')
        if project.workspace_id is not None:
            m = db.get(Membership, (user_id, project.workspace_id))
            if not m:
                raise HTTPException(404, '任务不存在或你没有访问权限')
            return task, project, m.role
        if project.owner_id != user_id:
            raise HTTPException(404, '任务不存在或你没有访问权限')
        return task, project, 'owner'

    def comment_and_role(db, comment_id, user_id):
        """取评论并校验访问权（沿任务所属项目/空间）。返回 (comment, role)。"""
        comment = db.get(Comment, comment_id)
        if not comment:
            raise HTTPException(404, '评论不存在或你没有访问权限')
        _task, _project, role = task_and_role(db, comment.task_id, user_id)
        return comment, role

    def comment_output(db, comment):
        author = db.get(User, comment.author_id)
        return CommentOutput(
            id=comment.id,
            task_id=comment.task_id,
            author_id=comment.author_id,
            author_username=author.username if author else '',
            body=comment.body,
            created_at=comment.created_at,
            updated_at=comment.updated_at,
        )

    def record_activity(db, workspace_id, actor_id, action, target_type, target_id, now):
        """写入活动流；存量项目没有空间，跳过。"""
        if workspace_id is None:
            return
        db.add(Activity(workspace_id=workspace_id, actor_id=actor_id, action=action,
                        target_type=target_type, target_id=target_id, created_at=now))

    @router.get('/tasks/{task_id}/comments', response_model=list[CommentOutput])
    def list_comments(task_id: int, user: User = Depends(current_user)):
        with Session(engine) as db:
            task_and_role(db, task_id, user.id)
            comments = db.scalars(
                select(Comment).where(Comment.task_id == task_id)
                .order_by(Comment.created_at.asc(), Comment.id.asc())
            ).all()
            return [comment_output(db, c) for c in comments]

    @router.post('/tasks/{task_id}/comments', response_model=CommentOutput, status_code=201)
    def create_comment(task_id: int, body: CommentInput, user: User = Depends(current_user)):
        now = datetime.now(timezone.utc)
        with Session(engine) as db:
            _task, project, _role = task_and_role(db, task_id, user.id)
            comment = Comment(task_id=task_id, author_id=user.id, body=body.body,
                              created_at=now, updated_at=now)
            db.add(comment)
            record_activity(db, project.workspace_id, user.id, 'commented', 'task', task_id, now)
            db.commit()
            db.refresh(comment)
            return comment_output(db, comment)

    @router.patch('/comments/{comment_id}', response_model=CommentOutput)
    def update_comment(comment_id: int, body: CommentPatch, user: User = Depends(current_user)):
        with Session(engine) as db:
            comment, _role = comment_and_role(db, comment_id, user.id)
            if comment.author_id != user.id:
                raise HTTPException(403, '只有评论作者可以修改评论')
            comment.body = body.body
            comment.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(comment)
            return comment_output(db, comment)

    @router.delete('/comments/{comment_id}', status_code=204)
    def delete_comment(comment_id: int, user: User = Depends(current_user)):
        with Session(engine) as db:
            comment, role = comment_and_role(db, comment_id, user.id)
            if comment.author_id != user.id and role not in ('Owner', 'Admin', 'owner'):
                raise HTTPException(403, '只有评论作者或空间 Owner/Admin 可以删除评论')
            db.delete(comment)
            db.commit()
        return Response(status_code=204)

    @router.get('/workspaces/{workspace_id}/activities', response_model=list[ActivityOutput])
    def list_activities(workspace_id: int,
                        limit: int = Query(30, ge=1, le=100),
                        offset: int = Query(0, ge=0),
                        user: User = Depends(current_user)):
        with Session(engine) as db:
            ws = db.get(Workspace, workspace_id)
            if not ws:
                raise HTTPException(404, '空间不存在')
            if not db.get(Membership, (user.id, workspace_id)):
                raise HTTPException(404, '你不是该空间的成员')
            rows = db.execute(
                select(Activity, User.username)
                .join(User, User.id == Activity.actor_id)
                .where(Activity.workspace_id == workspace_id)
                .order_by(Activity.created_at.desc(), Activity.id.desc())
                .limit(limit).offset(offset)
            ).all()
            return [ActivityOutput(
                id=a.id, workspace_id=a.workspace_id, actor_id=a.actor_id,
                actor_username=username, action=a.action, target_type=a.target_type,
                target_id=a.target_id, created_at=a.created_at,
            ) for a, username in rows]

    return router
