from fastapi.testclient import TestClient
import pytest
from backend.app import create_app

@pytest.fixture
def client(tmp_path):
    app = create_app('sqlite:///' + str(tmp_path / 'test.db'), token='test-token')
    with TestClient(app, headers={'X-FlowDesk-Token': 'test-token'}) as client:
        assert client.post('/api/auth/register', json={'username':'Project tester', 'email':'project@example.com', 'password':'test-password-123'}).status_code == 201
        yield client
    app.state.engine.dispose()

def test_full_crud(client):
    assert client.get('/api/health').json()['status'] == 'ok'
    assert client.get('/api/projects').json() == []
    response = client.post('/api/projects', json={'name': ' 项目一 ', 'description': '中文描述', 'start_date': '2026-10-01', 'deadline': '2026-12-15'})
    assert response.status_code == 201
    p = response.json()
    assert p['name'] == '项目一' and p['status'] == 'Planning'
    url = f"/api/projects/{p['id']}"
    assert client.get(url).json()['description'] == '中文描述'
    for status in ['Active', 'Paused', 'Completed', 'Archived', 'Planning']:
        assert client.patch(url, json={'status': status}).json()['status'] == status
    assert client.patch(url, json={'start_date': None, 'deadline': None, 'description': ''}).status_code == 200
    assert client.get(url).json()['deadline'] is None
    assert client.get('/api/export').json()['projects'][0]['id'] == p['id']
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404
    assert client.get('/api/projects').json() == []

@pytest.mark.parametrize('payload', [
    {'name': ''}, {'name': '   '}, {'name': 'x'*121}, {'name': 'x', 'description': 'x'*10001},
    {'name': 'x', 'status': 'Unknown'}, {'name': 'x', 'deadline': '2026-02-30'},
    {'name': 'x', 'start_date': '2026-10-02', 'deadline': '2026-10-01'},
    {'name': 'x', 'unexpected': True}, {'name': None},
])
def test_invalid_create(client, payload):
    assert client.post('/api/projects', json=payload).status_code == 422
    assert client.get('/api/projects').json() == []

def test_patch_validation_and_conflict(client):
    p = client.post('/api/projects', json={'name': 'x', 'start_date': '2026-10-01', 'deadline': '2026-10-10'}).json()
    url = f"/api/projects/{p['id']}"
    for payload in [{'deadline': '2026-09-01'}, {'start_date': '2026-11-01'}, {'name': None}, {'description': None}, {'status': None}, {'name':' '}]:
        assert client.patch(url, json=payload).status_code == 422
    assert client.get(url).json()['deadline'] == '2026-10-10'
    assert client.patch(url, json={'name':'changed'}, headers={'If-Match':'1'}).status_code == 200
    assert client.patch(url, json={'name':'stale'}, headers={'If-Match':'1'}).status_code == 409
    assert client.delete(url, headers={'If-Match':'1'}).status_code == 409
    assert client.get(url).json()['name'] == 'changed'

def test_local_request_protection(client):
    assert client.post('/api/projects', json={'name':'x'}, headers={'X-FlowDesk-Token':''}).status_code == 403
    assert client.post('/api/projects', json={'name':'x'}, headers={'Origin':'https://untrusted.example'}).status_code == 403
    assert client.get('/api/projects', headers={'Host':'untrusted.example'}).status_code == 400

def test_restart_persistence(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'persistent.db')
    first = create_app(url, token='test')
    with TestClient(first, headers={'X-FlowDesk-Token':'test'}) as client:
        client.post('/api/auth/register', json={'username':'Persistence', 'email':'persist@example.com', 'password':'test-password-123', 'remember':True})
        created = client.post('/api/projects', json={'name':'重启后仍在', 'description':'永久保存'}).json()
        cookies = dict(client.cookies)
    first.state.engine.dispose()
    second = create_app(url)
    with TestClient(second, cookies=cookies) as client:
        assert client.get('/api/projects').json()[0]['id'] == created['id']
        assert client.get('/api/projects').json()[0]['description'] == '永久保存'
    second.state.engine.dispose()

def test_missing_and_bad_json(client):
    assert client.patch('/api/projects/9999', json={'name':'x'}).status_code == 404
    assert client.delete('/api/projects/9999').status_code == 404
    assert client.post('/api/projects', content='{bad').status_code == 422
    assert client.get('/api/projects/nope').status_code == 422

def test_text_is_data(client):
    name = '<script>alert(1)</script>'
    p = client.post('/api/projects', json={'name':name, 'description':"' OR 1=1; --"}).json()
    assert p['name'] == name
    assert len(client.get('/api/projects').json()) == 1
