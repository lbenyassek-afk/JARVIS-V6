"""Local versioned workspace persistence; no external synchronization."""
import sqlite3
from . import config
from .memory import sensitive
from .crypto import open_text, seal

APP_DIR = config.APP_DIR

def connect():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(APP_DIR / 'workspace.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS records (id INTEGER PRIMARY KEY, category TEXT, title TEXT, body TEXT, updated TEXT DEFAULT CURRENT_TIMESTAMP)')
    return db

def save(category, title, body):
    if sensitive(title, body):
        raise ValueError('Remove credentials before saving this record.')
    with connect() as db:
        return db.execute('INSERT INTO records(category,title,body) VALUES (?,?,?)',
                          (category, seal(title), seal(body))).lastrowid

def records(category):
    with connect() as db:
        rows = db.execute('SELECT id,title,body FROM records WHERE category=? ORDER BY id DESC', (category,)).fetchall()
        return [(row[0], open_text(row[1]), open_text(row[2])) for row in rows]

def delete(record_id):
    with connect() as db:
        db.execute('DELETE FROM records WHERE id=?', (int(record_id),))
