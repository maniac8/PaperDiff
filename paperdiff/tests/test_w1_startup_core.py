"""Startup Optimization & Cross-Platform Web + macOS Launch Test Suite.

Covers behavioral assertions W1-T01 through W1-T14 mapped to W1-AC-01 through W1-AC-11.
"""
from __future__ import annotations

import json
import os
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

PAPERDIFF_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = PAPERDIFF_ROOT.parent
if str(PAPERDIFF_ROOT) not in sys.path:
    sys.path.insert(0, str(PAPERDIFF_ROOT))


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _start_mock_health_server(payload: dict) -> tuple[HTTPServer, int]:
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/api/health":
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):  # noqa: A002
            return

    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    port = int(srv.server_address[1])
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port


# ---------------------------------------------------------------------------
# Increment A: W1-T02 & W1-T03 (Cross-platform runtime_state lock & isolation)
# ---------------------------------------------------------------------------


def test_w1_t02_runtime_lock_lifecycle_and_stale_recovery(tmp_path: Path) -> None:
    """W1-T02: Cross-platform runtime_state.py lockfile, zero fcntl, stale lock self-healing < 2s."""
    from backend import runtime_state

    # 1. Must not unconditionally depend on POSIX-only fcntl
    source_text = Path(runtime_state.__file__).read_text(encoding="utf-8")
    assert "import fcntl" not in source_text

    data_dir = tmp_path / "app_data"
    data_dir.mkdir()

    # 2. Corrupt JSON lock is auto-cleaned within < 2s
    lock_path = runtime_state.get_lock_path(data_dir)
    lock_path.write_text("{corrupt json", encoding="utf-8")
    t0 = time.perf_counter()
    assert runtime_state.probe_running_instance(data_dir) is None
    assert (time.perf_counter() - t0) < 2.0
    assert not lock_path.exists()

    # 3. Dead PID lock is auto-cleaned within < 2s
    runtime_state.write_lock_file(
        data_dir,
        pid=9999999,
        host="127.0.0.1",
        port=_find_free_port(),
        launch_mode="web_daemon",
        instance_token="tok-dead",
        version="0.1.0",
    )
    if os.name == "posix":
        mode = stat.S_IMODE(lock_path.stat().st_mode)
        assert mode == 0o600
    t0 = time.perf_counter()
    assert runtime_state.probe_running_instance(data_dir) is None
    assert (time.perf_counter() - t0) < 2.0
    assert not lock_path.exists()

    # 4. Alive PID + mismatched data_dir in /api/health MUST NOT reuse and cleans stale lock
    other_dir = tmp_path / "other_data"
    other_dir.mkdir()
    srv_bad, port_bad = _start_mock_health_server(
        {
            "status": "ok",
            "app": "对稿 · PaperDiff",
            "version": "0.1.0",
            "pid": os.getpid(),
            "port": 0,
            "data_dir": str(other_dir.resolve()),
            "launch_mode": "web_daemon",
            "can_shutdown": True,
        }
    )
    try:
        runtime_state.write_lock_file(
            data_dir,
            pid=os.getpid(),
            host="127.0.0.1",
            port=port_bad,
            launch_mode="web_daemon",
            instance_token="tok-mismatch",
            version="0.1.0",
        )
        assert runtime_state.probe_running_instance(data_dir) is None
        assert not lock_path.exists()
    finally:
        srv_bad.shutdown()

    # 5. Alive PID + matching data_dir in /api/health -> returns reusable instance info
    srv_ok, port_ok = _start_mock_health_server(
        {
            "status": "ok",
            "app": "对稿 · PaperDiff",
            "version": "0.1.0",
            "pid": os.getpid(),
            "port": 0,
            "data_dir": str(data_dir.resolve()),
            "log_path": str(runtime_state.get_log_path(data_dir)),
            "launch_mode": "web_daemon",
            "can_shutdown": True,
        }
    )
    try:
        token = runtime_state.generate_instance_token()
        runtime_state.write_lock_file(
            data_dir,
            pid=os.getpid(),
            host="127.0.0.1",
            port=port_ok,
            launch_mode="web_daemon",
            instance_token=token,
            version="0.1.0",
        )
        info = runtime_state.probe_running_instance(data_dir)
        assert info is not None
        assert info["pid"] == os.getpid()
        assert info["port"] == port_ok
        assert info["url"] == f"http://127.0.0.1:{port_ok}"
        assert info["instance_token"] == token

        # Ownership-safe removal: wrong expected_pid MUST NOT delete lock
        assert runtime_state.remove_lock_file(data_dir, expected_pid=os.getpid() + 1) is False
        assert lock_path.exists()
        assert runtime_state.remove_lock_file(data_dir, expected_pid=os.getpid()) is True
        assert not lock_path.exists()
    finally:
        srv_ok.shutdown()

    # 6. Cross-platform init lock (O_CREAT|O_EXCL) recovers stale dead-PID lock and serializes
    init_lock = data_dir / runtime_state.INIT_LOCK_FILENAME
    init_lock.write_text(json.dumps({"pid": 9999999, "ts": time.time()}), encoding="utf-8")
    with runtime_state.acquire_init_lock(data_dir, timeout=2.0):
        assert init_lock.exists()
        content = json.loads(init_lock.read_text(encoding="utf-8"))
        assert content["pid"] == os.getpid()
    assert not init_lock.exists()


def test_w1_t03_isolated_data_dirs_do_not_interfere(tmp_path: Path) -> None:
    """W1-T03: Separate PAPERDIFF_DATA_DIR instances maintain independent locks and logs."""
    from backend import runtime_state

    dir_a = tmp_path / "iso_a"
    dir_b = tmp_path / "iso_b"
    dir_a.mkdir()
    dir_b.mkdir()

    srv_a, port_a = _start_mock_health_server(
        {
            "status": "ok",
            "version": "0.1.0",
            "pid": os.getpid(),
            "data_dir": str(dir_a.resolve()),
            "launch_mode": "web_daemon",
            "can_shutdown": True,
        }
    )
    srv_b, port_b = _start_mock_health_server(
        {
            "status": "ok",
            "version": "0.1.0",
            "pid": os.getpid(),
            "data_dir": str(dir_b.resolve()),
            "launch_mode": "web_daemon",
            "can_shutdown": True,
        }
    )
    try:
        runtime_state.write_lock_file(
            dir_a,
            pid=os.getpid(),
            host="127.0.0.1",
            port=port_a,
            launch_mode="web_daemon",
            instance_token="tok-a",
            version="0.1.0",
        )
        runtime_state.write_lock_file(
            dir_b,
            pid=os.getpid(),
            host="127.0.0.1",
            port=port_b,
            launch_mode="web_daemon",
            instance_token="tok-b",
            version="0.1.0",
        )
        info_a = runtime_state.probe_running_instance(dir_a)
        info_b = runtime_state.probe_running_instance(dir_b)
        assert info_a is not None and info_b is not None
        assert info_a["port"] == port_a and info_b["port"] == port_b
        assert info_a["port"] != info_b["port"]

        # Shutting down & removing lock B leaves A intact
        srv_b.shutdown()
        runtime_state.remove_lock_file(dir_b, expected_pid=os.getpid())
        assert runtime_state.probe_running_instance(dir_b) is None
        still_a = runtime_state.probe_running_instance(dir_a)
        assert still_a is not None and still_a["port"] == port_a
    finally:
        srv_a.shutdown()
        srv_b.shutdown()


# ---------------------------------------------------------------------------
# Increment B: W1-T04 & W1-T05 (Lazy jieba + enriched /api/health + CSRF shutdown)
# ---------------------------------------------------------------------------


def test_w1_t04_jieba_lazy_import_and_zero_drift(tmp_path: Path) -> None:
    """W1-T04: Importing backend.main + GET /api/projects must NOT import jieba; first Chinese diff loads it."""
    env = os.environ.copy()
    env["PAPERDIFF_DATA_DIR"] = str(tmp_path / "lazy_data")
    script = r"""
import json, sys
sys.path.insert(0, %r)
from fastapi.testclient import TestClient
import backend.main as main_mod
before_projects = "jieba" in sys.modules
with TestClient(main_mod.app) as client:
    r = client.get("/api/projects")
    assert r.status_code == 200
after_projects = "jieba" in sys.modules
from backend.analyzer import compare_documents
res = compare_documents(
    "稀疏注意力在长上下文中的推理误差达到 14.2%%。",
    "稀疏注意力在长上下文中的推理误差达到 15.8%%。",
    "markdown",
    "markdown",
)
after_diff = "jieba" in sys.modules
print(json.dumps({
    "before_projects": before_projects,
    "after_projects": after_projects,
    "after_diff": after_diff,
    "has_numeric_alert": any(a.get("category") == "number" for a in res.get("alerts", [])),
    "changed_blocks": res.get("summary", {}).get("modified_paragraphs", 0),
}))
""" % str(PAPERDIFF_ROOT)
    out = subprocess.check_output([sys.executable, "-c", script], env=env, text=True).strip()
    data = json.loads(out.splitlines()[-1])
    assert data["before_projects"] is False, "jieba must not be imported during backend.main startup"
    assert data["after_projects"] is False, "jieba must not be imported on homepage /api/projects"
    assert data["after_diff"] is True, "jieba should load lazily on first Chinese compare_documents()"
    assert data["has_numeric_alert"] is True
    assert data["changed_blocks"] >= 1


def test_w1_t05_health_contract_and_csrf_protected_shutdown(tmp_path: Path) -> None:
    """W1-T05: /api/health v0.1.0 metadata (no token leak) & POST /api/runtime/shutdown CSRF guard."""
    from fastapi.testclient import TestClient
    from backend import main as main_mod
    from backend import runtime_state

    token = runtime_state.generate_instance_token()
    triggered: list[bool] = []
    runtime_state.set_runtime_context(
        port=8765,
        data_dir=tmp_path,
        launch_mode="web_daemon",
        can_shutdown=True,
        instance_token=token,
    )
    runtime_state.register_shutdown_callback(lambda: triggered.append(True))

    client = TestClient(main_mod.app)
    try:
        # 1. Enriched /api/health contract (no instance_token leak!)
        h = client.get("/api/health")
        assert h.status_code == 200
        body = h.json()
        assert body["status"] == "ok"
        assert body["version"] == runtime_state.APP_VERSION
        assert body["pid"] == os.getpid()
        assert body["port"] == 8765
        assert Path(body["data_dir"]).resolve() == tmp_path.resolve()
        assert body["log_path"].endswith("server.log")
        assert body["launch_mode"] == "web_daemon"
        assert body["can_shutdown"] is True
        assert "instance_token" not in body and "token" not in body

        # 2. Cross-origin request MUST be rejected with 403
        r_evil = client.post(
            "/api/runtime/shutdown",
            headers={
                "Host": "127.0.0.1:8765",
                "Origin": "https://evil.example",
                "X-PaperDiff-Client": "web-ui",
            },
        )
        assert r_evil.status_code == 403
        assert not triggered

        # 3. Missing client header / missing token MUST be rejected with 403
        r_bare = client.post("/api/runtime/shutdown", headers={"Host": "127.0.0.1:8765"})
        assert r_bare.status_code == 403
        assert not triggered

        # 4. Desktop mode (can_shutdown=False) MUST reject with 409
        runtime_state.set_runtime_context(
            port=18765,
            data_dir=tmp_path,
            launch_mode="desktop",
            can_shutdown=False,
            instance_token=token,
        )
        r_desk = client.post(
            "/api/runtime/shutdown",
            headers={"X-PaperDiff-Token": token, "X-PaperDiff-Client": "cli"},
        )
        assert r_desk.status_code == 409
        assert not triggered

        # 5. Valid CLI token when can_shutdown=True -> 200 and callback fires
        runtime_state.set_runtime_context(
            port=8765,
            data_dir=tmp_path,
            launch_mode="web_daemon",
            can_shutdown=True,
            instance_token=token,
        )
        r_cli = client.post(
            "/api/runtime/shutdown",
            headers={"X-PaperDiff-Token": token, "X-PaperDiff-Client": "cli"},
        )
        assert r_cli.status_code == 200
        assert r_cli.json().get("stopping") is True
        deadline = time.monotonic() + 1.5
        while not triggered and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(triggered) == 1

        # 6. Same-origin web UI header also succeeds
        triggered.clear()
        r_web = client.post(
            "/api/runtime/shutdown",
            headers={
                "Host": "127.0.0.1:8765",
                "Origin": "http://127.0.0.1:8765",
                "X-PaperDiff-Client": "web-ui",
            },
        )
        assert r_web.status_code == 200
        assert r_web.json().get("stopping") is True
        deadline = time.monotonic() + 1.5
        while not triggered and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(triggered) == 1
    finally:
        runtime_state.register_shutdown_callback(None)
        runtime_state.set_runtime_context(
            port=0,
            data_dir=tmp_path,
            launch_mode="test",
            can_shutdown=False,
            instance_token="",
        )


# ---------------------------------------------------------------------------
# Increment C: W1-T06 & W1-T07 (Cross-platform Web --daemon/--status/--stop & scripts)
# ---------------------------------------------------------------------------


def test_w1_t06_web_daemon_single_instance_status_and_stop(tmp_path: Path) -> None:
    """W1-T06: Real launch_desktop.py --daemon parent exits 0, daemon survives, 2nd launch reuses PID/port, --stop cleans up."""
    from backend import runtime_state

    data_dir = tmp_path / "daemon_data"
    port = _find_free_port()
    env = os.environ.copy()
    env["PAPERDIFF_DATA_DIR"] = str(data_dir)
    env["PAPERDIFF_PORT"] = str(port)
    env["PAPERDIFF_NO_BROWSER"] = "1"
    env["PYTHONUTF8"] = "1"
    launcher = str(PAPERDIFF_ROOT / "launch_desktop.py")

    try:
        # 1. Start daemon; parent must exit 0 while background daemon keeps running
        r1 = subprocess.run(
            [sys.executable, launcher, "--daemon", "--json"],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert r1.returncode == 0, f"--daemon failed: stdout={r1.stdout} stderr={r1.stderr}"
        info1 = json.loads(r1.stdout.strip().splitlines()[-1])
        assert info1["running"] is True
        assert info1["reused"] is False
        assert info1["port"] == port
        pid1 = int(info1["pid"])
        assert runtime_state.is_pid_alive(pid1)

        log_path = runtime_state.get_log_path(data_dir)
        assert log_path.exists()

        # 2. Second --daemon on same DATA_DIR MUST reuse identical PID & port (no 2nd server)
        r2 = subprocess.run(
            [sys.executable, launcher, "--daemon", "--json"],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        assert r2.returncode == 0, f"2nd --daemon failed: {r2.stderr}"
        info2 = json.loads(r2.stdout.strip().splitlines()[-1])
        assert info2["running"] is True
        assert info2["reused"] is True
        assert int(info2["pid"]) == pid1
        assert int(info2["port"]) == port

        # 3. --status --json reports accurate running PID & port
        r_st = subprocess.run(
            [sys.executable, launcher, "--status", "--json"],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        assert r_st.returncode == 0
        st = json.loads(r_st.stdout.strip().splitlines()[-1])
        assert st["running"] is True
        assert int(st["pid"]) == pid1
        assert int(st["port"]) == port

        # 4. --stop --json gracefully exits daemon, releases port, removes lockfile
        r_stop = subprocess.run(
            [sys.executable, launcher, "--stop", "--json"],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        assert r_stop.returncode == 0
        stop_data = json.loads(r_stop.stdout.strip().splitlines()[-1])
        assert stop_data["stopped"] is True
        assert not runtime_state.get_lock_path(data_dir).exists()
        assert runtime_state.fetch_health("127.0.0.1", port, timeout=0.4) is None
    finally:
        runtime_state.request_graceful_shutdown(data_dir, timeout=3.0)


def test_w1_t07_windows_cross_platform_launcher_and_dual_scripts() -> None:
    """W1-T07: Windows detached flags/browser detection/PID probe & macOS/Windows scripts."""
    import launch_desktop
    from backend import runtime_state

    # 1. Windows detached process flags prevent lingering CMD black window
    win_kwargs = launch_desktop.build_daemon_popen_kwargs(platform_name="win32")
    flags = win_kwargs.get("creationflags", 0)
    assert flags & 0x00000008  # DETACHED_PROCESS
    assert flags & 0x00000200  # CREATE_NEW_PROCESS_GROUP
    assert flags & 0x08000000  # CREATE_NO_WINDOW
    assert "start_new_session" not in win_kwargs

    # 2. POSIX detached kwargs use start_new_session=True
    mac_kwargs = launch_desktop.build_daemon_popen_kwargs(platform_name="darwin")
    assert mac_kwargs.get("start_new_session") is True

    # 3. Windows browser candidates include Chrome and Edge paths
    win_cands = launch_desktop.get_app_browser_candidates(
        platform_name="win32",
        env={
            "PROGRAMFILES": r"C:\Program Files",
            "PROGRAMFILES(X86)": r"C:\Program Files (x86)",
            "LOCALAPPDATA": r"C:\Users\Alice\AppData\Local",
        },
    )
    joined = "\n".join(win_cands).lower()
    assert "chrome.exe" in joined and "msedge.exe" in joined

    # 4. Windows PID probe mock verifies STILL_ACTIVE (259) vs exited (0)
    class _FakeKernel32:
        def __init__(self, exit_code: int, handle: int = 42) -> None:
            self.exit_code = exit_code
            self.handle = handle
            self.closed = False

        def OpenProcess(self, _access, _inherit, _pid):  # noqa: N802
            return self.handle

        def GetExitCodeProcess(self, _h, ptr):  # noqa: N802
            ptr._obj.value = self.exit_code
            return 1

        def CloseHandle(self, _h):  # noqa: N802
            self.closed = True
            return 1

    k_alive = _FakeKernel32(259)
    assert runtime_state._is_pid_alive_windows(1234, kernel32=k_alive) is True
    assert k_alive.closed is True

    k_dead = _FakeKernel32(0)
    assert runtime_state._is_pid_alive_windows(1234, kernel32=k_dead) is False
    assert k_dead.closed is True

    # 5. Dual-platform launch & stop scripts exist, valid syntax, no hardcoded absolute paths
    mac_start = PROJECT_ROOT / "启动PaperDiff.command"
    mac_stop = PROJECT_ROOT / "停止PaperDiff.command"
    win_start = PROJECT_ROOT / "启动PaperDiff.bat"
    win_stop = PROJECT_ROOT / "停止PaperDiff.bat"
    for p in (mac_start, mac_stop, win_start, win_stop):
        assert p.exists(), f"Missing launcher script: {p}"
        txt = p.read_text(encoding="utf-8")
        assert "/Users/" not in txt, f"Hardcoded absolute path in {p}"

    assert "--daemon" in mac_start.read_text(encoding="utf-8")
    assert "--stop" in mac_stop.read_text(encoding="utf-8")
    assert "--daemon" in win_start.read_text(encoding="utf-8")
    assert "--stop" in win_stop.read_text(encoding="utf-8")

    # bash -n syntax validation & executable bit check on POSIX platforms
    if os.name == "posix":
        for sh_file in (mac_start, mac_stop):
            chk = subprocess.run(["bash", "-n", str(sh_file)], capture_output=True, text=True)
            assert chk.returncode == 0, f"Syntax error in {sh_file}: {chk.stderr}"
            assert os.access(sh_file, os.X_OK), f"{sh_file} must be executable"


# ---------------------------------------------------------------------------
# Increment D: W1-T08 & W1-T09 (Desktop Splash-First, reuse ownership, open_in_browser)
# ---------------------------------------------------------------------------


def test_w1_t08_desktop_splash_first_reuse_ownership_and_timeout_card(tmp_path: Path) -> None:
    """W1-T08: Splash HTML self-contained, reuse external service without killing on exit, timeout diagnostic card."""
    import desktop_app
    from backend import runtime_state

    # 1. Self-contained Splash HTML: zero external http/https links, supports light/sepia/dark & error hooks
    log_path = runtime_state.get_log_path(tmp_path)
    splash = desktop_app.build_splash_html(str(log_path))
    assert "http://" not in splash and "https://" not in splash
    assert "paperdiff_theme" in splash
    assert "__paperdiffSplashError" in splash
    assert "retry_boot" in splash and "open_logs_dir" in splash

    # 2. Reuse existing healthy same-DATA_DIR service -> owns_server=False & shutdown does NOT stop external service
    ext_srv, ext_port = _start_mock_health_server(
        {
            "status": "ok",
            "app": "对稿 · PaperDiff",
            "version": "0.1.0",
            "pid": os.getpid(),
            "port": 0,
            "data_dir": str(tmp_path.resolve()),
            "log_path": str(log_path),
            "launch_mode": "web_daemon",
            "can_shutdown": True,
        }
    )
    try:
        runtime_state.write_lock_file(
            tmp_path,
            pid=os.getpid(),
            host="127.0.0.1",
            port=ext_port,
            launch_mode="web_daemon",
            instance_token="ext-tok",
            version="0.1.0",
        )

        class _FakeWindow:
            def __init__(self) -> None:
                self.loaded_urls: list[str] = []
                self.eval_scripts: list[str] = []

            def load_url(self, u: str) -> None:
                self.loaded_urls.append(u)

            def evaluate_js(self, js: str) -> None:
                self.eval_scripts.append(js)

        win = _FakeWindow()
        bridge = desktop_app.DesktopBridge()
        ctrl = desktop_app.DesktopBootstrapController(data_dir=tmp_path, bridge=bridge)
        ctrl.boot_sync(win)
        assert ctrl.owns_server is False
        assert win.loaded_urls == [f"http://127.0.0.1:{ext_port}"]
        assert bridge.active_url == f"http://127.0.0.1:{ext_port}"

        # Closing desktop controller must NOT delete external lock or kill external server
        ctrl.shutdown()
        assert runtime_state.get_lock_path(tmp_path).exists()
        assert runtime_state.fetch_health("127.0.0.1", ext_port, timeout=0.5) is not None
    finally:
        ext_srv.shutdown()
        runtime_state.remove_lock_file(tmp_path)

    # 3. Boot timeout/failure -> evaluates Chinese diagnostic error card with server.log path
    win_err = _FakeWindow()
    bridge_err = desktop_app.DesktopBridge()

    class _FailingServer:
        def __init__(self, *_a, **_kw) -> None:
            self.stopped = False

        def start(self) -> None:
            raise RuntimeError("模拟本地端口绑定失败")

        def stop(self) -> None:
            self.stopped = True

    ctrl_err = desktop_app.DesktopBootstrapController(
        data_dir=tmp_path,
        bridge=bridge_err,
        server_factory=_FailingServer,
        boot_timeout=0.3,
    )
    ctrl_err.boot_sync(win_err)
    assert not win_err.loaded_urls
    assert len(win_err.eval_scripts) == 1
    js_call = win_err.eval_scripts[0]
    assert "__paperdiffSplashError" in js_call
    assert "模拟本地端口绑定失败" in js_call
    assert "server.log" in js_call


def test_w1_t09_desktop_bridge_open_in_browser_redirect_guard() -> None:
    """W1-T09: DesktopBridge.open_in_browser blocks external/protocol URLs and forwards safe relative paths."""
    import desktop_app

    opened: list[str] = []
    bridge = desktop_app.DesktopBridge(open_url_fn=lambda u: opened.append(u) or True)
    bridge.set_active_url("http://127.0.0.1:18765")

    # Blocked dangerous URLs
    for bad in ("http://evil.example/x", "https://evil.example", "//evil.example/path", "javascript:alert(1)", "file:///etc/passwd"):
        res = bridge.open_in_browser(bad)
        assert res.get("opened") is False, f"Must reject {bad}"
    assert opened == []

    # Allowed relative paths
    r1 = bridge.open_in_browser("/")
    assert r1.get("opened") is True and r1.get("url") == "http://127.0.0.1:18765/"
    r2 = bridge.open_in_browser("/?project=3&file=sections%2Fintro.tex")
    assert r2.get("opened") is True and r2.get("url") == "http://127.0.0.1:18765/?project=3&file=sections%2Fintro.tex"
    assert opened == [
        "http://127.0.0.1:18765/",
        "http://127.0.0.1:18765/?project=3&file=sections%2Fintro.tex",
    ]


# ---------------------------------------------------------------------------
# Increment E: W1-T11, W1-T12, W1-T13 (Real Headless Chrome CDP E2E + 3-theme WCAG)
# ---------------------------------------------------------------------------


def test_w1_t11_t12_t13_pwa_splash_topbar_controls_and_context_handoff_cdp(tmp_path: Path) -> None:
    """W1-T11/T12/T13: Real daemon + compiled SPA + Headless Chrome CDP verification."""
    import shutil
    import tempfile
    from backend import runtime_state
    from backend.export.pdf_exporter import find_local_chrome
    from tests.test_performance_benchmark import _MiniCDP

    chrome = find_local_chrome()
    if not chrome:
        pytest.skip("Local Chrome not found for CDP E2E test")

    data_dir = tmp_path / "cdp_w1_data"
    paper_dir = tmp_path / "sample_paper"
    paper_dir.mkdir()
    (paper_dir / "v1.md").write_text("# 引言\n\n这是用于 W1 启动体验验收的测试段落。\n", encoding="utf-8")

    port = _find_free_port()
    cdp_port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    env = os.environ.copy()
    env["PAPERDIFF_DATA_DIR"] = str(data_dir)
    env["PAPERDIFF_PORT"] = str(port)
    env["PAPERDIFF_NO_BROWSER"] = "1"
    launcher = str(PAPERDIFF_ROOT / "launch_desktop.py")

    r_start = subprocess.run(
        [sys.executable, launcher, "--daemon", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert r_start.returncode == 0, f"Daemon start failed: {r_start.stdout} {r_start.stderr}"

    chrome_proc = None
    cdp = None
    user_dir = tempfile.mkdtemp(prefix="pd_w1_cdp_")
    try:
        # --- W1-T11: Raw HTML splash, PWA manifest & PNG icons ---
        with opener.open(f"{base_url}/", timeout=5.0) as r:
            raw_html = r.read().decode("utf-8")
            assert r.status == 200
            assert 'id="pd-boot-splash"' in raw_html
            assert 'href="/manifest.webmanifest"' in raw_html

        with opener.open(f"{base_url}/manifest.webmanifest", timeout=5.0) as r:
            assert r.status == 200
            manifest = json.loads(r.read().decode("utf-8"))
            assert manifest["display"] == "standalone"
            assert manifest["start_url"] == "/"
            assert "对稿" in manifest["name"]
            sizes = {ic.get("sizes") for ic in manifest.get("icons", [])}
            assert "192x192" in sizes and "512x512" in sizes

        for icon_path in ("/icon-192.png", "/icon-512.png"):
            with opener.open(f"{base_url}{icon_path}", timeout=5.0) as r:
                raw_png = r.read()
                assert r.status == 200 and raw_png[:4] == b"\x89PNG"

        # Seed a local-folder project for W1-T13 context handoff & W1-T12 draft-dirty edit
        req_proj = urllib.request.Request(
            f"{base_url}/api/projects",
            data=json.dumps(
                {
                    "name": "W1 CDP Local Paper",
                    "project_mode": "local_folder",
                    "local_root_path": str(paper_dir),
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with opener.open(req_proj, timeout=8.0) as r:
            proj = json.loads(r.read().decode("utf-8"))
            pid = int(proj["id"])

        chrome_proc = subprocess.Popen(
            [
                chrome,
                "--headless=new",
                f"--remote-debugging-port={cdp_port}",
                f"--user-data-dir={user_dir}",
                "--window-size=1440,900",
                "--no-first-run",
                "--disable-default-apps",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ws_url = None
        for _ in range(50):
            try:
                with opener.open(f"http://127.0.0.1:{cdp_port}/json", timeout=1.0) as r:
                    tabs = json.loads(r.read().decode("utf-8"))
                    if tabs and tabs[0].get("webSocketDebuggerUrl"):
                        ws_url = tabs[0]["webSocketDebuggerUrl"]
                        break
            except Exception:
                time.sleep(0.15)
        assert ws_url, "Headless Chrome CDP websocket not ready"

        cdp = _MiniCDP(ws_url)
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")

        def eval_js(expr: str) -> object:
            res = cdp.send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
            if "exceptionDetails" in res:
                raise AssertionError(f"JS exception: {res['exceptionDetails']}")
            return res.get("result", {}).get("value")

        def wait_for(expr: str, timeout: float = 8.0) -> object:
            end = time.monotonic() + timeout
            last_err: Exception | None = None
            while time.monotonic() < end:
                try:
                    val = eval_js(expr)
                    if val:
                        return val
                    last_err = None
                except AssertionError as exc:
                    # Tolerate transient mid-navigation DOM states (e.g. null document.body)
                    last_err = exc
                time.sleep(0.12)
            if last_err is not None:
                raise AssertionError(f"Timeout waiting for: {expr} (last error: {last_err})") from last_err
            raise AssertionError(f"Timeout waiting for: {expr}")

        # 1. Load homepage and verify splash dismissed + zero errors + Web status pill present
        cdp.send("Page.navigate", {"url": f"{base_url}/"})
        wait_for("document.querySelector('[data-runtime-status-pill]') !== null")
        wait_for("document.getElementById('pd-boot-splash') === null")
        pill_text = str(eval_js("document.querySelector('[data-runtime-status-pill]').textContent"))
        assert f":{port}" in pill_text
        assert eval_js("document.querySelector('[data-runtime-open-browser]') === null") is True

        # 2. Verify 3-theme WCAG >= 4.5 contrast for RuntimeControl pill, popover & stop button
        eval_js("document.querySelector('[data-runtime-status-pill]').click()")
        wait_for("document.querySelector('[data-runtime-popover]') !== null")
        for theme_name in ("light", "sepia", "dark"):
            eval_js(f"document.documentElement.dataset.theme = '{theme_name}'")
            # Wait past Tailwind's 150ms transition-colors duration so computed colors settle
            time.sleep(0.35)
            eval_js(
                """(() => {
                  const pill = document.querySelector('[data-runtime-status-pill]');
                  if (pill && typeof pill.getAnimations === 'function') {
                    pill.getAnimations().forEach((a) => a.finish());
                  }
                  return true;
                })()"""
            )
            ratios = eval_js(
                """(() => {
                  const parseRgb = (s) => {
                    const m = (s || '').match(/\\d+/g);
                    return m ? m.slice(0, 3).map(Number) : [255, 255, 255];
                  };
                  const lum = ([r, g, b]) => {
                    const a = [r, g, b].map((v) => {
                      const c = v / 255;
                      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
                    });
                    return 0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2];
                  };
                  const contrast = (el) => {
                    const cs = getComputedStyle(el);
                    const l1 = lum(parseRgb(cs.color));
                    const l2 = lum(parseRgb(cs.backgroundColor));
                    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
                  };
                  const pill = document.querySelector('[data-runtime-status-pill]');
                  const pop = document.querySelector('[data-runtime-popover]');
                  const btn = document.querySelector('[data-runtime-stop-btn]');
                  return { pill: contrast(pill), pop: contrast(pop), btn: contrast(btn) };
                })()"""
            )
            assert ratios["pill"] >= 4.5, f"{theme_name} pill contrast too low: {ratios}"
            assert ratios["pop"] >= 4.5, f"{theme_name} popover contrast too low: {ratios}"
            assert ratios["btn"] >= 4.5, f"{theme_name} stop btn contrast too low: {ratios}"
        eval_js("document.documentElement.dataset.theme = 'light'")

        # --- W1-T13: Desktop bridge mode + `?project=&file=` direct handoff ---
        script_id = cdp.send(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                  window.__openedBrowserPaths = [];
                  window.pywebview = {
                    api: {
                      open_in_browser: (rel) => {
                        window.__openedBrowserPaths.push(rel);
                        return Promise.resolve({ opened: true, url: 'http://127.0.0.1' + rel });
                      }
                    }
                  };
                """
            },
        )["identifier"]
        cdp.send("Page.navigate", {"url": f"{base_url}/?project={pid}&file=v1.md"})
        wait_for("(document.body && document.body.innerText || '').includes('W1 启动体验验收的测试段落')")
        wait_for("document.querySelector('[data-runtime-open-browser]') !== null")
        assert eval_js("document.querySelector('[data-runtime-status-pill]') === null") is True
        eval_js("document.querySelector('[data-runtime-open-browser]').click()")
        wait_for("window.__openedBrowserPaths && window.__openedBrowserPaths.length === 1")
        handed = eval_js("window.__openedBrowserPaths[0]")
        assert handed == f"/?project={pid}&file=v1.md"

        # Remove desktop stub and reload in pure Web mode on the same local project to test W1-T12 draft-protected stop
        cdp.send("Page.removeScriptToEvaluateOnNewDocument", {"identifier": script_id})
        cdp.send("Page.navigate", {"url": f"{base_url}/?project={pid}&file=v1.md"})
        wait_for("(document.body && document.body.innerText || '').includes('W1 启动体验验收的测试段落')")
        wait_for("document.querySelector('[data-runtime-status-pill]') !== null")

        # Trigger an inline paragraph edit so Draft Dock has 1 unsaved edit
        eval_js(
            """(() => {
              const els = Array.from(document.querySelectorAll('p'));
              const target = els.find((el) => (el.textContent || '').includes('W1 启动体验验收的测试段落'));
              if (target) target.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
            })()"""
        )
        wait_for("document.querySelector('textarea') !== null")
        eval_js(
            """(() => {
              const ta = document.querySelector('textarea');
              const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
              setter.call(ta, '这是已修改但未落盘的暂存草稿。');
              ta.dispatchEvent(new Event('input', { bubbles: true }));
            })()"""
        )
        eval_js(
            """(() => {
              const btns = Array.from(document.querySelectorAll('button'));
              const ok = btns.find((b) => (b.textContent || '').includes('暂存'));
              if (ok) {
                ok.click();
              } else {
                const ta = document.querySelector('textarea');
                if (ta) ta.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, bubbles: true }));
              }
            })()"""
        )
        wait_for("(document.body && document.body.innerText || '').includes('保存到本地')")

        # Click Web status pill -> Stop -> MUST show draft protection confirmation modal!
        eval_js("document.querySelector('[data-runtime-status-pill]').click()")
        wait_for("document.querySelector('[data-runtime-stop-btn]') !== null")
        eval_js("document.querySelector('[data-runtime-stop-btn]').click()")
        wait_for("document.querySelector('[data-runtime-stop-confirm]') !== null")

        # Cancel keeps backend alive
        eval_js("document.querySelector('[data-runtime-stop-cancel]').click()")
        wait_for("document.querySelector('[data-runtime-stop-confirm]') === null")
        assert runtime_state.fetch_health("127.0.0.1", port, timeout=1.0) is not None

        # Confirm stop -> renders static stopped screen, backend exits & lockfile removed
        eval_js("document.querySelector('[data-runtime-status-pill]').click()")
        wait_for("document.querySelector('[data-runtime-stop-btn]') !== null")
        eval_js("document.querySelector('[data-runtime-stop-btn]').click()")
        wait_for("document.querySelector('[data-runtime-stop-confirm-btn]') !== null")
        eval_js("document.querySelector('[data-runtime-stop-confirm-btn]').click()")
        wait_for("document.querySelector('[data-runtime-stopped-screen]') !== null")
        assert "本地服务已停止" in str(eval_js("document.querySelector('[data-runtime-stopped-screen]').textContent"))

        # Wait up to 4s for daemon to exit and remove server.lock
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            if runtime_state.fetch_health("127.0.0.1", port, timeout=0.3) is None and not runtime_state.get_lock_path(data_dir).exists():
                break
            time.sleep(0.15)
        assert runtime_state.fetch_health("127.0.0.1", port, timeout=0.3) is None
        assert not runtime_state.get_lock_path(data_dir).exists()
    finally:
        if cdp is not None:
            cdp.close()
        if chrome_proc is not None:
            chrome_proc.terminate()
            try:
                chrome_proc.wait(timeout=3)
            except Exception:
                chrome_proc.kill()
        shutil.rmtree(user_dir, ignore_errors=True)
        runtime_state.request_graceful_shutdown(data_dir, timeout=3.0)
