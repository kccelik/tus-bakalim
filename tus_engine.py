import sqlite3
import json
import os
from datetime import datetime

class TusLibrary:
    def __init__(self, db_path="tus_database.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        """Veritabanı tablolarını oluşturur."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        # Soru tablosu
        cur.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                q_code TEXT UNIQUE,
                subject TEXT,
                topic TEXT,
                vignette TEXT,
                options_json TEXT,
                correct_opt TEXT,
                explanation TEXT,
                high_yield TEXT,
                source_year TEXT
            )
        """)
        
        # Çalışma / Çözüm geçmişi tablosu
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER,
                selected_opt TEXT,
                is_correct INTEGER,
                solved_at TIMESTAMP,
                FOREIGN KEY (question_id) REFERENCES questions (id)
            )
        """)
        conn.commit()
        conn.close()

    def add_question(self, q_code, subject, topic, vignette, options, correct_opt, explanation="", high_yield="", source_year=""):
        """Veritabanına yeni bir soru ekler."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO questions (q_code, subject, topic, vignette, options_json, correct_opt, explanation, high_yield, source_year)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (q_code, subject, topic, vignette, json.dumps(options, ensure_ascii=False), correct_opt.upper(), explanation, high_yield, source_year))
            conn.commit()
            print(f"[+] Soru başarıyla kaydedildi: {q_code}")
        except sqlite3.IntegrityError:
            print(f"[!] Soru kodu zaten mevcut: {q_code}")
        finally:
            conn.close()

    def get_questions(self, subject=None, topic=None, limit=10):
        """Kriterlere göre soruları listeler."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        query = "SELECT id, q_code, subject, topic, vignette, options_json, correct_opt, explanation, high_yield FROM questions WHERE 1=1"
        params = []
        
        if subject:
            query += " AND subject = ?"
            params.append(subject)
        if topic:
            query += " AND topic = ?"
            params.append(topic)
            
        query += " ORDER BY RANDOM() LIMIT ?"
        params.append(limit)
        
        cur.execute(query, params)
        rows = cur.fetchall()
        conn.close()
        
        questions = []
        for r in rows:
            questions.append({
                "id": r[0],
                "q_code": r[1],
                "subject": r[2],
                "topic": r[3],
                "vignette": r[4],
                "options": json.loads(r[5]),
                "correct_opt": r[6],
                "explanation": r[7],
                "high_yield": r[8]
            })
        return questions

    # --- ÇIKTI VE KULLANIM YOLLARI ---

    def run_cli_quiz(self, subject=None, limit=5):
        """Yol 1: Terminal/Termux üzerinde anlık interaktif soru çözme arayüzü."""
        questions = self.get_questions(subject=subject, limit=limit)
        if not questions:
            print("Uygun soru bulunamadı.")
            return

        print(f"\n=== {subject or 'GENEL'} TEST BAŞLIYOR ({len(questions)} Soru) ===\n")
        for idx, q in enumerate(questions, 1):
            print(f"[{idx}] {q['q_code']} - {q['subject']} ({q['topic']})")
            print(f"\n{q['vignette']}\n")
            for opt, text in q['options'].items():
                print(f"  {opt}) {text}")
            
            user_ans = input("\nCevabınız (A/B/C/D/E) veya çıkış için (Q): ").strip().upper()
            if user_ans == 'Q':
                break
                
            is_corr = (user_ans == q['correct_opt'])
            if is_corr:
                print("\n DOĞRU!")
            else:
                print(f"\n YANLIŞ! Doğru Cevap: {q['correct_opt']}")
                
            print(f"\n Açıklama: {q['explanation']}")
            print(f" High-Yield Not: {q['high_yield']}")
            print("-" * 50)

    def export_to_html(self, output_file="exports/quiz.html", subject=None, limit=20):
        """Yol 2: Tarayıcıda açılabilen, şıkları gizli/açılır interaktif HTML dosyası."""
        os.makedirs("exports", exist_ok=True)
        questions = self.get_questions(subject=subject, limit=limit)
        
        html_content = """<!DOCTYPE html><html><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>TUS/USMLE Soru Seti</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f4f6f9; padding: 15px; }
            .card { background: white; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .badge { background: #34495e; color: white; padding: 4px 8px; border-radius: 4px; font-size: 12px; }
            .opt { margin: 8px 0; padding: 8px; background: #f8f9fa; border-radius: 4px; }
            details { margin-top: 15px; background: #e8f8f5; padding: 10px; border-radius: 6px; }
            summary { font-weight: bold; cursor: pointer; color: #16a085; }
        </style></head><body><h2> TUS/USMLE Çalışma Seti</h2>"""
        
        for q in questions:
            html_content += f"""<div class="card">
                <span class="badge">{q['subject']} / {q['topic']}</span> <b>{q['q_code']}</b>
                <p style="margin-top:12px; font-size: 15px; line-height: 1.5;">{q['vignette']}</p>"""
            for opt, txt in q['options'].items():
                html_content += f"""<div class="opt"><b>{opt})</b> {txt}</div>"""
            html_content += f"""<details><summary>Çözümü ve Doğru Cevabı Göster</summary>
                <p><b>Doğru Şık:</b> {q['correct_opt']}</p>
                <p><b>Mekanizma:</b> {q['explanation']}</p>
                <p><b>Hap Bilgi:</b> {q['high_yield']}</p>
            </details></div>"""
            
        html_content += "</body></html>"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"[+] HTML Quiz kaydedildi: {output_file}")

    def export_to_markdown(self, output_file="exports/notlar.md", subject=None):
        """Yol 3: Obsidian veya Notion'a aktarılabilir Markdown vaka kartları."""
        os.makedirs("exports", exist_ok=True)
        questions = self.get_questions(subject=subject, limit=100)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"# {subject or 'Tüm'} Soru Arşivi\n\n")
            for q in questions:
                f.write(f"### {q['q_code']} - {q['topic']}\n\n")
                f.write(f"> {q['vignette']}\n\n")
                for opt, txt in q['options'].items():
                    f.write(f"- **{opt})** {txt}\n")
                f.write(f"\n? **Cevap:** {q['correct_opt']}\n")
                f.write(f"- **Açıklama:** {q['explanation']}\n")
                f.write(f"- **High-Yield:** {q['high_yield']}\n\n---\n\n")
        print(f"[+] Markdown dosyası kaydedildi: {output_file}")