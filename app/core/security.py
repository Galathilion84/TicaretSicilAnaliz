import re
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Path, Request
from fastapi.responses import JSONResponse

from app.core.config import settings

# Sunucu tarafında üretilen ID'ler (ann_xxx, comp_xxx, demo_xxx) dosya adına da girer.
ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
_ID_RE = re.compile(ID_PATTERN)
ResourceId = Annotated[str, Path(pattern=ID_PATTERN)]

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
# Bir ters vekil üzerinden gelen istek "yerel" görünse de uzaktan gelmiştir.
_FORWARD_HEADERS = ("x-forwarded-for", "x-forwarded-host", "x-real-ip", "forwarded")

MAX_BODY_BYTES = 64 * 1024  # bu uygulamadaki tüm JSON gövdeleri küçüktür

CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'"
)


def is_valid_id(value: str) -> bool:
    return bool(_ID_RE.match(value or ""))


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _is_direct_loopback(request: Request) -> bool:
    return client_ip(request) in _LOOPBACK and not any(h in request.headers for h in _FORWARD_HEADERS)


async def require_local(request: Request) -> None:
    """Kimlik bilgilerini değiştiren uçlar yalnızca doğrudan bu bilgisayardan çağrılabilir."""
    if not _is_direct_loopback(request):
        raise HTTPException(status_code=403, detail="Bu işlem yalnızca bu bilgisayardan yapılabilir.")


LocalOnly = Depends(require_local)


# ------------------------------------------- DNS rebinding / CSRF / başlıklar
def _hostname(host_header: str) -> str:
    return (urlsplit("//" + host_header).hostname or "").lower()


async def host_origin_gate(request: Request, call_next):
    """Kötü niyetli bir web sitesi bu yerel uygulamayı hedefleyemesin: yabancı Host (DNS rebinding)
    ve farklı kaynaklı (Origin) yazma istekleri reddedilir."""
    host_header = request.headers.get("host", "")
    if _hostname(host_header) not in {h.lower() for h in settings.ALLOWED_HOSTS}:
        return JSONResponse({"detail": "Geçersiz Host başlığı."}, status_code=400)

    if request.method not in ("GET", "HEAD", "OPTIONS"):
        # shortcut: yalnızca Content-Length denetlenir; yerel tek kullanıcı için yeterli
        try:
            too_big = int(request.headers.get("content-length", "0") or 0) > MAX_BODY_BYTES
        except ValueError:
            too_big = True
        if too_big:
            return JSONResponse({"detail": "İstek gövdesi çok büyük."}, status_code=413)
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc.lower() != host_header.lower():
            return JSONResponse({"detail": "Farklı kaynaktan gelen istek reddedildi."}, status_code=403)
    return await call_next(request)


async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")  # uygulama kendi PDF'ini çerçeveler
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    ctype = response.headers.get("content-type", "")
    if ctype.startswith("text/html"):
        # PDF yanıtlarına CSP verilmez: tarayıcının PDF görüntüleyicisi object-src kuralına takılır.
        response.headers.setdefault("Content-Security-Policy", CSP)
    elif request.url.path.startswith("/api/") and "/pdf/" not in request.url.path:
        response.headers.setdefault("Cache-Control", "no-store")
    return response
