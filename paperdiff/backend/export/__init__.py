"""Unified v1.1.0 export package combining offline PDF/Print engines and legacy exporters."""
from __future__ import annotations

from ..exporter import (
    apply_single_document_edits,
    export_docx_merged_bytes,
    export_docx_tracked_bytes,
    export_html_report,
    export_latexdiff_tex,
    export_markdown_summary,
    export_merged_document,
    export_single_html_report,
)
from .html_print import (
    generate_change_commentary,
    render_diff_print_html,
    render_single_print_html,
)
from .pdf_exporter import find_local_chrome, render_html_to_pdf_bytes

__all__ = [
    "apply_single_document_edits",
    "export_docx_merged_bytes",
    "export_docx_tracked_bytes",
    "export_html_report",
    "export_latexdiff_tex",
    "export_markdown_summary",
    "export_merged_document",
    "export_single_html_report",
    "find_local_chrome",
    "generate_change_commentary",
    "render_diff_print_html",
    "render_html_to_pdf_bytes",
    "render_single_print_html",
]
