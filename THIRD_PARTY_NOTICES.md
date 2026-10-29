# Üçüncü taraf bileşenler / Third-party notices

Bu depo aşağıdaki dosyaları `app/static/vendor/` altında yerel kopya olarak içerir (internet olmadan çalışsın diye).
Bütünlük için sağlama toplamları `app/static/vendor/CHECKSUMS.sha256` dosyasındadır.

| Bileşen | Sürüm | Lisans | Kaynak |
|---|---|---|---|
| Tailwind CSS (Play) | 3.4.17 | MIT | <https://tailwindcss.com> |
| Font Awesome Free (CSS ve yazı tipleri) | 6.5.1 | Simgeler CC BY 4.0, yazı tipleri SIL OFL 1.1, kod MIT | <https://fontawesome.com/license/free> |
| Bricolage Grotesque | fontsource | SIL OFL 1.1 | <https://github.com/ateliertriay/bricolage> |
| IBM Plex Sans | fontsource | SIL OFL 1.1 | <https://github.com/IBM/plex> |

Python bağımlılıkları (FastAPI, httpx, PyMuPDF, ddddocr, RapidOCR, google-genai vb.) `requirements.txt` ile kurulur ve kendi
lisansları altındadır. PyMuPDF **AGPL-3.0** / ticari çift lisanslıdır; bu proje onu yerel olarak kullanır ve ayrıca dağıtmaz,
ancak ürünü başkalarına paketleyip dağıtmayı düşünüyorsanız PyMuPDF lisansını ayrıca değerlendirin.
