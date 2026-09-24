"""M7 Collaboration tests: comment CRUD, ownership & role permissions, activity feed pagination."""
from fastapi.testclient import TestClient
import pytest
from backend.app import create_app

PASSWORD = 'test-password-123'

@pytest.fixture
def env(tmp_path):
    """三个用户（Alice=Owner, Bob=Member, Charlie=outsider）+ 一个空间 + 一个项目 + 一个任务。"""
    app = create_app('sqlite:///' + str(tmp_path / 'collab.db'), token='t')
    with TestClient(app, headers={'X-FlowDesk-Token': 't'}) as c:
        ids = {}
        for name, email in [('Alice','alice@ex.com'),('Bob','bob@ex.com'),('Charlie','charlie@ex.com')]:
            r = c.post('/api/auth/register', json={'username':name,'email':email,'password':PASSWORD})
            assert r.status_code == 201
            ids[name.lower()] = r.json()['id']
        login(c, 'alice@ex.com')
        wid = c.post('/api/workspaces', json={'name':'Team'}).json()['id']
        c.post(f'/api/workspaces/{wid}/members', json={'email':'bob@ex.com'})
        pid = c.post('/api/projects', json={'workspace_id':wid,'name':'Proj'}).json()['id']
        tid = c.post(f'/api/projects/{pid}/tasks', json={'title':'写文档'}).json()['id']
        yield c, ids, wid, pid, tid
    app.state.engine.dispose()

def login(c, email):
    assert c.post('/api/auth/login', json={'email':email,'password':PASSWORD}).status_code == 200

def create_comment(c, tid, body='很好'):
    return c.post(f'/api/tasks/{tid}/comments', json={'body':body})

# ---------- 评论 CRUD ----------

def test_comment_crud(env):
    c, ids, wid, pid, tid = env
    assert c.get(f'/api/tasks/{tid}/comments').json() == []
    r = create_comment(c, tid, '  第一条评论  ')
    assert r.status_code == 201
    cm = r.json()
    assert cm['body'] == '第一条评论' and cm['task_id'] == tid and cm['author_id'] == ids['alice']
    assert cm['author_username'] == 'Alice'
    assert cm['created_at'] == cm['updated_at']
    # 列表
    lst = c.get(f'/api/tasks/{tid}/comments').json()
    assert len(lst) == 1 and lst[0]['id'] == cm['id']
    # 修改（作者本人）
    r2 = c.patch(f"/api/comments/{cm['id']}", json={'body':'改过的评论'})
    assert r2.status_code == 200
    assert r2.json()['body'] == '改过的评论' and r2.json()['updated_at'] != cm['created_at']
    # 删除（作者本人）
    assert c.delete(f"/api/comments/{cm['id']}").status_code == 204
    assert c.get(f'/api/tasks/{tid}/comments').json() == []

def test_comment_list_order(env):
    c, ids, wid, pid, tid = env
    for i in range(3):
        assert create_comment(c, tid, f'评论{i}').status_code == 201
    lst = c.get(f'/api/tasks/{tid}/comments').json()
    assert [x['body'] for x in lst] == ['评论0', '评论1', '评论2']  # 时间正序

# ---------- 输入校验 ----------

@pytest.mark.parametrize('payload', [
    {'body': ''},
    {'body': '   '},
    {'body': 'x' * 10001},
    {'body': None},
    {'body': 'ok', 'unexpected': 1},
    {},
])
def test_comment_invalid_create(env, payload):
    c, ids, wid, pid, tid = env
    assert c.post(f'/api/tasks/{tid}/comments', json=payload).status_code == 422

@pytest.mark.parametrize('payload', [
    {'body': ''},
    {'body': 'x' * 10001},
    {'body': None},
    {},
])
def test_comment_invalid_patch(env, payload):
    c, ids, wid, pid, tid = env
    cm = create_comment(c, tid).json()
    assert c.patch(f"/api/comments/{cm['id']}", json=payload).status_code == 422

# ---------- 权限 ----------

def test_comment_member_read_and_write(env):
    c, ids, wid, pid, tid = env
    cm = create_comment(c, tid, 'Alice 的评论').json()
    # Bob（空间成员）可读可评论
    login(c, 'bob@ex.com')
    assert c.get(f'/api/tasks/{tid}/comments').status_code == 200
    assert create_comment(c, tid, 'Bob 的评论').status_code == 201
    assert c.patch(f"/api/comments/{cm['id']}", json={'body':'偷改'}).status_code == 403  # 非作者
    assert c.delete(f"/api/comments/{cm['id']}").status_code == 403  # 非作者且非 Owner/Admin

def test_comment_non_member(env):
    c, ids, wid, pid, tid = env
    cm = create_comment(c, tid).json()
    login(c, 'charlie@ex.com')
    assert c.get(f'/api/tasks/{tid}/comments').status_code == 404
    assert create_comment(c, tid).status_code == 404
    assert c.patch(f"/api/comments/{cm['id']}", json={'body':'x'}).status_code == 404
    assert c.delete(f"/api/comments/{cm['id']}").status_code == 404

def test_comment_owner_admin_delete_any(env):
    c, ids, wid, pid, tid = env
    login(c, 'bob@ex.com')
    bob_cm = create_comment(c, tid, 'Bob 的').json()
    login(c, 'alice@ex.com')
    alice_cm = create_comment(c, tid, 'Alice 的').json()
    # Alice（Owner）可删 Bob 的评论
    assert c.delete(f"/api/comments/{bob_cm['id']}").status_code == 204
    # Bob 升级为 Admin 后也可删 Alice 的评论
    c.patch(f'/api/workspaces/{wid}/members/{ids["bob"]}', json={'role':'Admin'})
    login(c, 'bob@ex.com')
    assert c.delete(f"/api/comments/{alice_cm['id']}").status_code == 204

# ---------- 404 / 边界 ----------

def test_comment_not_found(env):
    c, ids, wid, pid, tid = env
    assert c.get('/api/tasks/99999/comments').status_code == 404
    assert c.post('/api/tasks/99999/comments', json={'body':'x'}).status_code == 404
    assert c.patch('/api/comments/99999', json={'body':'x'}).status_code == 404
    assert c.delete('/api/comments/99999').status_code == 404

# ---------- 活动流 ----------

def test_activity_feed_records_comments(env):
    c, ids, wid, pid, tid = env
    assert c.get(f'/api/workspaces/{wid}/activities').json() == []
    create_comment(c, tid, '第一条')
    create_comment(c, tid, '第二条')
    rows = c.get(f'/api/workspaces/{wid}/activities').json()
    assert len(rows) == 2
    a = rows[0]
    assert a['action'] == 'commented' and a['target_type'] == 'task' and a['target_id'] == tid
    assert a['actor_id'] == ids['alice'] and a['actor_username'] == 'Alice'
    assert a['workspace_id'] == wid
    # 时间倒序（新在前）
    assert rows[0]['created_at'] >= rows[1]['created_at']

def test_activity_feed_non_member(env):
    c, ids, wid, pid, tid = env
    create_comment(c, tid)
    login(c, 'charlie@ex.com')
    assert c.get(f'/api/workspaces/{wid}/activities').status_code == 404

def test_activity_feed_pagination(env):
    c, ids, wid, pid, tid = env
    for i in range(5):
        create_comment(c, tid, f'评论{i}')
    page1 = c.get(f'/api/workspaces/{wid}/activities?limit=2&offset=0').json()
    page2 = c.get(f'/api/workspaces/{wid}/activities?limit=2&offset=2').json()
    page3 = c.get(f'/api/workspaces/{wid}/activities?limit=2&offset=4').json()
    ids1 = [x['id'] for x in page1]
    ids2 = [x['id'] for x in page2]
    ids3 = [x['id'] for x in page3]
    assert len(ids1) == 2 and len(ids2) == 2 and len(ids3) == 1
    assert len(set(ids1 + ids2 + ids3)) == 5
    # limit/offset 非法值
    assert c.get(f'/api/workspaces/{wid}/activities?limit=0').status_code == 422
    assert c.get(f'/api/workspaces/{wid}/activities?limit=101').status_code == 422
    assert c.get(f'/api/workspaces/{wid}/activities?offset=-1').status_code == 422
