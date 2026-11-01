"""
Spaced repetition (Anki-style) and personal statistics for TusBakalım.

Registered automatically by auth.init_auth(app) - no change to 1app.py.

How cards work
  * A question becomes a review card the first time the user gets it WRONG.
  * Every later answer to that question (from the normal page or the review
    page) reschedules it with a simplified SM-2 algorithm, like Anki:
        wrong  -> back to the start, due tomorrow, lapses + 1
        right  -> 1 day, then 3 days, then interval x ease (2.5 by default)
  * The review page can also send a grade: again / hard / good / easy.
  * A card counts as "learned" once its interval reaches 21 days.

Days are counted in TUS_TZ (default Europe/Istanbul).
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .. import config

TZ = ZoneInfo(config.TIMEZONE)
LEARNED_DAYS = 21

SCHEMA = """
CREATE TABLE IF NOT EXISTS srs_cards (
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    q_code        TEXT NOT NULL,
    ease          REAL NOT NULL DEFAULT 2.5,
    interval_days INTEGER NOT NULL DEFAULT 0,
    reps          INTEGER NOT NULL DEFAULT 0,
    lapses        INTEGER NOT NULL DEFAULT 0,
    due           TEXT NOT NULL,          -- YYYY-MM-DD in TUS_TZ
    last_review   TEXT,
    suspended     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, q_code)
);
CREATE INDEX IF NOT EXISTS idx_srs_due ON srs_cards(user_id, suspended, due);
"""


def today():
    return datetime.now(TZ).date()


def local_day(iso_ts):
    """UTC ISO timestamp from attempts.created_at -> local date string."""
    return datetime.fromisoformat(iso_ts).astimezone(TZ).date().isoformat()


def init_db(conn):
    conn.executescript(SCHEMA)


def schedule(card, grade, on=None):
    """Return new (ease, interval_days, reps, lapses, due) for a grade.

    grade: 'again' | 'hard' | 'good' | 'easy'
    card:  dict-like with ease, interval_days, reps, lapses (or None for new)
    """
    on = on or today()
    ease = card["ease"] if card else 2.5
    interval = card["interval_days"] if card else 0
    reps = card["reps"] if card else 0
    lapses = card["lapses"] if card else 0

    if grade == "again":
        lapses += 1
        reps = 0
        ease = max(1.3, ease - 0.2)
        interval = 1
    else:
        if grade == "hard":
            ease = max(1.3, ease - 0.15)
        elif grade == "easy":
            ease = ease + 0.15
        if reps == 0:
            interval = 1 if grade != "easy" else 3
        elif reps == 1:
            interval = 3 if grade != "easy" else 5
        else:
            factor = {"hard": 1.2, "good": ease, "easy": ease * 1.3}[grade]
            interval = max(interval + 1, round(interval * factor))
        reps += 1
    return ease, interval, reps, lapses, (on + timedelta(days=interval)).isoformat()


def record_answer(conn, user_id, q_code, correct, grade=None):
    """Called for every saved attempt. Creates a card on the first mistake,
    reschedules existing cards. Returns the card row (or None)."""
    card = conn.execute(
        "SELECT * FROM srs_cards WHERE user_id = ? AND q_code = ?", (user_id, q_code)
    ).fetchone()
    if card is None and correct:
        return None  # right on the first try: nothing to review
    if grade not in ("again", "hard", "good", "easy"):
        grade = "good" if correct else "again"
    if not correct:
        grade = "again"
    ease, interval, reps, lapses, due = schedule(card, grade)
    conn.execute(
        """INSERT INTO srs_cards (user_id, q_code, ease, interval_days, reps, lapses, due, last_review)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, q_code) DO UPDATE SET
             ease = excluded.ease, interval_days = excluded.interval_days,
             reps = excluded.reps, lapses = excluded.lapses,
             due = excluded.due, last_review = excluded.last_review""",
        (user_id, q_code, ease, interval, reps, lapses, due, today().isoformat()),
    )
    return conn.execute(
        "SELECT * FROM srs_cards WHERE user_id = ? AND q_code = ?", (user_id, q_code)
    ).fetchone()


def day_stats(conn, user_id, days=60):
    """Questions answered per local day for the last `days` days (oldest first)."""
    rows = conn.execute(
        "SELECT q_code, correct, created_at FROM attempts WHERE user_id = ?", (user_id,)
    ).fetchall()
    start = today() - timedelta(days=days - 1)
    per = {(start + timedelta(days=i)).isoformat(): {"n": 0, "correct": 0, "q": set()}
           for i in range(days)}
    for r in rows:
        d = local_day(r["created_at"])
        if d in per:
            per[d]["n"] += 1
            per[d]["correct"] += r["correct"]
            per[d]["q"].add(r["q_code"])
    return [{"day": d, "answers": v["n"], "correct": v["correct"],
             "questions": len(v["q"])} for d, v in per.items()]


def streak(conn, user_id):
    """Consecutive days with at least one answer, ending today (or yesterday)."""
    days = {local_day(r["created_at"]) for r in conn.execute(
        "SELECT created_at FROM attempts WHERE user_id = ?", (user_id,))}
    d = today()
    if d.isoformat() not in days:
        d -= timedelta(days=1)
    n = 0
    while d.isoformat() in days:
        n += 1
        d -= timedelta(days=1)
    return n


def summary(conn, user_id):
    a = conn.execute(
        """SELECT COUNT(*) AS answers, COALESCE(SUM(correct), 0) AS correct,
                  COUNT(DISTINCT q_code) AS questions
           FROM attempts WHERE user_id = ?""", (user_id,)).fetchone()
    t = today().isoformat()
    c = conn.execute(
        """SELECT COUNT(*) AS cards,
                  SUM(CASE WHEN due <= ? AND suspended = 0 THEN 1 ELSE 0 END) AS due_today,
                  SUM(CASE WHEN interval_days >= ? THEN 1 ELSE 0 END) AS learned
           FROM srs_cards WHERE user_id = ?""", (t, LEARNED_DAYS, user_id)).fetchone()
    today_row = day_stats(conn, user_id, days=1)[0]
    return {
        "answers": a["answers"], "correct": a["correct"], "questions": a["questions"],
        "accuracy": round(100 * a["correct"] / a["answers"], 1) if a["answers"] else None,
        "today": today_row, "streak": streak(conn, user_id),
        "cards": c["cards"] or 0, "due_today": c["due_today"] or 0,
        "learned": c["learned"] or 0,
    }


def due_cards(conn, user_id, limit=None):
    t = today().isoformat()
    sql = """SELECT q_code, due, interval_days, reps, lapses, ease FROM srs_cards
             WHERE user_id = ? AND suspended = 0 AND due <= ?
             ORDER BY due, lapses DESC"""
    params = [user_id, t]
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    return [dict(r) for r in conn.execute(sql, params)]


def history(conn, user_id, limit=200):
    rows = conn.execute(
        """SELECT q_code, chosen, correct, created_at FROM attempts
           WHERE user_id = ? ORDER BY id DESC LIMIT ?""", (user_id, limit)).fetchall()
    return [dict(r, day=local_day(r["created_at"])) for r in rows]

