"""v1.1.0 Format-Preserving Round-Trip Patcher Tests (Gates E1, E2, E3)."""
from __future__ import annotations

import io
import zipfile

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt
from fastapi.testclient import TestClient

from backend.analyzer import preview_document
from backend.main import app
from backend.parsers import extract_docx_with_assets, extract_latex_zip_with_assets
from backend.patcher import apply_typed_patches


def test_e1_latex_surgical_cell_and_math_patch_zero_drift() -> None:
    tex = r"""\documentclass{article}
% Important author comment
\begin{document}
\section{Results}
Our method achieves 88.5\% accuracy.

\begin{equation}
E = m c^2
\end{equation}

\begin{table}[t]
\caption{Main benchmark.}
\begin{tabular}{lcc}
\toprule
Method & RMSE & $R^2$ \\
\cmidrule(lr){2-3}
Baseline & 0.42 & 0.81 \\
Ours & 0.21 & 0.94 \\
\bottomrule
\end{tabular}
\end{table}
\end{document}
"""
    prev = preview_document(tex, fmt="latex", filename="main.tex")
    p_blk = next(b for b in prev["blocks"] if b["block_type"] == "paragraph")
    m_blk = next(b for b in prev["blocks"] if b["block_type"] == "math")
    t_blk = next(b for b in prev["blocks"] if b["block_type"] == "table")

    ops = [
        {"op": "replace_block", "block_index": p_blk["index"], "new_raw": r"Our method achieves 91.2\% accuracy."},
        {"op": "replace_math", "block_index": m_blk["index"], "new_raw": r"E = \gamma m c^2"},
        {"op": "edit_table_cell", "block_index": t_blk["index"], "row": 2, "col": 1, "new_value": "0.17", "bold": True},
    ]
    res = apply_typed_patches(tex, "latex", prev["blocks"], ops)
    patched = res["patched_content"]

    assert res["applied_count"] == 3
    assert r"91.2\%" in patched
    assert r"E = \gamma m c^2" in patched
    assert r"\textbf{0.17}" in patched
    # Original comments, booktabs, cmidrule, and untouched cells remain 100% intact!
    assert "% Important author comment" in patched
    assert r"\cmidrule(lr){2-3}" in patched
    assert "Baseline & 0.42 & 0.81" in patched


def test_e2_overleaf_zip_multi_file_roundtrip_repacking() -> None:
    buf = io.BytesIO()
    main_tex = r"""\documentclass{article}
\begin{document}
\input{sections/intro}
\input{sections/results}
\end{document}
"""
    intro_tex = r"""\section{Intro}
Original intro statement with 10 samples.
"""
    results_tex = r"""\section{Results}
\begin{tabular}{ll}
\toprule
Metric & Value \\
\midrule
F1 & 0.85 \\
\bottomrule
\end{tabular}
"""
    fake_png = b"\x89PNG\r\n\x1a\nFAKEIMAGEBYTES123456"

    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("main.tex", main_tex)
        zf.writestr("sections/intro.tex", intro_tex)
        zf.writestr("sections/results.tex", results_tex)
        zf.writestr("figures/fig1.png", fake_png)

    orig_zip = buf.getvalue()
    _, expanded, meta = extract_latex_zip_with_assets(orig_zip)
    prev = preview_document(expanded, fmt="latex", filename="project.zip", meta=meta)

    intro_p = next(b for b in prev["blocks"] if "10 samples" in b["clean_text"])
    res_t = next(b for b in prev["blocks"] if b["block_type"] == "table")

    ops = [
        {"op": "replace_block", "block_index": intro_p["index"], "new_raw": "Revised intro statement with 25 samples."},
        {"op": "edit_table_cell", "block_index": res_t["index"], "row": 1, "col": 1, "new_value": "0.93", "bold": True},
    ]
    res = apply_typed_patches(
        expanded,
        "latex",
        prev["blocks"],
        ops,
        orig_blob_bytes=orig_zip,
        source_map=meta["source_map"],
    )
    assert res["patched_blob_bytes"] is not None
    with zipfile.ZipFile(io.BytesIO(res["patched_blob_bytes"]), "r") as zout:
        assert "25 samples" in zout.read("sections/intro.tex").decode("utf-8")
        assert r"\textbf{0.93}" in zout.read("sections/results.tex").decode("utf-8")
        # Untouched files preserved byte-for-byte!
        assert zout.read("main.tex").decode("utf-8") == main_tex
        assert zout.read("figures/fig1.png") == fake_png


def test_e3_docx_template_inplace_xml_patch_clean_and_tracked() -> None:
    doc = Document()
    # Header + styled cover + paragraph with custom font + data table
    doc.sections[0].header.paragraphs[0].text = "NSFC Grant Application Header 2026"
    p_cover = doc.add_paragraph("国家自然科学基金项目申请书")
    p_body = doc.add_paragraph()
    r_body = p_body.add_run("The observed settling rate was 12.4 m/day across all sites.")
    r_body.font.name = "Times New Roman"
    r_body.font.size = Pt(11)

    tbl = doc.add_table(rows=3, cols=2)
    tbl.cell(0, 0).text = "Model"
    tbl.cell(0, 1).text = "RMSE"
    tbl.cell(1, 0).text = "Baseline"
    tbl.cell(1, 1).text = "0.45"
    tbl.cell(2, 0).text = "Ours"
    tbl.cell(2, 1).text = "0.28"

    raw_buf = io.BytesIO()
    doc.save(raw_buf)
    orig_bytes = raw_buf.getvalue()

    extracted_md, meta = extract_docx_with_assets(orig_bytes)
    prev = preview_document(extracted_md, fmt="docx", filename="grant.docx", meta=meta)
    body_blk = next(b for b in prev["blocks"] if "12.4 m/day" in b["clean_text"])
    tbl_blk = next(b for b in prev["blocks"] if b["block_type"] == "table")

    ops = [
        {
            "op": "replace_block",
            "block_index": body_blk["index"],
            "new_raw": "The observed settling rate was 15.8 m/day across all sites.",
        },
        {
            "op": "edit_table_cell",
            "block_index": tbl_blk["index"],
            "row": 2,
            "col": 1,
            "new_value": "0.19",
            "bold": True,
        },
        {
            "op": "insert_table_row",
            "block_index": tbl_blk["index"],
            "after_row": 2,
            "cells": ["Ablation", "0.24"],
        },
    ]

    # 1. Clean revised mode
    res_clean = apply_typed_patches(
        extracted_md, "docx", prev["blocks"], ops, orig_blob_bytes=orig_bytes, docx_mode="clean"
    )
    assert res_clean["patched_blob_bytes"] is not None
    doc_out = Document(io.BytesIO(res_clean["patched_blob_bytes"]))
    assert doc_out.sections[0].header.paragraphs[0].text == "NSFC Grant Application Header 2026"
    assert any("国家自然科学基金" in p.text for p in doc_out.paragraphs)
    revised_p = next(p for p in doc_out.paragraphs if "15.8 m/day" in p.text)
    # Preserved Times New Roman font from original run!
    assert revised_p.runs[0].font.name == "Times New Roman"
    assert len(doc_out.tables[0].rows) == 4
    assert doc_out.tables[0].cell(2, 1).text == "0.19"
    assert doc_out.tables[0].cell(2, 1).paragraphs[0].runs[0].bold is True
    assert doc_out.tables[0].cell(3, 0).text == "Ablation"

    # 2. Native Track Changes mode inside original template!
    res_tc = apply_typed_patches(
        extracted_md, "docx", prev["blocks"], ops[:2], orig_blob_bytes=orig_bytes, docx_mode="tracked"
    )
    doc_tc = Document(io.BytesIO(res_tc["patched_blob_bytes"]))
    assert doc_tc.sections[0].header.paragraphs[0].text == "NSFC Grant Application Header 2026"
    xml_str = doc_tc.element.xml
    assert "<w:del " in xml_str and "<w:ins " in xml_str
    assert "12.4" in xml_str and "15.8" in xml_str

    # 3. Full API round-trip via /api/documents/{id}/apply-patches + /api/export (docx_patched)
    with TestClient(app) as client:
        p = client.post("/api/projects", json={"name": "Patch API Test", "primary_format": "docx"}).json()
        did = p["documents"][0]["id"]
        v1 = client.post(
            f"/api/documents/{did}/versions/upload",
            files={"file": ("grant.docx", orig_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            data={"label": "v1", "source_tag": "初稿"},
        ).json()
        r_apply = client.post(
            f"/api/documents/{did}/apply-patches",
            json={
                "base_version_id": v1["id"],
                "patches": ops[:2],
                "label": "v2 · 原位修订",
                "source_tag": "人工修复",
            },
        )
        assert r_apply.status_code == 200
        v2 = r_apply.json()["version"]
        assert v2["source_blob_key"]
        r_exp = client.post(
            "/api/export",
            json={"version_id": v2["id"], "export_type": "docx_patched"},
        )
        assert r_exp.status_code == 200 and r_exp.content[:2] == b"PK"
        doc_dl = Document(io.BytesIO(r_exp.content))
        assert doc_dl.tables[0].cell(2, 1).text == "0.19"
        client.delete(f"/api/projects/{p['id']}")
