"""Consistent SQLite backup; copied login sessions are intentionally revoked."""
import sqlite3

def backup_sqlite(source_path, target_path):
    with sqlite3.connect(source_path) as source, sqlite3.connect(target_path) as target:
        source.backup(target)
        if target.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sessions'").fetchone():
            target.execute('DELETE FROM sessions')
            target.commit()
