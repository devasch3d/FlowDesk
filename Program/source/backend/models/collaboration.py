"""Comment and Activity tables (M7). 维护人：机器 E。

评论挂在任务下（任务 → 项目 → 空间），权限沿空间成员关系下推：
空间成员可读可评论；评论作者本人可改删，空间 Owner/Admin 可删任意评论。

活动流记录空间内的重要动作（created / status_changed / commented /
file_uploaded …）。M7 先落地信息流与「commented」事件的写入；
任务创建/状态变更等事件的写入由任务模块侧（机器 B）后续接入，
或由 A 合入时代补，接口与表结构在此预留。
"""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

class Comment(Base):
    __tablename__ = 'comments'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey('tasks.id', ondelete='CASCADE'), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class Activity(Base):
    __tablename__ = 'activities'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey('workspaces.id', ondelete='CASCADE'), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    action: Mapped[str] = mapped_column(String(32))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
