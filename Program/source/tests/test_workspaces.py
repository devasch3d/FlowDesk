"""M3 Workspace tests: many-to-many memberships and the Owner/Admin/Member permission matrix."""
from fastapi.testclient import TestClient
import pytest
from backend.app import create_app

PASSWORD = 'test-password-123'

@pytest.fixture
def users(tmp_path):
    app = create_app('sqlite:///' + str(tmp_path / 'test.db'), token='test-token')
    with TestClient(app, headers={'X-FlowDesk-Token': 'test-token'}) as c:
        ids = {}
        for name, email in [('Alice', 'alice@example.com'), ('Bob', 'bob@example.com'), ('Charlie', 'charlie@example.com')]:
            r = c.post('/api/auth/register', json={'username': name, 'email': email, 'password': PASSWORD})
            assert r.status_code == 201
            ids[name.lower()] = r.json()['id']
        login(c, 'alice@example.com')
        yield c, ids
    app.state.engine.dispose()

def login(c, email):
    assert c.post('/api/auth/login', json={'email': email, 'password': PASSWORD}).status_code == 200

def test_create_and_list(users):
    c, ids = users
    ws = c.post('/api/workspaces', json={'name': ' 团队空间 ', 'description': '开发'})
    assert ws.status_code == 201
    data = ws.json()
    assert data['name'] == '团队空间' and data['role'] == 'Owner'
    login(c, 'bob@example.com')
    assert c.get('/api/workspaces').json() == []
    login(c, 'alice@example.com')
    assert len(c.get('/api/workspaces').json()) == 1

def test_member_flow_and_permission_matrix(users):
    c, ids = users
    wid = c.post('/api/workspaces', json={'name': 'Team'}).json()['id']

    # Owner 加 Bob 为 Member；邮箱大小写与首尾空格应被归一化
    r = c.post(f'/api/workspaces/{wid}/members', json={'email': '  BOB@example.com  '})
    assert r.status_code == 201 and r.json()['role'] == 'Member'
    detail = c.get(f'/api/workspaces/{wid}').json()
    assert [m['email'] for m in detail['members']] == ['alice@example.com', 'bob@example.com']
    # 重复添加 409；不存在的邮箱 404
    assert c.post(f'/api/workspaces/{wid}/members', json={'email': 'bob@example.com'}).status_code == 409
    assert c.post(f'/api/workspaces/{wid}/members', json={'email': 'ghost@example.com'}).status_code == 404

    # Bob 是 Member：可读，但不可改空间/加人/移除/调角色
    login(c, 'bob@example.com')
    assert c.get(f'/api/workspaces/{wid}').status_code == 200
    assert c.patch(f'/api/workspaces/{wid}', json={'name': 'Hack'}).status_code == 403
    assert c.post(f'/api/workspaces/{wid}/members', json={'email': 'charlie@example.com'}).status_code == 403
    assert c.delete(f'/api/workspaces/{wid}/members/{ids["charlie"]}').status_code == 403
    assert c.patch(f'/api/workspaces/{wid}/members/{ids["alice"]}', json={'role': 'Member'}).status_code == 403

    # Owner 把 Bob 升为 Admin
    login(c, 'alice@example.com')
    assert c.patch(f'/api/workspaces/{wid}/members/{ids["bob"]}', json={'role': 'Admin'}).status_code == 200
    # Admin：可改空间、可加人、可移除普通成员；但不能调角色、不能移除 Owner
    login(c, 'bob@example.com')
    assert c.patch(f'/api/workspaces/{wid}', json={'description': 'by admin'}).status_code == 200
    assert c.post(f'/api/workspaces/{wid}/members', json={'email': 'charlie@example.com'}).status_code == 201
    assert c.patch(f'/api/workspaces/{wid}/members/{ids["alice"]}', json={'role': 'Member'}).status_code == 403
    assert c.delete(f'/api/workspaces/{wid}/members/{ids["alice"]}').status_code == 400
    assert c.delete(f'/api/workspaces/{wid}/members/{ids["charlie"]}').status_code == 204

    # Owner：不能降级自己；可以调其他成员角色
    login(c, 'alice@example.com')
    assert c.patch(f'/api/workspaces/{wid}/members/{ids["alice"]}', json={'role': 'Member'}).status_code == 400
    assert c.patch(f'/api/workspaces/{wid}/members/{ids["bob"]}', json={'role': 'Member'}).status_code == 200
    # Owner 移除 Bob
    assert c.delete(f'/api/workspaces/{wid}/members/{ids["bob"]}').status_code == 204
    login(c, 'bob@example.com')
    assert c.get('/api/workspaces').json() == []
    assert c.get(f'/api/workspaces/{wid}').status_code == 404

def test_invalid_create(users):
    c, ids = users
    for payload in [{'name': ''}, {'name': '   '}, {'name': 'x' * 81}, {'name': 'x', 'unexpected': 1}, {'name': 'x', 'description': 'x' * 1001}]:
        assert c.post('/api/workspaces', json=payload).status_code == 422

def test_patch_validation(users):
    c, ids = users
    wid = c.post('/api/workspaces', json={'name': 'Team'}).json()['id']
    for payload in [{'name': None}, {'description': None}, {'name': ' '}, {'name': ''}]:
        assert c.patch(f'/api/workspaces/{wid}', json=payload).status_code == 422

def test_missing(users):
    c, ids = users
    assert c.get('/api/workspaces/9999').status_code == 404
    assert c.patch('/api/workspaces/9999', json={'name': 'x'}).status_code == 404
    assert c.delete('/api/workspaces/9999/members/1').status_code == 404
