"""Test the actual EXE against an isolated M1 database, never real user data."""
import http.cookiejar
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

exe=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parents[2]/'FlowDesk.exe'
root=Path('test-results/packaged').resolve();root.mkdir(parents=True,exist_ok=True)
data=Path(tempfile.mkdtemp(prefix='m2-',dir=root))
base='http://127.0.0.1:18748'
password='packaged test passphrase'
with sqlite3.connect(data/'flowdesk.db') as db:
    db.execute('CREATE TABLE projects (id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL, description TEXT NOT NULL, status VARCHAR(20) NOT NULL, start_date DATE, deadline DATE, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, version INTEGER NOT NULL)')
    db.execute("INSERT INTO projects VALUES (7,'M1 legacy project','Keep these details','Active',NULL,'2026-12-15','2026-09-18 10:00:00','2026-09-18 10:00:00',1)")

def client():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
a,b=client(),client()

def request(opener,path,method='GET',body=None,token=''):
    r=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,method=method,headers={'Content-Type':'application/json','X-FlowDesk-Token':token})
    try:
        with opener.open(r,timeout=10) as response:
            value=response.read().decode()
            return response.status,json.loads(value) if value and path!='/' else value
    except urllib.error.HTTPError as exc:
        return exc.code,json.loads(exc.read().decode())

def stop(process):
    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,check=True)
    process.wait(timeout=10)

def start():
    process=subprocess.Popen([str(exe),'--headless','--port','18748','--data-dir',str(data)],creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(100):
        try:
            if request(a,'/api/health')[1]['version']=='0.2.0':return process
        except Exception:
            if process.poll() is not None:raise RuntimeError(f'EXE exited {process.returncode}')
            time.sleep(.2)
    stop(process);raise RuntimeError('EXE startup timed out')

def token(opener):
    return re.search(r'name="flowdesk-token" content="([^"]+)"',request(opener,'/')[1]).group(1)

p=start()
try:
    csrf=token(a)
    assert request(a,'/api/projects')[0]==401
    assert request(a,'/api/auth/setup')[1]['legacy_projects']==1
    body={'username':'Alice','email':'alice@example.com','password':password,'remember':True}
    assert request(a,'/api/auth/register','POST',body,csrf)[0]==409
    body['claim_legacy']=True
    assert request(a,'/api/auth/register','POST',body,csrf)[0]==201
    assert request(a,'/api/projects/7')[1]['description']=='Keep these details'
    created=request(a,'/api/projects','POST',{'name':'Created with packaged M2'},csrf)[1]
    body.update({'username':'Bob','email':'bob@example.com'})
    assert request(b,'/api/auth/register','POST',body,csrf)[0]==201
    assert request(b,'/api/projects')[1]==[]
    assert request(b,'/api/projects/7')[0]==404
    assert request(b,'/api/projects/7','PATCH',{'name':'Attack'},csrf)[0]==404
    assert request(b,'/api/projects/7','DELETE',None,csrf)[0]==404
    assert request(b,'/api/export')[1]['projects']==[]
finally:stop(p)
p=start()
try:
    assert request(a,'/api/auth/me')[1]['email']=='alice@example.com'
    assert request(a,f"/api/projects/{created['id']}")[0]==200
    assert request(a,'/api/projects/7')[0]==200
    csrf=token(a)
    assert request(a,'/api/auth/logout','POST',None,csrf)[0]==204
    assert request(a,'/api/projects')[0]==401
    assert len(list((data/'backups').glob('*.db')))==1
    with sqlite3.connect(next((data/'backups').glob('*.db'))) as db:
        assert 'owner_id' not in [r[1] for r in db.execute('PRAGMA table_info(projects)')]
    print('PACKAGED M2 PASS: M1 backup/migration, explicit claim, two-user authorization, durable login/project data across restart, logout revocation.')
finally:stop(p)
