import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.session_manager import session_manager

# Yerel uygulama: tarayıcı bu bilgisayardan (loopback) bağlanır.
client = TestClient(app, client=("127.0.0.1", 50000))
remote = TestClient(app, client=("10.1.2.3", 50000))


@pytest.fixture
def fake_update(monkeypatch):
    calls = []

    async def fake(email, password, key):
        calls.append((email, password, key))
        return True

    monkeypatch.setattr(session_manager, "update_credentials", fake)
    return calls


def test_healthz():
    assert client.get("/healthz").json()["status"] == "ok"


def test_settings_only_from_this_computer(fake_update):
    body = {"email": "a@b.c", "password": "p"}
    assert remote.post("/api/settings", json=body).status_code == 403
    assert client.post("/api/settings", json=body, headers={"X-Forwarded-For": "10.1.2.3"}).status_code == 403
    assert not fake_update
    assert client.post("/api/settings", json=body).status_code == 200
    assert len(fake_update) == 1


def test_login_endpoint_also_local_only():
    assert remote.post("/api/login").status_code == 403


def test_status_masks_email_and_reports_storage(monkeypatch):
    monkeypatch.setattr(settings, "TSG_EMAIL", "ahmet@firma.com")
    monkeypatch.setattr(settings, "TSG_PASSWORD", "x")
    status = client.get("/api/status").json()
    assert status["email"] == "a***@firma.com"
    assert status["secure_storage"] is False  # testlerde kasa devre dışı


@pytest.mark.parametrize("bad", ["..%5C..%5Cx", "a.b", "a%20b", "x" * 65])
def test_invalid_ids_rejected(bad):
    assert client.get(f"/api/preview/pdf/{bad}").status_code == 422


def test_search_validation():
    assert client.post("/api/search", json={"unvan": "x", "start_date": "<script>"}).status_code == 422
    assert client.post("/api/search", json={"unvan": "x" * 201}).status_code == 422
    assert client.post("/api/search", json={"unvan": "   "}).status_code == 400


def test_search_without_credentials_explains_what_to_do(monkeypatch):
    monkeypatch.setattr(settings, "TSG_EMAIL", "")
    monkeypatch.setattr(settings, "TSG_PASSWORD", "")
    res = client.post("/api/search", json={"unvan": "ACME"}).json()
    assert res["success"] is False and "Hesap ve ayarlar" in res["error"]


def test_demo_flow_end_to_end():
    res = client.post("/api/search", json={"unvan": "Test Holding", "is_demo": True}).json()
    assert res["success"] and res["multiple_companies"]
    ann_id = res["results"][0]["id"]
    assert ann_id.startswith("demo_")

    pdf = client.get(f"/api/preview/pdf/{ann_id}")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    comp_id = res["companies"][0]["company_id"]
    summary = client.get(f"/api/company/summary/{comp_id}").json()["summary"]
    for t in summary["timeline"]:
        assert client.get(f"/api/announcement/{t['announcement_id']}").json()["success"]


def test_unknown_non_demo_announcement():
    assert client.post("/api/announcement/ann_unknown00/ai-summary").status_code == 404
    assert client.get("/api/announcement/ann_unknown00").json()["success"] is False
