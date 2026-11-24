"""Unified Typed Patch Op dispatcher for LaTeX (.tex / .zip), Word (.docx), and Markdown (.md)."""
from __future__ import annotations

from typing import Any

from .docx_patcher import patch_docx_bytes
from .latex_patcher import patch_latex_content, patch_latex_zip_bytes
from .md_patcher import patch_markdown_content


def apply_typed_patches(
    content: str,
    fmt: str,
    blocks: list[dict[str, Any]],
    ops: list[dict[str, Any]],
    *,
    orig_blob_bytes: bytes | None = None,
    source_map: list[dict[str, Any]] | None = None,
    docx_mode: str = "clean",
    author: str = "PaperDiff",
) -> dict[str, Any]:
    """
    Apply structured Typed Patch Ops to any supported source format.
    Returns {
      'patched_content': str,
      'patched_blob_bytes': bytes | None,
      'patched_blob_ext': str | None,
      'applied_count': int,
      'warnings': list[str],
    }
    """
    if not ops:
        return {
            "patched_content": content,
            "patched_blob_bytes": orig_blob_bytes,
            "patched_blob_ext": None,
            "applied_count": 0,
            "warnings": [],
        }

    if fmt == "latex":
        if orig_blob_bytes and source_map:
            zip_bytes, patched_tex, applied, warnings = patch_latex_zip_bytes(
                orig_blob_bytes, source_map, content, blocks, ops
            )
            return {
                "patched_content": patched_tex,
                "patched_blob_bytes": zip_bytes,
                "patched_blob_ext": ".zip",
                "applied_count": applied,
                "warnings": warnings,
            }
        patched_tex, applied, warnings = patch_latex_content(content, blocks, ops)
        return {
            "patched_content": patched_tex,
            "patched_blob_bytes": None,
            "patched_blob_ext": None,
            "applied_count": applied,
            "warnings": warnings,
        }

    if fmt == "docx":
        patched_md, applied_md, w_md = patch_markdown_content(content, blocks, ops)
        patched_docx: bytes | None = None
        w_docx: list[str] = []
        applied_docx = 0
        if orig_blob_bytes:
            patched_docx, applied_docx, w_docx = patch_docx_bytes(
                orig_blob_bytes, blocks, ops, mode=docx_mode, author=author
            )
        return {
            "patched_content": patched_md,
            "patched_blob_bytes": patched_docx,
            "patched_blob_ext": ".docx" if patched_docx else None,
            "applied_count": max(applied_md, applied_docx),
            "warnings": w_md + w_docx,
        }

    patched_md, applied, warnings = patch_markdown_content(content, blocks, ops)
    return {
        "patched_content": patched_md,
        "patched_blob_bytes": None,
        "patched_blob_ext": None,
        "applied_count": applied,
        "warnings": warnings,
    }


__all__ = [
    "apply_typed_patches",
    "patch_docx_bytes",
    "patch_latex_content",
    "patch_latex_zip_bytes",
    "patch_markdown_content",
]
