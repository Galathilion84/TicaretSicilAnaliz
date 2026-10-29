import os
import threading
import time
import webbrowser

import uvicorn

from app.core.config import settings


def open_browser():
    time.sleep(1.5)
    url = f"http://localhost:{settings.PORT}"
    print("\n=======================================================")
    print("Ticaret Sicil Gazetesi Arama çalışıyor")
    print(f"Adres: {url}   (kapatmak için bu pencerede Ctrl+C)")
    print("=======================================================\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass


if __name__ == "__main__":
    if os.getenv("OPEN_BROWSER", "1") == "1":
        threading.Thread(target=open_browser, daemon=True).start()

    # Yalnızca bu bilgisayardan erişilir. proxy_headers kapalı: istemci adresi gerçek soket adresidir.
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=False, log_level="info",
                proxy_headers=False)
