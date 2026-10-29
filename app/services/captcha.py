import logging
from typing import Optional

logger = logging.getLogger(__name__)

class CaptchaSolver:
    def __init__(self):
        self._ocr = None

    def _get_ocr(self):
        if self._ocr is None:
            try:
                import ddddocr
                # Disable welcome banner
                self._ocr = ddddocr.DdddOcr(show_ad=False)
                logger.info("ddddocr engine loaded successfully.")
            except Exception as e:
                logger.warning(f"Could not initialize ddddocr: {e}")
                self._ocr = None
        return self._ocr

    def solve(self, image_bytes: bytes) -> Optional[str]:
        """
        Solves CAPTCHA image bytes using ddddocr.
        Returns the recognized alphanumeric code.
        """
        ocr = self._get_ocr()
        if not ocr:
            logger.error("No OCR engine available.")
            return None
        try:
            res = ocr.classification(image_bytes)
            # Clean up whitespace
            cleaned = "".join(res.split())
            logger.info(f"CAPTCHA recognized: {cleaned}")
            return cleaned
        except Exception as e:
            logger.error(f"Error solving CAPTCHA: {e}")
            return None

captcha_solver = CaptchaSolver()
