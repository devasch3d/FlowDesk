"""Models package: re-exports every table so existing imports keep working.
Importing this package registers all tables on Base.metadata (required by create_all).
维护人：机器 A。其他机器新增表时新建自己的文件并在下方追加导出。"""
from .base import Base
from .user import AppSetting, LoginAttempt, LoginSession, User
from .project import Project
from .workspace import Membership, Workspace
from .task import Task
from .file import File
from .collaboration import Activity, Comment
from .ai import AiConversation, AiMessage, AiSetting

__all__ = ['Base', 'User', 'Project', 'LoginSession', 'LoginAttempt', 'AppSetting', 'Workspace', 'Membership', 'Task', 'File', 'Comment', 'Activity', 'AiConversation', 'AiMessage', 'AiSetting']
