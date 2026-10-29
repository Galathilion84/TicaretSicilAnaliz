"""TSG parolası ve Gemini anahtarı için işletim sistemi kimlik kasası (Windows Kimlik Bilgisi Yöneticisi,
macOS Anahtar Zinciri, Linux Secret Service). Kasa yoksa çağıran taraf .env'ye geri düşer."""
import logging
import os
from typing import Dict

logger = logging.getLogger(__name__)

SERVICE = "ticaretsicil-yerel"
KEYS = ("TSG_EMAIL", "TSG_PASSWORD", "GEMINI_API_KEY")


def _keyring():
    """Kullanılabilir bir kasa arka ucu döner; yoksa None."""
    if os.getenv("TS_DISABLE_KEYRING"):
        return None
    try:
        import keyring
        from keyring.backends import fail

        backend = keyring.get_keyring()
        if isinstance(backend, fail.Keyring) or getattr(backend, "priority", 1) <= 0:
            return None
        return keyring
    except Exception as e:  # keyring kurulu değil ya da arka uç başlatılamadı
        logger.debug("Kimlik kasası kullanılamıyor: %s", e)
        return None


def available() -> bool:
    return _keyring() is not None


def load() -> Dict[str, str]:
    kr = _keyring()
    if not kr:
        return {}
    out = {}
    for key in KEYS:
        try:
            value = kr.get_password(SERVICE, key)
        except Exception as e:
            logger.warning("Kasadan %s okunamadı: %s", key, e)
            continue
        if value:
            out[key] = value
    return out


def save(values: Dict[str, str]) -> bool:
    """Verilen anahtarları kasaya yazar (boş değer kaydı siler). Başarılıysa True."""
    kr = _keyring()
    if not kr:
        return False
    try:
        for key, value in values.items():
            if key not in KEYS:
                continue
            if value:
                kr.set_password(SERVICE, key, value)
            else:
                try:
                    kr.delete_password(SERVICE, key)
                except Exception:  # zaten yok
                    pass
        return True
    except Exception as e:
        logger.error("Kasaya yazılamadı: %s", e)
        return False


def apply_to(settings) -> None:
    """Ortam değişkeni/.env ile verilmemiş alanları kasadan doldurur."""
    stored = load()
    for key in KEYS:
        if not getattr(settings, key, "") and stored.get(key):
            setattr(settings, key, stored[key])
