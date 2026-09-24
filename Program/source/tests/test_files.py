"""M5 File tests: multipart upload / download / delete, workspace & project listing,
anchor validation, size limit, filename sanitization and the Owner/Admin/Member matrix."""
from pathlib import Path
from fastapi.testclient import TestClient
import pytest
from backend.app import create_app

PASSWORD = 'test-password-123'
UPLOADS = Path(__file__).resolve().parent.parent / 'uploads'

@pytest.fixture(autouse=True)
def clean_uploads():
    """每次测试前后清空本地 uploads 目录，保证用例隔离（uploads/ 已被 .gitignore 排除）。"""
    UPLOADS.mkdir(parents=True, exist_ok=True)
    for p in UPLOADS.iterdir():
        if p.is_file():
            p.unlink()
    yield
    for p in UPLOADS.iterdir():
        if p.is_file():
            p.unlink()

@pytest.fixture
def env(tmp_path):
    """三个用户（Alice=Owner, Bob=Member/Admin, Charlie=outsider）+ 一个空间 + 一个项目。"""
    app = create_app('sqlite:///' + str(tmp_path / 'files.db'), token='t')
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
        yield c, ids, wid, pid
    app.state.engine.dispose()

def login(c, email):
    assert c.post('/api/auth/login', json={'email':email,'password':PASSWORD}).status_code == 200

def upload(c, anchor, anchor_id, filename='hello.txt', content=b'hello world', mime='text/plain', extra=None):
    files = {'file': (filename, content, mime)}
    data = {anchor: str(anchor_id)}
    if extra:
        data.update(extra)
    return c.post('/api/files', files=files, data=data)

# ---------- 上传 / 下载 / 删除（空间层级） ----------

def test_upload_download_delete_workspace(env):
    c, ids, wid, pid = env
    assert c.get(f'/api/workspaces/{wid}/files').json() == []
    r = upload(c, 'workspace_id', wid, filename='  说明文档.txt  ', content=b'hello world', mime='text/plain')
    assert r.status_code == 201
    f = r.json()
    assert f['filename'] == '说明文档.txt' and f['mime_type'] == 'text/plain'
    assert f['size'] == len(b'hello world') and f['uploaded_by'] == ids['alice']
    assert f['workspace_id'] == wid and f['project_id'] is None and f['task_id'] is None
    assert 'stored_path' not in f  # 不暴露服务器存储路径
    # 落盘文件存在且用服务端随机名
    stored = list(UPLOADS.iterdir())
    assert len(stored) == 1 and stored[0].is_file() and stored[0].name != f['filename']
    # 列表
    lst = c.get(f'/api/workspaces/{wid}/files').json()
    assert len(lst) == 1 and lst[0]['id'] == f['id']
    # 下载
    d = c.get(f"/api/files/{f['id']}")
    assert d.status_code == 200 and d.content == b'hello world'
    assert d.headers['content-type'].startswith('text/plain')
    assert 'attachment' in d.headers.get('content-disposition', '')
    # 删除 → 204，再访问 404，物理文件被移除
    assert c.delete(f"/api/files/{f['id']}").status_code == 204
    assert c.get(f"/api/files/{f['id']}").status_code == 404
    assert list(UPLOADS.iterdir()) == []
    assert c.get(f'/api/workspaces/{wid}/files').json() == []

def test_project_files(env):
    c, ids, wid, pid = env
    r = upload(c, 'project_id', pid, filename='design.png', content=b'\x89PNGfake', mime='image/png')
    assert r.status_code == 201
    f = r.json()
    assert f['project_id'] == pid and f['workspace_id'] is None
    assert c.get(f'/api/projects/{pid}/files').json()[0]['id'] == f['id']
    assert c.get(f'/api/workspaces/{wid}/files').json() == []

def test_task_files(env):
    c, ids, wid, pid = env
    t = c.post(f'/api/projects/{pid}/tasks', json={'title':'写文档'})
    assert t.status_code == 201
    tid = t.json()['id']
    r = upload(c, 'task_id', tid, filename='draft.docx', content=b'PKfake', mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    assert r.status_code == 201
    f = r.json()
    assert f['task_id'] == tid
    d = c.get(f"/api/files/{f['id']}")
    assert d.status_code == 200 and d.content == b'PKfake'

# ---------- 挂载点校验 ----------

def test_anchor_required(env):
    c, ids, wid, pid = env
    # 没有挂载点 → 422
    assert c.post('/api/files', files={'file': ('x.txt', b'x', 'text/plain')}).status_code == 422
    # 两个挂载点 → 422
    assert upload(c, 'workspace_id', wid, extra={'project_id': str(pid)}).status_code == 422
    # 挂载点类型非法 → 422
    r = c.post('/api/files', files={'file': ('x.txt', b'x', 'text/plain')}, data={'workspace_id': 'abc'})
    assert r.status_code == 422
    # 文件不存在 → 404
    assert c.post('/api/files', files={'file': ('x.txt', b'x', 'text/plain')}, data={'workspace_id': '99999'}).status_code == 404
    # 任务不存在 → 404
    assert c.post('/api/files', files={'file': ('x.txt', b'x', 'text/plain')}, data={'task_id': '99999'}).status_code == 404

def test_filename_sanitization(env):
    c, ids, wid, pid = env
    for evil in ['../../evil.txt', '..\\evil.txt', 'a/b/evil.txt', 'x'*300 + '.txt']:
        before = {p.name for p in UPLOADS.iterdir()}
        r = upload(c, 'workspace_id', wid, filename=evil, content=b'x')
        assert r.status_code == 201, evil
        assert r.json()['filename'] == 'evil.txt' if 'evil' in evil else len(r.json()['filename']) <= 255
        added = {p.name for p in UPLOADS.iterdir()} - before
        assert len(added) == 1, evil
        assert '..' not in next(iter(added)), evil

def test_empty_filename_rejected(env):
    c, ids, wid, pid = env
    r = upload(c, 'workspace_id', wid, filename='', content=b'x')
    assert r.status_code == 422

def test_size_limit(env):
    c, ids, wid, pid = env
    r = upload(c, 'workspace_id', wid, filename='big.bin', content=b'x' * (20 * 1024 * 1024 + 1))
    assert r.status_code == 413
    # 恰好 20MB 通过
    r2 = upload(c, 'workspace_id', wid, filename='ok.bin', content=b'x' * (20 * 1024 * 1024))
    assert r2.status_code == 201 and r2.json()['size'] == 20 * 1024 * 1024

# ---------- 权限矩阵 ----------

def test_permissions(env):
    c, ids, wid, pid = env
    f = upload(c, 'workspace_id', wid).json()
    url = f"/api/files/{f['id']}"
    # Bob（Member）可上传、可下载，不可删除
    login(c, 'bob@ex.com')
    assert upload(c, 'workspace_id', wid, filename='bob.txt').status_code == 201
    assert c.get(url).status_code == 200
    assert c.delete(url).status_code == 403
    assert c.get(f'/api/workspaces/{wid}/files').status_code == 200
    # Owner 把 Bob 升为 Admin → 可删除
    login(c, 'alice@ex.com')
    c.patch(f'/api/workspaces/{wid}/members/{ids["bob"]}', json={'role':'Admin'})
    login(c, 'bob@ex.com')
    assert c.delete(url).status_code == 204

def test_non_member(env):
    c, ids, wid, pid = env
    f = upload(c, 'workspace_id', wid).json()
    url = f"/api/files/{f['id']}"
    login(c, 'charlie@ex.com')
    # 外部用户：上传/列表/下载/删除全部 404（不暴露资源存在性）
    assert upload(c, 'workspace_id', wid).status_code == 404
    assert c.get(f'/api/workspaces/{wid}/files').status_code == 404
    assert c.get(f'/api/projects/{pid}/files').status_code == 404
    assert c.get(url).status_code == 404
    assert c.delete(url).status_code == 404
    # 不存在的空间/项目
    assert c.get('/api/workspaces/99999/files').status_code == 404
    assert c.get('/api/projects/99999/files').status_code == 404

# ---------- 边界 ----------

def test_not_found(env):
    c, ids, wid, pid = env
    assert c.get('/api/files/99999').status_code == 404
    assert c.delete('/api/files/99999').status_code == 404

def test_missing_physical_file(env):
    c, ids, wid, pid = env
    f = upload(c, 'workspace_id', wid).json()
    # 模拟存储文件丢失：物理文件删除后下载返回 404，但不影响列表
    for p in UPLOADS.iterdir():
        p.unlink()
    assert c.get(f"/api/files/{f['id']}").status_code == 404
    assert c.get(f'/api/workspaces/{wid}/files').json()[0]['id'] == f['id']
