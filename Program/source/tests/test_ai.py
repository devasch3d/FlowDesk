"""M8 AI Copilot tests (机器 F).

样板沿用：create_app + TestClient + X-FlowDesk-Token；fixture 结尾 engine.dispose()。
由于 app.py 尚未挂载 AI 路由（由 A 代补合入时处理），测试内通过 mount_ai() 挂载
build_ai_router，并复用与 install_auth 一致的会话认证依赖。
所有 LLM 路径一律 monkeypatch call_llm，禁止真实调用外部 API。
"""
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app import create_app
from backend.models import LoginSession, User
from backend.routers.ai import build_ai_router
from backend.security import token_digest

PASSWORD = 'test-password-123'


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def mount_ai(app):
    """AI 路由在测试内挂载；认证依赖与 install_auth 行为一致（cookie → session → user）。"""
    engine = app.state.engine
    cookie_name = app.state.cookie_name

    def current_user(request: Request):
        raw = request.cookies.get(cookie_name)
        if not raw or len(raw) > 128:
            raise HTTPException(401, '请先登录 FlowDesk')
        with Session(engine) as db:
            session = db.get(LoginSession, token_digest(raw))
            if not session or aware(session.expires_at) <= datetime.now(timezone.utc):
                raise HTTPException(401, '登录已过期，请重新登录')
            user = db.get(User, session.user_id)
            if not user:
                raise HTTPException(401, '请重新登录')
            expected = request.headers.get('x-flowdesk-user')
            if expected and expected != str(user.id):
                raise HTTPException(409, '账号已在其他页面切换，请刷新后重试')
            return user

    app.include_router(build_ai_router(engine, current_user))
    return app


def login(c, email):
    assert c.post('/api/auth/login', json={'email': email, 'password': PASSWORD}).status_code == 200


@pytest.fixture
def env(tmp_path):
    """Alice（空间 Owner）+ Bob（Member）+ Charlie（外部）+ 一个空间 + 一个项目。"""
    app = mount_ai(create_app('sqlite:///' + str(tmp_path / 'ai.db'), token='t'))
    with TestClient(app, headers={'X-FlowDesk-Token': 't'}) as c:
        ids = {}
        for name, email in [('Alice', 'alice@ex.com'), ('Bob', 'bob@ex.com'), ('Charlie', 'charlie@ex.com')]:
            r = c.post('/api/auth/register', json={'username': name, 'email': email, 'password': PASSWORD})
            assert r.status_code == 201
            ids[name.lower()] = r.json()['id']
        login(c, 'alice@ex.com')
        wid = c.post('/api/workspaces', json={'name': 'Team'}).json()['id']
        c.post(f'/api/workspaces/{wid}/members', json={'email': 'bob@ex.com'})
        pid = c.post('/api/projects', json={'workspace_id': wid, 'name': 'Proj'}).json()['id']
        yield c, ids, wid, pid
    app.state.engine.dispose()


# ---------- 会话 CRUD + 归属隔离 ----------

def test_conversation_crud_and_ownership(env):
    c, ids, wid, pid = env
    r = c.post('/api/ai/conversations', json={'title': 'T1'})
    assert r.status_code == 201
    conv = r.json()
    assert conv['title'] == 'T1' and conv['user_id'] == ids['alice']
    assert conv['workspace_id'] is None and conv['project_id'] is None

    assert len(c.get('/api/ai/conversations').json()) == 1
    assert c.get(f"/api/ai/conversations/{conv['id']}").json()['messages'] == []

    # 上下文过滤：创建带 workspace/project 的会话后可按参数过滤
    r2 = c.post('/api/ai/conversations', json={'workspace_id': wid, 'project_id': pid})
    assert r2.status_code == 201
    assert len(c.get('/api/ai/conversations', params={'workspace_id': wid}).json()) == 1
    assert len(c.get('/api/ai/conversations', params={'project_id': pid}).json()) == 1
    assert len(c.get('/api/ai/conversations').json()) == 2
    # 不存在的空间/项目 → 404
    assert c.post('/api/ai/conversations', json={'workspace_id': 99999}).status_code == 404
    assert c.post('/api/ai/conversations', json={'project_id': 99999}).status_code == 404

    # 归属隔离：他人会话全部 404
    login(c, 'bob@ex.com')
    assert c.get(f"/api/ai/conversations/{conv['id']}").status_code == 404
    assert c.delete(f"/api/ai/conversations/{conv['id']}").status_code == 404
    assert c.post(f"/api/ai/conversations/{conv['id']}/messages", json={'content': 'hi'}).status_code == 404

    # 本人删除 → 204，级联删除后详情 404
    login(c, 'alice@ex.com')
    assert c.delete(f"/api/ai/conversations/{conv['id']}").status_code == 204
    assert c.get(f"/api/ai/conversations/{conv['id']}").status_code == 404


# ---------- 消息存取（mock call_llm） ----------

def test_message_flow_stores_pair(env, monkeypatch):
    c, ids, wid, pid = env
    c.put('/api/ai/settings', json={'api_key': 'sk-x', 'enabled': True})
    conv = c.post('/api/ai/conversations', json={'project_id': pid, 'title': 'Chat'}).json()

    calls = []

    def fake_llm(settings, messages, system_prompt, json_mode=False):
        calls.append({'messages': messages, 'system': system_prompt, 'json_mode': json_mode})
        return 'AI 回答内容'

    monkeypatch.setattr('backend.routers.ai.call_llm', fake_llm)

    r = c.post(f"/api/ai/conversations/{conv['id']}/messages", json={'content': '项目进展如何？'})
    assert r.status_code == 200
    data = r.json()
    assert data['user_message']['role'] == 'user' and data['user_message']['content'] == '项目进展如何？'
    assert data['assistant_message']['role'] == 'assistant' and data['assistant_message']['content'] == 'AI 回答内容'
    assert data['reply_error'] is None

    d = c.get(f"/api/ai/conversations/{conv['id']}").json()
    assert [m['role'] for m in d['messages']] == ['user', 'assistant']

    # LLM 调用参数：非 json_mode；system 含基础提示；messages 以本次输入收尾
    assert calls and calls[0]['json_mode'] is False
    assert 'FlowDesk' in calls[0]['system']
    assert calls[0]['messages'][-1] == {'role': 'user', 'content': '项目进展如何？'}


def test_message_system_contains_task_context(env, monkeypatch):
    c, ids, wid, pid = env
    c.put('/api/ai/settings', json={'api_key': 'sk-x', 'enabled': True})
    c.post(f'/api/projects/{pid}/tasks', json={'title': '写接口', 'priority': 'High'})
    conv = c.post('/api/ai/conversations', json={'project_id': pid}).json()
    seen = []

    def fake_llm(settings, messages, system_prompt, json_mode=False):
        seen.append(system_prompt)
        return '收到'

    monkeypatch.setattr('backend.routers.ai.call_llm', fake_llm)
    c.post(f"/api/ai/conversations/{conv['id']}/messages", json={'content': '总结一下'})
    assert '写接口' in seen[0] and 'High' in seen[0]


def test_message_llm_failure_reply_error(env, monkeypatch):
    c, ids, wid, pid = env
    c.put('/api/ai/settings', json={'api_key': 'sk-x', 'enabled': True})
    conv = c.post('/api/ai/conversations', json={}).json()

    def boom(settings, messages, system_prompt, json_mode=False):
        raise httpx.ConnectError('connection refused')

    monkeypatch.setattr('backend.routers.ai.call_llm', boom)
    r = c.post(f"/api/ai/conversations/{conv['id']}/messages", json={'content': 'hi'})
    assert r.status_code == 200  # 失败不抛 5xx
    data = r.json()
    assert data['assistant_message'] is None
    assert data['reply_error'] and 'AI 服务调用失败' in data['reply_error']
    d = c.get(f"/api/ai/conversations/{conv['id']}").json()
    assert [m['role'] for m in d['messages']] == ['user']  # 仅存了 user 消息


# ---------- 未配置 Key ----------

def test_unconfigured_key_409_and_user_message_stored(env, monkeypatch):
    c, ids, wid, pid = env
    conv = c.post('/api/ai/conversations', json={}).json()

    def fake_llm(settings, messages, system_prompt, json_mode=False):
        raise AssertionError('未启用时禁止调用 LLM')

    monkeypatch.setattr('backend.routers.ai.call_llm', fake_llm)
    r = c.post(f"/api/ai/conversations/{conv['id']}/messages", json={'content': 'hi'})
    assert r.status_code == 409
    assert 'API Key' in r.json()['detail']
    # user 消息已存库
    d = c.get(f"/api/ai/conversations/{conv['id']}").json()
    assert [m['role'] for m in d['messages']] == ['user']


# ---------- 设置 ----------

def test_settings_masked_and_validation(env):
    c, ids, wid, pid = env
    s = c.get('/api/ai/settings').json()
    assert s['enabled'] is False and s['api_key_masked'] == ''
    assert s['base_url'] == 'https://api.openai.com/v1'

    r = c.put('/api/ai/settings', json={'api_key': 'sk-abcdef1234', 'enabled': True, 'model': 'gpt-4o'})
    assert r.status_code == 200
    s = r.json()
    assert s['api_key_masked'] == 'sk-...1234'
    assert 'sk-abcdef1234' not in s['api_key_masked']  # 不回传明文
    assert s['enabled'] is True and s['model'] == 'gpt-4o'

    s2 = c.get('/api/ai/settings').json()
    assert 'abcdef1234' not in s2['api_key_masked']

    # enabled=true 但（结果）Key 为空 → 422：换一个从未配置过 Key 的用户
    login(c, 'bob@ex.com')
    assert c.put('/api/ai/settings', json={'enabled': True}).status_code == 422
    # 空 Key 保留原值（Alice 已有 Key）
    login(c, 'alice@ex.com')
    r3 = c.put('/api/ai/settings', json={'api_key': ''})
    assert r3.status_code == 200 and r3.json()['api_key_masked'] == 'sk-...1234'


# ---------- 提案接口 ----------

def test_proposals_parsed_and_skipped(env, monkeypatch):
    c, ids, wid, pid = env
    c.put('/api/ai/settings', json={'api_key': 'sk-x', 'enabled': True})
    conv = c.post('/api/ai/conversations', json={}).json()

    def fake_llm(settings, messages, system_prompt, json_mode=False):
        assert json_mode is True
        return ('[{"title":"发布准备","description":"检查清单","priority":"High","status":"Todo","due_date":"2026-12-01"},'
                '{"title":"","priority":"Low"}]')

    monkeypatch.setattr('backend.routers.ai.call_llm', fake_llm)
    r = c.post(f"/api/ai/conversations/{conv['id']}/proposals", json={'instruction': '准备发布', 'project_id': pid})
    assert r.status_code == 200
    data = r.json()
    assert data['skipped'] == 1  # 空标题条目被丢弃
    assert len(data['proposals']) == 1
    p = data['proposals'][0]
    assert p['title'] == '发布准备' and p['priority'] == 'High' and p['status'] == 'Todo'
    assert p['due_date'] == '2026-12-01'
    assert data['reply_error'] is None
    # 提案不落库：任务数不变
    assert c.get(f'/api/projects/{pid}/tasks').json() == []


def test_proposals_invalid_json_retries_once(env, monkeypatch):
    c, ids, wid, pid = env
    c.put('/api/ai/settings', json={'api_key': 'sk-x', 'enabled': True})
    conv = c.post('/api/ai/conversations', json={}).json()
    calls = []

    def fake_llm(settings, messages, system_prompt, json_mode=False):
        calls.append(1)
        return '这不是 JSON'

    monkeypatch.setattr('backend.routers.ai.call_llm', fake_llm)
    r = c.post(f"/api/ai/conversations/{conv['id']}/proposals", json={'instruction': 'x', 'project_id': pid})
    assert r.status_code == 200
    assert len(calls) == 2  # 重试 1 次
    data = r.json()
    assert data['proposals'] == [] and data['skipped'] == 0
    assert data['reply_error'] == 'AI 返回格式无法解析，请重试'


def test_proposals_permission_double_track(env, monkeypatch):
    c, ids, wid, pid = env
    c.put('/api/ai/settings', json={'api_key': 'sk-x', 'enabled': True})

    def fake_llm(settings, messages, system_prompt, json_mode=False):
        return '[{"title":"ok"}]'

    monkeypatch.setattr('backend.routers.ai.call_llm', fake_llm)

    # Bob（空间成员）：配置自己的 Key → 自己的会话 + 有项目访问权 → 可提案
    login(c, 'bob@ex.com')
    c.put('/api/ai/settings', json={'api_key': 'sk-x', 'enabled': True})
    bob_conv = c.post('/api/ai/conversations', json={}).json()
    assert c.post(f"/api/ai/conversations/{bob_conv['id']}/proposals",
                  json={'instruction': 'x', 'project_id': pid}).status_code == 200

    # Charlie（非空间成员）：自己的会话 + 无项目访问权 → 404
    login(c, 'charlie@ex.com')
    charlie_conv = c.post('/api/ai/conversations', json={}).json()
    assert c.post(f"/api/ai/conversations/{charlie_conv['id']}/proposals",
                  json={'instruction': 'x', 'project_id': pid}).status_code == 404

    # 会话归属：Alice 不能在他人的会话上提案 → 404
    login(c, 'alice@ex.com')
    assert c.post(f"/api/ai/conversations/{bob_conv['id']}/proposals",
                  json={'instruction': 'x', 'project_id': pid}).status_code == 404
