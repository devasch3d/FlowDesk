"""Project table. Owned by machine B (Project 挂入 Workspace 改造后由 B 维护本文件).

M4 改造：新增 workspace_id 外键（可空），兼容 M1/M2 无空间时期的存量项目。
- workspace_id 非空时：权限按空间成员关系判定
- workspace_id 为空时：退化为 owner_id 归属，仅 owner 本人可见可改（旧版兼容）
"""
from datetime import date, datetime
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base

class Project(Base):
    __tablename__ = 'projects'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey('workspaces.id'), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(String(20), default='Planning')
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {'version_id_col': version}
