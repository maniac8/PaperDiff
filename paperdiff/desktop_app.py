#!/usr/bin/env python3
"""Native macOS Desktop Application Entrypoint for 对稿 · PaperDiff Studio (v0.1.0).

Startup architecture (Splash-First + Single-Instance Reuse):
    - Top-level module imports stay ultra-light (stdlib + `backend.runtime_state` only),
      deferring `uvicorn` & `backend.main` into the background bootstrap thread so the
      native `WKWebView` Splash window renders immediately without a 2-4s blank freeze.
    - Probes `DATA_DIR/server.lock` + `/api/health` first: if a healthy same-`DATA_DIR`
      PaperDiff server is already running (e.g. Web daemon), reuses its port with
      `owns_server = False` and never kills the external service when the window closes.
    - If backend boot fails or exceeds 15s, switches the Splash view to an actionable
      Chinese diagnostic card with `server.log` path, Retry, and Open Logs Folder actions.

Exposed `DesktopBridge` JS-to-Cocoa capabilities (`window.pywebview.api`):
    - `save_file_base64` / `export_pdf_from_html`: Native macOS `NSSavePanel` & `NSPrintOperation`.
    - `select_local_folder`: Native macOS `NSOpenPanel` for W2 local-folder binding.
    - `open_in_browser`: Open current local port + safe relative project URL in system browser.
    - `get_data_dir` / `open_data_dir` / `open_logs_dir` / `retry_boot` / `get_runtime_info`.
    - `PAPERDIFF_SMOKE_TEST=1`: Headless self-check mode executed during `.dmg` CI verification.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable
import urllib.request
import webbrowser

# Ensure bundled modules are importable in both dev and PyInstaller frozen modes
if not getattr(sys, "frozen", False):
    ROOT = Path(__file__).resolve().parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

from backend import runtime_state  # noqa: E402

DATA_DIR = runtime_state.resolve_data_dir()


def find_free_port(preferred_start: int = 18765, preferred_end: int = 18820) -> int:
    return runtime_state.find_free_port(preferred_start, preferred_end)


def wait_for_server(url: str, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        try:
            with opener.open(f"{url}/api/health", timeout=0.8) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.05)
    return False


def build_splash_html(log_path: str) -> str:
    """Return a 100% offline, theme-aware inline HTML Splash screen with error diagnostics."""
    safe_log = (
        str(log_path)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>对稿 · PaperDiff</title>
<style>
  :root {{
    --bg: #F6F7F9;
    --card: #FFFFFF;
    --fg: #0F172A;
    --muted: #64748B;
    --border: #E2E8F0;
    --accent: #1E293B;
    --track: #E2E8F0;
    --err-bg: #FEF2F2;
    --err-fg: #991B1B;
    --err-bd: #FECACA;
  }}
  html[data-theme="sepia"] {{
    --bg: #F6F1E7;
    --card: #FBF8F1;
    --fg: #2C241B;
    --muted: #6B5E4F;
    --border: #E5DCCB;
    --accent: #3F3426;
    --track: #E5DCCB;
  }}
  html[data-theme="dark"] {{
    --bg: #0D1117;
    --card: #161B22;
    --fg: #E6EDF3;
    --muted: #8B949E;
    --border: #30363D;
    --accent: #E6EDF3;
    --track: #21262D;
    --err-bg: #2A1215;
    --err-fg: #FCA5A5;
    --err-bd: #7F1D1D;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", sans-serif;
    background: var(--bg);
    color: var(--fg);
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    -webkit-font-smoothing: antialiased;
  }}
  .card {{
    width: min(460px, 90vw);
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 32px 28px;
    text-align: center;
    box-shadow: 0 12px 32px rgba(15, 23, 42, 0.08);
  }}
  .mark {{
    width: 48px;
    height: 48px;
    margin: 0 auto 14px;
    color: var(--accent);
  }}
  h1 {{ font-size: 18px; font-weight: 600; letter-spacing: 0.02em; }}
  .sub {{ font-size: 13px; color: var(--muted); margin-top: 6px; }}
  .bar {{
    height: 4px;
    border-radius: 999px;
    background: var(--track);
    margin: 22px auto 12px;
    overflow: hidden;
    position: relative;
  }}
  .bar-inner {{
    position: absolute;
    inset: 0 auto 0 0;
    width: 42%;
    border-radius: 999px;
    background: var(--accent);
    animation: slide 1.15s ease-in-out infinite;
  }}
  @keyframes slide {{
    0% {{ transform: translateX(-110%); }}
    100% {{ transform: translateX(260%); }}
  }}
  .status {{ font-size: 12.5px; color: var(--muted); }}
  .err-box {{
    display: none;
    margin-top: 18px;
    text-align: left;
    background: var(--err-bg);
    color: var(--err-fg);
    border: 1px solid var(--err-bd);
    border-radius: 10px;
    padding: 12px 14px;
    font-size: 12.5px;
    line-height: 1.55;
  }}
  .log-path {{
    margin-top: 8px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 11px;
    word-break: break-all;
    opacity: 0.9;
  }}
  .actions {{
    display: none;
    margin-top: 16px;
    gap: 10px;
    justify-content: center;
  }}
  button {{
    border: 1px solid var(--border);
    background: var(--card);
    color: var(--fg);
    border-radius: 8px;
    padding: 8px 14px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
  }}
  button.primary {{
    background: var(--accent);
    color: var(--card);
    border-color: var(--accent);
  }}
</style>
<script>
  (function () {{
    try {{
      var pref = localStorage.getItem('paperdiff_theme') || 'auto';
      var resolved = pref === 'auto'
        ? (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
        : (pref === 'sepia' || pref === 'dark' ? pref : 'light');
      document.documentElement.dataset.theme = resolved;
    }} catch (e) {{}}
  }})();
</script>
</head>
<body>
  <div class="card">
    <svg class="mark" viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <rect x="4" y="6" width="18" height="36" rx="4" stroke="currentColor" stroke-width="2.6" />
      <rect x="26" y="6" width="18" height="36" rx="4" fill="currentColor" fill-opacity="0.12" stroke="currentColor" stroke-width="2.6" />
      <line x1="9" y1="16" x2="17" y2="16" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" />
      <line x1="9" y1="23" x2="17" y2="23" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" />
      <line x1="31" y1="16" x2="39" y2="16" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" />
      <line x1="31" y1="23" x2="39" y2="23" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" />
    </svg>
    <h1>对稿 · PaperDiff</h1>
    <div class="sub">论文阅读与版本比对</div>
    <div id="pd-bar" class="bar"><div class="bar-inner"></div></div>
    <div id="pd-status" class="status">正在启动…</div>
    <div id="pd-err" class="err-box">
      <div id="pd-err-msg"></div>
      <div class="log-path">日志位置：<span id="pd-log-path">{safe_log}</span></div>
    </div>
    <div id="pd-actions" class="actions">
      <button class="primary" onclick="window.__paperdiffRetryBoot()">重试启动</button>
      <button onclick="window.__paperdiffOpenLogs()">打开日志目录</button>
    </div>
  </div>
<script>
  window.__paperdiffSplashError = function (msg, logPath) {{
    var bar = document.getElementById('pd-bar');
    var st = document.getElementById('pd-status');
    var err = document.getElementById('pd-err');
    var errMsg = document.getElementById('pd-err-msg');
    var lp = document.getElementById('pd-log-path');
    var acts = document.getElementById('pd-actions');
    if (bar) bar.style.display = 'none';
    if (st) st.textContent = '本地引擎启动未完成';
    if (errMsg) errMsg.textContent = msg || '本地服务启动超时（超过 15 秒），请检查端口或日志文件。';
    if (lp && logPath) lp.textContent = logPath;
    if (err) err.style.display = 'block';
    if (acts) acts.style.display = 'flex';
  }};
  window.__paperdiffRetryBoot = function () {{
    var bar = document.getElementById('pd-bar');
    var st = document.getElementById('pd-status');
    var err = document.getElementById('pd-err');
    var acts = document.getElementById('pd-actions');
    if (bar) bar.style.display = 'block';
    if (st) st.textContent = '正在重新启动本地学术引擎…';
    if (err) err.style.display = 'none';
    if (acts) acts.style.display = 'none';
    if (window.pywebview && window.pywebview.api && window.pywebview.api.retry_boot) {{
      window.pywebview.api.retry_boot();
    }}
  }};
  window.__paperdiffOpenLogs = function () {{
    if (window.pywebview && window.pywebview.api && window.pywebview.api.open_logs_dir) {{
      window.pywebview.api.open_logs_dir();
    }}
  }};
</script>
</body>
</html>"""


class EmbeddedServer:
    """Runs FastAPI/Uvicorn cleanly on a daemon thread without relying on sys.stdout.isatty()."""

    def __init__(
        self,
        port: int,
        data_dir: Path | None = None,
        instance_token: str | None = None,
    ) -> None:
        self.port = int(port)
        self.data_dir = runtime_state.resolve_data_dir(data_dir)
        self.instance_token = instance_token or runtime_state.generate_instance_token()
        self.server: Any = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        import uvicorn
        from backend.main import app as fastapi_app

        runtime_state.set_runtime_context(
            port=self.port,
            data_dir=self.data_dir,
            launch_mode="desktop",
            can_shutdown=False,
            instance_token=self.instance_token,
        )
        config = uvicorn.Config(
            app=fastapi_app,
            host="127.0.0.1",
            port=self.port,
            log_level="warning",
            log_config=None,
            access_log=False,
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True
        if self.thread is not None:
            self.thread.join(timeout=3.0)


class DesktopBridge:
    """JS-to-Python bridge exposed as window.pywebview.api inside the native WKWebView."""

    def __init__(
        self,
        *,
        data_dir: Path | None = None,
        open_url_fn: Callable[[str], Any] | None = None,
    ) -> None:
        self.window: Any = None
        self.controller: DesktopBootstrapController | None = None
        self.data_dir = runtime_state.resolve_data_dir(data_dir)
        self.active_url: str = ""
        self._open_url_fn = open_url_fn or webbrowser.open

    def set_active_url(self, url: str) -> None:
        self.active_url = str(url).rstrip("/")

    def open_in_browser(self, relative_url: str = "/") -> dict[str, object]:
        """Open current local PaperDiff URL in the system default browser with open-redirect protection."""
        if not self.active_url:
            return {"opened": False, "error": "本地服务尚未就绪"}
        rel = (relative_url or "/").strip()
        if not rel:
            rel = "/"
        if (
            not rel.startswith("/")
            or rel.startswith("//")
            or "://" in rel
            or "\r" in rel
            or "\n" in rel
            or "\\" in rel
        ):
            return {"opened": False, "error": "仅允许打开当前本地服务内的相对路径"}
        target = f"{self.active_url}{rel}"
        try:
            self._open_url_fn(target)
            return {"opened": True, "url": target}
        except Exception as exc:
            return {"opened": False, "error": str(exc)}

    def retry_boot(self) -> dict[str, object]:
        if self.controller is None or self.window is None:
            return {"retrying": False}
        self.controller.boot_async(self.window)
        return {"retrying": True}

    def get_runtime_info(self) -> dict[str, object]:
        return {
            "active_url": self.active_url,
            "data_dir": str(self.data_dir),
            "log_path": str(runtime_state.get_log_path(self.data_dir)),
            "owns_server": bool(self.controller.owns_server) if self.controller else False,
            "version": runtime_state.APP_VERSION,
        }

    def save_file_base64(self, filename: string_or_str, base64_data: str) -> dict[str, object]:
        raw = base64.b64decode(base64_data)
        safe_name = Path(filename or "export.txt").name
        default_dir = str(Path.home() / "Downloads")

        target_path: str | None = None
        if self.window is not None:
            import webview

            dialog_type = getattr(webview, "FileDialog", None)
            save_mode = dialog_type.SAVE if dialog_type is not None else webview.SAVE_DIALOG
            result = self.window.create_file_dialog(
                save_mode,
                directory=default_dir,
                save_filename=safe_name,
            )
            if isinstance(result, (list, tuple)) and result:
                target_path = str(result[0])
            elif isinstance(result, str) and result:
                target_path = result
            else:
                return {"saved": False, "cancelled": True}
        else:
            out = Path(default_dir) / safe_name
            target_path = str(out)

        dest = Path(target_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        return {"saved": True, "path": str(dest)}

    def export_pdf_from_html(
        self,
        filename: str,
        html_content: str,
        landscape: bool = False,
    ) -> dict[str, object]:
        """Export self-contained printable HTML to multi-page A4 PDF (macOS WKWebView or headless Edge/Chrome)."""
        safe_name = Path(filename or "paperdiff_report.pdf").name
        if not safe_name.lower().endswith(".pdf"):
            safe_name += ".pdf"
        default_dir = str(Path.home() / "Downloads")

        target_path: str | None = None
        if self.window is not None:
            import webview

            dialog_type = getattr(webview, "FileDialog", None)
            save_mode = dialog_type.SAVE if dialog_type is not None else webview.SAVE_DIALOG
            result = self.window.create_file_dialog(
                save_mode,
                directory=default_dir,
                save_filename=safe_name,
            )
            if isinstance(result, (list, tuple)) and result:
                target_path = str(result[0])
            elif isinstance(result, str) and result:
                target_path = result
            else:
                return {"saved": False, "cancelled": True}
        else:
            target_path = str(Path(default_dir) / safe_name)

        dest = Path(target_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Primary on macOS: native WKWebView + NSPrintOperation (zero external browser dependency!)
        if sys.platform == "darwin":
            try:
                import AppKit
                import Foundation
                import WebKit
                from PyObjCTools import AppHelper

                done_evt = threading.Event()
                err_box: list[str] = []

                def _run_native_print() -> None:
                    try:
                        w_pt, h_pt = (841.89, 595.28) if landscape else (595.28, 841.89)
                        frame = Foundation.NSMakeRect(0, 0, w_pt, h_pt)
                        cfg = WebKit.WKWebViewConfiguration.alloc().init()
                        wv = WebKit.WKWebView.alloc().initWithFrame_configuration_(frame, cfg)
                        self._print_wv = wv
                        wv.loadHTMLString_baseURL_(html_content, None)

                        def _do_print() -> None:
                            try:
                                pinfo = AppKit.NSPrintInfo.sharedPrintInfo().copy()
                                pinfo.setJobDisposition_(AppKit.NSPrintSaveJob)
                                pinfo.dictionary()[AppKit.NSPrintJobSavingURL] = Foundation.NSURL.fileURLWithPath_(str(dest))
                                pinfo.setPaperSize_(Foundation.NSMakeSize(w_pt, h_pt))
                                pinfo.setOrientation_(
                                    AppKit.NSPaperOrientationLandscape if landscape else AppKit.NSPaperOrientationPortrait
                                )
                                pinfo.setTopMargin_(36.0)
                                pinfo.setBottomMargin_(36.0)
                                pinfo.setLeftMargin_(36.0)
                                pinfo.setRightMargin_(36.0)
                                pinfo.setHorizontalPagination_(AppKit.NSFitPagination)
                                pinfo.setVerticalPagination_(AppKit.NSAutoPagination)
                                op = wv.printOperationWithPrintInfo_(pinfo)
                                op.setShowsPrintPanel_(False)
                                op.setShowsProgressPanel_(False)
                                op.runOperation()
                            except Exception as exc_inner:
                                err_box.append(str(exc_inner))
                            finally:
                                self._print_wv = None
                                done_evt.set()

                        AppHelper.callLater(1.2, _do_print)
                    except Exception as exc_outer:
                        err_box.append(str(exc_outer))
                        done_evt.set()

                AppHelper.callAfter(_run_native_print)
                done_evt.wait(timeout=20.0)
                if not err_box and dest.exists() and dest.stat().st_size > 200:
                    return {"saved": True, "path": str(dest), "engine": "wkwebview"}
            except Exception:
                pass

        # Windows primary / macOS fallback: headless Edge/Chrome --print-to-pdf
        try:
            from backend.export.pdf_exporter import render_html_to_pdf_bytes

            pdf_bytes = render_html_to_pdf_bytes(html_content)
            dest.write_bytes(pdf_bytes)
            return {"saved": True, "path": str(dest), "engine": "chromium"}
        except Exception as exc:
            return {"saved": False, "error": str(exc)}

    def get_data_dir(self) -> str:
        return str(self.data_dir)

    def open_data_dir(self) -> bool:
        _open_in_file_manager(self.data_dir)
        return True

    def open_logs_dir(self) -> bool:
        logs_dir = runtime_state.get_log_path(self.data_dir).parent
        _open_in_file_manager(logs_dir)
        return True

    def get_cli_install_status(self) -> dict[str, object]:
        return runtime_state.get_cli_install_status()

    def install_cli_command(self) -> dict[str, object]:
        return runtime_state.install_cli_command()

    def uninstall_cli_command(self) -> dict[str, object]:
        return runtime_state.uninstall_cli_command()

    def select_local_folder(self, initial_dir: str = "") -> dict[str, object]:
        """Open native OS folder picker for local-folder project binding (macOS NSOpenPanel / Windows Explorer)."""
        if self.window is None:
            return {"picked": False, "supported": False}

        from backend.local_workspace import normalize_user_path

        cleaned_init = normalize_user_path(initial_dir)
        start_dir = (
            str(Path(cleaned_init).expanduser().resolve())
            if cleaned_init and Path(cleaned_init).expanduser().is_dir()
            else str(Path.home())
        )
        try:
            import webview

            dialog_type = getattr(webview, "FileDialog", None)
            folder_mode = dialog_type.FOLDER if dialog_type is not None else webview.FOLDER_DIALOG
            result = self.window.create_file_dialog(folder_mode, directory=start_dir)
        except Exception as exc:
            return {"picked": False, "supported": False, "detail": str(exc)}

        chosen: str | None = None
        if isinstance(result, (list, tuple)) and result:
            chosen = str(result[0])
        elif isinstance(result, str) and result:
            chosen = result
        if not chosen:
            return {"picked": False, "cancelled": True, "supported": True}
        return {"picked": True, "supported": True, "path": str(Path(chosen).resolve())}


string_or_str = str


class DesktopBootstrapController:
    """Coordinates Splash-First window bootstrap, single-instance reuse, and ownership-safe shutdown."""

    def __init__(
        self,
        *,
        data_dir: Path | None = None,
        bridge: DesktopBridge | None = None,
        requested_port: int = 0,
        server_factory: Callable[..., Any] = EmbeddedServer,
        boot_timeout: float = 15.0,
        initial_open_path: str | None = None,
    ) -> None:
        self.data_dir = runtime_state.resolve_data_dir(data_dir)
        self.log_path = runtime_state.get_log_path(self.data_dir)
        self.logger = runtime_state.configure_rotating_file_logger(self.data_dir, name="paperdiff.desktop")
        self.bridge = bridge or DesktopBridge(data_dir=self.data_dir)
        self.bridge.controller = self
        self.requested_port = int(requested_port)
        self.server_factory = server_factory
        self.boot_timeout = float(boot_timeout)
        self.initial_open_path = initial_open_path

        self.server: Any = None
        self.owns_server: bool = False
        self.active_url: str = ""
        self.active_port: int = 0
        self._boot_lock = threading.Lock()

    def _notify_error(self, window: Any, message: str) -> None:
        self.logger.error("Desktop bootstrap error: %s", message)
        if window is not None and hasattr(window, "evaluate_js"):
            js = f"window.__paperdiffSplashError({json.dumps(message, ensure_ascii=False)}, {json.dumps(str(self.log_path), ensure_ascii=False)})"
            try:
                window.evaluate_js(js)
            except Exception:
                pass

    def boot_sync(self, window: Any) -> bool:
        """Probe existing healthy server or boot embedded backend, then navigate Splash window."""
        with self._boot_lock:
            try:
                with runtime_state.acquire_init_lock(self.data_dir, timeout=8.0):
                    existing = runtime_state.probe_running_instance(self.data_dir)
                    if existing is not None:
                        self.owns_server = False
                        self.server = None
                        self.active_port = int(existing["port"])
                        self.active_url = str(existing["url"])
                        self.bridge.set_active_url(self.active_url)
                        self.logger.info("Reusing existing PaperDiff instance at %s (pid=%s)", self.active_url, existing["pid"])
                        target_url = self.active_url
                        if self.initial_open_path:
                            open_res = runtime_state.post_open_local_path("127.0.0.1", self.active_port, self.initial_open_path)
                            handoff = str(open_res.get("handoff_path") or "/")
                            if handoff != "/":
                                target_url = f"{self.active_url}{handoff}"
                        if window is not None:
                            window.load_url(target_url)
                        return True

                    port = self.requested_port or find_free_port()
                    token = runtime_state.generate_instance_token()
                    srv = self.server_factory(port, self.data_dir, token)
                    srv.start()
                    self.server = srv
                    self.owns_server = True
                    self.active_port = port
                    self.active_url = f"http://127.0.0.1:{port}"

                    if not wait_for_server(self.active_url, timeout=self.boot_timeout):
                        srv.stop()
                        self.server = None
                        self.owns_server = False
                        self._notify_error(
                            window,
                            f"本地学术引擎在 {int(self.boot_timeout)} 秒内未能就绪，请检查端口占用或日志详情。",
                        )
                        return False

                    runtime_state.write_lock_file(
                        self.data_dir,
                        pid=os.getpid(),
                        host="127.0.0.1",
                        port=port,
                        launch_mode="desktop",
                        instance_token=token,
                    )
                    self.bridge.set_active_url(self.active_url)
                    self.logger.info("Started embedded desktop PaperDiff backend at %s", self.active_url)
                    target_url = self.active_url
                    if self.initial_open_path:
                        open_res = runtime_state.post_open_local_path("127.0.0.1", self.active_port, self.initial_open_path)
                        handoff = str(open_res.get("handoff_path") or "/")
                        if handoff != "/":
                            target_url = f"{self.active_url}{handoff}"
                    if window is not None:
                        window.load_url(target_url)
                    return True
            except Exception as exc:
                if self.owns_server and self.server is not None:
                    try:
                        self.server.stop()
                    except Exception:
                        pass
                    self.server = None
                    self.owns_server = False
                self._notify_error(window, f"本地服务启动异常：{exc}")
                return False

    def boot_async(self, window: Any) -> threading.Thread:
        t = threading.Thread(target=self.boot_sync, args=(window,), daemon=True)
        t.start()
        return t

    def shutdown(self) -> None:
        if not self.owns_server:
            return
        try:
            if self.server is not None:
                self.server.stop()
        finally:
            self.server = None
            self.owns_server = False
            runtime_state.remove_lock_file(self.data_dir, expected_pid=os.getpid())


def run_headless_smoke_test(url: str, data_dir: Path) -> int:
    """Verify frozen binary boots FastAPI v0.1.0, lazy jieba, single-instance lock, SPA, W1 & W2."""
    checks: dict[str, object] = {"url": url, "data_dir": str(data_dir)}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def fetch_json(path: str) -> Any:
        with opener.open(f"{url}{path}", timeout=8.0) as r:
            assert r.status == 200, f"{path} returned {r.status}"
            return json.loads(r.read().decode("utf-8"))

    health = fetch_json("/api/health")
    assert health.get("version") == runtime_state.APP_VERSION
    assert "instance_token" not in health
    checks["health"] = health

    # Verify single-instance probe recognizes active smoke server
    probed = runtime_state.probe_running_instance(data_dir)
    assert probed is not None and probed["url"] == url
    checks["single_instance_lock_ok"] = True

    with opener.open(f"{url}/", timeout=5.0) as r:
        html_body = r.read().decode("utf-8")
        assert r.status == 200 and "<div id=\"root\">" in html_body
        checks["spa_ok"] = True

    with opener.open(f"{url}/manifest.webmanifest", timeout=5.0) as r:
        manifest = json.loads(r.read().decode("utf-8"))
        assert r.status == 200 and manifest.get("display") == "standalone"
        checks["pwa_manifest_ok"] = True

    with opener.open(f"{url}/favicon.svg", timeout=5.0) as r:
        svg_body = r.read().decode("utf-8")
        assert r.status == 200 and "<svg" in svg_body
        checks["favicon_ok"] = True

    projects = fetch_json("/api/projects")
    assert isinstance(projects, list) and len(projects) >= 2
    checks["seeded_projects"] = len(projects)

    # Verify jieba has NOT been loaded yet before Chinese diff
    checks["jieba_lazy_before_diff"] = "jieba" not in sys.modules
    assert checks["jieba_lazy_before_diff"] is True, "jieba must stay lazy until first Chinese diff"

    # Verify jieba Chinese tokenization + diff + Word Track Changes export inside frozen bundle
    req_data = json.dumps({
        "old_content": "值得注意的是，稀疏注意力在长上下文中的推理误差达到 14.2%。",
        "new_content": "稀疏注意力在长上下文中的推理误差达到 15.8%。",
        "export_type": "docx_tracked",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/api/export",
        data=req_data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(req, timeout=10.0) as r:
        docx_bytes = r.read()
        assert r.status == 200 and docx_bytes[:2] == b"PK" and len(docx_bytes) > 5000
        checks["docx_tracked_bytes"] = len(docx_bytes)
    checks["jieba_loaded_after_diff"] = "jieba" in sys.modules
    assert checks["jieba_loaded_after_diff"] is True

    # Verify AST parsers & offline KaTeX print HTML inside frozen bundle
    req_print = urllib.request.Request(
        f"{url}/api/export",
        data=json.dumps({
            "old_content": r"\newcommand{\R}{\mathbb{R}} Flux $v \in \R$ is \SI{42.5}{\um}.",
            "new_content": r"\newcommand{\R}{\mathbb{R}} Flux $v \in \R$ is \SI{45.0}{\um}.",
            "old_format": "latex",
            "new_format": "latex",
            "export_type": "print_html_diff",
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(req_print, timeout=10.0) as r:
        print_html = r.read().decode("utf-8")
        assert r.status == 200 and "katex" in print_html.lower() and "cdn.jsdelivr" not in print_html.lower()
        checks["offline_print_html_kb"] = round(len(print_html) / 1024, 1)

    # Verify W1 typography_hints & W2 local-folder workspace inside frozen bundle
    smoke_dir = Path(tempfile.mkdtemp(prefix="paperdiff_w2_smoke_"))
    try:
        (smoke_dir / "v1.md").write_text("# 引言\n\n第一段测试正文。\n", encoding="utf-8")
        (smoke_dir / "v2.md").write_text("# 引言\n\n第一段测试正文修订版。\n", encoding="utf-8")

        req_val = urllib.request.Request(
            f"{url}/api/local/validate-folder",
            data=json.dumps({"path": str(smoke_dir)}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with opener.open(req_val, timeout=8.0) as r:
            val_data = json.loads(r.read().decode("utf-8"))
            assert r.status == 200 and val_data.get("valid") is True and val_data.get("doc_count") == 2

        req_create = urllib.request.Request(
            f"{url}/api/projects",
            data=json.dumps({
                "name": "Smoke Local Workspace",
                "project_mode": "local_folder",
                "local_root_path": str(smoke_dir),
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with opener.open(req_create, timeout=8.0) as r:
            proj_data = json.loads(r.read().decode("utf-8"))
            proj_id = proj_data["id"]

        tree_data = fetch_json(f"/api/projects/{proj_id}/local/tree")
        assert tree_data.get("doc_count") == 2

        req_prev = urllib.request.Request(
            f"{url}/api/projects/{proj_id}/local/preview",
            data=json.dumps({"rel_path": "v1.md"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with opener.open(req_prev, timeout=8.0) as r:
            prev_data = json.loads(r.read().decode("utf-8"))
            assert r.status == 200 and "typography_hints" in prev_data

        req_del = urllib.request.Request(f"{url}/api/projects/{proj_id}", method="DELETE")
        with opener.open(req_del, timeout=8.0) as r:
            assert r.status == 200
        assert (smoke_dir / "v1.md").exists(), "Deleting local project must not delete disk files"

        # Verify POST /api/local/open-path & multi-monitor window clamping inside frozen bundle
        req_open = urllib.request.Request(
            f"{url}/api/local/open-path",
            data=json.dumps({"path": str(smoke_dir / "v1.md")}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with opener.open(req_open, timeout=8.0) as r:
            open_data = json.loads(r.read().decode("utf-8"))
            assert r.status == 200 and open_data.get("created") is True and open_data.get("rel_path") == "v1.md"
            open_pid = int(open_data["project_id"])
        with opener.open(urllib.request.Request(f"{url}/api/projects/{open_pid}", method="DELETE"), timeout=8.0) as r:
            assert r.status == 200
        clamped = runtime_state.clamp_window_geometry(
            {"width": 1400, "height": 900, "x": 4500, "y": 200},
            [{"x": 0, "y": 0, "width": 1728, "height": 1117}],
        )
        assert clamped["x"] is not None and 0 <= clamped["x"] < 1728
        checks["w1_w2_local_workspace_ok"] = True
        checks["w2_open_path_and_window_clamp_ok"] = True
    finally:
        shutil.rmtree(smoke_dir, ignore_errors=True)

    # Verify platform-native WebView / pywebview runtime imports cleanly inside frozen bundle
    checks.update(_verify_native_webview_runtime())

    print("PAPERDIFF_SMOKE_TEST_PASS", json.dumps(checks, ensure_ascii=False))
    return 0


def _open_in_file_manager(path: Path) -> None:
    """Open a directory in the OS native file manager (Explorer on Windows, Finder on macOS)."""
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _verify_native_webview_runtime() -> dict[str, Any]:
    """Verify platform-appropriate pywebview native backend imports inside frozen bundles."""
    import webview  # noqa: F401

    version = getattr(webview, "__version__", "unknown")
    if sys.platform == "darwin":
        import AppKit  # noqa: F401
        import Foundation  # noqa: F401
        import UniformTypeIdentifiers  # noqa: F401
        import WebKit  # noqa: F401
        from webview.platforms import cocoa  # noqa: F401

        return {"webview_cocoa_ok": True, "webview_version": version}
    if sys.platform == "win32":
        from webview.platforms import edgechromium  # noqa: F401

        return {"webview_edgechromium_ok": True, "webview_version": version}
    return {"webview_ok": True, "webview_version": version}


def _show_native_error_dialog(title: str, message: str) -> None:
    """Display an actionable native error dialog when the GUI webview fails to initialize."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, str(message), str(title), 0x10)
            return
        except Exception:
            pass
    print(f"[{title}]\n{message}", file=sys.stderr)


def _start_webview_with_guard(
    webview_mod: Any,
    *,
    func: Callable[[], None],
    debug: bool = False,
) -> int:
    """Launch `webview.start(...)` and surface a friendly Chinese dialog if WebView2/GUI fails."""
    try:
        webview_mod.start(func=func, debug=debug)
        return 0
    except Exception as exc:
        err_text = str(exc)
        if sys.platform == "win32":
            msg = (
                "对稿 · PaperDiff 无法初始化桌面窗口。\n\n"
                "若您使用的是精简版或早期 Windows 10，请先安装 Microsoft Edge WebView2 Runtime：\n"
                "https://developer.microsoft.com/microsoft-edge/webview2/\n\n"
                "您也可以改用项目目录内的「启动PaperDiff.bat」以浏览器模式运行。\n\n"
                f"详细错误：{err_text}"
            )
        else:
            msg = f"对稿 · PaperDiff 桌面窗口启动失败：{err_text}"
        _show_native_error_dialog("对稿 · PaperDiff 启动失败", msg)
        return 2


def get_connected_screens() -> list[dict[str, int]]:
    """Query connected display frames for safe multi-monitor window placement."""
    try:
        import webview

        out: list[dict[str, int]] = []
        for scr in getattr(webview, "screens", []) or []:
            out.append(
                {
                    "x": int(getattr(scr, "x", 0) or 0),
                    "y": int(getattr(scr, "y", 0) or 0),
                    "width": int(getattr(scr, "width", 0) or 0),
                    "height": int(getattr(scr, "height", 0) or 0),
                }
            )
        if out:
            return out
    except Exception:
        pass
    if sys.platform == "darwin":
        try:
            import AppKit

            out = []
            for scr in AppKit.NSScreen.screens() or []:
                f = scr.visibleFrame()
                out.append(
                    {
                        "x": int(f.origin.x),
                        "y": int(f.origin.y),
                        "width": int(f.size.width),
                        "height": int(f.size.height),
                    }
                )
            return out
        except Exception:
            return []
    return []


def resolve_initial_window_geometry(
    data_dir: Path,
    screens: list[dict[str, int]] | None = None,
) -> dict[str, int | None]:
    saved = runtime_state.load_window_state(data_dir)
    active_screens = screens if screens is not None else get_connected_screens()
    return runtime_state.clamp_window_geometry(saved, active_screens)


def persist_window_geometry(data_dir: Path, window: Any) -> bool:
    """Safely capture and persist desktop window dimensions and position."""
    try:
        w = int(getattr(window, "width"))
        h = int(getattr(window, "height"))
        x_raw = getattr(window, "x", None)
        y_raw = getattr(window, "y", None)
        x = int(x_raw) if x_raw is not None else None
        y = int(y_raw) if y_raw is not None else None
        if w <= 0 or h <= 0:
            return False
        runtime_state.save_window_state(data_dir, width=w, height=h, x=x, y=y)
        return True
    except Exception:
        return False


def _parse_desktop_open_path(argv: list[str]) -> str | None:
    args = argv[1:]
    if not args:
        return None
    for idx, tok in enumerate(args):
        if tok == "--open" and idx + 1 < len(args):
            return args[idx + 1]
        if tok.startswith("--open="):
            return tok.split("=", 1)[1]
    # Support Finder / CLI positional path argument (ignore macOS -psn_* launch flags)
    for tok in args:
        if not tok.startswith("-"):
            return tok
    return None


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if _stream is not None and hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    data_dir = runtime_state.resolve_data_dir()
    requested_port = int(os.environ.get("PAPERDIFF_PORT", "0") or "0")
    open_path_arg = _parse_desktop_open_path(sys.argv)
    resolved_open_path: str | None = None
    if open_path_arg:
        try:
            resolved_open_path = str(runtime_state.validate_cli_target_path(open_path_arg))
        except Exception as exc:
            print(f"[错误] {exc}", file=sys.stderr)
            sys.exit(1)

    if os.environ.get("PAPERDIFF_SMOKE_TEST") == "1":
        port = requested_port or find_free_port()
        url = f"http://127.0.0.1:{port}"
        token = runtime_state.generate_instance_token()
        srv = EmbeddedServer(port, data_dir=data_dir, instance_token=token)
        srv.start()
        if not wait_for_server(url):
            srv.stop()
            sys.exit(1)
        runtime_state.write_lock_file(
            data_dir,
            pid=os.getpid(),
            host="127.0.0.1",
            port=port,
            launch_mode="desktop",
            instance_token=token,
        )
        try:
            code = run_headless_smoke_test(url, data_dir)
        finally:
            srv.stop()
            runtime_state.remove_lock_file(data_dir, expected_pid=os.getpid())
        sys.exit(code)

    import webview

    webview.settings["ALLOW_DOWNLOADS"] = True
    bridge = DesktopBridge(data_dir=data_dir)
    controller = DesktopBootstrapController(
        data_dir=data_dir,
        bridge=bridge,
        requested_port=requested_port,
        initial_open_path=resolved_open_path,
    )
    splash_html = build_splash_html(str(controller.log_path))
    geom = resolve_initial_window_geometry(data_dir)
    win_kwargs: dict[str, Any] = {
        "title": "对稿 · PaperDiff",
        "html": splash_html,
        "width": int(geom["width"] or 1440),
        "height": int(geom["height"] or 900),
        "min_size": (1060, 680),
        "resizable": True,
        "text_select": True,
        "js_api": bridge,
    }
    if geom.get("x") is not None and geom.get("y") is not None:
        win_kwargs["x"] = int(geom["x"])  # type: ignore[arg-type]
        win_kwargs["y"] = int(geom["y"])  # type: ignore[arg-type]
    win = webview.create_window(**win_kwargs)
    bridge.window = win
    try:
        win.events.closing += lambda: persist_window_geometry(data_dir, win)
    except Exception:
        pass
    rc = 0
    try:
        rc = _start_webview_with_guard(webview, func=lambda: controller.boot_async(win), debug=False)
    finally:
        persist_window_geometry(data_dir, win)
        controller.shutdown()
    if rc != 0:
        sys.exit(rc)


if __name__ == "__main__":
    main()
