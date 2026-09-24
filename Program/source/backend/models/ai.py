"""AI Copilot tables (M8). 维护人：机器 F。

三张表：
- AiConversation：AI 会话，仅创建者本人可见；可选挂载 workspace/project 作为上下文标签。
- AiMessage：会话内的消息（user / assistant），随会话级联删除。
- AiSetting：每用户一条的 LLM 接入配置（密钥仅存本机 DB，不回传前端）。
"""
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class AiConversation(Base):
    __tablename__ = 'ai_conversations'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)  # 会话仅创建者本人可见
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey('workspaces.id'), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey('projects.id'), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200), default='新会话')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AiMessage(Base):
    __tablename__ = 'ai_messages'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey('ai_conversations.id', ondelete='CASCADE'), index=True)
    role: Mapped[str] = mapped_column(String(16))  # 'user' | 'assistant'
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AiSetting(Base):
    __tablename__ = 'ai_settings'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)  # 每用户一条
    provider: Mapped[str] = mapped_column(String(32), default='openai_compatible')
    base_url: Mapped[str] = mapped_column(String(255), default='https://api.openai.com/v1')
    model: Mapped[str] = mapped_column(String(128), default='gpt-4o-mini')
    api_key: Mapped[str] = mapped_column(String(255), default='')
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
