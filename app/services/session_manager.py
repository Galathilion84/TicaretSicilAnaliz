import os
import re
import asyncio
import logging
import json
import time
import uuid
from contextlib import asynccontextmanager
from functools import wraps
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urljoin, urlsplit
import httpx
from bs4 import BeautifulSoup

from app.core import secret_store
from app.core.config import settings
from app.services.cache import LRUCache, atomic_write_bytes, gazette_key
from app.services.captcha import captcha_solver
from app.services.analyzer import company_analyzer, extract_ocr_text
from app.services.ai_service import ai_service
from app.services.pdf_cache import PdfCache, is_pdf
from app.services.proxy import get_system_proxy, mask_proxy

logger = logging.getLogger(__name__)

TSG = "https://www.ticaretsicil.gov.tr"
VIEW = f"{TSG}/view/hizlierisim"
SEARCH_REFERER = f"{VIEW}/ilangoruntuleme.php"
LOGIN_REFERER = f"{VIEW}/girisyap.php"
TSG_HOST = "www.ticaretsicil.gov.tr"


class BusyError(Exception):
    """TSG işlem kuyruğunda LOCK_TIMEOUT_SEC içinde sıra gelmedi."""

    def __init__(self, waiting: int):
        super().__init__(f"{waiting} işlem sırada")
        self.waiting = waiting


def _busy_to_error(fn):
    @wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except BusyError as e:
            return {"success": False, "busy": True, "results": [], "companies": [],
                    "error": f"Sistem şu an yoğun ({e.waiting} işlem sırada). Lütfen birkaç saniye sonra tekrar deneyin."}
    return wrapper


class OffsiteRequest(httpx.RequestError):
    """TSG dışı bir adrese (SSRF / açık yönlendirme) giden istek."""


def tsg_url(href: str) -> Optional[str]:
    """TSG sayfalarından gelen bağlantıyı mutlak URL'ye çevirir; TSG dışındaysa None döner."""
    url = urljoin(f"{VIEW}/", href or "")
    parts = urlsplit(url)
    return url if parts.scheme == "https" and parts.hostname == TSG_HOST else None


async def _only_tsg(request: httpx.Request) -> None:
    # Her istekte (yönlendirmeler dahil) çalışır: oturum çerezleri ve sunucu ağı yalnızca TSG'ye gider.
    if request.url.scheme != "https" or request.url.host != TSG_HOST:
        raise OffsiteRequest(f"TSG dışı adres engellendi: {request.url.host}", request=request)

# Load cities mapping
CITIES_MAP: Dict[str, str] = {}
cities_file = settings.BASE_DIR / "app" / "core" / "cities.json"
if cities_file.exists():
    try:
        with open(cities_file, "r", encoding="utf-8") as f:
            CITIES_MAP = json.load(f)
    except Exception as e:
        logger.warning(f"Could not load cities.json: {e}")


def resolve_city_id(city_name: str) -> str:
    if not city_name:
        return "232"
    clean = city_name.strip().upper()
    if clean in CITIES_MAP:
        return CITIES_MAP[clean]
    for k, v in CITIES_MAP.items():
        if clean in k or k in clean:
            return v
    return "232"


def build_search_data(city: str, unvan: str, sicil_no: str, start_date: str, end_date: str) -> Dict[str, str]:
    return {
        "SicilMudurluguId": resolve_city_id(city),
        "TicaretUnvani": (unvan or "").strip(),
        "TicSicNo": (sicil_no or "").strip(),
        "BagliIlan": "",
        "Tarih": "1" if start_date else "",
        "Tarih1": (start_date or "").strip(),
        "Tarih2": (end_date or "").strip(),
    }


def parse_rows(html: str, min_cells: int = 4) -> List[Dict[str, Any]]:
    """TSG sonuç tablosunu satır sözlüklerine çevirir (arama ve oturum yenilemede ortak)."""
    rows = []
    for i, row in enumerate(BeautifulSoup(html, "html.parser").find_all("tr")):
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) < min_cells:
            continue
        pdf_link = None
        for a in row.find_all("a"):
            href = a.get("href", "")
            if "pdf_goster.php" in href:
                pdf_link = tsg_url(href)
                break
        def cell(n, default=""):
            return cells[n] if len(cells) > n else default

        rows.append({
            "row_index": i,
            "mudurluk": cell(0), "sicil_no": cell(1), "unvan": cell(2),
            "tarih": cell(3), "sayi": cell(4), "sayfa": cell(5), "tur": cell(6, "İlan"),
            "pdf_url": pdf_link, "has_pdf": bool(pdf_link),
        })
    return rows


def select_key_announcements(announcements: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Özet için en bilgilendirici ilanlar: en yeni, kuruluş, son sermaye, son yönetim/temsil."""
    target: Dict[str, Dict[str, Any]] = {announcements[0]["id"]: announcements[0]}

    for a in reversed(announcements):
        if any(k in a.get("tur", "").upper() for k in ["KURULUŞ", "ANA SÖZLEŞME", "HÜKÜM"]):
            target[a["id"]] = a
            break
    else:
        target[announcements[-1]["id"]] = announcements[-1]

    for a in announcements:
        if "SERMAYE" in a.get("tur", "").upper():
            target[a["id"]] = a
            break

    for a in announcements:
        if any(k in a.get("tur", "").upper() for k in ["YÖNETİM", "TEMSİL", "ORTAK", "MÜDÜR", "GENEL KURUL"]):
            target[a["id"]] = a
            break
    return target


def _env_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def mask_email(email: str) -> str:
    if "@" not in email:
        return email
    name, _, domain = email.partition("@")
    return f"{name[:1]}***@{domain}"


class TSGSessionManager:
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._is_logged_in = False
        self._lock = asyncio.Lock()
        self._waiting = 0  # kilidi bekleyen işlem sayısı
        n = settings.MEM_CACHE_ITEMS
        self._cached_results: LRUCache[Dict[str, Any]] = LRUCache(n * 4)
        self._cached_companies: LRUCache[Dict[str, Any]] = LRUCache(n)
        self._cached_texts: LRUCache[str] = LRUCache(n)
        self._pdfs = PdfCache()
        self._last_search_params: Optional[Dict[str, Any]] = None
        self._last_login_time: float = 0.0

    # ------------------------------------------------------------------ HTTP
    def _verify(self):
        if settings.TSG_CA_BUNDLE:
            return settings.TSG_CA_BUNDLE
        if not settings.TSG_VERIFY_TLS:
            return False
        # İşletim sistemi sertifika deposu: kurumsal SSL denetimi CA'sı Windows'ta kuruluysa çalışır.
        import ssl
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            }
            proxy = get_system_proxy()
            if proxy:
                logger.info("Using corporate web proxy for TTSG: %s", mask_proxy(proxy))
            self._client = httpx.AsyncClient(
                proxy=proxy,
                headers=headers,
                follow_redirects=True,
                verify=self._verify(),
                timeout=35.0,
                event_hooks={"request": [_only_tsg]},
            )
        return self._client

    @asynccontextmanager
    async def _exclusive(self):
        """TSG oturumu tek seferde bir işleme ayrılır; sırayı bekleyen sayısı izlenir, bekleme sınırlıdır."""
        self._waiting += 1
        try:
            await asyncio.wait_for(self._lock.acquire(), settings.LOCK_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            raise BusyError(self._waiting - 1)
        finally:
            self._waiting -= 1
        try:
            yield
        finally:
            self._lock.release()

    def uncached_ai_targets(self, company_id: str) -> int:
        """Bu şirket özeti için henüz önbellekte olmayan (yani Gemini çağırtacak) ilan sayısı."""
        company = self._cached_companies.get(company_id)
        if not company or not company.get("announcements") or not ai_service.has_api_key():
            return 0
        return sum(1 for a in select_key_announcements(company["announcements"]).values() if not ai_service.get_cached(a))

    async def aclose(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def is_session_alive(self) -> bool:
        if not self._is_logged_in:
            return False
        try:
            r = await self._get_client().get(SEARCH_REFERER)
            return "cikis.php" in r.text
        except httpx.HTTPError as e:
            logger.warning(f"Session liveness check failed: {e}")
            return False

    async def get_status(self) -> Dict[str, Any]:
        has_credentials = bool(settings.TSG_EMAIL and settings.TSG_PASSWORD)
        return {
            "has_credentials": has_credentials,
            "email": mask_email(settings.TSG_EMAIL) if has_credentials else "",
            "has_gemini_key": ai_service.has_api_key(),
            "is_logged_in": self._is_logged_in,
            "queue": self._waiting,
        }

    # ------------------------------------------------------------ credentials
    async def update_credentials(self, email: str, password: str, gemini_api_key: Optional[str] = None) -> bool:
        values = {"TSG_EMAIL": (email or "").strip(), "TSG_PASSWORD": (password or "").strip()}
        if gemini_api_key is not None:
            values["GEMINI_API_KEY"] = gemini_api_key.strip()
        values = {k: v for k, v in values.items() if v or k == "GEMINI_API_KEY"}

        if any(c in v for v in values.values() for c in "\r\n\x00"):
            raise ValueError("Değerler satır sonu karakteri içeremez.")

        for k, v in values.items():
            setattr(settings, k, v)
            if k == "GEMINI_API_KEY":
                os.environ[k] = v

        self._is_logged_in = False
        await self.aclose()

        try:
            if secret_store.save(values):
                # Kasaya yazıldı: aynı sırların düz metin kopyaları .env'de kalmasın.
                self._rewrite_env({}, remove=set(values))
            else:
                logger.warning("İşletim sistemi kimlik kasası yok; bilgiler .env dosyasına yazılıyor.")
                self._rewrite_env(values)
            return True
        except OSError as e:
            logger.error(f"Failed to update .env: {e}")
            return False

    @staticmethod
    def _rewrite_env(set_values: Dict[str, str], remove=frozenset()) -> None:
        env_path = settings.BASE_DIR / ".env"
        if not env_path.exists() and not set_values:
            return
        lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
        written = set()
        out = []
        for line in lines:
            key = line.split("=", 1)[0].strip()
            if key in remove:
                continue
            if key in set_values:
                out.append(f"{key}={_env_quote(set_values[key])}")
                written.add(key)
            else:
                out.append(line)
        out += [f"{k}={_env_quote(v)}" for k, v in set_values.items() if k not in written]
        atomic_write_bytes(env_path, ("\n".join(out) + "\n").encode("utf-8"))

    # ------------------------------------------------------------------ login
    async def _solve_captcha_image(self, content: bytes) -> Optional[str]:
        # OCR CPU-yoğun ve senkron: olay döngüsünü bloklamasın.
        return await asyncio.to_thread(captcha_solver.solve, content)

    @staticmethod
    def _captcha_url(soup: BeautifulSoup) -> str:
        cap_img = soup.find("img", {"id": "CaptchaImg"})
        src = cap_img.get("src") if cap_img else f"/captcha/captcha.php?{int(time.time() * 1000)}"
        return src if src.startswith("http") else f"{TSG}{src}"

    async def login(self, max_retries: int = 4) -> Tuple[bool, str]:
        if not settings.TSG_EMAIL or not settings.TSG_PASSWORD:
            return False, "Ticaret Sicil Gazetesi e-posta veya şifre tanımlanmamış. Lütfen Ayarlar bölümünden girin."

        # Debounce login requests to protect against WAF rate-limiting
        time_since_last = time.time() - self._last_login_time
        if time_since_last < 2.5:
            await asyncio.sleep(2.5 - time_since_last)
        self._last_login_time = time.time()

        client = self._get_client()
        for attempt in range(1, max_retries + 1):
            logger.info(f"Login attempt {attempt}/{max_retries}...")
            try:
                r_page = await client.get(LOGIN_REFERER, headers={"Referer": f"{TSG}/"})
                r_cap = await client.get(self._captcha_url(BeautifulSoup(r_page.text, "html.parser")))
                code = await self._solve_captcha_image(r_cap.content)
                if not code:
                    continue

                r_login = await client.post(
                    f"{TSG}/view/modal/uyegirisi_ok.php",
                    data={"LoginEmail": settings.TSG_EMAIL, "LoginSifre": settings.TSG_PASSWORD, "Captcha": code},
                    headers={"X-Requested-With": "XMLHttpRequest", "Referer": LOGIN_REFERER},
                )

                if r_login.text.strip() == "1":
                    # Navigate to ilan goruntuleme page to firmly establish session cookies
                    try:
                        await client.get(SEARCH_REFERER, headers={"Referer": LOGIN_REFERER})
                    except httpx.HTTPError as e:
                        logger.warning(f"Post-login page warm-up failed (ignored): {e}")
                    self._is_logged_in = True
                    logger.info("Successfully logged in via HTTP and session verified!")
                    return True, "Giriş Başarılı"
                await asyncio.sleep(1)

            except httpx.HTTPError as e:
                logger.error(f"Error during login attempt {attempt}: {e}")
                await asyncio.sleep(1)

        return False, "Giriş yapılamadı. Lütfen e-posta ve şifrenizi kontrol edin."

    # ----------------------------------------------------------------- search
    async def _post_search(self, client: httpx.AsyncClient, data: Dict[str, str]) -> httpx.Response:
        return await client.post(
            f"{VIEW}/ilangoruntuleme_ok.php",
            data=data,
            headers={"X-Requested-With": "XMLHttpRequest", "Referer": SEARCH_REFERER},
        )

    @_busy_to_error
    async def search_announcements(
        self,
        unvan: str,
        city: str = "",
        sicil_no: str = "",
        start_date: str = "",
        end_date: str = ""
    ) -> Dict[str, Any]:
        """
        Executes announcement search on Ticaret Sicil Gazetesi using pure HTTP requests.
        """
        def fail(msg: str) -> Dict[str, Any]:
            return {"success": False, "error": msg, "results": [], "companies": []}

        async with self._exclusive():
            client = self._get_client()

            if not self._is_logged_in or not await self.is_session_alive():
                logger.info("Session not active on TTSG. Logging in before search...")
                self._is_logged_in = False
                success, msg = await self.login()
                if not success:
                    return fail(msg)

            try:
                logger.info("Searching city=%r unvan=%r", city, unvan)  # %r: satır sonu enjeksiyonunu etkisiz kılar
                search_data = build_search_data(city, unvan, sicil_no, start_date, end_date)
                r_search = await self._post_search(client, search_data)

                if "girisyap.php" in str(r_search.url) or "Giriş" in r_search.text[:200]:
                    self._is_logged_in = False
                    success, msg = await self.login()
                    if not success:
                        return fail(msg)
                    r_search = await self._post_search(client, search_data)

                results = []
                for row in parse_rows(r_search.text):
                    item = {"id": f"ann_{uuid.uuid4().hex[:10]}", **row}
                    results.append(item)
                    self._cached_results[item["id"]] = item
                logger.info(f"Search returned {len(results)} announcements.")

                # Group announcements by company
                companies_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
                for item in results:
                    raw_sicil = item["sicil_no"].strip()
                    clean_sicil = re.sub(r'[-\s/]+0$', '', raw_sicil)
                    mudurluk_clean = item["mudurluk"].strip().upper()
                    key = (mudurluk_clean, clean_sicil or item["unvan"].strip().upper())

                    if key not in companies_map:
                        c_id = f"comp_{uuid.uuid4().hex[:8]}"
                        companies_map[key] = {
                            "company_id": c_id,
                            "unvan": item["unvan"].strip(),
                            "sicil_no": raw_sicil,
                            "mudurluk": item["mudurluk"].strip(),
                            "latest_date": item["tarih"],
                            "announcements": []
                        }
                        self._cached_companies[c_id] = companies_map[key]
                    elif len(item["unvan"].strip()) > len(companies_map[key]["unvan"]):
                        # Prefer longer, fuller trade title if available
                        companies_map[key]["unvan"] = item["unvan"].strip()

                    companies_map[key]["announcements"].append(item)

                companies_list = list(companies_map.values())
                self._last_search_params = {
                    "unvan": unvan, "city": city, "sicil_no": sicil_no,
                    "start_date": start_date, "end_date": end_date,
                }

                return {
                    "success": True,
                    "count": len(results),
                    "multiple_companies": len(companies_list) > 1,
                    "companies": companies_list,
                    "results": results
                }

            except Exception as e:
                logger.error(f"Search error: {e}", exc_info=True)
                return fail("Arama sırasında beklenmeyen bir hata oluştu. Ayrıntılar sunucu günlüğünde.")

    async def _refresh_search_context(self, client: httpx.AsyncClient):
        """Re-issues the search query to re-register announcement GUIDs in a new PHP session."""
        if not self._last_search_params:
            return
        try:
            p = self._last_search_params
            r_search = await self._post_search(
                client, build_search_data(p.get("city", ""), p.get("unvan", ""), p.get("sicil_no", ""),
                                          p.get("start_date", ""), p.get("end_date", "")))
            fresh = {(r["tarih"], r["sayi"], r["sayfa"]): r["pdf_url"] for r in parse_rows(r_search.text, 6) if r["pdf_url"]}
            for item in self._cached_results.values():
                url = fresh.get((item.get("tarih"), item.get("sayi"), item.get("sayfa")))
                if url:
                    item["pdf_url"] = url
        except Exception as e:
            logger.warning(f"Search context refresh failed: {e}")

    # -------------------------------------------------------------------- PDF
    @staticmethod
    def _has_inpage_captcha(html_content: str) -> bool:
        if not html_content:
            return False
        return 'id="CaptchaIlan"' in html_content or 'name="CaptchaIlan"' in html_content

    async def _solve_inpage_captcha(
        self,
        client: httpx.AsyncClient,
        viewer_html: str,
        pdf_url: str,
        max_attempts: int = 3
    ) -> Optional[str]:
        """
        Solves TTSG's inline CAPTCHA challenge (FormGuvenlikKodu) presented on pdf_goster.php.
        TTSG enforces this challenge after viewing 4 gazettes in a session.
        Returns the refreshed viewer HTML containing the PDF embed, or original HTML.
        """
        current_html = viewer_html
        verify_url = f"{VIEW}/guvenlikkodudogrula.php"

        for attempt in range(1, max_attempts + 1):
            if not self._has_inpage_captcha(current_html):
                return current_html

            logger.info(f"Solving TTSG in-page PDF CAPTCHA challenge (attempt {attempt}/{max_attempts})...")
            cap_url = self._captcha_url(BeautifulSoup(current_html, "html.parser"))

            try:
                r_cap = await client.get(cap_url, headers={"Referer": pdf_url})
                code = await self._solve_captcha_image(r_cap.content)
                if not code:
                    logger.warning(f"In-page captcha solver returned empty code on attempt {attempt}")
                    await asyncio.sleep(0.5)
                    continue

                code_clean = code.strip().upper()
                r_v = await client.post(
                    verify_url,
                    data={"CaptchaIlan": code_clean},
                    headers={"X-Requested-With": "XMLHttpRequest", "Referer": pdf_url}
                )
                logger.info(f"In-page captcha verification response={r_v.text.strip()!r}")

                if r_v.text.strip() == "1":
                    r_refreshed = await client.get(pdf_url, headers={"Referer": SEARCH_REFERER})
                    current_html = r_refreshed.text
                    if not self._has_inpage_captcha(current_html):
                        return current_html
                    logger.warning("Viewer still contains active CaptchaIlan input after verification. Retrying...")
                else:
                    await asyncio.sleep(0.5)
            except httpx.HTTPError as e:
                logger.error(f"Error handling in-page captcha on attempt {attempt}: {e}")
                await asyncio.sleep(0.5)

        return current_html

    @staticmethod
    def _extract_pdf_src(html_content: str) -> Optional[str]:
        if not html_content:
            return None
        # 1. Regex search for tmp_gazete or direct .pdf path
        m = re.search(r'(/tmp_gazete/[a-zA-Z0-9_\-\.]+\.pdf)', html_content, re.IGNORECASE)
        if m:
            return m.group(1)
        # 2. Check HTML tags: object, embed, iframe, a
        soup = BeautifulSoup(html_content, "html.parser")
        for el in soup.find_all(["object", "embed", "iframe", "a"]):
            src = el.get("data") or el.get("src") or el.get("href")
            if src and ".pdf" in src.lower():
                return src
        # 3. Any general .pdf link in quotes
        m2 = re.search(r'["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', html_content, re.IGNORECASE)
        return m2.group(1) if m2 else None

    @staticmethod
    def _ann_result(announcement_id: str, item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": True,
            "announcement_id": announcement_id,
            "unvan": item.get("unvan", ""),
            "tarih": item.get("tarih", ""),
            "sayi": item.get("sayi", ""),
            "sayfa": item.get("sayfa", ""),
            "tur": item.get("tur", ""),
            "has_pdf": True
        }

    @_busy_to_error
    async def get_announcement_pdf(self, announcement_id: str, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Retrieves the full gazette PDF for a specific announcement and caches it.
        Checks persistent disk cache first.
        Automatically verifies valid %PDF bytes and recovers from expired sessions.
        """
        item = self._cached_results.get(announcement_id)
        if not item:
            return {"success": False, "error": "İlan bulunamadı veya arama oturumu yenilendi."}

        if not force_refresh and self.get_raw_pdf(announcement_id):
            return self._ann_result(announcement_id, item)

        pdf_url = item.get("pdf_url")
        if not pdf_url:
            return {"success": False, "error": "Bu ilana ait gazete PDF bağlantısı bulunamadı."}

        async with self._exclusive():
            # Check cache again inside lock (başka bir istek indirmiş olabilir)
            if not force_refresh and self.get_raw_pdf(announcement_id):
                return self._ann_result(announcement_id, item)

            client = self._get_client()
            try:
                pdf_bytes = None
                # Up to 3 attempts with automatic in-page captcha solving and network glitch resilience
                for attempt in range(1, 4):
                    if not self._is_logged_in:
                        logger.info(f"Not logged in. Performing login before PDF retrieval (attempt {attempt})...")
                        ok, msg = await self.login()
                        if not ok:
                            return {"success": False, "error": f"Giriş yapılamadı: {msg}"}

                    logger.info(f"Opening PDF viewer page (attempt {attempt}): {pdf_url}")
                    try:
                        r_viewer = await client.get(pdf_url, headers={"Referer": SEARCH_REFERER})
                        viewer_text = r_viewer.text
                    except httpx.HTTPError as e:
                        logger.warning(f"Network error opening PDF viewer page (attempt {attempt}): {e}")
                        if attempt < 3:
                            await asyncio.sleep(1.0)
                            continue
                        break

                    # Detect and solve inline FormGuvenlikKodu CAPTCHA challenge
                    if self._has_inpage_captcha(viewer_text):
                        logger.info(f"TTSG presented FormGuvenlikKodu inline captcha for {announcement_id}.")
                        resolved_html = await self._solve_inpage_captcha(client, viewer_text, pdf_url)
                        if resolved_html:
                            viewer_text = resolved_html

                    pdf_direct_src = self._extract_pdf_src(viewer_text)

                    if not pdf_direct_src:
                        is_login_demanded = any(k in viewer_text for k in ["girisyap.php", "GİRİŞ YAPMALISINIZ", "giriş yapmalısınız"])
                        if is_login_demanded and attempt < 3:
                            logger.warning(f"TTSG requested login for {announcement_id}. Re-authenticating and refreshing search context...")
                            self._is_logged_in = False
                            ok, msg = await self.login()
                            if not ok:
                                return {"success": False, "error": f"Oturum yenilenemedi: {msg}"}
                            await self._refresh_search_context(client)
                            refreshed = self._cached_results.get(announcement_id)
                            if refreshed and refreshed.get("pdf_url"):
                                pdf_url = refreshed["pdf_url"]
                            continue
                        if attempt < 3:
                            logger.info(f"PDF embed not ready on attempt {attempt} for {announcement_id}. Pausing 1s before retry...")
                            await asyncio.sleep(1.0)
                            continue
                        logger.error(f"No PDF embed found in viewer HTML even after retries for {announcement_id}. Snippet: {viewer_text[:200]!r}")
                        break

                    actual_pdf_url = tsg_url(pdf_direct_src)
                    if not actual_pdf_url:
                        logger.error("PDF bağlantısı TSG dışına işaret ediyor, reddedildi: %r", pdf_direct_src[:200])
                        break
                    logger.info(f"Downloading actual PDF from: {actual_pdf_url}")
                    try:
                        downloaded = await self._download_limited(client, actual_pdf_url, pdf_url)
                    except httpx.HTTPError as e:
                        logger.warning(f"Network error downloading PDF bytes (attempt {attempt}): {e}")
                        if attempt < 3:
                            await asyncio.sleep(1.0)
                            continue
                        break

                    if is_pdf(downloaded):
                        pdf_bytes = downloaded
                        break
                    logger.warning(f"Downloaded content did not start with %PDF (length: {len(downloaded)}). Retrying login...")
                    self._is_logged_in = False
                    if attempt < 3:
                        await self.login()

                if not is_pdf(pdf_bytes):
                    self._pdfs.drop(gazette_key(item))
                    return {
                        "success": False,
                        "error": "Gazete PDF belgesi alınamadı veya oturum süresi doldu. Lütfen tekrar deneyin."
                    }

                self._pdfs.put(gazette_key(item), pdf_bytes)
                return self._ann_result(announcement_id, item)

            except Exception as e:
                logger.error(f"Error fetching announcement PDF: {e}", exc_info=True)
                return {"success": False, "error": "Gazete PDF belgesi alınırken beklenmeyen bir hata oluştu."}

    @staticmethod
    async def _download_limited(client: httpx.AsyncClient, url: str, referer: str) -> bytes:
        """Gövdeyi parça parça okur; MAX_PDF_MB aşılırsa bağlantıyı keser (bellek tüketimi saldırısı)."""
        limit = settings.MAX_PDF_MB * 1024 * 1024
        buf = bytearray()
        async with client.stream("GET", url, headers={"Referer": referer}) as r:
            async for chunk in r.aiter_bytes():
                buf += chunk
                if len(buf) > limit:
                    raise ValueError(f"PDF {settings.MAX_PDF_MB} MB sınırını aşıyor")
        return bytes(buf)

    def get_raw_pdf(self, announcement_id: str) -> Optional[bytes]:
        item = self._cached_results.get(announcement_id)
        return self._pdfs.get(gazette_key(item)) if item else None

    def get_item(self, announcement_id: str) -> Optional[Dict[str, Any]]:
        return self._cached_results.get(announcement_id)

    # ---------------------------------------------------------------- summary
    async def _extract_text_locally(self, pdf_bytes: bytes) -> str:
        def work() -> str:
            import pymupdf
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            text = "\n".join(p.get_text() for p in doc)
            if not text.strip() and len(doc) > 0:
                text = extract_ocr_text(doc[0].get_pixmap(dpi=150).tobytes("png"))
            return text
        return await asyncio.to_thread(work)

    async def get_company_summary(self, company_id: str) -> Dict[str, Any]:
        """
        Generates an intelligent decision-based corporate intelligence summary for a company.
        Selects key announcements (Kuruluş, latest status/address, latest Sermaye, latest Yönetim/Ortak)
        and extracts structured insights concurrently via AI vision or text analysis.
        """
        company = self._cached_companies.get(company_id)
        if not company:
            return {"success": False, "error": "Şirket kaydı bulunamadı."}

        announcements = company.get("announcements", [])
        if not announcements:
            return {"success": True, "company_id": company_id,
                    "summary": company_analyzer.generate_summary(company, [])}

        target_map = select_key_announcements(announcements)
        logger.info(f"Summary target announcements for {company.get('unvan')}: {list(target_map.keys())}")

        async def process_key_announcement(ann: Dict[str, Any]):
            ann_id = ann.get("id")
            if not ann_id or ai_service.get_cached(ann):
                return

            pdf_bytes = self.get_raw_pdf(ann_id)
            if not pdf_bytes:
                await self.get_announcement_pdf(ann_id)
                pdf_bytes = self.get_raw_pdf(ann_id)
            if not pdf_bytes:
                logger.warning(f"Could not load PDF bytes for target announcement {ann_id}")
                return

            try:
                if ai_service.has_api_key():
                    await ai_service.analyze_announcement(ann, pdf_bytes=pdf_bytes)
                else:
                    extracted = await self._extract_text_locally(pdf_bytes)
                    if extracted:
                        self._cached_texts[ann_id] = extracted
            except Exception as ex:
                logger.warning(f"Analysis failed for {ann_id}: {ex}")

        await asyncio.gather(*(process_key_announcement(a) for a in target_map.values()))

        summary = company_analyzer.generate_summary(
            company_info=company,
            announcements=announcements,
            announcements_text_map=self._cached_texts._d
        )
        return {"success": True, "company_id": company_id, "summary": summary}


session_manager = TSGSessionManager()
