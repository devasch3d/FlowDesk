"""File table (M5). 维护人：机器 C。

附件可归属工作空间、项目或任务三个层级（三个外键均可空）：
- workspace_id 非空：文件挂在空间下，权限按空间成员关系判定
- project_id 非空：文件挂在项目下，权限沿项目 → 空间成员关系下推
- task_id 非空：文件挂在任务下，权限沿任务 → 项目 → 空间成员关系下推
- 三者都为空：存量/直传兼容场景，仅上传者本人可访问

物理文件存放在 Program/source/uploads/（已在仓库根 .gitignore 排除），
stored_path 只保存相对于 uploads 目录的文件名，不暴露服务器绝对路径。
"""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base

class File(Base):
    __tablename__ = 'files'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey('workspaces.id'), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey('projects.id'), nullable=True, index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey('tasks.id'), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(1024))
    mime_type: Mapped[str] = mapped_column(String(128))
    size: Mapped[int] = mapped_column(Integer)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
