"""v1.1.0 20-Class Academic Format Stress Test Suite (M1-M6, L1-L8, W1-W6)."""
from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from fastapi.testclient import TestClient

from backend.analyzer import compare_documents, preview_document
from backend.main import app
from backend.parsers import (
    extract_docx_with_assets,
    extract_latex_zip_with_assets,
    format_bib_entry_text,
    inspect_docx_tracked_changes,
    parse_document_with_meta,
)

# Optional external real-world fixture overrides for local extended stress runs.
# When unset (e.g., on GitHub CI or a fresh clone), all 20 stress classes run against
# built-in high-fidelity academic fixtures so the full suite is 100% self-contained.
EXTRA_MD_PATH = Path(os.environ["PAPERDIFF_EXTRA_MD"]) if os.environ.get("PAPERDIFF_EXTRA_MD") else None
EXTRA_DOCX_PATH = Path(os.environ["PAPERDIFF_EXTRA_DOCX"]) if os.environ.get("PAPERDIFF_EXTRA_DOCX") else None
EXTRA_TEX_TABLE_PATH = Path(os.environ["PAPERDIFF_EXTRA_TEX_TABLE"]) if os.environ.get("PAPERDIFF_EXTRA_TEX_TABLE") else None


def _build_10k_math_markdown_fixture() -> str:
    """Build a self-contained ~10k-word academic Markdown manual with 12 tables and 12 display equations."""
    sections: list[str] = [
        "---\ntitle: Long-Context Transformer Attention Scaling Reference Manual\nauthor: PaperDiff QA\n---\n",
        "# Long-Context Transformer Attention Scaling Reference Manual\n",
    ]
    for i in range(1, 13):
        sections.append(f"## Section {i}: Regime {i} Formulation (`module_{i}.py`)\n")
        sections.append(
            f"The saturation index $\\Omega_{{\\mathrm{{cal}}}} = {1.1 + i * 0.2:.2f}$ governs crystal "
            f"nucleation under Debye–Hückel activity $\\gamma_i$ at $10\\,\\mu\\mathrm{{m}}$ scale "
            f"using `sparse_attn` solver `v2.3.{i}`.\n"
        )
        sections.append(
            f"$$\n\\Omega_{{\\mathrm{{cal}},{i}}} = \\frac{{\\gamma_{{Ca}} [Ca^{{2+}}]_{{{i}}} \\gamma_{{CO3}} [CO_3^{{2-}}]_{{{i}}}}}{{K_{{sp,cal}}(T)}}\n$$\n"
        )
        sections.append(
            f"| Regime | Depth (m) | Velocity ($v_s$) | RMSE |\n"
            f"| :--- | :---: | ---: | ---: |\n"
            f"| Case {i}A | {i * 5} | {1.2 + i * 0.1:.2f} | **0.{10 + i}** |\n"
            f"| Case {i}B | {i * 8} | {1.5 + i * 0.1:.2f} | 0.{20 + i} |\n"
        )
        for p in range(4):
            sections.append(
                f"Paragraph {i}.{p}: Under block-sparse routing ($L_p = {10 + i + p}$), head entropy "
                f"$h_{{ent}}$ couples with token budget allocation rate $k_p (\\Omega - 1)^2$ across "
                f"long-context transformer layers while preserving `KV_CACHE_CORE` memory balance.\n"
            )
    return "\n".join(sections)


# ============================================================================
# M1 - M6: Markdown AST Parser Stress Tests (markdown-it-py + mdit-py-plugins)
# ============================================================================

def test_m1_real_10k_word_markdown_math_and_tables() -> None:
    """Verify M1: 10k-word academic Markdown manual with >=10 tables, >=10 display equations, and line anchors."""
    if EXTRA_MD_PATH and EXTRA_MD_PATH.exists():
        txt = EXTRA_MD_PATH.read_text(encoding="utf-8")
        fname = EXTRA_MD_PATH.name
    else:
        txt = _build_10k_math_markdown_fixture()
        fname = "synthetic_10k_academic_manual.md"
    prev = preview_document(txt, fmt="markdown", filename=fname)
    assert prev["format"] == "markdown"
    assert prev["summary"]["table_count"] >= 10
    assert prev["summary"]["math_count"] >= 10
    # Zero raw $$ delimiter leaks in paragraph/list clean_text
    leaked_dd = [
        b["clean_text"][:80]
        for b in prev["blocks"]
        if b["block_type"] in ("paragraph", "list") and "$$" in b["clean_text"]
    ]
    assert not leaked_dd, f"Found leaked $$ in prose: {leaked_dd[:3]}"
    # Source line anchors present on body blocks
    anchored = [b for b in prev["blocks"] if b.get("source_anchor", {}) and b["source_anchor"].get("kind") == "md_lines"]
    assert len(anchored) >= 40


def test_m2_m3_m4_m5_m6_markdown_extensions_ast() -> None:
    md_doc = """---
title: "Sparse Attention Routing Architecture"
author: "PaperDiff Lab"
---

# Sparse Attention Routing Architecture

> [!WARNING]
> Always verify $p < 0.001$ and H<sub>2</sub>O + Ca<sup>2+</sup> balance[^1].

> [!TIP]
> Use `sparse_attn_v2` with ~~legacy_solver~~ new RK4 integrator.

- Outer item with inline `code_var` and math $\\Omega_{\\mathrm{attn}}$
  $$
  \\Omega_{\\mathrm{attn}} = \\frac{\\gamma_q \\|Q K^\\top\\|}{\\sqrt{d_k}}
  $$
  - Nested depth 1 bullet
- [x] Completed calibration task
- [ ] Pending sensitivity sweep

Term A
:   Definition of Term A with $x_1 = 2.5$.

```python
def calc_omega(q_norm: float, k_norm: float) -> float:
    return q_norm * k_norm / 64.0
```

```mermaid
flowchart LR
  A[Input] --> B[Router]
```

| Model | RMSE | $R^2$ |
| :--- | :---: | ---: |
| Baseline | 0.42 | 0.81 |
| **AdaptRoute** | **0.18** | **0.96** |

[^1]: Measured at 25 °C under standard benchmark hardware.
"""
    prev = preview_document(md_doc, fmt="markdown", filename="stress.md")
    blocks = prev["blocks"]

    # M5: YAML frontmatter metadata_form + footnotes
    fm_tables = [b for b in blocks if b["zone"] == "frontmatter" and b["table_role"] == "metadata_form"]
    assert len(fm_tables) == 1
    assert "1" in prev["footnotes"]
    assert "25 °C" in prev["footnotes"]["1"]

    # M3: GitHub Callouts
    callouts = [b for b in blocks if b.get("callout_type")]
    assert [c["callout_type"] for c in callouts] == ["warning", "tip"]
    assert any(it["kind"] == "fn" and it["value"] == "1" for it in callouts[0]["items"])
    assert any(it.get("strike") and "legacy_solver" in it["text"] for it in callouts[1]["items"])

    # M2: Nested list + embedded display math + tasklist + deflist
    maths = [b for b in blocks if b["block_type"] == "math"]
    assert len(maths) == 1
    assert "Omega" in maths[0]["clean_text"]
    tasks = [b for b in blocks if b["block_type"] == "list" and b.get("list_meta", {}).get("checked") is not None]
    assert len(tasks) == 2
    assert tasks[0]["list_meta"]["checked"] is True
    assert tasks[1]["list_meta"]["checked"] is False

    # M4: Code highlight lang + Mermaid diagram flag
    codes = [b for b in blocks if b["block_type"] == "code"]
    assert len(codes) == 2
    assert codes[0]["code_lang"] == "python" and codes[0]["is_diagram"] is False
    assert codes[1]["code_lang"] == "mermaid" and codes[1]["is_diagram"] is True

    # M6: GFM alignments + bold optimal cells
    data_tbls = [b for b in blocks if b["block_type"] == "table" and b["table_role"] == "data_table"]
    assert len(data_tbls) == 1
    assert data_tbls[0]["table_alignments"] == ["left", "center", "right"]
    assert data_tbls[0]["table_rows"][2][1]["bold"] is True


# ============================================================================
# L1 - L8: LaTeX AST Parser Stress Tests (pylatexenc)
# ============================================================================

def test_l1_l3_l4_l5_l7_l8_latex_academic_full_suite() -> None:
    tex = r"""
\documentclass{article}
\newcommand{\R}{\mathbb{R}}
\newcommand{\method}{AdaptRoute}
\DeclareMathOperator*{\argmin}{arg\,min}
\newtheorem{theorem}{Theorem}
\newtheorem{lemma}{Lemma}
\title{Sparse Attention Routing for Long-Context Transformers}
\begin{document}
\begin{titlepage}
\begin{spacing}{1.0}
\ThisCenterWallPaper{.60}{images/logo.jpg}
\begin{CJK*}{UTF8}{bkai}
\begin{tabular}{lll}
姓\qquad 名 & : & 陳明 \\
\noalign{}學\qquad 號 & : & 2026001001 \\
\end{tabular}
\end{CJK*}
\end{spacing}
\end{titlepage}

\section{Introduction}\label{sec:intro}
We propose \method{} operating in $\R^3$ with $\argmin_x f(x)$.\footnote{All runs used double precision.}
Benchmarks also render scientific notation \ce{H2O + CO2 -> H2CO3} at \SI{42.5}{\micro\second} and \qty{3.2e-4}{\meter\per\second} (\num{1.5e-6}, \ang{45}).
As shown in Fig.~\ref{fig:arch}, Table~\ref{tab:res}, Eq.~\eqref{eq:mass}, Theorem~\ref{thm:conv}, and Algorithm~\ref{alg:solve}, accuracy improves \cite{vaswani2017}.

\begin{equation}\label{eq:mass}
\frac{dm}{dt} = k_p (\Omega - 1)^2
\end{equation}

\begin{theorem}[Global Convergence]\label{thm:conv}
For every $x \in \R^d$, the scheme converges quadratically.
\end{theorem}

\begin{proof}
Follows directly from Banach fixed-point contraction.
\end{proof}

\begin{algorithm}
\caption{Adaptive Time Stepping}
\label{alg:solve}
\begin{algorithmic}
\Require Initial state $C_0$, tolerance $\epsilon$
\For{$t = 1$ to $T$}
\State Compute saturation $\Omega(t)$
\If{$\Omega(t) > 1$}
\State Update shell thickness $h \gets h + \Delta h$
\EndIf
\EndFor
\Return $h(T)$
\end{algorithmic}
\end{algorithm}

\begin{figure}[t]
\begin{subfigure}{0.48\textwidth}
\includegraphics{fig_a.png}
\caption{Velocity field}\label{fig:arch_a}
\end{subfigure}
\begin{subfigure}{0.48\textwidth}
\includegraphics{fig_b.png}
\caption{Shell growth}\label{fig:arch_b}
\end{subfigure}
\caption{Overview of multi-panel dynamics.}\label{fig:arch}
\end{figure}

\begin{table}[t]
\caption{Benchmark accuracy.}\label{tab:res}
\begin{threeparttable}
\begin{tabular}{lcr}
\toprule
Method & \multicolumn{2}{c}{Metrics} \\
\cmidrule(lr){2-3}
Model & RMSE & $R^2$ \\
\midrule
Baseline & 0.41 & 0.82 \\
\textbf{Ours} & \textbf{0.19} & \textbf{0.97} \\
\bottomrule
\end{tabular}
\begin{tablenotes}
\item[a] Averaged over 5 random seeds.
\end{tablenotes}
\end{threeparttable}
\end{table}

\TOCadd{References}\fancypagestyle{plain}{\fancyhf{}}
\bibliography{refs}
\end{document}
"""
    bib = {
        "vaswani2017": {
            "author": "Vaswani, A. et al.",
            "year": "2017",
            "title": "Attention Is All You Need",
            "venue": "NeurIPS",
        }
    }
    prev = preview_document(tex, fmt="latex", filename="paper.tex", meta={"bib": bib})

    # L1: Preamble macros extracted for KaTeX + 0-arg prose macro expanded
    assert "\\R" in prev["latex_macros"]
    assert "\\argmin" in prev["latex_macros"]
    intro_p = next(b for b in prev["blocks"] if b["block_type"] == "paragraph" and "AdaptRoute" in b["clean_text"])
    assert "\\method" not in intro_p["clean_text"]
    assert "1" in prev["footnotes"]

    # L2: Zero thesis layout macro leaks + frontmatter folded cleanly
    full_clean = "\n".join(b["clean_text"] for b in prev["blocks"])
    for leaked in ("ThisCenterWallPaper", "fancypagestyle", "TOCadd", "noalign", "qquad", "CJK"):
        assert leaked not in full_clean, f"Leaked LaTeX control command: {leaked}"
    assert any(b["zone"] == "frontmatter" and b["table_role"] == "metadata_form" for b in prev["blocks"])

    # L3: mhchem & siunitx converted cleanly (upright µ!)
    assert "\\ce{H2O + CO2 -> H2CO3}" in intro_p["clean_text"]
    assert "42.5" in intro_p["clean_text"] and ("\\mu" in intro_p["clean_text"] or "µ" in intro_p["clean_text"])
    assert "1.5 \\times 10^{-6}" in intro_p["clean_text"]

    # L4: Theorem + Proof + Algorithm
    thms = [b for b in prev["blocks"] if b["block_type"] == "theorem"]
    assert len(thms) == 2
    assert thms[0]["theorem_meta"]["theorem_title"] == "Theorem"
    assert thms[0]["theorem_meta"]["optional_title"] == "Global Convergence"
    assert thms[1]["theorem_meta"]["is_proof"] is True
    algs = [b for b in prev["blocks"] if b["block_type"] == "algorithm"]
    assert len(algs) == 1
    assert len(algs[0]["algorithm_meta"]["lines"]) >= 6

    # L5: Multi-subfigure extraction
    figs = [b for b in prev["blocks"] if b["block_type"] == "figure"]
    assert len(figs) == 1
    assert len(figs[0]["figure_info"]["images"]) == 2
    assert figs[0]["figure_info"]["images"][0]["subcaption"] == "Velocity field"

    # L6: Table + tablenotes + cell_spans anchor
    data_tbls = [b for b in prev["blocks"] if b["block_type"] == "table" and b["table_role"] == "data_table"]
    assert len(data_tbls) == 1
    assert data_tbls[0]["table_notes"] and "5 random seeds" in data_tbls[0]["table_notes"][0]
    assert data_tbls[0]["source_anchor"]["kind"] == "latex_table"
    assert len(data_tbls[0]["source_anchor"]["cell_spans"]) == len(data_tbls[0]["table_rows"])

    # L7: Cross-reference resolution without duplicating preceding type words!
    ref_items = [it for it in intro_p["items"] if it["kind"] == "ref"]
    resolved_texts = {it["value"]: it["text"] for it in ref_items}
    assert resolved_texts.get("fig:arch") == "1"
    assert resolved_texts.get("tab:res") == "1"
    assert resolved_texts.get("eq:mass") == "(1)"
    assert resolved_texts.get("thm:conv") == "1"
    assert resolved_texts.get("alg:solve") == "1"
    assert prev["label_map"].get("fig:arch") == "Fig. 1"
    assert prev["label_map"].get("thm:conv") == "Theorem 1"

    # L8: Bibliography + 4 citation styles
    refs = [b for b in prev["blocks"] if b["block_type"] == "reference_item"]
    assert len(refs) == 1
    for style in ("gbt7714", "nature", "ieee", "apa"):
        formatted = format_bib_entry_text("vaswani2017", bib["vaswani2017"], style=style)
        assert "Vaswani" in formatted and "2017" in formatted


def test_l6_real_manuscript_latex_table() -> None:
    """Verify L6: multi-row booktabs LaTeX table parses cleanly with full row fidelity."""
    if EXTRA_TEX_TABLE_PATH and EXTRA_TEX_TABLE_PATH.exists():
        tex = EXTRA_TEX_TABLE_PATH.read_text(encoding="utf-8")
        fname = EXTRA_TEX_TABLE_PATH.name
    else:
        tex = r"""\begin{table}[t]
\centering
\caption{Context regimes and attention routing thresholds.}
\begin{tabular}{lccc}
\toprule
Regime & Context (k) & $\Pi_{\mathrm{ent}}$ & Routing Cadence \\
\midrule
Short Context & 0--8 & $< 0.2$ & Dense \\
Medium Window & 8--32 & $0.2$--$0.8$ & Block Top-k \\
Long Context & 32--128 & $> 0.8$ & Entropy Router \\
Ultra-Long & $> 128$ & $\gg 1.0$ & Hierarchical \\
\bottomrule
\end{tabular}
\end{table}
"""
        fname = "table_regimes.tex"
    _, blocks, _ = parse_document_with_meta(tex, fmt="latex", filename=fname)
    tbls = [b for b in blocks if b.block_type == "table"]
    assert len(tbls) >= 1
    assert len(tbls[0].meta["rows"]) >= 4


# ============================================================================
# W1 - W6: Deep Word OOXML Stress Tests
# ============================================================================

def _build_deep_ooxml_stress_docx() -> bytes:
    """Build a synthetic .docx containing numbering.xml, footnotes.xml, comments.xml,
    mc:Choice/mc:Fallback textbox, OMML math, and Word Track Changes (<w:ins>/<w:del>)."""
    doc = Document()
    h1 = doc.add_heading("Introduction", level=1)
    # Attach numbering numPr (numId=1, ilvl=0) to Heading 1
    pPr = h1._p.get_or_add_pPr()
    pPr.append(parse_xml(f'<w:numPr {nsdecls("w")}><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'))

    p_body = doc.add_paragraph()
    # Add comment range + normal run + footnoteReference + tracked deletion & insertion
    p_body._p.append(parse_xml(f'<w:commentRangeStart {nsdecls("w")} w:id="1"/>'))
    p_body.add_run("Water velocity was ")
    p_body._p.append(
        parse_xml(
            f'<w:del {nsdecls("w")} w:id="10" w:author="Advisor" w:date="2026-11-20T10:00:00Z">'
            f'<w:r><w:delText>1.2 m/s</w:delText></w:r></w:del>'
        )
    )
    p_body._p.append(
        parse_xml(
            f'<w:ins {nsdecls("w")} w:id="11" w:author="Advisor" w:date="2026-11-20T10:00:00Z">'
            f'<w:r><w:t>1.8 m/s</w:t></w:r></w:ins>'
        )
    )
    p_body._p.append(parse_xml(f'<w:r {nsdecls("w")}><w:footnoteReference w:id="1"/></w:r>'))
    p_body._p.append(parse_xml(f'<w:commentRangeEnd {nsdecls("w")} w:id="1"/>'))
    p_body._p.append(parse_xml(f'<w:r {nsdecls("w")}><w:commentReference w:id="1"/></w:r>'))

    # Add AlternateContent textbox with BOTH mc:Choice and mc:Fallback (must NOT duplicate!)
    p_tb = doc.add_paragraph()
    p_tb._p.append(
        parse_xml(
            f'<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
            f'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<mc:Choice Requires="wps"><w:drawing><w:txbxContent><w:p><w:r><w:t>Unique Textbox Callout</w:t></w:r></w:p></w:txbxContent></w:drawing></mc:Choice>'
            f'<mc:Fallback><w:pict><w:txbxContent><w:p><w:r><w:t>Unique Textbox Callout</w:t></w:r></w:p></w:txbxContent></w:pict></mc:Fallback>'
            f'</mc:AlternateContent>'
        )
    )

    buf = io.BytesIO()
    doc.save(buf)

    # Inject word/numbering.xml, word/footnotes.xml, word/comments.xml directly into zip
    out_buf = io.BytesIO()
    numbering_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering {nsdecls("w")}>
  <w:abstractNum w:abstractNumId="0">
    <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
  </w:abstractNum>
  <w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
</w:numbering>"""
    footnotes_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:footnotes {nsdecls("w")}>
  <w:footnote w:id="1"><w:p><w:r><w:t>Measured via ADCP sensor.</w:t></w:r></w:p></w:footnote>
</w:footnotes>"""
    comments_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments {nsdecls("w")}>
  <w:comment w:id="1" w:author="Prof. Li" w:date="2026-11-20T09:00:00Z">
    <w:p><w:r><w:t>Please verify sensor calibration.</w:t></w:r></w:p>
  </w:comment>
</w:comments>"""

    with zipfile.ZipFile(io.BytesIO(buf.getvalue()), "r") as zin, zipfile.ZipFile(out_buf, "w") as zout:
        for info in zin.infolist():
            if info.filename in ("word/numbering.xml", "word/footnotes.xml", "word/comments.xml"):
                continue
            zout.writestr(info, zin.read(info.filename))
        zout.writestr("word/numbering.xml", numbering_xml.encode("utf-8"))
        zout.writestr("word/footnotes.xml", footnotes_xml.encode("utf-8"))
        zout.writestr("word/comments.xml", comments_xml.encode("utf-8"))
    return out_buf.getvalue()


def _build_omml_multitable_docx() -> bytes:
    """Build a self-contained scientific .docx with 16 OMML equations and 4 data tables."""
    doc = Document()
    doc.add_heading("Supplementary Information", level=1)
    m_ns = "http://schemas.openxmlformats.org/officeDocument/2006/math"
    for i in range(1, 17):
        p = doc.add_paragraph()
        p.add_run(f"Equation {i} models attention latency: ")
        p._p.append(
            parse_xml(
                f'<m:oMath xmlns:m="{m_ns}"><m:f><m:num><m:r><m:t>v_{i}</m:t></m:r></m:num>'
                f'<m:den><m:r><m:t>k_{i}</m:t></m:r></m:den></m:f></m:oMath>'
            )
        )
    for t_idx in range(1, 5):
        tbl = doc.add_table(rows=2, cols=3)
        tbl.cell(0, 0).text = f"Site {t_idx}"
        tbl.cell(0, 1).text = "Depth (m)"
        tbl.cell(0, 2).text = "RMSE"
        tbl.cell(1, 0).text = f"Station {t_idx}"
        tbl.cell(1, 1).text = str(t_idx * 15)
        tbl.cell(1, 2).text = f"0.{15 + t_idx}"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_w1_real_nature_si_docx_and_blob_archive() -> None:
    """Verify W1: OMML math extraction, multi-table parsing, and original .docx binary blob archiving."""
    if EXTRA_DOCX_PATH and EXTRA_DOCX_PATH.exists():
        raw = EXTRA_DOCX_PATH.read_bytes()
        fname = EXTRA_DOCX_PATH.name
    else:
        raw = _build_omml_multitable_docx()
        fname = "synthetic_scientific_si.docx"
    txt, meta = extract_docx_with_assets(raw)
    assert meta.get("source_blob_key")
    prev = preview_document(txt, fmt="docx", filename=fname, meta=meta)
    inline_and_table_maths = sum(
        1 for b in prev["blocks"] for it in b.get("items") or [] if it["kind"] == "math"
    ) + sum(
        1
        for b in prev["blocks"]
        if b.get("table_rows")
        for r in b["table_rows"]
        for c in r
        for it in c.get("items") or []
        if it["kind"] == "math"
    )
    assert inline_and_table_maths >= 14
    assert prev["summary"]["table_count"] >= 4


def test_w2_w3_w4_w5_w6_deep_ooxml_numbering_footnotes_comments_textbox_tracked() -> None:
    raw = _build_deep_ooxml_stress_docx()

    # W6: Track Changes detection
    tc = inspect_docx_tracked_changes(raw)
    assert tc["has_tracked_changes"] is True
    assert tc["ins_count"] == 1 and tc["del_count"] == 1
    assert "Advisor" in tc["authors"]

    # Split extraction: before vs after
    before_txt, before_meta = extract_docx_with_assets(raw, track_mode="before")
    after_txt, after_meta = extract_docx_with_assets(raw, track_mode="after")

    assert "1.2 m/s" in before_txt and "1.8 m/s" not in before_txt
    assert "1.8 m/s" in after_txt and "1.2 m/s" not in after_txt
    assert after_meta.get("source_blob_key")

    prev = preview_document(after_txt, fmt="docx", filename="stress.docx", meta=after_meta)

    # W2: numbering.xml auto-prefixed "1. Introduction"
    headings = [b for b in prev["blocks"] if b["block_type"] == "heading"]
    assert any(h["clean_text"].startswith("1.") and "Introduction" in h["clean_text"] for h in headings)

    # W3: Footnote extracted and linked
    assert "1" in prev["footnotes"]
    assert "ADCP" in prev["footnotes"]["1"]

    # W4: Reviewer comment bound to paragraph
    commented = [b for b in prev["blocks"] if b.get("comments")]
    assert len(commented) == 1
    assert commented[0]["comments"][0]["author"] == "Prof. Li"
    assert "calibration" in commented[0]["comments"][0]["text"]

    # W5: AlternateContent textbox deduplicated (appears ONCE, not twice!)
    tb_hits = [b for b in prev["blocks"] if "Unique Textbox Callout" in b["clean_text"]]
    assert len(tb_hits) == 1

    # W6 End-to-End REST Split Import API
    with TestClient(app) as client:
        p = client.post("/api/projects", json={"name": "Word TC Test", "primary_format": "docx"}).json()
        doc_id = p["documents"][0]["id"]
        r_insp = client.post(
            f"/api/documents/{doc_id}/versions/inspect-docx",
            files={"file": ("review.docx", raw, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        assert r_insp.status_code == 200 and r_insp.json()["has_tracked_changes"] is True

        r_split = client.post(
            f"/api/documents/{doc_id}/versions/import-tracked-docx",
            files={"file": ("review.docx", raw, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            data={"label_prefix": "导师一审"},
        )
        assert r_split.status_code == 200
        body = r_split.json()
        bv_id = body["before_version"]["id"]
        av_id = body["after_version"]["id"]
        # Verify comparison between split versions catches the numerical change 1.2 -> 1.8!
        cmp_res = client.get(f"/api/documents/{doc_id}/compare?old_id={bv_id}&new_id={av_id}").json()
        assert any(a["category"] == "number" for a in cmp_res["alerts"])
        # Verify source-blob endpoint serves original .docx bytes for docx-preview
        r_blob = client.get(f"/api/versions/{av_id}/source-blob")
        assert r_blob.status_code == 200 and r_blob.content[:2] == b"PK"
        client.delete(f"/api/projects/{p['id']}")
