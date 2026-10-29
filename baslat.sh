#!/usr/bin/env bash
# macOS / Linux başlatıcısı. NOT: Bu betik Windows'ta geliştirildi, macOS/Linux'ta DENENMEDİ.
set -e
cd "$(dirname "$0")"

PY=""
for c in python3.12 python3.11 python3.13 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)'; then
        PY="$c"; break
    fi
done
if [ -z "$PY" ]; then
    echo "[HATA] Python 3.11 veya üzeri bulunamadı. https://www.python.org/downloads/ adresinden kurun." >&2
    exit 1
fi

if [ ! -x .venv/bin/python ]; then
    echo "[*] İlk kurulum: sanal ortam oluşturuluyor..."
    "$PY" -m venv .venv
fi

if ! cmp -s requirements.txt .venv/requirements.installed; then
    echo "[*] Bağımlılıklar kuruluyor (ilk seferde birkaç dakika sürebilir)..."
    .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
    cp requirements.txt .venv/requirements.installed
fi

echo "[*] Uygulama başlatılıyor. Kapatmak için Ctrl+C."
exec .venv/bin/python run_server.py
