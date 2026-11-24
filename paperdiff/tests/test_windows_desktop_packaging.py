"""Cross-platform Windows desktop runtime, packaging, folder workflow, and dual-platform CI test suite."""
from __future__ import annotations

import os
import re
import struct
import subprocess
import sys
import types
import zipfile
from pathlib import Path
from unittest import mock

import pytest

PAPERDIFF_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = PAPERDIFF_ROOT.parent
PACKAGING_DIR = PAPERDIFF_ROOT / "packaging"


# ---------------------------------------------------------------------------
# Inc-1: Cross-platform frozen DATA_DIR & portable mode (T-01 ~ T-04)
# ---------------------------------------------------------------------------


def test_t01_windows_frozen_default_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T-01 (AC-03): Frozen Windows build defaults to %LOCALAPPDATA%/PaperDiff (never Library/Application Support)."""
    from backend import database, runtime_state

    fake_exe_dir = tmp_path / "install_dir"
    fake_exe_dir.mkdir()
    fake_exe = fake_exe_dir / "PaperDiff.exe"
    fake_exe.write_bytes(b"MZ")
    local_app = tmp_path / "LocalAppData"

    monkeypatch.delenv("PAPERDIFF_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local_app))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))

    expected = (local_app / "PaperDiff").resolve()
    rt_dir = runtime_state.resolve_data_dir()
    db_dir = database._resolve_data_dir()

    assert rt_dir == expected
    assert db_dir == expected
    assert "Library" not in str(rt_dir)

    # Fallback when LOCALAPPDATA is absent -> ~/AppData/Local/PaperDiff
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    fallback_expected = (fake_home / "AppData" / "Local" / "PaperDiff").resolve()
    assert runtime_state.resolve_data_dir() == fallback_expected
    assert database._resolve_data_dir() == fallback_expected


def test_t02_windows_portable_flag_and_readonly_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T-02 (AC-04): Frozen build with sibling portable.flag uses sibling data/, falling back safely if read-only."""
    from backend import database, runtime_state

    portable_dir = tmp_path / "PaperDiff_Portable_中文目录"
    portable_dir.mkdir()
    fake_exe = portable_dir / "PaperDiff.exe"
    fake_exe.write_bytes(b"MZ")
    (portable_dir / "portable.flag").write_text("portable\n", encoding="utf-8")
    local_app = tmp_path / "LocalAppData"

    monkeypatch.delenv("PAPERDIFF_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local_app))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))

    expected_portable = (portable_dir / "data").resolve()
    assert runtime_state.resolve_data_dir() == expected_portable
    assert database._resolve_data_dir() == expected_portable
    assert expected_portable.exists()

    # Simulate read-only portable directory -> safe fallback to %LOCALAPPDATA%/PaperDiff
    ro_portable = tmp_path / "ro_usb"
    ro_portable.mkdir()
    ro_exe = ro_portable / "PaperDiff.exe"
    ro_exe.write_bytes(b"MZ")
    (ro_portable / "portable.flag").write_text("portable\n", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(ro_exe))

    orig_mkdir = Path.mkdir

    def _guarded_mkdir(self: Path, *args, **kwargs):
        if str(self).startswith(str(ro_portable / "data")):
            raise PermissionError("Read-only removable media")
        return orig_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", _guarded_mkdir)
    fallback_expected = (local_app / "PaperDiff").resolve()
    assert runtime_state.resolve_data_dir() == fallback_expected
    assert database._resolve_data_dir() == fallback_expected


def test_t03_env_data_dir_overrides_portable_and_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T-03 (AC-05): PAPERDIFF_DATA_DIR takes strict precedence over portable.flag and OS default."""
    from backend import database, runtime_state

    portable_dir = tmp_path / "portable_dir"
    portable_dir.mkdir()
    fake_exe = portable_dir / "PaperDiff.exe"
    fake_exe.write_bytes(b"MZ")
    (portable_dir / "portable.flag").write_text("portable\n", encoding="utf-8")
    override_dir = tmp_path / "explicit_override_data"

    monkeypatch.setenv("PAPERDIFF_DATA_DIR", str(override_dir))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))

    assert runtime_state.resolve_data_dir() == override_dir.resolve()
    assert database._resolve_data_dir() == override_dir.resolve()


def test_t04_macos_frozen_and_dev_data_dir_regression(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T-04: macOS frozen app and source dev mode preserve original DATA_DIR paths."""
    from backend import database, runtime_state

    fake_home = tmp_path / "mac_home"
    fake_home.mkdir()
    fake_app_bin = tmp_path / "PaperDiff.app" / "Contents" / "MacOS" / "PaperDiff"
    fake_app_bin.parent.mkdir(parents=True)
    fake_app_bin.write_bytes(b"")

    monkeypatch.delenv("PAPERDIFF_DATA_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_app_bin))

    mac_expected = (fake_home / "Library" / "Application Support" / "PaperDiff").resolve()
    assert runtime_state.resolve_data_dir() == mac_expected
    assert database._resolve_data_dir() == mac_expected

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    dev_expected = (PAPERDIFF_ROOT / "data").resolve()
    assert runtime_state.resolve_data_dir() == dev_expected
    assert database._resolve_data_dir() == dev_expected


# ---------------------------------------------------------------------------
# Inc-2: Windows desktop shell, silent PDF export, CLI .cmd & smoke (T-05 ~ T-10)
# ---------------------------------------------------------------------------


def test_t05_windows_open_data_and_logs_dir_uses_startfile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T-05 (AC-08): open_data_dir / open_logs_dir invoke os.startfile on Windows instead of macOS `open`."""
    import desktop_app

    data_dir = tmp_path / "win_data"
    bridge = desktop_app.DesktopBridge(data_dir=data_dir)
    opened: list[str] = []

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(os, "startfile", lambda p: opened.append(str(p)), raising=False)

    with mock.patch("desktop_app.subprocess.Popen") as m_popen:
        assert bridge.open_data_dir() is True
        assert bridge.open_logs_dir() is True
        m_popen.assert_not_called()

    assert len(opened) == 2
    assert Path(opened[0]) == data_dir
    assert Path(opened[1]) == data_dir / "logs"
    assert (data_dir / "logs").exists()


def test_t06_windows_pdf_export_no_window_and_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T-06 (AC-06): Windows PDF export supports PAPERDIFF_CHROME_PATH, passes CREATE_NO_WINDOW, skips AppKit."""
    import desktop_app
    from backend.export import pdf_exporter

    fake_edge = tmp_path / "msedge.exe"
    fake_edge.write_bytes(b"MZ")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("PAPERDIFF_CHROME_PATH", str(fake_edge))
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

    assert pdf_exporter.find_local_chrome() == str(fake_edge)

    captured_kwargs: dict = {}

    def _fake_run(cmd, **kwargs):
        captured_kwargs.update(kwargs)
        for arg in cmd:
            if isinstance(arg, str) and arg.startswith("--print-to-pdf="):
                out_path = Path(arg.split("=", 1)[1])
                out_path.write_bytes(b"%PDF-1.4\n" + b"0" * 300)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    with mock.patch("backend.export.pdf_exporter.subprocess.run", side_effect=_fake_run):
        pdf_bytes = pdf_exporter.render_html_to_pdf_bytes("<html><body>PaperDiff</body></html>")
        assert pdf_bytes.startswith(b"%PDF")
        assert captured_kwargs.get("creationflags") == 0x08000000

    # DesktopBridge on Windows must skip AppKit and route cleanly to pdf_exporter
    bridge = desktop_app.DesktopBridge(data_dir=tmp_path)
    out_dir = tmp_path / "Downloads"
    out_dir.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    with mock.patch("backend.export.pdf_exporter.subprocess.run", side_effect=_fake_run):
        res = bridge.export_pdf_from_html("review.pdf", "<html><body>Hello</body></html>", landscape=False)
    assert res["saved"] is True
    assert res["engine"] == "chromium"
    assert Path(str(res["path"])).read_bytes().startswith(b"%PDF")


def test_t07_windows_pdf_export_missing_browser_graceful_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T-07 (AC-07): Missing Edge/Chrome on Windows returns actionable Chinese error without crashing."""
    import desktop_app
    from backend.export import pdf_exporter

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("PAPERDIFF_CHROME_PATH", raising=False)
    monkeypatch.setattr(pdf_exporter, "find_local_chrome", lambda: None)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / "Downloads").mkdir()

    bridge = desktop_app.DesktopBridge(data_dir=tmp_path)
    res = bridge.export_pdf_from_html("review.pdf", "<html><body>Test</body></html>")
    assert res["saved"] is False
    err = str(res.get("error") or "")
    assert "Edge" in err or "Chrome" in err
    assert "PDF" in err


def test_t08_windows_screens_fallback_and_webview2_missing_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """T-08 (AC-09): get_connected_screens degrades safely without AppKit; missing WebView2 triggers Chinese dialog."""
    import desktop_app

    monkeypatch.setattr(sys, "platform", "win32")

    # 1. get_connected_screens does not crash if webview.screens is empty and AppKit does not exist
    fake_wv = types.SimpleNamespace(screens=[])
    with mock.patch.dict(sys.modules, {"webview": fake_wv, "AppKit": None}):
        screens = desktop_app.get_connected_screens()
        assert screens == []

    # 2. _start_webview_with_guard catches WebView2 missing error and invokes Chinese guidance dialog
    shown_dialogs: list[tuple[str, str]] = []
    monkeypatch.setattr(
        desktop_app,
        "_show_native_error_dialog",
        lambda title, msg: shown_dialogs.append((title, msg)),
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("Microsoft Edge WebView2 Runtime is not installed")

    fake_wv_start = types.SimpleNamespace(start=_boom)
    with mock.patch.dict(sys.modules, {"webview": fake_wv_start}):
        exit_code = desktop_app._start_webview_with_guard(fake_wv_start, func=lambda: None, debug=False)

    assert exit_code != 0
    assert len(shown_dialogs) == 1
    title, msg = shown_dialogs[0]
    assert "PaperDiff" in title or "对稿" in title
    assert "WebView2" in msg


def test_t09_windows_cli_cmd_wrapper_install_status_and_uninstall(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T-09: Windows CLI helper creates paperdiff.cmd, checks PATH, and uninstalls cleanly."""
    from backend import runtime_state

    monkeypatch.setattr(sys, "platform", "win32")
    bin_dir = tmp_path / "win_bin"
    fake_exe = tmp_path / "PaperDiff" / "PaperDiff.exe"
    fake_exe.parent.mkdir()
    fake_exe.write_bytes(b"MZ")

    st0 = runtime_state.get_cli_install_status(bin_dir=bin_dir, path_env=r"C:\Windows\System32")
    assert st0["installed"] is False
    assert st0["script_path"].endswith("paperdiff.cmd")

    res_in = runtime_state.install_cli_command(
        bin_dir=bin_dir,
        executable_target=fake_exe,
        path_env=r"C:\Windows\System32",
    )
    assert res_in["installed"] is True
    cmd_file = Path(res_in["script_path"])
    assert cmd_file.name == "paperdiff.cmd"
    assert cmd_file.exists()
    content = cmd_file.read_text(encoding="utf-8")
    assert "@echo off" in content.lower()
    assert "--open" in content
    assert "%*" in content
    assert str(bin_dir) in res_in["path_hint"]

    st1 = runtime_state.get_cli_install_status(bin_dir=bin_dir, path_env=f"{bin_dir}{os.pathsep}C:\\Windows")
    assert st1["installed"] is True
    assert st1["in_path"] is True

    res_un = runtime_state.uninstall_cli_command(bin_dir=bin_dir)
    assert res_un["installed"] is False
    assert res_un["removed"] is True
    assert not cmd_file.exists()


def test_t10_cross_platform_smoke_test_webview_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """T-10 (AC-10): Native webview smoke check verifies edgechromium on win32 without importing AppKit/Cocoa."""
    import desktop_app

    monkeypatch.setattr(sys, "platform", "win32")
    fake_webview = types.ModuleType("webview")
    fake_webview.__version__ = "5.4.0"
    fake_platforms = types.ModuleType("webview.platforms")
    fake_edge = types.ModuleType("webview.platforms.edgechromium")

    with mock.patch.dict(
        sys.modules,
        {
            "webview": fake_webview,
            "webview.platforms": fake_platforms,
            "webview.platforms.edgechromium": fake_edge,
            "AppKit": None,
            "WebKit": None,
        },
    ):
        info = desktop_app._verify_native_webview_runtime()

    assert info["webview_edgechromium_ok"] is True
    assert info["webview_version"] == "5.4.0"


# ---------------------------------------------------------------------------
# Inc-3: Windows packaging artifacts (.ico, spec, .iss, Portable.zip, freshness)
# ---------------------------------------------------------------------------


def test_t11_windows_ico_spec_iss_and_portable_zip_contract(tmp_path: Path) -> None:
    """T-11 (AC-01, AC-04, AC-10): Verify ICO builder, onedir spec, Inno Setup .iss, Portable.zip & requirements."""
    if str(PACKAGING_DIR) not in sys.path:
        sys.path.insert(0, str(PACKAGING_DIR))
    import build_windows_release

    # 1. Pure-Python multi-size ICO generator produces valid ICO header
    ico_out = tmp_path / "PaperDiff.ico"
    build_windows_release.build_ico(output_path=ico_out)
    ico_bytes = ico_out.read_bytes()
    reserved, img_type, count = struct.unpack("<HHH", ico_bytes[:6])
    assert (reserved, img_type) == (0, 1)
    assert count >= 3

    # 2. PaperDiff-win.spec enforces onedir, console=False, upx=False, no macOS Cocoa in hiddenimports
    spec_text = (PACKAGING_DIR / "PaperDiff-win.spec").read_text(encoding="utf-8")
    hidden_section = spec_text.split("hiddenimports = [", 1)[1].split("excludes = [", 1)[0]
    assert "exclude_binaries=True" in spec_text
    assert "console=False" in spec_text
    assert "upx=False" in spec_text
    assert "PaperDiff.ico" in spec_text
    assert "webview.platforms.edgechromium" in hidden_section
    assert "webview.platforms.cocoa" not in hidden_section
    assert '"AppKit"' not in hidden_section

    # 3. PaperDiff.iss enforces per-user lowest install + dialog override, optional PATH task, no file hijacking
    iss_text = (PACKAGING_DIR / "PaperDiff.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in iss_text
    assert "PrivilegesRequiredOverridesAllowed=dialog" in iss_text
    assert "addtopath" in iss_text.lower()
    assert "paperdiff.cmd" in iss_text.lower()
    assert "Classes\\.docx" not in iss_text
    assert "Classes\\.tex" not in iss_text

    # 4. Portable.zip builder includes PaperDiff.exe and portable.flag
    fake_onedir = tmp_path / "dist_out" / "PaperDiff"
    fake_onedir.mkdir(parents=True)
    (fake_onedir / "PaperDiff.exe").write_bytes(b"MZ")
    (fake_onedir / "_internal").mkdir()
    (fake_onedir / "_internal" / "sample.txt").write_text("ok", encoding="utf-8")
    zip_out = tmp_path / "PaperDiff-v0.2.0-Windows-x64-Portable.zip"
    build_windows_release.build_portable_zip(fake_onedir, output_zip=zip_out)
    with zipfile.ZipFile(zip_out, "r") as zf:
        names = set(zf.namelist())
        assert "PaperDiff/PaperDiff.exe" in names
        assert "PaperDiff/portable.flag" in names

    # 5. requirements-dev.txt enables pyinstaller on win32
    req_dev = (PAPERDIFF_ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert re.search(r'pyinstaller.*win32', req_dev)


def test_t12_windows_bundle_freshness_gate_blocks_stale_assets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T-12 (AC-11): verify_bundle_freshness passes on matching frontend/dist and fails on stale assets."""
    if str(PACKAGING_DIR) not in sys.path:
        sys.path.insert(0, str(PACKAGING_DIR))
    import build_windows_release

    src_dist = tmp_path / "frontend" / "dist"
    (src_dist / "assets").mkdir(parents=True)
    (src_dist / "index.html").write_text('<script src="/assets/app-abc123.js"></script>', encoding="utf-8")
    (src_dist / "assets" / "app-abc123.js").write_text("console.log('fresh');", encoding="utf-8")

    # PyInstaller 6 onedir puts datas inside `_internal/`
    bundle_dir = tmp_path / "dist_out" / "PaperDiff"
    bnd_dist = bundle_dir / "_internal" / "frontend" / "dist"
    (bnd_dist / "assets").mkdir(parents=True)
    (bnd_dist / "index.html").write_text('<script src="/assets/app-abc123.js"></script>', encoding="utf-8")
    (bnd_dist / "assets" / "app-abc123.js").write_text("console.log('fresh');", encoding="utf-8")

    monkeypatch.setattr(build_windows_release, "FRONTEND_DIR", tmp_path / "frontend")
    build_windows_release.verify_bundle_freshness(bundle_dir, label="TestWinBundle")

    # Mutate bundled asset -> must raise RuntimeError
    (bnd_dist / "assets" / "app-abc123.js").write_text("console.log('stale');", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Asset mismatch|Stale"):
        build_windows_release.verify_bundle_freshness(bundle_dir, label="TestWinBundle")


# ---------------------------------------------------------------------------
# Inc-4: Dual-platform atomic GitHub Actions release pipeline (T-13)
# ---------------------------------------------------------------------------


def test_t13_release_workflow_dual_platform_atomic_pipeline() -> None:
    """T-13 (AC-12, AC-13): release.yml runs verify -> [build-macos, build-windows] -> atomic publish."""
    wf_text = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in wf_text
    assert "verify:" in wf_text
    assert "build-macos:" in wf_text
    assert "build-windows:" in wf_text
    assert "publish:" in wf_text
    assert "runs-on: macos-latest" in wf_text
    assert "runs-on: windows-latest" in wf_text
    assert "build_windows_release.py" in wf_text
    assert "needs: [verify, build-macos, build-windows]" in wf_text
    assert "github.event_name == 'push'" in wf_text
    assert "SHA256SUMS.txt" in wf_text
    # publish must never bypass upstream failures with always()
    publish_section = wf_text.split("publish:", 1)[1]
    assert "always()" not in publish_section


# ---------------------------------------------------------------------------
# End-to-end Windows folder picking & local manuscript workflow (T-14 ~ T-15)
# ---------------------------------------------------------------------------


def test_t14_windows_frozen_folder_picker_and_desktop_bridge_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-14: Frozen Windows build skips tkinter subprocess (never re-spawns PaperDiff.exe) and bridges safely."""
    import desktop_app
    from backend.main import _pick_native_folder

    # 1. Frozen Windows backend must skip `[sys.executable, "-c", ...]` and go straight to PowerShell
    monkeypatch.setattr("backend.main.platform.system", lambda: "Windows")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    ps_ok = subprocess.CompletedProcess(
        args=["powershell.exe"], returncode=0, stdout=r"D:\Papers\中文论文目录" + "\n", stderr=""
    )
    with mock.patch("backend.main.subprocess.run", return_value=ps_ok) as m_run:
        res = _pick_native_folder(str(tmp_path))
        assert res["picked"] is True
        assert res["supported"] is True
        assert "中文论文目录" in str(res["path"])
        assert m_run.call_count == 1
        assert m_run.call_args_list[0].args[0][0] == "powershell.exe"

    # 2. DesktopBridge.select_local_folder works with quoted initial_dir and degrades cleanly on GUI dialog error
    paper_dir = tmp_path / "论文项目_Win"
    paper_dir.mkdir()
    fake_wv = types.SimpleNamespace(FOLDER_DIALOG=20)
    fake_win_ok = types.SimpleNamespace(create_file_dialog=lambda mode, directory="": (str(paper_dir),))
    bridge = desktop_app.DesktopBridge(data_dir=tmp_path)
    bridge.window = fake_win_ok
    with mock.patch.dict(sys.modules, {"webview": fake_wv}):
        picked = bridge.select_local_folder(f'"{paper_dir}"')
        assert picked["picked"] is True
        assert picked["supported"] is True
        assert Path(str(picked["path"])) == paper_dir.resolve()

    def _boom_dialog(*args, **kwargs):
        raise RuntimeError("WinForms dialog init error")

    bridge.window = types.SimpleNamespace(create_file_dialog=_boom_dialog)
    with mock.patch.dict(sys.modules, {"webview": fake_wv}):
        fallback = bridge.select_local_folder(str(paper_dir))
        assert fallback["picked"] is False
        assert fallback["supported"] is False


def test_t15_windows_local_folder_project_create_read_diff_and_writeback_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-15: End-to-end Windows Explorer quoted path -> bind local project -> tree -> preview -> diff -> safe save."""
    import hashlib
    from fastapi.testclient import TestClient
    from backend import database as db
    from backend.main import app

    # Isolate DB inside tmp_path so real workspace data is never touched
    db_path = tmp_path / "test_win_e2e.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()

    paper_dir = tmp_path / "论文审校测试_Win"
    sections_dir = paper_dir / "sections"
    sections_dir.mkdir(parents=True)
    v1_file = paper_dir / "v1_初稿.md"
    v2_file = paper_dir / "v2_修订稿.md"
    tex_file = sections_dir / "method.tex"

    v1_file.write_text("# 引言\n\n实验准确率为 91.2%，样本量 n = 120。\n", encoding="utf-8")
    v2_file.write_text("# 引言\n\n实验准确率为 94.8%，样本量 n = 150。\n", encoding="utf-8")
    tex_file.write_text(r"\section{Method}" + "\nWe achieved 94.8\\% accuracy.\n", encoding="utf-8")
    orig_v2_hash = hashlib.sha256(v2_file.read_bytes()).hexdigest()

    quoted_win_input = f'"{paper_dir}"'

    with TestClient(app) as client:
        # 1. Validate folder pasted in Windows Explorer "Copy as path" format
        r_val = client.post("/api/local/validate-folder", json={"path": quoted_win_input})
        assert r_val.status_code == 200, r_val.text
        vdata = r_val.json()
        assert vdata["valid"] is True
        assert vdata["doc_count"] == 3

        # 2. Create local_folder project using the quoted path directly
        r_proj = client.post(
            "/api/projects",
            json={
                "name": "Windows 端到端测试论文",
                "project_mode": "local_folder",
                "local_root_path": quoted_win_input,
            },
        )
        assert r_proj.status_code == 200, r_proj.text
        pid = r_proj.json()["id"]

        # 3. Browse local file tree and verify normalized POSIX rel_paths across subdirectories
        r_tree = client.get(f"/api/projects/{pid}/local/tree")
        assert r_tree.status_code == 200, r_tree.text
        tree = r_tree.json()
        assert tree["doc_count"] == 3

        def _collect_rels(nodes: list[dict]) -> set[str]:
            rels: set[str] = set()
            for n in nodes:
                if n["node_type"] == "file":
                    rels.add(n["rel_path"])
                else:
                    rels.update(_collect_rels(n.get("children") or []))
            return rels

        rels = _collect_rels(tree["nodes"])
        assert rels == {"v1_初稿.md", "v2_修订稿.md", "sections/method.tex"}

        # 4. Preview single document directly from bound local folder
        r_prev = client.post(f"/api/projects/{pid}/local/preview", json={"rel_path": "sections/method.tex"})
        assert r_prev.status_code == 200, r_prev.text
        assert r_prev.json()["blocks"]

        # 5. Pairwise compare between v1 and v2 detects numeric & text changes
        r_diff = client.post(
            f"/api/projects/{pid}/local/compare",
            json={"old_rel_path": "v1_初稿.md", "new_rel_path": "v2_修订稿.md"},
        )
        assert r_diff.status_code == 200, r_diff.text
        diff_data = r_diff.json()
        assert diff_data["summary"]["modified_paragraphs"] >= 1
        assert len(diff_data.get("alerts") or []) >= 1

        # 6. Safe writeback saves sibling _revised copy while keeping original v2_修订稿.md untouched
        p_v2 = client.post(f"/api/projects/{pid}/local/preview", json={"rel_path": "v2_修订稿.md"}).json()
        para_block = [b for b in p_v2["blocks"] if b["block_type"] == "paragraph"][0]
        r_save = client.post(
            f"/api/projects/{pid}/local/save-edits",
            json={
                "rel_path": "v2_修订稿.md",
                "mode": "save_as",
                "patches": [
                    {
                        "op": "replace_block",
                        "block_index": para_block["index"],
                        "new_raw": "实验准确率为 95.1%，样本量 n = 150。",
                    }
                ],
            },
        )
        assert r_save.status_code == 200, r_save.text
        save_res = r_save.json()
        saved_rel = save_res.get("target_rel_path") or ""
        assert "_revised" in saved_rel
        assert (paper_dir / saved_rel).exists()
        assert "95.1%" in (paper_dir / saved_rel).read_text(encoding="utf-8")

    # Original file remains 100% unmodified on disk
    assert hashlib.sha256(v2_file.read_bytes()).hexdigest() == orig_v2_hash
