"""Backward-compatible re-export of backend.parsers.omml."""
from .parsers.omml import M_NS, format_word_vert_align, omml_to_latex

__all__ = ["M_NS", "format_word_vert_align", "omml_to_latex"]
