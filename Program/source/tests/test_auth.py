from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app import create_app
from backend.models import User, LoginSession, Project
from backend.security import verify_password, token_digest

PASSWORD = 'a long test password 2026'

@pytest.fixture
def app(tmp_path):
    instance = create_app('sqlite:///' + str(tmp_path / 'auth.db'), token='test-csrf')
    yield instance
    instance.state.engine.dispose()

def browser(app):
    return TestClient(app, headers={'X-FlowDesk-Token':'test-csrf'})

def register(client, email='alice@example.com', **extra):
    return client.post('/api/auth/register', json={'username':'Alice', 'email':email, 'password':PASSWORD, **extra})

def login(client, email='alice@example.com', **extra):
    return client.post('/api/auth/login', json={'email':email,'password':PASSWORD,**extra})

def test_register_cookie_me_and_hash(app):
    with browser(app) as c:
        result=register(c,email='ALICE@EXAMPLE.COM',remember=True)
        assert result.status_code==201
        assert result.json()['email']=='alice@example.com'
        assert set(result.json())=={'id','username','email','created_at'}
        header=result.headers['set-cookie']
        assert 'HttpOnly' in header and 'SameSite=strict' in header and 'Max-Age=2592000' in header and 'Path=/api' in header
        assert c.get('/api/auth/me').json()['id']==result.json()['id']
        raw=c.cookies.get(app.state.cookie_name)
        with Session(app.state.engine) as db:
            user=db.scalar(select(User))
            assert user.password_hash!=PASSWORD and PASSWORD not in user.password_hash
            assert verify_password(PASSWORD,user.password_hash)
            session=db.scalar(select(LoginSession))
            assert session.token_hash==token_digest(raw) and session.token_hash!=raw
        assert 'password' not in c.get('/api/auth/me').text

@pytest.mark.parametrize('path,method,body',[
    ('/api/auth/me','GET',None),('/api/projects','GET',None),('/api/projects/1','GET',None),
    ('/api/projects','POST',{'name':'x'}),('/api/projects/1','PATCH',{'name':'x'}),
    ('/api/projects/1','DELETE',None),('/api/export','GET',None),
])
def test_anonymous_denied(app,path,method,body):
    with browser(app) as c:
        assert c.request(method,path,json=body).status_code==401

def test_owner_isolation_every_endpoint(app):
    with browser(app) as a,browser(app) as b:
        alice=register(a).json()
        project=a.post('/api/projects',json={'name':'Alice secret'}).json()
        bob=register(b,'bob@example.com',username='Bob').json()
        url=f"/api/projects/{project['id']}"
        assert b.get('/api/projects').json()==[]
        assert b.get('/api/export').json()['projects']==[]
        assert b.get(url).status_code==404
        assert b.patch(url,json={'name':'attack'}).status_code==404
        assert b.delete(url).status_code==404
        assert b.post('/api/projects',json={'name':'attack','owner_id':alice['id']}).status_code==422
        assert b.patch(url,json={'owner_id':bob['id']}).status_code==422
        assert a.get(url).json()['name']=='Alice secret'
        assert a.get('/api/export').json()['projects'][0]['id']==project['id']
        assert a.patch(url,json={'name':'Alice updated'}).status_code==200
        assert a.delete(url).status_code==204

def test_logout_revokes_replayed_cookie(app):
    with browser(app) as c:
        register(c)
        old=dict(c.cookies)
        assert c.post('/api/auth/logout').status_code==204
        assert c.get('/api/auth/me').status_code==401
        c.cookies.update(old)
        assert c.get('/api/projects').status_code==401
        assert c.post('/api/auth/logout').status_code==204

def test_login_replaces_old_session_and_preserves_spaces(app):
    with browser(app) as c:
        register(c,password='  密码有空格，不能偷偷删除  ')
        old=dict(c.cookies)
        c.post('/api/auth/logout')
        assert login(c,password='密码有空格，不能偷偷删除').status_code==401
        assert login(c,password='  密码有空格，不能偷偷删除  ').status_code==200
        first=dict(c.cookies)
        response=login(c,password='  密码有空格，不能偷偷删除  ')
        assert response.status_code==200 and dict(c.cookies)!=first
        assert 'Max-Age' not in response.headers['set-cookie']
        c.cookies.update(first)
        assert c.get('/api/auth/me').status_code==401

def test_expired_and_forged_session(app):
    with browser(app) as c:
        register(c)
        with Session(app.state.engine) as db:
            db.scalar(select(LoginSession)).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
            db.commit()
        assert c.get('/api/projects').status_code==401
        c.cookies.clear();c.cookies.set(app.state.cookie_name,'fabricated')
        assert c.get('/api/auth/me').status_code==401

def test_duplicate_email_case_insensitive(app):
    with browser(app) as c:
        assert register(c).status_code==201
        assert register(c,' ALICE@example.com ').status_code==409
        with Session(app.state.engine) as db:
            assert len(db.scalars(select(User)).all())==1

@pytest.mark.parametrize('extra',[
    {'email':'not-an-email'}, {'email':'a@bad..com'}, {'username':'  '}, {'username':'a'*41},
    {'password':'short'}, {'password':' '*12}, {'password':'a'*129}, {'role':'admin'},
])
def test_invalid_registration(app,extra):
    with browser(app) as c:
        assert register(c,**extra).status_code==422
        with Session(app.state.engine) as db:
            assert db.scalar(select(User)) is None

def test_login_error_and_rate_limit(app):
    with browser(app) as c:
        register(c);c.post('/api/auth/logout')
        wrong=login(c,password='wrong')
        unknown=login(c,email='unknown@example.com',password='wrong')
        assert wrong.status_code==unknown.status_code==401
        assert wrong.json()==unknown.json()
        for _ in range(4):
            assert login(c,password='wrong').status_code==401
        assert login(c).status_code==429

def test_cross_site_auth_is_denied(app):
    with browser(app) as c:
        body={'username':'a','email':'a@example.com','password':PASSWORD}
        assert c.post('/api/auth/register',json=body,headers={'Origin':'https://evil.example'}).status_code==403
        assert c.post('/api/auth/register',json=body,headers={'X-FlowDesk-Token':''}).status_code==403
        assert register(c).status_code==201
        assert c.post('/api/auth/logout',headers={'Origin':'https://evil.example'}).status_code==403
        assert c.get('/api/auth/me').status_code==200

def test_stale_tab_cannot_write_under_new_account(app):
    with browser(app) as c:
        alice=register(c).json()
        c.post('/api/auth/logout');register(c,'bob@example.com')
        assert c.post('/api/projects',json={'name':'from stale Alice tab'},headers={'X-FlowDesk-User':str(alice['id'])}).status_code==409
        assert c.get('/api/projects').json()==[]

def legacy_database(path):
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE projects (id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL, description TEXT NOT NULL, status VARCHAR(20) NOT NULL, start_date DATE, deadline DATE, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, version INTEGER NOT NULL)')
        db.execute("INSERT INTO projects VALUES (7, '旧项目', '保留描述', 'Active', '2026-10-01', '2026-12-15', '2026-09-18 10:00:00', '2026-09-18 10:00:00', 3)")

def test_migration_backup_claim_and_restart(tmp_path):
    path=tmp_path/'old.db';legacy_database(path)
    app=create_app('sqlite:///'+str(path),token='test-csrf')
    backup=Path(app.state.migration_backup)
    assert backup.is_file()
    with sqlite3.connect(backup) as db:
        assert 'owner_id' not in [r[1] for r in db.execute('PRAGMA table_info(projects)')]
        assert db.execute('SELECT name FROM projects WHERE id=7').fetchone()[0]=='旧项目'
    with browser(app) as a,browser(app) as b:
        assert a.get('/api/auth/setup').json()=={'first_user':True,'legacy_projects':1}
        assert register(a).status_code==409
        assert a.get('/api/auth/setup').json()['first_user'] is True
        assert register(a,claim_legacy=True,remember=True).status_code==201
        project=a.get('/api/projects/7').json()
        assert project['description']=='保留描述' and project['start_date']=='2026-10-01' and project['version']==4
        assert register(b,'bob@example.com',claim_legacy=True).status_code==201
        assert b.get('/api/projects').json()==[]
        cookies=dict(a.cookies)
    app.state.engine.dispose()
    restarted=create_app('sqlite:///'+str(path),token='test-csrf')
    assert restarted.state.migration_backup is None
    with browser(restarted) as c:
        c.cookies.update(cookies)
        assert c.get('/api/auth/me').status_code==200
        assert c.get('/api/projects/7').json()['name']=='旧项目'
    restarted.state.engine.dispose()

def test_backup_failure_leaves_legacy_database_untouched(tmp_path):
    path=tmp_path/'old.db';legacy_database(path)
    (tmp_path/'backups').write_text('blocked backup path')
    with pytest.raises(FileExistsError):
        create_app('sqlite:///'+str(path))
    with sqlite3.connect(path) as db:
        assert 'owner_id' not in [r[1] for r in db.execute('PRAGMA table_info(projects)')]
        assert db.execute('SELECT COUNT(*) FROM projects').fetchone()[0]==1
        assert db.execute("SELECT name FROM sqlite_master WHERE name='users'").fetchone() is None

def test_first_claim_is_atomic(tmp_path):
    path=tmp_path/'old.db';legacy_database(path)
    app=create_app('sqlite:///'+str(path),token='test-csrf')
    def run(email):
        with browser(app) as c:
            assert register(c,email,claim_legacy=True).status_code==201
            return len(c.get('/api/projects').json())
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run,['first@example.com','second@example.com']))==[0,1]
    app.state.engine.dispose()

def test_backup_keeps_users_and_projects_but_drops_sessions(app,tmp_path):
    from backend.backup import backup_sqlite
    with browser(app) as c:
        register(c)
        c.post('/api/projects',json={'name':'Backed-up project'})
        backup=tmp_path/'backup.db'
        backup_sqlite(app.state.engine.url.database,backup)
        with sqlite3.connect(backup) as db:
            assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0]==1
            assert db.execute('SELECT COUNT(*) FROM projects').fetchone()[0]==1
            assert db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==0
        assert c.get('/api/auth/me').status_code==200
