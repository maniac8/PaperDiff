#!/usr/bin/env python3
"""End-to-end macOS `.app` & `.dmg` release builder for 对稿 · PaperDiff Studio (v0.1.0).

Steps:
  1. Build React production bundle (`npm run build`).
  2. Convert Apple HIG `app-icon-macos-1024.png` into 10-layer native `PaperDiff.icns`.
  3. Freeze standalone `PaperDiff.app` via clean `.venv_pkg/bin/pyinstaller`.
  4. Ad-hoc codesign `PaperDiff.app` (`codesign --force --deep --sign -`).
  5. Run frozen binary headless smoke test (`PAPERDIFF_SMOKE_TEST=1`) to verify
     FastAPI, SPA, SQLite, jieba, AST parsers, and python-docx inside the bundle.
  6. Package compressed macOS `.dmg` (`PaperDiff-v0.1.0-macOS-arm64.dmg`) with
     `PaperDiff.app`, `/Applications` symlink, `产品使用指南.md`, and custom volume icon.
  7. Verify `.dmg` integrity (`hdiutil verify`), mount/unmount test, and emit `release/SHA256SUMS.txt`.
"""
from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

PACKAGING_DIR = Path(__file__).resolve().parent
PAPERDIFF_ROOT = PACKAGING_DIR.parent
PROJECT_ROOT = PAPERDIFF_ROOT.parent
FRONTEND_DIR = PAPERDIFF_ROOT / "frontend"
VENV_PYINSTALLER = PAPERDIFF_ROOT / ".venv_pkg" / "bin" / "pyinstaller"
SOURCE_ICON_PNG = PROJECT_ROOT / "branding" / "release" / "app-icon-macos-1024.png"
ICNS_PATH = PACKAGING_DIR / "PaperDiff.icns"
GUIDE_MD = PROJECT_ROOT / "产品使用指南.md"

VERSION = "0.1.0"
ARCH = platform.machine()  # arm64 / x86_64
RELEASE_DIR = PROJECT_ROOT / "release"
BUILD_WORK = PACKAGING_DIR / "build_work"
BUILD_DIST = PACKAGING_DIR / "dist_out"
DMG_NAME = f"PaperDiff-v{VERSION}-macOS-{ARCH}.dmg"
DMG_PATH = RELEASE_DIR / DMG_NAME


def run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print(f"\n▶ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=True)


def build_icns() -> None:
    if not SOURCE_ICON_PNG.exists():
        raise FileNotFoundError(f"Missing HIG icon PNG: {SOURCE_ICON_PNG}")

    iconset = PACKAGING_DIR / "PaperDiff.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)

    sizes = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]
    for px, fname in sizes:
        run(
            ["sips", "-z", str(px), str(px), str(SOURCE_ICON_PNG), "--out", str(iconset / fname)]
        )
    run(["iconutil", "-c", "icns", str(iconset), "-o", str(ICNS_PATH)])
    shutil.rmtree(iconset)
    print(f"✓ Built {ICNS_PATH} ({ICNS_PATH.stat().st_size // 1024} KB)")


def build_frontend() -> None:
    dist_dir = FRONTEND_DIR / "dist"
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    run(["npm", "run", "build"], cwd=FRONTEND_DIR)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_bundle_freshness(app_bundle: Path, label: str = "PaperDiff.app") -> None:
    """Assert the bundled frontend inside `.app` matches the freshly built `frontend/dist/` bit-for-bit."""
    src_dist = FRONTEND_DIR / "dist"
    bnd_dist = app_bundle / "Contents" / "Resources" / "frontend" / "dist"
    src_index = src_dist / "index.html"
    bnd_index = bnd_dist / "index.html"
    if not bnd_index.exists():
        raise RuntimeError(f"[{label}] Missing bundled index.html: {bnd_index}")
    src_hash = _sha256(src_index)
    bnd_hash = _sha256(bnd_index)
    if src_hash != bnd_hash:
        raise RuntimeError(f"[{label}] Stale index.html detected! src={src_hash[:12]} != bundled={bnd_hash[:12]}")

    import re as _re
    index_txt = src_index.read_text(encoding="utf-8")
    referenced = _re.findall(r'/(assets/[^"\']+)', index_txt)
    if not referenced:
        raise RuntimeError(f"[{label}] No hashed /assets/* references found in index.html")
    for rel in referenced:
        sf = src_dist / rel
        bf = bnd_dist / rel
        if not bf.exists() or _sha256(sf) != _sha256(bf):
            raise RuntimeError(f"[{label}] Asset mismatch for {rel}: bundle is out of sync with frontend/dist!")
    print(f"✓ Freshness verified [{label}]: index.html ({src_hash[:10]}) + {len(referenced)} entry assets match 100%")


def build_app_bundle() -> Path:
    if not VENV_PYINSTALLER.exists():
        raise FileNotFoundError(f"Clean packaging venv missing: {VENV_PYINSTALLER}")
    for d in (BUILD_WORK, BUILD_DIST):
        if d.exists():
            shutil.rmtree(d)

    run(
        [
            str(VENV_PYINSTALLER),
            "--noconfirm",
            "--clean",
            "--workpath",
            str(BUILD_WORK),
            "--distpath",
            str(BUILD_DIST),
            str(PACKAGING_DIR / "PaperDiff.spec"),
        ],
        cwd=PAPERDIFF_ROOT,
    )

    app_bundle = BUILD_DIST / "PaperDiff.app"
    if not app_bundle.exists():
        raise RuntimeError(f"Expected .app bundle not found: {app_bundle}")

    # Ad-hoc sign the bundle so Apple Silicon macOS launches cleanly
    run(["codesign", "--force", "--deep", "--sign", "-", str(app_bundle)])
    run(["codesign", "--verify", "--deep", "--strict", str(app_bundle)])
    print(f"✓ Signed and verified {app_bundle}")
    return app_bundle


def smoke_test_frozen_app(app_bundle: Path) -> None:
    binary = app_bundle / "Contents" / "MacOS" / "PaperDiff"
    with tempfile.TemporaryDirectory(prefix="paperdiff_smoke_") as tmpdir:
        env = os.environ.copy()
        env["PAPERDIFF_SMOKE_TEST"] = "1"
        env["PAPERDIFF_DATA_DIR"] = tmpdir
        env["PAPERDIFF_PORT"] = "18943"
        run([str(binary)], env=env)
        db_file = Path(tmpdir) / "paperdiff.db"
        assert db_file.exists() and db_file.stat().st_size > 4096, "SQLite DB not created in DATA_DIR"
    print("✓ Frozen .app headless smoke test PASSED (FastAPI + SPA + SQLite + jieba + python-docx)")


def build_dmg(app_bundle: Path) -> Path:
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    if DMG_PATH.exists():
        DMG_PATH.unlink()

    # Copy standalone .app into release/ as well for immediate testing
    release_app = RELEASE_DIR / "PaperDiff.app"
    if release_app.exists():
        shutil.rmtree(release_app)
    shutil.copytree(app_bundle, release_app, symlinks=True)

    with tempfile.TemporaryDirectory(prefix="paperdiff_dmg_stage_") as stage_str:
        stage = Path(stage_str)
        # Copy .app with symlinks preserved
        shutil.copytree(app_bundle, stage / "PaperDiff.app", symlinks=True)
        # Standard drag-to-Applications symlink
        os.symlink("/Applications", stage / "Applications")
        # Include concise user guide
        if GUIDE_MD.exists():
            shutil.copy2(GUIDE_MD, stage / "产品使用指南.md")
        # Add concise macOS installation readme
        (stage / "首次打开说明.txt").write_text(
            f"对稿 · PaperDiff (v{VERSION})\n"
            "=========================\n\n"
            "1. 将 PaperDiff.app 拖入右侧「应用程序」即可安装。\n"
            "2. 所有文件与记录仅保存在本机，不会联网上传。\n"
            "3. 若系统提示「无法验证开发者」：\n"
            "   右键点击 PaperDiff.app → 打开 → 再次点击「打开」，\n"
            "   或在终端执行：xattr -cr /Applications/PaperDiff.app\n",
            encoding="utf-8",
        )

        # Build compressed read-only UDZO DMG directly from staging directory
        run(
            [
                "hdiutil",
                "create",
                "-volname",
                f"对稿 PaperDiff {VERSION}",
                "-srcfolder",
                str(stage),
                "-ov",
                "-format",
                "UDZO",
                "-imagekey",
                "zlib-level=9",
                str(DMG_PATH),
            ]
        )

    run(["hdiutil", "verify", str(DMG_PATH)])

    # Mount the freshly created DMG read-only and verify its embedded .app matches frontend/dist bit-for-bit
    with tempfile.TemporaryDirectory(prefix="paperdiff_dmg_verify_") as mnt_dir:
        run(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", mnt_dir, str(DMG_PATH)])
        try:
            mounted_app = Path(mnt_dir) / "PaperDiff.app"
            verify_bundle_freshness(mounted_app, label=f"Mounted {DMG_NAME}")
        finally:
            subprocess.run(["hdiutil", "detach", mnt_dir, "-force"], check=False)

    size_mb = DMG_PATH.stat().st_size / (1024 * 1024)
    digest = hashlib.sha256(DMG_PATH.read_bytes()).hexdigest()
    sums_path = RELEASE_DIR / "SHA256SUMS.txt"
    sums_path.write_text(f"{digest}  {DMG_PATH.name}\n", encoding="utf-8")
    print(f"✓ Built and verified DMG: {DMG_PATH} ({size_mb:.1f} MB)")
    print(f"✓ SHA-256: {digest} (saved to {sums_path})")
    return DMG_PATH


def main() -> None:
    print(f"=== Building 对稿 · PaperDiff v{VERSION} (macOS {ARCH}) ===")
    build_frontend()
    build_icns()
    app_bundle = build_app_bundle()
    verify_bundle_freshness(app_bundle, label="Built PaperDiff.app")
    smoke_test_frozen_app(app_bundle)
    dmg = build_dmg(app_bundle)

    # Clean up temporary build_work/dist_out to keep repo tidy
    for d in (BUILD_WORK, BUILD_DIST):
        if d.exists():
            shutil.rmtree(d)

    print(f"\n🎉 Release ready:\n   App: {RELEASE_DIR / 'PaperDiff.app'}\n   DMG: {dmg}")


if __name__ == "__main__":
    main()
