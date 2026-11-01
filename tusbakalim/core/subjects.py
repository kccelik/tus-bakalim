"""Which TUS subject a question belongs to, from exam name + question number."""

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

