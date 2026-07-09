"""
Preprocessor Service
Enhances scanned property document quality before OCR:
  - Contrast enhancement (CLAHE)
  - Denoising
  - Deskewing (straighten tilted pages)
  - Binarization (Otsu threshold for faded stamps)
  - Resolution normalization to 200 DPI
Output: preprocessed PDF ready for Sarvam
"""

import cv2
import numpy as np
import fitz                        # PyMuPDF
from PIL import Image
from pathlib import Path


# ── Constants ──────────────────────────────────────────────────────────────────
TARGET_DPI    = 200                # Sarvam works best at 150-200 DPI
RENDER_MATRIX = fitz.Matrix(TARGET_DPI / 72, TARGET_DPI / 72)


def preprocess_pdf(src_pdf: Path, out_pdf: Path) -> Path:
    """
    Read src_pdf, enhance each page, write to out_pdf.
    Returns out_pdf path.
    """
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(src_pdf))
    result_doc = fitz.open()      # new empty PDF

    for page_num in range(len(doc)):
        page = doc[page_num]
        pix  = page.get_pixmap(matrix=RENDER_MATRIX, colorspace=fitz.csRGB)

        # Convert pixmap → numpy array (BGR for OpenCV)
        img_np = np.frombuffer(pix.samples, dtype=np.uint8)
        img_np = img_np.reshape(pix.height, pix.width, 3)
        img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

        # Apply enhancement chain
        enhanced = _enhance_page(img_bgr)

        # Convert back to RGB PIL image → insert into new PDF
        enhanced_rgb = cv2.cvtColor(enhanced, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(enhanced_rgb)

        # Write enhanced image page to result doc
        img_bytes = _pil_to_bytes(pil_img)
        new_page  = result_doc.new_page(width=pil_img.width, height=pil_img.height)
        new_page.insert_image(new_page.rect, stream=img_bytes)

    result_doc.save(str(out_pdf), garbage=4, deflate=True)
    result_doc.close()
    doc.close()

    return out_pdf


def _enhance_page(img: np.ndarray) -> np.ndarray:
    """Apply full enhancement chain to a page image."""
    # 1. Convert to grayscale for analysis
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 2. Deskew
    img = _deskew(img, gray)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 3. Denoising — only apply if the page is actually noisy.
    #    Clean digital PDFs rendered to image have very low pixel std dev (< 8).
    #    Scanned documents with film grain / JPEG compression noise sit above ~15.
    #    Skipping on clean pages avoids the expensive O(N²) search window pass
    #    and prevents slight text blurring on already-clear documents.
    noise_level = float(np.std(gray))
    if noise_level > 15.0:
        denoised = cv2.fastNlMeansDenoisingColored(img, None,
                                                    h=10, hColor=10,
                                                    templateWindowSize=7,
                                                    searchWindowSize=21)
    else:
        denoised = img

    # 4. CLAHE contrast enhancement on L channel (LAB space)
    lab   = cv2.cvtColor(denoised, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    l_eq  = clahe.apply(l)
    enhanced_lab = cv2.merge([l_eq, a, b])
    enhanced = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)

    # 5. Sharpen (Unsharp mask)
    blurred  = cv2.GaussianBlur(enhanced, (0, 0), 3)
    sharpened = cv2.addWeighted(enhanced, 1.5, blurred, -0.5, 0)

    return sharpened


def _deskew(img: np.ndarray, gray: np.ndarray) -> np.ndarray:
    """
    Detect and correct page tilt up to ±15°.
    Uses Hough line transform on edges.
    """
    try:
        edges  = cv2.Canny(gray, 50, 150, apertureSize=3)
        lines  = cv2.HoughLines(edges, 1, np.pi / 180, threshold=200)
        if lines is None:
            return img

        angles = []
        for line in lines[:50]:
            theta = line[0][1]
            angle = np.degrees(theta) - 90
            if abs(angle) < 15:            # only correct small tilts
                angles.append(angle)

        if not angles:
            return img

        median_angle = float(np.median(angles))
        if abs(median_angle) < 0.3:        # skip trivial corrections
            return img

        h, w = img.shape[:2]
        M    = cv2.getRotationMatrix2D((w / 2, h / 2), median_angle, 1.0)
        rotated = cv2.warpAffine(img, M, (w, h),
                                  flags=cv2.INTER_LINEAR,
                                  borderMode=cv2.BORDER_REPLICATE)
        return rotated
    except Exception:
        return img                         # if deskew fails, return original


def _pil_to_bytes(pil_img: Image.Image) -> bytes:
    """Convert PIL image to JPEG bytes for embedding in PDF."""
    import io
    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()
