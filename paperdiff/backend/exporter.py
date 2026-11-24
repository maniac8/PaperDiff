"""Classic Document Exporters (Source-Span LaTeX Merge, Structured DOCX, Offline HTML, latexdiff).

Complements `backend.patcher` (v1.1.0 format-preserving template patching) and `backend.export`
(v1.1.0 offline KaTeX publication PDF/print engine) by providing:
    - `export_merged_document` & `apply_single_document_edits`: Cherry-pick merge & LaTeX span edits.
    - `export_docx_tracked_bytes` & `export_docx_merged_bytes`: Structured OOXML Track Changes fallback
      when no archived `source_blob_key` template is available.
    - `export_html_report` & `export_single_html_report`: Self-contained offline HTML snapshots.
    - `export_latexdiff_tex` & `export_markdown_summary`: Academic revision markup & audit summaries.
"""
from __future__ import annotations

import base64
import html
import io
import mimetypes
from datetime import datetime, timezone
from typing import Any

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from .assets import get_asset_path


def _render_items_plain(items: list[dict[str, Any]], as_latex: bool = True) -> str:
    parts: list[str] = []
    for it in items:
        k = it["kind"]
        if k == "text":
            parts.append(it["text"])
        elif k == "ref":
            parts.append(f"\\ref{{{it['value']}}}" if as_latex else f"[{it['value']}]")
        elif k == "cite":
            parts.append(f"\\cite{{{it['value']}}}" if as_latex else f"[{it['value']}]")
        elif k == "math":
            parts.append(f"${it['value']}$")
    return "".join(parts)


def reconstruct_merged_paragraph(para: dict[str, Any], decisions: dict[str, str], as_latex: bool = True) -> str:
    """
    Reconstruct a single paragraph applying per-hunk cherry-pick decisions.
    Decision values: 'accept_new' (default) | 'keep_old'.
    """
    if para["status"] == "unchanged":
        return para["new_raw"] if (as_latex and para["new_raw"]) else para["new_clean"]

    # If no custom 'keep_old' overrides in this paragraph and user accepts all new, return clean new_raw if available
    hunk_ids = [seg["hunk_id"] for seg in para["segments"] if seg["type"] != "equal"]
    if not any(decisions.get(hid) == "keep_old" for hid in hunk_ids):
        if para["status"] == "deleted":
            return ""
        return para["new_raw"] if (as_latex and para["new_raw"]) else _rebuild_from_segments(para["segments"], decisions, as_latex)

    if all(decisions.get(hid) == "keep_old" for hid in hunk_ids):
        if para["status"] == "added":
            return ""
        return para["old_raw"] if (as_latex and para["old_raw"]) else _rebuild_from_segments(para["segments"], decisions, as_latex)

    return _rebuild_from_segments(para["segments"], decisions, as_latex)


def _rebuild_from_segments(segments: list[dict[str, Any]], decisions: dict[str, str], as_latex: bool) -> str:
    out: list[str] = []
    for seg in segments:
        t = seg["type"]
        if t == "equal":
            txt = seg.get("raw") or _render_items_plain(seg["items"], as_latex)
            if out and seg.get("lead_space_new") and not out[-1].endswith(" "):
                out.append(" ")
            out.append(txt)
        else:
            choice = decisions.get(seg["hunk_id"], "accept_new")
            if t == "replace":
                if choice == "keep_old":
                    txt = seg.get("old_raw") or _render_items_plain(seg["old_items"], as_latex)
                    if out and seg.get("lead_space_old") and not out[-1].endswith(" "):
                        out.append(" ")
                    out.append(txt)
                else:
                    txt = seg.get("new_raw") or _render_items_plain(seg["new_items"], as_latex)
                    if out and seg.get("lead_space_new") and not out[-1].endswith(" "):
                        out.append(" ")
                    out.append(txt)
            elif t == "delete":
                if choice == "keep_old":
                    txt = seg.get("old_raw") or _render_items_plain(seg["old_items"], as_latex)
                    if out and seg.get("lead_space_old") and not out[-1].endswith(" "):
                        out.append(" ")
                    out.append(txt)
            elif t == "insert":
                if choice != "keep_old":
                    txt = seg.get("new_raw") or _render_items_plain(seg["new_items"], as_latex)
                    if out and seg.get("lead_space_new") and not out[-1].endswith(" "):
                        out.append(" ")
                    out.append(txt)
    return "".join(out).strip()


def export_merged_document(
    comparison: dict[str, Any],
    decisions: dict[str, str],
    paragraph_edits: dict[int, str] | None = None,
    new_full_content: str | None = None,
) -> str:
    """
    v1.3 Lossless LaTeX Source-Span Patching:
    When new_full_content is a LaTeX source document, splice ONLY the user's
    reverted / inline-edited blocks back into their exact (raw_start, raw_end)
    character offsets so preamble, packages, comments, \\includegraphics, and
    unmodified environments remain 100% byte-for-byte intact!
    """
    is_latex = comparison["formats"]["new"] == "latex" or comparison["formats"]["old"] == "latex"
    edits_map = {int(k): v for k, v in (paragraph_edits or {}).items()}

    if new_full_content is not None and comparison["formats"]["new"] == "latex":
        patches: list[tuple[int, int, str]] = []
        last_valid_end = 0
        # Locate \\begin{document} fallback anchor for restored deleted paragraphs
        doc_start = new_full_content.find("\\begin{document}")
        if doc_start != -1:
            last_valid_end = doc_start + len("\\begin{document}")

        for para in comparison["paragraphs"]:
            idx = int(para["index"])
            ns = para.get("new_raw_start")
            ne = para.get("new_raw_end")
            if ns is not None and ne is not None:
                last_valid_end = max(last_valid_end, int(ne))

            hunk_ids = [seg["hunk_id"] for seg in para["segments"] if seg["type"] != "equal"]
            has_revert = any(decisions.get(hid) == "keep_old" for hid in hunk_ids)
            has_edit = idx in edits_map
            if not has_revert and not has_edit:
                continue

            replacement = edits_map[idx].strip() if has_edit else reconstruct_merged_paragraph(para, decisions, as_latex=True)
            if ns is not None and ne is not None and 0 <= int(ns) <= int(ne) <= len(new_full_content):
                patches.append((int(ns), int(ne), replacement))
            elif para["status"] == "deleted" and replacement:
                # Re-insert deleted paragraph right after preceding block
                patches.append((last_valid_end, last_valid_end, "\n\n" + replacement))

        if not patches:
            return new_full_content

        # Apply patches from back to front without mutating earlier offsets
        patched = new_full_content
        patches.sort(key=lambda x: (x[0], x[1]), reverse=True)
        prev_start = len(patched) + 1
        for s, e, rep in patches:
            if e <= prev_start:
                patched = patched[:s] + rep + patched[e:]
                prev_start = s
        return patched

    chunks: list[str] = []
    for para in comparison["paragraphs"]:
        btype = para["block_type"]
        idx = int(para["index"])
        if idx in edits_map:
            merged = edits_map[idx].strip()
        else:
            merged = reconstruct_merged_paragraph(para, decisions, as_latex=is_latex)
        if not merged:
            continue
        if btype == "title":
            chunks.append(f"\\title{{{merged}}}" if is_latex else f"# {merged}")
        elif btype == "heading":
            lvl = para.get("section_level", 1)
            if is_latex:
                if merged.lower() == "abstract":
                    chunks.append("% Abstract")
                elif lvl == 1:
                    chunks.append(f"\\section{{{merged}}}")
                elif lvl == 2:
                    chunks.append(f"\\subsection{{{merged}}}")
                elif lvl == 3:
                    chunks.append(f"\\subsubsection{{{merged}}}")
                else:
                    chunks.append(f"\\paragraph{{{merged}}}")
            else:
                chunks.append(f"{'#' * max(1, min(4, lvl))} {merged}")
        else:
            chunks.append(merged)
    return "\n\n".join(chunks) + "\n"


# ---------------- v1.3 Native Word (.docx) OOXML Track Changes & Clean Export ----------------

def _append_docx_run(p_el: Any, text: str) -> None:
    if not text:
        return
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = text
    r.append(t)
    p_el.append(r)


def _append_docx_tracked(p_el: Any, kind: str, text: str, rev_id: int, author: str, date_iso: str) -> None:
    """Append native OOXML <w:ins> or <w:del> revision markup."""
    if not text:
        return
    tag = "w:ins" if kind == "ins" else "w:del"
    wrapper = OxmlElement(tag)
    wrapper.set(qn("w:id"), str(rev_id))
    wrapper.set(qn("w:author"), author)
    wrapper.set(qn("w:date"), date_iso)
    r = OxmlElement("w:r")
    t = OxmlElement("w:t" if kind == "ins" else "w:delText")
    t.set(qn("xml:space"), "preserve")
    t.text = text
    r.append(t)
    wrapper.append(r)
    p_el.append(wrapper)


def _write_segments_tracked(p_el: Any, segments: list[dict[str, Any]], rev_counter: list[int], author: str, date_iso: str) -> None:
    has_prev = False
    for seg in segments:
        t = seg["type"]
        if t == "equal":
            txt = _render_items_plain(seg["items"], as_latex=False)
            prefix = " " if (has_prev and seg.get("lead_space_new")) else ""
            _append_docx_run(p_el, prefix + txt)
            has_prev = True
        elif t == "replace":
            old_txt = _render_items_plain(seg["old_items"], as_latex=False)
            new_txt = _render_items_plain(seg["new_items"], as_latex=False)
            prefix = " " if (has_prev and (seg.get("lead_space_old") or seg.get("lead_space_new"))) else ""
            if prefix:
                _append_docx_run(p_el, prefix)
            rev_counter[0] += 1
            _append_docx_tracked(p_el, "del", old_txt, rev_counter[0], author, date_iso)
            rev_counter[0] += 1
            _append_docx_tracked(p_el, "ins", new_txt, rev_counter[0], author, date_iso)
            has_prev = True
        elif t == "delete":
            old_txt = _render_items_plain(seg["old_items"], as_latex=False)
            prefix = " " if (has_prev and seg.get("lead_space_old")) else ""
            rev_counter[0] += 1
            _append_docx_tracked(p_el, "del", prefix + old_txt, rev_counter[0], author, date_iso)
            has_prev = True
        elif t == "insert":
            new_txt = _render_items_plain(seg["new_items"], as_latex=False)
            prefix = " " if (has_prev and seg.get("lead_space_new")) else ""
            rev_counter[0] += 1
            _append_docx_tracked(p_el, "ins", prefix + new_txt, rev_counter[0], author, date_iso)
            has_prev = True


def export_docx_tracked_bytes(comparison: dict[str, Any], author: str = "PaperDiff Studio") -> bytes:
    """Export native Microsoft Word / WPS Track Changes (.docx) with <w:ins> and <w:del>."""
    doc = Document()
    date_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rev_counter = [1]

    for para in comparison["paragraphs"]:
        btype = para["block_type"]
        if btype == "title":
            p = doc.add_heading("", level=0)
            _write_segments_tracked(p._p, para["segments"], rev_counter, author, date_iso)
        elif btype == "heading":
            lvl = max(1, min(3, int(para.get("section_level", 1))))
            p = doc.add_heading("", level=lvl)
            _write_segments_tracked(p._p, para["segments"], rev_counter, author, date_iso)
        elif btype == "table" and para.get("table_diff"):
            rows = para["table_diff"]["rows"]
            if not rows:
                continue
            max_cols = max(len(r["cells"]) for r in rows)
            tbl = doc.add_table(rows=len(rows), cols=max_cols)
            tbl.style = "Table Grid"
            for r_idx, r in enumerate(rows):
                for c_idx, cell in enumerate(r["cells"]):
                    cp = tbl.cell(r_idx, c_idx).paragraphs[0]
                    st = cell["status"]
                    if st == "unchanged":
                        _append_docx_run(cp._p, cell["new"])
                    elif st == "added":
                        rev_counter[0] += 1
                        _append_docx_tracked(cp._p, "ins", cell["new"], rev_counter[0], author, date_iso)
                    elif st == "deleted":
                        rev_counter[0] += 1
                        _append_docx_tracked(cp._p, "del", cell["old"], rev_counter[0], author, date_iso)
                    elif cell.get("segments"):
                        _write_segments_tracked(cp._p, cell["segments"], rev_counter, author, date_iso)
                    else:
                        rev_counter[0] += 1
                        _append_docx_tracked(cp._p, "del", cell["old"], rev_counter[0], author, date_iso)
                        rev_counter[0] += 1
                        _append_docx_tracked(cp._p, "ins", cell["new"], rev_counter[0], author, date_iso)
        else:
            p = doc.add_paragraph()
            _write_segments_tracked(p._p, para["segments"], rev_counter, author, date_iso)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def export_docx_merged_bytes(
    comparison: dict[str, Any],
    decisions: dict[str, str],
    paragraph_edits: dict[int, str] | None = None,
) -> bytes:
    """Export clean merged Word (.docx) applying Cherry-Pick decisions and inline edits."""
    doc = Document()
    edits_map = {int(k): v for k, v in (paragraph_edits or {}).items()}

    for para in comparison["paragraphs"]:
        btype = para["block_type"]
        idx = int(para["index"])
        if btype == "table" and para.get("table_diff") and idx not in edits_map:
            rows = [r for r in para["table_diff"]["rows"] if r["status"] != "deleted"]
            if not rows:
                continue
            max_cols = max(len(r["cells"]) for r in rows)
            tbl = doc.add_table(rows=len(rows), cols=max_cols)
            tbl.style = "Table Grid"
            for r_idx, r in enumerate(rows):
                for c_idx, cell in enumerate(r["cells"]):
                    tbl.cell(r_idx, c_idx).text = cell["new"] if cell["status"] != "deleted" else ""
            continue

        merged = (
            edits_map[idx].strip()
            if idx in edits_map
            else reconstruct_merged_paragraph(para, decisions, as_latex=False)
        )
        if not merged:
            continue
        if btype == "title":
            doc.add_heading(merged, level=0)
        elif btype == "heading":
            lvl = max(1, min(3, int(para.get("section_level", 1))))
            doc.add_heading(merged, level=lvl)
        else:
            doc.add_paragraph(merged)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def export_latexdiff_tex(comparison: dict[str, Any], old_label: str, new_label: str) -> str:
    header = (
        "% Generated by PaperDiff Studio (Local Academic Diff Workbench)\n"
        f"% Comparison: {old_label} -> {new_label}\n"
        "% Add the following macros to your preamble if compiling standalone:\n"
        "% \\usepackage[normalem]{ulem}\n"
        "% \\usepackage{xcolor}\n"
        "% \\providecommand{\\DIFadd}[1]{{\\protect\\color{blue}\\uwave{#1}}}\n"
        "% \\providecommand{\\DIFdel}[1]{{\\protect\\color{red}\\sout{#1}}}\n\n"
    )
    lines: list[str] = [header]
    for para in comparison["paragraphs"]:
        btype = para["block_type"]
        if btype == "heading":
            lvl = para.get("section_level", 1)
            title = para["new_raw"] or para["old_raw"] or para["new_clean"]
            cmd = {1: "section", 2: "subsection", 3: "subsubsection"}.get(lvl, "paragraph")
            lines.append(f"\\{cmd}{{{title}}}\n")
            continue
        parts: list[str] = []
        for seg in para["segments"]:
            t = seg["type"]
            if t == "equal":
                if parts and seg.get("lead_space_new"):
                    parts.append(" ")
                parts.append(seg.get("raw", ""))
            elif t == "replace":
                if parts and seg.get("lead_space_old"):
                    parts.append(" ")
                parts.append(f"\\DIFdel{{{seg.get('old_raw', '')}}} \\DIFadd{{{seg.get('new_raw', '')}}}")
            elif t == "delete":
                if parts and seg.get("lead_space_old"):
                    parts.append(" ")
                parts.append(f"\\DIFdel{{{seg.get('old_raw', '')}}}")
            elif t == "insert":
                if parts and seg.get("lead_space_new"):
                    parts.append(" ")
                parts.append(f"\\DIFadd{{{seg.get('new_raw', '')}}}")
        lines.append("".join(parts).strip() + "\n")
    return "\n".join(lines)


def export_markdown_summary(
    comparison: dict[str, Any],
    project_name: str,
    old_label: str,
    new_label: str,
) -> str:
    s = comparison["summary"]
    ev = comparison["evaluation"]
    sign = "+" if s["word_delta"] > 0 else ""
    md = [
        f"# 论文版本修改评估报告：{project_name}",
        "",
        f"- **对比版本**：`{old_label}` → `{new_label}`",
        f"- **综合改稿健康度**：**{ev['overall_health']} / 100**（事实守恒 {ev['scores']['fact_safety']} · 去 AI 味 {ev['scores']['ai_naturalness']} · 可读性 {ev['scores']['readability']}）",
        "",
        "## 1. 全局定量指标",
        "",
        "| 指标 | 数值 |",
        "| :--- | :--- |",
        f"| 词级相似度（LCS） | **{s['overall_similarity']}%**（改写率 {s['rewrite_ratio']}%） |",
        f"| 总词数变化 | {s['old_words']} → {s['new_words']}（**{sign}{s['word_delta']} 词**） |",
        f"| 新增 / 删除词数 | +{s['added_words']} / -{s['deleted_words']} |",
        f"| 段落变动分布 | 修改 {s['modified_paragraphs']} · 新增 {s['added_paragraphs']} · 删除 {s['deleted_paragraphs']} · 未变 {s['unchanged_paragraphs']} |",
        f"| AI 高频套话词 | {ev['ai_ism_diff']['old_count']} → {ev['ai_ism_diff']['new_count']}（{ev['ai_ism_diff']['delta']:+d}） |",
        f"| 平均句长 | {ev['old_style']['avg_sentence_len']} → {ev['new_style']['avg_sentence_len']} 词/句 |",
        "",
        "## 2. 学术事实守恒告警清单",
        "",
    ]
    alerts = comparison["alerts"]
    if not alerts:
        md.append("- 未检测到数值、引文、图表引用或受保护术语的异常变动。")
    else:
        for a in alerts:
            sev_tag = {"high": "[高风险]", "medium": "[注意]", "info": "[提示]"}.get(a["severity"], "[提示]")
            md.append(f"- {sev_tag} **[{a['section']}] {a['title']}**：{a['detail']}")

    md.extend(["", "## 3. 分章节改写概览", "", "| 章节 | 词数变化 | 相似度 | 改动段数 | 告警 |", "| :--- | :---: | :---: | :---: | :---: |"])
    for sec in comparison["sections"]:
        sd = f"+{sec['word_delta']}" if sec["word_delta"] > 0 else str(sec["word_delta"])
        md.append(
            f"| {sec['title']} | {sd} | {sec['similarity']}% | {sec['changed_para_count']}/{sec['para_count']} | {sec['alert_count']} |"
        )
    return "\n".join(md) + "\n"


def _render_items_html(items: list[dict[str, Any]]) -> str:
    out: list[str] = []
    for it in items:
        k = it["kind"]
        if k == "br":
            out.append("<br/>")
            continue
        if k == "text":
            chunk = html.escape(it["text"])
        elif k == "code":
            chunk = f'<code class="chip-code">{html.escape(it.get("value") or it["text"])}</code>'
        elif k == "link":
            href = html.escape(it.get("value") or it["text"], quote=True)
            lbl = html.escape(it["text"])
            chunk = f'<a class="chip-link" href="{href}" target="_blank" rel="noreferrer">{lbl}</a>'
        elif k == "ref":
            chunk = f'<span class="chip-ref">[{html.escape(it["value"])}]</span>'
        elif k == "cite":
            chunk = f'<span class="chip-cite">[@{html.escape(it["value"])}]</span>'
        elif k == "math":
            chunk = f'<span class="chip-math">${html.escape(it["value"])}$</span>'
        else:
            chunk = html.escape(it.get("text", ""))
        if it.get("italic"):
            chunk = f"<em>{chunk}</em>"
        if it.get("bold"):
            chunk = f"<strong>{chunk}</strong>"
        out.append(chunk)
    return "".join(out)


_BRAND_ICON_SVG = (
    '<svg viewBox="0 0 24 24" width="26" height="26" style="flex-shrink:0">'
    '<rect x="0.5" y="0.5" width="23" height="23" rx="5.4" fill="#0D1117"/>'
    '<g transform="translate(12 12) scale(0.68) translate(-12 -12)">'
    '<rect x="2.2" y="5.8" width="8.6" height="15.4" rx="1.6" fill="#FFF"/>'
    '<rect x="3.55" y="8.45" width="4.13" height="1.3" rx="0.65" fill="#8C959F"/>'
    '<rect x="3.55" y="10.95" width="4.96" height="1.3" rx="0.65" fill="#8C959F"/>'
    '<rect x="3.55" y="13.55" width="5.9" height="2" rx="1" fill="#0D1117"/>'
    '<rect x="3.55" y="16.95" width="3.42" height="1.3" rx="0.65" fill="#8C959F"/>'
    '<rect x="13.2" y="2.8" width="8.6" height="15.4" rx="1.6" fill="#FFF"/>'
    '<rect x="14.55" y="5.45" width="4.13" height="1.3" rx="0.65" fill="#8C959F"/>'
    '<rect x="14.55" y="7.95" width="4.96" height="1.3" rx="0.65" fill="#8C959F"/>'
    '<rect x="14.55" y="10.55" width="5.9" height="2" rx="1" fill="#2563EB"/>'
    '<rect x="14.55" y="13.95" width="3.42" height="1.3" rx="0.65" fill="#8C959F"/>'
    '</g></svg>'
)


def export_html_report(
    comparison: dict[str, Any],
    project_name: str,
    old_label: str,
    new_label: str,
    view_mode: str = "split",
) -> str:
    s = comparison["summary"]
    ev = comparison["evaluation"]
    sign = "+" if s["word_delta"] > 0 else ""

    rows_html: list[str] = []
    for p in comparison["paragraphs"]:
        if p["block_type"] == "heading":
            title = html.escape(p["new_clean"] or p["old_clean"])
            rows_html.append(f'<div class="sec-heading">{title}</div>')
            continue

        wd = p["word_delta"]
        wd_str = f"+{wd} 词" if wd > 0 else f"{wd} 词"
        wd_cls = "delta-neg" if wd < 0 else ("delta-pos" if wd > 0 else "delta-zero")
        sim_int = p["similarity_int"]

        if view_mode == "inline":
            parts: list[str] = []
            for seg in p["segments"]:
                t = seg["type"]
                if t == "equal":
                    if parts and seg.get("lead_space_new"):
                        parts.append(" ")
                    parts.append(_render_items_html(seg["items"]))
                elif t == "replace":
                    if parts and seg.get("lead_space_old"):
                        parts.append(" ")
                    parts.append(f'<span class="pill-del">{_render_items_html(seg["old_items"])}</span> ')
                    parts.append(f'<span class="pill-add">{_render_items_html(seg["new_items"])}</span>')
                elif t == "delete":
                    if parts and seg.get("lead_space_old"):
                        parts.append(" ")
                    parts.append(f'<span class="pill-del">{_render_items_html(seg["old_items"])}</span>')
                elif t == "insert":
                    if parts and seg.get("lead_space_new"):
                        parts.append(" ")
                    parts.append(f'<span class="pill-add">{_render_items_html(seg["new_items"])}</span>')
            rows_html.append(
                f'<div class="inline-row">'
                f'<div class="inline-meta"><span class="delta-badge {wd_cls}">{wd_str}</span><span class="sim-tag">相似 {sim_int}%</span></div>'
                f'<div class="prose">{"".join(parts)}</div></div>'
            )
        else:
            left_parts: list[str] = []
            right_parts: list[str] = []
            for seg in p["segments"]:
                t = seg["type"]
                if t == "equal":
                    if left_parts and seg.get("lead_space_old"):
                        left_parts.append(" ")
                    if right_parts and seg.get("lead_space_new"):
                        right_parts.append(" ")
                    left_parts.append(_render_items_html(seg.get("old_items", seg["items"])))
                    right_parts.append(_render_items_html(seg["items"]))
                elif t == "replace":
                    if left_parts and seg.get("lead_space_old"):
                        left_parts.append(" ")
                    if right_parts and seg.get("lead_space_new"):
                        right_parts.append(" ")
                    left_parts.append(f'<span class="pill-del">{_render_items_html(seg["old_items"])}</span>')
                    right_parts.append(f'<span class="pill-add">{_render_items_html(seg["new_items"])}</span>')
                elif t == "delete":
                    if left_parts and seg.get("lead_space_old"):
                        left_parts.append(" ")
                    left_parts.append(f'<span class="pill-del">{_render_items_html(seg["old_items"])}</span>')
                elif t == "insert":
                    if right_parts and seg.get("lead_space_new"):
                        right_parts.append(" ")
                    right_parts.append(f'<span class="pill-add">{_render_items_html(seg["new_items"])}</span>')

            rows_html.append(
                f'<div class="split-row">'
                f'<div class="prose col-left">{"".join(left_parts) or "<span class=empty>—（旧版无此段）</span>"}</div>'
                f'<div class="gutter"><span class="delta-badge {wd_cls}">{wd_str}</span><div class="sim-tag">相似 {sim_int}%</div></div>'
                f'<div class="prose col-right">{"".join(right_parts) or "<span class=empty>—（新版已删除）</span>"}</div>'
                f'</div>'
            )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>对稿 PaperDiff 对比报告 — {html.escape(project_name)}</title>
<style>
  body {{ margin: 0; padding: 32px; background: #f8fafc; color: #1e293b; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
  .container {{ max-width: 1240px; margin: 0 auto; background: #fff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 28px 34px; box-shadow: 0 4px 20px rgba(15,23,42,.04); }}
  .header {{ display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 1px solid #e2e8f0; padding-bottom: 16px; margin-bottom: 24px; }}
  .title {{ font-size: 20px; font-weight: 700; margin: 0 0 6px; }}
  .sub {{ font-size: 13px; color: #64748b; }}
  .stats {{ display: flex; gap: 14px; font-size: 13px; }}
  .stat-pill {{ background: #f1f5f9; padding: 6px 12px; border-radius: 8px; color: #334155; font-weight: 600; }}
  .sec-heading {{ font-size: 15px; font-weight: 700; color: #0f172a; margin: 26px 0 12px; padding-bottom: 6px; border-bottom: 1px solid #f1f5f9; }}
  .split-row {{ display: grid; grid-template-columns: 1fr 84px 1fr; gap: 16px; padding: 14px 0; border-bottom: 1px solid #f1f5f9; align-items: start; }}
  .inline-row {{ padding: 14px 0; border-bottom: 1px solid #f1f5f9; }}
  .inline-meta {{ display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }}
  .gutter {{ text-align: center; padding-top: 4px; }}
  .delta-badge {{ display: inline-block; font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 6px; }}
  .delta-neg {{ background: #e0ecff; color: #2563eb; }}
  .delta-pos {{ background: #dcfce7; color: #15803d; }}
  .delta-zero {{ background: #f1f5f9; color: #64748b; }}
  .sim-tag {{ font-size: 11.5px; color: #64748b; margin-top: 5px; }}
  .prose {{ font-family: "Georgia", "Times New Roman", "Songti SC", "Noto Serif SC", serif; font-size: 15.5px; line-height: 1.88; color: #1f2937; }}
  .pill-del {{ background: #fde8e8; color: #9b1c1c; text-decoration: line-through; text-decoration-color: rgba(220,38,38,.7); padding: 1px 4px; border-radius: 4px; box-decoration-break: clone; -webkit-box-decoration-break: clone; }}
  .pill-add {{ background: #dcfce7; color: #065f46; border-bottom: 1.5px solid #6ee7b7; padding: 1px 4px; border-radius: 4px; box-decoration-break: clone; -webkit-box-decoration-break: clone; }}
  .chip-ref {{ color: #2563eb; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13.5px; }}
  .chip-cite {{ color: #6d28d9; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; background: #f5f3ff; padding: 1px 5px; border-radius: 4px; }}
  .chip-math {{ color: #0f766e; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13.5px; background: #f0fdfa; padding: 1px 5px; border-radius: 4px; }}
  .empty {{ color: #94a3b8; font-style: italic; font-size: 13px; font-family: sans-serif; }}
  @media print {{ body {{ background: #fff; padding: 0; }} .container {{ box-shadow: none; border: none; padding: 0; }} }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div style="display:flex;align-items:center;gap:12px">
      {_BRAND_ICON_SVG}
      <div>
        <h1 class="title">{html.escape(project_name)}</h1>
        <div class="sub">对稿 · PaperDiff · {html.escape(old_label)} &rarr; {html.escape(new_label)} · 综合健康度 {ev['overall_health']}/100</div>
      </div>
    </div>
    <div class="stats">
      <span class="stat-pill">相似度 {s['overall_similarity']}%</span>
      <span class="stat-pill">词数 {sign}{s['word_delta']} 词</span>
      <span class="stat-pill">AI 词 {ev['ai_ism_diff']['old_count']} &rarr; {ev['ai_ism_diff']['new_count']}</span>
    </div>
  </div>
  {"".join(rows_html)}
</div>
</body>
</html>
"""


def apply_single_document_edits(
    content: str,
    fmt: str,
    preview: dict[str, Any],
    paragraph_edits: dict[int, str],
) -> str:
    """
    v1.4.5 Lossless Single-Document Patching:
    - For LaTeX: splice ONLY edited blocks back into exact (raw_start, raw_end)
      character spans so preamble, packages, comments, figures and untouched
      environments stay 100% byte-for-byte intact.
    - For Markdown / Word / Text: preserve untouched blocks' raw_text verbatim
      (including asset:// images and PAPERDIFF_TABLE metadata headers).
    """
    edits_map = {int(k): v for k, v in (paragraph_edits or {}).items()}
    if not edits_map:
        return content

    blocks = preview.get("blocks", [])
    if fmt == "latex":
        patches: list[tuple[int, int, str]] = []
        for blk in blocks:
            idx = int(blk["index"])
            if idx not in edits_map:
                continue
            s = blk.get("raw_start")
            e = blk.get("raw_end")
            if s is not None and e is not None and 0 <= int(s) <= int(e) <= len(content):
                patches.append((int(s), int(e), edits_map[idx].strip()))
        if patches:
            patched = content
            patches.sort(key=lambda x: (x[0], x[1]), reverse=True)
            prev_start = len(patched) + 1
            for s, e, rep in patches:
                if e <= prev_start:
                    patched = patched[:s] + rep + patched[e:]
                    prev_start = s
            return patched

    chunks: list[str] = []
    for blk in blocks:
        idx = int(blk["index"])
        if idx in edits_map:
            txt = edits_map[idx].strip()
        else:
            txt = str(blk.get("raw_text") or "").strip()
        if txt:
            chunks.append(txt)
    return "\n\n".join(chunks) + "\n"


def _asset_to_data_uri(asset_key: str | None) -> str | None:
    if not asset_key:
        return None
    p = get_asset_path(asset_key)
    if not p or not p.exists():
        return None
    mime, _ = mimetypes.guess_type(str(p))
    mime = mime or "image/png"
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def export_single_html_report(
    preview: dict[str, Any],
    title: str,
    version_label: str,
) -> str:
    """Export a clean, standalone, offline-readable HTML view of a single manuscript."""
    s = preview["summary"]
    body_parts: list[str] = []

    for blk in preview.get("blocks", []):
        bt = blk["block_type"]
        if bt == "title":
            body_parts.append(f'<h1 class="paper-title">{_render_items_html(blk["items"])}</h1>')
        elif bt == "heading":
            lvl = max(2, min(4, int(blk.get("section_level") or 1) + 1))
            body_parts.append(f'<h{lvl} class="sec-h sec-h-{lvl}">{_render_items_html(blk["items"])}</h{lvl}>')
        elif bt == "hr":
            body_parts.append('<hr class="doc-hr"/>')
        elif bt == "blockquote":
            body_parts.append(f'<blockquote class="doc-quote">{_render_items_html(blk["items"])}</blockquote>')
        elif bt == "code":
            lang = html.escape(blk.get("code_lang") or "")
            body_parts.append(f'<pre class="doc-code" data-lang="{lang}"><code>{html.escape(blk.get("clean_text") or "")}</code></pre>')
        elif bt == "reference_item":
            rm = blk.get("ref_meta") or {}
            num = f'[{rm["ref_num"]}] ' if rm.get("ref_num") else ""
            body_parts.append(f'<p class="ref-item"><span class="ref-num">{num}</span>{_render_items_html(blk["items"])}</p>')
        elif bt == "figure":
            fi = blk.get("figure_info") or {}
            uri = _asset_to_data_uri(fi.get("asset_key"))
            img_html = f'<img src="{uri}" alt="{html.escape(fi.get("image_path") or "figure")}" />' if uri else f'<div class="fig-placeholder">插图：{html.escape(fi.get("image_path") or "无预览")}</div>'
            cap_html = _render_items_html(blk["items"])
            body_parts.append(f'<figure class="paper-fig">{img_html}<figcaption>{cap_html}</figcaption></figure>')
        elif bt == "table":
            rows = blk.get("table_rows") or []
            tr_list: list[str] = []
            for r_idx, row in enumerate(rows):
                tag = "th" if r_idx == 0 else "td"
                tds: list[str] = []
                for cell in row:
                    cs = f' colspan="{cell["colspan"]}"' if cell.get("colspan", 1) > 1 else ""
                    rs = f' rowspan="{cell["rowspan"]}"' if cell.get("rowspan", 1) > 1 else ""
                    cls = ' class="bold-cell"' if cell.get("bold") else ""
                    inner = _render_items_html(cell.get("items") or [{"kind": "text", "text": cell.get("text", "")}])
                    tds.append(f"<{tag}{cs}{rs}{cls}>{inner}</{tag}>")
                tr_list.append(f"<tr>{''.join(tds)}</tr>")
            body_parts.append(f'<div class="table-wrap"><table class="acad-table">{"".join(tr_list)}</table></div>')
        elif bt == "math":
            eq_num = blk.get("eq_number")
            num_html = f'<span class="eq-num">({eq_num})</span>' if eq_num else ""
            math_val = (blk["items"][0].get("value") if blk.get("items") else blk["clean_text"]) or ""
            body_parts.append(f'<div class="math-block"><code>{html.escape(math_val)}</code>{num_html}</div>')
        elif bt == "list":
            lm = blk.get("list_meta") or {}
            depth = int(lm.get("depth") or 0)
            marker = f'{lm.get("item_num", 1)}.' if lm.get("ordered") else ("•" if depth == 0 else "◦")
            body_parts.append(f'<div class="list-item" style="margin-left:{14 + depth * 20}px"><span class="list-mark">{marker}</span><div>{_render_items_html(blk["items"])}</div></div>')
        elif bt == "caption":
            body_parts.append(f'<p class="caption-p">{_render_items_html(blk["items"])}</p>')
        else:
            body_parts.append(f'<p class="prose">{_render_items_html(blk["items"])}</p>')

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>对稿 PaperDiff — {html.escape(title)} ({html.escape(version_label)})</title>
<style>
  body {{ margin: 0; padding: 36px 20px; background: #f6f7f9; color: #1e293b; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
  .sheet {{ max-width: 820px; margin: 0 auto; background: #fff; border: 1px solid #e2e8f0; border-radius: 16px; padding: 40px 52px; box-shadow: 0 4px 24px rgba(15,23,42,.04); }}
  .meta-bar {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e2e8f0; padding-bottom: 14px; margin-bottom: 28px; font-size: 12.5px; color: #64748b; }}
  .meta-title {{ font-weight: 700; color: #0f172a; font-size: 14px; }}
  .paper-title {{ font-family: "Georgia", "Songti SC", serif; font-size: 24px; line-height: 1.4; color: #0f172a; margin: 0 0 22px; }}
  .sec-h {{ font-weight: 700; color: #0f172a; margin: 28px 0 12px; }}
  .sec-h-2 {{ font-size: 18px; border-bottom: 1px solid #f1f5f9; padding-bottom: 6px; }}
  .sec-h-3 {{ font-size: 15.5px; }}
  .sec-h-4 {{ font-size: 14px; color: #334155; }}
  .prose {{ font-family: "Georgia", "Times New Roman", "Songti SC", "Noto Serif SC", serif; font-size: 16px; line-height: 1.9; color: #1f2937; margin: 0 0 15px; text-align: justify; }}
  .caption-p {{ font-size: 13.5px; line-height: 1.65; color: #475569; margin: 10px 0 18px; }}
  .list-item {{ display: flex; gap: 10px; font-family: "Georgia", "Songti SC", serif; font-size: 15.5px; line-height: 1.8; margin: 6px 0 6px 14px; }}
  .list-mark {{ color: #64748b; font-family: sans-serif; font-weight: 600; min-width: 18px; }}
  .paper-fig {{ margin: 22px 0; padding: 14px; border: 1px solid #e2e8f0; border-radius: 12px; background: #fafbfc; text-align: center; }}
  .paper-fig img {{ max-width: 100%; max-height: 360px; border-radius: 6px; }}
  .paper-fig figcaption {{ margin-top: 10px; font-size: 13.5px; color: #475569; text-align: left; line-height: 1.6; }}
  .fig-placeholder {{ padding: 20px; color: #94a3b8; font-size: 13px; }}
  .table-wrap {{ overflow-x: auto; margin: 20px 0; }}
  .acad-table {{ width: 100%; border-collapse: collapse; font-size: 13.5px; border-top: 2px solid #0f172a; border-bottom: 2px solid #0f172a; }}
  .acad-table th {{ background: #f8fafc; font-weight: 700; text-align: left; padding: 8px 10px; border-bottom: 1px solid #94a3b8; }}
  .acad-table td {{ padding: 7px 10px; border-bottom: 1px solid #f1f5f9; }}
  .acad-table .bold-cell {{ font-weight: 700; color: #0f172a; }}
  .math-block {{ display: flex; justify-content: space-between; align-items: center; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 12px 18px; margin: 16px 0; font-family: ui-monospace, Menlo, monospace; font-size: 14px; color: #0f766e; }}
  .eq-num {{ color: #64748b; font-family: serif; font-size: 14px; margin-left: 16px; }}
  .chip-ref {{ color: #2563eb; font-family: ui-monospace, Menlo, monospace; font-size: 13.5px; }}
  .chip-cite {{ color: #6d28d9; font-family: ui-monospace, Menlo, monospace; font-size: 13px; background: #f5f3ff; padding: 1px 5px; border-radius: 4px; }}
  .chip-math {{ color: #0f766e; font-family: ui-monospace, Menlo, monospace; font-size: 13.5px; background: #f0fdfa; padding: 1px 5px; border-radius: 4px; }}
  @media print {{ body {{ background: #fff; padding: 0; }} .sheet {{ box-shadow: none; border: none; padding: 0; }} }}
</style>
</head>
<body>
<div class="sheet">
  <div class="meta-bar">
    <div style="display:flex;align-items:center;gap:10px">
      {_BRAND_ICON_SVG}
      <div class="meta-title">{html.escape(title)} · {html.escape(version_label)}</div>
    </div>
    <div>{s['word_count']} 词 · {s['figure_count']} 图 · {s['table_count']} 表 · {s['citation_count']} 引文</div>
  </div>
  {"".join(body_parts)}
</div>
</body>
</html>
"""
