# Changelog

All notable changes to **对稿 · PaperDiff** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] - 2026-11-24

Initial public open-source release of **对稿 · PaperDiff** — a 100% local-first academic manuscript reader, structural diff & fact-conservation auditor, and lossless round-trip revision workbench.

### Highlights

- **Modular Open-Source AST Reading Engine (`backend/parsers/`)**
  - **Markdown (`.md / .txt`)**: CommonMark/GFM via `markdown-it-py`, YAML Frontmatter folding, inline/display KaTeX math, footnotes, GitHub Callouts, offline `highlight.js` syntax highlighting, and lazy-loaded offline Mermaid diagrams.
  - **LaTeX (`.tex / .ltx / .zip`)**: `pylatexenc` `LatexWalker` preserving exact `(pos, len)` character spans, preamble `\newcommand` macro injection into KaTeX, `mhchem` / `siunitx`, `amsthm` theorems, `algorithm` pseudocode, multi-`subfigure` grids, `threeparttable`, smart cross-reference jumps, and GB/T 7714 / Nature / IEEE / APA `.bib` citation formatting.
  - **Word (`.docx`)**: Deep OOXML parsing (`numbering.xml` multi-level lists, `footnotes`/`endnotes`, `comments.xml` reviewer bubbles, `mc:Choice` textbox deduplication, pure-Python OMML-to-KaTeX + MathType OLE fallback), **Academic Read ⇄ Original Word (`docx-preview`)** dual view, and 1-click splitting of native Track Changes (`<w:ins>/<w:del>`) into before/after comparison versions.
  - **Academic Typography & Indentation Calibration**: Cross-format extraction of first-line indents, hanging indents, alignment, and 4+ level nested lists/quotes, with Smart Academic Default + 4 named presets and three WCAG-calibrated themes (Light / Warm Sepia / Dark).

- **Local Folder Workspace & Pairwise Structural Diff**
  - Direct local directory binding with canonical `realpath` root sandbox (preventing path traversal and symlink escapes), alongside managed upload workspaces.
  - Bilingual CJK/EN word-level DP alignment, side-by-side / inline / source views, unchanged-block folding, and cross-section move detection.
  - **4-Dimension Local Fact-Conservation Audit**: Instant local detection of numeric/`p`-value changes, citation & `.bib` regressions, broken cross-references, math symbol shifts, table value deltas & best-metric bold shifts (`+B/-B`, `Δ/%`), protected domain terms, and customizable AI-phrase lexicons, with persistent 1-click `✓ Verified` dismissal.

- **In-Place Editing, Lossless Round-Trip Writeback & Offline PDF Export**
  - Double-click in-place editing for paragraphs, headings, captions, equations, and interactive table grids (with automatic body-prose stale-number scan after table edits).
  - Safe disk write policy: defaults to `_revised` sibling copy; automatic `.paperdiff.bak` backup before overwrite.
  - Surgical LaTeX span patching, Overleaf `.zip` repacking via `source_map`, original `.docx` template XML patching (clean or native `<w:ins>/<w:del>` redline), and 100% offline self-contained KaTeX HTML + publication-grade PDF export (macOS native `WKWebView` / Headless Chrome fallback).

- **Dual-Channel Launch, CLI & Performance**
  - Cross-platform runtime coordination (`backend/runtime_state.py`): single-instance port lock, lazy `jieba` loading, silent background Web launcher (`launch_desktop.py --daemon/--status/--stop` + macOS `.command` / Windows `.bat` scripts), PWA manifest, and graceful CSRF-guarded stop.
  - Native macOS desktop shell (`desktop_app.py`, ~47 MB standalone `.dmg`), window geometry memory with multi-monitor clamping, last-workspace quick resume, and `paperdiff <path>` CLI launch with 1-click `~/.local/bin/paperdiff` installation.
  - Verified **60.0 FPS** scrolling (`P50 = 16.65 ms`) on 441-block / 2,750-KaTeX stress manuscripts, backed by **59 pytest + 14 frontend unit tests** and 4 official synthetic showcase manuscripts in [`examples/`](./examples/README.md).
