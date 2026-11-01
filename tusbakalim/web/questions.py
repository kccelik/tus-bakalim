"""Main page, question search and question images."""
import json
import re

from flask import Blueprint, jsonify, render_template, request, send_from_directory

from .. import config
from ..core.subjects import SUBJECTS, get_subject, turkish_lower
from ..storage.questions import (fetch_questions_by_codes, get_db_connection,
                                 row_to_question)
from .study import my_wrong_codes

CLEAN_IMG_DIR = config.CLEAN_IMG_DIR

bp = Blueprint("questions", __name__)


@bp.route("/")
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


@bp.route("/api/questions")
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


@bp.route("/api/questions/by_codes", methods=["POST"])
def api_questions_by_codes():
    codes = [str(c) for c in (request.get_json(silent=True) or {}).get("codes", [])][:2000]
    return jsonify(fetch_questions_by_codes(codes))


@bp.route("/exports/clean_images/<path:filename>")
def serve_image(filename):
    return send_from_directory(CLEAN_IMG_DIR, filename)

