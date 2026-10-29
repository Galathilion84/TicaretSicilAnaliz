import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in ("true", "1", "yes")


class Settings:
    APP_VERSION: str = "2.0.0"
    BASE_DIR: Path = BASE_DIR

    # Kimlik bilgileri: ortam değişkeni/.env > işletim sistemi kimlik kasası (bkz. secret_store).
    TSG_EMAIL: str = os.getenv("TSG_EMAIL", "")
    TSG_PASSWORD: str = os.getenv("TSG_PASSWORD", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    # Uygulama yalnızca bu bilgisayardan erişilebilir olacak şekilde tasarlanmıştır; adres değiştirilemez.
    HOST: str = "127.0.0.1"
    PORT: int = int(os.getenv("PORT", "8000"))
    # Kabul edilen Host başlıkları (DNS rebinding koruması).
    ALLOWED_HOSTS: list = ["localhost", "127.0.0.1", "::1"]

    MAX_PDF_MB: int = int(os.getenv("MAX_PDF_MB", "40"))
    # TSG işlem kuyruğunda en fazla bekleme süresi (sn).
    LOCK_TIMEOUT_SEC: int = int(os.getenv("LOCK_TIMEOUT_SEC", "120"))
    # TSG TLS doğrulaması. Kurumsal SSL denetimi varsa TSG_CA_BUNDLE ile CA dosyasını verin.
    TSG_VERIFY_TLS: bool = _env_bool("TSG_VERIFY_TLS", True)
    TSG_CA_BUNDLE: str = os.getenv("TSG_CA_BUNDLE", "")

    # Gemini model sırası (virgülle ayrılmış, ilk başarılı olan kullanılır)
    GEMINI_MODELS: list = [
        m.strip() for m in os.getenv(
            "GEMINI_MODELS", "gemini-flash-lite-latest,gemini-flash-latest"
        ).split(",") if m.strip()
    ]
    GEMINI_TIMEOUT_SEC: int = int(os.getenv("GEMINI_TIMEOUT_SEC", "60"))

    # Önbellek sınırları
    PDF_CACHE_MAX_MB: int = int(os.getenv("PDF_CACHE_MAX_MB", "500"))
    PDF_CACHE_TTL_DAYS: int = int(os.getenv("PDF_CACHE_TTL_DAYS", "30"))
    MEM_CACHE_ITEMS: int = int(os.getenv("MEM_CACHE_ITEMS", "500"))
    MEM_PDF_ITEMS: int = int(os.getenv("MEM_PDF_ITEMS", "20"))

    # Base URL for Ticaret Sicil Gazetesi
    BASE_URL: str = "https://www.ticaretsicil.gov.tr"
    LOGIN_URL: str = "https://www.ticaretsicil.gov.tr/"

    DATA_DIR: Path = BASE_DIR / "data"
    TEMP_DIR: Path = BASE_DIR / "temp_data"


settings = Settings()
settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)

# Ortam değişkeni/.env boş bıraktığı alanları kimlik kasasından doldur.
from app.core import secret_store  # noqa: E402

secret_store.apply_to(settings)
