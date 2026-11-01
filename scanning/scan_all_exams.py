import os
import re
import pymupdf

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root
DATA_DIR = os.path.join(BASE_DIR, "data")
REPORT_FILE = os.path.join(BASE_DIR, "exports", "sinav_raporu.txt")

NOISE_KEYWORDS = [
    "tusdata", "hazırlık merkez", "ilk 10'da", "ilk 50'de", "kazanan her",
    "dus'ta", "sorulabilecek", "tıp akademisi", "tusworld"
]

def clean_noise_text(text):
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        l_lower = line.lower()
        if any(kw in l_lower for kw in NOISE_KEYWORDS):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)

def parse_answer_key_robust(text):
    pattern = r'(\d{1,3})\s*[\.\-\s:]\s*([A-Ea-e]|İPTAL|IPTAL|iptal)\b'
    matches = re.findall(pattern, text)
    
    answers = {}
    canceled = []
    
    for q_num_str, val in matches:
        q_num = int(q_num_str)
        val_clean = val.strip().upper()
        if "İPTAL" in val_clean or "IPTAL" in val_clean:
            answers[q_num] = "İPTAL"
            canceled.append(q_num)
        else:
            answers[q_num] = val_clean
            
    return answers, canceled

def extract_questions_perfect(doc):
    full_text = ""
    for page in doc:
        blocks = page.get_text("blocks")
        blocks.sort(key=lambda b: (b[1], b[0]))
        for b in blocks:
            if b[6] == 0:
                full_text += "\n" + b[4]

    cleaned_text = clean_noise_text(full_text)
    
    # 1. Kalıp: Satır başı veya boşluk + 1-3 basamaklı sayı + nokta/parantez
    pattern = r'(?:^|\n)(?:\d{1,2}\s+)?(\d{1,3})\s*[\.\)]\s*(?=[\s\S]{1,100}?[A-E]\))'
    matches = re.findall(pattern, cleaned_text)
    
    found_nums = set()
    for m in matches:
        num = int(m)
        if 1 <= num <= 300:
            found_nums.add(num)
            
    # 2. Kalıp (Görsel sebebiyle şıkları uzakta kalan sorular için yedek)
    pattern_fallback = r'(?:^|\n)(?:\d{1,2}\s+)?(\d{1,3})\s*[\.\)]\s*(?=[A-ZÇĞİÖŞÜa-zçğıöşüα-ωΑ-Ωβγ\d%\"\'\(\-\n])'
    matches_fallback = re.findall(pattern_fallback, cleaned_text)
    for m in matches_fallback:
        num = int(m)
        if 1 <= num <= 300:
            found_nums.add(num)

    return sorted(list(found_nums)), cleaned_text

def run_full_audit():
    print(f"[*] Stabil Kodla Tarama Başlatılıyor...\n[*] Dizin: {DATA_DIR}\n")
    
    if not os.path.exists(DATA_DIR):
        print(f"[!] HATA: '{DATA_DIR}' dizini bulunamadı!")
        return

    all_files = []
    for root, dirs, files in os.walk(DATA_DIR):
        for f in files:
            if f.lower().endswith(".pdf"):
                all_files.append(os.path.join(root, f))

    exam_groups = {}
    for path in all_files:
        filename = os.path.basename(path)
        dirname = os.path.dirname(path)
        
        if any(keyword in filename.lower() for keyword in ["cevapanah", "cevap", "answer"]):
            key = filename.lower().replace("cevapanah", "").replace("cevap", "").replace(".pdf", "").strip()
            exam_groups.setdefault(dirname, {})["ans_" + key] = path
        else:
            key = filename.lower().replace(".pdf", "").strip()
            exam_groups.setdefault(dirname, {})["q_" + key] = path

    report_lines = []
    report_lines.append("==================================================")
    report_lines.append("       TUS SORU VE İPTAL RAPORU (STABİL HALİ)     ")
    report_lines.append("==================================================\n")

    total_exams = 0
    total_canceled = 0

    for dirname, files_dict in sorted(exam_groups.items()):
        q_keys = [k for k in files_dict.keys() if k.startswith("q_")]
        
        for q_k in q_keys:
            q_pdf = files_dict[q_k]
            exam_title = os.path.splitext(os.path.basename(q_pdf))[0]
            
            clean_name = q_k.replace("q_", "")
            matched_ans_key = "ans_" + clean_name
            ans_pdf = files_dict.get(matched_ans_key, None)
            
            doc = pymupdf.open(q_pdf)
            q_nums, cleaned_text = extract_questions_perfect(doc)
            
            if ans_pdf:
                ans_doc = pymupdf.open(ans_pdf)
                ans_text = "\n".join([p.get_text() for p in ans_doc])
                ans_type = "Ayrı Dosyadan"
            else:
                ans_text = cleaned_text
                ans_type = "Dahili (PDF İçinden)"
                
            answers, canceled_in_key = parse_answer_key_robust(ans_text)
            
            total_exams += 1
            total_canceled += len(canceled_in_key)
            
            rel_path = os.path.relpath(q_pdf, DATA_DIR)
            report_lines.append(f"📁 Sınav: {exam_title}")
            report_lines.append(f"   - Yol: {rel_path}")
            report_lines.append(f"   - Bulunan Soru Sayısı: {len(q_nums)} (Aralık: {min(q_nums) if q_nums else 0} - {max(q_nums) if q_nums else 0})")
            report_lines.append(f"   - Bulunan Cevap Sayısı: {len(answers)}")
            
            if canceled_in_key:
                report_lines.append(f"   - 🚫 İPTAL EDİLEN SORULAR: {canceled_in_key}")
            
            if q_nums:
                expected_set = set(range(min(q_nums), max(q_nums) + 1))
                missing = expected_set - set(q_nums)
                if missing and len(missing) <= 10:
                    report_lines.append(f"   - ℹ️ Atlanan Soru Numaraları: {sorted(list(missing))}")
                elif len(missing) > 10:
                    report_lines.append(f"   - ⚠️ UYARI: {len(missing)} adet numara atlandı.")
                    
            report_lines.append("-" * 45)

    report_lines.append(f"\n[+] Tarama Tamamlandı. Toplam Sınav: {total_exams}")
    report_lines.append(f"[+] Toplam İptal Soru: {total_canceled}")
    
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
        
    print(f"[+] İşlem tamam! Stabil rapor '{REPORT_FILE}' dosyasına yazıldı.")

if __name__ == "__main__":
    run_full_audit()