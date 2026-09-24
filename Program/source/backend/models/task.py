"""Task table (M4). 维护人：机器 B。

任务归属于项目，项目归属于空间。权限沿空间成员关系下推：
- 空间成员可读、可建任务
- 空间 Owner/Admin 可删任务
- 指派人必须在项目所属空间内
PATCH 沿用 version 乐观锁（If-Match / 409）。
"""
from datetime import date, datetime
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base

class Task(Base):
    __tablename__ = 'tasks'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(String(20), default='Todo')
    priority: Mapped[str] = mapped_column(String(16), default='Medium')
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True, index=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {'version_id_col': version}
