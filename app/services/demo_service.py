import base64
import uuid
from typing import Any, Dict, Optional

from app.services.ai_service import is_demo_id  # noqa: F401
from app.services.cache import LRUCache
from app.services.cropper import cropper
from app.services.demo_generator import generate_sample_gazette_pdf

# Demo PDF'leri bellekte tutulur; sınırsız büyümesin diye LRU.
demo_storage: LRUCache[Dict[str, Any]] = LRUCache(40)

DEMO_PREFIX = "demo_"
COMPANY_PREFIX = "comp_"
MULTI_COMPANY_WORDS = ("HOLDING", "HOLDİNG", "GRUP", "VE", "BİLİŞİM")


def _announcement(demo_id: str, title: str, tur: str, tarih: str, sayi: str, sayfa: str,
                  pdf_bytes: bytes, crop: Dict[str, Any]) -> Dict[str, Any]:
    demo_storage[demo_id] = {
        "id": demo_id, "pdf_bytes": pdf_bytes, "crop_bytes": crop["crop_image_bytes"],
        "title": title, "unvan": title, "tur": tur, "tarih": tarih, "sayi": sayi, "sayfa": sayfa,
    }
    def b64(b):
        return base64.b64encode(b).decode("utf-8") if b else ""

    return {
        "id": demo_id, "mudurluk": "ANKARA", "sicil_no": "458120", "unvan": title,
        "tarih": tarih, "sayi": sayi, "sayfa": sayfa, "tur": tur, "has_pdf": True, "is_demo": True,
        "crop_image_b64": b64(crop["crop_image_bytes"]),
        "full_image_b64": b64(crop["full_page_image_bytes"]),
    }


def build_demo_search(unvan: str) -> Dict[str, Any]:
    demo_id = f"{DEMO_PREFIX}{uuid.uuid4().hex[:8]}"
    title = unvan.strip().upper()
    pdf_bytes = generate_sample_gazette_pdf(company_name=title)
    crop = cropper.extract_crop(pdf_bytes=pdf_bytes, target_title=title, page_num=0, sicil_no="458120")

    latest = _announcement(demo_id, title, "Sermaye Artırımı / Genel Kurul", "24.10.2026", "11180", "142", pdf_bytes, crop)
    prev = _announcement(f"{demo_id}_prev", title, "Kuruluş Tescili", "15.01.2025", "10745", "88", pdf_bytes, crop)
    announcements = [latest, prev]

    companies = [{
        "company_id": f"{COMPANY_PREFIX}{demo_id}", "unvan": title, "sicil_no": "458120",
        "mudurluk": "ANKARA", "latest_date": "24.10.2026", "announcements": announcements,
    }]
    if any(k in title for k in MULTI_COMPANY_WORDS):
        companies.append({
            "company_id": f"{COMPANY_PREFIX}{demo_id}_2", "unvan": f"{title} YATIRIM HOLDİNG A.Ş.",
            "sicil_no": "992451", "mudurluk": "İSTANBUL", "latest_date": "10.03.2026",
            "announcements": [latest],
        })
    return {
        "success": True, "count": len(announcements), "multiple_companies": len(companies) > 1,
        "companies": companies, "results": announcements,
    }


def demo_company_summary(company_id: str) -> Dict[str, Any]:
    demo_id = company_id[len(COMPANY_PREFIX):].removesuffix("_2")
    latest_id, prev_id = demo_id, f"{demo_id}_prev"
    return {
        "success": True,
        "company_id": company_id,
        "summary": {
            "unvan": "ANTİGRAVİTY BİLİŞİM VE TEKNOLOJİ ANONİM ŞİRKETİ",
            "sicil_no": "458120", "mudurluk": "ANKARA", "mersis": "0123456789000001",
            "kurulus_tarihi": "15.01.2025",
            "guncel_adres": "Üniversiteler Mah. ODTÜ Teknokent Bilişim İnovasyon Binası No:4/B Çankaya / Ankara",
            "guncel_sermaye": "25.000.000 TL", "toplam_ilan_sayisi": 2, "tek_pay_sahibi": "",
            "ortaklar": [
                {"ad": "Ahmet Yılmaz", "pay": "%60 (15.000.000 TL)", "durum": "Kurucu / Hâkim Ortak"},
                {"ad": "Zeynep Kaya", "pay": "%40 (10.000.000 TL)", "durum": "Ortak (Pay Devriyle Katıldı)"},
            ],
            "pay_devirleri": [{
                "tarih": "24.10.2026", "sayi": "11180", "devreden": "Mehmet Demir", "devralan": "Zeynep Kaya",
                "pay": "10.000.000 TL (200.000 Pay)", "announcement_id": latest_id,
            }],
            "capital_history": [
                {"tarih": "24.10.2026", "sayi": "11180", "sayfa": "142", "old": "5.000.000 TL",
                 "new": "25.000.000 TL", "increase": "+20.000.000 TL", "announcement_id": latest_id},
                {"tarih": "15.01.2025", "sayi": "10745", "sayfa": "88", "old": "-",
                 "new": "5.000.000 TL", "increase": "Kuruluş Sermayesi", "announcement_id": prev_id},
            ],
            "management_changes": [{
                "tarih": "24.10.2026", "sayi": "11180", "tur": "Genel Kurul & Temsil İlzam",
                "appointed": ["Ahmet Yılmaz (Yönetim Kurulu Başkanı)", "Zeynep Kaya (Yönetim Kurulu Üyesi)"],
                "resigned": ["Mehmet Demir (Eski Üye)"], "announcement_id": latest_id,
            }],
            "timeline": [
                {"announcement_id": latest_id, "tarih": "24.10.2026", "sayi": "11180", "sayfa": "142",
                 "tur": "Sermaye Artırımı / Genel Kurul",
                 "summary": "Sermaye 5.000.000 TL'den 25.000.000 TL'ye artırıldı. Ahmet Yılmaz 3 yıl süreyle YK Başkanı seçildi.",
                 "has_pdf": True},
                {"announcement_id": prev_id, "tarih": "15.01.2025", "sayi": "10745", "sayfa": "88",
                 "tur": "Kuruluş Tescili",
                 "summary": "Şirket 5.000.000 TL sermaye ile Ankara Ticaret Sicili Müdürlüğü'nde tescil edildi.",
                 "has_pdf": True},
            ],
        },
    }


def get_demo(announcement_id: str) -> Optional[Dict[str, Any]]:
    return demo_storage.get(announcement_id)
