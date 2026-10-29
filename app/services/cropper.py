import re
import logging
from typing import Dict, Any
import pymupdf  # PyMuPDF

logger = logging.getLogger(__name__)

def normalize_tr(text: str) -> str:
    """Normalize Turkish characters for robust matching."""
    if not text:
        return ""
    mapping = {
        'İ': 'i', 'I': 'ı', 'ı': 'i', 'Ş': 's', 'ş': 's',
        'Ğ': 'g', 'ğ': 'g', 'Ü': 'u', 'ü': 'u', 'Ö': 'o',
        'ö': 'o', 'Ç': 'c', 'ç': 'c'
    }
    res = text.lower()
    for k, v in mapping.items():
        res = res.replace(k.lower(), v)
    # Remove extra spaces and special punctuation for comparison
    return re.sub(r'[^a-z0-9]', '', res)

class GazetteCropper:
    def __init__(self, zoom: float = 2.0):
        # 2.0 zoom produces crisp 144 DPI image from 72 DPI PDF
        self.matrix = pymupdf.Matrix(zoom, zoom)

    def extract_crop(
        self,
        pdf_bytes: bytes,
        target_title: str = "",
        page_num: int = 0,
        sicil_no: str = ""
    ) -> Dict[str, Any]:
        """
        Locates the company's announcement in the PDF page and crops it.
        Returns:
            {
                "crop_image_bytes": bytes (PNG),
                "full_page_image_bytes": bytes (PNG),
                "page_count": int,
                "target_found": bool,
                "bbox": [x0, y0, x1, y1]
            }
        """
        try:
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            page_count = len(doc)
            if page_count == 0:
                raise ValueError("PDF is empty")

            target_page_idx = max(0, min(page_num, page_count - 1))
            page = doc[target_page_idx]
            page_rect = page.rect

            # 1. Search text matches
            found_rects = []
            
            # Search by title words if title provided
            title_clean = target_title.strip()
            if title_clean:
                # Try exact search first
                rects = page.search_for(title_clean)
                if rects:
                    found_rects.extend(rects)
                else:
                    # Try first significant words (e.g. 2-3 words)
                    words = [w for w in title_clean.split() if len(w) > 2 and w.upper() not in ("VE", "İLE", "TİC.", "LTD.", "ŞTİ.", "A.Ş.", "SAN.")]
                    if words:
                        for word in words[:2]:
                            w_rects = page.search_for(word)
                            if w_rects:
                                found_rects.extend(w_rects)

            # Search by sicil_no if available and no rects yet
            if not found_rects and sicil_no:
                s_rects = page.search_for(sicil_no.strip())
                if s_rects:
                    found_rects.extend(s_rects)

            target_found = len(found_rects) > 0
            
            # Determine crop box
            if target_found:
                # Union of matched rects
                u_rect = found_rects[0]
                for r in found_rects[1:]:
                    u_rect = u_rect | r

                # Determine column boundaries based on newspaper 3 or 4 columns layout
                col_width = page_rect.width / 4.0
                col_idx = int(u_rect.x0 / col_width)
                col_x0 = max(0, col_idx * col_width - 8)
                col_x1 = min(page_rect.width, (col_idx + 1) * col_width + 8)

                # Expand vertically for the announcement height
                y0 = max(page_rect.y0 + 20, u_rect.y0 - 25)
                # Gazette notices typically span 150 - 450 points vertically
                y1 = min(page_rect.y1 - 20, max(u_rect.y1 + 250, y0 + 350))

                crop_rect = pymupdf.Rect(col_x0, y0, col_x1, y1)
            else:
                # Fallback: Center-focused crop or upper half
                crop_rect = pymupdf.Rect(
                    page_rect.x0 + 15,
                    page_rect.y0 + 35,
                    page_rect.x1 - 15,
                    min(page_rect.y1 - 35, page_rect.y0 + 400)
                )

            # Render cropped region
            pix_crop = page.get_pixmap(matrix=self.matrix, clip=crop_rect)
            crop_bytes = pix_crop.tobytes("png")

            # Render full page image for preview
            pix_full = page.get_pixmap(matrix=pymupdf.Matrix(1.2, 1.2))
            full_page_bytes = pix_full.tobytes("png")

            doc.close()

            return {
                "success": True,
                "crop_image_bytes": crop_bytes,
                "full_page_image_bytes": full_page_bytes,
                "page_count": page_count,
                "target_found": target_found,
                "bbox": [crop_rect.x0, crop_rect.y0, crop_rect.x1, crop_rect.y1]
            }

        except Exception as e:
            logger.error(f"Error in extract_crop: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "crop_image_bytes": b"",
                "full_page_image_bytes": b"",
                "page_count": 1,
                "target_found": False,
                "bbox": []
            }

cropper = GazetteCropper()
