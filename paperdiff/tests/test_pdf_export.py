"""v1.1.0 Offline Printable HTML & Publication-Grade PDF Export Tests (Gate E4)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.analyzer import compare_documents, preview_document
from backend.export import (
    find_local_chrome,
    render_diff_print_html,
    render_html_to_pdf_bytes,
    render_single_print_html,
)
from backend.main import app


def test_e4_offline_printable_html_and_pdf_generation() -> None:
    old_md = """# Sparse Attention Latency Benchmark

## Methods

It is worth noting that we delve into the comprehensive decode latency $t_d = 12.4$ ms/tok [1].

| Model | Latency (ms/tok) |
| :--- | ---: |
| Model A | 14.2 |
| Model B | 18.6 |
"""
    new_md = """# Sparse Attention Latency Benchmark

## Methods

We measured a decode latency of $t_d = 15.8$ ms/tok on 128K context benchmarks.

| Model | Latency (ms/tok) |
| :--- | ---: |
| Model A | 14.2 |
| Model B | **22.4** |
"""
    comp = compare_documents(old_md, new_md, "markdown", "markdown")
    diff_html = render_diff_print_html(
        comp,
        "Sparse Attention Study",
        "v1 · AI初稿",
        "v2 · 人工修复",
        compact=False,
        commentary_note="请审阅人重点核对 Model B 延迟由 18.6 升至 22.4。",
    )
    compact_html = render_diff_print_html(
        comp, "Sparse Attention Study", "v1", "v2", compact=True
    )

    prev = preview_document(new_md, fmt="markdown", filename="study.md")
    single_html = render_single_print_html(prev, "Sparse Attention Study", "v2 · 终稿")

    for h in (diff_html, compact_html, single_html):
        # 100% offline: ZERO external CDN references!
        assert "cdn.jsdelivr.net" not in h
        assert "unpkg.com" not in h
        assert "cdnjs.cloudflare.com" not in h
        # Offline KaTeX CSS/JS embedded
        assert ".katex" in h

    # Automated Chinese commentary & user note present
    assert "请审阅人重点核对 Model B" in diff_html
    assert "【数值核查】" in diff_html or "【去 AI 味优化】" in diff_html
    assert len(compact_html) <= len(diff_html)

    # Real PDF rendering via local headless Chrome (if installed on test host)
    if find_local_chrome():
        pdf_diff = render_html_to_pdf_bytes(diff_html)
        assert pdf_diff.startswith(b"%PDF-") and len(pdf_diff) > 15_000

        with TestClient(app) as client:
            r_pdf = client.post(
                "/api/export",
                json={
                    "old_content": old_md,
                    "new_content": new_md,
                    "project_name": "PDF API Test",
                    "export_type": "pdf_diff_report",
                    "commentary_note": "API 导出测试批注",
                },
            )
            assert r_pdf.status_code == 200
            assert r_pdf.headers["content-type"] == "application/pdf"
            assert r_pdf.content.startswith(b"%PDF-")

            r_single = client.post(
                "/api/export",
                json={
                    "single_content": new_md,
                    "project_name": "PDF Single Test",
                    "export_type": "pdf_single",
                },
            )
            assert r_single.status_code == 200
            assert r_single.content.startswith(b"%PDF-")
