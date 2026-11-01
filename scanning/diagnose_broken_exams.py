import os
import pymupdf

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root
DATA_DIR = os.path.join(BASE_DIR, "data")

TARGETS = [
    os.path.join("TUS Soruları ve Yapay Soru Bankası", "Tus2006-2013", "Tus2009", "Tus2009Eylül.pdf"),
    os.path.join("TUS Soruları ve Yapay Soru Bankası", "Tus2006-2013", "Tus2013", "Tus2013NisanTemel.pdf"),
    os.path.join("TUS Soruları ve Yapay Soru Bankası", "Tus2014-2018", "Tus2016", "2016TUSIlkbaharTemel.pdf"),
    os.path.join("TUS Soruları ve Yapay Soru Bankası", "Tus2019-2025", "Tus2021", "2021TUSİlkbaharTUSDATA.pdf")
]

def diagnose():
    print("==================================================")
    print("      2009-2025 DÖNEMİ METİN VE ŞIK TEŞHİSİ      ")
    print("==================================================\n")

    for rel_path in TARGETS:
        full_path = os.path.join(DATA_DIR, rel_path)
        if not os.path.exists(full_path):
            print(f"[!] Dosya bulunamadı: {rel_path}\n")
            continue

        exam_name = os.path.basename(full_path)
        doc = pymupdf.open(full_path)
        print(f"📁 Sınav: {exam_name} (Toplam {len(doc)} Sayfa)")

        # İlk 3 sayfanın bloklarını yazdır
        for p_idx in range(min(3, len(doc))):
            page = doc[p_idx]
            blocks = page.get_text("blocks")
            print(f"\n--- [Sayfa {p_idx+1} Metin Blokları (İlk 3 Blok)] ---")
            text_blocks = [b[4].strip() for b in blocks if b[6] == 0 and b[4].strip()]
            for b_i, tb in enumerate(text_blocks[:3]):
                print(f"[Blok {b_i+1}]: {tb[:160]}...")
            print("-" * 40)
        print("\n" + "="*55 + "\n")

if __name__ == "__main__":
    diagnose()