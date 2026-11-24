"""Unified modular parser package for PaperDiff Studio v1.1.0.

Exports:
- DocumentBlock, detect_format
- parse_document, parse_document_with_meta
- parse_latex_document, parse_latex_with_meta, extract_latex_zip_with_assets, extract_latex_zip_bytes, format_bib_entry_text
- parse_markdown_or_text, parse_markdown_with_meta, normalize_plain_or_md_inline
- extract_docx_with_assets, extract_docx_bytes, inspect_docx_tracked_changes
"""
from __future__ import annotations

from typing import Any

from .docx_parser import (
    extract_docx_bytes,
    extract_docx_with_assets,
    inspect_docx_tracked_changes,
)
from .ir import (
    DocumentBlock,
    _clean_latex_display_math,
    _resolve_asset_key,
    _strip_inline_markers_fast,
    detect_format,
    normalize_block_style,
)
from .latex_parser import (
    extract_latex_preamble_info,
    extract_latex_zip_bytes,
    extract_latex_zip_with_assets,
    format_bib_entry_text,
    normalize_latex_inline,
    parse_latex_document,
    parse_latex_with_meta,
)
from .md_parser import (
    normalize_plain_or_md_inline,
    parse_markdown_or_text,
    parse_markdown_with_meta,
)
from .omml import M_NS, format_word_vert_align, omml_to_latex
from .zones import _classify_document_zones, _is_metadata_form_table


def parse_document_with_meta(
    content: str,
    fmt: str = "auto",
    filename: str = "",
    asset_map: dict[str, str] | None = None,
    bib_entries: dict[str, Any] | None = None,
    bbl_content: str | None = None,
) -> tuple[str, list[DocumentBlock], dict[str, Any]]:
    effective_fmt = detect_format(filename, content) if fmt in ("", "auto") else fmt
    if effective_fmt == "latex":
        blocks, doc_meta = parse_latex_with_meta(
            content,
            asset_map=asset_map,
            bib_entries=bib_entries,
            bbl_content=bbl_content,
        )
        return "latex", blocks, doc_meta
    blocks, doc_meta = parse_markdown_with_meta(content, asset_map=asset_map)
    return effective_fmt, blocks, doc_meta


def parse_document(
    content: str,
    fmt: str = "auto",
    filename: str = "",
    asset_map: dict[str, str] | None = None,
    bib_entries: dict[str, Any] | None = None,
    bbl_content: str | None = None,
) -> tuple[str, list[DocumentBlock]]:
    eff_fmt, blocks, _ = parse_document_with_meta(
        content,
        fmt=fmt,
        filename=filename,
        asset_map=asset_map,
        bib_entries=bib_entries,
        bbl_content=bbl_content,
    )
    return eff_fmt, blocks


__all__ = [
    "DocumentBlock",
    "M_NS",
    "detect_format",
    "extract_docx_bytes",
    "extract_docx_with_assets",
    "extract_latex_preamble_info",
    "extract_latex_zip_bytes",
    "extract_latex_zip_with_assets",
    "format_bib_entry_text",
    "format_word_vert_align",
    "inspect_docx_tracked_changes",
    "normalize_block_style",
    "normalize_latex_inline",
    "normalize_plain_or_md_inline",
    "omml_to_latex",
    "parse_document",
    "parse_document_with_meta",
    "parse_latex_document",
    "parse_latex_with_meta",
    "parse_markdown_or_text",
    "parse_markdown_with_meta",
]
