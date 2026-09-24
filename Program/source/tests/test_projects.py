"""M4 Project tests: workspace-scoped projects with membership-based permissions."""
from fastapi.testclient import TestClient
import pytest
from backend.app import create_app

PASSWORD = 'test-password-123'

@pytest.fixture
def client(tmp_path):
    app = create_app('sqlite:///' + str(tmp_path / 'test.db'), token='test-token')
    with TestClient(app, headers={'X-FlowDesk-Token': 'test-token'}) as c:
        r = c.post('/api/auth/register', json={'username':'Project tester', 'email':'project@example.com', 'password':PASSWORD})
        assert r.status_code == 201
        ws = c.post('/api/workspaces', json={'name': 'Test Workspace'})
        assert ws.status_code == 201
        yield c, ws.json()['id']
    app.state.engine.dispose()

def create_project(c, wid, **overrides):
    payload = {'workspace_id': wid, 'name': '项目一', 'description': '中文描述',
               'start_date': '2026-10-01', 'deadline': '2026-12-15'}
    payload.update(overrides)
    return c.post('/api/projects', json=payload)

def test_full_crud(client):
    c, wid = client
    assert c.get('/api/health').json()['status'] == 'ok'
    assert c.get('/api/projects').json() == []
    response = create_project(c, wid, name=' 项目一 ', description='中文描述')
    assert response.status_code == 201
    p = response.json()
    assert p['name'] == '项目一' and p['status'] == 'Planning'
    assert p['workspace_id'] == wid
    url = f"/api/projects/{p['id']}"
    assert c.get(url).json()['description'] == '中文描述'
    for status in ['Active', 'Paused', 'Completed', 'Archived', 'Planning']:
        assert c.patch(url, json={'status': status}).json()['status'] == status
    assert c.patch(url, json={'start_date': None, 'deadline': None, 'description': ''}).status_code == 200
    assert c.get(url).json()['deadline'] is None
    assert c.get('/api/export').json()['projects'][0]['id'] == p['id']
    assert c.delete(url).status_code == 204
    assert c.get(url).status_code == 404
    assert c.get('/api/projects').json() == []

@pytest.mark.parametrize('payload', [
    {'name': ''}, {'name': '   '}, {'name': 'x'*121}, {'name': 'x', 'description': 'x'*10001},
    {'name': 'x', 'status': 'Unknown'}, {'name': 'x', 'deadline': '2026-02-30'},
    {'name': 'x', 'start_date': '2026-10-02', 'deadline': '2026-10-01'},
    {'name': 'x', 'unexpected': True}, {'name': None},
])
def test_invalid_create(client, payload):
    c, wid = client
    body = {'workspace_id': wid, 'name': 'x'}
    body.update(payload)
    assert c.post('/api/projects', json=body).status_code == 422
    assert c.get('/api/projects').json() == []

def test_create_without_workspace_is_legacy(client):
    c, wid = client
    # 不传 workspace_id → 存量项目模式（仅自己可见）
    r = c.post('/api/projects', json={'name': '个人项目'})
    assert r.status_code == 201
    assert r.json()['workspace_id'] is None and r.json()['owner_id']
    # 不存在的空间 / 非成员空间 → 403/404
    assert c.post('/api/projects', json={'name': 'x', 'workspace_id': 99999}).status_code in (403, 404)

def test_patch_validation_and_conflict(client):
    c, wid = client
    p = create_project(c, wid, name='x', start_date='2026-10-01', deadline='2026-10-10').json()
    url = f"/api/projects/{p['id']}"
    for payload in [{'deadline': '2026-09-01'}, {'start_date': '2026-11-01'}, {'name': None}, {'description': None}, {'status': None}, {'name':' '}]:
        assert c.patch(url, json=payload).status_code == 422
    assert c.get(url).json()['deadline'] == '2026-10-10'
    assert c.patch(url, json={'name':'changed'}, headers={'If-Match':'1'}).status_code == 200
    assert c.patch(url, json={'name':'stale'}, headers={'If-Match':'1'}).status_code == 409
    assert c.delete(url, headers={'If-Match':'1'}).status_code == 409
    assert c.get(url).json()['name'] == 'changed'

def test_local_request_protection(client):
    c, wid = client
    assert c.post('/api/projects', json={'workspace_id':wid,'name':'x'}, headers={'X-FlowDesk-Token':''}).status_code == 403
    assert c.post('/api/projects', json={'workspace_id':wid,'name':'x'}, headers={'Origin':'https://untrusted.example'}).status_code == 403
    assert c.get('/api/projects', headers={'Host':'untrusted.example'}).status_code == 400

def test_restart_persistence(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'persistent.db')
    first = create_app(url, token='test')
    with TestClient(first, headers={'X-FlowDesk-Token':'test'}) as c:
        c.post('/api/auth/register', json={'username':'Persistence', 'email':'persist@example.com', 'password':PASSWORD, 'remember':True})
        wid = c.post('/api/workspaces', json={'name':'WS'}).json()['id']
        created = c.post('/api/projects', json={'workspace_id':wid,'name':'重启后仍在','description':'永久保存'}).json()
        cookies = dict(c.cookies)
    first.state.engine.dispose()
    second = create_app(url)
    with TestClient(second, cookies=cookies) as c:
        assert c.get('/api/projects').json()[0]['id'] == created['id']
        assert c.get('/api/projects').json()[0]['description'] == '永久保存'
    second.state.engine.dispose()

def test_missing_and_bad_json(client):
    c, wid = client
    assert c.patch('/api/projects/9999', json={'name':'x'}).status_code == 404
    assert c.delete('/api/projects/9999').status_code == 404
    assert c.post('/api/projects', content='{bad').status_code == 422
    assert c.get('/api/projects/nope').status_code == 422

def test_text_is_data(client):
    c, wid = client
    name = '<script>alert(1)</script>'
    p = create_project(c, wid, name=name, description="' OR 1=1; --").json()
    assert p['name'] == name
    assert len(c.get('/api/projects').json()) == 1

def test_workspace_isolation(tmp_path):
    """非空间成员看不到别人空间的项目；成员加入后可见。"""
    app = create_app('sqlite:///' + str(tmp_path / 'iso.db'), token='t')
    with TestClient(app, headers={'X-FlowDesk-Token':'t'}) as c:
        for name, email in [('Alice','alice@ex.com'),('Bob','bob@ex.com')]:
            r = c.post('/api/auth/register', json={'username':name,'email':email,'password':PASSWORD})
            assert r.status_code == 201
        # Alice creates workspace + project
        c.post('/api/auth/login', json={'email':'alice@ex.com','password':PASSWORD})
        wid = c.post('/api/workspaces', json={'name':'A空间'}).json()['id']
        p = c.post('/api/projects', json={'workspace_id':wid,'name':'保密项目'}).json()
        # Bob is not a member: cannot see
        c.post('/api/auth/login', json={'email':'bob@ex.com','password':PASSWORD})
        assert c.get('/api/projects').json() == []
        assert c.get(f"/api/projects/{p['id']}").status_code == 404
        # Bob cannot create project in Alice's workspace
        assert c.post('/api/projects', json={'workspace_id':wid,'name':'x'}).status_code in (403,404)
        # Alice adds Bob as Member
        c.post('/api/auth/login', json={'email':'alice@ex.com','password':PASSWORD})
        c.post(f'/api/workspaces/{wid}/members', json={'email':'bob@ex.com'})
        # Now Bob can see and edit
        c.post('/api/auth/login', json={'email':'bob@ex.com','password':PASSWORD})
        assert len(c.get('/api/projects').json()) == 1
        assert c.get(f"/api/projects/{p['id']}").json()['name'] == '保密项目'
        # Member can edit but NOT delete (needs Owner/Admin)
        assert c.patch(f"/api/projects/{p['id']}", json={'description':'by bob'}).status_code == 200
        assert c.delete(f"/api/projects/{p['id']}").status_code == 403
    app.state.engine.dispose()
