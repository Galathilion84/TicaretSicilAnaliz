import re
import logging
from typing import List, Dict, Any, Optional

from app.services.ai_service import ai_service

logger = logging.getLogger(__name__)

# Initialize RapidOCR engine
_ocr_engine = None

def get_ocr():
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _ocr_engine = RapidOCR()
            logger.info("RapidOCR engine initialized successfully.")
        except Exception as e:
            logger.warning(f"Could not initialize RapidOCR: {e}")
    return _ocr_engine

def extract_ocr_text(image_bytes: bytes) -> str:
    engine = get_ocr()
    if not engine or not image_bytes:
        return ""
    try:
        out, _ = engine(image_bytes)
        if out:
            lines = [item[1] for item in out]
            return "\n".join(lines)
    except Exception as e:
        logger.error(f"Error extracting text with OCR: {e}")
    return ""

def parse_decision_details(text: str, announcement_type: str) -> Dict[str, Any]:
    """
    Extracts address, capital, mersis, management, and partner details from announcement text.
    """
    details = {
        "address": "",
        "capital_old": "",
        "capital_new": "",
        "capital_increase": "",
        "mersis": "",
        "officers_appointed": [],
        "officers_resigned": [],
        "partners": [],
        "share_transfers": [],
        "single_shareholder": "",
        "summary": ""
    }

    if not text:
        return details

    # 1. Extract MERSİS Number
    mersis_match = re.search(r'Mersis\s*No\s*:\s*([0-9]{16})', text, re.IGNORECASE)
    if mersis_match:
        details["mersis"] = mersis_match.group(1)

    # 2. Extract Address
    addr_match = re.search(r'Adres\s*:\s*([^\n\r]+(?:\n[^\n\r]+)?)', text, re.IGNORECASE)
    if addr_match:
        raw_addr = addr_match.group(1).strip()
        raw_addr = re.sub(r'(Yukarıda|Merkezin|Tescil).*', '', raw_addr, flags=re.IGNORECASE).strip()
        if len(raw_addr) > 8:
            details["address"] = raw_addr

    # 3. Capital changes (e.g. 100.000.000 TL -> 1.000.000.000 TL)
    cap_new_match = re.search(r'bölünmüş[,\s]+([0-9.,]+)\s*(\([^\)]+\))?\s*(?:Türk Lirası|TL)', text, re.IGNORECASE)
    if not cap_new_match:
        cap_new_match = re.search(r'sermayesi[,\s]+([0-9.,]+)\s*(\([^\)]+\))?\s*(?:Türk Lirası|TL)', text, re.IGNORECASE)
    if cap_new_match:
        details["capital_new"] = cap_new_match.group(1) + " TL"

    cap_old_match = re.search(r'Önceki\s+sermayesi\s+olan\s+([0-9.,]+)\s*[-]?TL', text, re.IGNORECASE)
    if cap_old_match:
        details["capital_old"] = cap_old_match.group(1) + " TL"

    cap_inc_match = re.search(r'artırılan\s+([0-9.,]+)\s*[-]?TL', text, re.IGNORECASE)
    if cap_inc_match:
        details["capital_increase"] = "+" + cap_inc_match.group(1) + " TL"

    # 4. Management / Board members & Corporate Officers
    appointed = re.findall(
        r'([A-ZÇĞİÖŞÜa-zçğıöşü\s]{3,35})\s+(?:Yönetim Kurulu Başkanı|Yönetim Kurulu Başkan Vekili|Yönetim Kurulu Üyesi|Müdür|Müdürler Kurulu Başkanı|Temsile Yetkili|Tasfiye Memuru)\s+olarak\s+(?:seçil|atan|tayin)',
        text, re.IGNORECASE
    )
    if not appointed:
        appointed = re.findall(
            r'(?:Yönetim Kurulu Başkanlığına|Yönetim Kurulu Üyeliğine|Şirket Müdürlüğüne)\s+([A-ZÇĞİÖŞÜa-zçğıöşü\s]{3,35})\s+(?:seçil|atan)',
            text, re.IGNORECASE
        )
    if appointed:
        details["officers_appointed"] = list(dict.fromkeys([
            a.strip() for a in appointed 
            if len(a.strip()) > 3 and not any(w in a.upper() for w in ["ŞİRKET", "TİCARET", "MADDE", "GENEL", "KARAR"])
        ]))

    resigned = re.findall(
        r'([A-ZÇĞİÖŞÜa-zçğıöşü\s]{3,35})\s+(?:görevinden\s+)?(?:istifa\s+etmiş|istifasıyla|ayrılmış|sona\s+ermiş|üyeliği\s+düşmüş)',
        text, re.IGNORECASE
    )
    if resigned:
        details["officers_resigned"] = list(dict.fromkeys([
            r.strip() for r in resigned 
            if len(r.strip()) > 3 and not any(w in r.upper() for w in ["ŞİRKET", "TİCARET", "MADDE", "GENEL"])
        ]))

    # 5. Partners / Shareholders & Share Transfers (Ortaklar ve Pay Devirleri)
    single_match = re.search(r'tek\s+pay\s+sahibi(?:nin|nin)?\s+([A-ZÇĞİÖŞÜa-zçğıöşü\s]{3,40})\s+(?:olduğu|kaldığı)', text, re.IGNORECASE)
    if single_match:
        details["single_shareholder"] = single_match.group(1).strip()
        details["partners"].append({
            "ad": details["single_shareholder"],
            "pay": "%100 (Tek Pay Sahibi)",
            "durum": "Tek Pay Sahibi"
        })

    # Share transfer detection
    transfers = re.findall(
        r'([A-ZÇĞİÖŞÜa-zçğıöşü\s]{3,35})\s+(?:şirketteki\s+)?([0-9.,]+)?\s*(?:adet\s+)?payını\s+([A-ZÇĞİÖŞÜa-zçğıöşü\s]{3,35})[\'e|\'a|na|ne]?\s+devret',
        text, re.IGNORECASE
    )
    for devreden, pay_count, devralan in transfers:
        dev_clean = devreden.strip()
        al_clean = devralan.strip()
        if len(dev_clean) > 3 and len(al_clean) > 3:
            details["share_transfers"].append({
                "devreden": dev_clean,
                "devralan": al_clean,
                "pay": f"{pay_count} Pay" if pay_count else "Pay Devri"
            })
            details["partners"].append({
                "ad": al_clean,
                "pay": "Pay Devriyle Katıldı",
                "durum": "Mevcut Ortak"
            })

    # Partner capital mapping (e.g. "... TL sermaye karşılığı ... paya sahip ...")
    partner_shares = re.findall(
        r'([0-9.,]+)\s*TL.*paya\s+sahip\s+([A-ZÇĞİÖŞÜa-zçğıöşü\s]{3,35})',
        text, re.IGNORECASE
    )
    for pay_tl, p_name in partner_shares:
        p_clean = p_name.strip()
        if len(p_clean) > 3 and not any(w in p_clean.upper() for w in ["ŞİRKET", "MADDE", "GENEL"]):
            details["partners"].append({
                "ad": p_clean,
                "pay": f"{pay_tl} TL",
                "durum": "Tescilli Ortak"
            })

    return details

class CompanyAnalyzer:
    """
    Synthesizes company announcements into an Executive Corporate Intelligence Summary.
    """
    def generate_summary(
        self,
        company_info: Dict[str, Any],
        announcements: List[Dict[str, Any]],
        announcements_text_map: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        
        announcements_text_map = announcements_text_map or {}
        
        # Sort announcements chronologically (oldest to newest)
        def parse_date(item):
            t = item.get("tarih", "")
            try:
                parts = t.split(".")
                if len(parts) == 3:
                    return f"{parts[2]}-{parts[1]}-{parts[0]}"
            except Exception:
                pass
            return t

        sorted_announcements = sorted(announcements, key=parse_date)

        kurulus_tarihi = ""
        current_address = ""
        current_mersis = ""
        current_capital = ""
        capital_history = []
        management_changes = []
        timeline = []
        all_partners = []
        all_transfers = []
        single_shareholder = ""

        for ann in sorted_announcements:
            ann_id = ann.get("id")
            text = announcements_text_map.get(ann_id, "")
            tur = ann.get("tur", "").upper()
            tarih = ann.get("tarih", "")
            sayi = ann.get("sayi", "")
            sayfa = ann.get("sayfa", "")
            
            ai_data = ai_service.get_cached(ann)
            parsed = parse_decision_details(text, tur)
            
            # 1. Address & Mersis & Single Shareholder
            if ai_data:
                addr = ai_data.get("sirket_adresi") or ai_data.get("yeni_adres_veya_merkez") or ai_data.get("kurulus_adresi")
                if addr and isinstance(addr, str) and addr.strip().lower() not in ["-", "yok", "belirtilmemiş", "tespit edilemedi", "none", "null"] and len(addr.strip()) > 5:
                    current_address = addr.strip()
                if ai_data.get("mersis_no") and isinstance(ai_data["mersis_no"], str) and ai_data["mersis_no"].strip().lower() not in ["-", "yok", "belirtilmemiş", "none", "null"] and len(ai_data["mersis_no"].strip()) >= 10:
                    current_mersis = ai_data["mersis_no"].strip()
                if ai_data.get("tek_pay_sahibi") and isinstance(ai_data["tek_pay_sahibi"], str) and ai_data["tek_pay_sahibi"].strip().lower() not in ["-", "yok", "belirtilmemiş", "none", "null"] and len(ai_data["tek_pay_sahibi"].strip()) > 3:
                    single_shareholder = ai_data["tek_pay_sahibi"].strip()

                # Partners / Kurucular from AI
                partners_list = ai_data.get("ortaklar_ve_pay_sahipleri") or ai_data.get("kurucular_ve_ortaklar") or ai_data.get("ortaklar")
                if partners_list and isinstance(partners_list, list):
                    for p in partners_list:
                        if isinstance(p, dict) and p.get("ad") and p["ad"].strip().lower() not in ["-", "yok", "belirtilmemiş"]:
                            all_partners.append({
                                "ad": p["ad"].strip(),
                                "pay": p.get("pay", "Tescilli Pay"),
                                "durum": p.get("rol", "Ortak / Pay Sahibi")
                            })
                        elif isinstance(p, str) and p.strip() and p.strip().lower() not in ["-", "yok", "belirtilmemiş"]:
                            all_partners.append({
                                "ad": p.strip(),
                                "pay": "Tescilli Pay",
                                "durum": "Ortak / Pay Sahibi"
                            })
            elif parsed.get("address"):
                current_address = parsed["address"]

            if "TEK PAY SAHİPLİ" in tur and not single_shareholder:
                single_shareholder = "Tek Pay Sahipli Şirket (Tek Ortaklı Anonim Şirket)"

            if parsed.get("mersis") and not current_mersis:
                current_mersis = parsed["mersis"]
            if parsed.get("single_shareholder") and not single_shareholder:
                single_shareholder = parsed["single_shareholder"]
            if parsed.get("partners"):
                all_partners.extend(parsed["partners"])

            # 2. Establishment (oldest establishment date)
            if ("KURULUŞ" in tur or "ANA SÖZLEŞME" in tur) and not kurulus_tarihi:
                kurulus_tarihi = tarih
            elif not kurulus_tarihi:
                kurulus_tarihi = tarih

            # 3. Capital changes
            if ai_data and ai_data.get("sermaye_degisimi") and ai_data["sermaye_degisimi"].get("yeni_sermaye") != "-":
                sd = ai_data["sermaye_degisimi"]
                capital_history.append({
                    "tarih": tarih,
                    "sayi": sayi,
                    "sayfa": sayfa,
                    "old": sd.get("eski_sermaye", "-"),
                    "new": sd.get("yeni_sermaye", "Tescil Edildi"),
                    "increase": sd.get("artis_tutari", ""),
                    "announcement_id": ann_id
                })
                current_capital = sd.get("yeni_sermaye")
            elif "SERMAYE" in tur or parsed.get("capital_new"):
                cap_item = {
                    "tarih": tarih,
                    "sayi": sayi,
                    "sayfa": sayfa,
                    "old": parsed.get("capital_old", "-"),
                    "new": parsed.get("capital_new", "Tescil Edildi"),
                    "increase": parsed.get("capital_increase", ""),
                    "announcement_id": ann_id
                }
                capital_history.append(cap_item)
                if parsed.get("capital_new"):
                    current_capital = parsed["capital_new"]

            # 4. Management changes
            if ai_data and ai_data.get("yonetim_ve_yetkililer"):
                yy = ai_data["yonetim_ve_yetkililer"]
                if (yy.get("goreve_secilenler") or yy.get("gorevden_ayrilanlar")):
                    management_changes.append({
                        "tarih": tarih,
                        "sayi": sayi,
                        "tur": ai_data.get("karar_turu", ann.get("tur", "")),
                        "appointed": yy.get("goreve_secilenler", []),
                        "resigned": yy.get("gorevden_ayrilanlar", []),
                        "announcement_id": ann_id
                    })
            elif any(k in tur for k in ["GENEL KURUL", "YÖNETİM", "TEMSİL", "MÜDÜR", "ORTAK"]):
                mgmt_item = {
                    "tarih": tarih,
                    "sayi": sayi,
                    "tur": ann.get("tur", "Genel Kurul / Yetkili Değişikliği"),
                    "appointed": parsed.get("officers_appointed", []),
                    "resigned": parsed.get("officers_resigned", []),
                    "announcement_id": ann_id
                }
                management_changes.append(mgmt_item)

            # 5. Partners & Transfers
            if ai_data and ai_data.get("ortaklar_ve_pay_devirleri"):
                for op in ai_data["ortaklar_ve_pay_devirleri"]:
                    all_transfers.append({
                        "tarih": tarih,
                        "sayi": sayi,
                        "devreden": op.get("islem", "Pay Devri"),
                        "devralan": op.get("detay", ""),
                        "pay": op.get("detay", ""),
                        "announcement_id": ann_id
                    })
            elif parsed.get("share_transfers"):
                for st in parsed["share_transfers"]:
                    all_transfers.append({
                        "tarih": tarih,
                        "sayi": sayi,
                        "devreden": st["devreden"],
                        "devralan": st["devralan"],
                        "pay": st["pay"],
                        "announcement_id": ann_id
                    })

            # Timeline Decision Item
            decision_summary = ann.get("tur", "")
            if ai_data and ai_data.get("yonetici_ozeti"):
                decision_summary = ai_data["yonetici_ozeti"]
            elif parsed.get("capital_increase"):
                decision_summary += f" (Sermaye Artırımı: {parsed['capital_increase']})"
            elif parsed.get("address"):
                decision_summary += f" (Yeni Adres: {parsed['address'][:45]}...)"

            timeline.append({
                "announcement_id": ann_id,
                "tarih": tarih,
                "sayi": sayi,
                "sayfa": sayfa,
                "tur": ann.get("tur", "İlan"),
                "summary": decision_summary,
                "has_pdf": ann.get("has_pdf", True),
                "has_ai": bool(ai_data)
            })

        # Deduplicate partners by name
        unique_partners_map = {}
        for p in all_partners:
            name = p["ad"].strip()
            if name not in unique_partners_map:
                unique_partners_map[name] = p

        final_partners = list(unique_partners_map.values())
        
        # If no explicit partner share list extracted, infer key corporate representatives from management appointments
        if not final_partners:
            for mgmt in management_changes:
                for app in mgmt.get("appointed", []):
                    final_partners.append({
                        "ad": app,
                        "pay": "Temsil & İlzam Yetkilisi",
                        "durum": "Yönetim Organı Üyesi"
                    })

        # Reverse lists so newest is on top
        timeline.reverse()
        capital_history.reverse()
        management_changes.reverse()
        all_transfers.reverse()

        return {
            "unvan": company_info.get("unvan", ""),
            "sicil_no": company_info.get("sicil_no", ""),
            "mudurluk": company_info.get("mudurluk", ""),
            "mersis": current_mersis or "Belirtilmemiş",
            "kurulus_tarihi": kurulus_tarihi or "Tespit Edilemedi",
            "guncel_adres": current_address or "Ticaret Sicil Dosyasında Kayıtlı Merkez Adresi",
            "guncel_sermaye": current_capital or "Tescilli Sermaye Mevcut",
            "toplam_ilan_sayisi": len(announcements),
            "tek_pay_sahibi": single_shareholder,
            "ortaklar": final_partners,
            "pay_devirleri": all_transfers,
            "capital_history": capital_history,
            "management_changes": management_changes,
            "timeline": timeline
        }

company_analyzer = CompanyAnalyzer()
