from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


_BROWSER_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
]

_PDF_RENDER_TIMEOUT_SECONDS = 20.0
_PDF_VIRTUAL_TIME_BUDGET_MS = 3000


def _resolve_browser(browser_value: str) -> Path | None:
    candidate = Path(browser_value).expanduser()
    if candidate.exists():
        return candidate.resolve()

    resolved = shutil.which(browser_value)
    if resolved:
        return Path(resolved).resolve()
    return None


def find_pdf_browser() -> Path:
    configured = os.getenv("MAILATLAS_PDF_BROWSER")
    if configured:
        resolved = _resolve_browser(configured)
        if resolved:
            return resolved
        raise RuntimeError(
            "MAILATLAS_PDF_BROWSER is set, but the configured browser executable was not found: "
            f"{configured}"
        )

    for candidate in _BROWSER_CANDIDATES:
        resolved = _resolve_browser(candidate)
        if resolved:
            return resolved

    raise RuntimeError(
        "No Chrome/Chromium executable was found for PDF export. Install Chrome or Chromium, "
        "or set MAILATLAS_PDF_BROWSER to a browser executable."
    )


def render_pdf_from_html(html_path: str | Path, pdf_path: str | Path) -> Path:
    source = Path(html_path).expanduser().resolve()
    destination = Path(pdf_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    browser = find_pdf_browser()

    command = [
        browser.as_posix(),
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--allow-file-access-from-files",
        "--disable-background-networking",
        "--disable-breakpad",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-features=OptimizationHints,Translate,MediaRouter",
        "--disable-sync",
        "--metrics-recording-only",
        "--no-first-run",
        # Give inline assets time to load before Chrome snapshots the page into PDF.
        f"--virtual-time-budget={_PDF_VIRTUAL_TIME_BUDGET_MS}",
        f"--print-to-pdf={destination.as_posix()}",
        "--print-to-pdf-no-header",
        source.as_uri(),
    ]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_PDF_RENDER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"PDF export timed out using {browser.name} after {_PDF_RENDER_TIMEOUT_SECONDS:.0f}s."
        ) from exc

    if not destination.exists() or destination.stat().st_size <= 0:
        error_detail = (result.stderr or result.stdout).strip()
        if error_detail:
            error_detail = f" Renderer output: {error_detail}"
        raise RuntimeError(f"PDF export failed using {browser.name}.{error_detail}")

    return destination
