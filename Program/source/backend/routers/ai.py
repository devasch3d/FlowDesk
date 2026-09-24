"""AI Copilot REST API router (M8). 维护人：机器 F。

接口（前缀 /api）：
- GET    /api/ai/conversations            会话列表（本人；可选 ?workspace_id= / ?project_id= 过滤）
- POST   /api/ai/conversations            创建会话
- GET    /api/ai/conversations/{id}       会话详情 + 消息数组（正序）
- DELETE /api/ai/conversations/{id}       删除会话（级联删消息），204
- POST   /api/ai/conversations/{id}/messages   发送消息（调用 LLM，失败不抛 5xx）
- POST   /api/ai/conversations/{id}/proposals  任务提案（LLM 生成 JSON，不落库）
- GET    /api/ai/settings                 读取 LLM 设置（Key 掩码）
- PUT    /api/ai/settings                 更新 LLM 设置

LLM 接入：httpx 同步调用 OpenAI 兼容 /chat/completions，封装为独立函数 call_llm，
便于测试 monkeypatch。禁止真实外部调用由测试层约束。
"""
from datetime import datetime, timezone
import json
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Membership, Project, Task, User, Workspace
from ..models.ai import AiConversation, AiMessage, AiSetting  # 直接从子模块导入，触发表注册；models/__init__.py 由 A 统一导出

DEFAULT_BASE_URL = 'https://api.openai.com/v1'
DEFAULT_MODEL = 'gpt-4o-mini'
HISTORY_LIMIT = 20
CONTEXT_TASK_LIMIT = 50

TaskStatus = Literal['Todo', 'In Progress', 'Review', 'Done']
TaskPriority = Literal['Low', 'Medium', 'High', 'Urgent']
VALID_STATUSES = ('Todo', 'In Progress', 'Review', 'Done')
VALID_PRIORITIES = ('Low', 'Medium', 'High', 'Urgent')


# ---------------------------------------------------------------- LLM 封装

def call_llm(settings, messages, system_prompt, json_mode=False) -> str:
    """调用 OpenAI 兼容 /chat/completions，返回回答文本。

    settings: AiSetting（含 base_url / model / api_key）
    messages: [{role, content}, ...] 会话历史（不含 system）
    json_mode: 提案接口传 True，附加 response_format 要求 JSON 对象
    """
    base_url = (settings.base_url or DEFAULT_BASE_URL).rstrip('/')
    payload = {
        'model': settings.model or DEFAULT_MODEL,
        'messages': [{'role': 'system', 'content': system_prompt}]
                    + [{'role': m['role'], 'content': m['content']} for m in messages],
        'temperature': 0.3,
    }
    if json_mode:
        payload['response_format'] = {'type': 'json_object'}
    with httpx.Client(timeout=60) as client:
        response = client.post(
            f'{base_url}/chat/completions',
            headers={'Authorization': f'Bearer {settings.api_key}'},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    return data['choices'][0]['message']['content']


# ---------------------------------------------------------------- 出入参模型

class ConversationInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    workspace_id: int | None = None
    project_id: int | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)


class ConversationOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    workspace_id: int | None
    project_id: int | None
    title: str
    created_at: datetime
    updated_at: datetime


class AiMessageOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    conversation_id: int
    role: str
    content: str
    created_at: datetime


class ConversationDetail(ConversationOutput):
    messages: list[AiMessageOutput] = []


class MessageInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    content: str = Field(min_length=1, max_length=10000)


class MessageResponse(BaseModel):
    user_message: AiMessageOutput
    assistant_message: AiMessageOutput | None = None
    reply_error: str | None = None


class ProposalInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    instruction: str = Field(min_length=1, max_length=2000)
    project_id: int


class ProposalOutput(BaseModel):
    title: str
    description: str
    priority: str
    status: str
    due_date: str | None


class ProposalResponse(BaseModel):
    proposals: list[ProposalOutput] = []
    skipped: int = 0
    reply_error: str | None = None


class SettingInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    provider: str | None = Field(default=None, max_length=32)
    base_url: str | None = Field(default=None, max_length=255)
    model: str | None = Field(default=None, max_length=128)
    api_key: str | None = Field(default=None, max_length=255)
    enabled: bool | None = None


class SettingOutput(BaseModel):
    provider: str
    base_url: str
    model: str
    enabled: bool
    api_key_masked: str


# ---------------------------------------------------------------- 工厂

def build_ai_router(engine, current_user):
    router = APIRouter(prefix='/api')

    def conversation_or_404(db, conversation_id, user_id):
        """取会话并校验归属（仅创建者本人可见）。"""
        conv = db.get(AiConversation, conversation_id)
        if not conv or conv.user_id != user_id:
            raise HTTPException(404, '会话不存在或你没有访问权限')
        return conv

    def project_access(db, project_id, user_id):
        """取项目并校验访问权（空间成员或存量 owner 双轨，参照 tasks.py）。"""
        project = db.get(Project, project_id)
        if not project:
            raise HTTPException(404, '项目不存在或你没有访问权限')
        if project.workspace_id is not None:
            m = db.get(Membership, (user_id, project.workspace_id))
            if not m:
                raise HTTPException(404, '项目不存在或你没有访问权限')
            return project
        if project.owner_id != user_id:
            raise HTTPException(404, '项目不存在或你没有访问权限')
        return project

    def require_setting(db, user_id):
        """读取当前用户的 AI 设置；未启用返回 None（调用方按 409 处理）。"""
        setting = db.get(AiSetting, user_id)
        if not setting or not setting.enabled or not (setting.api_key or '').strip():
            raise HTTPException(409, '请先在 AI 设置中配置 API Key 并启用')
        return setting

    def recent_history(db, conversation_id, exclude_id=None):
        """最近 HISTORY_LIMIT 条历史消息（created_at 正序，供 LLM 上下文）。"""
        query = select(AiMessage).where(AiMessage.conversation_id == conversation_id)
        if exclude_id is not None:
            query = query.where(AiMessage.id != exclude_id)
        rows = db.scalars(query.order_by(AiMessage.created_at.desc(), AiMessage.id.desc()).limit(HISTORY_LIMIT)).all()
        rows.reverse()
        return [{'role': m.role, 'content': m.content} for m in rows]

    def task_context(db, conv):
        """把会话挂载的 workspace/project 的任务摘要拼入提示（标题+状态+优先级+负责人，最多 50 条）。"""
        if conv.project_id is not None:
            rows = db.scalars(
                select(Task).where(Task.project_id == conv.project_id)
                .order_by(Task.created_at.desc(), Task.id.desc()).limit(CONTEXT_TASK_LIMIT)
            ).all()
        elif conv.workspace_id is not None:
            pids = db.scalars(select(Project.id).where(Project.workspace_id == conv.workspace_id)).all()
            if not pids:
                return ''
            rows = db.scalars(
                select(Task).where(Task.project_id.in_(pids))
                .order_by(Task.created_at.desc(), Task.id.desc()).limit(CONTEXT_TASK_LIMIT)
            ).all()
        else:
            return ''
        if not rows:
            return ''
        assignee_ids = {t.assignee_id for t in rows if t.assignee_id}
        names = {}
        if assignee_ids:
            names = {u.id: u.username for u in db.scalars(select(User).where(User.id.in_(assignee_ids)))}
        lines = [
            f"- {t.title} | 状态:{t.status} | 优先级:{t.priority} | 负责人:{names.get(t.assignee_id, '未指派')}"
            for t in rows
        ]
        return '\n'.join(lines)

    def base_system_prompt(db, conv):
        prompt = ('你是 FlowDesk 的 AI 助手，帮助用户管理工作空间、项目与任务。'
                  '请使用简洁的中文纯文本回答，不使用 Markdown 表格或代码块。')
        context = task_context(db, conv)
        if context:
            prompt += '\n\n以下是当前项目/空间的任务概况（供回答项目进展、总结类问题时参考）：\n' + context
        return prompt

    def parse_proposals(raw):
        """解析 LLM 返回的提案 JSON 列表。

        完全不可解析（非 JSON / 非数组）返回 None（触发重试）；
        可解析但部分条目非法 → 丢弃非法条目并计数，返回 (proposals, skipped)。
        """
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if not isinstance(parsed, list):
            return None
        proposals, skipped = [], 0
        for item in parsed:
            if not isinstance(item, dict):
                skipped += 1
                continue
            title = item.get('title')
            if not isinstance(title, str) or not title.strip() or len(title) > 200:
                skipped += 1
                continue
            description = item.get('description')
            description = description if isinstance(description, str) else ''
            priority = item.get('priority') or 'Medium'
            if priority not in VALID_PRIORITIES:
                skipped += 1
                continue
            status = item.get('status') or 'Todo'
            if status not in VALID_STATUSES:
                skipped += 1
                continue
            due_date = item.get('due_date')
            if due_date is not None:
                if not isinstance(due_date, str):
                    skipped += 1
                    continue
                try:
                    datetime.fromisoformat(due_date)
                except ValueError:
                    skipped += 1
                    continue
            proposals.append(ProposalOutput(
                title=title.strip()[:200],
                description=description[:10000],
                priority=priority,
                status=status,
                due_date=due_date,
            ))
        return proposals, skipped

    def setting_output(setting):
        key = setting.api_key or ''
        if not key:
            masked = ''
        elif len(key) <= 8:
            masked = '***'
        else:
            masked = key[:3] + '...' + key[-4:]
        return SettingOutput(
            provider=setting.provider,
            base_url=setting.base_url,
            model=setting.model,
            enabled=setting.enabled,
            api_key_masked=masked,
        )

    # ---- 会话 CRUD ----

    @router.get('/ai/conversations', response_model=list[ConversationOutput])
    def list_conversations(
        workspace_id: int | None = None,
        project_id: int | None = None,
        user: User = Depends(current_user),
    ):
        with Session(engine) as db:
            query = select(AiConversation).where(AiConversation.user_id == user.id)
            if workspace_id is not None:
                query = query.where(AiConversation.workspace_id == workspace_id)
            if project_id is not None:
                query = query.where(AiConversation.project_id == project_id)
            return db.scalars(query.order_by(AiConversation.created_at.desc(), AiConversation.id.desc())).all()

    @router.post('/ai/conversations', response_model=ConversationOutput, status_code=201)
    def create_conversation(body: ConversationInput, user: User = Depends(current_user)):
        now = datetime.now(timezone.utc)
        with Session(engine) as db:
            if body.workspace_id is not None and not db.get(Workspace, body.workspace_id):
                raise HTTPException(404, '空间不存在')
            if body.project_id is not None and not db.get(Project, body.project_id):
                raise HTTPException(404, '项目不存在或你没有访问权限')
            conv = AiConversation(
                user_id=user.id,
                workspace_id=body.workspace_id,
                project_id=body.project_id,
                title=body.title or '新会话',
                created_at=now,
                updated_at=now,
            )
            db.add(conv)
            db.commit()
            db.refresh(conv)
            return conv

    @router.get('/ai/conversations/{conversation_id}', response_model=ConversationDetail)
    def get_conversation(conversation_id: int, user: User = Depends(current_user)):
        with Session(engine) as db:
            conv = conversation_or_404(db, conversation_id, user.id)
            messages = db.scalars(
                select(AiMessage).where(AiMessage.conversation_id == conv.id)
                .order_by(AiMessage.created_at.asc(), AiMessage.id.asc())
            ).all()
            return ConversationDetail(
                id=conv.id, user_id=conv.user_id, workspace_id=conv.workspace_id,
                project_id=conv.project_id, title=conv.title,
                created_at=conv.created_at, updated_at=conv.updated_at,
                messages=messages,
            )

    @router.delete('/ai/conversations/{conversation_id}', status_code=204)
    def delete_conversation(conversation_id: int, user: User = Depends(current_user)):
        with Session(engine) as db:
            conv = conversation_or_404(db, conversation_id, user.id)
            db.delete(conv)
            db.commit()
        return Response(status_code=204)

    # ---- 发送消息（核心） ----

    @router.post('/ai/conversations/{conversation_id}/messages', response_model=MessageResponse)
    def send_message(conversation_id: int, body: MessageInput, user: User = Depends(current_user)):
        now = datetime.now(timezone.utc)
        with Session(engine) as db:
            conv = conversation_or_404(db, conversation_id, user.id)
            user_msg = AiMessage(conversation_id=conv.id, role='user', content=body.content, created_at=now)
            db.add(user_msg)
            db.commit()
            db.refresh(user_msg)

            setting = require_setting(db, user.id)  # 未启用 → 409（user 消息已存）
            history = recent_history(db, conv.id, exclude_id=user_msg.id)
            history.append({'role': 'user', 'content': body.content})
            system = base_system_prompt(db, conv)
            try:
                reply = call_llm(setting, history, system)
            except httpx.HTTPError as exc:
                conv.updated_at = now
                db.commit()
                return MessageResponse(user_message=user_msg, assistant_message=None,
                                       reply_error=f'AI 服务调用失败：{exc}')
            except Exception as exc:
                conv.updated_at = now
                db.commit()
                return MessageResponse(user_message=user_msg, assistant_message=None,
                                       reply_error=f'AI 服务调用失败：{exc}')

            assistant_msg = AiMessage(conversation_id=conv.id, role='assistant', content=reply, created_at=now)
            db.add(assistant_msg)
            conv.updated_at = now
            db.commit()
            db.refresh(assistant_msg)
            return MessageResponse(user_message=user_msg, assistant_message=assistant_msg)

    # ---- 任务提案（"经确认执行"，不落库） ----

    @router.post('/ai/conversations/{conversation_id}/proposals', response_model=ProposalResponse)
    def propose_tasks(conversation_id: int, body: ProposalInput, user: User = Depends(current_user)):
        with Session(engine) as db:
            conv = conversation_or_404(db, conversation_id, user.id)
            project_access(db, body.project_id, user.id)
            setting = require_setting(db, user.id)
            history = recent_history(db, conv.id)
            system = (
                '你是 FlowDesk 的任务拆解助手。根据用户指令，把目标拆解为任务提案，'
                '只返回一个 JSON 数组，每个元素形如 '
                '{"title": "任务标题(1-200字)", "description": "可选描述", '
                '"priority": "Low|Medium|High|Urgent", "status": "Todo|In Progress|Review|Done", "due_date": "YYYY-MM-DD 或 null"}。'
                '不要输出任何 JSON 以外的内容。'
            )
            for _attempt in range(2):
                try:
                    raw = call_llm(setting, history, system, json_mode=True)
                except httpx.HTTPError as exc:
                    return ProposalResponse(proposals=[], skipped=0,
                                            reply_error=f'AI 服务调用失败：{exc}')
                except Exception as exc:
                    return ProposalResponse(proposals=[], skipped=0,
                                            reply_error=f'AI 服务调用失败：{exc}')
                parsed = parse_proposals(raw)
                if parsed is not None:
                    proposals, skipped = parsed
                    return ProposalResponse(proposals=proposals, skipped=skipped)
                # 完全不可解析 → 重试 1 次
            return ProposalResponse(proposals=[], skipped=0,
                                    reply_error='AI 返回格式无法解析，请重试')

    # ---- 设置 ----

    @router.get('/ai/settings', response_model=SettingOutput)
    def get_settings(user: User = Depends(current_user)):
        with Session(engine) as db:
            setting = db.get(AiSetting, user.id)
            if not setting:
                return SettingOutput(
                    provider='openai_compatible', base_url=DEFAULT_BASE_URL,
                    model=DEFAULT_MODEL, enabled=False, api_key_masked='',
                )
            return setting_output(setting)

    @router.put('/ai/settings', response_model=SettingOutput)
    def update_settings(body: SettingInput, user: User = Depends(current_user)):
        now = datetime.now(timezone.utc)
        with Session(engine) as db:
            setting = db.get(AiSetting, user.id)
            if not setting:
                setting = AiSetting(user_id=user.id, updated_at=now)
                db.add(setting)
            data = body.model_dump(exclude_unset=True)
            for key, value in data.items():
                if key == 'api_key':
                    if value is not None and value.strip():
                        setting.api_key = value.strip()
                    # 为空/缺省 = 保留原值
                else:
                    setattr(setting, key, value)
            if setting.enabled and not (setting.api_key or '').strip():
                raise HTTPException(422, '请先填写 API Key')
            setting.updated_at = now
            db.commit()
            db.refresh(setting)
            return setting_output(setting)

    return router
