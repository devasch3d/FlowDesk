from collections import deque
from datetime import datetime, timedelta, timezone
import re
import secrets
import threading
import time

from fastapi import Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .models import AppSetting, LoginAttempt, LoginSession, Project, User
from .security import hash_password, token_digest, verify_password

def utcnow():
    return datetime.now(timezone.utc)

def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)
    remember: bool = False

    @field_validator('email')
    @classmethod
    def valid_email(cls, value):
        value = value.strip().casefold()
        if not re.fullmatch(r'[a-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}', value) or '..' in value or len(value.split('@')[0]) > 64:
            raise ValueError('请输入有效邮箱地址')
        return value

class Registration(Credentials):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=10, max_length=128)
    claim_legacy: bool = False

    @field_validator('username')
    @classmethod
    def name_valid(cls, value):
        value = value.strip()
        if not value or any(ord(c)<32 for c in value):
            raise ValueError('请填写有效的用户名称')
        return value

    @field_validator('password')
    @classmethod
    def password_valid(cls, value):
        if not value.strip():
            raise ValueError('密码不能只包含空格')
        return value  # Deliberately do not trim passwords.

class CurrentUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    email: str
    created_at: datetime

def install_auth(app, engine):
    with Session(engine) as db:
        instance = db.get(AppSetting, 'instance_id').value
    cookie_name = 'flowdesk_' + instance
    app.state.cookie_name = cookie_name
    dummy_hash = hash_password(secrets.token_urlsafe(32))
    auth_lock = threading.Lock()
    requests = deque()

    def throttle():
        # One loopback server; limit total costly password checks per minute.
        now = time.monotonic()
        while requests and now - requests[0] > 60:
            requests.popleft()
        if len(requests) >= 30:
            raise HTTPException(429, '操作太频繁，请一分钟后再试', headers={'Retry-After': '60'})
        requests.append(now)

    def current_user(request: Request):
        raw = request.cookies.get(cookie_name)
        if not raw or len(raw) > 128:
            raise HTTPException(401, '请先登录 FlowDesk')
        with Session(engine) as db:
            session = db.get(LoginSession, token_digest(raw))
            if not session or aware(session.expires_at) <= utcnow():
                raise HTTPException(401, '登录已过期，请重新登录')
            user = db.get(User, session.user_id)
            if not user:
                raise HTTPException(401, '请重新登录')
            expected = request.headers.get('x-flowdesk-user')
            if expected and expected != str(user.id):
                raise HTTPException(409, '账号已在其他页面切换，请刷新后重试')
            return user

    def new_session(db, request, response, user_id, remember):
        now = utcnow()
        lifetime = 30*24*3600 if remember else 8*3600
        old = request.cookies.get(cookie_name)
        if old:
            db.execute(delete(LoginSession).where(LoginSession.token_hash == token_digest(old)))
        db.execute(delete(LoginSession).where(LoginSession.expires_at <= now).execution_options(synchronize_session=False))
        raw = secrets.token_urlsafe(32)
        db.add(LoginSession(token_hash=token_digest(raw), user_id=user_id, created_at=now, expires_at=now+timedelta(seconds=lifetime)))
        response.set_cookie(cookie_name, raw, max_age=lifetime if remember else None, httponly=True, samesite='strict', secure=False, path='/api')

    @app.get('/api/auth/setup')
    def setup():
        with Session(engine) as db:
            first = not db.scalar(select(func.count()).select_from(User))
            count = db.scalar(select(func.count()).select_from(Project).where(Project.owner_id.is_(None))) if first else 0
            return {'first_user': first, 'legacy_projects': count}

    @app.post('/api/auth/register', response_model=CurrentUser, status_code=201)
    def register(body: Registration, request: Request, response: Response):
        with auth_lock:
            throttle()
            password_hash = hash_password(body.password)
            with Session(engine) as db:
                # Serialize the first-owner decision across local processes as well.
                if engine.dialect.name == 'sqlite':
                    db.execute(text('BEGIN IMMEDIATE'))
                elif engine.dialect.name == 'postgresql':
                    db.execute(text('SELECT pg_advisory_xact_lock(73421902)'))
                if db.scalar(select(User).where(User.email == body.email)):
                    raise HTTPException(409, '这个邮箱已注册，请直接登录')
                first = not db.scalar(select(func.count()).select_from(User))
                legacy = db.scalar(select(func.count()).select_from(Project).where(Project.owner_id.is_(None))) if first else 0
                if legacy and not body.claim_legacy:
                    raise HTTPException(409, '请先确认将旧版项目归属到此账号，再完成注册')
                user = User(username=body.username, email=body.email, password_hash=password_hash, created_at=utcnow())
                db.add(user)
                try:
                    db.flush()
                    if first and legacy:
                        db.execute(update(Project).where(Project.owner_id.is_(None)).values(owner_id=user.id, version=Project.version+1))
                    new_session(db, request, response, user.id, body.remember)
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    raise HTTPException(409, '这个邮箱已注册，请直接登录')
                db.refresh(user)
                return user

    @app.post('/api/auth/login', response_model=CurrentUser)
    def login(body: Credentials, request: Request, response: Response):
        with auth_lock:
            throttle()
            now = utcnow()
            identity = token_digest(instance + ':' + body.email)
            with Session(engine) as db:
                attempt = db.get(LoginAttempt, identity)
                if attempt and now - aware(attempt.window_start) < timedelta(minutes=15) and attempt.failures >= 5:
                    seconds = max(1, int((aware(attempt.window_start)+timedelta(minutes=15)-now).total_seconds()))
                    raise HTTPException(429, '尝试次数过多，请 15 分钟后再试', headers={'Retry-After': str(seconds)})
                user = db.scalar(select(User).where(User.email == body.email))
                valid = verify_password(body.password, user.password_hash if user else dummy_hash)
                if not user or not valid:
                    if not attempt:
                        db.add(LoginAttempt(identity=identity, failures=1, window_start=now))
                    elif now - aware(attempt.window_start) >= timedelta(minutes=15):
                        attempt.failures, attempt.window_start = 1, now
                    else:
                        attempt.failures += 1
                    db.execute(delete(LoginAttempt).where(LoginAttempt.window_start < now-timedelta(days=1)).execution_options(synchronize_session=False))
                    db.commit()
                    raise HTTPException(401, '邮箱或密码不正确')
                if attempt:
                    db.delete(attempt)
                new_session(db, request, response, user.id, body.remember)
                db.commit()
                db.refresh(user)
                return user

    @app.post('/api/auth/logout', status_code=204)
    def logout(request: Request):
        raw = request.cookies.get(cookie_name)
        if raw:
            with Session(engine) as db:
                db.execute(delete(LoginSession).where(LoginSession.token_hash == token_digest(raw)))
                db.commit()
        response = Response(status_code=204)
        response.delete_cookie(cookie_name, path='/api', httponly=True, samesite='strict')
        return response

    @app.get('/api/auth/me', response_model=CurrentUser)
    def me(user: User = Depends(current_user)):
        return user

    return current_user
