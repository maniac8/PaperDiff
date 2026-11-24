"""Unified Academic Intermediate Representation (IR) and shared marker helpers."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DocumentBlock:
    index: int
    # 'title' | 'heading' | 'paragraph' | 'caption' | 'figure' | 'math' | 'table'
    # | 'list' | 'blockquote' | 'code' | 'hr' | 'reference_item' | 'theorem' | 'algorithm'
    block_type: str
    section_title: str
    section_level: int
    raw_text: str
    clean_text: str
    raw_start: int | None = None
    raw_end: int | None = None
    zone: str = "body"  # 'frontmatter' | 'body' | 'backmatter'
    source_anchor: dict[str, Any] | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def detect_format(filename: str, content: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in (".tex", ".ltx", ".zip"):
        return "latex"
    if ext == ".docx":
        return "docx"
    if ext in (".md", ".markdown"):
        return "markdown"
    latex_signals = [
        r"\\documentclass",
        r"\\begin\{document\}",
        r"\\chapter\*?\{",
        r"\\section\*?\{",
        r"\\subsection\*?\{",
        r"\\cite[pt]?\{",
        r"\\ref\{",
        r"\\eqref\{",
        r"\\textbf\{",
        r"\\emph\{",
    ]
    hits = sum(1 for pat in latex_signals if re.search(pat, content))
    if hits >= 1:
        return "latex"
    if re.search(r"^#{1,6}\s+", content, re.MULTILINE):
        return "markdown"
    return "text"


def _strip_inline_markers_fast(s: str) -> str:
    if not s or "⟦" not in s:
        return s
    s = re.sub(r"⟦/?[BIS]⟧", "", s)
    s = s.replace("⟦BR⟧", " ")
    s = re.sub(r"⟦SP:[^⟧]+⟧", " ", s)
    s = re.sub(r"⟦FN:([^⟧]+)⟧", r"[\1]", s)
    s = re.sub(r"⟦REF:([^|⟧]+)\|([^⟧]+)⟧", r"\2", s)
    s = re.sub(r"⟦LINK:([^|⟧]+)\|[^⟧]+⟧", r"\1", s)
    s = re.sub(r"⟦(?:REF|CITE|MATH|CODE|LINK):(.*?)⟧", r"\1", s)
    return s


def normalize_block_style(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize and clamp optional block typography metadata.

    Ensures out-of-range indentation values or casing differences from Word OOXML,
    LaTeX AST, or Markdown cannot push text out of the viewport or pollute JSON.

    Args:
        raw: Optional raw style dictionary emitted by a format parser.

    Returns:
        A compact, clamped dictionary containing only valid non-None typography keys.
    """
    if not raw or not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}

    def _clamp_float(val: Any, lo: float, hi: float) -> float | None:
        if val is None or isinstance(val, bool):
            return None
        try:
            f = float(val)
        except (TypeError, ValueError):
            return None
        return round(max(lo, min(hi, f)), 2)

    def _clamp_int(val: Any, lo: int, hi: int) -> int | None:
        if val is None or isinstance(val, bool):
            return None
        try:
            n = int(val)
        except (TypeError, ValueError):
            return None
        return max(lo, min(hi, n))

    for key, hi in (
        ("first_line_indent_em", 4.0),
        ("hanging_indent_em", 4.0),
        ("left_indent_em", 8.0),
        ("right_indent_em", 8.0),
    ):
        v = _clamp_float(raw.get(key), 0.0, hi)
        if v is not None:
            out[key] = v

    align_raw = raw.get("align")
    if isinstance(align_raw, str):
        al = align_raw.strip().lower()
        if al in ("left", "center", "right", "justify"):
            out["align"] = al

    exp_raw = raw.get("explicit_indent")
    if isinstance(exp_raw, str):
        ex = exp_raw.strip().lower()
        if ex in ("indent", "none"):
            out["explicit_indent"] = ex

    qd = _clamp_int(raw.get("quote_depth"), 1, 4)
    if qd is not None:
        out["quote_depth"] = qd

    pld = _clamp_int(raw.get("parent_list_depth"), 0, 5)
    if pld is not None:
        out["parent_list_depth"] = pld

    ld = _clamp_int(raw.get("list_depth"), 0, 5)
    if ld is not None:
        out["list_depth"] = ld

    role_raw = raw.get("semantic_role")
    if isinstance(role_raw, str):
        rl = role_raw.strip().lower()
        if rl in ("abstract", "keywords"):
            out["semantic_role"] = rl

    return out


def _resolve_asset_key(image_path: str, asset_map: dict[str, str] | None) -> str | None:
    if not image_path or not asset_map:
        return None
    clean = image_path.strip()
    if clean.startswith("asset://"):
        cand = clean[len("asset://") :]
        return asset_map.get(cand, cand)
    p = Path(clean)
    stem_rel = str(p.with_suffix(""))
    for k in (clean, clean.lower(), stem_rel, stem_rel.lower(), p.name, p.name.lower(), p.stem, p.stem.lower()):
        if k in asset_map:
            return asset_map[k]
    return None


def _clean_latex_display_math(raw_env: str, env_name: str | None = None) -> str:
    inner = raw_env.strip()
    inner = re.sub(r"^\\begin\{[^}]+\}|\\end\{[^}]+\}$", "", inner).strip()
    inner = re.sub(r"^\\\[|\\\]$", "", inner).strip()
    inner = re.sub(r"^\$\$|\$\$$", "", inner).strip()
    inner = re.sub(r"\\label\{[^}]+\}", "", inner)
    inner = re.sub(r"\\(?:nonumber|notag)\b", "", inner)
    inner = re.sub(r"\s+", " ", inner).strip()
    if env_name in ("align", "eqnarray", "gather", "multline", "flalign", "alignat") and (
        r"\\" in inner or "&" in inner
    ):
        if not re.search(r"\\begin\{(?:aligned|cases|split|matrix|pmatrix|bmatrix|array|gathered)", inner):
            inner = rf"\begin{{aligned}} {inner} \end{{aligned}}"
    return inner
