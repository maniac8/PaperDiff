"""Cross-platform Runtime State, Single-Instance Lock & Rotating Log Coordinator.

Pure Python standard-library module shared by:
    - `paperdiff/desktop_app.py` (macOS native WKWebView desktop app)
    - `paperdiff/launch_desktop.py` (Cross-platform macOS + Windows Web launcher)
    - `paperdiff/backend/main.py` (FastAPI `/api/health` & `/api/runtime/shutdown`)

Design invariants:
    - Zero third-party imports (does NOT import FastAPI/Uvicorn/jieba), keeping
      pre-splash startup import overhead under 10 ms.
    - 100% cross-platform (macOS + Windows): never imports POSIX-only `fcntl`.
      Uses atomic `os.O_CREAT | os.O_EXCL` init lock with dead-PID / timeout recovery.
    - Strict loopback (`127.0.0.1`) & normalized `data_dir` matching before reusing
      any existing instance.
"""
from __future__ import annotations

import contextlib
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Iterator
import urllib.error
import urllib.request

APP_VERSION = "0.2.0"
LOCK_FILENAME = "server.lock"
INIT_LOCK_FILENAME = "server.lock.init"
WINDOW_STATE_FILENAME = "window_state.json"
PORTABLE_FLAG_FILENAME = "portable.flag"
LOGS_SUBDIR = "logs"
LOG_FILENAME = "server.log"
LOG_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
LOG_BACKUP_COUNT = 3

_CTX_LOCK = threading.Lock()
_RUNTIME_CONTEXT: dict[str, Any] = {
    "pid": os.getpid(),
    "host": "127.0.0.1",
    "port": 0,
    "data_dir": "",
    "log_path": "",
    "launch_mode": "test",
    "can_shutdown": False,
    "instance_token": "",
}
_SHUTDOWN_CALLBACK: Callable[[], None] | None = None


def _resolve_default_frozen_data_dir() -> Path:
    """Return the platform-standard per-user data directory for frozen desktop binaries."""
    if sys.platform == "win32":
        local_app = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app:
            return Path(local_app).expanduser() / "PaperDiff"
        return Path.home() / "AppData" / "Local" / "PaperDiff"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "PaperDiff"
    xdg_data = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg_data:
        return Path(xdg_data).expanduser() / "PaperDiff"
    return Path.home() / ".local" / "share" / "PaperDiff"


def resolve_data_dir(explicit: str | Path | None = None) -> Path:
    """Resolve active DATA_DIR identically to `backend.database._resolve_data_dir`.

    Resolution precedence:
        1. Explicit `explicit` argument or `PAPERDIFF_DATA_DIR` environment variable.
        2. Portable mode when `sys.frozen` is True and `<exe_dir>/portable.flag` exists
           (uses `<exe_dir>/data`, falling back to the OS per-user dir if read-only).
        3. Platform-standard frozen per-user directory (`%LOCALAPPDATA%\\PaperDiff` on Windows,
           `~/Library/Application Support/PaperDiff` on macOS).
        4. Local `paperdiff/data/` directory during source development.
    """
    if explicit is not None and str(explicit).strip():
        target = Path(explicit).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        return target

    env_dir = os.environ.get("PAPERDIFF_DATA_DIR", "").strip()
    if env_dir:
        target = Path(env_dir).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        return target

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve(strict=False).parent
        if (exe_dir / PORTABLE_FLAG_FILENAME).exists():
            portable_target = (exe_dir / "data").resolve(strict=False)
            try:
                portable_target.mkdir(parents=True, exist_ok=True)
                probe = portable_target / f".write_probe_{os.getpid()}"
                probe.write_bytes(b"")
                probe.unlink(missing_ok=True)
                return portable_target
            except OSError:
                # Read-only removable media or protected folder -> safe fallback
                pass
        target = _resolve_default_frozen_data_dir().resolve(strict=False)
        target.mkdir(parents=True, exist_ok=True)
        return target

    target = (Path(__file__).resolve().parent.parent / "data").resolve(strict=False)
    target.mkdir(parents=True, exist_ok=True)
    return target


def get_lock_path(data_dir: str | Path) -> Path:
    return Path(data_dir).expanduser().resolve() / LOCK_FILENAME


def get_init_lock_path(data_dir: str | Path) -> Path:
    return Path(data_dir).expanduser().resolve() / INIT_LOCK_FILENAME


def get_log_path(data_dir: str | Path) -> Path:
    logs_dir = Path(data_dir).expanduser().resolve() / LOGS_SUBDIR
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / LOG_FILENAME


def generate_instance_token() -> str:
    return secrets.token_hex(32)


def configure_rotating_file_logger(
    data_dir: str | Path,
    name: str = "paperdiff.runtime",
) -> logging.Logger:
    """Configure a UTF-8 rotating file logger at `DATA_DIR/logs/server.log`."""
    log_path = get_log_path(data_dir)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    resolved_str = str(log_path)
    for existing in logger.handlers:
        if isinstance(existing, RotatingFileHandler) and getattr(existing, "baseFilename", "") == resolved_str:
            return logger
    handler = RotatingFileHandler(
        resolved_str,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    return logger


def _is_pid_alive_windows(pid: int, kernel32: Any | None = None) -> bool:
    """Windows-safe PID liveness probe via OpenProcess + GetExitCodeProcess."""
    if pid <= 0:
        return False
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    k32 = kernel32 if kernel32 is not None else ctypes.windll.kernel32
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not k32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return int(exit_code.value) == STILL_ACTIVE
    finally:
        k32.CloseHandle(handle)


def is_pid_alive(pid: int) -> bool:
    """Return True if process `pid` appears alive on macOS/Linux/Windows."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            return _is_pid_alive_windows(pid)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def read_lock_file(data_dir: str | Path) -> dict[str, Any] | None:
    lock_path = get_lock_path(data_dir)
    if not lock_path.exists():
        return None
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def write_lock_file(
    data_dir: str | Path,
    *,
    pid: int,
    host: str,
    port: int,
    launch_mode: str,
    instance_token: str,
    version: str = APP_VERSION,
) -> Path:
    """Atomically write `DATA_DIR/server.lock` with restrictive permissions (`0600` on POSIX)."""
    base = Path(data_dir).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    lock_path = get_lock_path(base)
    tmp_path = base / f"{LOCK_FILENAME}.tmp.{os.getpid()}.{threading.get_ident()}"
    payload = {
        "pid": int(pid),
        "host": str(host),
        "port": int(port),
        "data_dir": str(base),
        "launch_mode": str(launch_mode),
        "instance_token": str(instance_token),
        "version": str(version),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    raw = json.dumps(payload, ensure_ascii=False, indent=2)
    fd = os.open(str(tmp_path), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            fp.write(raw)
        if os.name == "posix":
            with contextlib.suppress(OSError):
                os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, lock_path)
        if os.name == "posix":
            with contextlib.suppress(OSError):
                os.chmod(lock_path, 0o600)
    except Exception:
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise
    return lock_path


def remove_lock_file(data_dir: str | Path, *, expected_pid: int | None = None) -> bool:
    """Remove `server.lock` if present (and owned by `expected_pid` when specified)."""
    lock_path = get_lock_path(data_dir)
    if not lock_path.exists():
        return False
    if expected_pid is not None:
        existing = read_lock_file(data_dir)
        if existing is not None:
            try:
                if int(existing.get("pid", -1)) != int(expected_pid):
                    return False
            except (TypeError, ValueError):
                pass
    try:
        lock_path.unlink()
        return True
    except OSError:
        return False


@contextlib.contextmanager
def acquire_init_lock(
    data_dir: str | Path,
    *,
    timeout: float = 5.0,
    stale_after: float = 15.0,
) -> Iterator[Path]:
    """Cross-platform atomic initialization lock (`O_CREAT | O_EXCL`) preventing startup races."""
    base = Path(data_dir).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    init_path = get_init_lock_path(base)
    deadline = time.monotonic() + max(0.2, timeout)
    acquired = False

    while True:
        try:
            fd = os.open(str(init_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                os.write(
                    fd,
                    json.dumps({"pid": os.getpid(), "ts": time.time()}).encode("utf-8"),
                )
            finally:
                os.close(fd)
            acquired = True
            break
        except FileExistsError:
            stale = False
            try:
                meta = json.loads(init_path.read_text(encoding="utf-8"))
                holder_pid = int(meta.get("pid", 0))
                holder_ts = float(meta.get("ts", 0.0))
                if not is_pid_alive(holder_pid) or (time.time() - holder_ts) > stale_after:
                    stale = True
            except Exception:
                try:
                    age = time.time() - init_path.stat().st_mtime
                    stale = age > stale_after
                except OSError:
                    stale = True

            if stale:
                with contextlib.suppress(OSError):
                    init_path.unlink()
                continue

            if time.monotonic() >= deadline:
                raise TimeoutError(f"获取启动初始化锁超时：{init_path}")
            time.sleep(0.05)

    try:
        yield init_path
    finally:
        if acquired:
            with contextlib.suppress(Exception):
                meta = json.loads(init_path.read_text(encoding="utf-8"))
                if int(meta.get("pid", -1)) == os.getpid():
                    init_path.unlink()


def fetch_health(host: str = "127.0.0.1", port: int = 8765, *, timeout: float = 0.8) -> dict[str, Any] | None:
    """Query `GET http://{host}:{port}/api/health` without using system HTTP proxies."""
    url = f"http://{host}:{int(port)}/api/health"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, dict) else None
    except Exception:
        return None


def probe_running_instance(
    data_dir: str | Path,
    *,
    health_timeout: float = 0.8,
    cleanup_stale: bool = True,
) -> dict[str, Any] | None:
    """Check `DATA_DIR/server.lock` and live `/api/health`; auto-clean stale/mismatched locks."""
    base = Path(data_dir).expanduser().resolve()
    lock_path = get_lock_path(base)
    if not lock_path.exists():
        return None

    lock = read_lock_file(base)
    if not lock:
        if cleanup_stale:
            remove_lock_file(base)
        return None

    try:
        pid = int(lock.get("pid", 0))
        port = int(lock.get("port", 0))
    except (TypeError, ValueError):
        if cleanup_stale:
            remove_lock_file(base)
        return None
    host = str(lock.get("host") or "127.0.0.1")
    if pid <= 0 or port <= 0 or port > 65535 or host not in {"127.0.0.1", "localhost"}:
        if cleanup_stale:
            remove_lock_file(base)
        return None

    if not is_pid_alive(pid):
        if cleanup_stale:
            remove_lock_file(base, expected_pid=pid)
        return None

    health = fetch_health(host, port, timeout=health_timeout)
    if not health or health.get("status") != "ok":
        if cleanup_stale:
            # Avoid nuking a freshly written lock while a live sibling process is still binding its port
            try:
                lock_age = time.time() - lock_path.stat().st_mtime
            except OSError:
                lock_age = 999.0
            if lock_age > 5.0:
                remove_lock_file(base, expected_pid=pid)
        return None

    try:
        health_pid = int(health.get("pid", -1))
    except (TypeError, ValueError):
        health_pid = -1
    health_data_dir_raw = str(health.get("data_dir") or "").strip()
    if health_pid != pid or not health_data_dir_raw:
        if cleanup_stale:
            remove_lock_file(base, expected_pid=pid)
        return None

    try:
        if Path(health_data_dir_raw).expanduser().resolve() != base:
            if cleanup_stale:
                remove_lock_file(base, expected_pid=pid)
            return None
    except OSError:
        if cleanup_stale:
            remove_lock_file(base, expected_pid=pid)
        return None

    return {
        "pid": pid,
        "host": host,
        "port": port,
        "url": f"http://{host}:{port}",
        "data_dir": str(base),
        "log_path": str(health.get("log_path") or get_log_path(base)),
        "launch_mode": str(health.get("launch_mode") or lock.get("launch_mode") or "unknown"),
        "version": str(health.get("version") or lock.get("version") or APP_VERSION),
        "can_shutdown": bool(health.get("can_shutdown", False)),
        "instance_token": str(lock.get("instance_token") or ""),
        "started_at": str(lock.get("started_at") or ""),
    }


def find_free_port(preferred_start: int, preferred_end: int) -> int:
    """Bind-probe and return the first free loopback port in range, falling back to ephemeral port."""
    for port in range(preferred_start, preferred_end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _terminate_pid_fallback(pid: int) -> None:
    if pid <= 0 or not is_pid_alive(pid):
        return
    if sys.platform == "win32":
        with contextlib.suppress(Exception):
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3.0,
                check=False,
            )
    else:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)


def request_graceful_shutdown(data_dir: str | Path, *, timeout: float = 5.0) -> dict[str, Any]:
    """Stop the running instance for `data_dir` via HTTP token shutdown with OS fallback."""
    base = Path(data_dir).expanduser().resolve()
    info = probe_running_instance(base)
    if not info:
        remove_lock_file(base)
        return {"stopped": False, "was_running": False, "detail": "未检测到正在运行的本地服务"}

    pid = int(info["pid"])
    host = str(info["host"])
    port = int(info["port"])
    token = str(info.get("instance_token") or "")

    http_accepted = False
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(
        f"http://{host}:{port}/api/runtime/shutdown",
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "X-PaperDiff-Token": token,
            "X-PaperDiff-Client": "cli",
        },
        method="POST",
    )
    try:
        with opener.open(req, timeout=2.0) as resp:
            http_accepted = resp.status == 200
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            return {
                "stopped": False,
                "was_running": True,
                "pid": pid,
                "port": port,
                "detail": "当前运行的是 macOS 桌面应用内置服务，请直接关闭 PaperDiff 桌面窗口退出。",
            }
    except Exception:
        pass

    deadline = time.monotonic() + max(1.0, timeout)
    while time.monotonic() < deadline:
        if not is_pid_alive(pid) and fetch_health(host, port, timeout=0.3) is None:
            remove_lock_file(base, expected_pid=pid)
            return {
                "stopped": True,
                "was_running": True,
                "pid": pid,
                "port": port,
                "method": "http" if http_accepted else "exit",
            }
        time.sleep(0.1)

    _terminate_pid_fallback(pid)
    wait_end = time.monotonic() + 2.0
    while time.monotonic() < wait_end:
        if not is_pid_alive(pid):
            break
        time.sleep(0.1)
    remove_lock_file(base, expected_pid=pid)
    return {
        "stopped": not is_pid_alive(pid),
        "was_running": True,
        "pid": pid,
        "port": port,
        "method": "fallback_terminate",
    }


def set_runtime_context(
    *,
    port: int,
    data_dir: str | Path,
    launch_mode: str,
    can_shutdown: bool,
    instance_token: str,
    host: str = "127.0.0.1",
) -> dict[str, Any]:
    """Register active server metadata so `/api/health` and `/api/runtime/shutdown` share one truth."""
    base = Path(data_dir).expanduser().resolve()
    with _CTX_LOCK:
        _RUNTIME_CONTEXT.update(
            {
                "pid": os.getpid(),
                "host": str(host),
                "port": int(port),
                "data_dir": str(base),
                "log_path": str(get_log_path(base)),
                "launch_mode": str(launch_mode),
                "can_shutdown": bool(can_shutdown),
                "instance_token": str(instance_token),
            }
        )
        return dict(_RUNTIME_CONTEXT)


def get_runtime_context() -> dict[str, Any]:
    with _CTX_LOCK:
        ctx = dict(_RUNTIME_CONTEXT)
    if not ctx.get("data_dir"):
        base = resolve_data_dir()
        ctx["data_dir"] = str(base)
        ctx["log_path"] = str(get_log_path(base))
    return ctx


def register_shutdown_callback(callback: Callable[[], None] | None) -> None:
    global _SHUTDOWN_CALLBACK
    with _CTX_LOCK:
        _SHUTDOWN_CALLBACK = callback


def trigger_shutdown_callback() -> bool:
    with _CTX_LOCK:
        cb = _SHUTDOWN_CALLBACK
    if cb is not None:
        cb()
        return True
    return False


# ---------------------------------------------------------------------------
# W2: Window Geometry Persistence & Multi-Monitor Clamping (AC-11)
# ---------------------------------------------------------------------------


def get_window_state_path(data_dir: str | Path) -> Path:
    return Path(data_dir).expanduser().resolve() / WINDOW_STATE_FILENAME


def load_window_state(data_dir: str | Path) -> dict[str, int | None] | None:
    """Safely load saved desktop window geometry; return None if missing or corrupt."""
    path = get_window_state_path(data_dir)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        w = int(raw["width"])
        h = int(raw["height"])
        if w <= 0 or h <= 0:
            return None
        x_val = raw.get("x")
        y_val = raw.get("y")
        x = int(x_val) if x_val is not None else None
        y = int(y_val) if y_val is not None else None
        return {"width": w, "height": h, "x": x, "y": y}
    except Exception:
        return None


def save_window_state(
    data_dir: str | Path,
    *,
    width: int,
    height: int,
    x: int | None = None,
    y: int | None = None,
) -> Path:
    """Atomically persist desktop window geometry to `DATA_DIR/window_state.json`."""
    base = Path(data_dir).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    dest = get_window_state_path(base)
    tmp = base / f"{WINDOW_STATE_FILENAME}.tmp.{os.getpid()}"
    payload: dict[str, Any] = {
        "width": int(width),
        "height": int(height),
        "x": int(x) if x is not None else None,
        "y": int(y) if y is not None else None,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, dest)
    return dest


def clamp_window_geometry(
    saved: dict[str, int | None] | None,
    screens: list[dict[str, int]] | None,
    *,
    default_size: tuple[int, int] = (1440, 900),
    min_size: tuple[int, int] = (1060, 680),
) -> dict[str, int | None]:
    """Clamp window dimensions and coordinates onto visible connected displays."""
    min_w, min_h = int(min_size[0]), int(min_size[1])
    def_w, def_h = int(default_size[0]), int(default_size[1])

    valid_screens = [
        {
            "x": int(s.get("x", 0)),
            "y": int(s.get("y", 0)),
            "width": int(s.get("width", 0)),
            "height": int(s.get("height", 0)),
        }
        for s in (screens or [])
        if int(s.get("width", 0)) > 0 and int(s.get("height", 0)) > 0
    ]
    primary = valid_screens[0] if valid_screens else None

    raw_w = int(saved["width"]) if (saved and saved.get("width")) else def_w
    raw_h = int(saved["height"]) if (saved and saved.get("height")) else def_h
    w = max(min_w, raw_w)
    h = max(min_h, raw_h)

    if primary is not None:
        max_w = max(min_w, primary["width"])
        max_h = max(min_h, primary["height"])
        w = min(w, max_w)
        h = min(h, max_h)

    if not saved or saved.get("x") is None or saved.get("y") is None:
        return {"width": w, "height": h, "x": None, "y": None}

    x = int(saved["x"])  # type: ignore[arg-type]
    y = int(saved["y"])  # type: ignore[arg-type]
    if not valid_screens:
        return {"width": w, "height": h, "x": x, "y": y}

    # Verify the window title bar region [x, x+w] x [y, y+80] intersects a connected screen by >= 200x40 px
    title_h = min(80, h)
    visible = False
    for scr in valid_screens:
        ix1 = max(x, scr["x"])
        iy1 = max(y, scr["y"])
        ix2 = min(x + w, scr["x"] + scr["width"])
        iy2 = min(y + title_h, scr["y"] + scr["height"])
        if (ix2 - ix1) >= 200 and (iy2 - iy1) >= 40:
            visible = True
            break

    if visible:
        return {"width": w, "height": h, "x": x, "y": y}

    # Disconnected monitor fallback: safely center on primary display
    assert primary is not None
    w = min(w, primary["width"])
    h = min(h, primary["height"])
    cx = primary["x"] + max(0, (primary["width"] - w) // 2)
    cy = primary["y"] + max(0, (primary["height"] - h) // 2)
    return {"width": w, "height": h, "x": cx, "y": cy}


# ---------------------------------------------------------------------------
# W2: CLI Path Launch & `paperdiff` Command Installer (AC-13, D-05 Option A)
# ---------------------------------------------------------------------------

CLI_SUPPORTED_FILE_EXTS = {".tex", ".ltx", ".docx", ".md", ".markdown", ".txt", ".zip"}


def validate_cli_target_path(raw_path: str) -> Path:
    """Pre-validate a local directory or supported file path before starting/contacting server."""
    cleaned = (raw_path or "").strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ('"', "'"):
        cleaned = cleaned[1:-1].strip()
    if not cleaned:
        raise ValueError("目标路径不能为空")
    target = Path(cleaned).expanduser().resolve(strict=False)
    if not target.exists():
        raise FileNotFoundError(f"目标路径不存在：{cleaned}")
    if target.is_dir():
        try:
            os.listdir(target)
        except OSError as exc:
            raise PermissionError(f"无权读取目录：{target}（{exc}）") from exc
        return target
    if not target.is_file():
        raise ValueError(f"目标既不是目录也不是普通文件：{target}")
    if target.suffix.lower() not in CLI_SUPPORTED_FILE_EXTS:
        raise ValueError(
            f"暂不支持直接打开该文件类型（{target.suffix or '无后缀'}）；支持 .tex/.ltx/.docx/.md/.txt/.zip"
        )
    try:
        with target.open("rb"):
            pass
    except OSError as exc:
        raise PermissionError(f"无权读取文件：{target}（{exc}）") from exc
    return target


def post_open_local_path(
    host: str,
    port: int,
    target_path: str | Path,
    *,
    timeout: float = 8.0,
) -> dict[str, Any]:
    """Call `POST /api/local/open-path` on the local PaperDiff backend without proxies."""
    url = f"http://{host}:{int(port)}/api/local/open-path"
    payload = json.dumps({"path": str(target_path)}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            err_body = json.loads(exc.read().decode("utf-8"))
            detail = str(err_body.get("detail") or err_body)
        except Exception:
            detail = str(exc)
        raise RuntimeError(detail or f"打开本地路径失败（HTTP {exc.code}）") from exc


def _cli_script_name() -> str:
    return "paperdiff.cmd" if sys.platform == "win32" else "paperdiff"


def get_default_cli_bin_dir() -> Path:
    if sys.platform == "win32":
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve(strict=False).parent
        local_app = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_app).expanduser() if local_app else (Path.home() / "AppData" / "Local")
        return base / "PaperDiff" / "bin"
    return Path.home() / ".local" / "bin"


def _is_dir_in_path(bin_dir: Path, path_env: str | None = None) -> bool:
    env_val = os.environ.get("PATH", "") if path_env is None else path_env
    resolved_bin = bin_dir.expanduser().resolve(strict=False)
    sep = ";" if (sys.platform == "win32" and ";" in env_val) else os.pathsep
    bin_norm = str(resolved_bin).rstrip("\\/").lower() if sys.platform == "win32" else str(resolved_bin)
    for entry in env_val.split(sep):
        cleaned = entry.strip().strip('"')
        if not cleaned:
            continue
        try:
            cand = Path(cleaned).expanduser().resolve(strict=False)
            if sys.platform == "win32":
                if str(cand).rstrip("\\/").lower() == bin_norm:
                    return True
            elif cand == resolved_bin:
                return True
        except OSError:
            continue
    return False


def _format_cli_path_hint(target_dir: Path) -> str:
    if sys.platform == "win32":
        return f'setx PATH "%PATH%;{target_dir}"'
    return f'export PATH="{target_dir}:$PATH"'


def get_cli_install_status(
    *,
    bin_dir: str | Path | None = None,
    path_env: str | None = None,
) -> dict[str, Any]:
    target_dir = Path(bin_dir).expanduser().resolve(strict=False) if bin_dir else get_default_cli_bin_dir()
    script_path = target_dir / _cli_script_name()
    installed = script_path.exists() and script_path.is_file()
    in_path = _is_dir_in_path(target_dir, path_env=path_env)
    path_hint = _format_cli_path_hint(target_dir)
    return {
        "installed": installed,
        "script_path": str(script_path),
        "bin_dir": str(target_dir),
        "in_path": in_path,
        "path_hint": path_hint,
    }


def _build_cli_wrapper_content(executable_target: str | Path | None = None) -> str:
    if sys.platform == "win32":
        if executable_target is not None:
            target_str = str(Path(executable_target).expanduser().resolve(strict=False))
            return f'@echo off\r\n"{target_str}" --open %*\r\n'
        if getattr(sys, "frozen", False):
            exe = str(Path(sys.executable).resolve(strict=False))
            return f'@echo off\r\n"{exe}" --open %*\r\n'
        launcher = str((Path(__file__).resolve().parent.parent / "launch_desktop.py").resolve(strict=False))
        py_exe = str(Path(sys.executable).resolve(strict=False))
        return f'@echo off\r\n"{py_exe}" "{launcher}" --daemon %*\r\n'
    if executable_target is not None:
        target_str = str(Path(executable_target).expanduser().resolve())
        return f'#!/bin/sh\nexec "{target_str}" --open "$@"\n'
    if getattr(sys, "frozen", False):
        exe = str(Path(sys.executable).resolve())
        return f'#!/bin/sh\nexec "{exe}" --open "$@"\n'
    launcher = str((Path(__file__).resolve().parent.parent / "launch_desktop.py").resolve())
    py_exe = str(Path(sys.executable).resolve())
    return f'#!/bin/sh\nexec "{py_exe}" "{launcher}" --daemon "$@"\n'


def install_cli_command(
    *,
    bin_dir: str | Path | None = None,
    executable_target: str | Path | None = None,
    path_env: str | None = None,
) -> dict[str, Any]:
    """Install executable `paperdiff` CLI wrapper (`paperdiff` on POSIX, `paperdiff.cmd` on Windows)."""
    target_dir = Path(bin_dir).expanduser().resolve(strict=False) if bin_dir else get_default_cli_bin_dir()
    script_path = target_dir / _cli_script_name()
    in_path = _is_dir_in_path(target_dir, path_env=path_env)
    path_hint = _format_cli_path_hint(target_dir)
    wrapper = _build_cli_wrapper_content(executable_target=executable_target)

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = target_dir / f".paperdiff.tmp.{os.getpid()}"
        tmp_path.write_text(wrapper, encoding="utf-8")
        if os.name == "posix" and sys.platform != "win32":
            os.chmod(tmp_path, 0o755)
        os.replace(tmp_path, script_path)
        if os.name == "posix" and sys.platform != "win32":
            os.chmod(script_path, 0o755)
        return {
            "installed": True,
            "script_path": str(script_path),
            "bin_dir": str(target_dir),
            "in_path": in_path,
            "path_hint": path_hint,
        }
    except OSError as exc:
        fallback_hint = "%LOCALAPPDATA%\\PaperDiff\\bin" if sys.platform == "win32" else "~/.local/bin"
        return {
            "installed": False,
            "script_path": str(script_path),
            "bin_dir": str(target_dir),
            "in_path": in_path,
            "path_hint": path_hint,
            "error": f"无权写入 {script_path}（{exc}），可改用用户目录 {fallback_hint} 或手动创建命令包装。",
        }


def uninstall_cli_command(*, bin_dir: str | Path | None = None) -> dict[str, Any]:
    target_dir = Path(bin_dir).expanduser().resolve(strict=False) if bin_dir else get_default_cli_bin_dir()
    script_path = target_dir / _cli_script_name()
    if not script_path.exists():
        return {"installed": False, "removed": False, "script_path": str(script_path)}
    try:
        script_path.unlink()
        return {"installed": False, "removed": True, "script_path": str(script_path)}
    except OSError as exc:
        return {"installed": True, "removed": False, "script_path": str(script_path), "error": str(exc)}
