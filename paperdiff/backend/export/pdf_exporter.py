"""Headless Chromium/Chrome PDF exporter fallback for browser-mode & automated tests.

In macOS Desktop App mode (pywebview), the frontend invokes native WKWebView NSPrintOperation
via DesktopBridge.export_pdf_from_html (+0 MB extra dependencies).
When accessed from a normal browser or pytest, this module invokes local Chrome/Chromium
`--headless=new --print-to-pdf` cleanly on offline self-contained printable HTML.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_MACOS_CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
]


def _windows_chrome_candidates(env: dict[str, str] | None = None) -> list[str]:
    environ = env if env is not None else dict(os.environ)
    roots = [
        environ.get("PROGRAMFILES", r"C:\Program Files"),
        environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        environ.get("LOCALAPPDATA", ""),
    ]
    rels = (
        r"Google\Chrome\Application\chrome.exe",
        r"Microsoft\Edge\Application\msedge.exe",
        r"BraveSoftware\Brave-Browser\Application\brave.exe",
    )
    out: list[str] = []
    for base in roots:
        if not base:
            continue
        clean_base = base.rstrip("\\/")
        for rel in rels:
            out.append(f"{clean_base}\\{rel}")
    return out


def find_local_chrome() -> str | None:
    env_chrome = os.environ.get("PAPERDIFF_CHROME_PATH", "").strip().strip('"').strip("'")
    if env_chrome and Path(env_chrome).exists():
        return env_chrome
    candidates = _windows_chrome_candidates() if sys.platform.startswith("win") else _MACOS_CHROME_CANDIDATES
    for p in candidates:
        if Path(p).exists():
            return p
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return None


def render_html_to_pdf_bytes(html_content: str, *, timeout_sec: float = 25.0) -> bytes:
    """Render offline self-contained HTML into real PDF bytes using local headless Chrome/Edge."""
    chrome = find_local_chrome()
    if not chrome:
        if sys.platform.startswith("win"):
            raise RuntimeError(
                "未检测到本地 Microsoft Edge 或 Google Chrome 浏览器；请安装 Edge / Chrome，或在浏览器中打开打印视图另存为 PDF。"
            )
        raise RuntimeError(
            "未检测到本地 Chrome/Chromium；桌面版请直接使用原生 PDF 导出，或在浏览器中打开打印视图另存为 PDF。"
        )

    with tempfile.TemporaryDirectory(prefix="paperdiff_pdf_") as td:
        tmp_dir = Path(td)
        html_path = tmp_dir / "print_doc.html"
        pdf_path = tmp_dir / "output.pdf"
        html_path.write_text(html_content, encoding="utf-8")

        cmd = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--allow-file-access-from-files",
            "--no-pdf-header-footer",
            "--virtual-time-budget=3500",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ]
        run_kwargs: dict[str, object] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "timeout": timeout_sec,
            "check": False,
        }
        if sys.platform.startswith("win"):
            run_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        proc = subprocess.run(cmd, **run_kwargs)  # type: ignore[arg-type]
        if not pdf_path.exists() or pdf_path.stat().st_size < 100:
            err_msg = proc.stderr.decode("utf-8", errors="ignore")[:300]
            raise RuntimeError(f"PDF 渲染失败: {err_msg or '未生成输出文件'}")
        pdf_bytes = pdf_path.read_bytes()
        if not pdf_bytes.startswith(b"%PDF"):
            raise RuntimeError("生成的 PDF 文件头异常")
        return pdf_bytes
