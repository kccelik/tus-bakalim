"""Login, logout, password change and the login guard.

A login is remembered for config.LOGIN_HOURS (24h), counted from the moment
of login; after that, or after logout, every page asks for the password.
"""
import os
import secrets
import time
from datetime import timedelta
from functools import wraps

from flask import (Blueprint, g, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash

from .. import config
from ..storage.progress import get_db, set_password

LOGIN_HOURS = config.LOGIN_HOURS
SECRET_KEY_FILE = config.SECRET_KEY_FILE

# Paths that work without being logged in
PUBLIC_ENDPOINTS = {"auth.login", "auth.change_password", "static"}

bp = Blueprint("auth", __name__)


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


def login_expired():
    login_at = session.get("login_at")
    return login_at is None or time.time() - login_at > LOGIN_HOURS * 3600


def current_user():
    uid = session.get("user_id")
    if uid is None:
        return None
    if login_expired():
        session.clear()
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
            session.permanent = True   # cookie survives closing the browser
            session["user_id"] = row["id"]
            session["login_at"] = time.time()
            session["fresh"] = True    # allows exactly one page load
            nxt = request.args.get("next", "/")
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = "/"
            return redirect(nxt)
        error = "Kullanıcı adı veya şifre hatalı."
    return render_template("login.html", error=error)


@bp.route("/password", methods=["GET", "POST"])
def change_password():
    error = message = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        old = request.form.get("old_password", "")
        new = request.form.get("new_password", "")
        new2 = request.form.get("new_password2", "")
        row = get_db().execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
        if not row or not check_password_hash(row["password_hash"], old):
            error = "Kullanıcı adı veya mevcut şifre hatalı."
        elif len(new) < 6:
            error = "Yeni şifre en az 6 karakter olmalı."
        elif new != new2:
            error = "Yeni şifreler eşleşmiyor."
        else:
            set_password(username, new)
            message = "Şifren değişti. Artık yeni şifrenle giriş yapabilirsin."
    return render_template("password.html", error=error, message=message)



@bp.route("/logout")
def logout():
    session.clear()
    resp = redirect(url_for("auth.login"))
    resp.headers["Clear-Site-Data"] = '"cache"'   # drop cached pages too
    return resp


@bp.route("/api/me")
@login_required
def api_me():
    return jsonify(username=current_user()["username"])



def configure(app):
    """Secret key, cookie settings and the login guard for every request."""
    app.secret_key = load_secret_key()
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=config.LOGIN_HOURS)
    # don't push the expiry forward on every request: 24h from login, then ask again
    app.config["SESSION_REFRESH_EACH_REQUEST"] = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if os.environ.get("TUS_HTTPS") == "1":
        app.config["SESSION_COOKIE_SECURE"] = True

    @app.before_request
    def require_login_everywhere():
        if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
            return None
        if current_user() is None:
            if request.path.startswith("/api/"):
                return jsonify(error="login required"), 401
            return redirect(url_for("auth.login", next=request.path))
        if config.ASK_EVERY_LOAD and is_page_navigation():
            if session.pop("fresh", False):
                return None
            session.clear()
            return redirect(url_for("auth.login", next=request.path))
        return None

    @app.after_request
    def no_cache_for_private_pages(resp):
        # Without this the browser keeps logged-in pages in its cache and the
        # Back button shows them again after logout.
        if resp.mimetype in ("text/html", "application/json"):
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
        return resp

    @app.context_processor
    def inject_user():
        u = current_user()
        return {"current_username": u["username"] if u else None}
