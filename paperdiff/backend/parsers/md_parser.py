"""Open-source AST Markdown parser powered by markdown-it-py + mdit-py-plugins.

Supports 100% CommonMark & GFM plus academic extensions:
- YAML frontmatter, dollarmath ($...$ / $$...$$), amsmath (\begin{equation} / align)
- Footnotes ([^1] + footnote definitions dictionary)
- GitHub-style Callouts (> [!NOTE|TIP|IMPORTANT|WARNING|CAUTION])
- Task lists (- [x] / - [ ]), Definition lists, Strikethrough (~~...~~)
- Fenced code blocks (language metadata + Mermaid diagram flagging)
- Rich GFM tables (alignments, <br>, inline math/code, Word merged-cell comment pass-through)
- Exact line-range source_anchor & character offsets for format-preserving patching
"""
from __future__ import annotations

import html
import json
import re
from typing import Any

from markdown_it import MarkdownIt
from mdit_py_plugins.amsmath import amsmath_plugin
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.front_matter import front_matter_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

from .ir import (
    DocumentBlock,
    _clean_latex_display_math,
    _resolve_asset_key,
    _strip_inline_markers_fast,
    normalize_block_style,
)
from .omml import format_word_vert_align
from .zones import (
    _BACKMATTER_HEADING_RE,
    _BODY_START_HEADING_RE,
    _REF_HEADING_RE,
    _classify_document_zones,
    _is_metadata_form_table,
)

# Shared singleton MarkdownIt instance (zero per-call initialization overhead)
_MD_ENGINE = (
    MarkdownIt("gfm-like", {"html": True, "breaks": False, "linkify": False})
    .use(front_matter_plugin)
    .use(
        dollarmath_plugin,
        allow_labels=True,
        allow_space=True,
        allow_digits=True,
        double_inline=True,
    )
    .use(amsmath_plugin)
    .use(footnote_plugin)
    .use(tasklists_plugin)
    .use(deflist_plugin)
)

_CALLOUT_RE = re.compile(
    r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(?:⟦BR⟧|\n|\s)*",
    re.IGNORECASE,
)


def normalize_plain_or_md_inline(raw: str, *, keep_bold_markers: bool = True) -> str:
    """
    Convert Markdown inline syntax into clean rich academic text preserving:
    - Inline code (`...`) -> ⟦CODE:...⟧ (stashed FIRST)
    - Inline/embedded math ($...$, \\(...\\), $$...$$) -> ⟦MATH:...⟧
    - Line breaks (<br>) -> ⟦BR⟧, HTML entities (&nbsp;, &amp;, etc.), <sup>/<sub>
    - Markdown links [text](url) -> ⟦LINK:text|url⟧
    - Strikethrough (~~...~~) -> ⟦S⟧...⟦/S⟧
    - Bold (**...**) -> ⟦B⟧...⟦/B⟧ and Italic (*...*) -> ⟦I⟧...⟦/I⟧
    - Footnotes [^id] -> ⟦FN:id⟧ and LaTeX \\ref / \\cite chips
    """
    s = raw.strip()
    if not s:
        return ""

    code_store: list[str] = []
    math_store: list[str] = []
    link_store: list[str] = []

    def _stash_code(m: re.Match[str]) -> str:
        idx = len(code_store)
        code_store.append(m.group(1))
        return f"__CODE_HOLD_{idx}__"

    def _stash_math(expr: str) -> str:
        cleaned = re.sub(r"\s+", " ", expr.strip())
        idx = len(math_store)
        math_store.append(cleaned)
        return f"__MATH_HOLD_{idx}__"

    def _stash_link(m: re.Match[str]) -> str:
        idx = len(link_store)
        lbl = m.group(1).strip()
        url = m.group(2).strip()
        link_store.append(f"{lbl}|{url}")
        return f"__LINK_HOLD_{idx}__"

    # 1. Inline code FIRST
    s = re.sub(r"``([^`]+)``", _stash_code, s)
    s = re.sub(r"`([^`\n]+)`", _stash_code, s)

    # 2. Inline/embedded math BEFORE emphasis
    s = re.sub(r"\$\$(.+?)\$\$", lambda m: _stash_math(m.group(1)), s, flags=re.DOTALL)
    s = re.sub(r"\\\((.+?)\\\)", lambda m: _stash_math(m.group(1)), s)
    s = re.sub(
        r"(?<!\\)(?<!\$)\$(?!\$)(?!\s)([^\n$]+?)(?<!\s)(?<!\\)\$(?!\$)",
        lambda m: _stash_math(m.group(1)),
        s,
    )
    s = re.sub(
        r"(?<!\\)(?<!\$)\$(?!\$)([^\s$])(?<!\\)\$(?!\$)",
        lambda m: _stash_math(m.group(1)),
        s,
    )

    # 3. HTML inline tags (<br>, <sup>, <sub>, entities) & links
    s = re.sub(r"<br\s*/?>", "⟦BR⟧", s, flags=re.IGNORECASE)
    s = re.sub(
        r"<sup>(.*?)</sup>",
        lambda m: format_word_vert_align(m.group(1), "superscript"),
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"<sub>(.*?)</sub>",
        lambda m: format_word_vert_align(m.group(1), "subscript"),
        s,
        flags=re.IGNORECASE,
    )
    s = s.replace("&nbsp;", " ")
    s = html.unescape(s)
    s = re.sub(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)", _stash_link, s)

    # 4. Footnotes [^id]
    s = re.sub(r"\[\^([^\s\]]+)\]", r"⟦FN:\1⟧", s)

    # 5. Strikethrough, Bold, Italic
    s = re.sub(r"~~([^\s~](?:[^~\n]*?[^\s~])?)~~", r"⟦S⟧\1⟦/S⟧", s)
    if keep_bold_markers:
        s = re.sub(r"\*\*\*([^\s*](?:[^*]*?[^\s*])?)\*\*\*", r"⟦B⟧⟦I⟧\1⟦/I⟧⟦/B⟧", s)
        s = re.sub(r"\*\*([^\s*](?:(?:(?!\*\*).)*?[^\s*])?)\*\*", r"⟦B⟧\1⟦/B⟧", s)
        s = re.sub(r"(?<!\w)__([^\s_](?:[^_]*?[^\s_])?)__(?!\w)", r"⟦B⟧\1⟦/B⟧", s)
    else:
        s = re.sub(r"\*\*\*([^\s*](?:[^*]*?[^\s*])?)\*\*\*", r"\1", s)
        s = re.sub(r"\*\*([^\s*](?:(?:(?!\*\*).)*?[^\s*])?)\*\*", r"\1", s)
        s = re.sub(r"(?<!\w)__([^\s_](?:[^_]*?[^\s_])?)__(?!\w)", r"\1", s)

    s = re.sub(r"(?<!\*)\*([^\s*](?:[^*\n]*?[^\s*])?)\*(?!\*)", r"⟦I⟧\1⟦/I⟧", s)
    s = re.sub(r"(?<!\w)_([^\s_](?:[^_\n]*?[^\s_])?)_(?!\w)", r"⟦I⟧\1⟦/I⟧", s)

    # 6. Mixed LaTeX ref/cite chips
    s = re.sub(r"\\(?:eq|c|C|auto)?ref\{([^}]+)\}", lambda m: f"⟦REF:{m.group(1).strip()}⟧", s)
    s = re.sub(r"\\cite[pt]*\{([^}]+)\}", lambda m: "⟦CITE:" + re.sub(r"\s+", "", m.group(1).strip()) + "⟧", s)
    s = re.sub(r"\[(fig|tab|sec|eq|alg|app):([^\]]+)\]", r"⟦REF:\1:\2⟧", s)

    # 7. Restore stashed spans
    for idx, val in enumerate(link_store):
        s = s.replace(f"__LINK_HOLD_{idx}__", f"⟦LINK:{val}⟧")
    for idx, expr in enumerate(math_store):
        s = s.replace(f"__MATH_HOLD_{idx}__", f"⟦MATH:{expr}⟧")
    for idx, code_txt in enumerate(code_store):
        s = s.replace(f"__CODE_HOLD_{idx}__", f"⟦CODE:{code_txt}⟧")

    # Convert any leftover $...$ created by format_word_vert_align
    s = re.sub(
        r"(?<!\\)(?<!\$)\$(?!\$)([^\n$]+?)(?<!\\)\$(?!\$)",
        lambda m: f"⟦MATH:{m.group(1).strip()}⟧",
        s,
    )

    s = re.sub(r"[ \t]+", " ", s).strip()
    s = re.sub(r"\s*⟦BR⟧\s*", "⟦BR⟧", s)
    return s


def _preprocess_md_preserving_lines(text: str) -> str:
    """
    Lightweight line-preserving pre-pass before markdown-it-py:
    - Converts standalone `\\[` / `\\]` display math delimiters (outside fenced code blocks)
      into `$$` while keeping line count 1-to-1 so token.map line numbers remain exact!
    """
    lines = text.split("\n")
    in_fence = False
    fence_char = ""
    fence_len = 0
    out: list[str] = []
    for ln in lines:
        s = ln.strip()
        fm = re.match(r"^(`{3,}|~{3,})", s)
        if fm:
            fc = fm.group(1)[0]
            fl = len(fm.group(1))
            if not in_fence:
                in_fence = True
                fence_char = fc
                fence_len = fl
            elif fc == fence_char and fl >= fence_len and s == fc * len(s):
                in_fence = False
            out.append(ln)
            continue
        if in_fence:
            out.append(ln)
            continue
        if s == r"\[":
            out.append(ln.replace(r"\[", "$$", 1))
        elif s == r"\]":
            out.append(ln.replace(r"\]", "$$", 1))
        elif s.startswith(r"\[") and s.endswith(r"\]") and len(s) > 4:
            lead = ln[: len(ln) - len(ln.lstrip())]
            out.append(f"{lead}$${s[2:-2]}$$")
        else:
            out.append(ln)
    return "\n".join(out)


def _postprocess_plain_text_segment(txt: str) -> str:
    """Process plain text chunks from markdown-it AST for mixed LaTeX refs/cites/inline-math/footnotes."""
    if not txt:
        return ""
    s = txt.replace("&nbsp;", " ")
    s = html.unescape(s)
    # Mixed \( ... \) inline math
    if r"\(" in s:
        s = re.sub(r"\\\((.+?)\\\)", lambda m: "⟦MATH:" + re.sub(r"\s+", " ", m.group(1).strip()) + "⟧", s)
    if "\\" in s:
        s = re.sub(r"\\(?:eq|c|C|auto)?ref\{([^}]+)\}", lambda m: f"⟦REF:{m.group(1).strip()}⟧", s)
        s = re.sub(r"\\cite[pt]*\{([^}]+)\}", lambda m: "⟦CITE:" + re.sub(r"\s+", "", m.group(1).strip()) + "⟧", s)
    if "[" in s:
        s = re.sub(r"\[(fig|tab|sec|eq|alg|app):([^\]]+)\]", r"⟦REF:\1:\2⟧", s)
        # Fallback for unreferenced [^id] markers (e.g. emitted from DOCX footnotes)
        s = re.sub(r"\[\^([^\s\]]+)\]", r"⟦FN:\1⟧", s)
    return s


def _render_inline_children(
    children: list[Any] | None,
    *,
    keep_bold_markers: bool = True,
    softbreak_as_br: bool = False,
) -> tuple[str, list[str], bool | None]:
    """
    Convert a markdown-it inline token's children into PaperDiff rich text.
    Returns (clean_text, extracted_display_maths, task_checked_or_None).
    """
    if not children:
        return "", [], None

    out: list[str] = []
    display_maths: list[str] = []
    task_checked: bool | None = None
    in_sup = False
    in_sub = False
    sup_buf: list[str] = []
    sub_buf: list[str] = []

    idx = 0
    n = len(children)

    def _append(val: str) -> None:
        if in_sup:
            sup_buf.append(val)
        elif in_sub:
            sub_buf.append(val)
        else:
            out.append(val)

    while idx < n:
        tok = children[idx]
        ttype = tok.type

        if ttype == "text":
            _append(_postprocess_plain_text_segment(tok.content))
        elif ttype == "code_inline":
            _append(f"⟦CODE:{tok.content}⟧")
        elif ttype == "math_inline":
            expr = re.sub(r"\s+", " ", tok.content.strip())
            if expr:
                _append(f"⟦MATH:{expr}⟧")
        elif ttype == "math_inline_double":
            expr = _clean_latex_display_math(tok.content)
            # If this $$...$$ was on its own line (preceded by softbreak or start, and followed by softbreak or end),
            # extract as a standalone display equation block for crisp centered rendering!
            prev_is_break = idx == 0 or children[idx - 1].type in ("softbreak", "hardbreak")
            next_is_break = idx == n - 1 or children[idx + 1].type in ("softbreak", "hardbreak")
            is_multiline = "\n" in tok.content
            if expr and (is_multiline or (prev_is_break and next_is_break and len(expr) >= 12)):
                display_maths.append(expr)
            elif expr:
                _append(f"⟦MATH:{expr}⟧")
        elif ttype == "strong_open":
            if keep_bold_markers:
                _append("⟦B⟧")
        elif ttype == "strong_close":
            if keep_bold_markers:
                _append("⟦/B⟧")
        elif ttype == "em_open":
            _append("⟦I⟧")
        elif ttype == "em_close":
            _append("⟦/I⟧")
        elif ttype == "s_open":
            _append("⟦S⟧")
        elif ttype == "s_close":
            _append("⟦/S⟧")
        elif ttype == "hardbreak":
            _append("⟦BR⟧")
        elif ttype == "softbreak":
            _append("⟦BR⟧" if softbreak_as_br else " ")
        elif ttype == "footnote_ref":
            lbl = str((tok.meta or {}).get("label") or (tok.meta or {}).get("id", ""))
            if lbl:
                _append(f"⟦FN:{lbl}⟧")
        elif ttype == "link_open":
            href = tok.attrGet("href") or ""
            # Collect link label tokens until link_close
            lbl_parts: list[str] = []
            idx += 1
            while idx < n and children[idx].type != "link_close":
                sub_t = children[idx]
                if sub_t.type in ("text", "code_inline"):
                    lbl_parts.append(sub_t.content)
                elif sub_t.type == "math_inline":
                    lbl_parts.append(sub_t.content)
                idx += 1
            lbl = "".join(lbl_parts).strip() or href
            if href:
                _append(f"⟦LINK:{lbl}|{href}⟧")
            else:
                _append(lbl)
        elif ttype == "image":
            alt = tok.content or (tok.children[0].content if tok.children else "")
            if alt:
                _append(alt)
        elif ttype == "html_inline":
            raw_h = tok.content.strip()
            low_h = raw_h.lower()
            if "task-list-item-checkbox" in low_h:
                task_checked = 'checked="checked"' in low_h or "checked" in low_h
            elif re.fullmatch(r"<br\s*/?>", low_h):
                _append("⟦BR⟧")
            elif low_h == "<sup>":
                in_sup = True
                sup_buf = []
            elif low_h == "</sup>":
                in_sup = False
                formatted = format_word_vert_align("".join(sup_buf), "superscript")
                if formatted.startswith("$") and formatted.endswith("$"):
                    out.append(f"⟦MATH:{formatted[1:-1]}⟧")
                else:
                    out.append(formatted)
                sup_buf = []
            elif low_h == "<sub>":
                in_sub = True
                sub_buf = []
            elif low_h == "</sub>":
                in_sub = False
                formatted = format_word_vert_align("".join(sub_buf), "subscript")
                if formatted.startswith("$") and formatted.endswith("$"):
                    out.append(f"⟦MATH:{formatted[1:-1]}⟧")
                else:
                    out.append(formatted)
                sub_buf = []
            elif low_h in ("<b>", "<strong>"):
                if keep_bold_markers:
                    _append("⟦B⟧")
            elif low_h in ("</b>", "</strong>"):
                if keep_bold_markers:
                    _append("⟦/B⟧")
            elif low_h in ("<i>", "<em>"):
                _append("⟦I⟧")
            elif low_h in ("</i>", "</em>"):
                _append("⟦/I⟧")
            elif low_h in ("<s>", "<del>"):
                _append("⟦S⟧")
            elif low_h in ("</s>", "</del>"):
                _append("⟦/S⟧")
            # Ignore other bare HTML tags cleanly
        idx += 1

    # Flush unclosed sup/sub defensively
    if sup_buf:
        out.append("".join(sup_buf))
    if sub_buf:
        out.append("".join(sub_buf))

    text = "".join(out)
    text = text.replace("⟦B⟧⟦/B⟧", "").replace("⟦I⟧⟦/I⟧", "").replace("⟦S⟧⟦/S⟧", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*⟦BR⟧\s*", "⟦BR⟧", text)
    text = re.sub(r"^(?:⟦BR⟧)+|(?:⟦BR⟧)+$", "", text).strip()
    return text, display_maths, task_checked


def _parse_paperdiff_comment_directives(raw_html: str) -> dict[str, Any]:
    """Parse internal <!-- PAPERDIFF_*:... --> directives emitted by docx_parser."""
    res: dict[str, Any] = {}
    for line in raw_html.splitlines():
        s = line.strip()
        if not s.startswith("<!--"):
            continue
        m_zone = re.fullmatch(r"<!--\s*PAPERDIFF_ZONE:(frontmatter|body|backmatter)\s*-->", s)
        if m_zone:
            res["zone"] = m_zone.group(1)
            continue
        for prefix, key in (
            ("<!-- PAPERDIFF_TABLE_META:", "table_meta"),
            ("<!-- PAPERDIFF_TABLE:", "table_rows"),
            ("<!-- PAPERDIFF_ANCHOR:", "anchor"),
            ("<!-- PAPERDIFF_STYLE:", "style"),
            ("<!-- PAPERDIFF_COMMENTS:", "comments"),
            ("<!-- PAPERDIFF_FOOTNOTES:", "doc_footnotes"),
        ):
            if s.startswith(prefix) and s.endswith("-->"):
                payload = s[len(prefix) : -len("-->")].strip()
                try:
                    res[key] = json.loads(payload)
                except Exception:
                    pass
                break
    return res


def _is_whole_cell_bold(children: list[Any] | None) -> bool:
    if not children:
        return False
    sig = [c for c in children if not (c.type == "text" and not c.content.strip())]
    if len(sig) < 3:
        return False
    return (
        sig[0].type == "strong_open"
        and sig[-1].type == "strong_close"
        and sum(1 for c in sig if c.type == "strong_open") == 1
    )


def parse_markdown_with_meta(
    content: str,
    asset_map: dict[str, str] | None = None,
) -> tuple[list[DocumentBlock], dict[str, Any]]:
    """
    Parse Markdown (or Word-intermediate Markdown) using markdown-it-py AST into
    DocumentBlocks + document-level metadata (footnotes dictionary).
    """
    norm_content = content.replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = norm_content.split("\n")
    # Compute 0-based line start character offsets in norm_content
    line_offsets: list[int] = [0]
    for ln in raw_lines:
        line_offsets.append(line_offsets[-1] + len(ln) + 1)

    def _span_from_map(mp: list[int] | None) -> tuple[int | None, int | None, str, dict[str, Any] | None]:
        if not mp or len(mp) < 2:
            return None, None, "", None
        s_line = max(0, min(mp[0], len(raw_lines)))
        e_line = max(s_line, min(mp[1], len(raw_lines)))
        rs = line_offsets[s_line]
        re_pos = max(rs, line_offsets[e_line] - 1) if e_line > s_line else rs
        raw_chunk = "\n".join(raw_lines[s_line:e_line]).strip(" \t\r\n")
        anchor = {"kind": "md_lines", "line_start": s_line, "line_end": e_line}
        return rs, re_pos, raw_chunk, anchor

    preprocessed = _preprocess_md_preserving_lines(norm_content)
    tokens = _MD_ENGINE.parse(preprocessed)

    blocks: list[DocumentBlock] = []
    doc_footnotes: dict[str, str] = {}
    current_section = "正文" if any("\u4e00" <= ch <= "\u9fff" for ch in norm_content[:600]) else "Main Text"
    current_level = 1
    current_zone = "body"
    eq_counter = 0

    pending_zone: str | None = None
    pending_anchor: dict[str, Any] | None = None
    pending_style: dict[str, Any] | None = None
    pending_comments: list[dict[str, Any]] | None = None
    pending_table_rows: list[list[dict[str, Any]]] | None = None
    pending_table_meta: dict[str, Any] = {}

    def _consume_pending(
        default_anchor: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]], dict[str, Any]]:
        nonlocal pending_zone, pending_anchor, pending_style, pending_comments
        z = pending_zone or current_zone
        anc = pending_anchor or default_anchor
        cmts = pending_comments or []
        sty = dict(pending_style) if pending_style else {}
        pending_zone = None
        pending_anchor = None
        pending_style = None
        pending_comments = None
        return z, anc, cmts, sty

    n_tok = len(tokens)
    i = 0

    # Helper to walk list items recursively with nesting depth (0..5) and aligned child blocks
    def _parse_list(start_idx: int, ordered: bool, start_num: int, depth: int) -> int:
        nonlocal current_section, current_level, current_zone, eq_counter
        close_type = "ordered_list_close" if ordered else "bullet_list_close"
        item_num = start_num - 1
        eff_list_depth = min(5, max(0, depth))
        k = start_idx + 1
        while k < n_tok and tokens[k].type != close_type:
            if tokens[k].type == "list_item_open":
                item_num += 1
                li_map = tokens[k].map
                k += 1
                item_texts: list[str] = []
                item_dmaths: list[str] = []
                item_checked: bool | None = None
                emitted_primary = False
                item_start_map = li_map

                def _flush_primary_item() -> None:
                    nonlocal item_texts, emitted_primary
                    if not item_texts:
                        return
                    rs, re_pos, raw_chunk, def_anc = _span_from_map(item_start_map)
                    z_here, anc, cmts, sty = _consume_pending(def_anc)
                    eff_depth = sty.pop("list_depth", eff_list_depth)
                    norm_sty = normalize_block_style(sty)
                    is_ref = z_here == "backmatter" and bool(_REF_HEADING_RE.match(current_section))
                    meta_item: dict[str, Any] = (
                        {"ref_num": item_num}
                        if is_ref
                        else {"ordered": ordered, "item_num": item_num, "depth": eff_depth}
                    )
                    if item_checked is not None and not is_ref:
                        meta_item["checked"] = item_checked
                    if cmts:
                        meta_item["comments"] = cmts
                    if norm_sty:
                        meta_item["style"] = norm_sty
                    blocks.append(
                        DocumentBlock(
                            index=len(blocks),
                            block_type="reference_item" if is_ref else "list",
                            section_title=current_section,
                            section_level=current_level,
                            raw_text=raw_chunk,
                            clean_text=" ".join(item_texts),
                            raw_start=rs,
                            raw_end=re_pos,
                            zone=z_here,
                            source_anchor=anc,
                            meta=meta_item,
                        )
                    )
                    item_texts = []
                    emitted_primary = True

                def _flush_item_maths() -> None:
                    nonlocal item_dmaths, eq_counter
                    for dm in item_dmaths:
                        eq_counter += 1
                        blocks.append(
                            DocumentBlock(
                                index=len(blocks),
                                block_type="math",
                                section_title=current_section,
                                section_level=current_level,
                                raw_text=f"$$\n{dm}\n$$",
                                clean_text=f"⟦MATH:{dm}⟧",
                                zone=current_zone,
                                meta={
                                    "label": "",
                                    "eq_number": None,
                                    "style": normalize_block_style({"parent_list_depth": eff_list_depth}),
                                },
                            )
                        )
                    item_dmaths = []

                while k < n_tok and tokens[k].type != "list_item_close":
                    tk = tokens[k]
                    if tk.type == "paragraph_open":
                        p_map = tk.map
                        if k + 1 < n_tok and tokens[k + 1].type == "inline":
                            txt, dms, chk = _render_inline_children(tokens[k + 1].children)
                            if chk is not None and item_checked is None:
                                item_checked = chk
                            if not emitted_primary and not item_texts:
                                if txt:
                                    item_texts.append(txt)
                                item_dmaths.extend(dms)
                            else:
                                # Continuation paragraph inside the same list item aligns with parent list column
                                _flush_primary_item()
                                _flush_item_maths()
                                if txt:
                                    rs_c, re_c, raw_c, anc_c = _span_from_map(p_map)
                                    blocks.append(
                                        DocumentBlock(
                                            index=len(blocks),
                                            block_type="paragraph",
                                            section_title=current_section,
                                            section_level=current_level,
                                            raw_text=raw_c,
                                            clean_text=txt,
                                            raw_start=rs_c,
                                            raw_end=re_c,
                                            zone=current_zone,
                                            source_anchor=anc_c,
                                            meta={"style": normalize_block_style({"parent_list_depth": eff_list_depth})},
                                        )
                                    )
                                item_dmaths.extend(dms)
                                _flush_item_maths()
                        while k < n_tok and tokens[k].type != "paragraph_close":
                            k += 1
                        k += 1
                        continue
                    elif tk.type == "inline":
                        txt, dms, chk = _render_inline_children(tk.children)
                        if chk is not None and item_checked is None:
                            item_checked = chk
                        if txt:
                            item_texts.append(txt)
                        item_dmaths.extend(dms)
                    elif tk.type in ("math_block", "math_block_label", "amsmath"):
                        _flush_primary_item()
                        expr = _clean_latex_display_math(tk.content)
                        if expr:
                            item_dmaths.append(expr)
                            _flush_item_maths()
                    elif tk.type in ("bullet_list_open", "ordered_list_open"):
                        _flush_primary_item()
                        _flush_item_maths()
                        sub_ordered = tk.type == "ordered_list_open"
                        sub_start = int(tk.attrGet("start") or 1) if sub_ordered else 1
                        k = _parse_list(k, sub_ordered, sub_start, depth + 1)
                        continue
                    elif tk.type == "fence":
                        _flush_primary_item()
                        _flush_item_maths()
                        lang = (tk.info or "").strip().split()[0].lower() if tk.info else ""
                        rs, re_pos, raw_chunk, def_anc = _span_from_map(tk.map)
                        blocks.append(
                            DocumentBlock(
                                index=len(blocks),
                                block_type="code",
                                section_title=current_section,
                                section_level=current_level,
                                raw_text=raw_chunk or tk.content,
                                clean_text=tk.content.rstrip("\n"),
                                raw_start=rs,
                                raw_end=re_pos,
                                zone=current_zone,
                                source_anchor=def_anc,
                                meta={
                                    "lang": lang,
                                    "is_diagram": lang == "mermaid",
                                    "style": normalize_block_style({"parent_list_depth": eff_list_depth}),
                                },
                            )
                        )
                    elif tk.type == "blockquote_open":
                        _flush_primary_item()
                        _flush_item_maths()
                        rs_q, re_q, raw_q, anc_q = _span_from_map(tk.map)
                        q_seg: list[str] = []
                        dq = 1
                        k += 1
                        while k < n_tok and dq > 0:
                            if tokens[k].type == "blockquote_open":
                                dq += 1
                            elif tokens[k].type == "blockquote_close":
                                dq -= 1
                            elif tokens[k].type == "inline":
                                qt, _, _ = _render_inline_children(tokens[k].children, softbreak_as_br=True)
                                if qt:
                                    q_seg.append(qt)
                            k += 1
                        if q_seg:
                            blocks.append(
                                DocumentBlock(
                                    index=len(blocks),
                                    block_type="blockquote",
                                    section_title=current_section,
                                    section_level=current_level,
                                    raw_text=raw_q,
                                    clean_text="⟦BR⟧".join(q_seg).strip(),
                                    raw_start=rs_q,
                                    raw_end=re_q,
                                    zone=current_zone,
                                    source_anchor=anc_q,
                                    meta={
                                        "style": normalize_block_style(
                                            {"quote_depth": 1, "parent_list_depth": eff_list_depth}
                                        )
                                    },
                                )
                            )
                        continue
                    k += 1

                _flush_primary_item()
                _flush_item_maths()
                k += 1  # consume list_item_close
            else:
                k += 1
        return k + 1  # consume close_type

    while i < n_tok:
        tok = tokens[i]
        ttype = tok.type

        # 1. YAML Frontmatter
        if ttype == "front_matter":
            kv_rows: list[list[dict[str, Any]]] = []
            for ln in tok.content.splitlines():
                ln_s = ln.strip()
                if ":" in ln_s:
                    kk, vv = ln_s.split(":", 1)
                    kv_rows.append(
                        [
                            {"text": kk.strip(), "colspan": 1, "rowspan": 1, "bold": True},
                            {"text": vv.strip().strip('"').strip("'"), "colspan": 1, "rowspan": 1, "bold": False},
                        ]
                    )
            if kv_rows:
                rs, re_pos, raw_chunk, def_anc = _span_from_map(tok.map)
                blocks.append(
                    DocumentBlock(
                        index=len(blocks),
                        block_type="table",
                        section_title="文档元数据",
                        section_level=1,
                        raw_text=raw_chunk,
                        clean_text="\n".join(f"{r[0]['text']} | {r[1]['text']}" for r in kv_rows),
                        raw_start=rs,
                        raw_end=re_pos,
                        zone="frontmatter",
                        source_anchor=def_anc,
                        meta={"rows": kv_rows, "label": "", "table_role": "metadata_form"},
                    )
                )
            i += 1
            continue

        # 2. Internal PAPERDIFF HTML comments (from docx_parser)
        if ttype == "html_block":
            directives = _parse_paperdiff_comment_directives(tok.content)
            if directives:
                if "zone" in directives:
                    pending_zone = directives["zone"]
                if "anchor" in directives:
                    pending_anchor = directives["anchor"]
                if "style" in directives and isinstance(directives["style"], dict):
                    pending_style = {**(pending_style or {}), **directives["style"]}
                if "comments" in directives and isinstance(directives["comments"], list):
                    pending_comments = directives["comments"]
                if "table_meta" in directives and isinstance(directives["table_meta"], dict):
                    pending_table_meta.update(directives["table_meta"])
                if "table_rows" in directives and isinstance(directives["table_rows"], list):
                    pending_table_rows = directives["table_rows"]
                if "doc_footnotes" in directives and isinstance(directives["doc_footnotes"], dict):
                    for fk, fv in directives["doc_footnotes"].items():
                        doc_footnotes[str(fk)] = normalize_plain_or_md_inline(str(fv))
            i += 1
            continue

        # 3. Headings
        if ttype == "heading_open":
            lvl = min(4, max(1, int(tok.tag[1]) if tok.tag.startswith("h") and tok.tag[1:].isdigit() else 1))
            rs, re_pos, raw_chunk, def_anc = _span_from_map(tok.map)
            inline_tok = tokens[i + 1] if i + 1 < n_tok and tokens[i + 1].type == "inline" else None
            title_clean, _, _ = _render_inline_children(
                inline_tok.children if inline_tok else None,
                keep_bold_markers=False,
            )
            title_plain = _strip_inline_markers_fast(title_clean).strip()
            z_here, anc, cmts, sty = _consume_pending(def_anc)
            sty.pop("list_depth", None)
            norm_sty = normalize_block_style(sty)
            if _BACKMATTER_HEADING_RE.match(title_plain):
                current_zone = "backmatter"
                z_here = "backmatter"
            elif current_zone == "frontmatter" and _BODY_START_HEADING_RE.match(title_plain):
                current_zone = "body"
                z_here = "body"
            current_section = title_plain or current_section
            current_level = lvl
            meta_h: dict[str, Any] = {}
            if cmts:
                meta_h["comments"] = cmts
            if norm_sty:
                meta_h["style"] = norm_sty
            blocks.append(
                DocumentBlock(
                    index=len(blocks),
                    block_type="heading",
                    section_title=current_section,
                    section_level=lvl,
                    raw_text=raw_chunk,
                    clean_text=title_clean,
                    raw_start=rs,
                    raw_end=re_pos,
                    zone=z_here,
                    source_anchor=anc,
                    meta=meta_h,
                )
            )
            while i < n_tok and tokens[i].type != "heading_close":
                i += 1
            i += 1
            continue

        # 4. Fenced / indented code blocks (incl. Mermaid diagram detection)
        if ttype in ("fence", "code_block"):
            lang = (tok.info or "").strip().split()[0].lower() if tok.info else ""
            rs, re_pos, raw_chunk, def_anc = _span_from_map(tok.map)
            z_here, anc, cmts, _ = _consume_pending(def_anc)
            meta_c: dict[str, Any] = {"lang": lang, "is_diagram": lang == "mermaid"}
            if cmts:
                meta_c["comments"] = cmts
            blocks.append(
                DocumentBlock(
                    index=len(blocks),
                    block_type="code",
                    section_title=current_section,
                    section_level=current_level,
                    raw_text=raw_chunk or tok.content,
                    clean_text=tok.content.rstrip("\n"),
                    raw_start=rs,
                    raw_end=re_pos,
                    zone=z_here,
                    source_anchor=anc,
                    meta=meta_c,
                )
            )
            i += 1
            continue

        # 5. Display math blocks (dollarmath & amsmath)
        if ttype in ("math_block", "math_block_label", "amsmath"):
            rs, re_pos, raw_chunk, def_anc = _span_from_map(tok.map)
            env_name = None
            m_env = re.match(r"\\begin\{([a-zA-Z]+)\*?\}", tok.content.strip())
            if m_env:
                env_name = m_env.group(1)
            inner_clean = _clean_latex_display_math(tok.content, env_name=env_name)
            lbl = ""
            if tok.info:
                lbl = tok.info.strip()
            else:
                m_lbl = re.search(r"\\label\{([^}]+)\}", tok.content)
                if m_lbl:
                    lbl = m_lbl.group(1).strip()
            z_here, anc, cmts, _ = _consume_pending(def_anc)
            if inner_clean:
                eq_counter += 1
                is_numbered = bool(lbl) or (ttype == "amsmath" and not re.match(r"\\begin\{[a-zA-Z]+\*\}", tok.content.strip()))
                meta_m: dict[str, Any] = {
                    "label": lbl,
                    "eq_number": eq_counter if is_numbered else None,
                }
                if cmts:
                    meta_m["comments"] = cmts
                blocks.append(
                    DocumentBlock(
                        index=len(blocks),
                        block_type="math",
                        section_title=current_section,
                        section_level=current_level,
                        raw_text=raw_chunk or tok.content,
                        clean_text=f"⟦MATH:{inner_clean}⟧",
                        raw_start=rs,
                        raw_end=re_pos,
                        zone=z_here,
                        source_anchor=anc,
                        meta=meta_m,
                    )
                )
            i += 1
            continue

        # 6. Horizontal rule
        if ttype == "hr":
            rs, re_pos, raw_chunk, def_anc = _span_from_map(tok.map)
            z_here, anc, _, _ = _consume_pending(def_anc)
            blocks.append(
                DocumentBlock(
                    index=len(blocks),
                    block_type="hr",
                    section_title=current_section,
                    section_level=current_level,
                    raw_text=raw_chunk or "---",
                    clean_text="",
                    raw_start=rs,
                    raw_end=re_pos,
                    zone=z_here,
                    source_anchor=anc,
                )
            )
            i += 1
            continue

        # 7. Blockquote (Caption, GitHub Callout, or Standard/Nested Blockquote)
        if ttype == "blockquote_open":
            rs, re_pos, raw_chunk, def_anc = _span_from_map(tok.map)
            q_entries: list[tuple[int, str]] = []
            depth_q = 1
            i += 1
            while i < n_tok and depth_q > 0:
                tk = tokens[i]
                if tk.type == "blockquote_open":
                    depth_q += 1
                elif tk.type == "blockquote_close":
                    depth_q -= 1
                elif tk.type == "inline":
                    txt, _, _ = _render_inline_children(tk.children, softbreak_as_br=True)
                    if txt:
                        q_entries.append((min(4, depth_q), txt))
                i += 1

            z_here, anc, cmts, sty = _consume_pending(def_anc)
            sty.pop("list_depth", None)
            has_nested_q = any(d > 1 for d, _ in q_entries)
            if not has_nested_q:
                joined_q = "⟦BR⟧".join(t for _, t in q_entries).strip()
                norm_sty = normalize_block_style(sty)
                if joined_q.startswith("[Caption]"):
                    cap_clean = joined_q[len("[Caption]") :].strip()
                    cap_raw = re.sub(r"^\s*>\s*\[Caption\]\s*", "", raw_chunk).strip()
                    meta_cap: dict[str, Any] = {}
                    if cmts:
                        meta_cap["comments"] = cmts
                    if norm_sty:
                        meta_cap["style"] = norm_sty
                    blocks.append(
                        DocumentBlock(
                            index=len(blocks),
                            block_type="caption",
                            section_title=current_section,
                            section_level=current_level,
                            raw_text=cap_raw,
                            clean_text="[Caption] " + cap_clean,
                            raw_start=rs,
                            raw_end=re_pos,
                            zone=z_here,
                            source_anchor=anc,
                            meta=meta_cap,
                        )
                    )
                elif joined_q:
                    callout_type = None
                    m_call = _CALLOUT_RE.match(joined_q)
                    if m_call:
                        callout_type = m_call.group(1).lower()
                        joined_q = joined_q[m_call.end() :].strip()
                    meta_q: dict[str, Any] = {}
                    if callout_type:
                        meta_q["callout_type"] = callout_type
                    if cmts:
                        meta_q["comments"] = cmts
                    q_sty = normalize_block_style({**norm_sty, "quote_depth": 1})
                    if q_sty:
                        meta_q["style"] = q_sty
                    blocks.append(
                        DocumentBlock(
                            index=len(blocks),
                            block_type="blockquote",
                            section_title=current_section,
                            section_level=current_level,
                            raw_text=raw_chunk,
                            clean_text=joined_q,
                            raw_start=rs,
                            raw_end=re_pos,
                            zone=z_here,
                            source_anchor=anc,
                            meta=meta_q,
                        )
                    )
            else:
                # Emit distinct depth groups in order so nested (> >) quotes preserve visual hierarchy
                groups: list[tuple[int, list[str]]] = []
                for d_val, txt in q_entries:
                    if groups and groups[-1][0] == d_val:
                        groups[-1][1].append(txt)
                    else:
                        groups.append((d_val, [txt]))
                for g_idx, (d_val, segs) in enumerate(groups):
                    meta_q = {
                        "style": normalize_block_style({**sty, "quote_depth": d_val}),
                    }
                    if g_idx == 0 and cmts:
                        meta_q["comments"] = cmts
                    blocks.append(
                        DocumentBlock(
                            index=len(blocks),
                            block_type="blockquote",
                            section_title=current_section,
                            section_level=current_level,
                            raw_text=raw_chunk,
                            clean_text="⟦BR⟧".join(segs).strip(),
                            raw_start=rs,
                            raw_end=re_pos,
                            zone=z_here,
                            source_anchor=anc,
                            meta=meta_q,
                        )
                    )
            continue

        # 8. Lists (bullet / ordered, nested, tasklists)
        if ttype in ("bullet_list_open", "ordered_list_open"):
            ordered = ttype == "ordered_list_open"
            start_num = int(tok.attrGet("start") or 1) if ordered else 1
            i = _parse_list(i, ordered, start_num, 0)
            continue

        # 9. Definition Lists (<dl><dt><dd>)
        if ttype == "dl_open":
            rs, re_pos, raw_chunk, def_anc = _span_from_map(tok.map)
            cur_term = ""
            i += 1
            while i < n_tok and tokens[i].type != "dl_close":
                if tokens[i].type == "dt_open":
                    if i + 1 < n_tok and tokens[i + 1].type == "inline":
                        cur_term, _, _ = _render_inline_children(tokens[i + 1].children, keep_bold_markers=False)
                elif tokens[i].type == "dd_open":
                    dd_parts: list[str] = []
                    i += 1
                    while i < n_tok and tokens[i].type != "dd_close":
                        if tokens[i].type == "inline":
                            t_dd, _, _ = _render_inline_children(tokens[i].children)
                            if t_dd:
                                dd_parts.append(t_dd)
                        i += 1
                    if cur_term or dd_parts:
                        clean_dl = f"⟦B⟧{cur_term}⟦/B⟧ — {' '.join(dd_parts)}" if cur_term else " ".join(dd_parts)
                        z_here, anc, cmts, _ = _consume_pending(def_anc)
                        blocks.append(
                            DocumentBlock(
                                index=len(blocks),
                                block_type="list",
                                section_title=current_section,
                                section_level=current_level,
                                raw_text=raw_chunk,
                                clean_text=clean_dl,
                                raw_start=rs,
                                raw_end=re_pos,
                                zone=z_here,
                                source_anchor=anc,
                                meta={"ordered": False, "item_num": 1, "depth": 0, "is_deflist": True},
                            )
                        )
                i += 1
            i += 1
            continue

        # 10. Tables (GFM AST + optional Word merged-cell comment override)
        if ttype == "table_open":
            rs, re_pos, raw_chunk, def_anc = _span_from_map(tok.map)
            gfm_rows: list[list[dict[str, Any]]] = []
            alignments: list[str] = []
            i += 1
            while i < n_tok and tokens[i].type != "table_close":
                if tokens[i].type == "tr_open":
                    row_cells: list[dict[str, Any]] = []
                    row_aligns: list[str] = []
                    i += 1
                    while i < n_tok and tokens[i].type != "tr_close":
                        if tokens[i].type in ("th_open", "td_open"):
                            style_attr = tokens[i].attrGet("style") or ""
                            if "center" in style_attr:
                                row_aligns.append("center")
                            elif "right" in style_attr:
                                row_aligns.append("right")
                            else:
                                row_aligns.append("left")
                            inline_t = tokens[i + 1] if i + 1 < n_tok and tokens[i + 1].type == "inline" else None
                            whole_bold = _is_whole_cell_bold(inline_t.children if inline_t else None)
                            cell_txt, _, _ = _render_inline_children(
                                inline_t.children if inline_t else None,
                                keep_bold_markers=not whole_bold,
                            )
                            row_cells.append(
                                {
                                    "text": cell_txt,
                                    "colspan": 1,
                                    "rowspan": 1,
                                    "bold": whole_bold,
                                }
                            )
                        i += 1
                    if row_cells:
                        gfm_rows.append(row_cells)
                        if not alignments and row_aligns:
                            alignments = row_aligns
                i += 1
            i += 1  # consume table_close

            if pending_table_rows:
                final_rows: list[list[dict[str, Any]]] = []
                for r in pending_table_rows:
                    final_rows.append(
                        [
                            {
                                "text": normalize_plain_or_md_inline(
                                    str(c.get("text", "")),
                                    keep_bold_markers=not bool(c.get("bold", False)),
                                ),
                                "colspan": max(1, int(c.get("colspan", 1))),
                                "rowspan": max(1, int(c.get("rowspan", 1))),
                                "bold": bool(c.get("bold", False)),
                            }
                            for c in r
                        ]
                    )
                pending_table_rows = None
            else:
                final_rows = gfm_rows

            tmeta = dict(pending_table_meta)
            pending_table_meta = {}
            z_here, anc, cmts, _ = _consume_pending(def_anc)

            if final_rows:
                role = tmeta.get("role") or ("metadata_form" if _is_metadata_form_table(final_rows) else "data_table")
                zone_here = tmeta.get("zone") or ("frontmatter" if role == "metadata_form" else z_here)
                meta_tbl: dict[str, Any] = {
                    "rows": final_rows,
                    "alignments": alignments,
                    "label": "",
                    "table_role": role,
                }
                if cmts:
                    meta_tbl["comments"] = cmts
                blocks.append(
                    DocumentBlock(
                        index=len(blocks),
                        block_type="table",
                        section_title=current_section,
                        section_level=current_level,
                        raw_text=raw_chunk,
                        clean_text="\n".join(" | ".join(c["text"] for c in r) for r in final_rows),
                        raw_start=rs,
                        raw_end=re_pos,
                        zone=zone_here,
                        source_anchor=anc,
                        meta=meta_tbl,
                    )
                )
            continue

        # 11. Footnote definitions block (bottom of document)
        if ttype == "footnote_block_open":
            i += 1
            while i < n_tok and tokens[i].type != "footnote_block_close":
                if tokens[i].type == "footnote_open":
                    fn_lbl = str((tokens[i].meta or {}).get("label") or (tokens[i].meta or {}).get("id", ""))
                    fn_parts: list[str] = []
                    i += 1
                    while i < n_tok and tokens[i].type != "footnote_close":
                        if tokens[i].type == "inline":
                            t_fn, _, _ = _render_inline_children(tokens[i].children)
                            if t_fn:
                                fn_parts.append(t_fn)
                        i += 1
                    if fn_lbl and fn_parts:
                        doc_footnotes[fn_lbl] = " ".join(fn_parts).strip()
                i += 1
            i += 1
            continue

        # 12. Paragraph (including standalone image + optional immediately following > [Caption])
        if ttype == "paragraph_open":
            rs, re_pos, raw_chunk, def_anc = _span_from_map(tok.map)
            inline_tok = tokens[i + 1] if i + 1 < n_tok and tokens[i + 1].type == "inline" else None
            children = inline_tok.children if inline_tok else []

            # Check for standalone image paragraph ![alt](url)
            if len(children) == 1 and children[0].type == "image":
                img_tok = children[0]
                alt_txt = img_tok.content or (img_tok.children[0].content if img_tok.children else "")
                img_ref = img_tok.attrGet("src") or ""
                asset_key = _resolve_asset_key(img_ref, asset_map) or (
                    img_ref[len("asset://") :] if img_ref.startswith("asset://") else None
                )
                cap_text = ""
                cap_raw = raw_chunk
                # Advance past paragraph_close
                i += 3
                # Skip any intervening PAPERDIFF comment html_blocks (e.g. anchor on caption para)
                j_cap = i
                cap_anchor = None
                while j_cap < n_tok and tokens[j_cap].type == "html_block":
                    d_cap = _parse_paperdiff_comment_directives(tokens[j_cap].content)
                    if "anchor" in d_cap:
                        cap_anchor = d_cap["anchor"]
                    j_cap += 1
                # Pair with immediately following > [Caption] blockquote if present
                if (
                    j_cap + 2 < n_tok
                    and tokens[j_cap].type == "blockquote_open"
                    and tokens[j_cap + 1].type == "paragraph_open"
                    and tokens[j_cap + 2].type == "inline"
                    and tokens[j_cap + 2].content.strip().startswith("[Caption]")
                ):
                    q_txt, _, _ = _render_inline_children(tokens[j_cap + 2].children)
                    cap_text = q_txt[len("[Caption]") :].strip() if q_txt.startswith("[Caption]") else q_txt
                    _, _, cap_raw_q, _ = _span_from_map(tokens[j_cap].map)
                    cap_raw = re.sub(r"^\s*>\s*\[Caption\]\s*", "", cap_raw_q).strip()
                    i = j_cap
                    while i < n_tok and tokens[i].type != "blockquote_close":
                        i += 1
                    i += 1
                    if cap_anchor:
                        pending_anchor = cap_anchor

                z_here, anc, cmts, _ = _consume_pending(def_anc)
                meta_fig: dict[str, Any] = {
                    "env": "figure",
                    "label": alt_txt,
                    "image_path": img_ref,
                    "asset_key": asset_key,
                }
                if cmts:
                    meta_fig["comments"] = cmts
                blocks.append(
                    DocumentBlock(
                        index=len(blocks),
                        block_type="figure",
                        section_title=current_section,
                        section_level=current_level,
                        raw_text=cap_raw,
                        clean_text=cap_text or alt_txt,
                        raw_start=rs,
                        raw_end=re_pos,
                        zone=z_here,
                        source_anchor=anc,
                        meta=meta_fig,
                    )
                )
                continue

            clean_p, dmaths, _ = _render_inline_children(children)
            z_here, anc, cmts, sty = _consume_pending(def_anc)
            sty.pop("list_depth", None)
            # Detect explicit leading full-width spaces (\u3000) in Markdown/text paragraphs
            if tok.map and len(tok.map) >= 1 and 0 <= tok.map[0] < len(raw_lines):
                first_raw_ln = raw_lines[tok.map[0]]
                fw_cnt = len(first_raw_ln) - len(first_raw_ln.lstrip("\u3000"))
                if fw_cnt > 0 and "first_line_indent_em" not in sty and "hanging_indent_em" not in sty:
                    sty["first_line_indent_em"] = min(4.0, float(fw_cnt))
                    sty["explicit_indent"] = "indent"
            if clean_p.startswith("\u3000"):
                clean_p = clean_p.lstrip("\u3000").strip()
            if (
                z_here == "body"
                and "semantic_role" not in sty
                and re.fullmatch(r"(?:摘\s*要|中文摘要|英文摘要|Abstract)", current_section.strip(), re.IGNORECASE)
            ):
                sty["semantic_role"] = "abstract"
            norm_sty = normalize_block_style(sty)
            if clean_p:
                if z_here == "backmatter" and _REF_HEADING_RE.match(current_section):
                    rm_num = re.match(r"^\[(\d+)\]\s*(.+)$", clean_p)
                    blocks.append(
                        DocumentBlock(
                            index=len(blocks),
                            block_type="reference_item",
                            section_title=current_section,
                            section_level=current_level,
                            raw_text=raw_chunk,
                            clean_text=rm_num.group(2).strip() if rm_num else clean_p,
                            raw_start=rs,
                            raw_end=re_pos,
                            zone="backmatter",
                            source_anchor=anc,
                            meta={"ref_num": int(rm_num.group(1)) if rm_num else None},
                        )
                    )
                else:
                    meta_p: dict[str, Any] = {}
                    if cmts:
                        meta_p["comments"] = cmts
                    if norm_sty:
                        meta_p["style"] = norm_sty
                    blocks.append(
                        DocumentBlock(
                            index=len(blocks),
                            block_type="paragraph",
                            section_title=current_section,
                            section_level=current_level,
                            raw_text=raw_chunk,
                            clean_text=clean_p,
                            raw_start=rs,
                            raw_end=re_pos,
                            zone=z_here,
                            source_anchor=anc,
                            meta=meta_p,
                        )
                    )
            for dm in dmaths:
                eq_counter += 1
                blocks.append(
                    DocumentBlock(
                        index=len(blocks),
                        block_type="math",
                        section_title=current_section,
                        section_level=current_level,
                        raw_text=f"$$\n{dm}\n$$",
                        clean_text=f"⟦MATH:{dm}⟧",
                        raw_start=rs,
                        raw_end=re_pos,
                        zone=z_here,
                        source_anchor=anc,
                        meta={"label": "", "eq_number": None},
                    )
                )
            while i < n_tok and tokens[i].type != "paragraph_close":
                i += 1
            i += 1
            continue

        i += 1

    classified = _classify_document_zones(blocks, allow_h1_title_promote=True)
    if doc_footnotes and classified:
        classified[0].meta["doc_footnotes"] = doc_footnotes
    return classified, {"footnotes": doc_footnotes}


def parse_markdown_or_text(content: str, asset_map: dict[str, str] | None = None) -> list[DocumentBlock]:
    blocks, _ = parse_markdown_with_meta(content, asset_map=asset_map)
    return blocks
