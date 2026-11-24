"""Window Geometry Persistence, Workspace Resume & CLI Path Launch Test Suite.

Covers behavioral assertions W2-T01 through W2-T09 mapped to W2-AC-01 through W2-AC-04.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import stat
import subprocess
import sys
import time
import urllib.request
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


def _sha256_tree(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# ---------------------------------------------------------------------------
# Increment A: W2-T01 & W2-T02 (Window geometry persistence & screen clamping)
# ---------------------------------------------------------------------------


def test_w2_t01_window_geometry_persistence_and_screen_clamping(tmp_path: Path) -> None:
    """W2-T01: Persist window_state.json, preserve valid coordinates, clamp min/oversize/disconnected monitor."""
    from backend import runtime_state

    primary_only = [{"x": 0, "y": 0, "width": 1728, "height": 1117}]
    dual_screens = [
        {"x": 0, "y": 0, "width": 1728, "height": 1117},
        {"x": 1728, "y": 0, "width": 2560, "height": 1440},
    ]

    # 1. Missing or corrupt file falls back cleanly to default (1440, 900) centered
    assert runtime_state.load_window_state(tmp_path) is None
    g_def = runtime_state.clamp_window_geometry(None, primary_only)
    assert g_def["width"] == 1440 and g_def["height"] == 900
    assert g_def["x"] is None and g_def["y"] is None

    state_path = runtime_state.get_window_state_path(tmp_path)
    state_path.write_text("{broken json", encoding="utf-8")
    assert runtime_state.load_window_state(tmp_path) is None

    # 2. Save & reload valid custom geometry within primary screen
    runtime_state.save_window_state(tmp_path, width=1280, height=820, x=120, y=80)
    loaded = runtime_state.load_window_state(tmp_path)
    assert loaded is not None
    assert (loaded["width"], loaded["height"], loaded["x"], loaded["y"]) == (1280, 820, 120, 80)
    g_ok = runtime_state.clamp_window_geometry(loaded, primary_only)
    assert (g_ok["width"], g_ok["height"], g_ok["x"], g_ok["y"]) == (1280, 820, 120, 80)

    # 3. Below minimum size clamped up to (1060, 680)
    g_min = runtime_state.clamp_window_geometry({"width": 400, "height": 300, "x": 50, "y": 50}, primary_only)
    assert g_min["width"] == 1060 and g_min["height"] == 680

    # 4. External 4K monitor coordinates valid while connected, safely clamped back to primary when disconnected!
    ext_saved = {"width": 1600, "height": 1000, "x": 2200, "y": 140}
    g_dual = runtime_state.clamp_window_geometry(ext_saved, dual_screens)
    assert (g_dual["x"], g_dual["y"]) == (2200, 140)

    g_unplugged = runtime_state.clamp_window_geometry(ext_saved, primary_only)
    assert g_unplugged["width"] <= 1728 and g_unplugged["height"] <= 1117
    assert g_unplugged["x"] is not None and 0 <= g_unplugged["x"] < 1728
    assert g_unplugged["y"] is not None and 0 <= g_unplugged["y"] < 1117


def test_w2_t02_desktop_app_geometry_restore_and_closing_persist(tmp_path: Path) -> None:
    """W2-T02: desktop_app resolves clamped initial geometry and persists safely on window close."""
    import desktop_app
    from backend import runtime_state

    runtime_state.save_window_state(tmp_path, width=1310, height=840, x=90, y=60)
    geom = desktop_app.resolve_initial_window_geometry(
        tmp_path,
        screens=[{"x": 0, "y": 0, "width": 1600, "height": 1000}],
    )
    assert (geom["width"], geom["height"], geom["x"], geom["y"]) == (1310, 840, 90, 60)

    class _FakeWin:
        width = 1220
        height = 790
        x = 150
        y = 110

    assert desktop_app.persist_window_geometry(tmp_path, _FakeWin()) is True
    saved = runtime_state.load_window_state(tmp_path)
    assert saved is not None
    assert (saved["width"], saved["height"], saved["x"], saved["y"]) == (1220, 790, 150, 110)

    # Unavailable/broken window attributes must not raise
    assert desktop_app.persist_window_geometry(tmp_path, object()) is False


# ---------------------------------------------------------------------------
# Increment C: W2-T04 (POST /api/local/open-path idempotent readonly bind)
# ---------------------------------------------------------------------------


def test_w2_t04_api_local_open_path_idempotent_readonly_and_errors(tmp_path: Path, monkeypatch) -> None:
    """W2-T04: POST /api/local/open-path binds unbound dirs read-only, reuses existing/deepest ancestor, rejects bad paths."""
    from fastapi.testclient import TestClient
    from backend import database
    from backend.main import app

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "w2_t04.db")
    database.init_db()

    paper_dir = tmp_path / "transformer_paper"
    sub_dir = paper_dir / "sections"
    sub_dir.mkdir(parents=True)
    (paper_dir / "main.tex").write_text(r"\section{Intro}" + "\nHello.\n", encoding="utf-8")
    (sub_dir / "method.tex").write_text(r"\section{Method}" + "\nDetails.\n", encoding="utf-8")
    (paper_dir / "fig.png").write_bytes(b"\x89PNG\r\n\x1a\nFAKE")

    standalone_dir = tmp_path / "single_draft_dir"
    standalone_dir.mkdir()
    standalone_md = standalone_dir / "notes.md"
    standalone_md.write_text("# Notes\n\nBody.\n", encoding="utf-8")

    symlink_alias = tmp_path / "transformer_link"
    has_symlink = False
    try:
        os.symlink(paper_dir, symlink_alias)
        has_symlink = True
    except OSError:
        has_symlink = False

    orig_paper_hashes = _sha256_tree(paper_dir)
    orig_standalone_hashes = _sha256_tree(standalone_dir)

    with TestClient(app) as client:
        # 1. Unbound directory -> creates read-only local_folder project
        r1 = client.post("/api/local/open-path", json={"path": str(paper_dir)})
        assert r1.status_code == 200, r1.text
        d1 = r1.json()
        assert d1["created"] is True
        assert d1["project_name"] == "transformer_paper"
        assert d1["rel_path"] is None
        assert d1["handoff_path"] == f"/?project={d1['project_id']}"
        pid_paper = d1["project_id"]

        # 2. Repeat via symlink alias (if supported) or trailing separator -> idempotent reuse (created=False)
        repeat_target = (str(symlink_alias) if has_symlink else str(paper_dir)) + os.sep
        r2 = client.post("/api/local/open-path", json={"path": repeat_target})
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["created"] is False
        assert d2["project_id"] == pid_paper

        # 3. Supported file inside already-bound dir -> reuses ancestor project & returns rel_path
        r3 = client.post("/api/local/open-path", json={"path": str(sub_dir / "method.tex")})
        assert r3.status_code == 200
        d3 = r3.json()
        assert d3["created"] is False
        assert d3["project_id"] == pid_paper
        assert d3["rel_path"] == "sections/method.tex"
        assert d3["handoff_path"] == f"/?project={pid_paper}&file=sections%2Fmethod.tex"

        # 4. Supported file in an unbound dir -> binds parent dir read-only & points to file
        r4 = client.post("/api/local/open-path", json={"path": str(standalone_md)})
        assert r4.status_code == 200
        d4 = r4.json()
        assert d4["created"] is True
        assert d4["project_name"] == "single_draft_dir"
        assert d4["rel_path"] == "notes.md"
        assert d4["handoff_path"] == f"/?project={d4['project_id']}&file=notes.md"

        before_proj_count = len(client.get("/api/projects").json())

        # 5. Missing path -> 404 PATH_NOT_FOUND, unsupported file -> 422 UNSUPPORTED_FILE_TYPE, zero orphan projects
        r_miss = client.post("/api/local/open-path", json={"path": str(tmp_path / "does_not_exist")})
        assert r_miss.status_code == 404
        assert r_miss.json().get("code") == "PATH_NOT_FOUND"

        r_img = client.post("/api/local/open-path", json={"path": str(paper_dir / "fig.png")})
        assert r_img.status_code == 422
        assert r_img.json().get("code") == "UNSUPPORTED_FILE_TYPE"

        assert len(client.get("/api/projects").json()) == before_proj_count

    # Strict read-only disk invariance
    assert _sha256_tree(paper_dir) == orig_paper_hashes
    assert _sha256_tree(standalone_dir) == orig_standalone_hashes


# ---------------------------------------------------------------------------
# Increment D: W2-T05 & W2-T06 (CLI path launch & install/uninstall command)
# ---------------------------------------------------------------------------


def test_w2_t05_cli_path_launch_reuse_readonly_and_bad_path_exit(tmp_path: Path) -> None:
    """W2-T05: launch_desktop.py <path> auto-starts/reuses daemon, opens dir/file read-only, exits 1 on bad path."""
    from backend import runtime_state

    data_dir = tmp_path / "cli_data"
    paper_dir = tmp_path / "cli_paper"
    paper_dir.mkdir()
    doc_md = paper_dir / "manuscript.md"
    doc_md.write_text("# Abstract\n\nCLI path launch test.\n", encoding="utf-8")
    orig_hashes = _sha256_tree(paper_dir)

    port = _find_free_port()
    env = os.environ.copy()
    env["PAPERDIFF_DATA_DIR"] = str(data_dir)
    env["PAPERDIFF_PORT"] = str(port)
    env["PAPERDIFF_NO_BROWSER"] = "1"
    env["PYTHONUTF8"] = "1"
    launcher = str(PAPERDIFF_ROOT / "launch_desktop.py")

    try:
        # 1. Invalid / nonexistent path -> exits non-zero (1) with Chinese error on stderr, no server/projects polluted
        r_bad = subprocess.run(
            [sys.executable, launcher, str(tmp_path / "no_such_dir"), "--daemon"],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        assert r_bad.returncode == 1
        assert "不存在" in (r_bad.stderr + r_bad.stdout)

        # 2. Valid directory -> starts daemon, creates read-only local binding, returns handoff_path
        r_dir = subprocess.run(
            [sys.executable, launcher, str(paper_dir), "--daemon", "--json"],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert r_dir.returncode == 0, f"CLI dir launch failed: {r_dir.stdout} {r_dir.stderr}"
        d_dir = json.loads(r_dir.stdout.strip().splitlines()[-1])
        assert d_dir["running"] is True
        assert d_dir["created"] is True
        assert d_dir["handoff_path"] == f"/?project={d_dir['project_id']}"
        assert d_dir["target_url"] == f"http://127.0.0.1:{port}/?project={d_dir['project_id']}"
        pid1 = int(d_dir["pid"])

        # 3. Valid file inside same dir -> reuses identical daemon PID & project, returns &file=manuscript.md
        r_file = subprocess.run(
            [sys.executable, launcher, str(doc_md), "--daemon", "--json"],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        assert r_file.returncode == 0, f"CLI file launch failed: {r_file.stdout} {r_file.stderr}"
        d_file = json.loads(r_file.stdout.strip().splitlines()[-1])
        assert int(d_file["pid"]) == pid1
        assert d_file["reused"] is True
        assert d_file["created"] is False
        assert d_file["project_id"] == d_dir["project_id"]
        assert d_file["rel_path"] == "manuscript.md"
        assert d_file["handoff_path"] == f"/?project={d_dir['project_id']}&file=manuscript.md"

        # 4. Disk files 100% untouched
        assert _sha256_tree(paper_dir) == orig_hashes
    finally:
        runtime_state.request_graceful_shutdown(data_dir, timeout=4.0)


def test_w2_t06_cli_installer_uninstaller_and_readonly_fallback(tmp_path: Path) -> None:
    """W2-T06: install_cli_command creates 0755 wrapper, reports PATH hint, uninstalls cleanly, handles read-only dir."""
    import desktop_app
    from backend import runtime_state

    bin_dir = tmp_path / ".local" / "bin"
    other_path = f"/usr/bin{os.pathsep}/bin"

    # 1. Initially not installed
    st0 = runtime_state.get_cli_install_status(bin_dir=bin_dir, path_env=other_path)
    assert st0["installed"] is False
    assert st0["in_path"] is False

    # 2. Install into bin_dir -> executable script + PATH hint since bin_dir not in path_env
    res_in = runtime_state.install_cli_command(bin_dir=bin_dir, path_env=other_path)
    assert res_in["installed"] is True
    script_path = Path(res_in["script_path"])
    assert script_path.exists()
    if os.name == "posix":
        assert stat.S_IMODE(script_path.stat().st_mode) & 0o111
    else:
        assert script_path.name == "paperdiff.cmd"
    assert res_in["in_path"] is False
    assert "PATH" in res_in["path_hint"]

    # When bin_dir IS in PATH -> in_path=True
    st1 = runtime_state.get_cli_install_status(bin_dir=bin_dir, path_env=f"{bin_dir}{os.pathsep}/usr/bin")
    assert st1["installed"] is True and st1["in_path"] is True

    # 3. Uninstall removes wrapper cleanly
    res_un = runtime_state.uninstall_cli_command(bin_dir=bin_dir)
    assert res_un["installed"] is False and res_un["removed"] is True
    assert not script_path.exists()

    # 4. Read-only directory returns clean Chinese error without crashing (POSIX non-root only)
    if os.name == "posix" and getattr(os, "geteuid", lambda: 1)() != 0:
        ro_dir = tmp_path / "readonly_bin"
        ro_dir.mkdir()
        os.chmod(ro_dir, 0o555)
        try:
            res_ro = runtime_state.install_cli_command(bin_dir=ro_dir, path_env="/usr/bin")
            assert res_ro["installed"] is False
            assert res_ro.get("error")
        finally:
            os.chmod(ro_dir, 0o755)

    # 5. DesktopBridge exposes CLI installer methods
    bridge = desktop_app.DesktopBridge(data_dir=tmp_path)
    assert hasattr(bridge, "get_cli_install_status")
    assert hasattr(bridge, "install_cli_command")
    assert hasattr(bridge, "uninstall_cli_command")


# ---------------------------------------------------------------------------
# Increment E: W2-T07 & W2-T08 (Real Headless Chrome CDP E2E + 3-theme WCAG)
# ---------------------------------------------------------------------------


def test_w2_t07_t08_resume_card_auto_resume_invalid_fallback_and_cli_ui_cdp(tmp_path: Path) -> None:
    """W2-T07/T08: Real daemon + compiled SPA + Headless Chrome CDP for Resume Card, Auto-Resume & Desktop CLI UI."""
    import shutil
    import tempfile
    from backend import runtime_state
    from backend.export.pdf_exporter import find_local_chrome
    from tests.test_performance_benchmark import _MiniCDP

    chrome = find_local_chrome()
    if not chrome:
        pytest.skip("Local Chrome not found for CDP E2E test")

    data_dir = tmp_path / "cdp_w2_data"
    dir_a = tmp_path / "paper_alpha"
    dir_b = tmp_path / "paper_beta"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "alpha.md").write_text("# Alpha Paper\n\nAlpha body paragraph for W2 resume test.\n", encoding="utf-8")
    (dir_b / "beta.md").write_text("# Beta Paper\n\nBeta body paragraph for explicit override.\n", encoding="utf-8")

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
    user_dir = tempfile.mkdtemp(prefix="pd_w2_res_cdp_")
    try:
        # Bind two local projects via /api/local/open-path
        def _open_path_api(p: Path) -> dict:
            req = urllib.request.Request(
                f"{base_url}/api/local/open-path",
                data=json.dumps({"path": str(p)}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with opener.open(req, timeout=8.0) as r:
                return json.loads(r.read().decode("utf-8"))

        pa = _open_path_api(dir_a / "alpha.md")
        pb = _open_path_api(dir_b / "beta.md")
        pid_a = int(pa["project_id"])
        pid_b = int(pb["project_id"])

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
            while time.monotonic() < end:
                val = eval_js(expr)
                if val:
                    return val
                time.sleep(0.12)
            raise AssertionError(f"Timeout waiting for: {expr}")

        # 1. Visit Alpha project via handoff URL so `paperdiff_last_workspace` gets saved
        cdp.send("Page.navigate", {"url": f"{base_url}/?project={pid_a}&file=alpha.md"})
        wait_for("document.body.innerText.includes('Alpha body paragraph for W2 resume test')")

        # 2. Navigate back to Home `/` -> default stays on Home (auto-resume OFF) and shows Resume Card!
        cdp.send("Page.navigate", {"url": f"{base_url}/"})
        wait_for("document.querySelector('[data-resume-workspace-card]') !== null")
        assert eval_js("document.querySelector('[data-auto-resume-toggle]').checked") is False
        assert eval_js("document.querySelector('[data-desktop-cli-btn]') === null") is True
        card_text = str(eval_js("document.querySelector('[data-resume-workspace-card]').textContent"))
        assert "paper_alpha" in card_text and "alpha.md" in card_text

        # Check 3-theme WCAG >= 4.5 contrast on Resume Card & primary CTA
        for theme_name in ("light", "sepia", "dark"):
            eval_js(f"document.documentElement.dataset.theme = '{theme_name}'")
            time.sleep(0.05)
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
                  const card = document.querySelector('[data-resume-workspace-card]');
                  const btn = document.querySelector('[data-resume-open-btn]');
                  return { card: contrast(card), btn: contrast(btn) };
                })()"""
            )
            assert ratios["card"] >= 4.5, f"{theme_name} resume card contrast too low: {ratios}"
            assert ratios["btn"] >= 4.5, f"{theme_name} resume CTA contrast too low: {ratios}"
        eval_js("document.documentElement.dataset.theme = 'light'")

        # 3. Click「继续上次工作区」-> lands straight into alpha.md
        eval_js("document.querySelector('[data-resume-open-btn]').click()")
        wait_for("document.body.innerText.includes('Alpha body paragraph for W2 resume test')")

        # 4. Return Home, turn ON auto-resume toggle, reload `/` -> auto-lands in alpha.md!
        cdp.send("Page.navigate", {"url": f"{base_url}/"})
        wait_for("document.querySelector('[data-auto-resume-toggle]') !== null")
        eval_js("document.querySelector('[data-auto-resume-toggle]').click()")
        wait_for("document.querySelector('[data-auto-resume-toggle]').checked === true")
        cdp.send("Page.navigate", {"url": f"{base_url}/"})
        wait_for("document.body.innerText.includes('Alpha body paragraph for W2 resume test')")

        # 5. Explicit `/?project=<pid_b>&file=beta.md` MUST override auto-resume!
        cdp.send("Page.navigate", {"url": f"{base_url}/?project={pid_b}&file=beta.md"})
        wait_for("document.body.innerText.includes('Beta body paragraph for explicit override')")

        # 6. Move `dir_b` away on disk & reload `/` -> gracefully falls back to Home with invalid badge + relocate button!
        shutil.move(str(dir_b), str(tmp_path / "paper_beta_moved"))
        cdp.send("Page.navigate", {"url": f"{base_url}/"})
        wait_for("document.querySelector('[data-resume-workspace-card][data-resume-status=\"root_invalid\"]') !== null")
        assert eval_js("document.querySelector('[data-resume-relocate-btn]') !== null") is True
        assert "目录已移动" in str(eval_js("document.querySelector('[data-resume-invalid-badge]').textContent"))

        # --- W2-T08: Desktop CLI installer UI with injected pywebview bridge ---
        script_id = cdp.send(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                  window.__cliInstalled = false;
                  window.pywebview = {
                    api: {
                      open_in_browser: (rel) => Promise.resolve({ opened: true, url: 'http://127.0.0.1' + rel }),
                      get_cli_install_status: () => Promise.resolve({
                        installed: window.__cliInstalled,
                        script_path: '/Users/demo/.local/bin/paperdiff',
                        in_path: false,
                        path_hint: 'export PATH="/Users/demo/.local/bin:$PATH"'
                      }),
                      install_cli_command: () => {
                        window.__cliInstalled = true;
                        return Promise.resolve({
                          installed: true,
                          script_path: '/Users/demo/.local/bin/paperdiff',
                          in_path: false,
                          path_hint: 'export PATH="/Users/demo/.local/bin:$PATH"'
                        });
                      },
                      uninstall_cli_command: () => {
                        window.__cliInstalled = false;
                        return Promise.resolve({
                          installed: false,
                          removed: true,
                          script_path: '/Users/demo/.local/bin/paperdiff'
                        });
                      }
                    }
                  };
                """
            },
        )["identifier"]
        cdp.send("Page.navigate", {"url": f"{base_url}/"})
        wait_for("document.querySelector('[data-desktop-cli-btn]') !== null")
        eval_js("document.querySelector('[data-desktop-cli-btn]').click()")
        wait_for("document.querySelector('[data-desktop-cli-install-btn]') !== null")
        eval_js("document.querySelector('[data-desktop-cli-install-btn]').click()")
        wait_for("document.querySelector('[data-desktop-cli-state=\"installed\"]') !== null")
        assert eval_js("document.querySelector('[data-desktop-cli-path-hint]') !== null") is True
        cdp.send("Page.removeScriptToEvaluateOnNewDocument", {"identifier": script_id})
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
        runtime_state.request_graceful_shutdown(data_dir, timeout=4.0)
