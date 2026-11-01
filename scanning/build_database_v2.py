"""
build_database_v2.py — TUS PDF -> SQLite (aynı şema, app.py ile uyumlu)

Ne değişti (v1'e göre):
  1. Metin, kelime koordinatlarından sütun sütun yeniden kuruluyor. 2009-2018 ÖSYM
     PDF'lerinde soru numaraları ve A) B) etiketleri metinden ayrı katmanda
     olduğu için eski ayrıştırıcı bunları kaçırıyordu.
  2. Soru numaraları SIRAYLA bekleniyor (1, 2, 3 ...). Cevap anahtarı sayfasındaki
     "1. D" satırları artık soruların üzerine yazılmıyor.
  3. Görsel soru tespiti, soru bölgesinde gerçekten resim olup olmamasına göre
     yapılıyor ve görsel olarak sadece o sorunun bölgesi kırpılıyor.
  4. Metin katmanı olmayan (taranmış) sayfalar raporlanıyor; istenirse
     --vision ile yerel Qwen3-VL (Ollama) üzerinden okunuyor.

Kullanım:
  python scanning/build_database_v2.py                    # metinli PDF'ler -> tus_database_v2.db
  python scanning/build_database_v2.py --vision           # + taranmış sayfaları Qwen3-VL ile oku
  python scanning/build_database_v2.py --only 2015TUSIlkbaharTemel   # tek sınav (test için)
"""
import argparse
import json
import os
import re
import sqlite3

import pymupdf

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.environ.get("TUS_QUESTION_DB", os.path.join(BASE_DIR, "instance", "tus_database_v2.db"))
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
IMAGES_DIR = os.path.join(BASE_DIR, "exports", "clean_images")
IMG_PREFIX = "v2_"

NOISE = [
    r"^\d{4}\s*[-–]\s*TUS\b", r"^TUS\s", r"Diğer sayfaya geçiniz", r"^ÖSYM$",
    r"^\d{1,2}$", r"^[AB]$", r"^(TEMEL|KLİNİK) TIP BİLİMLERİ", r"^TESTİ$",
    r"^Bu testte \d+ soru vardır", r"^TTBT|^KTBT", r"^www\.", r"TUSDATA",
]
NOISE_RE = re.compile("|".join(NOISE))
QSTART_RE = re.compile(r"^(\d{1,3})\s*[\.\)]\s*(.*)$")
ANSWER_ONLY_RE = re.compile(r"^([A-E]|İptal|İPTAL|IPTAL|iptal)?\s*$")
ANSWER_PAIR_RE = re.compile(r"(?<!\d)(\d{1,3})\s*[\.\-:]?\s*\n?\s*([A-E]|İPTAL|IPTAL|İptal|iptal)\b")


# ---------------------------------------------------------------- page text
def page_lines(page):
    """Return reading-order lines: [(text, col, y0, y1)] — left column then right."""
    mid = page.rect.width / 2
    words = page.get_text("words")
    # a word that clearly spans the middle (full-width header) goes to the left column
    out = []
    for col in (0, 1):
        ws = [w for w in words if ((w[0] < mid) == (col == 0))]
        ws.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
        lines = []
        for w in ws:
            yc = (w[1] + w[3]) / 2
            if lines and abs(lines[-1]["yc"] - yc) < 3.0:
                lines[-1]["w"].append(w)
            else:
                lines.append({"yc": yc, "w": [w]})
        for ln in lines:
            lw = sorted(ln["w"], key=lambda w: w[0])
            text = " ".join(w[4] for w in lw if w[4] != "ÖSYM").strip()   # watermark
            if text:
                out.append((text, col, min(w[1] for w in lw), max(w[3] for w in lw)))
    return out


def is_scanned(page):
    body = [t for t, *_ in page_lines(page) if not NOISE_RE.search(t)]
    return sum(len(t) for t in body) < 150


# ---------------------------------------------------------------- parsing
def join_lines(lines):
    text = ""
    for ln in lines:
        if text.endswith("-") and ln[:1].islower():
            text = text[:-1] + ln          # "yak-" + "laşık" -> "yaklaşık"
        else:
            text += ("\n" if text else "") + ln
    return text


def split_options(text):
    """Find A) .. E) in order; anything before A) is the vignette."""
    # "A)" can also appear inside the stem, e.g. "(vitamin A)": use the last A) that has a B) after it
    a_hits = [m.start() for m in re.finditer(r"(?<!\S)A\s*\)", text)]
    with_b = [a for a in a_hits if re.search(r"(?<!\S)B\s*\)", text[a:])]
    pos, start = {}, (with_b[-1] if with_b else (a_hits[0] if a_hits else 0))
    for letter in "ABCDE":
        m = re.compile(rf"(?<!\S){letter}\s*\)").search(text, start)
        if not m:
            break
        pos[letter] = (m.start(), m.end())
        start = m.end()
    if "A" not in pos:
        return re.sub(r"\s+", " ", text).strip(), {}
    letters = list(pos)
    opts = {}
    for i, l in enumerate(letters):
        end = pos[letters[i + 1]][0] if i + 1 < len(letters) else len(text)
        opts[l] = re.sub(r"\s+", " ", text[pos[l][1]:end]).strip()
    vignette = re.sub(r"\s+", " ", text[: pos["A"][0]]).strip()
    return vignette, opts


def has_opts(q):
    return bool(re.search(r"(?:^|\s)A\s*\)", "\n".join(q["lines"])))


def parse_questions(doc):
    """Sequential state machine over all pages. Returns (questions, scanned_pages)."""
    questions = []          # dicts: num, section, page, col, y0, y1, lines
    cur = None
    expected = 1
    section = 1
    scanned = []
    for p_idx, page in enumerate(doc):
        if is_scanned(page):
            scanned.append(p_idx + 1)
            continue
        for text, col, y0, y1 in page_lines(page):
            if NOISE_RE.search(text):
                continue
            m = QSTART_RE.match(text)
            if m:
                num, rest = int(m.group(1)), m.group(2)
                answer_like = bool(ANSWER_ONLY_RE.match(rest)) and rest != ""
                # A "1." restarts numbering (new test, or real questions after rules)
                # only if the current item is complete (has options) or the whole
                # current section is option-less rules. Blocks numbered lists in a vignette.
                sec_items = [q for q in questions if q["section"] == section]
                new_section = (num == 1 and expected > 5 and (len(rest) > 15 or rest == "")
                               and cur is not None
                               and (has_opts(cur) or not any(has_opts(q) for q in sec_items)))
                if not answer_like and (expected <= num <= expected + 2 or new_section):
                    if new_section:
                        section += 1
                    cur = {"num": num, "section": section, "page": p_idx + 1,
                           "col": col, "y0": y0, "y1": y1, "lines": [rest] if rest else []}
                    questions.append(cur)
                    expected = num + 1
                    continue
            if cur is not None:
                # stop collecting if we've wandered onto an answer-key page
                if cur["page"] == p_idx + 1 and cur["col"] == col:
                    cur["y1"] = max(cur["y1"], y1)
                cur["lines"].append(text)

    # Drop "sections" that are really numbered exam rules (instruction pages):
    # most items are sentences without A) options. Items that are only a number
    # (question printed as a picture) are NOT rules — they go to the vision step.
    keep = []
    for s in sorted({q["section"] for q in questions}):
        items = [q for q in questions if q["section"] == s]
        rule_like = sum(1 for q in items if not has_opts(q) and len(" ".join(q["lines"])) > 15)
        with_opts = sum(1 for q in items if has_opts(q))
        if not (rule_like >= 3 and rule_like >= 2 * with_opts):
            keep.append(s)
    renum = {s: i + 1 for i, s in enumerate(keep)}
    questions = [dict(q, section=renum[q["section"]]) for q in questions if q["section"] in renum]
    return questions, len(keep), scanned


def parse_answer_key(doc, ans_doc=None):
    """Prefer the separate key PDF; else pages that look like a key (many 'N. X' pairs)."""
    def blocks(text):
        """Split a page's pairs into separate keys when numbering restarts
        (e.g. Temel 1-120 and Klinik 1-120 printed on the same page)."""
        parts = re.split(r"CEVAP ANAHTARI", text)
        if len(parts) > 1:             # headed keys: first value per number wins
            out = []                   # (ignores garbled duplicate text layers)
            for part in parts[1:]:
                d = {}
                for n, v in ANSWER_PAIR_RE.findall(part):
                    v = v.upper().replace("IPTAL", "İPTAL")
                    d.setdefault(int(n), "İPTAL" if "PTAL" in v else v)
                out.append(d)
            return [b for b in out if b]
        out = [{}]
        for n, v in ANSWER_PAIR_RE.findall(text):
            n = int(n)
            v = v.upper().replace("IPTAL", "İPTAL")
            if n in out[-1]:
                out.append({})
            out[-1][n] = "İPTAL" if "PTAL" in v else v
        return [b for b in out if b]

    pages = list(ans_doc) if ans_doc else list(doc)
    keys = []
    for page in pages:
        found = blocks(page.get_text())
        if sum(len(b) for b in found) < 20:
            continue
        for b in found:
            if keys and 1 not in b and not (set(b) & set(keys[-1])):
                keys[-1].update(b)       # continuation of the previous key
            else:
                keys.append(b)           # starts at 1 = a new test/section
    keys = [k for k in keys if len(k) >= 20]
    if not keys and ans_doc:
        keys = blocks("\n".join(p.get_text() for p in ans_doc))
    return keys   # list of {num: answer}; one per test/section


# ---------------------------------------------------------------- images
_BOX_CACHE = {}


def _page_boxes(doc, idx):
    """Pictures / vector figures on a page (cached per page)."""
    if doc.name not in _BOX_CACHE:          # images repeated on many pages = logo/watermark
        seen = {}
        for pg in doc:
            for x in {i["xref"] for i in pg.get_image_info(xrefs=True)}:
                seen[x] = seen.get(x, 0) + 1
        _BOX_CACHE[doc.name] = {x for x, n in seen.items() if n > 3}
    key = (doc.name, idx)
    if key not in _BOX_CACHE:
        page = doc[idx]
        W, H = page.rect.width, page.rect.height
        boxes = [pymupdf.Rect(i["bbox"]) for i in page.get_image_info(xrefs=True)
                 if i["xref"] not in _BOX_CACHE[doc.name]]
        try:
            boxes += list(page.cluster_drawings())
        except Exception:
            pass
        _BOX_CACHE[key] = [b for b in boxes if b.width > 50 and b.height > 50
                           and b.width < 0.75 * W and b.height < 0.5 * H   # not page/column frames
                           and b.y0 > 0.06 * H and b.y1 < 0.95 * H]
    return _BOX_CACHE[key]


def question_image(doc, q, exam_name, next_q, force=False):
    """If the question's own region contains a picture (or force), save a crop of that region."""
    page = doc[q["page"] - 1]
    W, H = page.rect.width, page.rect.height
    x0, x1 = (0, W / 2) if q["col"] == 0 else (W / 2, W)
    y0 = max(0, q["y0"] - 4)
    if next_q and next_q["page"] == q["page"] and next_q["col"] == q["col"]:
        y1 = next_q["y0"] - 2
    else:
        y1 = H - 30
    region = pymupdf.Rect(x0, y0, x1, y1)
    if not force and not any(b.intersects(region) for b in _page_boxes(doc, q["page"] - 1)):
        return None
    name = f"{IMG_PREFIX}{exam_name}_S{q['section']}_Soru_{q['num']}_Sayfa_{q['page']}.png"
    if region.height < 20 or region.width < 20:
        return None
    try:
        page.get_pixmap(dpi=170, clip=region).save(os.path.join(IMAGES_DIR, name))
    except Exception:
        return None
    return os.path.relpath(os.path.join(IMAGES_DIR, name), BASE_DIR)


# ---------------------------------------------------------------- vision fallback
VISION_PROMPT = """Bu görsel bir Türkçe TUS sınavı sayfasıdır. Sayfadaki TÜM soruları sırayla çıkar.
- Metni birebir, Türkçe karakterlerle yaz; düzeltme veya çeviri yapma.
- İki sütunlu sayfada önce sol, sonra sağ sütunu oku.
- Her soru için: number, text (soru kökü), options (A-E), has_figure (soruda şekil/görsel var mı).
- Soru yoksa boş liste döndür."""
VISION_SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "number": {"type": "integer"},
            "text": {"type": "string"},
            "options": {"type": "object",
                        "properties": {k: {"type": "string"} for k in "ABCDE"}},
            "has_figure": {"type": "boolean"},
        },
        "required": ["number", "text", "options"]}}},
    "required": ["questions"],
}


def vision_page(page, model):
    import ollama   # only needed for --vision
    zoom = 1600 / max(page.rect.width, page.rect.height)
    png = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")
    resp = ollama.chat(model=model,
                       messages=[{"role": "user", "content": VISION_PROMPT, "images": [png]}],
                       format=VISION_SCHEMA,
                       options={"temperature": 0, "num_ctx": 8192})
    return json.loads(resp["message"]["content"])["questions"]


# ---------------------------------------------------------------- db
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
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
        )""")
    # extra columns (ignored by app.py, useful for review)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(questions)")}
    for c, t in [("source_pdf", "TEXT"), ("source_page", "INTEGER"),
                 ("method", "TEXT"), ("problems", "TEXT")]:
        if c not in cols:
            conn.execute(f"ALTER TABLE questions ADD COLUMN {c} {t}")
    conn.commit()
    return conn


def problems_of(vignette, options):
    if "iptal edil" in vignette.lower():
        return []                      # cancelled question: nothing to fix
    p = []
    if len(vignette) < 15:
        p.append("short_vignette")
    if len([k for k in "ABCDE" if options.get(k)]) != 5:
        p.append("not_5_options")
    return p


def save(conn, exam_type, exam_name, num, vignette, options, answer, img, pdf, page, method):
    q_code = f"{exam_type}_{exam_name}_Q{num:03d}"
    conn.execute("""
        INSERT OR REPLACE INTO questions
        (q_code, exam_type, exam_name, q_num, vignette, options_json, correct_opt, image_path,
         source_pdf, source_page, method, problems)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (q_code, exam_type, exam_name, num, vignette, json.dumps(options, ensure_ascii=False),
         answer, img, os.path.relpath(pdf, BASE_DIR), page, method,
         ",".join(problems_of(vignette, options))))


# ---------------------------------------------------------------- main
def process(conn, pdf, ans_pdf, exam_name, exam_type, args):
    doc = pymupdf.open(pdf)
    ans_doc = pymupdf.open(ans_pdf) if ans_pdf else None
    qs, n_sections, scanned = parse_questions(doc)
    keys = parse_answer_key(doc, ans_doc)

    # questions in later sections get numbers offset (e.g. 2009/2010: Temel 1-100 + Klinik 1-100)
    offsets, last = {}, 0
    for q in qs:
        offsets.setdefault(q["section"], last)
        last = max(last, offsets[q["section"]] + q["num"])

    def key_for(section_idx):          # section_idx is 1-based
        if not keys or (len(keys) == 1 and n_sections > 1):
            return {}                  # one key but several tests -> ambiguous, leave blank
        return keys[min(section_idx, len(keys)) - 1]

    saved = 0
    picture_pages = set()              # pages whose questions are printed as pictures
    for i, q in enumerate(qs):
        text = join_lines(q["lines"])
        inline = re.search(r"DOĞRU CEVAP\s*:\s*([A-E])", text)
        text = re.sub(r"DOĞRU CEVAP\s*:\s*[A-E]", "", text)
        vignette, options = split_options(text)
        if not vignette and not options:
            picture_pages.add(q["page"])
            continue
        num = offsets[q["section"]] + q["num"]
        answer = inline.group(1) if inline else key_for(q["section"]).get(q["num"], "")
        nxt = qs[i + 1] if i + 1 < len(qs) else None
        picture_opts = len([k for k in "ABCDE" if options.get(k)]) < 5
        img = question_image(doc, q, exam_name, nxt, force=picture_opts)
        save(conn, exam_type, exam_name, num, vignette, options, answer, img, pdf, q["page"], "text")
        saved += 1

    vision_pages = sorted(set(scanned) | picture_pages)
    if saved < 60:                     # questions mostly printed as pictures: read every page
        vision_pages = list(range(1, len(doc) + 1))
    v_saved = 0
    if vision_pages and args.vision:
        clean = {r[0] for r in conn.execute(
            "SELECT q_num FROM questions WHERE exam_name=? AND problems=''", (exam_name,))}
        v_off, prev, sec = 0, 0, 1
        for p in vision_pages:
            try:
                found = vision_page(doc[p - 1], args.model)
            except Exception as e:
                print(f"     ! vision page {p} failed: {e}")
                continue
            for vq in found:
                if not isinstance(vq.get("number"), int):
                    continue
                if vq["number"] + v_off < prev - 30:      # numbering restarted: next test
                    v_off, sec = prev, sec + 1
                num = vq["number"] + v_off
                prev = max(prev, num)
                if num in clean:
                    continue                              # text version is already good
                opts = {k: v.strip() for k, v in (vq.get("options") or {}).items() if v.strip()}
                img = None
                if vq.get("has_figure"):
                    name = f"{IMG_PREFIX}{exam_name}_Soru_{num}_Sayfa_{p}.png"
                    doc[p - 1].get_pixmap(dpi=150).save(os.path.join(IMAGES_DIR, name))
                    img = os.path.relpath(os.path.join(IMAGES_DIR, name), BASE_DIR)
                save(conn, exam_type, exam_name, num, vq.get("text", "").strip(), opts,
                     key_for(sec).get(vq["number"], ""), img, pdf, p, "vision")
                v_saved += 1
            conn.commit()
            print(f"     vision sayfa {p}: {len(found)} soru", flush=True)
    conn.commit()
    return saved, v_saved, vision_pages, n_sections


def find_exams():
    pdfs = []
    for root, _, files in os.walk(DATA_DIR):
        for f in files:
            if f.lower().endswith(".pdf"):
                pdfs.append(os.path.join(root, f))
    answers = {}
    exams = []
    for p in pdfs:
        stem = os.path.splitext(os.path.basename(p))[0]
        if "cevap" in stem.lower():
            answers[(os.path.dirname(p), stem.lower().replace("cevapanah", "").replace("cevap", ""))] = p
        else:
            exams.append(p)
    import difflib
    out = []
    for p in sorted(exams):
        stem = os.path.splitext(os.path.basename(p))[0]
        d = os.path.dirname(p)
        ans = answers.get((d, stem.lower()))
        if not ans:   # tolerate typos like tus2008eylutemel / tus2008eylultemelcevapanah
            same_dir = {k[1]: v for k, v in answers.items() if k[0] == d}
            close = difflib.get_close_matches(stem.lower(), list(same_dir), n=1, cutoff=0.9)
            ans = same_dir[close[0]] if close else None
        out.append((p, ans, stem))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vision", action="store_true", help="read scanned pages with Qwen3-VL via Ollama")
    ap.add_argument("--model", default="qwen3-vl:8b-instruct")
    ap.add_argument("--only", help="process only exams whose name contains this text")
    ap.add_argument("--skip-done", action="store_true",
                    help="skip exams already in the database (resume an interrupted run)")
    args = ap.parse_args()

    os.makedirs(IMAGES_DIR, exist_ok=True)
    conn = init_db()
    print(f"[*] Veritabanı: {DB_PATH}\n")
    todo_scanned = []
    for pdf, ans, name in find_exams():
        if args.only and args.only not in name:
            continue
        if args.skip_done and conn.execute(
                "SELECT 1 FROM questions WHERE exam_name=? LIMIT 1", (name,)).fetchone():
            continue
        exam_type = "USMLE" if "usmle" in name.lower() else ("YDUS" if "ydus" in name.lower() else "TUS")
        saved, v_saved, scanned, n_sec = process(conn, pdf, ans, name, exam_type, args)
        row = conn.execute("""SELECT COUNT(*), SUM(problems=''), SUM(correct_opt!='')
                              FROM questions WHERE exam_name=?""", (name,)).fetchone()
        total, clean, with_ans = row[0], row[1] or 0, row[2] or 0
        flag = "✓" if total and clean == total else "⚠️"
        extra = f" | görsel/taranmış sayfa: {len(scanned)}" if scanned else ""
        print(f"[{flag}] {name:30s} {total:3d} soru, {clean:3d} temiz, {with_ans:3d} cevaplı"
              f"{' | bölüm: ' + str(n_sec) if n_sec > 1 else ''}{extra}", flush=True)
        if scanned and not args.vision:
            todo_scanned.append((name, scanned))
    conn.close()
    if todo_scanned:
        print("\n[i] Soruları resim olarak basılmış sayfalar (Qwen3-VL için --vision ile tekrar çalıştırın):")
        for name, pages in todo_scanned:
            print(f"    {name}: {len(pages)} sayfa")


if __name__ == "__main__":
    main()
