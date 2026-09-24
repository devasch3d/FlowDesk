"""Additive M1 -> M2 migration. Back up SQLite before touching its schema."""
from datetime import datetime, timezone
from pathlib import Path
import secrets
import sqlite3
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from .models import Base, AppSetting

def migrate(engine):
    old = inspect(engine)
    legacy = old.has_table('projects') and 'owner_id' not in {c['name'] for c in old.get_columns('projects')}
    backup = None
    if legacy and engine.dialect.name == 'sqlite' and engine.url.database not in (None, ':memory:'):
        path = Path(engine.url.database).resolve()
        folder = path.parent / 'backups'
        folder.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
        backup = folder / f'flowdesk-before-M2-{stamp}.db'
        with sqlite3.connect(path) as source, sqlite3.connect(backup) as destination:
            source.backup(destination)
        # If backup creation fails, migration stops without changing the old DB.
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        if legacy:
            conn.execute(text('ALTER TABLE projects ADD COLUMN owner_id INTEGER REFERENCES users(id)'))
        conn.execute(text('CREATE INDEX IF NOT EXISTS ix_projects_owner_id ON projects (owner_id)'))
    with Session(engine) as db:
        if not db.get(AppSetting, 'instance_id'):
            db.add(AppSetting(key='instance_id', value=secrets.token_hex(12)))
        version = db.get(AppSetting, 'schema_version')
        if version:
            version.value = '2'
        else:
            db.add(AppSetting(key='schema_version', value='2'))
        db.commit()
    return str(backup) if backup else None
