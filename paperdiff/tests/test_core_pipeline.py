from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.analyzer import compare_documents
from backend.diff_engine import diff_paragraph
from backend.exporter import (
    export_docx_merged_bytes,
    export_docx_tracked_bytes,
    export_merged_document,
)
from backend.main import app
from backend.parsers import extract_docx_with_assets, extract_latex_zip_with_assets

TEST_CASES = Path(__file__).resolve().parents[2] / "test_cases"


def test_case1_en_latex_traps_tables_and_lossless_patch() -> None:
    v1 = (TEST_CASES / "01_en_latex_nature_revision/v1_ai_draft.tex").read_text(encoding="utf-8")
    v2 = (TEST_CASES / "01_en_latex_nature_revision/v2_ai_polished_with_traps.tex").read_text(encoding="utf-8")
    res = compare_documents(v1, v2, "latex", "latex", protected_terms=["AdaptRoute", "PPL", "KV-Cache"])

    titles = {a["title"] for a in res["alerts"]}
    assert "引文丢失" in titles
    assert "图表/公式引用丢失" in titles
    assert "数值/统计量变动" in titles
    assert "表格数值变动" in titles
    assert "核心术语被替换" in titles
    assert "断言强度抬升" in titles

    tables = [p for p in res["paragraphs"] if p["block_type"] == "table"]
    assert len(tables) == 1
    assert tables[0]["table_diff"]["changed_cells"] >= 2

    moved = [p for p in res["paragraphs"] if p["status"] in ("moved_from", "moved_to")]
    assert len(moved) == 2
    assert all(p["moved_peer_index"] is not None for p in moved)
    assert all(len(p["alerts"]) == 0 for p in moved)

    intro_p = [p for p in res["paragraphs"] if "conclusively proves" in p["new_clean"]][0]
    hunks = [s["hunk_id"] for s in intro_p["segments"] if s["type"] != "equal"]
    merged = export_merged_document(res, {h: "keep_old" for h in hunks}, {}, new_full_content=v2)
    assert "\\documentclass[11pt]{article}" in merged
    assert "\\usepackage{amsmath,graphicx}" in merged
    assert "\\begin{tabular}{lccc}" in merged
    assert "may suggest" in merged
    assert "conclusively proves" not in merged


def test_case2_overleaf_zip_expansion_figures_tables_and_bib() -> None:
    _, z1, m1 = extract_latex_zip_with_assets((TEST_CASES / "02_en_latex_overleaf_zip/overleaf_project_v1.zip").read_bytes())
    _, z2, m2 = extract_latex_zip_with_assets((TEST_CASES / "02_en_latex_overleaf_zip/overleaf_project_v2.zip").read_bytes())
    res = compare_documents(z1, z2, "latex", "latex", old_meta=m1, new_meta=m2)
    assert res["summary"]["old_words"] > 100
    assert "dao2022neurips" in res["bib_entries"]
    assert res["bib_entries"]["dao2022neurips"]["venue"] == "NeurIPS"

    # Embedded figure PNG extracted & detected as 'updated' via SHA-256 hash
    figs = [p for p in res["paragraphs"] if p["block_type"] == "figure"]
    assert len(figs) == 1
    assert figs[0]["figure_info"]["image_status"] == "updated"
    assert figs[0]["figure_info"]["old_asset"] and figs[0]["figure_info"]["new_asset"]

    # Rich LaTeX table with \multicolumn{2}, bold shift (\textbf{89.3\%} -> 89.3\%), numeric delta (12.0 -> 10.0)
    tables = [p for p in res["paragraphs"] if p["block_type"] == "table"]
    assert len(tables) == 1
    td = tables[0]["table_diff"]
    assert td["rows"][0]["cells"][1]["colspan"] == 2
    assert td["bold_changed_cells"] == 1
    assert any(a["title"] == "表格最优值加粗变动" for a in res["alerts"])
    # Check numeric delta on 12.0 mm -> 10.0 mm cell
    delta_cells = [c for r in td["rows"] for c in r["cells"] if c.get("numeric_delta")]
    assert len(delta_cells) == 1 and delta_cells[0]["numeric_delta"]["delta"] == -2.0


def test_case3_zh_latex_ai_isms_and_numbers() -> None:
    v1 = (TEST_CASES / "03_zh_latex_thesis/v1_初稿.tex").read_text(encoding="utf-8")
    v2 = (TEST_CASES / "03_zh_latex_thesis/v2_精简修订.tex").read_text(encoding="utf-8")
    res = compare_documents(v1, v2, "latex", "latex")
    assert res["evaluation"]["ai_ism_diff"]["old_count"] >= 9
    assert res["evaluation"]["ai_ism_diff"]["new_count"] == 0
    assert any("4.8%" in a["detail"] and "4.6%" in a["detail"] for a in res["alerts"])


def test_case4_en_word_images_merged_tables_citations_and_ooxml_export() -> None:
    d1, m1 = extract_docx_with_assets((TEST_CASES / "04_en_word_manuscript/v1_draft.docx").read_bytes())
    d2, m2 = extract_docx_with_assets((TEST_CASES / "04_en_word_manuscript/v2_revised.docx").read_bytes())
    res = compare_documents(d1, d2, "docx", "docx", old_meta=m1, new_meta=m2)

    assert not any("新增引文" in a["title"] for a in res["alerts"])
    assert any(a["category"] == "citation" and "[14]" in a["detail"] for a in res["alerts"])

    # Embedded Word PNG image extracted & merged with Figure 1 caption!
    figs = [p for p in res["paragraphs"] if p["block_type"] == "figure"]
    assert len(figs) == 1
    assert figs[0]["figure_info"]["image_status"] == "updated"
    assert "benchmark B3" in figs[0]["new_clean"]

    # Word table with merged gridSpan header + bold cell + numeric delta 63.8 -> 64.1
    tables = [p for p in res["paragraphs"] if p["block_type"] == "table"]
    assert len(tables) == 1
    td = tables[0]["table_diff"]
    assert td["changed_cells"] == 1
    assert td["rows"][0]["cells"][1]["colspan"] == 2
    assert any(a["title"] == "表格数值变动" and "63.8" in a["detail"] for a in res["alerts"])

    tracked = export_docx_tracked_bytes(res)
    with zipfile.ZipFile(io.BytesIO(tracked)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "<w:ins " in xml and "<w:del " in xml and "<w:tbl>" in xml

    clean = export_docx_merged_bytes(res, {}, {})
    assert len(clean) > 1000


def test_case6_edge_cases_wrap_immunity_and_math_diff() -> None:
    v1 = (TEST_CASES / "06_edge_cases_stress_tex/edge_v1.tex").read_text(encoding="utf-8")
    v2 = (TEST_CASES / "06_edge_cases_stress_tex/edge_v2.tex").read_text(encoding="utf-8")
    res = compare_documents(v1, v2, "latex", "latex")
    wrap_p = [p for p in res["paragraphs"] if "narrow column" in p["old_clean"]][0]
    assert wrap_p["status"] == "unchanged" and wrap_p["similarity"] == 100.0
    math_p = [p for p in res["paragraphs"] if p["block_type"] == "math"]
    assert len(math_p) == 1 and math_p[0]["status"] == "modified"
    assert len(math_p[0]["math_diff"]) > 0


def test_diff_orphan_stopword_smoothing_preserves_atoms() -> None:
    d = diff_paragraph(
        "latent architecture of fundamental failure in Fig. ⟦REF:fig:m⟧.",
        "standard model of clear drawback in Fig. ⟦REF:fig:m⟧.",
        0,
    )
    ref_in_equal = any(
        seg["type"] == "equal" and any(it["kind"] == "ref" for it in seg.get("items", []))
        for seg in d["segments"]
    )
    assert ref_in_equal
    non_eq = [s for s in d["segments"] if s["type"] != "equal"]
    assert len(non_eq) == 1


def test_api_v14_assets_bib_ack_alerts_and_custom_lexicon() -> None:
    with TestClient(app) as client:
        assert client.get("/api/health").json()["version"] == "0.2.0"

        # Verify asset endpoint serves real extracted PNG from Overleaf zip!
        _, _, m1 = extract_latex_zip_with_assets((TEST_CASES / "02_en_latex_overleaf_zip/overleaf_project_v1.zip").read_bytes())
        any_key = next(iter(m1["assets"].values()))
        asset_resp = client.get(f"/api/assets/{any_key}")
        assert asset_resp.status_code == 200 and asset_resp.content[:4] == b"\x89PNG"
        # Reject path traversal and invalid keys safely
        assert client.get("/api/assets/..%2Fpaperdiff.db").status_code == 404
        assert client.get("/api/assets/not_a_valid_key.png").status_code == 404

        # Verify undefined .bib citation alert!
        q_bib = client.post(
            "/api/compare/quick",
            json={
                "old_content": "Prior work~\\cite{dao2022neurips}.",
                "new_content": "Prior work~\\cite{dao2022neurips,fake_hallucination2026}.",
                "old_meta": {"bib": {"dao2022neurips": {"title": "FlashAttention", "year": "2022"}}},
                "new_meta": {"bib": {"dao2022neurips": {"title": "FlashAttention", "year": "2022"}}},
            },
        ).json()
        assert any(a["title"] == "未在 .bib 中定义的引文" and "fake_hallucination2026" in a["detail"] for a in q_bib["alerts"])

        orig = client.get("/api/settings/ai-lexicon").json()
        try:
            client.put(
                "/api/settings/ai-lexicon",
                json={"added_en": ["obviously"], "added_zh": ["众所周知"], "muted": ["paradigm"]},
            )
            q = client.post(
                "/api/compare/quick",
                json={
                    "old_content": "This paradigm is obviously flawed and 众所周知.",
                    "new_content": "This design has clear drawbacks.",
                },
            ).json()
            removed_words = {x["word"] for x in q["evaluation"]["ai_ism_diff"]["removed"]}
            assert "obviously" in removed_words
            assert "众所周知" in removed_words
            assert "paradigm" not in removed_words
        finally:
            client.put(
                "/api/settings/ai-lexicon",
                json={
                    "added_en": orig.get("added_en", []),
                    "added_zh": orig.get("added_zh", []),
                    "muted": orig.get("muted", []),
                },
            )

        p = client.post("/api/projects", json={"name": "__v13_ack_test__", "category": "paper"}).json()
        doc_id = p["documents"][0]["id"]
        try:
            v1 = client.post(f"/api/documents/{doc_id}/versions", json={"label": "v1", "content": "Accuracy is 91.2%."}).json()
            v2 = client.post(f"/api/documents/{doc_id}/versions", json={"label": "v2", "content": "Accuracy is 92.4%."}).json()
            c1 = client.get(f"/api/documents/{doc_id}/compare?old_id={v1['id']}&new_id={v2['id']}").json()
            assert c1["summary"]["alert_counts"]["total"] == 1
            aid = c1["alerts"][0]["alert_id"]
            client.put(
                f"/api/documents/{doc_id}/ack-alerts",
                json={"old_version_id": v1["id"], "new_version_id": v2["id"], "acked_ids": [aid]},
            )
            c2 = client.get(f"/api/documents/{doc_id}/compare?old_id={v1['id']}&new_id={v2['id']}").json()
            assert c2["summary"]["alert_counts"]["total"] == 0
            assert c2["summary"]["alert_counts"]["acked"] == 1
            assert c2["evaluation"]["scores"]["fact_safety"] > c1["evaluation"]["scores"]["fact_safety"]

            resp = client.post(
                "/api/export",
                json={"old_version_id": v1["id"], "new_version_id": v2["id"], "export_type": "docx_tracked"},
            )
            assert resp.status_code == 200 and len(resp.content) > 1000
        finally:
            client.delete(f"/api/projects/{p['id']}")


def test_v145_single_doc_preview_self_audit_lossless_edit_and_html_export() -> None:
    with TestClient(app) as client:
        _, z1, m1 = extract_latex_zip_with_assets(
            (TEST_CASES / "02_en_latex_overleaf_zip/overleaf_project_v1.zip").read_bytes()
        )
        # Inject one broken \ref and one undefined .bib cite before \end{document}
        z1_audit = z1.replace(
            "\\end{document}",
            "\n\nThis pivotal paradigm delves into Fig.~\\ref{fig:missing_label} and cites \\cite{hallucinated_2026}.\n\\end{document}",
        )
        # 1) Quick single-doc preview & self-audit
        qp = client.post(
            "/api/preview/quick",
            json={
                "content": z1_audit,
                "meta": m1,
                "label": "overleaf_v1.zip",
                "protected_terms": ["Transformer", "UnseenTerm"],
            },
        )
        assert qp.status_code == 200
        qd = qp.json()
        assert qd["summary"]["figure_count"] == 1
        assert qd["summary"]["table_count"] == 1
        assert qd["summary"]["ai_ism_count"] >= 3
        assert any(i["title"] == "断链交叉引用" and "fig:missing_label" in i["items"] for i in qd["issues"])
        assert any(i["title"] == "未在 .bib 中定义的引文" and "hallucinated_2026" in i["items"] for i in qd["issues"])
        tc = {x["term"]: x["count"] for x in qd["term_coverage"]}
        assert tc["Transformer"] >= 1 and tc["UnseenTerm"] == 0

        # 2) Project single-version preview -> in-place edit -> lossless save as v2 -> auto diff check!
        p = client.post(
            "/api/projects",
            json={"name": "__v145_single_read_test__", "category": "paper", "protected_terms": ["Transformer"]},
        ).json()
        doc_id = p["documents"][0]["id"]
        try:
            v1_resp = client.post(
                f"/api/documents/{doc_id}/versions/upload",
                files={"file": ("overleaf_v1.zip", (TEST_CASES / "02_en_latex_overleaf_zip/overleaf_project_v1.zip").read_bytes(), "application/zip")},
                data={"label": "v1 · 初稿", "source_tag": "AI初稿", "notes": "", "is_milestone": "false"},
            )
            assert v1_resp.status_code == 200
            v1 = v1_resp.json()

            prev = client.get(f"/api/versions/{v1['id']}/preview").json()
            assert prev["summary"]["figure_count"] == 1
            assert prev["summary"]["table_count"] == 1
            assert "dao2022neurips" in prev["bib_entries"]

            # Pick first editable paragraph block and polish it in Read Mode
            target_blk = next(b for b in prev["blocks"] if b["block_type"] == "paragraph" and b["ai_isms"])
            edited_raw = target_blk["raw_text"].replace("paradigm", "framework").replace("notably", "specifically")
            v2_resp = client.post(
                f"/api/documents/{doc_id}/save-single-version",
                json={
                    "base_version_id": v1["id"],
                    "paragraph_edits": {str(target_blk["index"]): edited_raw},
                    "label": "v2 · 阅读微调",
                    "source_tag": "人工修复",
                    "notes": "去除 AI 腔",
                    "is_milestone": False,
                },
            )
            assert v2_resp.status_code == 200
            v2 = v2_resp.json()
            v2_full = client.get(f"/api/versions/{v2['id']}").json()
            # Verify LaTeX preamble & figures were preserved 100% losslessly!
            assert "\\documentclass" in v2_full["content"]
            assert "\\includegraphics" in v2_full["content"]
            assert v2_full["meta"].get("assets") == prev["version"]["meta"].get("assets")

            # Verify standalone offline HTML reading export embeds PNG as base64 data URI!
            html_resp = client.post(
                "/api/export",
                json={"version_id": v2["id"], "export_type": "single_html"},
            )
            assert html_resp.status_code == 200
            assert "data:image/png;base64," in html_resp.text
            assert "acad-table" in html_resp.text
        finally:
            client.delete(f"/api/projects/{p['id']}")


def test_v16_markdown_rich_rendering_and_zero_unicode_loss() -> None:
    from backend.analyzer import preview_document

    md = """# Idea 1 手册

> **核对版本**：`AdaptRoute v2.3.0`（包名 `sparse_attn`）
> **阅读顺序**：背景 $\\to$ 模型

---

## 第四部分：模型公式（`hydrochemistry.py`）

其中离子活度系数 $\\gamma_i$ 采用 `WATEQ` 扩展 Debye–Hückel 公式，粒径 $200\\ \\mu\\mathrm{m}$ 与 10 μm：

$$\\log_{10}\\gamma_i = -\\frac{A(T)\\,z_i^2\\sqrt{I}}{1 + B(T)\\,a_i\\sqrt{I}} + b_i I$$

* **大白话拆解**：
  * $[\\mathrm{Ca^{2+}}]_{\\mathrm{free}}$ 是自由钙离子；
  * $K_{\\mathrm{sp,cal}}(T)$ 是溶度积。
* **淡水密度**：
  $$\\rho_w(T, S_{\\mathrm{TDS}}) = \\rho_0(T) + 0.8181 S_{\\mathrm{TDS}}$$
  其中纯水项采用 Kell (1975)。

| 类别 | 公式 | 链接 |
| :--- | :---: | ---: |
| **状态 III** | $z_T\\text{–}z_\\Omega$ | • A<br>• https://doi.org/10.1016/test |

```python
def calc_omega(ca, co3):
    return ca * co3
```
"""
    prev = preview_document(md, "markdown", "sample_academic_manual.md")
    blocks = prev["blocks"]
    btypes = [b["block_type"] for b in blocks]

    assert "title" in btypes
    assert "blockquote" in btypes
    assert "hr" in btypes
    assert "code" in btypes
    assert prev["summary"]["math_count"] == 2
    assert prev["summary"]["table_count"] == 1

    # Display math items must carry raw inner LaTeX WITHOUT ⟦MATH:...⟧ wrapper
    maths = [b for b in blocks if b["block_type"] == "math"]
    assert len(maths) == 2
    assert all(not m["items"][0]["value"].startswith("⟦MATH:") for m in maths)
    assert any("\\log_{10}\\gamma_i" in m["items"][0]["value"] for m in maths)
    assert any("\\rho_w(T, S_{\\mathrm{TDS}})" in m["items"][0]["value"] for m in maths)

    # Zero dropped Unicode (ü, μ) and zero dropped underscores (_) in code pills
    huckel_blk = next(b for b in blocks if "Debye" in b["clean_text"])
    rendered_txt = "".join(it["text"] for it in huckel_blk["items"] if it["kind"] in ("text", "code"))
    assert "Debye–Hückel" in rendered_txt
    assert "10 μm" in rendered_txt
    assert any(it["kind"] == "code" and it["value"] == "WATEQ" for it in huckel_blk["items"])

    bq = next(b for b in blocks if b["block_type"] == "blockquote")
    assert any(it["kind"] == "code" and it["value"] == "sparse_attn" for it in bq["items"])
    assert any(it["kind"] == "br" for it in bq["items"])

    # Nested list depth preserved
    lists = [b for b in blocks if b["block_type"] == "list"]
    assert any(l["list_meta"]["depth"] == 1 for l in lists)

    # Table alignments and <br> line break preserved
    tbl = next(b for b in blocks if b["block_type"] == "table")
    assert tbl["table_alignments"] == ["left", "center", "right"]
    assert any(it["kind"] == "br" for it in tbl["table_rows"][1][2]["items"])


def test_v16_latex_thesis_sanitizer_frontmatter_and_references() -> None:
    from backend.analyzer import preview_document

    tex = r"""
\documentclass{book}
\begin{document}
\begin{spacing}{1.0}
\ThisCenterWallPaper{.60}{images/univ-logo.jpg}
\thispagestyle{empty}\vspace*{2cm}
\begin{CJK*}{UTF8}{bkai}
\begin{tabular}{lcl}
\multicolumn{3}{c}{\begin{center}\chinesechaptersize{長上下文稀疏注意力優化研究}\end{center}} \\
姓\qquad 名 & : & 陳明 \\
\noalign{} 學\qquad 號 & : & 2026001001 \\
\noalign{} 指導老師 & : & Dr. Alex Lin \\
\end{tabular}
\end{CJK*}
\end{spacing}

\chapter{Introduction}
\section{Background}
Stable decoding in long contexts (e.g.\ real-time feeds), see \cite{vaswani2017}.

\TOCadd{References}
\fancypagestyle{plain}{\fancyhf{}\fancyhead[R]{{\footnotesize References}}\renewcommand{\headrulewidth}{0.7pt}}
\pagestyle{fancy}\lhead{}\rhead{{\footnotesize References}}
\bibliography{refs}

\pagestyle{fancy}\lhead{}\rhead{\footnotesize{Acknowledgements}}
\addcontentsline{toc}{chapter}{Acknowledgements}\setlength{\parskip}{0pt}{\bf \Large {Acknowledgements} \par}

\par I express my gratitude to my advisor.
\end{document}
"""
    prev = preview_document(
        tex,
        "latex",
        "thesis.tex",
        meta={"bib": {"vaswani2017": {"author": "Vaswani et al.", "year": "2017", "title": "Attention Is All You Need", "venue": "NeurIPS"}}},
    )
    all_clean = "\n".join(b["clean_text"] for b in prev["blocks"])
    for leaked in ("spacing", "ThisCenterWallPaper", "fancypagestyle", "TOCadd", "addcontentsline", "noalign", "qquad", "headrulewidth", "parskip"):
        assert leaked not in all_clean, f"Leaked LaTeX macro: {leaked}"

    # Cover table classified into frontmatter as metadata_form (NOT counted as scientific table)
    fm_tables = [b for b in prev["blocks"] if b["zone"] == "frontmatter" and b["block_type"] == "table"]
    assert len(fm_tables) == 1
    assert fm_tables[0]["table_role"] == "metadata_form"
    assert prev["summary"]["table_count"] == 0

    # \chapter + \section + References + Acknowledgements headings all recognized
    sec_titles = [s["title"] for s in prev["sections"]]
    assert "Introduction" in sec_titles and "Background" in sec_titles
    assert "References" in sec_titles and "Acknowledgements" in sec_titles

    # Reference item synthesized from .bib in backmatter
    refs = [b for b in prev["blocks"] if b["block_type"] == "reference_item"]
    assert len(refs) == 1 and "Attention Is All You Need" in refs[0]["clean_text"]
    assert "e.g. real-time feeds" in all_clean


def test_v16_docx_chinese_outline_cover_table_and_omml_math() -> None:
    from docx import Document as DocxDoc
    from docx.oxml import OxmlElement, parse_xml
    from docx.oxml.ns import qn
    from backend.analyzer import preview_document

    doc = DocxDoc()
    doc.add_paragraph("硕士研究生学位论文")
    tbl = doc.add_table(rows=4, cols=2)
    kv = [("题目：", "大语言模型稀疏注意力优化研究"), ("姓名：", "示例作者"), ("学号：", "2026001001"), ("导师姓名：", "审阅人A")]
    for r_i, (k, v) in enumerate(kv):
        tbl.cell(r_i, 0).text = k
        tbl.cell(r_i, 1).text = v

    # Heading styled via XML outlineLvl=0 (standard Chinese thesis template pattern)
    h1 = doc.add_paragraph("第1章 绪论")
    pPr = h1._p.get_or_add_pPr()
    ol = OxmlElement("w:outlineLvl")
    ol.set(qn("w:val"), "0")
    pPr.append(ol)

    # Paragraph with inline OMML equation (<m:oMath>) for fraction a/b
    p_math = doc.add_paragraph("饱和度满足公式 ")
    omath_xml = parse_xml(
        '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
        '<m:f><m:num><m:r><m:t>a</m:t></m:r></m:num><m:den><m:r><m:t>b</m:t></m:r></m:den></m:f>'
        "</m:oMath>"
    )
    p_math._p.append(omath_xml)

    buf = io.BytesIO()
    doc.save(buf)
    md_text, meta = extract_docx_with_assets(buf.getvalue())
    prev = preview_document(md_text, "docx", "thesis_zh.docx", meta=meta)

    # Cover lines & cover table folded cleanly into frontmatter
    fm_blocks = [b for b in prev["blocks"] if b["zone"] == "frontmatter"]
    assert any(b["block_type"] == "table" and b["table_role"] == "metadata_form" for b in fm_blocks)
    assert prev["summary"]["table_count"] == 0

    # Chinese outlineLvl heading recognized into sidebar TOC
    assert any(s["title"] == "第1章 绪论" for s in prev["sections"])

    # OMML equation parsed into KaTeX math chip!
    body_paras = [b for b in prev["blocks"] if b["zone"] == "body" and b["block_type"] == "paragraph"]
    assert any(any(it["kind"] == "math" and ("\\frac{a}{b}" in (it.get("value") or "") or "\\dfrac{a}{b}" in (it.get("value") or "")) for it in bp["items"]) for bp in body_paras)

