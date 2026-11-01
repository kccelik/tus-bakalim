"""Personal progress: saving answers, statistics, history and the daily review.
All routes need a login (enforced by auth.configure)."""
from collections import Counter, defaultdict

from flask import Blueprint, jsonify, request

from ..core import srs
from ..core.srs import day_stats, due_cards, history, record_answer, summary
from ..core.subjects import SUBJECTS
from ..storage.progress import get_db, now_iso
from ..storage.questions import fetch_questions_by_codes, question_meta
from .auth import current_user, login_required

get_progress_db = get_db

bp = Blueprint("study", __name__)


def _ctx():
    return get_db(), current_user()["id"]


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
    card = srs.record_answer(db, current_user()["id"], q_code, bool(correct))
    db.commit()
    return jsonify(ok=True, card=dict(card) if card else None)


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



def my_wrong_codes():
    """Questions whose latest answer by the current user was wrong."""
    rows = get_progress_db().execute(
        """SELECT q_code, correct FROM attempts WHERE user_id = ? ORDER BY id""",
        (current_user()["id"],)).fetchall()
    last = {}
    for r in rows:
        last[r["q_code"]] = r["correct"]
    return [c for c, ok in last.items() if not ok]


@bp.route("/api/me/subjects")
def api_me_subjects():
    """Per subject: questions in the bank, solved, accuracy, open mistakes, due reviews."""
    meta = question_meta()
    uid = current_user()["id"]
    pdb = get_progress_db()
    bank = Counter(m["subject"] for m in meta.values())
    s = defaultdict(lambda: {"answers": 0, "correct": 0, "solved": set(), "last": {}})
    for r in pdb.execute("SELECT q_code, correct FROM attempts WHERE user_id = ? ORDER BY id", (uid,)):
        m = meta.get(r["q_code"])
        if not m:
            continue
        d = s[m["subject"]]
        d["answers"] += 1
        d["correct"] += r["correct"]
        d["solved"].add(r["q_code"])
        d["last"][r["q_code"]] = r["correct"]
    due = Counter()
    cards = Counter()
    today = srs.today().isoformat()
    for r in pdb.execute("SELECT q_code, due, suspended FROM srs_cards WHERE user_id = ?", (uid,)):
        m = meta.get(r["q_code"])
        if not m or r["suspended"]:
            continue
        cards[m["subject"]] += 1
        if r["due"] <= today:
            due[m["subject"]] += 1
    out = []
    for subj in SUBJECTS + sorted(set(bank) - set(SUBJECTS)):
        d = s[subj]
        out.append({
            "subject": subj, "bank": bank.get(subj, 0), "solved": len(d["solved"]),
            "answers": d["answers"], "correct": d["correct"],
            "accuracy": round(100 * d["correct"] / d["answers"], 1) if d["answers"] else None,
            "open_mistakes": sum(1 for ok in d["last"].values() if not ok),
            "cards": cards.get(subj, 0), "due": due.get(subj, 0),
        })
    return jsonify(out)


@bp.route("/api/me/history")
def api_me_history():
    """Latest answers with exam / number / subject, newest first."""
    meta = question_meta()
    limit = min(int(request.args.get("limit", 100)), 1000)
    rows = srs.history(get_progress_db(), current_user()["id"], limit)
    for r in rows:
        r.update(meta.get(r["q_code"], {}))
    return jsonify(rows)


@bp.route("/api/review/session")
def api_review_session():
    """Due cards today with full question data; optional ?subject= filter."""
    subject = request.args.get("subject", "")
    meta = question_meta()
    due = srs.due_cards(get_progress_db(), current_user()["id"])
    per_subject = Counter(meta[c["q_code"]]["subject"] for c in due if c["q_code"] in meta)
    if subject:
        due = [c for c in due if meta.get(c["q_code"], {}).get("subject") == subject]
    qs = {q["q_code"]: q for q in fetch_questions_by_codes([c["q_code"] for c in due[:200]])}
    items = []
    for c in due[:200]:
        if c["q_code"] in qs:
            items.append(dict(qs[c["q_code"]], card=c))
    return jsonify(total=sum(per_subject.values()), per_subject=per_subject, items=items)



@bp.route("/api/stats")
def api_stats():
    db, uid = _ctx()
    days = min(int(request.args.get("days", 60)), 365)
    return jsonify(summary=summary(db, uid), days=day_stats(db, uid, days))


@bp.route("/api/history")
def api_history():
    db, uid = _ctx()
    return jsonify(history(db, uid, min(int(request.args.get("limit", 200)), 2000)))


@bp.route("/api/review/due")
def api_review_due():
    """Cards due today. The page joins q_code with the question data
    (subject, text, options) and can filter/group by subject itself."""
    db, uid = _ctx()
    return jsonify(due_cards(db, uid, request.args.get("limit")))


@bp.route("/api/review/cards")
def api_review_cards():
    db, uid = _ctx()
    rows = db.execute("SELECT * FROM srs_cards WHERE user_id = ?", (uid,)).fetchall()
    return jsonify({r["q_code"]: dict(r) for r in rows})


@bp.route("/api/review/<q_code>", methods=["POST"])
def api_review_answer(q_code):
    """Answer from the review page: {"correct": bool, "chosen": "B", "grade": "good"}"""
    db, uid = _ctx()
    data = request.get_json(silent=True) or {}
    correct = 1 if data.get("correct") else 0
    chosen = data.get("chosen")
    chosen = str(chosen).strip().upper()[:1] if chosen else None
    db.execute(
        "INSERT INTO attempts (user_id, q_code, chosen, correct, created_at) VALUES (?, ?, ?, ?, ?)",
        (uid, q_code, chosen, correct, now_iso()))
    card = record_answer(db, uid, q_code, bool(correct), data.get("grade"))
    db.commit()
    return jsonify(ok=True, card=dict(card) if card else None)


@bp.route("/api/review/<q_code>/suspend", methods=["POST"])
def api_review_suspend(q_code):
    """Take a card out of the daily review (e.g. a cancelled question)."""
    db, uid = _ctx()
    on = 0 if (request.get_json(silent=True) or {}).get("unsuspend") else 1
    db.execute("UPDATE srs_cards SET suspended = ? WHERE user_id = ? AND q_code = ?",
               (on, uid, q_code))
    db.commit()
    return jsonify(ok=True)

