import io
import time
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.core import secret_store
from app.core.config import settings
from app.core.security import LocalOnly, ResourceId, host_origin_gate, security_headers
from app.services.session_manager import session_manager
from app.services.ai_service import ai_service
from app.services.pdf_cache import is_pdf
from app.services import demo_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("tsg_app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await session_manager.aclose()


app = FastAPI(
    title="Ticaret Sicil Gazetesi Arama",
    description="Ticaret Sicil Gazetesi ilanlarını arayan, gazete sayfasını gösteren ve yapay zeka ile özetleyen yerel uygulama",
    version=settings.APP_VERSION,
    lifespan=lifespan,
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    if request.url.path != "/healthz":
        logger.info("%s %s -> %s (%.0f ms)", request.method, request.url.path,
                    response.status_code, (time.perf_counter() - start) * 1000)
    return response


# En son eklenen middleware en dışta çalışır: başlıklar > host/origin > log.
app.middleware("http")(host_origin_gate)
app.middleware("http")(security_headers)

app.mount("/static", StaticFiles(directory=settings.BASE_DIR / "app" / "static"), name="static")
templates = Jinja2Templates(directory=settings.BASE_DIR / "app" / "templates")


# Alanlar TSG formuna iletilir; uzunluk ve tarih biçimi sınırlandırılır.
class SearchRequest(BaseModel):
    unvan: str = Field(max_length=200)
    city: Optional[str] = Field("", max_length=50)
    sicil_no: Optional[str] = Field("", max_length=30)
    start_date: Optional[str] = Field("", max_length=10, pattern=r"^[0-9./-]*$")
    end_date: Optional[str] = Field("", max_length=10, pattern=r"^[0-9./-]*$")
    is_demo: Optional[bool] = False


class SettingsRequest(BaseModel):
    email: Optional[str] = Field("", max_length=200)
    password: Optional[str] = Field("", max_length=200)
    gemini_api_key: Optional[str] = Field(None, max_length=200)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"app_version": settings.APP_VERSION}
    )


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "version": settings.APP_VERSION}


@app.get("/api/status")
async def get_status():
    status = await session_manager.get_status()
    status["secure_storage"] = secret_store.available()
    return status


@app.post("/api/settings", dependencies=[LocalOnly])
async def update_settings(req: SettingsRequest):
    try:
        success = await session_manager.update_credentials(req.email, req.password, req.gemini_api_key)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if success:
        return {"success": True, "message": "Bilgileriniz kaydedildi.", "secure_storage": secret_store.available()}
    raise HTTPException(status_code=500, detail="Bilgiler kaydedilemedi.")


@app.post("/api/login", dependencies=[LocalOnly])
async def trigger_login():
    success, msg = await session_manager.login()
    return {"success": success, "message": msg}


@app.post("/api/search")
async def search(req: SearchRequest):
    if not req.unvan.strip():
        raise HTTPException(status_code=400, detail="Lütfen aranacak şirket unvanını girin.")

    if req.is_demo:
        return demo_service.build_demo_search(req.unvan)

    status = await session_manager.get_status()
    if not status["has_credentials"]:
        return {
            "success": False,
            "error": "Henüz Ticaret Sicil Gazetesi e-posta ve şifresi tanımlanmamış. 'Hesap ve ayarlar' bölümünden girebilir veya 'Örnek sorgu' ile arayüzü deneyebilirsiniz.",
            "results": [],
            "companies": []
        }

    return await session_manager.search_announcements(
        unvan=req.unvan,
        city=req.city or "",
        sicil_no=req.sicil_no or "",
        start_date=req.start_date or "",
        end_date=req.end_date or ""
    )


@app.get("/api/company/summary/{company_id}")
async def get_company_summary(company_id: ResourceId):
    if demo_service.is_demo_id(company_id):
        return demo_service.demo_company_summary(company_id)
    return await session_manager.get_company_summary(company_id)


@app.get("/api/announcement/{announcement_id}")
async def get_announcement_details(announcement_id: ResourceId):
    item = demo_service.get_demo(announcement_id)
    if item:
        return {
            "success": True,
            "announcement_id": announcement_id,
            "unvan": item["title"],
            "has_pdf": True
        }
    return await session_manager.get_announcement_pdf(announcement_id)


async def _load_pdf(announcement_id: str, failure_detail: str) -> bytes:
    demo = demo_service.get_demo(announcement_id)
    if demo and demo.get("pdf_bytes"):
        return demo["pdf_bytes"]

    raw = session_manager.get_raw_pdf(announcement_id)
    if not is_pdf(raw):
        res = await session_manager.get_announcement_pdf(announcement_id, force_refresh=True)
        if not res.get("success"):
            raise HTTPException(status_code=502, detail=res.get("error", failure_detail))
        raw = session_manager.get_raw_pdf(announcement_id)

    if not is_pdf(raw):
        raise HTTPException(status_code=404, detail="Geçerli bir PDF belgesi bulunamadı.")
    return raw


@app.get("/api/download/pdf/{announcement_id}")
async def download_pdf(announcement_id: ResourceId):
    raw = await _load_pdf(announcement_id, "PDF belgesi indirilemedi.")
    return StreamingResponse(
        io.BytesIO(raw),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=gazete_{announcement_id}.pdf"}
    )


@app.get("/api/preview/pdf/{announcement_id}")
async def preview_pdf(announcement_id: ResourceId):
    raw = await _load_pdf(announcement_id, "PDF belgesi yüklenemedi.")
    return StreamingResponse(
        io.BytesIO(raw),
        media_type="application/pdf",
        headers={"Content-Disposition": "inline", "Cache-Control": "private, max-age=3600"}
    )


@app.post("/api/announcement/{announcement_id}/ai-summary")
async def get_announcement_ai_summary(announcement_id: ResourceId):
    demo = demo_service.get_demo(announcement_id)
    if demo_service.is_demo_id(announcement_id):
        item = demo or {"id": announcement_id, "unvan": "ANTİGRAVİTY BİLİŞİM VE TEKNOLOJİ A.Ş.", "tur": "Sermaye Artırımı"}
        return await ai_service.analyze_announcement(item, pdf_bytes=item.get("pdf_bytes"), is_demo=True)

    item = session_manager.get_item(announcement_id)
    if not item:
        raise HTTPException(status_code=404, detail="İlan kaydı bulunamadı.")

    pdf_bytes = session_manager.get_raw_pdf(announcement_id)
    if not pdf_bytes:
        await session_manager.get_announcement_pdf(announcement_id)
        pdf_bytes = session_manager.get_raw_pdf(announcement_id)

    return await ai_service.analyze_announcement(item, pdf_bytes=pdf_bytes, is_demo=False)
