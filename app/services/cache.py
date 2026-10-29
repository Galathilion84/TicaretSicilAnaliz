import logging
import os
import tempfile
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Generic, Optional, TypeVar

logger = logging.getLogger(__name__)

V = TypeVar("V")


class LRUCache(Generic[V]):
    """Boyutu sınırlı, en az kullanılanı atan basit sözlük."""

    def __init__(self, max_items: int):
        self.max_items = max(1, max_items)
        self._d: "OrderedDict[str, V]" = OrderedDict()

    def get(self, key: str, default: Optional[V] = None) -> Optional[V]:
        if key in self._d:
            self._d.move_to_end(key)
            return self._d[key]
        return default

    def __setitem__(self, key: str, value: V) -> None:
        self._d[key] = value
        self._d.move_to_end(key)
        while len(self._d) > self.max_items:
            self._d.popitem(last=False)

    def __contains__(self, key: str) -> bool:
        return key in self._d

    def __len__(self) -> int:
        return len(self._d)

    def pop(self, key: str, default: Any = None) -> Any:
        return self._d.pop(key, default)

    def values(self):
        return list(self._d.values())


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Geçici dosyaya yazıp os.replace ile değiştirir; yarım dosya kalmaz."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def prune_dir(directory: Path, pattern: str, max_bytes: int, ttl_days: int) -> int:
    """TTL'i geçenleri sil, sonra toplam boyut sınırı aşılıyorsa en eskileri sil. Silinen sayısını döner."""
    removed = 0
    try:
        files = [(p, p.stat()) for p in directory.glob(pattern) if p.is_file()]
    except OSError as e:
        logger.warning("Önbellek dizini taranamadı %s: %s", directory, e)
        return 0

    cutoff = time.time() - ttl_days * 86400
    keep = []
    for p, st in files:
        if st.st_mtime < cutoff:
            removed += _unlink(p)
        else:
            keep.append((p, st))

    total = sum(st.st_size for _, st in keep)
    for p, st in sorted(keep, key=lambda x: x[1].st_mtime):
        if total <= max_bytes:
            break
        total -= st.st_size
        removed += _unlink(p)
    return removed


def _unlink(p: Path) -> int:
    try:
        p.unlink()
        return 1
    except OSError as e:
        logger.warning("Silinemedi %s: %s", p, e)
        return 0


def stable_hash(*parts: str) -> str:
    """Aramalar arası değişmeyen önbellek anahtarı (ilan ID'leri her aramada yeniden üretilir)."""
    import hashlib
    # Güvenlik amacı yok (yalnızca önbellek anahtarı); sha256'ya geçmek mevcut AI önbelleğini geçersiz kılardı.
    # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
    return hashlib.sha1("|".join((p or "").strip().upper() for p in parts).encode("utf-8"), usedforsecurity=False).hexdigest()[:24]


def gazette_key(item: dict) -> str:
    """Aynı gazete sayfası tüm şirketler için aynı PDF'tir."""
    return stable_hash(item.get("tarih", ""), item.get("sayi", ""), item.get("sayfa", ""))


def announcement_key(item: dict) -> str:
    """AI analizi şirkete ve ilana özgüdür."""
    return stable_hash(
        item.get("mudurluk", ""), item.get("sicil_no", ""), item.get("unvan", ""),
        item.get("tur", ""), item.get("tarih", ""), item.get("sayi", ""), item.get("sayfa", ""),
    )
