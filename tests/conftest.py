import os

# Testler gerçek işletim sistemi kimlik kasasına dokunmasın.
os.environ["TS_DISABLE_KEYRING"] = "1"

import pytest  # noqa: E402

from app.core.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _test_env(monkeypatch):
    # TestClient'ın Host başlığı "testserver".
    monkeypatch.setattr(settings, "ALLOWED_HOSTS", ["testserver", "localhost", "127.0.0.1", "::1"])
