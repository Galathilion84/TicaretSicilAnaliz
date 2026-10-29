import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.backends import fail

from app.core import secret_store
from app.core.config import settings
from app.services.session_manager import TSGSessionManager


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        self.data = {}

    def set_password(self, service, username, password):
        self.data[(service, username)] = password

    def get_password(self, service, username):
        return self.data.get((service, username))

    def delete_password(self, service, username):
        self.data.pop((service, username), None)


@pytest.fixture
def vault(monkeypatch):
    monkeypatch.delenv("TS_DISABLE_KEYRING", raising=False)
    previous = keyring.get_keyring()
    mem = MemoryKeyring()
    keyring.set_keyring(mem)
    yield mem
    keyring.set_keyring(previous)


@pytest.fixture
def no_vault(monkeypatch):
    monkeypatch.delenv("TS_DISABLE_KEYRING", raising=False)
    previous = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    yield
    keyring.set_keyring(previous)


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "BASE_DIR", tmp_path)
    return tmp_path / ".env"


def test_save_and_load_roundtrip(vault):
    assert secret_store.available()
    assert secret_store.save({"TSG_EMAIL": "a@b.c", "TSG_PASSWORD": "p", "GEMINI_API_KEY": "k", "BASKA": "yok sayilir"})
    assert secret_store.load() == {"TSG_EMAIL": "a@b.c", "TSG_PASSWORD": "p", "GEMINI_API_KEY": "k"}
    secret_store.save({"GEMINI_API_KEY": ""})  # boş değer siler
    assert "GEMINI_API_KEY" not in secret_store.load()


def test_apply_to_prefers_explicit_env_over_vault(vault):
    secret_store.save({"TSG_EMAIL": "kasa@x.y", "TSG_PASSWORD": "kasa-p"})

    class S:
        TSG_EMAIL = "env@x.y"
        TSG_PASSWORD = ""
        GEMINI_API_KEY = ""

    s = S()
    secret_store.apply_to(s)
    assert (s.TSG_EMAIL, s.TSG_PASSWORD) == ("env@x.y", "kasa-p")


def test_unavailable_without_backend(no_vault):
    assert not secret_store.available()
    assert secret_store.load() == {}
    assert secret_store.save({"TSG_EMAIL": "a"}) is False


async def test_update_credentials_uses_vault_and_scrubs_plaintext_env(vault, env_file, monkeypatch):
    env_file.write_text('PORT=9000\nTSG_PASSWORD="eski-duz-metin"\nGEMINI_API_KEY="eski-anahtar"\n', encoding="utf-8")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    mgr = TSGSessionManager()
    assert await mgr.update_credentials("yeni@x.y", "yeni-parola", "yeni-anahtar")
    assert vault.data[(secret_store.SERVICE, "TSG_PASSWORD")] == "yeni-parola"
    text = env_file.read_text(encoding="utf-8")
    assert "eski-duz-metin" not in text and "eski-anahtar" not in text and "yeni-parola" not in text
    assert "PORT=9000" in text  # ilgisiz ayarlara dokunulmaz


async def test_update_credentials_falls_back_to_env_file(no_vault, env_file, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    mgr = TSGSessionManager()
    assert await mgr.update_credentials("a@b.c", "p", None)
    text = env_file.read_text(encoding="utf-8")
    assert 'TSG_EMAIL="a@b.c"' in text and 'TSG_PASSWORD="p"' in text


async def test_update_credentials_rejects_newlines(vault, env_file):
    with pytest.raises(ValueError):
        await TSGSessionManager().update_credentials("a@b.c", "p\nEVIL=1", None)
