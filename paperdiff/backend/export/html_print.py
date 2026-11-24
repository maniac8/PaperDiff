"""100% Offline Publication-Grade Printable HTML & Automated Chinese Revision Commentary Engine.

Generates completely self-contained HTML (inlined KaTeX CSS/JS/WOFF2 fonts + Base64 figures,
zero external network/CDN requests) tailored for macOS WKWebView NSPrintOperation and
Chromium headless PDF export in three templates:
  1. pdf_diff_report   — Full version comparison + 4-dim health cards + auto Chinese commentary
  2. pdf_diff_compact  — Changed/flagged blocks only (compact advisor sign-off sheet)
  3. pdf_single        — Publication-grade single-manuscript reading PDF
"""
from __future__ import annotations

import base64
import datetime
import html
import json
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..assets import get_asset_path


def _find_katex_asset_dirs() -> list[Path]:
    dirs: list[Path] = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        dirs.extend([meipass / "frontend" / "dist" / "assets", meipass / "katex"])
    root = Path(__file__).resolve().parent.parent.parent
    dirs.extend(
        [
            root / "frontend" / "node_modules" / "katex" / "dist",
            root / "frontend" / "dist" / "assets",
        ]
    )
    return [d for d in dirs if d.exists()]


@lru_cache(maxsize=1)
def _load_offline_katex_assets() -> tuple[str, str]:
    """
    Load local KaTeX CSS (with WOFF2 fonts inlined as data URIs) + katex.min.js + mhchem.min.js.
    100% offline — zero external CDN links!
    """
    katex_css = ""
    katex_js = ""
    mhchem_js = ""
    font_dirs: list[Path] = []

    for d in _find_katex_asset_dirs():
        if (d / "katex.min.css").exists() and not katex_css:
            katex_css = (d / "katex.min.css").read_text(encoding="utf-8", errors="ignore")
            if (d / "fonts").exists():
                font_dirs.append(d / "fonts")
        if (d / "katex.min.js").exists() and not katex_js:
            katex_js = (d / "katex.min.js").read_text(encoding="utf-8", errors="ignore")
        if (d / "contrib" / "mhchem.min.js").exists() and not mhchem_js:
            mhchem_js = (d / "contrib" / "mhchem.min.js").read_text(encoding="utf-8", errors="ignore")
        font_dirs.append(d)

    # Fallback: pick bundled KaTeX CSS from Vite frontend/dist/assets if node_modules not shipped
    if not katex_css:
        for d in _find_katex_asset_dirs():
            for css_f in sorted(d.glob("*.css")):
                txt = css_f.read_text(encoding="utf-8", errors="ignore")
                if ".katex" in txt:
                    katex_css = txt
                    break

    # Inline essential .woff2 fonts referenced in KaTeX CSS as Base64 data URIs (drop .woff/.ttf fallback bloat)
    if katex_css:
        font_lookup: dict[str, Path] = {}
        for fd in font_dirs:
            for wf in fd.glob("KaTeX_*.woff2"):
                # Map both exact filename and stripped Vite-hashed name
                font_lookup[wf.name] = wf
                clean_name = re.sub(r"-[A-Za-z0-9_-]{6,12}\.woff2$", ".woff2", wf.name)
                font_lookup.setdefault(clean_name, wf)

        def _inline_font_src(m: re.Match[str]) -> str:
            block = m.group(0)
            m_w2 = re.search(r"url\(([^)]+\.woff2)\)", block)
            if not m_w2:
                return block
            raw_ref = m_w2.group(1).strip().strip("'\"")
            fname = Path(raw_ref).name
            clean_fname = re.sub(r"-[A-Za-z0-9_-]{6,12}\.woff2$", ".woff2", fname)
            fp = font_lookup.get(fname) or font_lookup.get(clean_fname)
            if not fp or not fp.exists():
                return block
            b64 = base64.b64encode(fp.read_bytes()).decode("ascii")
            return f"src:url(data:font/woff2;base64,{b64}) format('woff2')"

        katex_css = re.sub(r"src:[^;]+;", _inline_font_src, katex_css)

    combined_js = "\n".join(x for x in (katex_js, mhchem_js) if x)
    return katex_css, combined_js


def _asset_to_data_uri(asset_key: str | None) -> str | None:
    if not asset_key:
        return None
    p = get_asset_path(asset_key)
    if not p or not p.exists():
        return None
    ext = p.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }.get(ext, "application/octet-stream")
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def generate_change_commentary(para: dict[str, Any]) -> list[str]:
    """
    Generate structured, publication-grade Chinese editorial explanations for a modified/flagged block.
    Covers 4 academic dimensions: numerical facts, citations/refs, table best-value bolding, and AI-ism/style.
    """
    notes: list[str] = []
    status = para.get("status", "unchanged")
    alerts = [a for a in (para.get("alerts") or []) if not a.get("acked")]

    for al in alerts[:3]:
        cat = al.get("category", "")
        title = al.get("title", "")
        detail = al.get("detail", "")
        if cat == "number":
            notes.append(f"【数值核查】{title}：{detail}")
        elif cat == "citation":
            notes.append(f"【引文守恒】{title}：{detail}")
        elif cat == "reference":
            notes.append(f"【交叉引用】{title}：{detail}")
        elif cat == "table":
            notes.append(f"【表格变动】{title}：{detail}")
        elif cat == "term":
            notes.append(f"【术语保护】{title}：{detail}")
        else:
            notes.append(f"【核查提醒】{title}：{detail}")

    old_ai = set(para.get("ai_isms_old") or [])
    new_ai = set(para.get("ai_isms_new") or [])
    removed_ai = sorted(old_ai - new_ai)
    added_ai = sorted(new_ai - old_ai)
    if removed_ai:
        notes.append(f"【去 AI 味优化】清理学术套话：{', '.join(removed_ai[:5])}。")
    if added_ai:
        notes.append(f"【新增 AI 高频词】引入 {', '.join(added_ai[:4])}，建议替换为平实学术动词。")

    if para.get("block_type") == "table" and para.get("table_diff"):
        td = para["table_diff"]
        changed_cells = int(td.get("changed_cells", 0))
        if changed_cells > 0 and not any("表格" in n for n in notes):
            notes.append(f"【数据表更新】共修订 {changed_cells} 个单元格，请核对表内数值与正文一致。")

    if not notes and status != "unchanged":
        wdelta = int(para.get("word_delta", 0))
        sim = para.get("similarity", 100)
        if status == "added":
            notes.append(f"【新增段落】本段为新版新增内容（+{para.get('new_word_count', 0)} 词）。")
        elif status == "deleted":
            notes.append(f"【删除段落】原版该段落已整体移除（-{para.get('old_word_count', 0)} 词）。")
        elif status in ("moved_from", "moved_to"):
            notes.append(f"【段落迁移】检测到整段结构调整（目标章节：{para.get('moved_peer_section', '其他章节')}）。")
        else:
            trend = f"扩充 +{wdelta} 词" if wdelta > 0 else (f"精简 {wdelta} 词" if wdelta < 0 else "词数持平")
            notes.append(f"【表述修订】语义保留度 {sim}%，字数{trend}。")
    return notes


def _render_items_print_html(items: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for it in items:
        k = it.get("kind", "text")
        if k == "br":
            parts.append("<br/>")
            continue
        if k == "sp":
            try:
                w = round(min(4.0, max(0.25, float(it.get("value", "1") or "1"))), 2)
            except (TypeError, ValueError):
                w = 1.0
            parts.append(f'<span class="inline-space" style="display:inline-block;width:{w}em;"></span>')
            continue
        if k == "math":
            val = it.get("value", "")
            parts.append(f'<span class="pd-katex-inline" data-tex="{html.escape(val, quote=True)}">{html.escape(val)}</span>')
            continue
        if k == "cite":
            val = str(it.get("value", "")).replace(",", ", ")
            parts.append(f'<span class="chip chip-cite">@{html.escape(val)}</span>')
            continue
        if k == "ref":
            disp = it.get("text") or it.get("value") or ""
            parts.append(f'<span class="chip chip-ref">{html.escape(str(disp))}</span>')
            continue
        if k == "fn":
            val = it.get("value", "")
            parts.append(f'<sup class="chip-fn">[{html.escape(str(val))}]</sup>')
            continue
        if k == "code":
            parts.append(f'<code>{html.escape(str(it.get("text", "")))}</code>')
            continue
        if k == "link":
            lbl = html.escape(str(it.get("text", "")))
            url = html.escape(str(it.get("value", "")), quote=True)
            parts.append(f'<a href="{url}" class="pd-link">{lbl}</a>')
            continue

        txt = html.escape(str(it.get("text", "")))
        if it.get("strike"):
            txt = f"<s>{txt}</s>"
        if it.get("italic"):
            txt = f"<em>{txt}</em>"
        if it.get("bold"):
            txt = f"<strong>{txt}</strong>"
        parts.append(txt)
    return "".join(parts)


def _render_segments_inline_html(segments: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for seg in segments:
        t = seg.get("type")
        lead = " " if (seg.get("lead_space_new") or seg.get("lead_space_old")) else ""
        if t == "equal":
            parts.append(lead + _render_items_print_html(seg.get("items") or []))
        elif t == "delete":
            parts.append(lead + f'<del class="diff-del">{_render_items_print_html(seg.get("old_items") or [])}</del>')
        elif t == "insert":
            parts.append(lead + f'<ins class="diff-ins">{_render_items_print_html(seg.get("new_items") or [])}</ins>')
        elif t == "replace":
            old_h = _render_items_print_html(seg.get("old_items") or [])
            new_h = _render_items_print_html(seg.get("new_items") or [])
            parts.append(f'{lead}<del class="diff-del">{old_h}</del><ins class="diff-ins">{new_h}</ins>')
    return "".join(parts)


def _render_print_shell(
    *,
    doc_title: str,
    body_html: str,
    latex_macros: dict[str, str] | None = None,
    landscape: bool = False,
) -> str:
    katex_css, katex_js = _load_offline_katex_assets()
    macros_json = json.dumps(latex_macros or {}, ensure_ascii=False)
    page_orient = "A4 landscape" if landscape else "A4 portrait"

    boot_script = ""
    if katex_js:
        boot_script = f"""
<script>
{katex_js}
</script>
<script>
(function() {{
  var macros = {macros_json};
  function renderAll() {{
    if (!window.katex) return;
    document.querySelectorAll('.pd-katex-inline').forEach(function(el) {{
      var tex = el.getAttribute('data-tex') || '';
      try {{
        window.katex.render(tex, el, {{ displayMode: false, throwOnError: false, strict: false, macros: Object.assign({{}}, macros) }});
      }} catch (e) {{}}
    }});
    document.querySelectorAll('.pd-katex-display').forEach(function(el) {{
      var tex = el.getAttribute('data-tex') || '';
      try {{
        window.katex.render(tex, el, {{ displayMode: true, throwOnError: false, strict: false, macros: Object.assign({{}}, macros) }});
      }} catch (e) {{}}
    }});
    window.__PAPERDIFF_PRINT_READY__ = true;
  }}
  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', renderAll);
  }} else {{
    renderAll();
  }}
}})();
</script>
"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{html.escape(doc_title)}</title>
<style>
{katex_css}
@page {{
  size: {page_orient};
  margin: 15mm 14mm 16mm 14mm;
}}
* {{ box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Noto Sans CJK SC", "Hiragino Sans GB", "Segoe UI", sans-serif;
  color: #18181b;
  background: #ffffff;
  margin: 0;
  padding: 0;
  font-size: 10.5pt;
  line-height: 1.72;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}}
.page-wrap {{ max-width: 1040px; margin: 0 auto; padding: 18px 20px; }}
@media print {{ .page-wrap {{ max-width: none; padding: 0; }} .no-print {{ display: none !important; }} }}

.report-header {{
  border-bottom: 2px solid #18181b;
  padding-bottom: 12px;
  margin-bottom: 16px;
}}
.brand-kicker {{
  font-size: 8.5pt;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #2563eb;
  margin-bottom: 4px;
}}
.report-title {{ font-size: 18pt; font-weight: 700; margin: 0 0 6px 0; color: #09090b; line-height: 1.3; }}
.report-sub {{ font-size: 9.5pt; color: #52525b; display: flex; flex-wrap: wrap; gap: 14px; }}

.score-grid {{
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin: 14px 0 18px 0;
  break-inside: avoid;
}}
.score-card {{
  border: 1px solid #e4e4e7;
  border-radius: 8px;
  padding: 10px 12px;
  background: #fafafa;
}}
.score-label {{ font-size: 8.5pt; color: #71717a; }}
.score-val {{ font-size: 16pt; font-weight: 700; color: #18181b; margin-top: 2px; }}
.score-meta {{ font-size: 8pt; color: #52525b; margin-top: 2px; }}

.user-note-box {{
  border-left: 3.5px solid #2563eb;
  background: #eff6ff;
  border-radius: 0 8px 8px 0;
  padding: 10px 14px;
  margin: 12px 0 16px 0;
  break-inside: avoid;
}}
.user-note-title {{ font-weight: 700; font-size: 9.5pt; color: #1d4ed8; margin-bottom: 4px; }}

.sec-h1 {{ font-size: 14pt; font-weight: 700; margin: 20px 0 8px 0; padding-bottom: 4px; border-bottom: 1px solid #e4e4e7; page-break-after: avoid; }}
.sec-h2 {{ font-size: 12pt; font-weight: 700; margin: 16px 0 6px 0; page-break-after: avoid; }}
.sec-h3 {{ font-size: 11pt; font-weight: 600; margin: 12px 0 4px 0; page-break-after: avoid; }}

.blk-card {{ margin: 0 0 10px 0; padding: 6px 0; }}
.blk-changed {{
  border-left: 3px solid #3b82f6;
  padding: 8px 12px;
  background: #fcfcfd;
  border-radius: 0 6px 6px 0;
  margin: 10px 0;
  break-inside: avoid;
}}
.blk-alert {{ border-left-color: #dc2626; background: #fffafb; }}

.diff-del {{ background: #fee2e2; color: #991b1b; text-decoration: line-through; padding: 0 2px; border-radius: 3px; }}
.diff-ins {{ background: #dcfce7; color: #166534; text-decoration: none; padding: 0 2px; border-radius: 3px; font-weight: 500; }}

.commentary-box {{
  margin-top: 6px;
  padding: 6px 10px;
  background: #f4f4f5;
  border-radius: 6px;
  font-size: 8.8pt;
  color: #3f3f46;
  line-height: 1.55;
}}
.commentary-item {{ margin: 2px 0; }}

.chip {{ display: inline-block; font-size: 8.5pt; padding: 0 4px; border-radius: 4px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
.chip-cite {{ background: #eef2ff; color: #3730a3; }}
.chip-ref {{ background: #ecfeff; color: #155e75; }}
.chip-fn {{ color: #2563eb; font-weight: 600; font-size: 7.5pt; }}
code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 9pt; background: #f4f4f5; padding: 1px 4px; border-radius: 3px; }}
pre.code-block {{
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 8.5pt;
  line-height: 1.5;
  overflow-x: auto;
  white-space: pre-wrap;
  break-inside: avoid;
}}

.math-display-box {{
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  margin: 10px 0;
  padding: 8px 36px;
  background: #fafafa;
  border-radius: 6px;
  break-inside: avoid;
}}
.eq-num {{ position: absolute; right: 12px; font-size: 9pt; color: #71717a; }}

table.booktabs {{
  width: 100%;
  border-collapse: collapse;
  margin: 10px 0 12px 0;
  font-size: 9pt;
  border-top: 1.8px solid #18181b;
  border-bottom: 1.8px solid #18181b;
  break-inside: avoid;
}}
table.booktabs th, table.booktabs td {{
  padding: 5px 8px;
  text-align: left;
  vertical-align: top;
}}
table.booktabs thead tr {{ border-bottom: 1px solid #52525b; }}
table.booktabs tbody tr:nth-child(even) {{ background: #fafafa; }}
.cell-changed {{ background: #fef9c3 !important; }}
.cell-delta {{ font-size: 7.5pt; color: #b45309; margin-left: 4px; font-family: ui-monospace, monospace; }}

.callout-box {{
  border-left: 3.5px solid #2563eb;
  background: #f8fafc;
  border-radius: 0 6px 6px 0;
  padding: 8px 12px;
  margin: 10px 0;
  break-inside: avoid;
}}
.quote-depth-2 {{
  border-left-color: #6366f1;
  box-shadow: -5px 0 0 -2px rgba(59, 130, 246, 0.32);
}}
.quote-depth-3 {{
  border-left-color: #0ea5e9;
  box-shadow: -5px 0 0 -2px rgba(99, 102, 241, 0.35), -10px 0 0 -4px rgba(59, 130, 246, 0.25);
}}
.quote-depth-4 {{
  border-left-color: #14b8a6;
  box-shadow: -5px 0 0 -2px rgba(14, 165, 233, 0.35), -10px 0 0 -4px rgba(99, 102, 241, 0.25);
}}
.abstract-box {{
  border-left: 2.5px solid #64748b;
  background: #f8fafc;
  border-radius: 0 8px 8px 0;
  padding-top: 8px;
  padding-bottom: 8px;
  margin: 10px 0;
}}
.prose-academic {{
  line-break: strict;
  overflow-wrap: break-word;
}}
.prose-hyphen {{
  hyphens: auto;
  -webkit-hyphens: auto;
}}
.callout-warning, .callout-caution {{ border-left-color: #d97706; background: #fffbeb; }}
.callout-tip {{ border-left-color: #059669; background: #ecfdf5; }}
.callout-important {{ border-left-color: #7c3aed; background: #f5f3ff; }}
.callout-label {{ font-size: 8.5pt; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 3px; }}

.theorem-box {{
  border: 1px solid #cbd5e1;
  border-left: 3.5px solid #334155;
  border-radius: 6px;
  padding: 8px 12px;
  margin: 10px 0;
  background: #f8fafc;
  break-inside: avoid;
}}
.alg-box {{
  border-top: 1.8px solid #18181b;
  border-bottom: 1.8px solid #18181b;
  padding: 8px 10px;
  margin: 10px 0;
  font-size: 9.2pt;
  break-inside: avoid;
}}
.fig-box {{
  text-align: center;
  margin: 12px 0;
  break-inside: avoid;
}}
.fig-box img {{ max-width: 92%; max-height: 360px; object-fit: contain; border: 1px solid #e4e4e7; border-radius: 6px; padding: 4px; background: #fff; }}
.fig-cap {{ font-size: 9pt; color: #52525b; margin-top: 6px; }}
.ref-item {{ font-size: 9pt; padding-left: 26px; text-indent: -26px; margin: 4px 0; color: #27272a; }}
.footnotes-sec {{ margin-top: 22px; padding-top: 10px; border-top: 1px solid #d4d4d8; font-size: 8.8pt; color: #52525b; }}
.alert-table {{ width: 100%; border-collapse: collapse; margin: 8px 0 16px 0; font-size: 8.8pt; }}
.alert-table th, .alert-table td {{ border: 1px solid #e4e4e7; padding: 5px 8px; text-align: left; }}
.alert-table th {{ background: #f4f4f5; }}
.badge-high {{ color: #b91c1c; font-weight: 700; }}
.badge-med {{ color: #b45309; font-weight: 700; }}
.katex, .katex *, .pd-katex-inline, .pd-katex-display, .prose-academic code, .prose-academic sup {{ text-indent: 0; }}
</style>
</head>
<body>
<div class="page-wrap">
{body_html}
</div>
{boot_script}
</body>
</html>"""


def render_diff_print_html(
    comp: dict[str, Any],
    project_name: str,
    old_label: str,
    new_label: str,
    *,
    compact: bool = False,
    commentary_note: str = "",
    landscape: bool = False,
) -> str:
    """Render publication-grade offline printable HTML for full or compact version diff report."""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    summary = comp.get("summary") or {}
    ev = comp.get("evaluation") or {}
    scores = ev.get("scores") or {}
    alerts = [a for a in (comp.get("alerts") or []) if not a.get("acked")]

    parts: list[str] = []
    mode_tag = "精简修订清单（仅变更段落）" if compact else "版本对比与审校讲解报告"
    parts.append(
        f"""
<div class="report-header">
  <div class="brand-kicker">对稿 · PaperDiff v0.1.0 · {mode_tag}</div>
  <h1 class="report-title">{html.escape(project_name)}</h1>
  <div class="report-sub">
    <span><strong>基准版：</strong>{html.escape(old_label)}</span>
    <span>→</span>
    <span><strong>对比版：</strong>{html.escape(new_label)}</span>
    <span><strong>生成时间：</strong>{now_str}</span>
    <span><strong>语义保留度：</strong>{summary.get('overall_similarity', 100)}%</span>
    <span><strong>字数变动：</strong>{summary.get('old_words', 0)} → {summary.get('new_words', 0)} ({summary.get('word_delta', 0):+d})</span>
  </div>
</div>
"""
    )

    # 4-Dim Health Cards
    parts.append(
        f"""
<div class="score-grid">
  <div class="score-card">
    <div class="score-label">综合审校健康分</div>
    <div class="score-val">{ev.get('overall_health', 100)}<span style="font-size:10pt;font-weight:400;"> / 100</span></div>
    <div class="score-meta">修订 {summary.get('modified_paragraphs', 0)} 段 · 新增 {summary.get('added_paragraphs', 0)} · 删除 {summary.get('deleted_paragraphs', 0)}</div>
  </div>
  <div class="score-card">
    <div class="score-label">事实守恒安全分</div>
    <div class="score-val">{scores.get('fact_safety', 100)}</div>
    <div class="score-meta">高危预警 {summary.get('alert_counts', {}).get('high', 0)} · 中危 {summary.get('alert_counts', {}).get('medium', 0)}</div>
  </div>
  <div class="score-card">
    <div class="score-label">去 AI 味自然度</div>
    <div class="score-val">{scores.get('ai_naturalness', 100)}</div>
    <div class="score-meta">AI 词 {ev.get('ai_ism_diff', {}).get('old_count', 0)} → {ev.get('ai_ism_diff', {}).get('new_count', 0)}</div>
  </div>
  <div class="score-card">
    <div class="score-label">学术可读性</div>
    <div class="score-val">{scores.get('readability', 90)}</div>
    <div class="score-meta">平均句长 {ev.get('new_style', {}).get('avg_sentence_len', 0)} 词</div>
  </div>
</div>
"""
    )

    if commentary_note.strip():
        parts.append(
            f'<div class="user-note-box"><div class="user-note-title">作者 / 导师审校批注</div><div>{html.escape(commentary_note.strip()).replace(chr(10), "<br/>")}</div></div>'
        )

    # Fact-Conservation Alert Table
    if alerts:
        parts.append('<h2 class="sec-h2">一、核心事实守恒与风险预警摘要</h2>')
        parts.append('<table class="alert-table"><thead><tr><th style="width:10%;">级别</th><th style="width:22%;">所属章节</th><th style="width:24%;">预警项</th><th>详细说明</th></tr></thead><tbody>')
        for a in alerts[:30]:
            sev = a.get("severity", "info")
            sev_cls = "badge-high" if sev == "high" else ("badge-med" if sev == "medium" else "")
            sev_txt = "高危" if sev == "high" else ("中危" if sev == "medium" else "提示")
            parts.append(
                f'<tr><td class="{sev_cls}">{sev_txt}</td><td>{html.escape(str(a.get("section", "")))}</td>'
                f'<td><strong>{html.escape(str(a.get("title", "")))}</strong></td>'
                f'<td>{html.escape(str(a.get("detail", "")))}</td></tr>'
            )
        parts.append("</tbody></table>")

    parts.append('<h2 class="sec-h2">二、逐段对比与修订讲解</h2>')

    last_emitted_sec = ""
    for para in comp.get("paragraphs") or []:
        if para.get("zone") == "frontmatter":
            continue
        btype = para.get("block_type", "paragraph")
        status = para.get("status", "unchanged")
        has_alerts = any(not a.get("acked") for a in (para.get("alerts") or []))

        if compact and status == "unchanged" and not has_alerts:
            continue

        sec = para.get("section_title", "")
        if compact and sec and sec != last_emitted_sec and btype != "heading":
            parts.append(f'<h3 class="sec-h3">{html.escape(sec)}</h3>')
            last_emitted_sec = sec

        if btype == "heading":
            lvl = min(3, max(1, int(para.get("section_level") or 1)))
            h_html = _render_segments_inline_html(para.get("segments") or []) if status != "unchanged" else _render_items_print_html(para.get("heading_items") or [])
            parts.append(f'<h{lvl} class="sec-h{lvl}">{h_html or html.escape(para.get("new_clean") or para.get("old_clean") or "")}</h{lvl}>')
            last_emitted_sec = sec
            continue

        if btype == "hr":
            parts.append('<hr style="border:none;border-top:1px solid #d4d4d8;margin:12px 0;" />')
            continue

        wrap_cls = "blk-card"
        if status != "unchanged":
            wrap_cls = "blk-changed blk-alert" if has_alerts else "blk-changed"

        inner_html = ""
        if btype == "math":
            md = para.get("math_diff") or {}
            tex = md.get("new_expr") or md.get("old_expr") or ""
            eq_num = para.get("eq_number")
            eq_tag = f'<span class="eq-num">({eq_num})</span>' if eq_num else ""
            inner_html = f'<div class="math-display-box"><span class="pd-katex-display" data-tex="{html.escape(tex, quote=True)}">{html.escape(tex)}</span>{eq_tag}</div>'
        elif btype == "table" and para.get("table_diff"):
            td = para["table_diff"]
            rows_d = td.get("rows") or []
            t_parts = ['<table class="booktabs">']
            for ri, r_obj in enumerate(rows_d):
                cells = r_obj.get("cells") or []
                tag = "th" if ri == 0 else "td"
                if ri == 0:
                    t_parts.append("<thead><tr>")
                elif ri == 1:
                    t_parts.append("<tbody><tr>")
                else:
                    t_parts.append("<tr>")
                for c in cells:
                    cs = int(c.get("colspan", 1))
                    rs = int(c.get("rowspan", 1))
                    span_attr = (f' colspan="{cs}"' if cs > 1 else "") + (f' rowspan="{rs}"' if rs > 1 else "")
                    c_cls = ' class="cell-changed"' if c.get("status") not in ("unchanged", None) else ""
                    if c.get("status") == "modified":
                        c_body = f'<del class="diff-del">{_render_items_print_html(c.get("old_items") or [])}</del> → <ins class="diff-ins">{_render_items_print_html(c.get("new_items") or [])}</ins>'
                    else:
                        c_body = _render_items_print_html(c.get("new_items") or c.get("old_items") or [])
                    nd = c.get("numeric_delta")
                    if nd and nd.get("pct") is not None:
                        c_body += f'<span class="cell-delta">({nd["pct"]:+.1f}%)</span>'
                    if c.get("new_bold"):
                        c_body = f"<strong>{c_body}</strong>"
                    t_parts.append(f"<{tag}{span_attr}{c_cls}>{c_body}</{tag}>")
                t_parts.append("</tr>")
                if ri == 0:
                    t_parts.append("</thead>")
            if len(rows_d) > 1:
                t_parts.append("</tbody>")
            t_parts.append("</table>")
            inner_html = "".join(t_parts)
        elif btype == "figure":
            fi = para.get("figure_info") or {}
            uri = _asset_to_data_uri(fi.get("new_asset_key") or fi.get("old_asset_key"))
            img_tag = f'<img src="{uri}" />' if uri else ""
            cap_h = _render_segments_inline_html(para.get("segments") or [])
            inner_html = f'<div class="fig-box">{img_tag}<div class="fig-cap">{cap_h}</div></div>'
        elif btype == "code":
            inner_html = f'<pre class="code-block">{html.escape(para.get("new_clean") or para.get("old_clean") or "")}</pre>'
        else:
            inner_html = f'<div>{_render_segments_inline_html(para.get("segments") or [])}</div>'

        commentary_html = ""
        if status != "unchanged" or has_alerts:
            c_lines = generate_change_commentary(para)
            if c_lines:
                commentary_html = (
                    '<div class="commentary-box">'
                    + "".join(f'<div class="commentary-item">{html.escape(cl)}</div>' for cl in c_lines)
                    + "</div>"
                )

        parts.append(f'<div class="{wrap_cls}">{inner_html}{commentary_html}</div>')

    return _render_print_shell(
        doc_title=f"{project_name} · {mode_tag}",
        body_html="\n".join(parts),
        latex_macros=comp.get("latex_macros") or {},
        landscape=landscape,
    )


_LIST_BULLETS = ("•", "◦", "▪", "‣", "–", "·")

_PRINT_TYPO_PRESETS: dict[str, dict[str, Any]] = {
    "auto": {"indentMode": "auto", "lineHeight": 1.88, "paragraphGap": "normal", "textAlign": "auto"},
    "source": {"indentMode": "source", "lineHeight": 1.85, "paragraphGap": "normal", "textAlign": "auto"},
    "zh_thesis": {"indentMode": "2em", "lineHeight": 1.92, "paragraphGap": "compact", "textAlign": "justify"},
    "en_journal": {"indentMode": "source", "lineHeight": 1.76, "paragraphGap": "normal", "textAlign": "justify"},
    "modern_note": {"indentMode": "none", "lineHeight": 1.82, "paragraphGap": "relaxed", "textAlign": "left"},
}


def _clamp_num(val: Any, lo: float, hi: float, default: float) -> float:
    try:
        num = float(val)
    except (TypeError, ValueError):
        return default
    if num != num:  # NaN check
        return default
    return round(min(hi, max(lo, num)), 2)


def _normalize_print_typography_prefs(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize optional typography preferences to match frontend `normalizeTypographyPrefs`."""
    obj = raw if isinstance(raw, dict) else {}
    preset = obj.get("typographyPreset")
    if preset not in (*_PRINT_TYPO_PRESETS.keys(), "custom"):
        preset = "auto"
    base = _PRINT_TYPO_PRESETS.get(preset, _PRINT_TYPO_PRESETS["auto"])
    indent_mode = obj.get("indentMode")
    if indent_mode not in ("auto", "source", "2em", "none"):
        indent_mode = base["indentMode"]
    line_height = _clamp_num(obj.get("lineHeight"), 1.5, 2.3, float(base["lineHeight"]))
    paragraph_gap = obj.get("paragraphGap")
    if paragraph_gap not in ("compact", "normal", "relaxed"):
        paragraph_gap = base["paragraphGap"]
    text_align = obj.get("textAlign")
    if text_align not in ("auto", "justify", "left"):
        text_align = base["textAlign"]
    return {
        "typographyPreset": preset,
        "indentMode": indent_mode,
        "lineHeight": line_height,
        "paragraphGap": paragraph_gap,
        "textAlign": text_align,
    }


def _resolve_print_block_style(
    block: dict[str, Any],
    doc_lang: str | None,
    prefs: dict[str, Any],
) -> dict[str, Any]:
    """Resolve print HTML typography for one block (mirrors frontend `resolveBlockTypography`, I3)."""
    style = block.get("style") if isinstance(block.get("style"), dict) else {}
    zone = block.get("zone") or "body"
    btype = block.get("block_type", "paragraph")
    line_height = float(prefs["lineHeight"])

    is_abstract = style.get("semantic_role") == "abstract"
    raw_pld = style.get("parent_list_depth")
    parent_list_depth: int | None = None
    if isinstance(raw_pld, (int, float)) and not isinstance(raw_pld, bool):
        parent_list_depth = min(5, max(0, int(raw_pld)))
    quote_depth = 0
    if btype == "blockquote":
        raw_qd = style.get("quote_depth", 1)
        quote_depth = min(4, max(1, int(raw_qd) if isinstance(raw_qd, (int, float)) else 1))

    # Alignment: source explicit alignment always wins
    src_align = style.get("align")
    if src_align in ("left", "center", "right", "justify"):
        text_align = src_align
    elif btype == "paragraph" and zone == "body":
        if prefs["textAlign"] == "left":
            text_align = "left"
        elif prefs["textAlign"] == "justify":
            text_align = "justify"
        else:
            text_align = "left" if doc_lang == "en" else "justify"
    else:
        text_align = "left"

    pad_left = _clamp_num(style.get("left_indent_em"), 0.0, 8.0, 0.0)
    pad_right = _clamp_num(style.get("right_indent_em"), 0.0, 8.0, 0.0)
    if is_abstract:
        pad_left = max(pad_left, 1.25)
        pad_right = max(pad_right, 1.25)

    text_indent = 0.0
    is_hanging = False
    hyphenate = False

    if btype == "paragraph" and zone == "body":
        hanging = _clamp_num(style.get("hanging_indent_em"), 0.0, 4.0, 0.0)
        if hanging > 0:
            is_hanging = True
            text_indent = -hanging
            pad_left = max(pad_left, hanging)
        else:
            has_explicit_fl = isinstance(style.get("first_line_indent_em"), (int, float)) and not isinstance(
                style.get("first_line_indent_em"), bool
            )
            explicit_fl = _clamp_num(style.get("first_line_indent_em"), 0.0, 4.0, 0.0) if has_explicit_fl else 0.0
            exp_ind = style.get("explicit_indent")

            if text_align in ("center", "right"):
                text_indent = 0.0
            elif parent_list_depth is not None:
                text_indent = explicit_fl if (exp_ind == "indent" and has_explicit_fl) else 0.0
            elif is_abstract:
                if exp_ind == "none" or prefs["indentMode"] == "none":
                    text_indent = 0.0
                elif has_explicit_fl:
                    text_indent = explicit_fl
            elif prefs["indentMode"] == "none":
                text_indent = 0.0
            elif prefs["indentMode"] == "2em":
                text_indent = 0.0 if exp_ind == "none" else 2.0
            elif prefs["indentMode"] == "source":
                text_indent = 0.0 if exp_ind == "none" else (explicit_fl if has_explicit_fl else 0.0)
            else:
                # 'auto' (D-01 smart academic default)
                if exp_ind == "none":
                    text_indent = 0.0
                elif has_explicit_fl:
                    text_indent = explicit_fl
                elif doc_lang == "zh":
                    text_indent = 2.0
                else:
                    text_indent = 0.0
        hyphenate = doc_lang == "en" and text_align == "justify"

    return {
        "text_indent_em": text_indent,
        "padding_left_em": pad_left,
        "padding_right_em": pad_right,
        "text_align": text_align,
        "line_height": line_height,
        "is_abstract": is_abstract,
        "is_hanging": is_hanging,
        "quote_depth": quote_depth,
        "parent_list_depth": parent_list_depth,
        "hyphenate": hyphenate,
    }


def render_single_print_html(
    preview: dict[str, Any],
    title: str,
    version_label: str,
    *,
    commentary_note: str = "",
    landscape: bool = False,
    typography_prefs: dict[str, Any] | None = None,
) -> str:
    """Render publication-grade 100% offline single-manuscript reading HTML for PDF export."""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    summary = preview.get("summary") or {}
    blocks = preview.get("blocks") or []
    doc_lang = preview.get("doc_language")
    prefs = _normalize_print_typography_prefs(typography_prefs)
    para_gap_px = {"compact": 6, "normal": 10, "relaxed": 15}[prefs["paragraphGap"]]

    parts: list[str] = []
    parts.append(
        f"""
<div class="report-header">
  <div class="brand-kicker">对稿 · PaperDiff v0.1.0 · 精排阅读版</div>
  <h1 class="report-title">{html.escape(title)}</h1>
  <div class="report-sub">
    <span><strong>版本：</strong>{html.escape(version_label)}</span>
    <span><strong>字数：</strong>{summary.get('word_count', 0)}</span>
    <span><strong>体检健康分：</strong>{preview.get('health_score', 100)} / 100</span>
    <span><strong>导出时间：</strong>{now_str}</span>
  </div>
</div>
"""
    )

    if commentary_note.strip():
        parts.append(
            f'<div class="user-note-box"><div class="user-note-title">审校说明</div><div>{html.escape(commentary_note.strip()).replace(chr(10), "<br/>")}</div></div>'
        )

    for b in blocks:
        if b.get("zone") == "frontmatter" and b.get("block_type") != "table":
            continue
        btype = b.get("block_type", "paragraph")
        items = b.get("items") or []
        typo = _resolve_print_block_style(b, doc_lang, prefs)
        parent_ml_px = (16 + typo["parent_list_depth"] * 18 + 18) if typo["parent_list_depth"] is not None else 0

        if btype == "title":
            parts.append(f'<h1 class="sec-h1" style="border:none;font-size:17pt;text-align:center;">{_render_items_print_html(items)}</h1>')
        elif btype == "heading":
            lvl = min(3, max(1, int(b.get("section_level") or 1)))
            src_align = (b.get("style") or {}).get("align")
            h_style = f' style="text-align:{src_align};"' if src_align in ("center", "right", "left") else ""
            parts.append(f'<h{lvl} class="sec-h{lvl}"{h_style}>{_render_items_print_html(items)}</h{lvl}>')
        elif btype == "hr":
            parts.append('<hr style="border:none;border-top:1px solid #d4d4d8;margin:12px 0;" />')
        elif btype == "math":
            tex = items[0].get("value", "") if items else ""
            eq_num = b.get("eq_number")
            eq_tag = f'<span class="eq-num">({eq_num})</span>' if eq_num else ""
            m_style = f' style="margin-left:{parent_ml_px}px;"' if parent_ml_px > 0 else ""
            parts.append(f'<div class="math-display-box"{m_style}><span class="pd-katex-display" data-tex="{html.escape(tex, quote=True)}">{html.escape(tex)}</span>{eq_tag}</div>')
        elif btype == "code":
            lang = b.get("code_lang") or ""
            hdr = f'<div style="font-size:8pt;color:#64748b;margin-bottom:4px;">{html.escape(lang)}</div>' if lang else ""
            c_style = f' style="margin-left:{parent_ml_px}px;"' if parent_ml_px > 0 else ""
            parts.append(f'<pre class="code-block"{c_style}>{hdr}{html.escape(b.get("clean_text", ""))}</pre>')
        elif btype == "blockquote":
            ct = b.get("callout_type")
            if ct:
                parts.append(f'<div class="callout-box callout-{html.escape(ct)}"><div class="callout-label">{html.escape(ct.upper())}</div><div>{_render_items_print_html(items)}</div></div>')
            else:
                qd = typo["quote_depth"] or 1
                q_cls = f"callout-box quote-depth-{qd}" if qd >= 2 else "callout-box"
                q_styles: list[str] = [f"line-height:{typo['line_height']}"]
                q_ml = parent_ml_px + (qd - 1) * 16
                if q_ml > 0:
                    q_styles.append(f"margin-left:{q_ml}px")
                if typo["padding_left_em"] > 0 and qd == 1:
                    q_styles.append(f"padding-left:{max(1.25, typo['padding_left_em'])}em")
                if typo["padding_right_em"] > 0:
                    q_styles.append(f"padding-right:{max(1.25, typo['padding_right_em'])}em")
                parts.append(f'<div class="{q_cls}" style="{";".join(q_styles)};">{_render_items_print_html(items)}</div>')
        elif btype == "theorem":
            tm = b.get("theorem_meta") or {}
            t_lbl = tm.get("theorem_title", "Theorem")
            if tm.get("theorem_num"):
                t_lbl += f" {tm['theorem_num']}"
            if tm.get("optional_title"):
                t_lbl += f" ({tm['optional_title']})"
            parts.append(f'<div class="theorem-box"><strong>{html.escape(t_lbl)}.</strong> {_render_items_print_html(items)}</div>')
        elif btype == "algorithm":
            am = b.get("algorithm_meta") or {}
            cap = am.get("caption") or ""
            alg_num = am.get("alg_num") or ""
            lines_a = am.get("lines") or []
            ln_html = "".join(
                f'<div style="padding-left:{int(l.get("indent", 0)) * 18}px;">{idx_l}: {_render_items_print_html(l.get("items") or [{"kind":"text","text":l.get("text","")}])}</div>'
                for idx_l, l in enumerate(lines_a, start=1)
            )
            parts.append(f'<div class="alg-box"><div style="font-weight:700;margin-bottom:4px;">Algorithm {alg_num}: {html.escape(cap)}</div>{ln_html}</div>')
        elif btype == "table":
            rows = b.get("table_rows") or []
            aligns = b.get("table_alignments") or []
            if rows:
                tp = ['<table class="booktabs">']
                for ri, row in enumerate(rows):
                    tag = "th" if ri == 0 else "td"
                    if ri == 0:
                        tp.append("<thead><tr>")
                    elif ri == 1:
                        tp.append("<tbody><tr>")
                    else:
                        tp.append("<tr>")
                    for ci, c in enumerate(row):
                        cs = int(c.get("colspan", 1))
                        rs = int(c.get("rowspan", 1))
                        sp_a = (f' colspan="{cs}"' if cs > 1 else "") + (f' rowspan="{rs}"' if rs > 1 else "")
                        al = aligns[ci] if ci < len(aligns) else "left"
                        body_c = _render_items_print_html(c.get("items") or [])
                        if c.get("bold"):
                            body_c = f"<strong>{body_c}</strong>"
                        tp.append(f'<{tag}{sp_a} style="text-align:{al};">{body_c}</{tag}>')
                    tp.append("</tr>")
                    if ri == 0:
                        tp.append("</thead>")
                if len(rows) > 1:
                    tp.append("</tbody>")
                tp.append("</table>")
                parts.append("".join(tp))
        elif btype == "figure":
            fi = b.get("figure_info") or {}
            imgs = fi.get("images") or ([] if not fi.get("asset_key") else [{"asset_key": fi.get("asset_key"), "subcaption": ""}])
            img_tags: list[str] = []
            for im in imgs:
                uri = _asset_to_data_uri(im.get("asset_key"))
                if uri:
                    subc = f'<div style="font-size:8.5pt;color:#52525b;">{html.escape(im.get("subcaption", ""))}</div>' if im.get("subcaption") else ""
                    img_tags.append(f'<div style="display:inline-block;margin:4px;"><img src="{uri}" />{subc}</div>')
            parts.append(f'<div class="fig-box">{"".join(img_tags)}<div class="fig-cap">{_render_items_print_html(items)}</div></div>')
        elif btype == "list":
            lm = b.get("list_meta") or {}
            depth = min(5, max(0, int(lm.get("depth", 0))))
            marker = (
                f"{lm.get('item_num', 1)}."
                if lm.get("ordered")
                else ("☑" if lm.get("checked") is True else ("☐" if lm.get("checked") is False else _LIST_BULLETS[depth]))
            )
            parts.append(
                f'<div class="blk-card prose-academic" style="padding-left:{16 + depth * 18}px;text-indent:-14px;line-height:{typo["line_height"]};margin-bottom:4px;">{marker} {_render_items_print_html(items)}</div>'
            )
        elif btype == "reference_item":
            rm = b.get("ref_meta") or {}
            rnum = rm.get("ref_num")
            pref = f"[{rnum}] " if rnum else ""
            parts.append(f'<div class="ref-item">{pref}{_render_items_print_html(items)}</div>')
        elif btype == "caption":
            src_align = (b.get("style") or {}).get("align")
            cap_style = f' style="text-align:{src_align};"' if src_align in ("center", "right", "left") else ""
            parts.append(f'<p class="fig-cap"{cap_style}>{_render_items_print_html(items)}</p>')
        else:
            p_classes = ["blk-card", "prose-academic"]
            if typo["is_abstract"]:
                p_classes.append("abstract-box")
            if typo["hyphenate"]:
                p_classes.append("prose-hyphen")
            p_styles = [
                f"text-align:{typo['text_align']}",
                f"line-height:{typo['line_height']}",
                f"margin-bottom:{para_gap_px}px",
            ]
            if typo["text_indent_em"] != 0:
                p_styles.append(f"text-indent:{typo['text_indent_em']}em")
            else:
                p_styles.append("text-indent:0")
            if typo["padding_left_em"] > 0:
                p_styles.append(f"padding-left:{typo['padding_left_em']}em")
            if typo["padding_right_em"] > 0:
                p_styles.append(f"padding-right:{typo['padding_right_em']}em")
            if parent_ml_px > 0:
                p_styles.append(f"margin-left:{parent_ml_px}px")
            lang_attr = ' lang="en"' if typo["hyphenate"] else ""
            parts.append(
                f'<p class="{" ".join(p_classes)}"{lang_attr} style="{";".join(p_styles)};">{_render_items_print_html(items)}</p>'
            )

    footnotes = preview.get("footnotes") or {}
    footnote_items = preview.get("footnote_items") or {}
    if footnotes:
        fn_items = "".join(
            f'<div><sup>[{html.escape(str(k))}]</sup> {_render_items_print_html(footnote_items[k]) if k in footnote_items else html.escape(str(v))}</div>'
            for k, v in footnotes.items()
        )
        parts.append(f'<div class="footnotes-sec"><strong>注释 / Footnotes</strong>{fn_items}</div>')

    return _render_print_shell(
        doc_title=f"{title} · {version_label}",
        body_html="\n".join(parts),
        latex_macros=preview.get("latex_macros") or {},
        landscape=landscape,
    )
