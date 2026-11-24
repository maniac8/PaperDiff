#!/usr/bin/env python3
"""Cross-Platform (macOS + Windows) Web Mode Launcher for 对稿 · PaperDiff Studio (v0.2.0).

Supports:
    - Single-instance reuse per `DATA_DIR` via `backend.runtime_state` (`server.lock` + `/api/health`).
    - `--daemon`: Silent background launch (macOS `start_new_session` / Windows `DETACHED_PROCESS | CREATE_NO_WINDOW`)
      with rotating file logs at `DATA_DIR/logs/server.log` and zero lingering terminal/CMD window.
    - `--status [--json]`: Inspect running instance status, PID, port, URL, and log path.
    - `--stop [--json]`: Gracefully stop the active local Web backend and clean up `server.lock`.
    - Default (foreground): Developer-friendly foreground mode that still reuses any healthy existing instance.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from typing import Any
import webbrowser

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import runtime_state  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


def build_daemon_popen_kwargs(platform_name: str | None = None) -> dict[str, Any]:
    """Return OS-specific `subprocess.Popen` detachment kwargs (macOS/Linux + Windows)."""
    plat = (platform_name or sys.platform).lower()
    if plat.startswith("win"):
        return {
            "creationflags": DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
            "close_fds": True,
        }
    return {
        "start_new_session": True,
        "close_fds": True,
    }


def get_app_browser_candidates(
    platform_name: str | None = None,
    env: dict[str, str] | None = None,
) -> list[str]:
    """Return ordered Chromium/Edge browser executables supporting `--app=<url>` standalone mode."""
    plat = (platform_name or sys.platform).lower()
    environ = env if env is not None else dict(os.environ)
    candidates: list[str] = []

    if plat == "darwin":
        candidates.extend(
            [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "/Applications/Arc.app/Contents/MacOS/Arc",
            ]
        )
    elif plat.startswith("win"):
        roots = [
            environ.get("PROGRAMFILES", r"C:\Program Files"),
            environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            environ.get("LOCALAPPDATA", ""),
        ]
        rel_bins = [
            r"Google\Chrome\Application\chrome.exe",
            r"Microsoft\Edge\Application\msedge.exe",
        ]
        for base in roots:
            if not base:
                continue
            for rel in rel_bins:
                candidates.append(f"{base.rstrip(chr(92))}\\{rel}")
    else:
        for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
            found = shutil.which(name)
            if found:
                candidates.append(found)

    for fallback_bin in ("google-chrome", "chromium", "msedge"):
        found = shutil.which(fallback_bin)
        if found and found not in candidates:
            candidates.append(found)
    return candidates


def find_free_port(start: int = 8765, end: int = 8795) -> int:
    return runtime_state.find_free_port(start, end)


def wait_until_ready(port: int, timeout: float = 15.0) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        health = runtime_state.fetch_health("127.0.0.1", port, timeout=0.8)
        if health and health.get("status") == "ok":
            return health
        time.sleep(0.12)
    return None


def open_desktop_window(url: str) -> None:
    """Open URL in standalone Chromium/Edge `--app=` window if available, else system default browser."""
    popen_extra: dict[str, Any] = {}
    if sys.platform.startswith("win"):
        popen_extra["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    for exe in get_app_browser_candidates():
        if exe and Path(exe).exists():
            try:
                subprocess.Popen(
                    [exe, f"--app={url}", "--window-size=1480,920"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    **popen_extra,
                )
                return
            except Exception:
                pass
    webbrowser.open(url)


def _serve_process(port: int, launch_mode: str, open_browser: bool, token: str | None = None) -> int:
    """Run FastAPI/Uvicorn in current process with single-instance lock & rotating logs."""
    data_dir = runtime_state.resolve_data_dir()
    log_path = runtime_state.get_log_path(data_dir)
    logger = runtime_state.configure_rotating_file_logger(data_dir)
    instance_token = token or runtime_state.generate_instance_token()

    import uvicorn
    from backend.main import app as fastapi_app

    runtime_state.set_runtime_context(
        port=port,
        data_dir=data_dir,
        launch_mode=launch_mode,
        can_shutdown=True,
        instance_token=instance_token,
    )
    runtime_state.write_lock_file(
        data_dir,
        pid=os.getpid(),
        host="127.0.0.1",
        port=port,
        launch_mode=launch_mode,
        instance_token=instance_token,
    )

    config = uvicorn.Config(
        app=fastapi_app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        log_config=None if launch_mode == "web_daemon" else uvicorn.config.LOGGING_CONFIG,
        access_log=False,
    )
    server = uvicorn.Server(config)

    def _graceful_stop() -> None:
        logger.info("Received graceful shutdown request (pid=%s, port=%s)", os.getpid(), port)
        server.should_exit = True

    runtime_state.register_shutdown_callback(_graceful_stop)
    url = f"http://127.0.0.1:{port}"
    logger.info("Starting PaperDiff Web backend mode=%s url=%s data_dir=%s", launch_mode, url, data_dir)

    if open_browser:
        def _open_when_ready() -> None:
            if wait_until_ready(port, timeout=15.0):
                open_desktop_window(url)

        threading.Thread(target=_open_when_ready, daemon=True).start()

    try:
        server.run()
    finally:
        runtime_state.register_shutdown_callback(None)
        runtime_state.remove_lock_file(data_dir, expected_pid=os.getpid())
        logger.info("PaperDiff Web backend stopped cleanly (pid=%s, log=%s)", os.getpid(), log_path)
    return 0


def _emit_output(payload: dict[str, Any], as_json: bool, human_lines: list[str]) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        for line in human_lines:
            print(line)


def _handle_daemon_start(
    requested_port: int,
    open_browser: bool,
    as_json: bool,
    target_path: str | None = None,
) -> int:
    resolved_target: Path | None = None
    if target_path:
        try:
            resolved_target = runtime_state.validate_cli_target_path(target_path)
        except Exception as exc:
            if as_json:
                print(json.dumps({"running": False, "error": str(exc)}, ensure_ascii=False))
            else:
                print(f"[错误] {exc}", file=sys.stderr)
            return 1

    data_dir = runtime_state.resolve_data_dir()
    log_path = runtime_state.get_log_path(data_dir)
    reused = False

    with runtime_state.acquire_init_lock(data_dir, timeout=8.0):
        existing = runtime_state.probe_running_instance(data_dir)
        if existing is not None:
            reused = True
            ready_info = existing
        else:
            port = requested_port or find_free_port()
            cmd = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--serve-daemon",
                "--port",
                str(port),
            ]
            env = os.environ.copy()
            env["PAPERDIFF_DATA_DIR"] = str(data_dir)
            env["PAPERDIFF_PORT"] = str(port)
            env["PAPERDIFF_NO_BROWSER"] = "1"

            popen_kwargs = build_daemon_popen_kwargs()
            with open(log_path, "a", encoding="utf-8") as log_fp:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(ROOT),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log_fp,
                    stderr=log_fp,
                    **popen_kwargs,
                )

            deadline = time.monotonic() + 15.0
            ready_info = None
            while time.monotonic() < deadline:
                ready_info = runtime_state.probe_running_instance(
                    data_dir,
                    health_timeout=0.5,
                    cleanup_stale=False,
                )
                if ready_info is not None:
                    break
                if proc.poll() is not None:
                    break
                time.sleep(0.12)

    if ready_info is None:
        payload = {
            "running": False,
            "reused": False,
            "error": "本地服务启动超时或异常退出，请查看日志定位原因。",
            "log_path": str(log_path),
        }
        _emit_output(
            payload,
            as_json,
            [
                "\n  [启动失败] PaperDiff 本地服务未能就绪。",
                f"  请检查运行日志：{log_path}\n",
            ],
        )
        return 1

    url = str(ready_info["url"])
    handoff_path = "/"
    open_meta: dict[str, Any] = {}
    if resolved_target is not None:
        try:
            open_meta = runtime_state.post_open_local_path(
                str(ready_info["host"]),
                int(ready_info["port"]),
                resolved_target,
            )
            handoff_path = str(open_meta.get("handoff_path") or "/")
        except Exception as exc:
            if as_json:
                print(json.dumps({"running": True, "error": str(exc)}, ensure_ascii=False))
            else:
                print(f"[错误] {exc}", file=sys.stderr)
            return 1

    target_url = url if handoff_path == "/" else f"{url}{handoff_path}"
    if open_browser:
        open_desktop_window(target_url)

    payload: dict[str, Any] = {
        "running": True,
        "reused": reused,
        "pid": ready_info["pid"],
        "port": ready_info["port"],
        "url": url,
        "target_url": target_url,
        "handoff_path": handoff_path,
        "data_dir": ready_info["data_dir"],
        "log_path": ready_info["log_path"],
        "launch_mode": ready_info["launch_mode"],
    }
    if open_meta:
        payload.update(
            {
                "project_id": open_meta.get("project_id"),
                "project_name": open_meta.get("project_name"),
                "created": open_meta.get("created"),
                "rel_path": open_meta.get("rel_path"),
            }
        )

    lines = (
        [
            f"\n  对稿 · PaperDiff 已在运行，直接复用现有实例：{target_url}",
            f"  PID: {ready_info['pid']} · 日志: {ready_info['log_path']}\n",
        ]
        if reused
        else [
            f"\n  对稿 · PaperDiff 已在后台静默启动：{target_url}",
            f"  PID: {ready_info['pid']} · 日志: {ready_info['log_path']}",
            "  无需保留本终端窗口；如需停止，请点击网页顶栏「停止本地服务」或运行停止脚本。\n",
        ]
    )
    _emit_output(payload, as_json, lines)
    return 0


def _handle_status(as_json: bool) -> int:
    data_dir = runtime_state.resolve_data_dir()
    info = runtime_state.probe_running_instance(data_dir)
    if info is None:
        payload = {
            "running": False,
            "data_dir": str(data_dir),
            "log_path": str(runtime_state.get_log_path(data_dir)),
        }
        _emit_output(payload, as_json, ["PaperDiff 本地服务当前未运行。"])
        return 0
    payload = {
        "running": True,
        "pid": info["pid"],
        "port": info["port"],
        "url": info["url"],
        "data_dir": info["data_dir"],
        "log_path": info["log_path"],
        "launch_mode": info["launch_mode"],
        "version": info["version"],
    }
    _emit_output(
        payload,
        as_json,
        [
            f"PaperDiff 本地服务运行中：{info['url']} (PID {info['pid']}, v{info['version']})",
            f"数据目录：{info['data_dir']}",
            f"日志文件：{info['log_path']}",
        ],
    )
    return 0


def _handle_stop(as_json: bool) -> int:
    data_dir = runtime_state.resolve_data_dir()
    res = runtime_state.request_graceful_shutdown(data_dir, timeout=6.0)
    if res.get("stopped"):
        msg = [f"PaperDiff 本地服务已优雅停止（PID {res.get('pid')}，端口 {res.get('port')}）。"]
    elif not res.get("was_running"):
        msg = ["当前没有正在运行的 PaperDiff 本地服务。"]
    else:
        msg = [str(res.get("detail") or "停止本地服务失败，请检查进程状态。")]
    _emit_output(res, as_json, msg)
    return 0 if (res.get("stopped") or not res.get("was_running")) else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="对稿 · PaperDiff 跨平台本地 Web 启动器")
    parser.add_argument("target_path", nargs="?", default=None, help="可选：直接打开的本地论文目录或受支持文稿路径")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--daemon", action="store_true", help="后台静默启动本地服务并打开浏览器")
    group.add_argument("--status", action="store_true", help="查看当前数据目录的本地服务运行状态")
    group.add_argument("--stop", action="store_true", help="优雅停止正在运行的本地服务")
    group.add_argument("--serve-daemon", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=0, help="指定监听端口（默认自动探测 8765-8795）")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出结果")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    requested_port = args.port or int(os.environ.get("PAPERDIFF_PORT", "0") or "0")
    open_browser = (not args.no_browser) and (os.environ.get("PAPERDIFF_NO_BROWSER") != "1")

    if args.status:
        return _handle_status(as_json=args.json)
    if args.stop:
        return _handle_stop(as_json=args.json)
    if args.serve_daemon:
        return _serve_process(port=requested_port or find_free_port(), launch_mode="web_daemon", open_browser=False)
    if args.daemon or args.target_path:
        return _handle_daemon_start(
            requested_port=requested_port,
            open_browser=open_browser,
            as_json=args.json,
            target_path=args.target_path,
        )

    # Default foreground mode: still honors single-instance reuse
    data_dir = runtime_state.resolve_data_dir()
    existing = runtime_state.probe_running_instance(data_dir)
    if existing is not None:
        url = existing["url"]
        print(f"\n  PaperDiff Studio 已在运行，直接复用：{url} (PID {existing['pid']})\n")
        if open_browser:
            open_desktop_window(url)
        return 0

    port = requested_port or find_free_port()
    url = f"http://127.0.0.1:{port}"
    print(f"\n  PaperDiff Studio 已启动：{url}")
    print("  按 Ctrl+C 停止本地服务。\n")
    return _serve_process(port=port, launch_mode="web_foreground", open_browser=open_browser)


if __name__ == "__main__":
    raise SystemExit(main())
