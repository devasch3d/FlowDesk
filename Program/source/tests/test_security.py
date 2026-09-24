"""M9 安全中间件测试：跨源白名单 / Host 白名单（机器 A 维护）。

覆盖：
- 默认本地模式：跨源写操作 403（保持 M2 行为）
- 无 Origin 头请求（非浏览器客户端）：只校验 token
- FLOWDESK_ALLOWED_ORIGINS 白名单：白名单内放行、白名单外 403
- allowed_origins 显式参数：同上
- allowed_hosts：'*' 允许任意 Host；默认仅本地

说明：通过中间件后的写接口用 POST /api/projects（未登录 → 401 进入业务逻辑）。
"""
from contextlib import contextmanager
from pathlib import Path
import tempfile

from fastapi.testclient import TestClient

from backend.app import create_app


@contextmanager
def _make_app(allowed_origins=None, allowed_hosts=None):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / 't.db'
        app = create_app('sqlite:///' + db.as_posix(), token='t',
                         allowed_origins=allowed_origins, allowed_hosts=allowed_hosts)
        client = TestClient(app)
        yield client, app
        app.state.engine.dispose()


def test_default_local_mode_rejects_cross_origin():
    with _make_app() as (client, _app):
        # 白名单为空 = 本地单机模式
        r = client.post('/api/projects', json={'name': 'x'},
                        headers={'Origin': 'https://evil.example', 'X-FlowDesk-Token': 't'})
        assert r.status_code == 403


def test_default_local_mode_allows_same_origin():
    with _make_app() as (client, _app):
        r = client.post('/api/projects', json={'name': 'x'},
                        headers={'Origin': 'http://testserver', 'X-FlowDesk-Token': 't'})
        # 同源 + 有效 token → 中间件放行，进入业务逻辑（未登录 → 401）
        assert r.status_code == 401


def test_no_origin_requires_token_only():
    with _make_app() as (client, _app):
        # 无 Origin（curl / 脚本客户端）：仅校验 token
        r = client.post('/api/projects', json={'name': 'x'}, headers={'X-FlowDesk-Token': 't'})
        assert r.status_code == 401  # 通过中间件，进入业务逻辑
        r = client.post('/api/projects', json={'name': 'x'}, headers={'X-FlowDesk-Token': 'wrong'})
        assert r.status_code == 403  # token 校验仍然生效


def test_allowed_origins_whitelist_accepts_and_rejects():
    with _make_app(allowed_origins=['https://app.example.com', 'http://192.168.1.5:8000']) as (client, _app):
        ok = client.post('/api/projects', json={'name': 'x'},
                         headers={'Origin': 'https://app.example.com', 'X-FlowDesk-Token': 't'})
        assert ok.status_code == 401  # 白名单内 → 放行到业务逻辑
        ok2 = client.post('/api/projects', json={'name': 'x'},
                          headers={'Origin': 'http://192.168.1.5:8000', 'X-FlowDesk-Token': 't'})
        assert ok2.status_code == 401
        bad = client.post('/api/projects', json={'name': 'x'},
                          headers={'Origin': 'https://evil.example', 'X-FlowDesk-Token': 't'})
        assert bad.status_code == 403  # 白名单外 → 拒绝


def test_allowed_origins_env_var(monkeypatch):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / 't.db'
        monkeypatch.setenv('FLOWDESK_ALLOWED_ORIGINS', 'https://env.example.com')
        app = create_app('sqlite:///' + db.as_posix(), token='t')
        client = TestClient(app)
        try:
            ok = client.post('/api/projects', json={'name': 'x'},
                             headers={'Origin': 'https://env.example.com', 'X-FlowDesk-Token': 't'})
            assert ok.status_code == 401
            bad = client.post('/api/projects', json={'name': 'x'},
                              headers={'Origin': 'https://evil.example', 'X-FlowDesk-Token': 't'})
            assert bad.status_code == 403
        finally:
            app.state.engine.dispose()


def test_allowed_hosts_star_permits_any_host():
    with _make_app(allowed_hosts=['*']) as (client, _app):
        r = client.post('/api/projects', json={'name': 'x'},
                        headers={'Host': 'flowdesk.example.com', 'X-FlowDesk-Token': 't'})
        # '*' 允许任意 Host；无 Origin 仅校验 token → 401（进入业务逻辑）
        assert r.status_code == 401


def test_default_hosts_rejects_unknown_host():
    with _make_app() as (client, _app):
        r = client.post('/api/projects', json={'name': 'x'},
                        headers={'Host': 'flowdesk.example.com', 'X-FlowDesk-Token': 't'})
        assert r.status_code == 400  # TrustedHost 拒绝未知 Host
