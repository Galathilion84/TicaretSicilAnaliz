import logging
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.services.cache import LRUCache, atomic_write_bytes, prune_dir

logger = logging.getLogger(__name__)

PDF_CACHE_DIR: Path = settings.DATA_DIR / "pdf_cache"
PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def is_pdf(data: Optional[bytes]) -> bool:
    return bool(data) and data.strip().startswith(b"%PDF")


class PdfCache:
    """Bellekte LRU + diskte TTL/boyut sınırlı gazete PDF önbelleği (anahtar: gazete sayfası)."""

    def __init__(self, directory: Path = PDF_CACHE_DIR):
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        self._mem: LRUCache[bytes] = LRUCache(settings.MEM_PDF_ITEMS)
        self.prune()

    def prune(self) -> int:
        return prune_dir(self.dir, "*.pdf", settings.PDF_CACHE_MAX_MB * 1024 * 1024, settings.PDF_CACHE_TTL_DAYS)

    def get(self, key: str) -> Optional[bytes]:
        raw = self._mem.get(key)
        if is_pdf(raw):
            return raw
        path = self.dir / f"{key}.pdf"
        try:
            data = path.read_bytes()
        except OSError:
            return None
        if is_pdf(data):
            self._mem[key] = data
            return data
        return None

    def put(self, key: str, data: bytes) -> None:
        if not is_pdf(data):
            return
        self._mem[key] = data
        try:
            atomic_write_bytes(self.dir / f"{key}.pdf", data)
        except OSError as e:
            logger.warning("PDF diske yazılamadı (%s): %s", key, e)

    def drop(self, key: str) -> None:
        self._mem.pop(key, None)
