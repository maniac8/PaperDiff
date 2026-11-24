"""Cross-platform Windows compatibility tests for local folder picking, path normalization, and PDF Chrome discovery."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest import mock

from backend.export.pdf_exporter import _windows_chrome_candidates
from backend.local_workspace import normalize_user_path, scan_local_tree, validate_root_dir
from backend.main import _pick_native_folder


def test_normalize_user_path_strips_windows_quotes_and_file_uri(tmp_path: Path) -> None:
    assert normalize_user_path(r'  "D:\Papers\My Thesis"  ') == r"D:\Papers\My Thesis"
    assert normalize_user_path(r"'C:\Users\Alice\Paper'") == r"C:\Users\Alice\Paper"
    assert normalize_user_path("file:///D:/Papers/My%20Paper") == "D:/Papers/My Paper"
    assert normalize_user_path("file:///Users/alice/My%20Paper") == "/Users/alice/My Paper"

    # Quoted real directory should validate cleanly (Windows Explorer "Copy as path" format)
    (tmp_path / "draft.md").write_text("# Draft\n\nHello.\n", encoding="utf-8")
    quoted = f'"{tmp_path}"'
    res = validate_root_dir(quoted)
    assert res["valid"] is True
    assert res["doc_count"] == 1


def test_scan_local_tree_handles_zero_inode_filesystems(tmp_path: Path, monkeypatch) -> None:
    """Windows FAT32/exFAT/network/OneDrive mounts may report st_ino == 0; subdirectories must still be scanned."""
    sub = tmp_path / "chapter_1"
    sub.mkdir()
    (sub / "v1.md").write_text("# Chapter 1\n", encoding="utf-8")

    orig_stat = Path.stat

    class _ZeroInoStat:
        def __init__(self, real: os.stat_result) -> None:
            self._real = real
            self.st_dev = real.st_dev
            self.st_ino = 0
            self.st_size = real.st_size
            self.st_mtime = real.st_mtime
            self.st_mode = real.st_mode

        def __getattr__(self, name: str):
            return getattr(self._real, name)

    def _fake_stat(self: Path, *args, **kwargs):
        return _ZeroInoStat(orig_stat(self, *args, **kwargs))

    monkeypatch.setattr(Path, "stat", _fake_stat)
    tree = scan_local_tree(tmp_path)
    assert tree["doc_count"] == 1
    assert any(n["name"] == "chapter_1" and n["node_type"] == "dir" for n in tree["nodes"])


def test_windows_native_folder_picker_tk_and_powershell_fallback(monkeypatch) -> None:
    monkeypatch.setattr("backend.main.platform.system", lambda: "Windows")

    # 1. Primary tkinter subprocess succeeds
    ok_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout=r"D:\Papers\NeurIPS_2026" + "\n", stderr="")
    with mock.patch("backend.main.subprocess.run", return_value=ok_proc) as m_run:
        res = _pick_native_folder(None)
        assert res["picked"] is True
        assert res["supported"] is True
        assert "NeurIPS_2026" in res["path"]
        assert m_run.call_count == 1

    # 2. Primary tkinter cancelled (exit 0, empty output)
    cancel_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with mock.patch("backend.main.subprocess.run", return_value=cancel_proc):
        res = _pick_native_folder(None)
        assert res["picked"] is False
        assert res.get("cancelled") is True
        assert res["supported"] is True

    # 3. Primary tkinter unavailable (exit 1) -> PowerShell FolderBrowserDialog fallback succeeds
    fail_tk = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="No module named tkinter")
    ok_ps = subprocess.CompletedProcess(args=[], returncode=0, stdout=r"E:\Thesis\Drafts", stderr="")
    with mock.patch("backend.main.subprocess.run", side_effect=[fail_tk, ok_ps]) as m_run:
        res = _pick_native_folder(None)
        assert res["picked"] is True
        assert res["supported"] is True
        assert "Drafts" in res["path"]
        assert m_run.call_count == 2
        assert m_run.call_args_list[1].args[0][0] == "powershell.exe"


def test_windows_chrome_candidates_include_chrome_and_edge() -> None:
    cands = _windows_chrome_candidates(
        {
            "PROGRAMFILES": r"C:\Program Files",
            "PROGRAMFILES(X86)": r"C:\Program Files (x86)",
            "LOCALAPPDATA": r"C:\Users\Alice\AppData\Local",
        }
    )
    assert r"C:\Program Files\Google\Chrome\Application\chrome.exe" in cands
    assert r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" in cands
    assert r"C:\Users\Alice\AppData\Local\Google\Chrome\Application\chrome.exe" in cands
