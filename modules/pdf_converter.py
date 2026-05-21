from __future__ import annotations

from pathlib import Path
import os
import shutil


class PdfConversionError(Exception):
    """Raised when HTML to PDF conversion cannot be completed."""


def verify_pdf_file(pdf_path: Path) -> dict[str, int]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise PdfConversionError("PDF verification requires pypdf.") from exc

    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        raise PdfConversionError(f"PDF conversion produced an empty file: {pdf_path}")
    try:
        reader = PdfReader(str(pdf_path))
        page_count = len(reader.pages)
    except Exception as exc:  # noqa: BLE001
        raise PdfConversionError(f"PDF verification failed for {pdf_path.name}: {exc}") from exc
    if page_count < 1:
        raise PdfConversionError(f"PDF has no pages: {pdf_path}")
    return {"pdf_page_count": page_count, "pdf_file_size": pdf_path.stat().st_size}


def convert_html_file_to_pdf(html_path: Path, pdf_path: Path) -> Path:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise PdfConversionError(
            "PDF conversion requires Playwright. Run: python -m pip install playwright && python -m playwright install chromium"
        ) from exc

    html_path = html_path.resolve()
    pdf_path = pdf_path.resolve()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as playwright:
            executable_path = _find_chromium_executable()
            launch_kwargs = {"headless": True}
            if executable_path:
                launch_kwargs["executable_path"] = executable_path
            browser = playwright.chromium.launch(**launch_kwargs)
            page = browser.new_page(viewport={"width": 1440, "height": 2200})
            page.goto(html_path.as_uri(), wait_until="networkidle")
            page.emulate_media(media="screen")
            page.pdf(
                path=str(pdf_path),
                format="Letter",
                print_background=True,
                prefer_css_page_size=True,
                margin={"top": "0.35in", "right": "0.35in", "bottom": "0.35in", "left": "0.35in"},
            )
            browser.close()
    except Exception as exc:  # noqa: BLE001
        raise PdfConversionError(f"PDF conversion failed for {html_path.name}: {exc}") from exc

    verify_pdf_file(pdf_path)
    return pdf_path


def _find_chromium_executable() -> str | None:
    configured = os.getenv("CHROME_EXECUTABLE_PATH")
    if configured and Path(configured).exists():
        return configured
    for command in ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable"]:
        found = shutil.which(command)
        if found:
            return found
    for candidate in [
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
    ]:
        if Path(candidate).exists():
            return candidate
    return None
