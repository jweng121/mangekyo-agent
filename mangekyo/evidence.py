"""Captured document and browser evidence for an agent run."""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

from .store import Store

MIMES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
         ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}


def browser_environment() -> dict[str, str]:
    """Keep browser binaries outside PyInstaller's disposable extraction folder."""
    env = os.environ.copy()
    custom = env.get("MANGEKYO_BROWSERS_PATH")
    if custom:
        directory = Path(custom).expanduser()
    elif sys.platform == "win32":
        directory = Path(env.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "ms-playwright"
    elif sys.platform == "darwin":
        directory = Path.home() / "Library" / "Caches" / "ms-playwright"
    else:
        directory = Path(env.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "ms-playwright"
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(directory.resolve())
    return env


def add_file(store: Store, run_id: str, path: Path, *, event_id: str | None = None,
             parsed_text: str | None = None) -> str:
    path = path.expanduser().resolve()
    mime = MIMES.get(path.suffix.lower())
    if not mime:
        raise ValueError("Supported evidence: PDF, PNG, JPEG, WebP, GIF")
    if path.stat().st_size > 50_000_000:
        raise ValueError("Evidence file exceeds 50 MB")
    return store.artifact(run_id, path.name, path.read_bytes(), mime,
                          event_id=event_id, parsed_text=parsed_text, source=str(path))


def capture_url(store: Store, run_id: str, url: str, *, event_id: str | None = None) -> str:
    if not url.startswith(("https://", "http://")):
        raise ValueError("Browser capture needs an http or https URL")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Install the evidence extra: pip install 'mangekyo-agent[evidence]'") from exc
    os.environ.update(browser_environment())
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 800})
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                text = page.locator("body").inner_text(timeout=10000)
                screenshot = page.screenshot(full_page=True, animations="disabled")
                return store.artifact(run_id, "Browser capture.png", screenshot, "image/png",
                                      event_id=event_id, parsed_text=text, source=page.url)
            finally:
                browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            raise RuntimeError("Chromium is missing; run: mangekyo setup --browser") from exc
        raise


def install_chromium() -> None:
    try:
        from playwright._impl._driver import compute_driver_executable, get_driver_env
    except ImportError as exc:
        raise RuntimeError("Browser support is missing; install the mangekyo-agent[evidence] extra") from exc
    node, cli = compute_driver_executable()
    env = get_driver_env() | browser_environment()
    result = subprocess.run([node, cli, "install", "chromium"], env=env, timeout=600)
    if result.returncode:
        raise RuntimeError("Chromium installation failed; check the network connection and retry")


def render_pdf_page(data: bytes, page: int) -> tuple[bytes, int]:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise RuntimeError("PDF previews need the evidence extra: pip install 'mangekyo-agent[evidence]'") from exc
    document = pdfium.PdfDocument(io.BytesIO(data))
    count = len(document)
    if page < 0 or page >= count:
        raise ValueError(f"PDF page must be 1-{count}")
    image = document[page].render(scale=1.5).to_pil()
    output = io.BytesIO()
    image.save(output, format="PNG")
    document.close()
    return output.getvalue(), count


def pdf_page_count(data: bytes) -> int | None:
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return None
    document = pdfium.PdfDocument(io.BytesIO(data))
    count = len(document)
    document.close()
    return count
