import httpx
import pytest
from fastapi.testclient import TestClient

from app.core import security
from app.core.config import settings
from app.main import app
from app.services import proxy
from app.services.ai_service import ai_service, sanitize_analysis
from app.services.proxy import mask_proxy
from app.services.session_manager import (
    OffsiteRequest, TSGSessionManager, _only_tsg, parse_rows, tsg_url,
)

client = TestClient(app, client=("127.0.0.1", 50000))


# --- DNS rebinding / CSRF -------------------------------------------------
def test_foreign_host_header_rejected(monkeypatch):
    monkeypatch.setattr(settings, "ALLOWED_HOSTS", ["localhost", "127.0.0.1", "::1"])
    assert client.get("/api/status", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/api/status", headers={"Host": "localhost:8000"}).status_code == 200
    assert client.get("/api/status", headers={"Host": "127.0.0.1:8000"}).status_code == 200


def test_cross_origin_post_rejected():
    body = {"unvan": "x", "is_demo": True}
    assert client.post("/api/search", json=body, headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.post("/api/search", json=body, headers={"Origin": "http://testserver"}).status_code == 200
    assert client.post("/api/search", json=body).status_code == 200


def test_oversized_body_rejected():
    r = client.post("/api/search", content=b"x" * 70_000, headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_forwarded_requests_are_not_treated_as_local():
    class FakeReq:
        def __init__(self, headers):
            self.headers = headers
            self.client = type("C", (), {"host": "127.0.0.1"})()

    assert security._is_direct_loopback(FakeReq({}))
    assert not security._is_direct_loopback(FakeReq({"x-forwarded-for": "10.1.2.3"}))
    assert not security._is_direct_loopback(FakeReq({"forwarded": "for=10.1.2.3"}))


# --- başlıklar -----------------------------------------------------------
def test_security_headers_and_csp_only_on_html():
    page = client.get("/")
    assert "frame-ancestors 'self'" in page.headers["content-security-policy"]
    assert page.headers["x-content-type-options"] == "nosniff"
    assert "cdn.tailwindcss.com" not in page.text  # üçüncü taraf betik yok
    api = client.get("/api/status")
    assert api.headers["cache-control"] == "no-store" and "content-security-policy" not in api.headers

    demo = client.post("/api/search", json={"unvan": "x", "is_demo": True}).json()
    pdf = client.get(f"/api/preview/pdf/{demo['results'][0]['id']}")
    assert "content-security-policy" not in pdf.headers  # PDF görüntüleyiciyi bozmamak için


# --- SSRF ------------------------------------------------------------------
@pytest.mark.parametrize("href", [
    "http://169.254.169.254/latest/meta-data",
    "https://evil.example/x.pdf",
    "http://www.ticaretsicil.gov.tr/x.pdf",  # düz http
    "https://www.ticaretsicil.gov.tr.evil.example/x.pdf",
    "//evil.example/x.pdf",
    "https://user@evil.example/x.pdf",
])
def test_tsg_url_rejects_offsite(href):
    assert tsg_url(href) is None


def test_tsg_url_accepts_tsg_paths():
    assert tsg_url("/tmp_gazete/a.pdf") == "https://www.ticaretsicil.gov.tr/tmp_gazete/a.pdf"
    assert tsg_url("pdf_goster.php?g=1").startswith("https://www.ticaretsicil.gov.tr/view/hizlierisim/")


def test_parse_rows_drops_offsite_pdf_link():
    html = ('<table><tr><td>A</td><td>1</td><td>U</td><td>d</td><td>1</td><td>2</td><td>t</td>'
            '<td><a href="http://10.0.0.5/pdf_goster.php?x=1">PDF</a></td></tr></table>')
    row = parse_rows(html)[0]
    assert row["pdf_url"] is None and row["has_pdf"] is False


async def test_http_client_blocks_offsite_requests_including_redirects():
    mgr = TSGSessionManager()
    http = mgr._get_client()
    with pytest.raises(OffsiteRequest):
        await http.get("https://evil.example/")
    await http.aclose()
    with pytest.raises(OffsiteRequest):
        await _only_tsg(httpx.Request("GET", "http://www.ticaretsicil.gov.tr/"))


async def test_download_is_size_capped(monkeypatch):
    monkeypatch.setattr(settings, "MAX_PDF_MB", 1)
    big = httpx.MockTransport(lambda r: httpx.Response(200, content=b"%PDF" + b"0" * (2 * 1024 * 1024)))
    async with httpx.AsyncClient(transport=big) as c:
        with pytest.raises(ValueError):
            await TSGSessionManager._download_limited(c, "https://www.ticaretsicil.gov.tr/a.pdf", "r")
    small = httpx.MockTransport(lambda r: httpx.Response(200, content=b"%PDF-small"))
    async with httpx.AsyncClient(transport=small) as c:
        assert await TSGSessionManager._download_limited(c, "https://www.ticaretsicil.gov.tr/a.pdf", "r") == b"%PDF-small"


async def test_busy_queue_times_out_with_friendly_message(monkeypatch):
    monkeypatch.setattr(settings, "LOCK_TIMEOUT_SEC", 0.05)
    mgr = TSGSessionManager()
    await mgr._lock.acquire()
    res = await mgr.search_announcements("x")
    assert res["success"] is False and res["busy"] is True and "yoğun" in res["error"]
    assert mgr._waiting == 0
    mgr._lock.release()


# --- bilgi sızıntısı / önbellek --------------------------------------------
def test_mask_proxy_hides_credentials():
    assert mask_proxy("http://user:p%40ss@proxy.firma:8080") == "http://***@proxy.firma:8080"
    assert mask_proxy("http://proxy.firma:8080") == "http://proxy.firma:8080"
    assert mask_proxy(None) == ""


def test_demo_ai_summary_does_not_touch_shared_cache():
    before = len(ai_service._cache)
    for i in range(5):
        r = client.post(f"/api/announcement/demo_attack{i}/ai-summary")
        assert r.status_code == 200 and r.json()["success"]
    assert len(ai_service._cache) == before


def test_no_exception_text_in_search_error(monkeypatch):
    from app.services.session_manager import session_manager

    async def boom(*a, **k):
        raise RuntimeError("http://user:secret@10.0.0.1/internal")

    monkeypatch.setattr(settings, "TSG_EMAIL", "a@b.c")
    monkeypatch.setattr(settings, "TSG_PASSWORD", "x")
    monkeypatch.setattr(session_manager, "is_session_alive", boom)
    r = client.post("/api/search", json={"unvan": "x"})
    assert "secret" not in r.text and "10.0.0.1" not in r.text


# --- Gemini çıktısı güvenilmez veridir ----------------------------------------
def test_sanitize_drops_unknown_keys_and_bounds_sizes():
    evil = {
        "yonetici_ozeti": "A" * 5000,
        "onemli_notlar": ["n"] * 500,
        "sermaye_degisimi": {"yeni_sermaye": None, "x" * 200: "y"},
        "__proto__": "pwn",
        "calistir": "rm -rf /",
    }
    clean = sanitize_analysis(evil)
    assert set(clean) == {"yonetici_ozeti", "onemli_notlar", "sermaye_degisimi"}
    assert len(clean["yonetici_ozeti"]) == 1000
    assert len(clean["onemli_notlar"]) == 50
    assert clean["sermaye_degisimi"]["yeni_sermaye"] == "-"
    assert all(len(k) <= 60 for k in clean["sermaye_degisimi"])


def test_sanitize_rejects_non_object():
    for bad in ([], "metin", 5, None):
        with pytest.raises(ValueError):
            sanitize_analysis(bad)


# --- PAC yalnızca http(s) -------------------------------------------------------
def test_pac_scheme_restricted(monkeypatch):
    import sys
    import types

    seen = []

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def query(key, name):
        return (0, 0) if name == "ProxyEnable" else ("", 0) if name == "ProxyServer" else ("file:///C:/Windows/win.ini", 0)

    fake = types.SimpleNamespace(HKEY_CURRENT_USER=0, OpenKey=lambda *a: Key(), QueryValueEx=query)
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(proxy.urllib.request, "urlopen", lambda *a, **k: seen.append(a) or (_ for _ in ()).throw(AssertionError("açılmamalı")))
    assert proxy._windows_proxy() is None
    assert not seen
