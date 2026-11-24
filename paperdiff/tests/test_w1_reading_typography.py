"""Reading Typography & Indentation Calibration Tests.

Covers W1-T01 through W1-T13 behavior assertions for academic typography extraction,
presets, clean copy, multi-theme contrast, and offline PDF layout parity.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docx import Document  # noqa: E402
from docx.enum.style import WD_STYLE_TYPE  # noqa: E402
from docx.oxml import OxmlElement, parse_xml  # noqa: E402
from docx.oxml.ns import nsdecls, qn  # noqa: E402

from backend.analyzer import audit_paragraph_pair, compare_documents, preview_document  # noqa: E402
from backend.diff_engine import (  # noqa: E402
    count_academic_words,
    strip_rich_markers,
    text_to_display_items,
    tokenize_academic,
)
from backend.parsers import extract_docx_with_assets, ir, parse_document_with_meta  # noqa: E402
from backend.patcher import patch_docx_bytes, patch_latex_content  # noqa: E402


def test_w1_t02_block_style_clamping_and_sp_atom() -> None:
    """W1-T02: BlockStyle clamping & ⟦SP:...⟧ spacing atom isolation."""
    # 1. SP atom parsing in text_to_display_items
    items = text_to_display_items("作者⟦SP:2⟧日期")
    sp_items = [it for it in items if it.get("kind") == "sp"]
    assert len(sp_items) == 1, f"Expected 1 sp DisplayItem, got {items}"
    assert sp_items[0].get("value") == "2"

    # 2. SP atom treated as plain whitespace in word count, tokenizer, strip_rich_markers & audit
    assert count_academic_words("Hello⟦SP:2⟧World") == count_academic_words("Hello World")
    toks = [t for t in tokenize_academic("Hello⟦SP:2⟧World") if t.kind != "space"]
    assert [t.text for t in toks] == ["Hello", "World"]
    assert strip_rich_markers("Hello⟦SP:2⟧World") == "Hello World"
    assert ir._strip_inline_markers_fast("Hello⟦SP:2⟧World").strip() == "Hello World"

    alerts = audit_paragraph_pair(
        "Flux is 14.2% under control.",
        "Flux is⟦SP:2⟧14.2% under control.",
        para_index=0,
        section_title="Results",
        protected_terms=["Flux"],
    )
    assert alerts == [], f"Pure SP atom must never trigger audit alerts: {alerts}"

    # 3. normalize_block_style clamping bounds
    norm_fn = getattr(ir, "normalize_block_style", None)
    assert callable(norm_fn), "ir.normalize_block_style must exist"
    clamped = norm_fn(
        {
            "first_line_indent_em": 12.5,
            "hanging_indent_em": -3.0,
            "left_indent_em": 20.0,
            "right_indent_em": -1.0,
            "align": "CENTER",
            "explicit_indent": "indent",
            "quote_depth": 9,
            "parent_list_depth": 8,
            "semantic_role": "abstract",
        }
    )
    assert clamped["first_line_indent_em"] == 4.0
    assert clamped["hanging_indent_em"] == 0.0
    assert clamped["left_indent_em"] == 8.0
    assert clamped["right_indent_em"] == 0.0
    assert clamped["align"] == "center"
    assert clamped["explicit_indent"] == "indent"
    assert clamped["quote_depth"] == 4
    assert clamped["parent_list_depth"] == 5
    assert clamped["semantic_role"] == "abstract"


def _build_word_typography_fixture() -> bytes:
    """Build a real .docx with style-inherited indents, alignments, full-width spaces, tabs, and 5-level list."""
    doc = Document()

    # Custom inherited style: Normal -> AcademicBody (firstLineChars=200, jc=both)
    body_style = doc.styles.add_style("AcademicBody", WD_STYLE_TYPE.PARAGRAPH)
    body_style.base_style = doc.styles["Normal"]
    sp_ppr = body_style.element.get_or_add_pPr()
    sp_ind = OxmlElement("w:ind")
    sp_ind.set(qn("w:firstLineChars"), "200")
    sp_ppr.append(sp_ind)
    sp_jc = OxmlElement("w:jc")
    sp_jc.set(qn("w:val"), "both")
    sp_ppr.append(sp_jc)

    doc.add_heading("1. 引言", level=1)

    # 1) Direct firstLineChars=200
    p1 = doc.add_paragraph("第一段通过字符单位缩进两字符。")
    ind1 = OxmlElement("w:ind")
    ind1.set(qn("w:firstLineChars"), "200")
    p1._p.get_or_add_pPr().append(ind1)

    # 2) Direct firstLine=420 twips (~2.0em)
    p2 = doc.add_paragraph("第二段通过磅值 twips 缩进两字符。")
    ind2 = OxmlElement("w:ind")
    ind2.set(qn("w:firstLine"), "420")
    p2._p.get_or_add_pPr().append(ind2)

    # 3) Inherited from AcademicBody style (no direct w:ind on paragraph)
    doc.add_paragraph("第三段继承样式链缩进与两端对齐。", style=body_style)

    # 4) Hanging + left indent
    p4 = doc.add_paragraph("第四段采用悬挂缩进与左缩进。")
    ind4 = OxmlElement("w:ind")
    ind4.set(qn("w:left"), "420")
    ind4.set(qn("w:hanging"), "420")
    p4._p.get_or_add_pPr().append(ind4)

    # 5) Explicit firstLine=0 overriding AcademicBody style
    p5 = doc.add_paragraph("第五段显式声明取消首行缩进。", style=body_style)
    ind5 = OxmlElement("w:ind")
    ind5.set(qn("w:firstLine"), "0")
    p5._p.get_or_add_pPr().append(ind5)

    # 6) Centered and Right-aligned paragraphs
    p6 = doc.add_paragraph("居中标题行")
    jc6 = OxmlElement("w:jc")
    jc6.set(qn("w:val"), "center")
    p6._p.get_or_add_pPr().append(jc6)

    p7 = doc.add_paragraph("右对齐落款日期")
    jc7 = OxmlElement("w:jc")
    jc7.set(qn("w:val"), "right")
    p7._p.get_or_add_pPr().append(jc7)

    # 7) Leading full-width spaces + mid-line <w:tab/>
    p8 = doc.add_paragraph()
    p8.add_run("\u3000\u3000手工全角缩进段")
    r8_tab = OxmlElement("w:r")
    r8_tab.append(OxmlElement("w:tab"))
    p8._p.append(r8_tab)
    p8.add_run("制表符后文本")

    # 8) 5-level numbered list (ilvl 0..4) using numbering.xml
    for lvl in range(5):
        pl = doc.add_paragraph(f"列表层级 {lvl + 1} 内容")
        num_pr = parse_xml(
            f'<w:numPr {nsdecls("w")}><w:ilvl w:val="{lvl}"/><w:numId w:val="7"/></w:numPr>'
        )
        pl._p.get_or_add_pPr().append(num_pr)

    buf = io.BytesIO()
    doc.save(buf)

    numbering_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:abstractNum w:abstractNumId="7">
    <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
    <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="lowerLetter"/><w:lvlText w:val="%2)"/></w:lvl>
    <w:lvl w:ilvl="2"><w:start w:val="1"/><w:numFmt w:val="lowerRoman"/><w:lvlText w:val="%3."/></w:lvl>
    <w:lvl w:ilvl="3"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="(%4)"/></w:lvl>
    <w:lvl w:ilvl="4"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/></w:lvl>
  </w:abstractNum>
  <w:num w:numId="7"><w:abstractNumId w:val="7"/></w:num>
</w:numbering>"""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(buf.getvalue()), "r") as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.filename == "word/numbering.xml":
                continue
            zout.writestr(item, zin.read(item.filename))
        zout.writestr("word/numbering.xml", numbering_xml.encode("utf-8"))
    return out.getvalue()


def test_w1_t03_word_ooxml_indent_align_style_chain() -> None:
    """W1-T03: Word OOXML style-inherited indent, alignment, full-width spaces, and inline tab."""
    raw = _build_word_typography_fixture()
    md_text, meta = extract_docx_with_assets(raw)
    _, blocks, _ = parse_document_with_meta(md_text, fmt="docx", filename="typo.docx", asset_map=meta.get("assets"))

    def _find(substr: str):
        hits = [b for b in blocks if substr in b.clean_text]
        assert hits, f"Block containing {substr!r} not found"
        return hits[0]

    b1 = _find("第一段通过字符单位缩进两字符")
    assert b1.meta.get("style", {}).get("first_line_indent_em") == 2.0
    assert b1.meta.get("style", {}).get("explicit_indent") == "indent"

    b2 = _find("第二段通过磅值 twips 缩进两字符")
    assert b2.meta.get("style", {}).get("first_line_indent_em") == 2.0

    b3 = _find("第三段继承样式链缩进与两端对齐")
    assert b3.meta.get("style", {}).get("first_line_indent_em") == 2.0
    assert b3.meta.get("style", {}).get("align") == "justify"

    b4 = _find("第四段采用悬挂缩进与左缩进")
    assert b4.meta.get("style", {}).get("hanging_indent_em") == 2.0
    assert b4.meta.get("style", {}).get("left_indent_em") == 2.0

    b5 = _find("第五段显式声明取消首行缩进")
    assert b5.meta.get("style", {}).get("first_line_indent_em") == 0.0
    assert b5.meta.get("style", {}).get("explicit_indent") == "none"

    b6 = _find("居中标题行")
    assert b6.meta.get("style", {}).get("align") == "center"

    b7 = _find("右对齐落款日期")
    assert b7.meta.get("style", {}).get("align") == "right"

    b8 = _find("手工全角缩进段")
    assert b8.meta.get("style", {}).get("first_line_indent_em") == 2.0
    assert not b8.clean_text.startswith("\u3000"), f"Leading full-width spaces should not duplicate CSS indent: {b8.clean_text!r}"
    assert "⟦SP:2⟧" in b8.clean_text and "制表符后文本" in b8.clean_text


def test_w1_t04_word_deep_list_levels_and_patcher_anchor_fidelity() -> None:
    """W1-T04: Word 5-level list depth preservation (0..4) and docx_patcher XML anchor preservation."""
    raw = _build_word_typography_fixture()
    md_text, meta = extract_docx_with_assets(raw)
    _, blocks, _ = parse_document_with_meta(md_text, fmt="docx", filename="typo.docx", asset_map=meta.get("assets"))

    list_blocks = [b for b in blocks if b.block_type == "list" and "列表层级" in b.clean_text]
    assert len(list_blocks) == 5, f"Expected 5 list blocks, got {len(list_blocks)}"
    depths = [b.meta.get("depth") for b in list_blocks]
    assert depths == [0, 1, 2, 3, 4], f"Expected list depths [0,1,2,3,4], got {depths}"

    b2 = [b for b in blocks if "第二段通过磅值" in b.clean_text][0]
    ser_blocks = [{"index": b.index, "block_type": b.block_type, "source_anchor": b.source_anchor} for b in blocks]
    patched_bytes, applied, warnings = patch_docx_bytes(
        raw,
        ser_blocks,
        [{"op": "replace_block", "block_index": b2.index, "new_raw": "第二段已原地修订。"}],
    )
    assert applied == 1 and not warnings
    doc_after = Document(io.BytesIO(patched_bytes))
    texts = [p.text for p in doc_after.paragraphs]
    assert "第二段已原地修订。" in texts
    p1_after = [p for p in doc_after.paragraphs if "第一段通过字符单位" in p.text][0]
    ind_el = p1_after._p.find(f".//{qn('w:ind')}")
    assert ind_el is not None and ind_el.get(qn("w:firstLineChars")) == "200"


def test_w1_t05_latex_indent_align_quote_abstract_and_inline_spacing() -> None:
    """W1-T05: LaTeX \\noindent/\\indent, quote/quotation, center/flushright, abstract, and \\quad/\\qquad/\\hspace."""
    tex = r"""\documentclass{article}
\begin{document}

\begin{abstract}
本研究系统验证长上下文稀疏路由模型。
\end{abstract}

\section{引言}

\noindent 本段显式取消首行缩进。

\indent 本段显式启用首行缩进，并包含行内空白：甲\enspace 乙\quad 丙\qquad 丁\hspace{1.5em}戊\hspace{-3pt}己。

\begin{quote}
学术引文块应当呈现独立的左右缩进层次。
\end{quote}

\begin{center}
居中声明段落
\end{center}

\begin{flushright}
右对齐落款：2026年11月
\end{flushright}

\end{document}
"""
    _, blocks, _ = parse_document_with_meta(tex, fmt="latex", filename="typo.tex")

    def _find(substr: str):
        hits = [b for b in blocks if substr in b.clean_text]
        assert hits, f"Block containing {substr!r} not found in {[b.clean_text for b in blocks]}"
        return hits[0]

    b_abs = _find("本研究系统验证长上下文稀疏路由模型")
    assert b_abs.meta.get("style", {}).get("semantic_role") == "abstract"

    b_no = _find("本段显式取消首行缩进")
    assert b_no.meta.get("style", {}).get("explicit_indent") == "none"
    assert b_no.meta.get("style", {}).get("first_line_indent_em") == 0.0

    b_ind = _find("本段显式启用首行缩进")
    assert b_ind.meta.get("style", {}).get("explicit_indent") == "indent"
    assert b_ind.meta.get("style", {}).get("first_line_indent_em") == 2.0
    assert "⟦SP:0.5⟧" in b_ind.clean_text
    assert "⟦SP:1⟧" in b_ind.clean_text
    assert "⟦SP:2⟧" in b_ind.clean_text
    assert "⟦SP:1.5⟧" in b_ind.clean_text
    assert "hspace" not in b_ind.clean_text and "-3pt" not in b_ind.clean_text

    b_q = _find("学术引文块应当呈现独立的左右缩进层次")
    assert b_q.block_type == "blockquote"
    assert b_q.meta.get("style", {}).get("quote_depth", 0) >= 1
    assert b_q.meta.get("style", {}).get("left_indent_em", 0) >= 1.0
    assert b_q.meta.get("style", {}).get("right_indent_em", 0) >= 1.0

    b_c = _find("居中声明段落")
    assert b_c.meta.get("style", {}).get("align") == "center"

    b_r = _find("右对齐落款")
    assert b_r.meta.get("style", {}).get("align") == "right"


def test_w1_t06_latex_recursive_nested_lists_and_span_patch_zero_drift() -> None:
    """W1-T06: LaTeX 3-level nested itemize/enumerate AST parsing and surgical latex_patcher fidelity."""
    tex = r"""\documentclass{article}
\begin{document}
\section{方法}

\noindent 首段无需缩进，供回写保护检查。

\begin{enumerate}
  \item 一级步骤甲
  \begin{itemize}
    \item 二级要点乙
    \begin{itemize}
      \item 三级细节丙
    \end{itemize}
    \item 二级要点丁
  \end{itemize}
  \item 一级步骤戊
\end{enumerate}

\end{document}
"""
    _, blocks, _ = parse_document_with_meta(tex, fmt="latex", filename="nested.tex")
    list_blocks = [b for b in blocks if b.block_type == "list"]
    summary = [(b.clean_text.strip(), b.meta.get("depth"), b.meta.get("ordered")) for b in list_blocks]
    assert len(list_blocks) == 5, f"Expected 5 list items, got {summary}"
    assert [b.meta.get("depth") for b in list_blocks] == [0, 1, 2, 1, 0], f"Wrong nesting depths: {summary}"
    assert [b.meta.get("ordered") for b in list_blocks] == [True, False, False, False, True], f"Wrong ordered flags: {summary}"
    assert [b.clean_text.strip() for b in list_blocks] == ["一级步骤甲", "二级要点乙", "三级细节丙", "二级要点丁", "一级步骤戊"]

    target = [b for b in list_blocks if "三级细节丙" in b.clean_text][0]
    ser_blocks = [
        {"index": b.index, "block_type": b.block_type, "raw_start": b.raw_start, "raw_end": b.raw_end, "source_anchor": b.source_anchor}
        for b in blocks
    ]
    patched_tex, applied, warnings = patch_latex_content(
        tex,
        ser_blocks,
        [{"op": "replace_block", "block_index": target.index, "new_raw": "三级细节丙（已校准）"}],
    )
    assert applied == 1 and not warnings
    assert r"\noindent 首段无需缩进" in patched_tex
    assert "三级细节丙（已校准）" in patched_tex
    assert "二级要点丁" in patched_tex and "一级步骤戊" in patched_tex


def test_w1_t07_markdown_fullwidth_indent_nested_list_children_and_quotes() -> None:
    """W1-T07: Markdown full-width leading spaces, 4-level list child alignment, nested quotes, and hardbreak."""
    md = (
        "# 研究说明\n\n"
        "\u3000\u3000这是以全角空格缩进的中文段落，后接硬换行：第一行  \n第二行。\n\n"
        "- 一级条目\n"
        "  - 二级条目首段\n\n"
        "    二级条目内嵌续段说明。\n\n"
        "    ```python\n"
        "    x = 42\n"
        "    ```\n\n"
        "    $$\n"
        "    E = mc^2\n"
        "    $$\n\n"
        "    - 三级条目\n"
        "      - 四级条目\n\n"
        "> 外层学术引用段落\n"
        ">\n"
        "> > 内层二级嵌套引用段落\n"
    )
    _, blocks, _ = parse_document_with_meta(md, fmt="markdown", filename="notes.md")

    def _find(substr: str):
        hits = [b for b in blocks if substr in b.clean_text]
        assert hits, f"Block containing {substr!r} not found in {[(b.block_type, b.clean_text) for b in blocks]}"
        return hits[0]

    # 1. Leading full-width spaces -> style.first_line_indent_em == 2.0, clean_text stripped of leading \u3000, raw_text kept
    p_fw = _find("这是以全角空格缩进的中文段落")
    assert p_fw.meta.get("style", {}).get("first_line_indent_em") == 2.0
    assert p_fw.meta.get("style", {}).get("explicit_indent") == "indent"
    assert not p_fw.clean_text.startswith("\u3000")
    assert p_fw.raw_text.startswith("\u3000\u3000")
    assert "⟦BR⟧" in p_fw.clean_text

    # 2. 4-level list depths 0..3 + child continuation/code/math blocks aligned with parent_list_depth=1
    list_items = [b for b in blocks if b.block_type == "list"]
    assert [b.meta.get("depth") for b in list_items] == [0, 1, 2, 3], [
        (b.clean_text, b.meta.get("depth")) for b in list_items
    ]
    b_cont = _find("二级条目内嵌续段说明")
    assert b_cont.meta.get("style", {}).get("parent_list_depth") == 1
    b_code = [b for b in blocks if b.block_type == "code" and "x = 42" in b.clean_text][0]
    assert b_code.meta.get("style", {}).get("parent_list_depth") == 1
    b_math = [b for b in blocks if b.block_type == "math" and "mc^2" in b.clean_text][0]
    assert b_math.meta.get("style", {}).get("parent_list_depth") == 1

    # 3. Nested blockquotes preserve distinct quote_depth=1 and quote_depth=2
    q_outer = _find("外层学术引用段落")
    q_inner = _find("内层二级嵌套引用段落")
    assert q_outer.block_type == "blockquote" and q_outer.meta.get("style", {}).get("quote_depth") == 1
    assert q_inner.block_type == "blockquote" and q_inner.meta.get("style", {}).get("quote_depth") == 2


def test_w1_t08_analyzer_doc_language_and_pure_style_zero_alerts() -> None:
    """W1-T08: Document language detection, style passthrough, and zero false-positive alerts on pure layout changes."""
    zh_md = "# 摘要\n\n\u3000\u3000稀疏注意力在大模型长上下文推理中对显存效率具有重要影响。\n\n> 外层引用\n>\n> > 内层引用\n"
    en_md = "# Introduction\n\nSparse attention routing governs decode throughput in long-context Transformers.\n"

    prev_zh = preview_document(zh_md, fmt="markdown", filename="zh.md")
    prev_en = preview_document(en_md, fmt="markdown", filename="en.md")

    assert prev_zh.get("doc_language") == "zh" and float(prev_zh.get("cjk_ratio", 0.0)) >= 0.25
    assert prev_en.get("doc_language") == "en" and float(prev_en.get("cjk_ratio", 1.0)) < 0.05

    p_blk = [b for b in prev_zh["blocks"] if "稀疏注意力在大模型" in b["clean_text"]][0]
    assert (p_blk.get("style") or {}).get("first_line_indent_em") == 2.0

    # Pure indentation difference in LaTeX & Markdown produces 100% similarity and 0 alerts
    tex_old = r"\documentclass{article}\begin{document}\section{Results}" + "\n\n" + r"\noindent Error is 14.2\% ($p < 0.01$)." + "\n\n\\end{document}"
    tex_new = r"\documentclass{article}\begin{document}\section{Results}" + "\n\n" + r"\indent Error is 14.2\% ($p < 0.01$)." + "\n\n\\end{document}"
    cmp_tex = compare_documents(tex_old, tex_new, "latex", "latex", "a.tex", "b.tex", protected_terms=["Error"])
    assert cmp_tex["summary"]["overall_similarity"] == 100.0
    assert cmp_tex["alerts"] == [], f"Pure indent change triggered alerts: {cmp_tex['alerts']}"

    md_old = "# 结果\n\n稀疏推理相对误差为 14.2%。\n\n- 一级\n  - 二级\n    - 三级\n      - 四级\n\n> 外层\n>\n> > 内层\n"
    md_new = "# 结果\n\n\u3000\u3000稀疏推理相对误差为 14.2%。\n\n- 一级\n  - 二级\n    - 三级\n      - 四级\n\n> 外层\n>\n> > 内层\n"
    cmp_md = compare_documents(md_old, md_new, "markdown", "markdown", "a.md", "b.md")
    assert cmp_md["summary"]["overall_similarity"] == 100.0
    assert cmp_md["alerts"] == [], f"Pure full-width indent change triggered alerts: {cmp_md['alerts']}"
    l4 = [p for p in cmp_md["paragraphs"] if p["block_type"] == "list" and "四级" in p["new_clean"]][0]
    assert (l4.get("list_meta") or {}).get("depth") == 3
    q2 = [p for p in cmp_md["paragraphs"] if p["block_type"] == "blockquote" and "内层" in p["new_clean"]][0]
    assert q2.get("quote_depth") == 2


def test_w1_t10_t11_t12_browser_typography_themes_and_diff() -> None:
    """W1-T10/T11/T12: Real Headless Chrome CDP verification of typography styles, persistence, clean copy, themes & D-03 Diff."""
    import json
    import shutil
    import subprocess
    import tempfile
    import threading
    import time
    import urllib.request
    import uvicorn

    from backend.export import find_local_chrome
    from backend.main import app
    from tests.test_performance_benchmark import _MiniCDP, _find_free_port

    chrome = find_local_chrome()
    assert chrome, "Local Chrome/Chromium required for real browser typography verification"

    port = _find_free_port()
    cdp_port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    srv_thread = threading.Thread(target=server.run, daemon=True)
    srv_thread.start()
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"{base_url}/api/health", timeout=1.0) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(0.15)

    created_proj_id = None
    chrome_proc = None
    cdp = None
    user_dir = tempfile.mkdtemp(prefix="pd_w1_cdp_")

    try:
        def _post_json(path: str, data: dict) -> dict:
            req = urllib.request.Request(
                f"{base_url}{path}",
                data=json.dumps(data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15.0) as r:
                return json.loads(r.read().decode("utf-8"))

        md_v1 = (
            "# 长上下文大模型阅读排版测试\n\n"
            "## 摘要\n\n"
            "本研究系统评估了长上下文大语言模型中自适应键值缓存路由与稀疏注意力耦合机制。\n\n"
            "## 1. 引言\n\n"
            "键值缓存显存膨胀已成为长序列推理面临的重要系统瓶颈，其稀疏路由策略决定解码延迟。\n\n"
            "\u3000\u3000这是带全角空格首行缩进的对照正文段落，用于验证剪贴板拷贝不携带伪空格。\n\n"
            "- 一级列表条目\n"
            "  - 二级列表条目\n\n"
            "    二级列表内嵌续段说明。\n\n"
            "    ```python\n"
            "    latency_ms = 14.2\n"
            "    ```\n\n"
            "    $$\n"
            "    \\mathrm{Attn}(Q, K, V) = \\mathrm{softmax}\\left(\\frac{QK^\\top}{\\sqrt{d_k}}\\right) V\n"
            "    $$\n\n"
            "    - 三级列表条目\n"
            "      - 四级列表条目\n\n"
            "> 外层学术引用段落内容\n"
            ">\n"
            "> > 内层二级嵌套引用段落内容\n\n"
            "## 参考文献\n\n"
            "[1] Vaswani, A. et al. (2017). Attention Is All You Need. NeurIPS, 30, 5998-6008.\n"
        )
        md_v2 = md_v1.replace("决定解码延迟", "显著决定长程解码延迟").replace("外层学术引用段落内容", "外层学术引用修订内容")

        proj = _post_json(
            "/api/projects",
            {"name": "__W1_TYPO_E2E__", "primary_format": "markdown", "default_doc_name": "TypoDoc"},
        )
        created_proj_id = proj["id"]
        doc_id = proj["documents"][0]["id"]
        _post_json(
            f"/api/documents/{doc_id}/versions",
            {"label": "v1 · 初稿", "source_tag": "初稿", "filename": "typo_v1.md", "format": "markdown", "content": md_v1},
        )
        _post_json(
            f"/api/documents/{doc_id}/versions",
            {"label": "v2 · 修订", "source_tag": "润色", "filename": "typo_v2.md", "format": "markdown", "content": md_v2},
        )

        # Also create an English doc inside the same project to verify auto preset leaves English unindented
        en_doc = _post_json(
            f"/api/projects/{created_proj_id}/documents",
            {"name": "EnDoc", "doc_type": "manuscript", "primary_format": "markdown"},
        )
        _post_json(
            f"/api/documents/{en_doc['id']}/versions",
            {
                "label": "v1 · EN",
                "source_tag": "初稿",
                "filename": "en_v1.md",
                "format": "markdown",
                "content": "# Introduction\n\nSparse attention heads exhibit distinct entropy profiles across long-context Transformer layers.\n",
            },
        )

        chrome_proc = subprocess.Popen(
            [
                chrome,
                "--headless=new",
                f"--remote-debugging-port={cdp_port}",
                f"--user-data-dir={user_dir}",
                "--window-size=1440,900",
                "--no-first-run",
                "--disable-default-apps",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        ws_url = None
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json", timeout=1.0) as r:
                    tabs = json.loads(r.read().decode("utf-8"))
                    if tabs and tabs[0].get("webSocketDebuggerUrl"):
                        ws_url = tabs[0]["webSocketDebuggerUrl"]
                        break
            except Exception:
                time.sleep(0.15)
        assert ws_url, "Chrome CDP failed to start"

        cdp = _MiniCDP(ws_url)
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")
        cdp.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1440, "height": 900, "deviceScaleFactor": 2, "mobile": False},
        )

        # W1-T10 part 1: Inject legacy v1.1.0 localStorage BEFORE loading SPA, then reload cleanly
        cdp.send("Page.navigate", {"url": base_url})
        time.sleep(1.2)
        cdp.eval_js(
            """
            (() => {
              window.localStorage.setItem('paperdiff_ui_prefs', JSON.stringify({
                fontMode: 'serif',
                fontSize: 15.5,
                readWidth: 'standard',
                smartFold: true,
                showFigures: true,
                highlightAiIsms: true,
              }));
              return true;
            })()
            """
        )
        cdp.send("Page.reload", {"ignoreCache": True})
        time.sleep(1.2)

        # Open any doc in Single-Doc Read mode cleanly via Home navigation
        def _open_doc_in_read(doc_name: str, expected_text: str) -> dict:
            cdp.send("Page.navigate", {"url": base_url})
            time.sleep(0.9)
            return cdp.eval_js(
                f"""
                (async () => {{
                  const wait = (ms) => new Promise(r => setTimeout(r, ms));
                  for (let i = 0; i < 40; i++) {{
                    const span = Array.from(document.querySelectorAll('span')).find(
                      el => el.textContent && el.textContent.trim() === {json.dumps(doc_name)}
                    );
                    if (span) {{ span.click(); break; }}
                    await wait(100);
                  }}
                  // Wait for initial document fetch & default mode render to settle first
                  for (let i = 0; i < 60; i++) {{
                    if (document.body.innerText.includes({json.dumps(expected_text)})) break;
                    await wait(100);
                  }}
                  // Then switch to Single-Doc Read mode and ensure it stays active
                  for (let i = 0; i < 60; i++) {{
                    const readBtn = Array.from(document.querySelectorAll('button')).find(
                      b => b.textContent && b.textContent.trim() === '阅读'
                    );
                    const isReadActive = !!(readBtn && readBtn.className.includes('text-blue-700'));
                    if (readBtn && !isReadActive) {{
                      readBtn.click();
                    }} else if (
                      isReadActive &&
                      document.body.innerText.includes({json.dumps(expected_text)}) &&
                      document.querySelectorAll('[id^="para-"]').length > 0 &&
                      !document.body.innerText.includes('正在解析学术排版')
                    ) {{
                      break;
                    }}
                    await wait(100);
                  }}
                  await wait(250);
                  return {{
                    blocks: document.querySelectorAll('[id^="para-"]').length,
                    prefs: JSON.parse(window.localStorage.getItem('paperdiff_ui_prefs') || '{{}}'),
                  }};
                }})()
                """
            )

        opened_zh = _open_doc_in_read("TypoDoc", "键值缓存显存膨胀已成为长序列推理")
        assert opened_zh["blocks"] >= 10, f"TypoDoc failed to render blocks: {opened_zh}"
        assert opened_zh["prefs"].get("typographyPreset") == "auto", opened_zh["prefs"]

        # W1-T11: Verify computed styles, 4-level list, list children, nested quote, abstract, reference & clean selection
        read_check = cdp.eval_js(
            """
            (() => {
              const findP = (substr) => Array.from(document.querySelectorAll('p')).find(
                el => el.textContent && el.textContent.includes(substr)
              );
              const pAuto = findP('键值缓存显存膨胀已成为长序列推理');
              const pFw = findP('这是带全角空格首行缩进的对照正文段落');
              const pAbs = findP('本研究系统评估了长上下文大语言模型');
              const pRef = findP('Attention Is All You Need');

              const csAuto = pAuto ? getComputedStyle(pAuto) : null;
              const csFw = pFw ? getComputedStyle(pFw) : null;
              const csAbs = pAbs ? getComputedStyle(pAbs) : null;
              const csRef = pRef ? getComputedStyle(pRef) : null;

              // Clipboard selection check on pFw (must not start with \\u3000 or leading spaces)
              let selectedText = '';
              if (pFw) {
                const range = document.createRange();
                range.selectNodeContents(pFw);
                const sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(range);
                selectedText = sel.toString();
                sel.removeAllRanges();
              }

              // 4-level list paddingLeft & depth-3 bullet symbol
              const listEls = Array.from(document.querySelectorAll('[data-list-depth]'));
              const listPaddings = listEls.map(el => ({
                depth: Number(el.getAttribute('data-list-depth')),
                padLeft: parseFloat(getComputedStyle(el).paddingLeft),
                bullet: (el.querySelector('span') || {}).textContent?.trim() || '',
              }));

              // Child blocks nested under list (parent_list_depth=1)
              const childEls = Array.from(document.querySelectorAll('[data-parent-list-depth]'));
              const childMargins = childEls.map(el => ({
                tag: el.tagName,
                depth: Number(el.getAttribute('data-parent-list-depth')),
                marginLeft: parseFloat(getComputedStyle(el).marginLeft),
              }));

              // Nested blockquotes
              const q1 = document.querySelector('blockquote[data-quote-depth="1"]');
              const q2 = document.querySelector('blockquote[data-quote-depth="2"]');

              // Three-theme WCAG contrast check (luminance ratio >= 4.5 on body text & abstract)
              const parseRgb = (s) => {
                const m = s.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
                return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : [255, 255, 255];
              };
              const lum = ([r, g, b]) => {
                const f = (c) => {
                  const x = c / 255;
                  return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
                };
                return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
              };
              const contrast = (c1, c2) => {
                const l1 = lum(c1), l2 = lum(c2);
                return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
              };

              const themeResults = {};
              const origTheme = document.documentElement.getAttribute('data-theme') || 'light';
              for (const t of ['light', 'sepia', 'dark']) {
                document.documentElement.setAttribute('data-theme', t);
                const bg = parseRgb(getComputedStyle(document.querySelector('main')).backgroundColor);
                const fg = parseRgb(getComputedStyle(pAuto).color);
                const absBg = parseRgb(getComputedStyle(pAbs).backgroundColor);
                const absFg = parseRgb(getComputedStyle(pAbs).color);
                const q2Bg = q2 ? parseRgb(getComputedStyle(q2).backgroundColor) : bg;
                const q2Fg = q2 ? parseRgb(getComputedStyle(q2).color) : fg;
                themeResults[t] = {
                  bodyContrast: Math.round(contrast(bg, fg) * 100) / 100,
                  abstractContrast: Math.round(contrast(absBg, absFg) * 100) / 100,
                  quote2Contrast: Math.round(contrast(q2Bg, q2Fg) * 100) / 100,
                  absBg: getComputedStyle(pAbs).backgroundColor,
                };
              }
              document.documentElement.setAttribute('data-theme', origTheme);

              return {
                autoIndentPx: csAuto ? parseFloat(csAuto.textIndent) : -1,
                autoAlign: csAuto ? csAuto.textAlign : '',
                fwIndentPx: csFw ? parseFloat(csFw.textIndent) : -1,
                selectedText,
                absHasClass: pAbs ? pAbs.classList.contains('pd-abstract-box') : false,
                absPadLeftPx: csAbs ? parseFloat(csAbs.paddingLeft) : -1,
                refPadLeftPx: csRef ? parseFloat(csRef.paddingLeft) : -1,
                refIndentPx: csRef ? parseFloat(csRef.textIndent) : 0,
                listPaddings,
                childMargins,
                q1MarginLeft: q1 ? parseFloat(getComputedStyle(q1).marginLeft) : -1,
                q2MarginLeft: q2 ? parseFloat(getComputedStyle(q2).marginLeft) : -1,
                q2HasClass: q2 ? q2.classList.contains('pd-blockquote-d2') : false,
                themeResults,
              };
            })()
            """
        )

        # Assertions for W1-T11
        assert read_check["autoIndentPx"] >= 28.0, f"Chinese auto 2em indent failed: {read_check}"
        assert read_check["autoAlign"] == "justify", read_check
        assert read_check["fwIndentPx"] >= 28.0, read_check
        assert read_check["selectedText"].startswith("这是带全角空格"), f"Selection leaked indent spaces: {read_check['selectedText']!r}"
        assert read_check["absHasClass"] and read_check["absPadLeftPx"] >= 18.0, read_check
        assert read_check["refPadLeftPx"] >= 25.0 and read_check["refIndentPx"] <= -25.0, read_check
        by_depth = {item["depth"]: item for item in read_check["listPaddings"]}
        assert sorted(by_depth.keys()) == [0, 1, 2, 3], by_depth
        assert by_depth[0]["padLeft"] < by_depth[1]["padLeft"] < by_depth[2]["padLeft"] < by_depth[3]["padLeft"], by_depth
        assert by_depth[3]["bullet"] == "‣", by_depth
        assert len(read_check["childMargins"]) >= 3, read_check["childMargins"]
        assert all(c["marginLeft"] > by_depth[1]["padLeft"] for c in read_check["childMargins"]), read_check["childMargins"]
        assert read_check["q2HasClass"] and read_check["q2MarginLeft"] > read_check["q1MarginLeft"], read_check
        for t, res in read_check["themeResults"].items():
            assert res["bodyContrast"] >= 4.5, f"Low body contrast in {t}: {res}"
            assert res["abstractContrast"] >= 4.5, f"Low abstract contrast in {t}: {res}"
            assert res["quote2Contrast"] >= 4.5, f"Low quote2 contrast in {t}: {res}"
        assert read_check["themeResults"]["light"]["absBg"] != read_check["themeResults"]["dark"]["absBg"]

        # W1-T10 part 2: Switch preset to modern_note in Settings Popover -> immediate DOM update -> persists across reload
        switched = cdp.eval_js(
            """
            (async () => {
              const wait = (ms) => new Promise(r => setTimeout(r, ms));
              const gear = document.querySelector('button[title="排版设置与工具"]');
              if (!gear) return { ok: false, err: 'no gear' };
              gear.click();
              await wait(150);
              const modernBtn = document.querySelector('button[data-typo-preset="modern_note"]');
              if (!modernBtn) return { ok: false, err: 'no modern_note btn' };
              modernBtn.click();
              await wait(200);
              const pAuto = Array.from(document.querySelectorAll('p')).find(
                el => el.textContent && el.textContent.includes('键值缓存显存膨胀已成为长序列推理')
              );
              const cs = pAuto ? getComputedStyle(pAuto) : null;
              return {
                ok: true,
                indentPx: cs ? parseFloat(cs.textIndent) : -1,
                align: cs ? cs.textAlign : '',
                prefs: JSON.parse(window.localStorage.getItem('paperdiff_ui_prefs') || '{}'),
              };
            })()
            """
        )
        assert switched["ok"] and switched["indentPx"] == 0.0 and switched["align"] == "left", switched
        assert switched["prefs"]["typographyPreset"] == "modern_note", switched["prefs"]

        cdp.send("Page.reload", {"ignoreCache": True})
        time.sleep(1.0)
        persisted = _open_doc_in_read("TypoDoc", "键值缓存显存膨胀已成为长序列推理")
        assert persisted["prefs"].get("typographyPreset") == "modern_note", persisted["prefs"]

        # Switch back to auto preset and disable smartFold so DiffWorkspace shows all blocks unfolded
        cdp.eval_js(
            """
            (async () => {
              const wait = (ms) => new Promise(r => setTimeout(r, ms));
              document.querySelector('button[title="排版设置与工具"]')?.click();
              await wait(150);
              document.querySelector('button[data-typo-preset="auto"]')?.click();
              await wait(100);
              const foldLabel = Array.from(document.querySelectorAll('span')).find(
                s => s.textContent && s.textContent.trim() === '折叠未改段落'
              );
              foldLabel?.parentElement?.querySelector('button')?.click();
              await wait(150);
            })()
            """
        )
        _open_doc_in_read("EnDoc", "Sparse attention heads exhibit distinct")
        en_indent = cdp.eval_js(
            """
            (() => {
              const p = Array.from(document.querySelectorAll('p')).find(
                el => el.textContent && el.textContent.includes('Sparse attention heads exhibit distinct')
              );
              return p ? parseFloat(getComputedStyle(p).textIndent) : -1;
            })()
            """
        )
        assert en_indent == 0.0, f"English auto preset should have 0px indent, got {en_indent}"

        # W1-T12: Open TypoDoc in Split & Inline Diff views -> body textIndent === 0px (D-03), list/quote hierarchy preserved, Portal unclipped
        _open_doc_in_read("TypoDoc", "键值缓存显存膨胀已成为长序列推理")
        diff_check = cdp.eval_js(
            """
            (async () => {
              const wait = (ms) => new Promise(r => setTimeout(r, ms));
              const splitBtn = Array.from(document.querySelectorAll('button')).find(
                b => b.textContent && b.textContent.includes('左右对照')
              );
              if (!splitBtn) return { ok: false, err: 'no split btn' };
              splitBtn.click();
              for (let i = 0; i < 60; i++) {
                if (document.querySelector('[data-diff-pane="left"]')) break;
                await wait(100);
              }
              await wait(250);

              const splitParas = Array.from(document.querySelectorAll('[data-diff-pane="left"][data-block-type="paragraph"], [data-diff-pane="right"][data-block-type="paragraph"]'));
              const splitIndents = splitParas.map(el => parseFloat(getComputedStyle(el).textIndent));
              const splitLists = Array.from(document.querySelectorAll('[data-diff-pane="right"][data-list-depth]')).map(el => ({
                depth: Number(el.getAttribute('data-list-depth')),
                padLeft: parseFloat(getComputedStyle(el).paddingLeft),
              }));
              const splitQ2 = document.querySelector('[data-diff-pane="right"][data-quote-depth="2"]');
              const splitQ2Margin = splitQ2 ? parseFloat(getComputedStyle(splitQ2).marginLeft) : -1;

              // Return center coordinates of a visible paragraph gutter similarity badge for real CDP mouse hover
              let gutterPt = null;
              const simSpan = Array.from(document.querySelectorAll('[id^="para-"] span')).find(
                s => s.textContent && s.textContent.trim().startsWith('相似 ')
              );
              if (simSpan && simSpan.parentElement) {
                simSpan.parentElement.scrollIntoView({ block: 'center' });
                await wait(120);
                const r = simSpan.parentElement.getBoundingClientRect();
                gutterPt = { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
              }

              return {
                ok: true,
                splitParaCount: splitParas.length,
                splitIndents,
                splitLists,
                splitQ2Margin,
                gutterPt,
              };
            })()
            """
        )
        assert diff_check["ok"], diff_check
        assert diff_check["splitParaCount"] >= 2 and all(x == 0.0 for x in diff_check["splitIndents"]), diff_check
        s_lists = {x["depth"]: x["padLeft"] for x in diff_check["splitLists"]}
        assert s_lists[0] < s_lists[1] < s_lists[2] < s_lists[3], s_lists
        assert diff_check["splitQ2Margin"] > 0, diff_check
        assert diff_check["gutterPt"], diff_check

        # Real CDP mouseMoved over paragraph gutter -> verify FloatingHoverCard Portal renders in document.body unclipped (I4)
        cdp.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": 5, "y": 5})
        time.sleep(0.05)
        cdp.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": diff_check["gutterPt"]["x"], "y": diff_check["gutterPt"]["y"]})
        time.sleep(0.25)
        portal_rect = cdp.eval_js(
            """
            (() => {
              const card = Array.from(document.body.children).find(
                el => el.textContent && el.textContent.includes('词序 LCS')
              );
              if (!card) return null;
              const r = card.getBoundingClientRect();
              return { width: Math.round(r.width), height: Math.round(r.height), inBody: card.parentElement === document.body };
            })()
            """
        )
        assert portal_rect and portal_rect["inBody"] and portal_rect["height"] > 40 and portal_rect["width"] > 150, portal_rect

        # Switch to Inline view and verify D-03 compact left-aligned body + list/quote hierarchy
        inline_check = cdp.eval_js(
            """
            (async () => {
              const wait = (ms) => new Promise(r => setTimeout(r, ms));
              const inlineBtn = Array.from(document.querySelectorAll('button')).find(
                b => b.textContent && b.textContent.includes('行内融合')
              );
              inlineBtn?.click();
              for (let i = 0; i < 50; i++) {
                if (document.querySelector('[data-diff-pane="inline"]')) break;
                await wait(100);
              }
              await wait(200);
              const inlineParas = Array.from(document.querySelectorAll('[data-diff-pane="inline"][data-block-type="paragraph"]'));
              const inlineIndents = inlineParas.map(el => parseFloat(getComputedStyle(el).textIndent));
              const inlineLists = Array.from(document.querySelectorAll('[data-diff-pane="inline"][data-list-depth]')).map(el => ({
                depth: Number(el.getAttribute('data-list-depth')),
                padLeft: parseFloat(getComputedStyle(el).paddingLeft),
              }));
              const inlineQ2 = document.querySelector('[data-diff-pane="inline"][data-quote-depth="2"]');
              const inlineQ2Margin = inlineQ2 ? parseFloat(getComputedStyle(inlineQ2).marginLeft) : -1;
              return { inlineParaCount: inlineParas.length, inlineIndents, inlineLists, inlineQ2Margin };
            })()
            """
        )
        assert inline_check["inlineParaCount"] >= 1 and all(x == 0.0 for x in inline_check["inlineIndents"]), inline_check
        i_lists = {x["depth"]: x["padLeft"] for x in inline_check["inlineLists"]}
        assert i_lists[0] < i_lists[1] < i_lists[2] < i_lists[3], i_lists
        assert inline_check["inlineQ2Margin"] > 0, inline_check

    finally:
        if cdp:
            cdp.close()
        if chrome_proc:
            chrome_proc.terminate()
            try:
                chrome_proc.wait(timeout=3)
            except Exception:
                chrome_proc.kill()
        if created_proj_id:
            try:
                req = urllib.request.Request(f"{base_url}/api/projects/{created_proj_id}", method="DELETE")
                urllib.request.urlopen(req, timeout=5.0)
            except Exception:
                pass
        shutil.rmtree(user_dir, ignore_errors=True)
        server.should_exit = True
        srv_thread.join(timeout=3)


def test_w1_t13_offline_single_pdf_typography_sync() -> None:
    """W1-T13: Offline print_html_single & pdf_single sync typography rules (with & without typography_prefs) with zero CDN links."""
    from fastapi.testclient import TestClient

    from backend.export import find_local_chrome
    from backend.main import app

    zh_tex = r"""\documentclass{article}
\begin{document}
\begin{abstract}
本研究系统探讨稀疏注意力在长上下文大模型中的动态路由机制。
\end{abstract}
\section{引言}
\noindent 显式取消缩进的首段说明，包含作者\qquad 日期水平间距。

常规中文正文段落应当在智能默认模式下自动采用两字符首行缩进与两端对齐。

\begin{center}
居中声明段落不应缩进。
\end{center}

\begin{itemize}
  \item 一级要点
  \begin{itemize}
    \item 二级要点
    \begin{itemize}
      \item 三级要点
      \begin{itemize}
        \item 四级要点
      \end{itemize}
    \end{itemize}
  \end{itemize}
\end{itemize}

\begin{quote}
外层学术引用内容。
\begin{quote}
内层二级学术引用内容。
\end{quote}
\end{quote}
\end{document}
"""

    with TestClient(app) as client:
        # 1. Backward-compatible call WITHOUT typography_prefs (defaults to smart academic 'auto')
        r_default = client.post(
            "/api/export",
            json={
                "single_content": zh_tex,
                "single_label": "v1 · 默认",
                "project_name": "W1 PDF Sync",
                "export_type": "print_html_single",
            },
        )
        assert r_default.status_code == 200
        h_def = r_default.text
        for cdn in ("cdn.jsdelivr.net", "unpkg.com", "cdnjs.cloudflare.com", "fonts.googleapis.com"):
            assert cdn not in h_def, f"External CDN leaked into offline print HTML: {cdn}"
        assert "abstract-box" in h_def, "Abstract box styling missing in single print HTML"
        assert "text-indent:2.0em" in h_def or "text-indent:2em" in h_def, "Chinese auto 2em indent missing in print HTML"
        assert "text-align:center" in h_def, "Centered paragraph alignment missing in print HTML"
        assert "width:2.0em" in h_def or "width:2em" in h_def, "Inline \\qquad SP spacing missing in print HTML"
        assert "‣" in h_def, "4th-level list bullet symbol (‣) missing in print HTML"
        assert "quote-depth-2" in h_def, "Nested quote_depth=2 styling missing in print HTML"

        # 2. Explicit modern_note typography_prefs overrides body indent -> 0 and align -> left
        r_modern = client.post(
            "/api/export",
            json={
                "single_content": zh_tex,
                "single_label": "v1 · 现代笔记",
                "project_name": "W1 PDF Sync",
                "export_type": "print_html_single",
                "typography_prefs": {
                    "typographyPreset": "modern_note",
                    "indentMode": "none",
                    "lineHeight": 1.82,
                    "paragraphGap": "relaxed",
                    "textAlign": "left",
                },
            },
        )
        assert r_modern.status_code == 200
        h_mod = r_modern.text
        assert "text-indent:2.0em" not in h_mod and "text-indent:2em" not in h_mod, (
            "modern_note preset should disable 2em body first-line indent in print HTML"
        )
        assert "text-align:left" in h_mod

        # 3. Real offline PDF bytes generation via local headless Chrome
        if find_local_chrome():
            r_pdf = client.post(
                "/api/export",
                json={
                    "single_content": zh_tex,
                    "single_label": "v1 · PDF",
                    "project_name": "W1 PDF Sync",
                    "export_type": "pdf_single",
                    "typography_prefs": {
                        "typographyPreset": "zh_thesis",
                        "indentMode": "2em",
                        "lineHeight": 1.92,
                        "paragraphGap": "compact",
                        "textAlign": "justify",
                    },
                },
            )
            assert r_pdf.status_code == 200
            assert r_pdf.headers["content-type"] == "application/pdf"
            assert r_pdf.content.startswith(b"%PDF-") and len(r_pdf.content) > 10_000


def test_w1_t01_legacy_blocks_without_style_safe() -> None:
    """W1-T01: Legacy preview payloads lacking `style` and `doc_language` render safely with zero character loss."""
    from backend.export import render_single_print_html

    legacy_preview = {
        "format": "markdown",
        "health_score": 96,
        "summary": {"word_count": 18},
        "blocks": [
            {
                "index": 0,
                "block_type": "heading",
                "section_level": 1,
                "clean_text": "历史章节标题",
                "items": [{"kind": "text", "text": "历史章节标题"}],
            },
            {
                "index": 1,
                "block_type": "paragraph",
                "clean_text": "这是一段不含 style 与 doc_language 字段的旧版本正文内容。",
                "items": [{"kind": "text", "text": "这是一段不含 style 与 doc_language 字段的旧版本正文内容。"}],
            },
            {
                "index": 2,
                "block_type": "list",
                "list_meta": {"ordered": False, "item_num": 1},
                "clean_text": "旧版列表项",
                "items": [{"kind": "text", "text": "旧版列表项"}],
            },
        ],
    }
    html_out = render_single_print_html(legacy_preview, "Legacy Doc", "v1.1.0")
    assert "历史章节标题" in html_out
    assert "这是一段不含 style 与 doc_language 字段的旧版本正文内容。" in html_out
    assert "旧版列表项" in html_out



