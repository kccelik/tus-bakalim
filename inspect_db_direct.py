import sqlite3
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "tus_database.db")

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

TARGET_EXAMS = [
    "Tus2009Eylül",
    "Tus2013NisanTemel",
    "2016TUSIlkbaharTemel",
    "2021TUSİlkbaharTUSDATA"
]

print("\n" + "="*60)
print("       VERİTABANI DOĞRUDAN İÇERİK DENETİMİ       ")
print("="*60)

for exam in TARGET_EXAMS:
    cur.execute("SELECT q_num, vignette, options_json, correct_opt FROM questions WHERE exam_name = ? ORDER BY q_num ASC LIMIT 2", (exam,))
    rows = cur.fetchall()
    
    print(f"\n📁 SINAV: {exam}")
    if not rows:
        print("   ❌ Veritabanında bu sınava ait HİÇ KAYIT YOK!")
        continue

    for r in rows:
        opts = json.loads(r["options_json"]) if r["options_json"] else {}
        print(f"\n  [Soru {r['q_num']}]")
        print(f"  - Gövde (Vignette): '{r['vignette'][:120]}...'")
        print(f"  - Şık Sayısı: {len(opts)}")
        print(f"  - Şıklar: {opts}")
        print(f"  - Doğru Cevap: {r['correct_opt']}")
        print("  " + "-"*40)

conn.close()