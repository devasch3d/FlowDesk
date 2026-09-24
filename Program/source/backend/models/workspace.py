"""Workspace and membership tables (many-to-many via memberships).
维护人：机器 A。Workspace 是 Project/Task/Files/Dashboard 的地基。
memberships 用复合主键 (user_id, workspace_id)：一个人在一个空间只有一条记录。"""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base

class Workspace(Base):
    __tablename__ = 'workspaces'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class Membership(Base):
    __tablename__ = 'memberships'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True, index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey('workspaces.id'), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(16), default='Member')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
