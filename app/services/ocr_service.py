import os
import shutil
from pathlib import Path

import pymupdf

DEFAULT_TESSDATA_PATH = r"C:\Program Files\Tesseract-OCR\tessdata"
OCR_DPI = 200


class OcrServiceError(RuntimeError):
    """Raised when Tesseract OCR is unavailable or fails."""


def is_usable_text(text: str) -> bool:
    stripped_text = text.strip()
    if not stripped_text:
        return False

    alphanumeric_count = sum(character.isalnum() for character in stripped_text)
    return alphanumeric_count >= 4 and alphanumeric_count / len(stripped_text) >= 0.25


def get_tessdata_path() -> Path:
    configured_path = os.environ.get("TESSDATA_PREFIX", "").strip()
    tessdata_path = Path(configured_path or DEFAULT_TESSDATA_PATH)
    if not tessdata_path.is_dir():
        raise OcrServiceError(
            f"Tesseract tessdata directory was not found at '{tessdata_path}'. "
            "Set TESSDATA_PREFIX to the tessdata directory."
        )
    if not (tessdata_path / "eng.traineddata").is_file():
        raise OcrServiceError(
            f"English Tesseract data was not found in '{tessdata_path}'. "
            "Install eng.traineddata or set TESSDATA_PREFIX to the correct directory."
        )

    executable_available = shutil.which("tesseract") is not None
    if os.name == "nt" and not executable_available:
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        executable_paths = {
            tessdata_path.parent / "tesseract.exe",
            program_files / "Tesseract-OCR" / "tesseract.exe",
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        }
        executable_available = any(path.is_file() for path in executable_paths)
    if not executable_available:
        raise OcrServiceError(
            "Tesseract OCR executable was not found. Install Tesseract and ensure it "
            "is discoverable by PyMuPDF (on Windows, the standard Program Files "
            "installation is also checked)."
        )

    return tessdata_path


def extract_ocr_text(page: pymupdf.Page) -> str:
    tessdata_path = get_tessdata_path()
    try:
        text_page = page.get_textpage_ocr(
            language="eng",
            dpi=OCR_DPI,
            full=True,
            tessdata=str(tessdata_path),
        )
        return page.get_text("text", textpage=text_page)
    except Exception as exc:
        raise OcrServiceError(
            "PyMuPDF OCR failed. Check the Tesseract installation and English "
            "traineddata configuration."
        ) from exc