import os

import pymupdf

# PyMuPDF'in yerleşik "helv" yazı tipi ş, ğ, İ, ı harflerini içermez. Sistemde Türkçe destekleyen bir
# yazı tipi varsa demo gazete onunla çizilir; yoksa yerleşik yazı tipine düşer (bu harfler bozuk görünür).
_FONT_CANDIDATES = (
    os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arial.ttf"),
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)


def _turkish_font_file():
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def generate_sample_gazette_pdf(company_name: str = "ANTİGRAVİTY BİLİŞİM VE TEKNOLOJİ ANONİM ŞİRKETİ") -> bytes:
    """
    Generates a realistic 1-page sample Ticaret Sicili Gazetesi PDF
    with multiple announcement columns, dividers, headers, and company notice.
    """
    doc = pymupdf.open()
    # A4 standard page in points: 595 x 842
    page = doc.new_page(width=595, height=842)
    fontname = "helv"
    font_file = _turkish_font_file()
    if font_file:
        page.insert_font(fontname="demo", fontfile=font_file)
        fontname = "demo"

    # 1. Official Header
    # Outer Border
    page.draw_rect(pymupdf.Rect(20, 20, 575, 822), color=(0.2, 0.2, 0.2), width=1)
    
    # Header Banner
    header_rect = pymupdf.Rect(25, 25, 570, 75)
    page.draw_rect(header_rect, color=(0.1, 0.1, 0.1), width=0.5)
    
    # Header Titles
    page.insert_text(
        pymupdf.Point(165, 45),
        "TÜRKİYE TİCARET SİCİLİ GAZETESİ",
        fontsize=16,
        fontname=fontname,
        color=(0, 0, 0)
    )
    page.insert_text(
        pymupdf.Point(185, 60),
        "TÜRKİYE ODALAR VE BORSALAR BİRLİĞİ",
        fontsize=10,
        fontname=fontname,
        color=(0.3, 0.3, 0.3)
    )
    page.insert_text(
        pymupdf.Point(35, 70),
        "Sayı: 11180",
        fontsize=9,
        fontname=fontname
    )
    page.insert_text(
        pymupdf.Point(460, 70),
        "24 Ekim 2026 - Sayfa: 142",
        fontsize=9,
        fontname=fontname
    )
    
    # 2. Draw 3 Columns
    col1_x0, col1_x1 = 28, 205
    col2_x0, col2_x1 = 210, 387
    col3_x0, col3_x1 = 392, 569
    y_start = 85
    y_end = 815
    
    # Column dividers
    page.draw_line(pymupdf.Point(207, y_start), pymupdf.Point(207, y_end), color=(0.7, 0.7, 0.7), width=0.5)
    page.draw_line(pymupdf.Point(389, y_start), pymupdf.Point(389, y_end), color=(0.7, 0.7, 0.7), width=0.5)
    
    # Column 1 Notice (Filler)
    c1_rect = pymupdf.Rect(col1_x0, y_start + 10, col1_x1, y_start + 250)
    page.draw_rect(c1_rect, color=(0.4, 0.4, 0.4), width=0.5)
    page.insert_textbox(
        c1_rect + (4, 4, -4, -4),
        "İSTANBUL TİCARET SİCİLİ MÜDÜRLÜĞÜ\n"
        "Sicil No: 984521-5\n"
        "Ticaret Unvanı:\n"
        "KUZEY MARMARA LOJİSTİK VE DIŞ TİCARET LİMİTED ŞİRKETİ\n\n"
        "Yukarıda bilgileri verilen şirketin 12/10/2026 tarihli olağan genel kurul toplantısında alınan kararlar gereğince "
        "şirket merkezinin Maslak Mah. Büyükdere Cad. No:14 Sarıyer / İstanbul adresine taşınmasına oy birliğiyle karar verilmiştir.\n"
        "Tescil Tarihi: 20.10.2026",
        fontsize=7.5,
        fontname=fontname
    )

    # Column 2 Notice (TARGET ANNOUNCEMENT)
    c2_rect = pymupdf.Rect(col2_x0, y_start + 10, col2_x1, y_start + 280)
    page.draw_rect(c2_rect, color=(0.1, 0.1, 0.1), width=1)
    
    target_notice_text = (
        "ANKARA TİCARET SİCİLİ MÜDÜRLÜĞÜ\n"
        "Sicil No: 458120\n"
        "MERSİS No: 012345678900001\n"
        f"Ticaret Unvanı:\n{company_name}\n\n"
        "İLAN METNİ (KURULUŞ / SERMAYE ARTIRIMI):\n"
        "Yukarıda unvanı ve sicil numarası yazılı şirketin 18/10/2026 tarihli genel kurul kararı ile "
        "şirket sermayesinin 5.000.000 TL'den 25.000.000 TL'ye artırılmasına ve esas sözleşmenin 6. maddesinin tadiline "
        "karar verilmiş olup, işbu karar Ankara Ticaret Sicili Müdürlüğü'nce 22/10/2026 tarihinde tescil edilmiştir.\n\n"
        "Yönetim Kurulu Başkanı: Ahmet Yılmaz\n"
        "Tescil Tarihi: 22.10.2026 - İlan Sıra: 8412"
    )
    
    page.insert_textbox(
        c2_rect + (5, 5, -5, -5),
        target_notice_text,
        fontsize=8,
        fontname=fontname
    )

    # Column 3 Notice (Filler)
    c3_rect = pymupdf.Rect(col3_x0, y_start + 10, col3_x1, y_start + 220)
    page.draw_rect(c3_rect, color=(0.4, 0.4, 0.4), width=0.5)
    page.insert_textbox(
        c3_rect + (4, 4, -4, -4),
        "İZMİR TİCARET SİCİLİ MÜDÜRLÜĞÜ\n"
        "Sicil No: 331200\n"
        "Ticaret Unvanı:\n"
        "EGE YAZILIM VE DANIŞMANLIK HİZMETLERİ A.Ş.\n\n"
        "Şirket temsil ve ilzam yetkilisinin görev süresinin 3 yıl süreyle uzatılmasına karar verilmiştir.\n"
        "Tescil Tarihi: 21.10.2026",
        fontsize=7.5,
        fontname=fontname
    )

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes
