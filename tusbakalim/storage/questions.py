"""Read access to the question bank (instance/tus_database_v2.db).
The bank is built by scanning/build_database_v2.py."""
import json
import re
import sqlite3

from .. import config
from ..core.subjects import get_subject, turkish_lower

DB_PATH = config.QUESTION_DB


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.create_function("TR_LOWER", 1, turkish_lower)
    return conn


def row_to_question(r, subject=None):
    keys = r.keys()
    q = {
        "id": r["id"],
        "q_code": r["q_code"],
        "exam_name": r["exam_name"],
        "q_num": r["q_num"],
        "subject": subject or get_subject(r["exam_name"], r["q_num"]),
        "vignette": r["vignette"],
        "options": json.loads(r["options_json"]) if r["options_json"] else {},
        "correct_opt": r["correct_opt"],
        "image_path": r["image_path"],
    }
    # filled later by the explanation batch job (step 4), if present
    for extra in ("topic", "explanation", "tip"):
        if extra in keys and r[extra]:
            q[extra] = r[extra]
    return q



_META = None


def question_meta():
    """q_code -> exam, number, subject, year for all questions (cached;
    restart the app after rebuilding the question database)."""
    global _META
    if _META is None:
        conn = get_db_connection()
        rows = conn.execute("SELECT q_code, exam_name, q_num FROM questions").fetchall()
        conn.close()
        _META = {}
        for r in rows:
            m = re.search(r"(20\d\d)", r["exam_name"] or "")
            _META[r["q_code"]] = {
                "exam_name": r["exam_name"], "q_num": r["q_num"],
                "subject": get_subject(r["exam_name"], r["q_num"]),
                "year": m.group(1) if m else None,
            }
    return _META


def fetch_questions_by_codes(codes):
    if not codes:
        return []
    conn = get_db_connection()
    out = {}
    for i in range(0, len(codes), 500):
        chunk = codes[i:i + 500]
        for r in conn.execute(
                f"SELECT * FROM questions WHERE q_code IN ({','.join('?' * len(chunk))})", chunk):
            out[r["q_code"]] = row_to_question(r)
    conn.close()
    return [out[c] for c in codes if c in out]

