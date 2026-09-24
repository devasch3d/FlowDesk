"""Workspace REST API router (M3). 维护人：机器 A。
权限语义：空间成员可读；Owner/Admin 可改空间、加/移除成员；Owner 可调角色。
后端做全部权限判断，前端只是展示层（沿用 M2 安全哲学）。"""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Membership, User, Workspace

Role = Literal['Owner', 'Admin', 'Member']

class WorkspaceInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default='', max_length=1000)

class WorkspacePatch(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=1000)

    @field_validator('name', 'description')
    @classmethod
    def not_null(cls, value):
        if value is None:
            raise ValueError('此字段不能为 null')
        return value

class MemberAdd(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    email: str = Field(min_length=3, max_length=254)
    role: Role = 'Member'

class MemberPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    role: Role

class MemberOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    username: str
    email: str
    role: str
    created_at: datetime

class WorkspaceOutput(BaseModel):
    id: int
    name: str
    description: str
    created_at: datetime
    updated_at: datetime
    role: str

class WorkspaceDetail(WorkspaceOutput):
    members: list[MemberOutput]

def build_workspaces_router(engine, current_user):
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

    def member_or_404(db, workspace_id, member_user_id):
        m = db.get(Membership, (member_user_id, workspace_id))
        if not m:
            raise HTTPException(404, '该成员不在空间中')
        return m

    def to_output(ws, role):
        return WorkspaceOutput(id=ws.id, name=ws.name, description=ws.description,
                               created_at=ws.created_at, updated_at=ws.updated_at, role=role)

    @router.get('/workspaces', response_model=list[WorkspaceOutput])
    def list_workspaces(user: User = Depends(current_user)):
        with Session(engine) as db:
            rows = db.execute(
                select(Workspace, Membership.role)
                .join(Membership, Membership.workspace_id == Workspace.id)
                .where(Membership.user_id == user.id)
                .order_by(Workspace.updated_at.desc(), Workspace.id.desc())
            ).all()
            return [to_output(ws, role) for ws, role in rows]

    @router.post('/workspaces', response_model=WorkspaceOutput, status_code=201)
    def create_workspace(body: WorkspaceInput, user: User = Depends(current_user)):
        now = datetime.now(timezone.utc)
        with Session(engine) as db:
            ws = Workspace(name=body.name, description=body.description, created_at=now, updated_at=now)
            db.add(ws)
            db.flush()
            db.add(Membership(user_id=user.id, workspace_id=ws.id, role='Owner', created_at=now))
            db.commit()
            db.refresh(ws)
            return to_output(ws, 'Owner')

    @router.get('/workspaces/{workspace_id}', response_model=WorkspaceDetail)
    def get_workspace(workspace_id: int, user: User = Depends(current_user)):
        with Session(engine) as db:
            ws = workspace_or_404(db, workspace_id)
            my = membership_or_404(db, workspace_id, user.id)
            members = db.execute(
                select(User, Membership.role, Membership.created_at)
                .join(Membership, Membership.user_id == User.id)
                .where(Membership.workspace_id == workspace_id)
                .order_by(User.id)
            ).all()
            return WorkspaceDetail(
                id=ws.id, name=ws.name, description=ws.description,
                created_at=ws.created_at, updated_at=ws.updated_at, role=my.role,
                members=[MemberOutput(user_id=u.id, username=u.username, email=u.email,
                                      role=role, created_at=created) for u, role, created in members],
            )

    @router.patch('/workspaces/{workspace_id}', response_model=WorkspaceOutput)
    def update_workspace(workspace_id: int, body: WorkspacePatch, user: User = Depends(current_user)):
        with Session(engine) as db:
            ws = workspace_or_404(db, workspace_id)
            my = membership_or_404(db, workspace_id, user.id)
            if my.role not in ('Owner', 'Admin'):
                raise HTTPException(403, '只有空间 Owner 或 Admin 可以修改空间')
            changes = body.model_dump(exclude_unset=True)
            for key, value in changes.items():
                setattr(ws, key, value)
            ws.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(ws)
            return to_output(ws, my.role)

    @router.post('/workspaces/{workspace_id}/members', response_model=MemberOutput, status_code=201)
    def add_member(workspace_id: int, body: MemberAdd, user: User = Depends(current_user)):
        with Session(engine) as db:
            workspace_or_404(db, workspace_id)
            my = membership_or_404(db, workspace_id, user.id)
            if my.role not in ('Owner', 'Admin'):
                raise HTTPException(403, '只有空间 Owner 或 Admin 可以添加成员')
            target = db.scalar(select(User).where(User.email == body.email.strip().casefold()))
            if not target:
                raise HTTPException(404, '没有找到该邮箱对应的账号')
            if db.get(Membership, (target.id, workspace_id)):
                raise HTTPException(409, '该成员已在空间中')
            m = Membership(user_id=target.id, workspace_id=workspace_id, role=body.role,
                           created_at=datetime.now(timezone.utc))
            db.add(m)
            db.commit()
            db.refresh(m)
            return MemberOutput(user_id=target.id, username=target.username, email=target.email,
                                role=m.role, created_at=m.created_at)

    @router.patch('/workspaces/{workspace_id}/members/{member_user_id}', response_model=MemberOutput)
    def update_member(workspace_id: int, member_user_id: int, body: MemberPatch,
                      user: User = Depends(current_user)):
        with Session(engine) as db:
            workspace_or_404(db, workspace_id)
            my = membership_or_404(db, workspace_id, user.id)
            if my.role != 'Owner':
                raise HTTPException(403, '只有空间 Owner 可以调整成员角色')
            m = member_or_404(db, workspace_id, member_user_id)
            if m.role == 'Owner' and body.role != 'Owner':
                raise HTTPException(400, '不能降级空间 Owner')
            m.role = body.role
            db.commit()
            db.refresh(m)
            target = db.get(User, member_user_id)
            return MemberOutput(user_id=target.id, username=target.username, email=target.email,
                                role=m.role, created_at=m.created_at)

    @router.delete('/workspaces/{workspace_id}/members/{member_user_id}', status_code=204)
    def remove_member(workspace_id: int, member_user_id: int, user: User = Depends(current_user)):
        with Session(engine) as db:
            workspace_or_404(db, workspace_id)
            my = membership_or_404(db, workspace_id, user.id)
            if my.role not in ('Owner', 'Admin'):
                raise HTTPException(403, '只有空间 Owner 或 Admin 可以移除成员')
            m = member_or_404(db, workspace_id, member_user_id)
            if m.role == 'Owner':
                raise HTTPException(400, '不能移除空间 Owner')
            db.delete(m)
            db.commit()
        return Response(status_code=204)

    return router
