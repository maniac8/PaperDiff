#!/usr/bin/env python3
"""End-to-end Windows x64 `Setup.exe` & `Portable.zip` release builder for 对稿 · PaperDiff Studio.

Steps:
  1. Build React production bundle (`npm run build`).
  2. Build multi-size Windows `PaperDiff.ico` from `branding/release/app-icon-*.png`.
  3. Freeze standalone `onedir` bundle via PyInstaller (`PaperDiff-win.spec`, `upx=False`).
  4. Verify bundled `frontend/dist` matches freshly built assets bit-for-bit (SHA-256).
  5. Run frozen binary headless smoke test (`PAPERDIFF_SMOKE_TEST=1`) in isolated temp DATA_DIR.
  6. Archive `PaperDiff-v<VERSION>-Windows-x64-Portable.zip` (with `portable.flag` & guide).
  7. Compile Inno Setup `PaperDiff.iss` into `PaperDiff-v<VERSION>-Windows-x64-Setup.exe`.
  8. Emit `release/SHA256SUMS-windows.txt` (and `release/SHA256SUMS.txt` when run locally).
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PACKAGING_DIR = Path(__file__).resolve().parent
PAPERDIFF_ROOT = PACKAGING_DIR.parent
PROJECT_ROOT = PAPERDIFF_ROOT.parent
FRONTEND_DIR = PAPERDIFF_ROOT / "frontend"
BRANDING_RELEASE_DIR = PROJECT_ROOT / "branding" / "release"
ICO_PATH = PACKAGING_DIR / "PaperDiff.ico"
SPEC_PATH = PACKAGING_DIR / "PaperDiff-win.spec"
ISS_PATH = PACKAGING_DIR / "PaperDiff.iss"
GUIDE_MD = PROJECT_ROOT / "产品使用指南.md"

VERSION = "0.2.0"
ARCH = "x64"
RELEASE_DIR = PROJECT_ROOT / "release"
BUILD_WORK = PACKAGING_DIR / "build_work_win"
BUILD_DIST = PACKAGING_DIR / "dist_out_win"
SETUP_BASENAME = f"PaperDiff-v{VERSION}-Windows-{ARCH}-Setup"
SETUP_EXE_PATH = RELEASE_DIR / f"{SETUP_BASENAME}.exe"
PORTABLE_ZIP_PATH = RELEASE_DIR / f"PaperDiff-v{VERSION}-Windows-{ARCH}-Portable.zip"


def run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print(f"\n▶ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=True)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _png_dimensions(png_bytes: bytes) -> tuple[int, int]:
    if len(png_bytes) < 24 or png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Invalid PNG file header")
    width, height = struct.unpack(">II", png_bytes[16:24])
    return int(width), int(height)


def _pack_pngs_as_ico(png_frames: list[bytes]) -> bytes:
    """Pack one or more <=256x256 PNG byte buffers into a valid Windows ICO binary."""
    if not png_frames:
        raise ValueError("At least one PNG frame is required to build an ICO file")
    count = len(png_frames)
    header = struct.pack("<HHH", 0, 1, count)
    entries: list[bytes] = []
    offset = 6 + 16 * count
    for raw in png_frames:
        w, h = _png_dimensions(raw)
        if w > 256 or h > 256:
            raise ValueError(f"ICO PNG frame exceeds 256x256 limit: {w}x{h}")
        w_byte = 0 if w == 256 else w
        h_byte = 0 if h == 256 else h
        entries.append(struct.pack("<BBBBHHII", w_byte, h_byte, 0, 0, 1, 32, len(raw), offset))
        offset += len(raw)
    return header + b"".join(entries) + b"".join(png_frames)


def build_ico(output_path: Path | None = None) -> Path:
    """Build multi-size Windows `PaperDiff.ico` (uses Pillow if installed, pure-Python PNG-in-ICO fallback)."""
    dest = Path(output_path) if output_path is not None else ICO_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)

    frames: list[bytes] = []
    src_1024 = BRANDING_RELEASE_DIR / "app-icon-1024.png"
    try:
        from PIL import Image  # type: ignore[import-not-found]

        if src_1024.exists():
            with Image.open(src_1024) as im:
                rgba = im.convert("RGBA")
                for sz in (16, 32, 48, 64, 128, 256):
                    buf = io.BytesIO()
                    rgba.resize((sz, sz), Image.Resampling.LANCZOS).save(buf, format="PNG")
                    frames.append(buf.getvalue())
    except Exception:
        frames = []

    if not frames:
        fallback_sources = [
            BRANDING_RELEASE_DIR / "app-icon-256.png",
            BRANDING_RELEASE_DIR / "apple-touch-icon-180.png",
            BRANDING_RELEASE_DIR / "app-icon-128.png",
        ]
        for candidate in fallback_sources:
            if candidate.exists():
                frames.append(candidate.read_bytes())

    if not frames:
        raise FileNotFoundError(f"No source icon PNGs found under {BRANDING_RELEASE_DIR}")

    dest.write_bytes(_pack_pngs_as_ico(frames))
    print(f"✓ Built {dest} ({len(frames)} icon sizes, {dest.stat().st_size // 1024} KB)")
    return dest


def build_frontend() -> None:
    dist_dir = FRONTEND_DIR / "dist"
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    npm_bin = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
    run([npm_bin, "run", "build"], cwd=FRONTEND_DIR)


def _locate_bundled_frontend_dist(onedir_bundle: Path) -> Path:
    for rel in (Path("_internal") / "frontend" / "dist", Path("frontend") / "dist"):
        cand = onedir_bundle / rel
        if cand.exists():
            return cand
    return onedir_bundle / "_internal" / "frontend" / "dist"


def verify_bundle_freshness(onedir_bundle: Path, label: str = "PaperDiff-win") -> None:
    """Assert the bundled frontend inside the Windows onedir matches `frontend/dist/` bit-for-bit."""
    src_dist = FRONTEND_DIR / "dist"
    bnd_dist = _locate_bundled_frontend_dist(onedir_bundle)
    src_index = src_dist / "index.html"
    bnd_index = bnd_dist / "index.html"
    if not bnd_index.exists():
        raise RuntimeError(f"[{label}] Missing bundled index.html: {bnd_index}")
    src_hash = _sha256(src_index)
    bnd_hash = _sha256(bnd_index)
    if src_hash != bnd_hash:
        raise RuntimeError(f"[{label}] Stale index.html detected! src={src_hash[:12]} != bundled={bnd_hash[:12]}")

    index_txt = src_index.read_text(encoding="utf-8")
    referenced = re.findall(r'/(assets/[^"\']+)', index_txt)
    if not referenced:
        raise RuntimeError(f"[{label}] No hashed /assets/* references found in index.html")
    for rel in referenced:
        sf = src_dist / rel
        bf = bnd_dist / rel
        if not bf.exists() or _sha256(sf) != _sha256(bf):
            raise RuntimeError(f"[{label}] Asset mismatch for {rel}: bundle is out of sync with frontend/dist!")
    print(f"✓ Freshness verified [{label}]: index.html ({src_hash[:10]}) + {len(referenced)} entry assets match 100%")


def _resolve_pyinstaller_cmd() -> list[str]:
    venv_pyinstaller = PAPERDIFF_ROOT / ".venv_pkg" / "Scripts" / "pyinstaller.exe"
    if venv_pyinstaller.exists():
        return [str(venv_pyinstaller)]
    which_pi = shutil.which("pyinstaller")
    if which_pi:
        return [which_pi]
    return [sys.executable, "-m", "PyInstaller"]


def build_onedir_bundle() -> Path:
    for d in (BUILD_WORK, BUILD_DIST):
        if d.exists():
            shutil.rmtree(d)

    cmd = _resolve_pyinstaller_cmd() + [
        "--noconfirm",
        "--clean",
        "--workpath",
        str(BUILD_WORK),
        "--distpath",
        str(BUILD_DIST),
        str(SPEC_PATH),
    ]
    run(cmd, cwd=PAPERDIFF_ROOT)

    onedir_bundle = BUILD_DIST / "PaperDiff"
    exe_file = onedir_bundle / "PaperDiff.exe"
    if not exe_file.exists():
        raise RuntimeError(f"Expected Windows executable not found: {exe_file}")
    print(f"✓ Frozen Windows onedir bundle ready: {onedir_bundle}")
    return onedir_bundle


def smoke_test_frozen_exe(onedir_bundle: Path) -> None:
    exe_file = onedir_bundle / "PaperDiff.exe"
    with tempfile.TemporaryDirectory(prefix="paperdiff_win_smoke_") as tmpdir:
        env = os.environ.copy()
        env["PAPERDIFF_SMOKE_TEST"] = "1"
        env["PAPERDIFF_DATA_DIR"] = tmpdir
        env["PAPERDIFF_PORT"] = "18944"
        proc = subprocess.run(
            [str(exe_file)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            check=False,
        )
        print(proc.stdout)
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        if proc.returncode != 0 or "PAPERDIFF_SMOKE_TEST_PASS" not in proc.stdout:
            raise RuntimeError(f"Frozen Windows smoke test failed (exit={proc.returncode})")
        db_file = Path(tmpdir) / "paperdiff.db"
        assert db_file.exists() and db_file.stat().st_size > 4096, "SQLite DB not created in DATA_DIR"
    print("✓ Frozen Windows PaperDiff.exe headless smoke test PASSED")


def _portable_readme_text() -> str:
    return (
        f"对稿 · PaperDiff (v{VERSION} Windows x64 便携版)\r\n"
        "================================================\r\n\r\n"
        "1. 解压后直接双击 PaperDiff.exe 即可运行，无需安装 Python 或管理员权限。\r\n"
        "2. 同级目录下的 portable.flag 使数据自动保存在本目录的 data\\ 文件夹中，\r\n"
        "   方便随身携带；若目录只读，程序会自动回退到 %LOCALAPPDATA%\\PaperDiff。\r\n"
        "3. 所有论文与记录 100% 仅保存在本机，不会联网上传。\r\n"
        "4. 若 Windows SmartScreen 提示「Windows 已保护你的电脑」：\r\n"
        "   这是开源免费软件未采购商业代码签名证书的常规提示，\r\n"
        "   请点击「更多信息」→「仍要运行」，并可对照 SHA256SUMS.txt 校验安装包完整性。\r\n"
    )


def build_portable_zip(onedir_bundle: Path, output_zip: Path | None = None) -> Path:
    dest = Path(output_zip) if output_zip is not None else PORTABLE_ZIP_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()

    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file_path in sorted(onedir_bundle.rglob("*")):
            if file_path.is_file():
                arcname = (Path("PaperDiff") / file_path.relative_to(onedir_bundle)).as_posix()
                zf.write(file_path, arcname=arcname)
        zf.writestr(
            "PaperDiff/portable.flag",
            "# Presence of this file enables portable data storage in ./data/\n",
        )
        zf.writestr("PaperDiff/首次打开说明.txt", _portable_readme_text().encode("utf-8"))
        if GUIDE_MD.exists():
            zf.write(GUIDE_MD, arcname="PaperDiff/产品使用指南.md")

    size_mb = dest.stat().st_size / (1024 * 1024)
    print(f"✓ Built Portable ZIP: {dest} ({size_mb:.1f} MB)")
    return dest


def _find_iscc() -> Path:
    candidates = [
        shutil.which("iscc"),
        shutil.which("ISCC"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    for cand in candidates:
        if cand and Path(cand).exists():
            return Path(cand)
    raise FileNotFoundError(
        "Inno Setup Compiler (ISCC.exe) not found. Install Inno Setup 6 or run on GitHub Actions `windows-latest`."
    )


def build_inno_setup_exe(onedir_bundle: Path) -> Path:
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    if SETUP_EXE_PATH.exists():
        SETUP_EXE_PATH.unlink()

    BUILD_WORK.mkdir(parents=True, exist_ok=True)
    cli_wrapper = BUILD_WORK / "paperdiff.cmd"
    cli_wrapper.write_text('@echo off\r\n"%~dp0PaperDiff.exe" --open %*\r\n', encoding="utf-8")

    iscc = _find_iscc()
    cmd = [
        str(iscc),
        f"/DAppVersion={VERSION}",
        f"/DSourceDir={onedir_bundle}",
        f"/DOutputDir={RELEASE_DIR}",
        f"/DOutputBaseName={SETUP_BASENAME}",
        f"/DIconFile={ICO_PATH}",
        f"/DGuideFile={GUIDE_MD}",
        f"/DCliWrapperFile={cli_wrapper}",
    ]
    zh_isl = iscc.parent / "Languages" / "ChineseSimplified.isl"
    if zh_isl.exists():
        cmd.append("/DHasZhCN=1")
    cmd.append(str(ISS_PATH))

    run(cmd, cwd=PACKAGING_DIR)
    if not SETUP_EXE_PATH.exists():
        raise RuntimeError(f"Expected Inno Setup installer not created: {SETUP_EXE_PATH}")

    size_mb = SETUP_EXE_PATH.stat().st_size / (1024 * 1024)
    print(f"✓ Built Inno Setup Installer: {SETUP_EXE_PATH} ({size_mb:.1f} MB)")
    return SETUP_EXE_PATH


def emit_checksums(artifacts: list[Path]) -> Path:
    lines = [f"{_sha256(p)}  {p.name}" for p in artifacts if p.exists()]
    content = "\n".join(lines) + "\n"
    win_sums = RELEASE_DIR / "SHA256SUMS-windows.txt"
    win_sums.write_text(content, encoding="utf-8")
    print(f"✓ Wrote checksums to {win_sums}:\n{content.strip()}")
    return win_sums


def main() -> None:
    for _stream in (sys.stdout, sys.stderr):
        if _stream is not None and hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    print(f"=== Building 对稿 · PaperDiff v{VERSION} (Windows {ARCH}) ===")
    build_frontend()
    build_ico()
    onedir_bundle = build_onedir_bundle()
    verify_bundle_freshness(onedir_bundle, label=f"PaperDiff-win-v{VERSION}")
    smoke_test_frozen_exe(onedir_bundle)
    portable_zip = build_portable_zip(onedir_bundle)
    setup_exe = build_inno_setup_exe(onedir_bundle)
    emit_checksums([setup_exe, portable_zip])

    for d in (BUILD_WORK, BUILD_DIST):
        if d.exists():
            shutil.rmtree(d)

    print(
        f"\n🎉 Windows release ready:\n"
        f"   Setup:    {setup_exe}\n"
        f"   Portable: {portable_zip}"
    )


if __name__ == "__main__":
    main()
