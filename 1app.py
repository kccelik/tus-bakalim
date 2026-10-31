import os
import json
import sqlite3
import re
from flask import Flask, render_template, request, jsonify, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# v2 veritabanı varsa onu kullan (build_database_v2.py), yoksa eskisi
DB_PATH = os.path.join(BASE_DIR, "tus_database_v2.db")
if not os.path.exists(DB_PATH):
    DB_PATH = os.path.join(BASE_DIR, "tus_database.db")
CLEAN_IMG_DIR = os.path.join(BASE_DIR, "exports", "clean_images")

app = Flask(__name__, template_folder="templates", static_folder="static")
from auth import init_auth
init_auth(app)

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

    subjects = [
        "Anatomi", "Histoloji ve Embriyoloji", "Fizyoloji", "Tıbbi Biyokimya",
        "Tıbbi Mikrobiyoloji", "Tıbbi Patoloji", "Tıbbi Farmakoloji",
        "Dahiliye Grubu", "Pediatri", "Genel Cerrahi", "Küçük Stajlar", "Kadın Hastalıkları ve Doğum"
    ]
    return render_template("index.html", 
                           exams_json=exams_json_str, 
                           sorted_years=sorted_years, 
                           subjects=subjects, 
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

        questions.append({
            "id": r["id"],
            "q_code": r["q_code"],
            "exam_name": r["exam_name"],
            "q_num": r["q_num"],
            "subject": q_subj,
            "vignette": r["vignette"],
            "options": json.loads(r["options_json"]) if r["options_json"] else {},
            "correct_opt": r["correct_opt"],
            "image_path": r["image_path"]
        })
    conn.close()
    return jsonify(questions)

@app.route("/exports/clean_images/<path:filename>")
def serve_image(filename):
    return send_from_directory(CLEAN_IMG_DIR, filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)