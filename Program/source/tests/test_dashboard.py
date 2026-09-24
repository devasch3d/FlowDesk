"""M6 Dashboard tests: space-dimension overview aggregates, empty-structure compatibility, member-only visibility."""
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from backend.app import create_app

PASSWORD = 'test-password-123'

PROJECT_STATUS_ZERO = {'Planning': 0, 'Active': 0, 'Paused': 0, 'Completed': 0, 'Archived': 0}
TASK_STATUS_ZERO = {'Todo': 0, 'In Progress': 0, 'Review': 0, 'Done': 0}


@pytest.fixture
def env(tmp_path):
    """Alice=Owner, Bob=Member, Charlie=outsider，一个空间 Team + 一个项目 Proj。"""
    app = create_app('sqlite:///' + str(tmp_path / 'dashboard.db'), token='t')
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


def login(c, email):
    assert c.post('/api/auth/login', json={'email': email, 'password': PASSWORD}).status_code == 200


def overview(c, wid):
    return c.get(f'/api/dashboard/overview?workspace_id={wid}')


def create_task(c, pid, **overrides):
    payload = {'title': '任务', 'description': '', 'priority': 'Medium'}
    payload.update(overrides)
    return c.post(f'/api/projects/{pid}/tasks', json=payload)


def set_done(c, task):
    return c.patch(f"/api/tasks/{task['id']}", json={'status': 'Done'}, headers={'If-Match': str(task['version'])})


# ---------- 空结构（兼容 Task / Activity 未合入） ----------

def test_empty_overview(env):
    c, ids, wid, pid = env
    eid = c.post('/api/workspaces', json={'name': 'Empty'}).json()['id']
    r = overview(c, eid)
    assert r.status_code == 200
    data = r.json()
    assert data['workspace_id'] == eid
    assert data['projects'] == {'total': 0, 'by_status': PROJECT_STATUS_ZERO, 'active': 0,
                                'completion': {'completed': 0, 'total': 0, 'percent': 0.0}}
    assert data['tasks']['total'] == 0
    assert data['tasks']['by_status'] == TASK_STATUS_ZERO
    assert data['tasks']['overdue'] == 0
    assert data['tasks']['completion'] == {'completed': 0, 'total': 0, 'percent': 0.0}
    assert len(data['tasks']['daily_completed']) == 14
    assert all(x['count'] == 0 for x in data['tasks']['daily_completed'])
    assert data['upcoming_due'] == []
    assert data['recent_activity'] == []


# ---------- 聚合正确性 ----------

def test_overview_aggregates(env):
    c, ids, wid, pid = env
    # 项目：Proj → Active；再建一个 Completed 项目
    assert c.patch(f'/api/projects/{pid}', json={'status': 'Active'}).status_code == 200
    done_pid = c.post('/api/projects', json={'workspace_id': wid, 'name': 'DoneProj', 'status': 'Completed'}).json()['id']
    # 任务：1 逾期 Todo（昨天截止）、1 未来 Todo、1 In Progress、1 Done
    create_task(c, pid, title='逾期', due_date=(date.today() - timedelta(days=1)).isoformat())
    create_task(c, pid, title='未来', due_date=(date.today() + timedelta(days=3)).isoformat())
    create_task(c, pid, title='进行中', status='In Progress')
    t = create_task(c, pid, title='完成').json()
    assert set_done(c, t).status_code == 200

    data = overview(c, wid).json()
    assert data['projects']['total'] == 2
    assert data['projects']['by_status']['Active'] == 1
    assert data['projects']['by_status']['Completed'] == 1
    assert data['projects']['active'] == 1
    assert data['projects']['completion'] == {'completed': 1, 'total': 2, 'percent': 50.0}

    assert data['tasks']['total'] == 4
    assert data['tasks']['by_status']['Todo'] == 2
    assert data['tasks']['by_status']['In Progress'] == 1
    assert data['tasks']['by_status']['Done'] == 1
    assert data['tasks']['overdue'] == 1
    assert data['tasks']['completion'] == {'completed': 1, 'total': 4, 'percent': 25.0}


def test_daily_completed_trend(env):
    c, ids, wid, pid = env
    t1 = create_task(c, pid, title='a').json()
    t2 = create_task(c, pid, title='b').json()
    set_done(c, t1)
    set_done(c, t2)
    data = overview(c, wid).json()
    rows = [x for x in data['tasks']['daily_completed'] if x['count'] > 0]
    assert len(rows) == 1
    assert rows[0]['date'] == datetime.now(timezone.utc).date().isoformat()
    assert rows[0]['count'] == 2


def test_upcoming_due(env):
    c, ids, wid, pid = env
    # 逾期（昨天）→ 只进 overdue，不进 upcoming
    create_task(c, pid, title='逾期', due_date=(date.today() - timedelta(days=1)).isoformat())
    # 未来 3 天未完成 → upcoming
    near = create_task(c, pid, title='临近', due_date=(date.today() + timedelta(days=3)).isoformat()).json()
    # 未来 3 天但已完成 → 不出现
    done_t = create_task(c, pid, title='已完', due_date=(date.today() + timedelta(days=2)).isoformat()).json()
    set_done(c, done_t)
    # 10 天后 → 不在窗口
    create_task(c, pid, title='远期', due_date=(date.today() + timedelta(days=10)).isoformat())

    data = overview(c, wid).json()
    assert data['tasks']['overdue'] == 1
    ids_upcoming = [u['task_id'] for u in data['upcoming_due']]
    assert near['id'] in ids_upcoming
    assert done_t['id'] not in ids_upcoming
    assert all(u['due_date'] >= date.today().isoformat() for u in data['upcoming_due'])
    row = next(u for u in data['upcoming_due'] if u['task_id'] == near['id'])
    assert row['title'] == '临近' and row['project_name'] == 'Proj' and row['project_id'] == pid


# ---------- 权限 ----------

def test_member_can_read(env):
    c, ids, wid, pid = env
    login(c, 'bob@ex.com')
    assert overview(c, wid).status_code == 200


def test_non_member_forbidden(env):
    c, ids, wid, pid = env
    login(c, 'charlie@ex.com')
    assert overview(c, wid).status_code == 404


def test_requires_login(env):
    c, ids, wid, pid = env
    assert c.post('/api/auth/logout').status_code == 204
    assert overview(c, wid).status_code == 401


def test_workspace_not_found(env):
    c, ids, wid, pid = env
    assert overview(c, 99999).status_code == 404
