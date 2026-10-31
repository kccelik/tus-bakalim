import os
import re
import json
import sqlite3
import pymupdf

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(BASE_DIR, "tus_database.db")
IMAGES_DIR = os.path.join(BASE_DIR, "exports", "clean_images")
os.makedirs(IMAGES_DIR, exist_ok=True)

GORSEL_TETIKLEYICILER = [
    r'yukarıdaki\s+şekil', r'aşağıdaki\s+şekil', r'şekilde\s+gösterilen',
    r'şekildeki\s+[a-z0-9]', r'şekildeki\s+numaralanmış', r'şekilde\s+işaretli',
    r'yukarıdaki\s+grafik', r'aşağıdaki\s+grafik', r'elektrokardiyogram\s+trasesi',
    r'ekg\s+trasesi', r'ok\s+ile\s+gösterilen', r'işaretli\s+alan',
    r'işaretli\s+sinir', r'işaretli\s+yapı', r'işaretli\s+damar',
    r'yandaki\s+fotoğraf', r'yandaki\s+şekil', r'verilen\s+kesitte',
    r'mikroskobik\s+görünüm'
]

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            q_code TEXT UNIQUE,
            exam_type TEXT DEFAULT 'TUS',
            exam_name TEXT,
            q_num INTEGER,
            vignette TEXT,
            options_json TEXT,
            correct_opt TEXT,
            image_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def parse_answer_key(text):
    pattern = r'(?:^|\s)(\d{1,3})\s*[\.\-\s:]\s*([A-Ea-e]|İPTAL|IPTAL|iptal)\b'
    matches = re.findall(pattern, text)
    answers = {}
    for q_num_str, val in matches:
        q_num = int(q_num_str)
        val_clean = val.strip().upper()
        answers[q_num] = "İPTAL" if "İPTAL" in val_clean or "IPTAL" in val_clean else val_clean
    return answers

def extract_options_strict(text):
    opt_matches = list(re.finditer(r'(?:^|\s|\n)([A-Ea-e])\s*[\)\.\-]\s*', text))
    if not opt_matches:
        return text.strip(), {}

    first_opt_start = opt_matches[0].start()
    vignette = text[:first_opt_start].strip()
    
    options = {}
    for idx, match in enumerate(opt_matches):
        letter = match.group(1).upper()
        content_start = match.end()
        content_end = opt_matches[idx + 1].start() if idx + 1 < len(opt_matches) else len(text)
        opt_text = text[content_start:content_end].strip()
        opt_text = re.sub(r'\s+', ' ', opt_text)
        options[letter] = opt_text

    return vignette, options

# ==========================================
# 1. MOTOR: 2006 - 2008 KLASİK DÖNEMİ (100 SORU)
# ==========================================
def parse_era_2006_2008(doc, exam_name):
    full_text = ""
    for p_idx in range(len(doc)):
        page = doc[p_idx]
        p_num = p_idx + 1
        mid_x = page.rect.width / 2.0
        blocks = page.get_text("blocks")
        left = [b for b in blocks if b[0] < mid_x and b[6] == 0]
        right = [b for b in blocks if b[0] >= mid_x and b[6] == 0]
        left.sort(key=lambda b: b[1])
        right.sort(key=lambda b: b[1])
        for b in left: full_text += f"\n[P_{p_num}]\n" + b[4]
        for b in right: full_text += f"\n[P_{p_num}]\n" + b[4]

    chunks = re.split(r'\n(?=(?:\d{1,2}\s+)?\d{1,3}\s*[\.\)])', full_text)
    questions = {}
    for c in chunks:
        m = re.match(r'^(?:\d{1,2}\s+)?(\d{1,3})\s*[\.\)]\s*(.+)', c.strip(), re.DOTALL)
        if m:
            q_num = int(m.group(1))
            if 1 <= q_num <= 100:
                p_match = re.search(r'\[P_(\d+)\]', c)
                p_num = int(p_match.group(1)) if p_match else 1
                questions[q_num] = (p_num, m.group(2).strip())
    return questions, 100

# ==========================================
# 2. MOTOR: 2009 - 2010 BİLİM SINAVLARI DÖNEMİ (100 SORU)
# ==========================================
def parse_era_2009_2010(doc, exam_name):
    questions = {}
    q_start = re.compile(r'^(?:\d{1,2}\s+)?(\d{1,3})\s*[\.\)]\s*(.*)', re.DOTALL)
    
    for p_idx in range(1, len(doc)):
        page = doc[p_idx]
        p_num = p_idx + 1
        blocks = page.get_text("blocks")
        mid_x = page.rect.width / 2.0
        left = [b for b in blocks if b[0] < mid_x and b[6] == 0]
        right = [b for b in blocks if b[0] >= mid_x and b[6] == 0]
        left.sort(key=lambda b: b[1])
        right.sort(key=lambda b: b[1])
        
        col_text = "\n".join([b[4] for b in left + right if len(b[4].strip()) > 3])
        chunks = re.split(r'\n(?=(?:\d{1,2}\s+)?\d{1,3}\s*[\.\)])', col_text)
        for c in chunks:
            m = q_start.match(c.strip())
            if m:
                q_num = int(m.group(1))
                if 1 <= q_num <= 100:
                    questions[q_num] = (p_num, m.group(2).strip())
    return questions, 100

# ==========================================
# 3. MOTOR: 2011 - 2013 ÖSYM DÖNEMİ (120 SORU)
# ==========================================
def parse_era_2011_2013(doc, exam_name):
    questions = {}
    q_start = re.compile(r'^(?:\d{1,2}\s+)?(\d{1,3})\s*[\.\)\-]\s*(.*)', re.DOTALL)
    
    for p_idx in range(len(doc)):
        page = doc[p_idx]
        p_num = p_idx + 1
        text = page.get_text()
        if "AÇIKLAMA" in text and p_num <= 2:
            continue
            
        mid_x = page.rect.width / 2.0
        blocks = page.get_text("blocks")
        left = [b for b in blocks if b[0] < mid_x and b[6] == 0]
        right = [b for b in blocks if b[0] >= mid_x and b[6] == 0]
        left.sort(key=lambda b: b[1])
        right.sort(key=lambda b: b[1])
        
        col_text = "\n".join([b[4] for b in left + right])
        chunks = re.split(r'\n(?=(?:\d{1,2}\s+)?\d{1,3}\s*[\.\)\-])', col_text)
        for c in chunks:
            m = q_start.match(c.strip())
            if m:
                q_num = int(m.group(1))
                if 1 <= q_num <= 120:
                    questions[q_num] = (p_num, m.group(2).strip())
    return questions, 120

# ==========================================
# 4. MOTOR: 2014 - 2018 GEÇİŞ DÖNEMİ (120 SORU)
# ==========================================
def parse_era_2014_2018(doc, exam_name):
    questions = {}
    q_start = re.compile(r'^(?:\d{1,2}\s+)?(\d{1,3})\s*[\.\)]\s*(.*)', re.DOTALL)
    
    for p_idx in range(len(doc)):
        page = doc[p_idx]
        p_num = p_idx + 1
        blocks = page.get_text("blocks")
        mid_x = page.rect.width / 2.0
        left = [b for b in blocks if b[0] < mid_x and b[6] == 0]
        right = [b for b in blocks if b[0] >= mid_x and b[6] == 0]
        left.sort(key=lambda b: b[1])
        right.sort(key=lambda b: b[1])
        
        col_text = "\n".join([b[4] for b in left + right])
        chunks = re.split(r'\n(?=(?:\d{1,2}\s+)?\d{1,3}\s*[\.\)])', col_text)
        for c in chunks:
            m = q_start.match(c.strip())
            if m:
                q_num = int(m.group(1))
                if 1 <= q_num <= 120:
                    questions[q_num] = (p_num, m.group(2).strip())
    return questions, 120

# ==========================================
# 5. MOTOR: 2019 - 2025 DERLEME DÖNEMİ (120 / 200 / 240 SORU)
# ==========================================
def parse_era_2019_2025(doc, exam_name):
    name_low = exam_name.lower()
    max_limit = 240 if ("2021" in name_low or "2022" in name_low) else (200 if ("2024" in name_low or "2025" in name_low or "2026" in name_low) else 120)
    
    questions = {}
    current_q_num = None
    current_page = 1
    current_content = []
    q_start = re.compile(r'^(?:\d{1,2}\s+)?(\d{1,3})\s*[\.\)]\s*(.*)', re.DOTALL)

    for p_idx in range(len(doc)):
        page = doc[p_idx]
        p_num = p_idx + 1
        blocks = page.get_text("blocks")
        mid_x = page.rect.width / 2.0
        left = [b for b in blocks if b[0] < mid_x and b[6] == 0]
        right = [b for b in blocks if b[0] >= mid_x and b[6] == 0]
        left.sort(key=lambda b: b[1])
        right.sort(key=lambda b: b[1])

        for b in left + right:
            b_text = b[4].strip()
            m = q_start.match(b_text)
            if m:
                p_num_val = int(m.group(1))
                if 1 <= p_num_val <= max_limit:
                    if current_q_num is not None:
                        questions[current_q_num] = (current_page, "\n".join(current_content))
                    current_q_num = p_num_val
                    current_page = p_num
                    current_content = [m.group(2).strip()]
                    continue
            if current_q_num is not None:
                current_content.append(b_text)

    if current_q_num is not None:
        questions[current_q_num] = (current_page, "\n".join(current_content))

    return questions, max_limit

# ==========================================
# ANA DAĞITICI MOTOR
# ==========================================
def process_exam_pdf(pdf_path, ans_path, exam_name, exam_type="TUS"):
    doc = pymupdf.open(pdf_path)
    name_low = exam_name.lower()

    if any(y in name_low for y in ["2006", "2007", "2008"]):
        questions_dict, max_limit = parse_era_2006_2008(doc, exam_name)
    elif any(y in name_low for y in ["2009", "2010"]):
        questions_dict, max_limit = parse_era_2009_2010(doc, exam_name)
    elif any(y in name_low for y in ["2011", "2012", "2013"]):
        questions_dict, max_limit = parse_era_2011_2013(doc, exam_name)
    elif any(y in name_low for y in ["2014", "2015", "2016", "2017", "2018"]):
        questions_dict, max_limit = parse_era_2014_2018(doc, exam_name)
    else:
        questions_dict, max_limit = parse_era_2019_2025(doc, exam_name)

    if ans_path:
        ans_doc = pymupdf.open(ans_path)
        ans_text = "\n".join([p.get_text() for p in ans_doc])
    else:
        ans_text = "\n".join([doc[i].get_text() for i in range(len(doc))])
    answers = parse_answer_key(ans_text)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    saved_nums = []

    for q_num, (p_target, full_content) in questions_dict.items():
        vignette, options = extract_options_strict(full_content)
        vignette = re.sub(r'\[P_\d+\]', '', vignette)
        vignette = re.sub(r'\s+', ' ', vignette).strip()
        correct = answers.get(q_num, "")

        is_visual = any(re.search(t, full_content, re.IGNORECASE) for t in GORSEL_TETIKLEYICILER)
        img_file_path = None

        if is_visual and p_target <= len(doc):
            page_obj = doc[p_target - 1]
            pix = page_obj.get_pixmap(dpi=150)
            img_name = f"{exam_name}_Soru_{q_num}_Sayfa_{p_target}.png"
            img_save_path = os.path.join(IMAGES_DIR, img_name)
            pix.save(img_save_path)
            img_file_path = os.path.relpath(img_save_path, BASE_DIR)

        q_code = f"{exam_type}_{exam_name}_Q{q_num:03d}"

        cur.execute("""
            INSERT OR REPLACE INTO questions 
            (q_code, exam_type, exam_name, q_num, vignette, options_json, correct_opt, image_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (q_code, exam_type, exam_name, q_num, vignette, json.dumps(options, ensure_ascii=False), correct, img_file_path))
        saved_nums.append(q_num)

    conn.commit()
    conn.close()
    return sorted(list(set(saved_nums))), max_limit

def build_database_pool():
    init_db()
    print("==================================================")
    print("      DİNAMİK VERİTABANI KASASI (DÖNEM MODÜLLÜ)  ")
    print(f"[*] Hedef Veritabanı: {DB_PATH}")
    print("==================================================\n")

    all_files = []
    for root, _, files in os.walk(DATA_DIR):
        for f in files:
            if f.lower().endswith(".pdf"):
                all_files.append(os.path.join(root, f))

    groups = {}
    for p in all_files:
        fn = os.path.basename(p)
        dn = os.path.dirname(p)
        if any(k in fn.lower() for k in ["cevapanah", "cevap", "answer"]):
            k = fn.lower().replace("cevapanah", "").replace("cevap", "").replace(".pdf", "").strip()
            groups.setdefault(dn, {})["ans_" + k] = p
        else:
            k = fn.lower().replace(".pdf", "").strip()
            groups.setdefault(dn, {})["q_" + k] = p

    total_pool_questions = 0
    total_exams = 0

    for dn, files in sorted(groups.items()):
        for q_k in [k for k in files if k.startswith("q_")]:
            q_pdf = files[q_k]
            name = os.path.splitext(os.path.basename(q_pdf))[0]
            ans_pdf = files.get("ans_" + q_k.replace("q_", ""), None)
            
            exam_type = "TUS"
            if "usmle" in name.lower():
                exam_type = "USMLE"
            elif "ydus" in name.lower():
                exam_type = "YDUS"

            saved_nums, max_limit = process_exam_pdf(q_pdf, ans_pdf, name, exam_type)
            count = len(saved_nums)
            
            if count > 0:
                expected = set(range(1, max_limit + 1))
                missing = expected - set(saved_nums)
                missing_info = f" (⚠️ Eksik: {sorted(list(missing))})" if missing else " (Tam Liste ✓)"
            else:
                missing_info = " (❌ 0 Soru)"

            print(f"[✓] {name} -> {count}/{max_limit} soru eklendi.{missing_info}")
            total_pool_questions += count
            total_exams += 1

    print("\n==================================================")
    print(f"[+] KASA TAMAMLANDI! Toplam {total_exams} sınavdan {total_pool_questions} soru dönem modülleriyle mühürlendi.")
    print("==================================================")

if __name__ == "__main__":
    build_database_pool()