"""SHA-256 Deduplicated Media Asset Store, Source Binary Blob Archive & BibTeX Parser.

Responsibilities:
    - `save_blob_bytes` / `get_blob_path`: Archive raw uploaded `.docx` templates and Overleaf
      `.zip` bundles in `DATA_DIR/blobs/` for pixel-identical `docx-preview` viewing and
      format-preserving round-trip patching (`backend.patcher`).
    - `save_asset_bytes` / `get_asset_path`: Deduplicate embedded figures (PNG/JPG/SVG/WEBP/GIF)
      and rasterize vector `.pdf` figures via macOS `sips` / `qlmanage` when available.
    - `parse_bibtex_entries`: Lightweight zero-dependency BibTeX parser populating `.bib` hover cards.

Security invariant:
    All asset/blob keys are validated against `SAFE_ASSET_KEY_RE` to prevent path traversal.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .database import DATA_DIR

ASSETS_DIR = DATA_DIR / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
BLOBS_DIR = DATA_DIR / "blobs"
BLOBS_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
ALLOWED_BLOB_EXTS = {".docx", ".zip"}
SAFE_ASSET_KEY_RE = re.compile(r"^[a-f0-9]{16,40}\.[a-z0-9]{2,5}$")


def save_blob_bytes(raw_bytes: bytes, ext: str) -> str | None:
    """Archive an original binary source package (.docx / .zip) with SHA-256 deduplication."""
    if not raw_bytes:
        return None
    norm_ext = ext.lower() if ext.startswith(".") else f".{ext.lower()}"
    if norm_ext not in ALLOWED_BLOB_EXTS:
        return None
    digest = hashlib.sha256(raw_bytes).hexdigest()[:24]
    key = f"{digest}{norm_ext}"
    target = BLOBS_DIR / key
    if not target.exists():
        target.write_bytes(raw_bytes)
    return key


def get_blob_path(blob_key: str | None) -> Path | None:
    if not blob_key or not SAFE_ASSET_KEY_RE.fullmatch(blob_key):
        return None
    p = BLOBS_DIR / blob_key
    if p.exists() and p.is_file():
        return p
    return None


def save_asset_bytes(raw_bytes: bytes, ext: str) -> str | None:
    """
    Save an image asset using SHA-256 content-addressed deduplication.
    For PDF figures (common in LaTeX/Overleaf), convert page 1 to PNG via macOS sips.
    Returns asset_key (e.g. 'a1b2c3d4e5f60708.png') or None if unsupported.
    """
    if not raw_bytes:
        return None
    norm_ext = ext.lower()
    if not norm_ext.startswith("."):
        norm_ext = "." + norm_ext
    if norm_ext == ".jpeg":
        norm_ext = ".jpg"

    digest = hashlib.sha256(raw_bytes).hexdigest()[:20]

    if norm_ext in ALLOWED_IMAGE_EXTS:
        key = f"{digest}{norm_ext}"
        target = ASSETS_DIR / key
        if not target.exists():
            target.write_bytes(raw_bytes)
        return key

    if norm_ext == ".pdf":
        key = f"{digest}.png"
        target = ASSETS_DIR / key
        if target.exists():
            return key
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                pdf_path = Path(tmpdir) / "fig.pdf"
                png_path = Path(tmpdir) / "fig.png"
                pdf_path.write_bytes(raw_bytes)
                res = subprocess.run(
                    ["sips", "-s", "format", "png", "--resampleWidth", "1400", str(pdf_path), "--out", str(png_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=8,
                    check=False,
                )
                if res.returncode == 0 and png_path.exists() and png_path.stat().st_size > 0:
                    target.write_bytes(png_path.read_bytes())
                    return key
        except Exception:
            return None

    return None


def get_asset_path(asset_key: str) -> Path | None:
    if not SAFE_ASSET_KEY_RE.fullmatch(asset_key):
        return None
    p = ASSETS_DIR / asset_key
    if p.exists() and p.is_file():
        return p
    return None


def _clean_bib_value(val: str) -> str:
    s = val.strip().rstrip(",").strip()
    if (s.startswith("{") and s.endswith("}")) or (s.startswith('"') and s.endswith('"')):
        s = s[1:-1].strip()
    s = re.sub(r"[{}]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def parse_bibtex_entries(bib_text: str) -> dict[str, dict[str, str]]:
    """Lightweight BibTeX parser extracting citekey -> {title, author, year, venue}."""
    entries: dict[str, dict[str, str]] = {}
    if not bib_text.strip():
        return entries

    entry_re = re.compile(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", re.IGNORECASE)
    matches = list(entry_re.finditer(bib_text))
    for i, m in enumerate(matches):
        etype = m.group(1).lower()
        if etype in ("string", "preamble", "comment"):
            continue
        key = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(bib_text)
        body = bib_text[start:end]

        info: dict[str, str] = {"type": etype}
        # Match field = {value} or field = "value" or field = 2024
        pos = 0
        while pos < len(body):
            fm = re.search(r"([A-Za-z_][A-Za-z0-9_-]*)\s*=\s*", body[pos:])
            if not fm:
                break
            fname = fm.group(1).lower()
            vpos = pos + fm.end()
            while vpos < len(body) and body[vpos].isspace():
                vpos += 1
            if vpos >= len(body):
                break
            ch = body[vpos]
            if ch == "{":
                depth = 0
                j = vpos
                while j < len(body):
                    if body[j] == "{":
                        depth += 1
                    elif body[j] == "}":
                        depth -= 1
                        if depth == 0:
                            j += 1
                            break
                    j += 1
                raw_val = body[vpos:j]
                pos = j
            elif ch == '"':
                j = vpos + 1
                while j < len(body):
                    if body[j] == '"' and body[j - 1] != "\\":
                        j += 1
                        break
                    j += 1
                raw_val = body[vpos:j]
                pos = j
            else:
                cm = re.search(r"[,\n\}]", body[vpos:])
                j = vpos + cm.start() if cm else len(body)
                raw_val = body[vpos:j]
                pos = j

            if fname in ("title", "author", "year", "journal", "booktitle", "publisher", "doi"):
                val = _clean_bib_value(raw_val)
                if fname in ("journal", "booktitle"):
                    info["venue"] = val
                else:
                    info[fname] = val

        if key:
            entries[key] = info
    return entries
