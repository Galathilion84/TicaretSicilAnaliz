import os
import time

from app.services.cache import (
    LRUCache, atomic_write_bytes, prune_dir, announcement_key, gazette_key,
)


def test_lru_evicts_least_recently_used():
    c = LRUCache(2)
    c["a"] = 1
    c["b"] = 2
    c.get("a")  # a artık en yeni
    c["c"] = 3
    assert "b" not in c and "a" in c and "c" in c


def test_atomic_write_replaces_and_leaves_no_tmp(tmp_path):
    p = tmp_path / "x.bin"
    atomic_write_bytes(p, b"one")
    atomic_write_bytes(p, b"two")
    assert p.read_bytes() == b"two"
    assert [f.name for f in tmp_path.iterdir()] == ["x.bin"]


def test_prune_by_ttl_and_size(tmp_path):
    old = tmp_path / "old.pdf"
    old.write_bytes(b"x" * 10)
    past = time.time() - 40 * 86400
    os.utime(old, (past, past))
    for i in range(3):
        f = tmp_path / f"n{i}.pdf"
        f.write_bytes(b"y" * 10)
        os.utime(f, (time.time() - (3 - i), time.time() - (3 - i)))
    removed = prune_dir(tmp_path, "*.pdf", max_bytes=20, ttl_days=30)
    assert removed == 2  # old (TTL) + en eski n0 (boyut)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["n1.pdf", "n2.pdf"]


def test_keys_are_stable_across_searches():
    a = {"id": "ann_1", "mudurluk": "ankara", "sicil_no": "1", "unvan": "X", "tur": "T", "tarih": "d", "sayi": "1", "sayfa": "2"}
    b = {**a, "id": "ann_999"}
    assert announcement_key(a) == announcement_key(b)
    assert gazette_key(a) == gazette_key({**b, "unvan": "BAŞKA"})
    assert announcement_key(a) != announcement_key({**a, "sayfa": "3"})
