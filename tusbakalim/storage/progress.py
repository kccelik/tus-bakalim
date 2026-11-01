"""Users, answers and review cards (instance/progress.db).

Kept separate from the question bank, so rebuilding the bank never touches
anyone's progress. Never commit this file.
"""
import sqlite3
from datetime import datetime, timezone

from flask import g
from werkzeug.security import generate_password_hash

from .. import config
from ..core import srs

PROGRESS_DB = config.PROGRESS_DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    q_code     TEXT NOT NULL,
    chosen     TEXT,
    correct    INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attempts_user_q ON attempts(user_id, q_code);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path=PROGRESS_DB):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # safe with 2 gunicorn workers
    return conn


def init_db(path=PROGRESS_DB):
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        srs.init_db(conn)
        # cards for mistakes saved before the review engine existed
        conn.execute(
            """INSERT OR IGNORE INTO srs_cards (user_id, q_code, lapses, interval_days, due)
               SELECT user_id, q_code, SUM(1 - correct), 0, ?
               FROM attempts GROUP BY user_id, q_code HAVING SUM(1 - correct) > 0""",
            (srs.today().isoformat(),))


def get_db():
    if "progress_db" not in g:
        g.progress_db = connect()
    return g.progress_db


def close_db(_exc=None):
    conn = g.pop("progress_db", None)
    if conn is not None:
        conn.close()


def create_user(username, password, path=PROGRESS_DB):
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username.strip(), generate_password_hash(password), now_iso()),
        )


def set_password(username, password, path=PROGRESS_DB):
    with connect(path) as conn:
        cur = conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (generate_password_hash(password), username.strip()),
        )
        return cur.rowcount > 0

