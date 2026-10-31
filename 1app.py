import os
import json
import sqlite3
import re
from collections import Counter, defaultdict
from flask import Flask, render_template, request, jsonify, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# v2 veritabanı varsa onu kullan (build_database_v2.py), yoksa eskisi
DB_PATH = os.path.join(BASE_DIR, "tus_database_v2.db")
if not os.path.exists(DB_PATH):
    DB_PATH = os.path.join(BASE_DIR, "tus_database.db")
CLEAN_IMG_DIR = os.path.join(BASE_DIR, "exports", "clean_images")

app = Flask(__name__, template_folder="templates", static_folder="static")
from auth import init_auth, current_user, get_db as get_progress_db
import srs
init_auth(app)

SUBJECTS = [
    "Anatomi", "Histoloji ve Embriyoloji", "Fizyoloji", "Tıbbi Biyokimya",
    "Tıbbi Mikrobiyoloji", "Tıbbi Patoloji", "Tıbbi Farmakoloji",
    "Dahiliye Grubu", "Pediatri", "Genel Cerrahi", "Küçük Stajlar", "Kadın Hastalıkları ve Doğum"
]

def turkish_lower(text):
    if not text:
        return ""
    replacements = {'İ': 'i', 'I': 'ı', 'Ş': 'ş', 'Ğ': 'ğ', 'Ü': 'ü', 'Ö': 'ö', 'Ç': 'ç'}
    for u, l in replacements.items():
        text = text.replace(u, l)
    return text.lower()

def get_subject(exam_name, q_num):
    name_low = exam_name.lower()
    # v2: 2009-2010 kitapçıkları 200 soru (Temel 1-100 + Klinik 101-200),
    #     2019-2020 kitapçıkları 240 soru (Temel 1-120 + Klinik 121-240)
    if ("2009" in name_low or "2010" in name_low) and q_num > 100:
        return get_subject(exam_name + " klinik", q_num - 100)
    if ("2019" in name_low or "2020" in name_low) and q_num > 120:
        return get_subject(exam_name + " klinik", q_num - 120)
    
    # 1. GÜNCEL SİSTEM (2024 ve Sonrası - 200 Soru)
    if "2024" in name_low or "2025" in name_low or "2026" in name_low:
        if 1 <= q_num <= 13: return "Anatomi"
        if 14 <= q_num <= 20: return "Histoloji ve Embriyoloji"
        if 21 <= q_num <= 28: return "Fizyoloji"
        if 29 <= q_num <= 46: return "Tıbbi Biyokimya"
        if 47 <= q_num <= 64: return "Tıbbi Mikrobiyoloji"
        if 65 <= q_num <= 82: return "Tıbbi Patoloji"
        if 83 <= q_num <= 100: return "Tıbbi Farmakoloji"
        if 101 <= q_num <= 123: return "Dahiliye Grubu"
        if 124 <= q_num <= 148: return "Pediatri"
        if 149 <= q_num <= 168: return "Genel Cerrahi"
        if 169 <= q_num <= 190: return "Küçük Stajlar"
        if 191 <= q_num <= 200: return "Kadın Hastalıkları ve Doğum"

    # 2. 240 SORULUK SİSTEM (2021 - 2022)
    if ("2021" in name_low or "2022" in name_low) and q_num > 120:
        k_num = q_num - 120
        if 1 <= k_num <= 30: return "Dahiliye Grubu"
        if 31 <= k_num <= 60: return "Pediatri"
        if 61 <= k_num <= 85: return "Genel Cerrahi"
        if 86 <= k_num <= 108: return "Küçük Stajlar"
        if 109 <= k_num <= 120: return "Kadın Hastalıkları ve Doğum"

    # 3. KLİNİK KİTAPÇIKLARI
    if "klinik" in name_low:
        if 1 <= q_num <= 30: return "Dahiliye Grubu"
        if 31 <= q_num <= 60: return "Pediatri"
        if 61 <= q_num <= 85: return "Genel Cerrahi"
        if 86 <= q_num <= 108: return "Küçük Stajlar"
        if 109 <= q_num <= 120: return "Kadın Hastalıkları ve Doğum"
        return "Klinik Bilimler"

    # 4. TEMEL BİLİMLER (120 Soruluk Dönem: 2012-2020)
    if any(str(y) in name_low for y in range(2012, 2021)) or (q_num <= 120 and ("2021" in name_low or "2022" in name_low)):
        if 1 <= q_num <= 14: return "Anatomi"
        if 15 <= q_num <= 22: return "Histoloji ve Embriyoloji"
        if 23 <= q_num <= 32: return "Fizyoloji"
        if 33 <= q_num <= 54: return "Tıbbi Biyokimya"
        if 55 <= q_num <= 76: return "Tıbbi Mikrobiyoloji"
        if 77 <= q_num <= 98: return "Tıbbi Patoloji"
        if 99 <= q_num <= 120: return "Tıbbi Farmakoloji"

    # 5. KLASİK 100 SORULUK DÖNEM (2006-2011)
    if 1 <= q_num <= 14: return "Anatomi"
    if 15 <= q_num <= 22: return "Histoloji ve Embriyoloji"
    if 23 <= q_num <= 32: return "Fizyoloji"
    if 33 <= q_num <= 54: return "Tıbbi Biyokimya"
    if 55 <= q_num <= 76: return "Tıbbi Mikrobiyoloji"
    if 77 <= q_num <= 88: return "Tıbbi Patoloji"
    if 89 <= q_num <= 100: return "Tıbbi Farmakoloji"

    return "Genel Tıp"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.create_function("TR_LOWER", 1, turkish_lower)
    return conn

@app.route("/")
def index():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT exam_name FROM questions ORDER BY exam_name ASC")
    raw_exams = [r["exam_name"] for r in cur.fetchall()]
    cur.execute("SELECT COUNT(*) FROM questions")
    total_q = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM questions WHERE image_path IS NOT NULL")
    total_img_q = cur.fetchone()[0]
    conn.close()

    # Sınavları yıllara göre ayır
    exams_by_year = {}
    for ex in raw_exams:
        m = re.search(r'(20\d\d)', ex)
        year = m.group(1) if m else "Diğer"
        exams_by_year.setdefault(year, []).append(ex)

    sorted_years = sorted([y for y in exams_by_year.keys() if y != "Diğer"], reverse=True)
    if "Diğer" in exams_by_year:
        sorted_years.append("Diğer")

    # Python tarafında temiz JSON dökümü hazırlıyoruz
    exams_json_str = json.dumps(exams_by_year, ensure_ascii=False)

    return render_template("index.html", 
                           exams_json=exams_json_str, 
                           sorted_years=sorted_years, 
                           subjects=SUBJECTS, 
                           total_q=total_q, 
                           total_img_q=total_img_q)

@app.route("/api/questions")
def get_questions():
    exam = request.args.get("exam", "")
    year = request.args.get("year", "")
    subject = request.args.get("subject", "")
    query = request.args.get("q", "").strip()
    visual_only = request.args.get("visual", "0")
    limit = int(request.args.get("limit", 250))
    
    conn = get_db_connection()
    cur = conn.cursor()

    sql = "SELECT * FROM questions WHERE 1=1"
    params = []

    if exam:
        sql += " AND exam_name = ?"
        params.append(exam)
    elif year and year != "all":
        sql += " AND exam_name LIKE ?"
        params.append(f"%{year}%")

    if visual_only == "1":
        sql += " AND image_path IS NOT NULL"

    if request.args.get("mistakes") == "1":
        codes = my_wrong_codes()
        if not codes:
            conn.close()
            return jsonify([])
        sql += f" AND q_code IN ({','.join('?' * len(codes))})"
        params.extend(codes)
        
    if query:
        norm_query = turkish_lower(query)
        sql += " AND (TR_LOWER(vignette) LIKE ? OR TR_LOWER(options_json) LIKE ?)"
        params.append(f"%{norm_query}%")
        params.append(f"%{norm_query}%")

    sql += " ORDER BY exam_name DESC, q_num ASC LIMIT ?"
    params.append(limit)

    cur.execute(sql, params)
    rows = cur.fetchall()
    
    questions = []
    for r in rows:
        q_subj = get_subject(r["exam_name"], r["q_num"])
        if subject and q_subj != subject:
            continue

        questions.append(row_to_question(r, q_subj))
    conn.close()
    return jsonify(questions)

# ---------- personal progress (uses progress.db via auth/srs) ----------

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


def my_wrong_codes():
    """Questions whose latest answer by the current user was wrong."""
    rows = get_progress_db().execute(
        """SELECT q_code, correct FROM attempts WHERE user_id = ? ORDER BY id""",
        (current_user()["id"],)).fetchall()
    last = {}
    for r in rows:
        last[r["q_code"]] = r["correct"]
    return [c for c, ok in last.items() if not ok]


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


@app.route("/api/questions/by_codes", methods=["POST"])
def api_questions_by_codes():
    codes = [str(c) for c in (request.get_json(silent=True) or {}).get("codes", [])][:2000]
    return jsonify(fetch_questions_by_codes(codes))


@app.route("/api/me/subjects")
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


@app.route("/api/me/history")
def api_me_history():
    """Latest answers with exam / number / subject, newest first."""
    meta = question_meta()
    limit = min(int(request.args.get("limit", 100)), 1000)
    rows = srs.history(get_progress_db(), current_user()["id"], limit)
    for r in rows:
        r.update(meta.get(r["q_code"], {}))
    return jsonify(rows)


@app.route("/api/review/session")
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


@app.route("/exports/clean_images/<path:filename>")
def serve_image(filename):
    return send_from_directory(CLEAN_IMG_DIR, filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)