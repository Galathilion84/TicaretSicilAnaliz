import logging
import os
import re
import ssl
import urllib.request
from urllib.parse import urlsplit
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

_PROBE_URL = "https://www.ticaretsicil.gov.tr/view/hizlierisim/girisyap.php"


def _env_proxy() -> Optional[str]:
    for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        if os.environ.get(k):
            return os.environ[k]
    return None


def _direct_reachable() -> bool:
    # Gerçek istemciyle aynı güven kuralları (OS sertifika deposu) kullanılır; sonuç tutarlı olsun.
    try:
        import truststore
        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        req = urllib.request.Request(_PROBE_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3.0, context=ctx) as resp:  # nosec B310: sabit https adresi
            return resp.status in (200, 301, 302)
    except Exception as e:
        logger.debug("Doğrudan TSG bağlantı testi başarısız: %s", e)
        return False


def _windows_proxy() -> Optional[str]:
    try:
        import winreg
    except ImportError:
        return None  # Windows dışı
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            try:
                enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
                if enabled and server:
                    return f"http://{server}"
            except OSError:
                pass
            try:
                pac, _ = winreg.QueryValueEx(key, "AutoConfigURL")
                # file:// ve benzeri şemalar yerel dosya okutabilir; yalnızca http(s) PAC kabul edilir.
                if pac and urlsplit(pac).scheme in ("http", "https"):
                    content = urllib.request.urlopen(pac, timeout=3).read()  # nosec B310: şema yukarıda doğrulandı.decode("utf-8", errors="ignore")
                    m = re.search(r"PROXY\s+([a-zA-Z0-9_\-\.]+:[0-9]+)", content)
                    if m:
                        return f"http://{m.group(1)}"
            except Exception as e:
                logger.debug("PAC okunamadı: %s", e)
    except OSError as e:
        logger.debug("Windows proxy ayarları okunamadı: %s", e)
    return None


def mask_proxy(url: Optional[str]) -> str:
    """Proxy adresindeki kullanıcı:parola kısmını log'a yazmamak için gizler."""
    return re.sub(r"//[^@/]*@", "//***@", url or "")


@lru_cache(maxsize=1)
def get_system_proxy() -> Optional[str]:
    """Proxy kararı süreç başına bir kez verilir (her istemci oluşumunda 3 sn'lik ağ testi yapılmaz)."""
    return _env_proxy() or (None if _direct_reachable() else _windows_proxy())
