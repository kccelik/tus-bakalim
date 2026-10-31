
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from functools import wraps

from flask import (Blueprint, g, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROGRESS_DB = os.environ.get("TUS_PROGRESS_DB", os.path.join(BASE_DIR, "progress.db"))
SECRET_KEY_FILE = os.environ.get("TUS_SECRET_KEY_FILE", os.path.join(BASE_DIR, "secret_key.txt"))

# Ask for the password on every page open/refresh (set TUS_ASK_EVERY_LOAD=0
# to stay logged in until the browser is closed instead)
ASK_EVERY_LOAD = os.environ.get("TUS_ASK_EVERY_LOAD", "1") != "0"


def is_page_navigation():
    """True for a top-level page load (typing the URL, refresh, link click),
    False for images, fetch() calls etc. made by an already open page."""
    if request.method != "GET" or request.path.startswith("/api/"):
        return False
    dest = request.headers.get("Sec-Fetch-Dest")
    if dest:
        return dest in ("document", "iframe")
    accept = request.headers.get("Accept", "")
    return "text/html" in accept


# Paths that work without being logged in
PUBLIC_ENDPOINTS = {"auth.login", "static"}

bp = Blueprint("auth", __name__)

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


# ---------- database ----------

def connect(path=PROGRESS_DB):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # safe with 2 gunicorn workers
    return conn


def init_db(path=PROGRESS_DB):
    with connect(path) as conn:
        conn.executescript(SCHEMA)


def get_db():
    if "progress_db" not in g:
        g.progress_db = connect()
    return g.progress_db


def close_db(_exc=None):
    conn = g.pop("progress_db", None)
    if conn is not None:
        conn.close()


# ---------- secret key ----------

def load_secret_key(path=SECRET_KEY_FILE):
    """Read the key from a file; create it once if missing (never in Git)."""
    if os.environ.get("TUS_SECRET_KEY"):
        return os.environ["TUS_SECRET_KEY"]
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    except FileExistsError:
        pass  # another gunicorn worker created it first
    with open(path) as f:
        return f.read().strip()


# ---------- users ----------

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


def current_user():
    uid = session.get("user_id")
    if uid is None:
        return None
    if "user" not in g:
        g.user = get_db().execute(
            "SELECT id, username FROM users WHERE id = ?", (uid,)
        ).fetchone()
    return g.user


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            if request.path.startswith("/api/"):
                return jsonify(error="login required"), 401
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


# ---------- routes ----------

@bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        row = get_db().execute(
            "SELECT id, password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row and check_password_hash(row["password_hash"], password):
            session.clear()
            session.permanent = False  # cookie dies when the browser closes
            session["user_id"] = row["id"]
            session["fresh"] = True    # allows exactly one page load
            nxt = request.args.get("next", "/")
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = "/"
            return redirect(nxt)
        error = "Kullanıcı adı veya şifre hatalı."
    return render_template("login.html", error=error)


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/api/me")
@login_required
def api_me():
    return jsonify(username=current_user()["username"])


@bp.route("/api/attempt", methods=["POST"])
@login_required
def api_attempt():
    data = request.get_json(silent=True) or {}
    q_code = str(data.get("q_code", "")).strip()
    if not q_code:
        return jsonify(error="q_code missing"), 400
    chosen = data.get("chosen")
    chosen = str(chosen).strip().upper()[:1] if chosen else None
    correct = 1 if data.get("correct") else 0
    db = get_db()
    db.execute(
        "INSERT INTO attempts (user_id, q_code, chosen, correct, created_at) VALUES (?, ?, ?, ?, ?)",
        (current_user()["id"], q_code, chosen, correct, now_iso()),
    )
    db.commit()
    return jsonify(ok=True)


@bp.route("/api/progress")
@login_required
def api_progress():
    """Per question: attempt count, wrong count, and the latest answer.

    The page uses this to mark answered questions, build the
    "my mistakes" filter (last_correct == 0) and per-subject stats.
    """
    rows = get_db().execute(
        """
        SELECT a.q_code,
               COUNT(*)                         AS n,
               SUM(CASE WHEN a.correct = 0 THEN 1 ELSE 0 END) AS n_wrong,
               (SELECT chosen  FROM attempts b WHERE b.user_id = a.user_id AND b.q_code = a.q_code
                 ORDER BY b.id DESC LIMIT 1)    AS last_chosen,
               (SELECT correct FROM attempts b WHERE b.user_id = a.user_id AND b.q_code = a.q_code
                 ORDER BY b.id DESC LIMIT 1)    AS last_correct,
               MAX(a.created_at)                AS last_at
        FROM attempts a
        WHERE a.user_id = ?
        GROUP BY a.q_code
        """,
        (current_user()["id"],),
    ).fetchall()
    return jsonify({r["q_code"]: dict(r) for r in rows})


@bp.route("/api/progress/<q_code>", methods=["DELETE"])
@login_required
def api_reset_question(q_code):
    """Forget one question (e.g. to take it off the mistakes list)."""
    db = get_db()
    db.execute("DELETE FROM attempts WHERE user_id = ? AND q_code = ?",
               (current_user()["id"], q_code))
    db.commit()
    return jsonify(ok=True)


# ---------- wiring ----------

def init_auth(app):
    from datetime import timedelta

    app.secret_key = load_secret_key()
    app.config.setdefault("PERMANENT_SESSION_LIFETIME", timedelta(days=60))
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    init_db()
    app.register_blueprint(bp)
    app.teardown_appcontext(close_db)

    @app.before_request
    def require_login_everywhere():
        if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
            return None
        if current_user() is None:
            if request.path.startswith("/api/"):
                return jsonify(error="login required"), 401
            return redirect(url_for("auth.login", next=request.path))
        # Ask again on every page open/refresh: a login is good for one
        # page load; images and API calls from that page keep working.
        if ASK_EVERY_LOAD and is_page_navigation():
            if session.pop("fresh", False):
                return None
            session.clear()
            return redirect(url_for("auth.login", next=request.path))
        return None

    @app.context_processor
    def inject_user():
        u = current_user()
        return {"current_username": u["username"] if u else None}