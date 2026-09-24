"""M4 Task tests: Task CRUD, workspace permissions, enum validation, optimistic lock, assignee rules."""
from fastapi.testclient import TestClient
import pytest
from backend.app import create_app

PASSWORD = 'test-password-123'

@pytest.fixture
def env(tmp_path):
    """三个用户（Alice=Owner, Bob=Admin/Member, Charlie=outsider）+ 一个空间 + 一个项目。"""
    app = create_app('sqlite:///' + str(tmp_path / 'tasks.db'), token='t')
    with TestClient(app, headers={'X-FlowDesk-Token': 't'}) as c:
        ids = {}
        for name, email in [('Alice','alice@ex.com'),('Bob','bob@ex.com'),('Charlie','charlie@ex.com')]:
            r = c.post('/api/auth/register', json={'username':name,'email':email,'password':PASSWORD})
            assert r.status_code == 201
            ids[name.lower()] = r.json()['id']
        login(c, 'alice@ex.com')
        wid = c.post('/api/workspaces', json={'name':'Team'}).json()['id']
        # Bob is Member
        c.post(f'/api/workspaces/{wid}/members', json={'email':'bob@ex.com'})
        pid = c.post('/api/projects', json={'workspace_id':wid,'name':'Proj'}).json()['id']
        yield c, ids, wid, pid
    app.state.engine.dispose()

def login(c, email):
    assert c.post('/api/auth/login', json={'email':email,'password':PASSWORD}).status_code == 200

def create_task(c, pid, **overrides):
    payload = {'title': '写文档', 'description': '初稿', 'priority': 'Medium'}
    payload.update(overrides)
    return c.post(f'/api/projects/{pid}/tasks', json=payload)

# ---------- CRUD ----------

def test_task_crud(env):
    c, ids, wid, pid = env
    assert c.get(f'/api/projects/{pid}/tasks').json() == []
    r = create_task(c, pid, title='  写文档  ', description='初稿', due_date='2026-10-01')
    assert r.status_code == 201
    t = r.json()
    assert t['title'] == '写文档' and t['status'] == 'Todo' and t['priority'] == 'Medium'
    assert t['creator_id'] == ids['alice'] and t['assignee_id'] is None
    assert t['completed_at'] is None
    url = f"/api/tasks/{t['id']}"
    assert c.get(url).json()['description'] == '初稿'
    # list
    tasks = c.get(f'/api/projects/{pid}/tasks').json()
    assert len(tasks) == 1 and tasks[0]['id'] == t['id']
    # patch with If-Match
    assert c.patch(url, json={'status':'In Progress','priority':'High'}, headers={'If-Match':str(t['version'])}).json()['status'] == 'In Progress'
    # delete
    assert c.delete(url, headers={'If-Match':'2'}).status_code == 204
    assert c.get(url).status_code == 404
    assert c.get(f'/api/projects/{pid}/tasks').json() == []

def test_task_completed_at(env):
    c, ids, wid, pid = env
    t = create_task(c, pid).json()
    url = f"/api/tasks/{t['id']}"
    # 标为 Done → completed_at 写入
    r = c.patch(url, json={'status':'Done'}, headers={'If-Match':str(t['version'])})
    assert r.json()['completed_at'] is not None
    # 改回 Todo → completed_at 清空
    v = r.json()['version']
    r2 = c.patch(url, json={'status':'Todo'}, headers={'If-Match':str(v)})
    assert r2.json()['completed_at'] is None

# ---------- 枚举校验 ----------

@pytest.mark.parametrize('payload', [
    {'title': 'x', 'status': 'BadStatus'},
    {'title': 'x', 'priority': 'Critical'},
    {'title': ''},
    {'title': 'x'*201},
    {'title': 'x', 'description': 'x'*10001},
    {'title': 'x', 'unexpected': 1},
    {'title': None},
])
def test_task_invalid_create(env, payload):
    c, ids, wid, pid = env
    assert c.post(f'/api/projects/{pid}/tasks', json=payload).status_code == 422

@pytest.mark.parametrize('payload', [
    {'status': 'Nope'}, {'priority': 'Critical'}, {'title': None}, {'description': None},
])
def test_task_invalid_patch(env, payload):
    c, ids, wid, pid = env
    t = create_task(c, pid).json()
    assert c.patch(f"/api/tasks/{t['id']}", json=payload).status_code == 422

# ---------- 乐观锁 ----------

def test_task_optimistic_lock(env):
    c, ids, wid, pid = env
    t = create_task(c, pid).json()
    url = f"/api/tasks/{t['id']}"
    # If-Match 不匹配 → 409
    assert c.patch(url, json={'title':'new'}, headers={'If-Match':'999'}).status_code == 409
    # 删除同理
    assert c.delete(url, headers={'If-Match':'999'}).status_code == 409
    # 正确版本号成功
    assert c.patch(url, json={'title':'ok'}, headers={'If-Match':str(t['version'])}).status_code == 200

# ---------- 权限 ----------

def test_task_permissions(env):
    c, ids, wid, pid = env
    # Alice (Owner) creates a task
    t = create_task(c, pid, title='任务A').json()
    url = f"/api/tasks/{t['id']}"

    # Bob (Member) can read and create
    login(c, 'bob@ex.com')
    assert c.get(url).status_code == 200
    assert c.get(f'/api/projects/{pid}/tasks').status_code == 200
    assert create_task(c, pid, title='Bob的任务').status_code == 201
    # Bob (Member) CANNOT delete
    assert c.delete(url).status_code == 403

    # Alice upgrades Bob to Admin
    login(c, 'alice@ex.com')
    c.patch(f'/api/workspaces/{wid}/members/{ids["bob"]}', json={'role':'Admin'})
    # Now Bob (Admin) CAN delete
    login(c, 'bob@ex.com')
    assert c.delete(url).status_code == 204

def test_task_non_member(env):
    c, ids, wid, pid = env
    t = create_task(c, pid, title='保密').json()
    url = f"/api/tasks/{t['id']}"
    # Charlie is not in the workspace
    login(c, 'charlie@ex.com')
    assert c.get(f'/api/projects/{pid}/tasks').status_code == 404
    assert c.get(url).status_code == 404
    assert create_task(c, pid, title='hacker').status_code == 404
    assert c.delete(url).status_code == 404

# ---------- 指派人校验 ----------

def test_assignee_must_be_in_workspace(env):
    c, ids, wid, pid = env
    # Bob is in workspace, Charlie is not
    r = create_task(c, pid, assignee_id=ids['bob'])
    assert r.status_code == 201 and r.json()['assignee_id'] == ids['bob']
    # Charlie is NOT in workspace → 422
    r = create_task(c, pid, assignee_id=ids['charlie'])
    assert r.status_code == 422
    # PATCH 指派给外部用户 → 422
    t = r = create_task(c, pid).json()
    r = c.patch(f"/api/tasks/{t['id']}", json={'assignee_id': ids['charlie']}, headers={'If-Match':str(t['version'])})
    assert r.status_code == 422
    # 指派给 Bob 成功
    r = c.patch(f"/api/tasks/{t['id']}", json={'assignee_id': ids['bob']}, headers={'If-Match':str(t['version'])})
    assert r.status_code == 200 and r.json()['assignee_id'] == ids['bob']

# ---------- 404 / 边界 ----------

def test_task_not_found(env):
    c, ids, wid, pid = env
    assert c.get('/api/tasks/99999').status_code == 404
    assert c.patch('/api/tasks/99999', json={'title':'x'}).status_code == 404
    assert c.delete('/api/tasks/99999').status_code == 404
    # 项目不存在
    assert c.get('/api/projects/99999/tasks').status_code == 404
    assert c.post('/api/projects/99999/tasks', json={'title':'x'}).status_code == 404
