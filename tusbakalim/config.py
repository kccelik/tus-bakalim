"""All paths and settings in one place.

Private runtime files (databases, secret key) live in instance/, which is
never committed. Every value can be overridden with an environment variable.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTANCE_DIR = os.environ.get("TUS_INSTANCE_DIR", os.path.join(ROOT, "instance"))


def _instance_file(name, env):
    """instance/<name>; falls back to the old location in the project root
    so an existing install keeps its data until the file is moved."""
    if os.environ.get(env):
        return os.environ[env]
    new = os.path.join(INSTANCE_DIR, name)
    old = os.path.join(ROOT, name)
    if not os.path.exists(new) and os.path.exists(old):
        return old
    return new


QUESTION_DB = _instance_file("tus_database_v2.db", "TUS_QUESTION_DB")
PROGRESS_DB = _instance_file("progress.db", "TUS_PROGRESS_DB")
SECRET_KEY_FILE = _instance_file("secret_key.txt", "TUS_SECRET_KEY_FILE")

PDF_DIR = os.path.join(ROOT, "data")                    # source exam PDFs (private)
EXPORTS_DIR = os.path.join(ROOT, "exports")
CLEAN_IMG_DIR = os.path.join(EXPORTS_DIR, "clean_images")

# A login is remembered this many hours from the moment of login.
LOGIN_HOURS = float(os.environ.get("TUS_LOGIN_HOURS", "24"))
# Old behaviour: ask for the password on every page load.
ASK_EVERY_LOAD = os.environ.get("TUS_ASK_EVERY_LOAD", "0") == "1"

TIMEZONE = os.environ.get("TUS_TZ", "Europe/Istanbul")
PORT = int(os.environ.get("TUS_PORT", "5050"))
# Never on a reachable server: the debugger lets visitors run code.
DEBUG = os.environ.get("TUS_DEBUG") == "1"
