"""Open-source AST LaTeX parser powered by pylatexenc (LatexWalker).

Features:
- Preamble macro table extraction (\\newcommand / \\renewcommand / \\DeclareMathOperator / \\def)
  passed to KaTeX macros + 0-arg prose macro expansion
- 3-tier layout/thesis control command stripping (\\fancypagestyle, \\ThisCenterWallPaper, CJK*, spacing, TOCadd)
- siunitx (\\SI, \\qty, \\num, \\ang) + mhchem (\\ce{...}) academic chemistry/unit support
- amsthm theorem/lemma/proof boxes + algorithm/algorithmic pseudocode + lstlisting/minted code blocks
- Multi-subfigure (\\begin{subfigure}, \\subcaptionbox, \\subfloat) + threeparttable/tablenotes
- Exact character offsets (raw_start, raw_end) AND tabular inner cell spans (cell_spans) for surgical patching
- Cross-reference label resolution (\\ref, \\eqref, \\autoref, \\cref -> clickable resolved labels)
- 4-style References formatter (GB/T 7714, Nature, IEEE, APA)
- Overleaf .zip extraction archiving original .zip blob + exact multi-file source_map
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Any

from pylatexenc.latexwalker import (
    LatexCharsNode,
    LatexCommentNode,
    LatexEnvironmentNode,
    LatexGroupNode,
    LatexMacroNode,
    LatexMathNode,
    LatexSpecialsNode,
    LatexWalker,
    get_default_latex_context_db,
)
from pylatexenc.macrospec import EnvironmentSpec, MacroSpec

from ..assets import ALLOWED_IMAGE_EXTS, parse_bibtex_entries, save_asset_bytes, save_blob_bytes
from .ir import (
    DocumentBlock,
    _clean_latex_display_math,
    _resolve_asset_key,
    _strip_inline_markers_fast,
    normalize_block_style,
)
from .zones import (
    _BACKMATTER_HEADING_RE,
    _BODY_START_HEADING_RE,
    _REF_HEADING_RE,
    _classify_document_zones,
    _is_metadata_form_table,
)


# ============================================================================
# Shared Balanced-Brace / Comment-Masking Utilities
# ============================================================================

def _mask_latex_comments_preserve_offsets(text: str) -> str:
    """Replace LaTeX % comments with equal-length spaces preserving 1-to-1 offsets."""
    out_parts: list[str] = []
    for line in text.splitlines(keepends=True):
        eol = ""
        if line.endswith("\r\n"):
            core, eol = line[:-2], "\r\n"
        elif line.endswith("\n") or line.endswith("\r"):
            core, eol = line[:-1], line[-1]
        else:
            core = line

        i = 0
        n = len(core)
        cut = n
        while i < n:
            if core[i] == "%":
                bs = 0
                j = i - 1
                while j >= 0 and core[j] == "\\":
                    bs += 1
                    j -= 1
                if bs % 2 == 0:
                    cut = i
                    break
            i += 1
        if cut < n:
            out_parts.append(core[:cut] + (" " * (n - cut)) + eol)
        else:
            out_parts.append(line)
    return "".join(out_parts)


def _extract_brace_group(text: str, start_brace: int) -> tuple[str, int] | None:
    if start_brace >= len(text) or text[start_brace] != "{":
        return None
    depth = 0
    i = start_brace
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start_brace + 1 : i], i + 1
        i += 1
    return None


def _extract_bracket_group(text: str, start_bracket: int) -> tuple[str, int] | None:
    if start_bracket >= len(text) or text[start_bracket] != "[":
        return None
    depth = 0
    i = start_bracket
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[start_bracket + 1 : i], i + 1
        i += 1
    return None


def _skip_ws(text: str, pos: int) -> int:
    n = len(text)
    while pos < n and text[pos].isspace():
        pos += 1
    return pos


# ============================================================================
# Shared pylatexenc Context DB (extended for academic environments)
# ============================================================================

def _build_academic_latex_context():
    db = get_default_latex_context_db()
    extra_envs = [
        EnvironmentSpec("titlepage", ""),
        EnvironmentSpec("abstract", ""),
        EnvironmentSpec("thebibliography", "{"),
        EnvironmentSpec("figure", "["),
        EnvironmentSpec("figure*", "["),
        EnvironmentSpec("sidewaysfigure", "["),
        EnvironmentSpec("table", "["),
        EnvironmentSpec("table*", "["),
        EnvironmentSpec("sidewaystable", "["),
        EnvironmentSpec("tabular", "[{",),
        EnvironmentSpec("tabular*", "[{{",),
        EnvironmentSpec("tabularx", "{{",),
        EnvironmentSpec("longtable", "[{",),
        EnvironmentSpec("threeparttable", "["),
        EnvironmentSpec("tablenotes", "["),
        EnvironmentSpec("subfigure", "[{"),
        EnvironmentSpec("itemize", "["),
        EnvironmentSpec("enumerate", "["),
        EnvironmentSpec("description", "["),
        EnvironmentSpec("equation", ""),
        EnvironmentSpec("equation*", ""),
        EnvironmentSpec("align", ""),
        EnvironmentSpec("align*", ""),
        EnvironmentSpec("gather", ""),
        EnvironmentSpec("gather*", ""),
        EnvironmentSpec("multline", ""),
        EnvironmentSpec("multline*", ""),
        EnvironmentSpec("eqnarray", ""),
        EnvironmentSpec("eqnarray*", ""),
        EnvironmentSpec("flalign", ""),
        EnvironmentSpec("flalign*", ""),
        EnvironmentSpec("algorithm", "["),
        EnvironmentSpec("algorithm*", "["),
        EnvironmentSpec("algorithm2e", "["),
        EnvironmentSpec("algorithmic", "["),
        EnvironmentSpec("theorem", "["),
        EnvironmentSpec("lemma", "["),
        EnvironmentSpec("proposition", "["),
        EnvironmentSpec("corollary", "["),
        EnvironmentSpec("definition", "["),
        EnvironmentSpec("remark", "["),
        EnvironmentSpec("assumption", "["),
        EnvironmentSpec("example", "["),
        EnvironmentSpec("proof", "["),
        EnvironmentSpec("lstlisting", "["),
        EnvironmentSpec("minted", "[{"),
        EnvironmentSpec("verbatim", ""),
        EnvironmentSpec("spacing", "{"),
        EnvironmentSpec("CJK", "{{"),
        EnvironmentSpec("CJK*", "{{"),
        EnvironmentSpec("minipage", "[{"),
        EnvironmentSpec("adjustbox", "{"),
    ]
    extra_macros = [
        MacroSpec("part", "*[{"),
        MacroSpec("chapter", "*[{"),
        MacroSpec("section", "*[{"),
        MacroSpec("subsection", "*[{"),
        MacroSpec("subsubsection", "*[{"),
        MacroSpec("paragraph", "*[{"),
        MacroSpec("bibliography", "{"),
        MacroSpec("bibliographystyle", "{"),
        MacroSpec("printbibliography", "["),
        MacroSpec("TOCadd", "{"),
        MacroSpec("addcontentsline", "{{{"),
        MacroSpec("ThisCenterWallPaper", "{{"),
        MacroSpec("fancypagestyle", "{{"),
    ]
    db.add_context_category(
        "paperdiff-academic",
        prepend=True,
        macros=extra_macros,
        environments=extra_envs,
    )
    return db


_ACADEMIC_LATEX_DB = _build_academic_latex_context()


# ============================================================================
# Preamble Macro & Theorem Declaration Extractor
# ============================================================================

_MATH_MACRO_HINT_RE = re.compile(
    r"\\(?:mathbb|mathcal|mathbf|mathrm|mathit|mathsf|mathfrak|boldsymbol|bm|operatorname|"
    r"frac|dfrac|sum|prod|int|left|right|vec|hat|bar|tilde|dot|sqrt|partial|nabla|"
    r"alpha|beta|gamma|delta|epsilon|varepsilon|theta|lambda|mu|nu|xi|pi|rho|sigma|tau|phi|varphi|psi|omega|"
    r"Gamma|Delta|Theta|Lambda|Xi|Pi|Sigma|Phi|Psi|Omega|le|ge|ne|approx|sim|cdot|times|pm|to|infty|in|subset|cup|cap)"
    r"|[_^]"
)

_DEFAULT_THEOREM_TITLES: dict[str, str] = {
    "theorem": "Theorem",
    "lemma": "Lemma",
    "proposition": "Proposition",
    "corollary": "Corollary",
    "definition": "Definition",
    "remark": "Remark",
    "assumption": "Assumption",
    "example": "Example",
    "proof": "Proof",
}


def extract_latex_preamble_info(content: str) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """
    Scan LaTeX preamble (and body macro defs) for:
    1. katex_macros: KaTeX-compatible math macro definitions (e.g. {'\\R': '\\mathbb{R}'})
    2. prose_macros: 0-arg plain text macros to expand in prose (e.g. {'\\method': 'AdaptRoute'})
    3. theorem_titles: Custom \\newtheorem{env}{Title} declarations
    """
    masked = _mask_latex_comments_preserve_offsets(content)
    m_begin = re.search(r"\\begin\{document\}", masked)
    preamble = masked[: m_begin.start()] if m_begin else masked[: min(len(masked), 12000)]

    katex_macros: dict[str, str] = {}
    prose_macros: dict[str, str] = {}
    theorem_titles: dict[str, str] = dict(_DEFAULT_THEOREM_TITLES)

    # 1. \DeclareMathOperator(*)?{\cmd}{body}
    for m in re.finditer(r"\\DeclareMathOperator(\*?)\s*", preamble):
        star = m.group(1)
        cur = _skip_ws(preamble, m.end())
        if cur >= len(preamble):
            continue
        if preamble[cur] == "{":
            g1 = _extract_brace_group(preamble, cur)
            if not g1:
                continue
            cmd_name = g1[0].strip()
            cur = _skip_ws(preamble, g1[1])
        else:
            mt = re.match(r"\\[A-Za-z]+", preamble[cur:])
            if not mt:
                continue
            cmd_name = mt.group(0)
            cur = _skip_ws(preamble, cur + mt.end())
        g2 = _extract_brace_group(preamble, cur)
        if g2 and cmd_name.startswith("\\"):
            op_cmd = r"\operatorname*" if star else r"\operatorname"
            katex_macros[cmd_name] = f"{op_cmd}{{{g2[0].strip()}}}"

    # 2. \newcommand / \renewcommand / \providecommand
    for m in re.finditer(r"\\(?:re|provide)?newcommand\*?\s*", preamble):
        cur = _skip_ws(preamble, m.end())
        if cur >= len(preamble):
            continue
        if preamble[cur] == "{":
            g1 = _extract_brace_group(preamble, cur)
            if not g1:
                continue
            cmd_name = g1[0].strip()
            cur = _skip_ws(preamble, g1[1])
        else:
            mt = re.match(r"\\[A-Za-z]+", preamble[cur:])
            if not mt:
                continue
            cmd_name = mt.group(0)
            cur = _skip_ws(preamble, cur + mt.end())
        if not cmd_name.startswith("\\") or cmd_name in (
            "\\headrulewidth", "\\footrulewidth", "\\arraystretch", "\\baselinestretch", "\\theequation", "\\thefigure",
        ):
            continue
        n_args = 0
        if cur < len(preamble) and preamble[cur] == "[":
            b1 = _extract_bracket_group(preamble, cur)
            if b1:
                try:
                    n_args = int(b1[0].strip())
                except ValueError:
                    n_args = 0
                cur = _skip_ws(preamble, b1[1])
        # Optional default arg [...]
        has_opt_default = False
        if cur < len(preamble) and preamble[cur] == "[":
            b2 = _extract_bracket_group(preamble, cur)
            if b2:
                has_opt_default = True
                cur = _skip_ws(preamble, b2[1])
        g_body = _extract_brace_group(preamble, cur)
        if not g_body:
            continue
        body = g_body[0].strip()
        if not body or len(body) > 300:
            continue
        if _MATH_MACRO_HINT_RE.search(body) or n_args > 0:
            if not has_opt_default and not re.search(r"\\(?:if|def|let|csname|@)", body):
                katex_macros[cmd_name] = body
        elif n_args == 0 and not has_opt_default:
            # Clean 0-arg prose macro (e.g., \newcommand{\method}{AdaptRoute})
            clean_val = re.sub(r"\\(?:xspace|emph|textbf|textit|textrm|text)\b", "", body).strip("{} ")
            if clean_val and "\\" not in clean_val and len(clean_val) <= 80:
                prose_macros[cmd_name] = clean_val
            else:
                katex_macros[cmd_name] = body

    # 3. Simple \def\cmd{body} (0-arg math shorthands)
    for m in re.finditer(r"\\def\s*(\\[A-Za-z]+)\s*\{", preamble):
        cmd_name = m.group(1)
        g = _extract_brace_group(preamble, m.end() - 1)
        if g and cmd_name not in katex_macros:
            body = g[0].strip()
            if body and len(body) <= 160 and _MATH_MACRO_HINT_RE.search(body):
                katex_macros[cmd_name] = body

    # 4. \newtheorem(*)?{env}[shared]{Title}[within]
    for m in re.finditer(r"\\newtheorem\*?\s*\{([A-Za-z0-9_]+)\}\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}", preamble):
        env_name = m.group(1).strip()
        title = m.group(2).strip()
        if env_name and title:
            theorem_titles[env_name] = title

    return katex_macros, prose_macros, theorem_titles


# ============================================================================
# Overleaf Project (.zip) Extraction with source_map & Blob Archiving
# ============================================================================

def extract_latex_zip_with_assets(raw_bytes: bytes) -> tuple[str, str, dict[str, Any]]:
    """
    Extract and recursively expand \\input / \\include from a LaTeX project .zip archive,
    archive the original .zip blob for format-preserving round-trip patching,
    record exact character-range source_map per sub-file, and extract figures + .bib + .bbl!
    """
    source_blob_key = save_blob_bytes(raw_bytes, ".zip")
    tex_files: dict[str, str] = {}
    asset_map: dict[str, str] = {}
    bib_entries: dict[str, dict[str, str]] = {}
    bbl_parts: list[str] = []

    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
        for name in zf.namelist():
            if name.startswith("__MACOSX/") or "/._" in name or name.endswith("/"):
                continue
            low = name.lower()
            norm_name = name.lstrip("./")
            ext = Path(low).suffix
            if low.endswith(".tex"):
                try:
                    tex_files[norm_name] = zf.read(name).decode("utf-8", errors="replace")
                except Exception:
                    continue
            elif low.endswith(".bib"):
                try:
                    bib_txt = zf.read(name).decode("utf-8", errors="replace")
                    bib_entries.update(parse_bibtex_entries(bib_txt))
                except Exception:
                    continue
            elif low.endswith(".bbl"):
                try:
                    bbl_parts.append(zf.read(name).decode("utf-8", errors="replace"))
                except Exception:
                    continue
            elif ext in ALLOWED_IMAGE_EXTS or ext == ".pdf":
                try:
                    blob = zf.read(name)
                    key = save_asset_bytes(blob, ext)
                    if key:
                        p = Path(norm_name)
                        stem_rel = str(p.with_suffix(""))
                        candidates = {
                            norm_name, norm_name.lower(), stem_rel, stem_rel.lower(),
                            p.name, p.name.lower(), p.stem, p.stem.lower(),
                        }
                        if len(p.parts) >= 2:
                            sub_rel = str(Path(*p.parts[1:]))
                            sub_stem = str(Path(*p.parts[1:]).with_suffix(""))
                            candidates.update({sub_rel, sub_rel.lower(), sub_stem, sub_stem.lower()})
                        for cand in candidates:
                            asset_map[cand] = key
                except Exception:
                    continue

    if not tex_files:
        raise ValueError("ZIP 压缩包中未找到任何 .tex 文件")

    root_file = None
    for name, content in tex_files.items():
        if "\\documentclass" in content and "\\begin{document}" in content:
            root_file = name
            break
    if root_file is None:
        for name, content in tex_files.items():
            if "\\begin{document}" in content:
                root_file = name
                break
    if root_file is None:
        root_file = sorted(tex_files.keys(), key=lambda x: (x.count("/"), len(x)))[0]

    root_dir = str(Path(root_file).parent)
    if root_dir == ".":
        root_dir = ""

    def _resolve(target: str, current_dir: str) -> str | None:
        target = target.strip()
        candidates = []
        base_targets = [target] if target.endswith(".tex") else [f"{target}.tex", target]
        for bt in base_targets:
            if current_dir:
                candidates.append(str(Path(current_dir) / bt))
            if root_dir:
                candidates.append(str(Path(root_dir) / bt))
            candidates.append(bt)
        for cand in candidates:
            cand_norm = cand.lstrip("./")
            if cand_norm in tex_files:
                return cand_norm
        for bt in base_targets:
            for k in tex_files:
                if k.endswith("/" + bt) or k == bt:
                    return k
        return None

    visited: set[str] = set()
    out_chunks: list[str] = []
    source_map: list[dict[str, Any]] = []
    out_cursor = 0
    inc_re = re.compile(r"\\(?:input|include)\{([^}]+)\}")

    def _append_mapped(member: str, m_start: int, m_end: int, text_piece: str) -> None:
        nonlocal out_cursor
        if not text_piece:
            return
        out_chunks.append(text_piece)
        source_map.append(
            {
                "exp_start": out_cursor,
                "exp_end": out_cursor + len(text_piece),
                "member": member,
                "member_start": m_start,
                "member_end": m_end,
            }
        )
        out_cursor += len(text_piece)

    def _append_marker(marker_txt: str) -> None:
        nonlocal out_cursor
        out_chunks.append(marker_txt)
        out_cursor += len(marker_txt)

    def _expand(file_key: str) -> None:
        if file_key in visited:
            return
        visited.add(file_key)
        src = tex_files[file_key]
        cur_dir = str(Path(file_key).parent)
        if cur_dir == ".":
            cur_dir = ""

        pos = 0
        for m in inc_re.finditer(src):
            inc_target = m.group(1)
            resolved = _resolve(inc_target, cur_dir)
            if not resolved:
                continue
            if m.start() > pos:
                _append_mapped(file_key, pos, m.start(), src[pos : m.start()])
            _append_marker(f"\n% >>> expanded: {resolved}\n")
            _expand(resolved)
            _append_marker(f"\n% <<< end: {resolved}\n")
            pos = m.end()
        if pos < len(src):
            _append_mapped(file_key, pos, len(src), src[pos:])

    _expand(root_file)
    expanded = "".join(out_chunks)

    meta: dict[str, Any] = {
        "assets": asset_map,
        "bib": bib_entries,
        "source_blob_key": source_blob_key,
        "root_file": root_file,
        "source_map": source_map,
    }
    if bbl_parts:
        meta["bbl"] = "\n\n".join(bbl_parts)
    return root_file, expanded, meta


def extract_latex_zip_bytes(raw_bytes: bytes) -> tuple[str, str]:
    root_file, expanded, _ = extract_latex_zip_with_assets(raw_bytes)
    return root_file, expanded


# ============================================================================
# 3-Tier Layout Macro Sanitizer, siunitx & Inline Normalizer
# ============================================================================

_LATEX_DISCARD_CMDS: dict[str, int] = {
    "addcontentsline": 3, "addtocontents": 2, "definecolor": 3, "SetWatermarkText": 1,
    "fancypagestyle": 2, "renewcommand": 2, "newcommand": 2, "providecommand": 2,
    "DeclareMathOperator": 2, "setlength": 2, "addtolength": 2, "setcounter": 2,
    "addtocounter": 2, "ThisCenterWallPaper": 2, "CenterWallPaper": 2, "TileWallPaper": 2,
    "ThisTileWallPaper": 2, "rule": 2, "fontsize": 2, "markboth": 2, "pdfbookmark": 2,
    "currentpdfbookmark": 2, "numberwithin": 2, "counterwithin": 2,
    "pagestyle": 1, "thispagestyle": 1, "pagenumbering": 1, "TOCadd": 1,
    "lhead": 1, "chead": 1, "rhead": 1, "lfoot": 1, "cfoot": 1, "rfoot": 1,
    "fancyhead": 1, "fancyfoot": 1, "fancyhf": 1, "vspace": 1, "hspace": 1,
    "label": 1, "bibliographystyle": 1, "bibliography": 1, "captionsetup": 1,
    "geometry": 1, "hypersetup": 1, "lstset": 1, "rowcolor": 1, "cellcolor": 1,
    "arrayrulecolor": 1, "color": 1, "pagecolor": 1, "selectlanguage": 1,
    "graphicspath": 1, "noalign": 1, "markright": 1, "index": 1, "stepcounter": 1,
    "phantom": 1, "hphantom": 1, "vphantom": 1, "cline": 1, "cmidrule": 1,
    "specialrule": 3, "includegraphics": 1, "AddToShipoutPicture": 1, "AddToShipoutPictureBG": 1,
}

_LATEX_WRAPPER_ENV_ARGS: dict[str, int] = {
    "spacing": 1, "CJK": 2, "CJK*": 2, "minipage": 1, "adjustbox": 1,
    "center": 0, "flushleft": 0, "flushright": 0, "quote": 0, "quotation": 0,
    "landscape": 0, "threeparttable": 0, "tablenotes": 0, "subequations": 0,
    "appendices": 0, "sloppypar": 0, "singlespace": 0, "onehalfspace": 0,
    "doublespace": 0, "titlepage": 0, "small": 0, "footnotesize": 0,
    "normalsize": 0, "large": 0, "Large": 0, "bf": 0,
}

_LATEX_ZERO_ARG_DIRECTIVES = {
    "maketitle", "tableofcontents", "listoffigures", "listoftables",
    "frontmatter", "mainmatter", "backmatter", "appendix",
    "clearpage", "cleardoublepage", "newpage", "pagebreak", "nopagebreak",
    "noindent", "indent", "centering", "raggedright", "raggedleft",
    "hfill", "vfill", "medskip", "smallskip", "bigskip", "par",
    "newline", "linebreak", "phantomsection", "protect", "allowdisplaybreaks",
    "sloppy", "fussy", "onecolumn", "twocolumn", "printbibliography",
    "toprule", "midrule", "bottomrule", "hline", "xspace",
    "normalsize", "small", "footnotesize", "scriptsize", "tiny",
    "large", "Large", "LARGE", "huge", "Huge",
    "bf", "it", "rm", "sf", "tt", "em",
    "bfseries", "itshape", "mdseries", "upshape", "scshape",
    "rmfamily", "sffamily", "ttfamily", "normalfont", "selectfont",
    "ignorespaces", "quad", "qquad", "enspace", "thinspace", "thickspace",
    "negthinspace", "nonumber", "notag",
}

_LATEX_DISCARD_RE = re.compile(
    r"\\(?:" + "|".join(sorted(_LATEX_DISCARD_CMDS.keys(), key=len, reverse=True)) + r")\*?(?![A-Za-z])"
)
_LATEX_WRAPPER_BEGIN_RE = re.compile(
    r"\\begin\{(" + "|".join(re.escape(k) for k in _LATEX_WRAPPER_ENV_ARGS.keys()) + r")\}"
)
_LATEX_WRAPPER_END_RE = re.compile(
    r"\\end\{(?:" + "|".join(re.escape(k) for k in _LATEX_WRAPPER_ENV_ARGS.keys()) + r")\}"
)
_LATEX_STYLE_ARG_RE = re.compile(
    r"^(?:"
    r"empty|plain|fancy|headings|myheadings|arabic|roman|Roman|alph|Alph|"
    r"utf8|utf-8|gbk|bkai|bsmi|gbsn|gkai|song|kai|hei|fangsong|"
    r"[-+]?\d*(?:\.\d+)?\s*(?:pt|cm|mm|in|em|ex|bp|pc|sp|\\textwidth|\\linewidth|\\baselineskip)?|"
    r"[a-zA-Z0-9_./-]+\.(?:jpg|jpeg|png|pdf|eps|svg|tif|tiff)"
    r")$",
    re.IGNORECASE,
)

_SI_UNIT_MAP: dict[str, str] = {
    "\\micro": "\\text{µ}", "\\nano": "\\mathrm{n}", "\\milli": "\\mathrm{m}",
    "\\centi": "\\mathrm{c}", "\\kilo": "\\mathrm{k}", "\\mega": "\\mathrm{M}",
    "\\giga": "\\mathrm{G}", "\\tera": "\\mathrm{T}", "\\peta": "\\mathrm{P}",
    "\\pico": "\\mathrm{p}", "\\femto": "\\mathrm{f}",
    "\\meter": "\\mathrm{m}", "\\metre": "\\mathrm{m}", "\\gram": "\\mathrm{g}",
    "\\second": "\\mathrm{s}", "\\minute": "\\mathrm{min}", "\\hour": "\\mathrm{h}",
    "\\day": "\\mathrm{d}", "\\liter": "\\mathrm{L}", "\\litre": "\\mathrm{L}",
    "\\mole": "\\mathrm{mol}", "\\kelvin": "\\mathrm{K}", "\\celsius": "^\\circ\\mathrm{C}",
    "\\degreeCelsius": "^\\circ\\mathrm{C}", "\\degree": "^\\circ",
    "\\pascal": "\\mathrm{Pa}", "\\hertz": "\\mathrm{Hz}", "\\newton": "\\mathrm{N}",
    "\\joule": "\\mathrm{J}", "\\watt": "\\mathrm{W}", "\\volt": "\\mathrm{V}",
    "\\ampere": "\\mathrm{A}", "\\ohm": "\\Omega", "\\percent": "\\%",
    "\\byte": "\\mathrm{B}", "\\bit": "\\mathrm{b}", "\\decibel": "\\mathrm{dB}",
    "\\per": "/", "\\squared": "^2", "\\cubed": "^3",
    "\\tothe": "^", "\\cdot": "\\cdot ",
}


def _format_si_number(num_str: str) -> str:
    s = num_str.strip()
    m = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)[eE]([+-]?\d+)", s)
    if m:
        return f"{m.group(1)} \\times 10^{{{int(m.group(2))}}}"
    m2 = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)\s*\\pm\s*([+-]?\d+(?:\.\d+)?)", s)
    if m2:
        return f"{m2.group(1)} \\pm {m2.group(2)}"
    return s


def _format_si_unit(unit_str: str) -> str:
    s = unit_str.strip()
    for k, v in sorted(_SI_UNIT_MAP.items(), key=lambda kv: len(kv[0]), reverse=True):
        s = re.sub(re.escape(k) + r"(?![A-Za-z])", lambda _m, rep=v: rep, s)
    # Wrap bare ASCII unit letters if no LaTeX command inside
    if "\\" not in s and re.fullmatch(r"[A-Za-z0-9/.\-^ ]+", s):
        return f"\\mathrm{{{s}}}"
    return s


def _convert_siunitx_and_mhchem(text: str, stash_math_fn: Any) -> str:
    """Convert \\ce{...}, \\SI{val}{unit}, \\qty{val}{unit}, \\num{val}, \\ang{deg} into stashed math."""
    s = text

    # \ce{...} (mhchem) -> stash directly for KaTeX mhchem!
    if "\\ce" in s:
        out: list[str] = []
        pos = 0
        pat = re.compile(r"\\ce\s*")
        while pos < len(s):
            m = pat.search(s, pos)
            if not m:
                out.append(s[pos:])
                break
            out.append(s[pos : m.start()])
            g = _extract_brace_group(s, m.end())
            if g:
                out.append(stash_math_fn(f"\\ce{{{g[0].strip()}}}"))
                pos = g[1]
            else:
                out.append(s[m.start() : m.end()])
                pos = m.end()
        s = "".join(out)

    # \SI[opt]{val}{unit} / \qty[opt]{val}{unit}
    if "\\SI" in s or "\\qty" in s:
        out = []
        pos = 0
        pat = re.compile(r"\\(?:SI|qty)(?![A-Za-z])\s*")
        while pos < len(s):
            m = pat.search(s, pos)
            if not m:
                out.append(s[pos:])
                break
            out.append(s[pos : m.start()])
            cur = m.end()
            if cur < len(s) and s[cur] == "[":
                b = _extract_bracket_group(s, cur)
                if b:
                    cur = _skip_ws(s, b[1])
            g1 = _extract_brace_group(s, cur)
            if not g1:
                out.append(s[m.start() : m.end()])
                pos = m.end()
                continue
            g2 = _extract_brace_group(s, _skip_ws(s, g1[1]))
            if not g2:
                out.append(stash_math_fn(_format_si_number(g1[0])))
                pos = g1[1]
                continue
            out.append(stash_math_fn(f"{_format_si_number(g1[0])}\\,{_format_si_unit(g2[0])}"))
            pos = g2[1]
        s = "".join(out)

    # \num[opt]{val}, \ang[opt]{val}, \si[opt]{unit}, \unit[opt]{unit}
    for cmd, kind in (("num", "num"), ("ang", "ang"), ("si", "unit"), ("unit", "unit")):
        if f"\\{cmd}" not in s:
            continue
        out = []
        pos = 0
        pat = re.compile(rf"\\{cmd}(?![A-Za-z])\s*")
        while pos < len(s):
            m = pat.search(s, pos)
            if not m:
                out.append(s[pos:])
                break
            out.append(s[pos : m.start()])
            cur = m.end()
            if cur < len(s) and s[cur] == "[":
                b = _extract_bracket_group(s, cur)
                if b:
                    cur = _skip_ws(s, b[1])
            g = _extract_brace_group(s, cur)
            if not g:
                out.append(s[m.start() : m.end()])
                pos = m.end()
                continue
            if kind == "num":
                out.append(stash_math_fn(_format_si_number(g[0])))
            elif kind == "ang":
                out.append(stash_math_fn(f"{g[0].strip()}^\\circ"))
            else:
                out.append(stash_math_fn(_format_si_unit(g[0])))
            pos = g[1]
        s = "".join(out)
    return s


def _strip_latex_control_cmds(text: str) -> str:
    if "\\" not in text:
        return text

    out: list[str] = []
    pos = 0
    n = len(text)
    while pos < n:
        m = _LATEX_WRAPPER_BEGIN_RE.search(text, pos)
        if not m:
            out.append(text[pos:])
            break
        out.append(text[pos : m.start()])
        env = m.group(1)
        cur = m.end()
        cur_ws = _skip_ws(text, cur)
        if cur_ws < n and text[cur_ws] == "[":
            b = _extract_bracket_group(text, cur_ws)
            if b:
                cur = b[1]
        for _ in range(_LATEX_WRAPPER_ENV_ARGS.get(env, 0)):
            cur_ws = _skip_ws(text, cur)
            if cur_ws < n and text[cur_ws] == "{":
                g = _extract_brace_group(text, cur_ws)
                if g:
                    cur = g[1]
                else:
                    break
            else:
                break
        out.append(" ")
        pos = cur
    s = _LATEX_WRAPPER_END_RE.sub(" ", "".join(out))

    out2: list[str] = []
    pos = 0
    n = len(s)
    while pos < n:
        m = _LATEX_DISCARD_RE.search(s, pos)
        if not m:
            out2.append(s[pos:])
            break
        out2.append(s[pos : m.start()])
        cmd_raw = m.group(0)[1:].rstrip("*")
        n_args = _LATEX_DISCARD_CMDS.get(cmd_raw, 0)
        cur = m.end()
        for _ in range(3):
            cur_ws = _skip_ws(s, cur)
            if cur_ws < n and s[cur_ws] == "[":
                b = _extract_bracket_group(s, cur_ws)
                if b:
                    cur = b[1]
                    continue
            if cur_ws < n and s[cur_ws] == "(" and cmd_raw in ("cmidrule",):
                end_p = s.find(")", cur_ws)
                if end_p != -1:
                    cur = end_p + 1
                    continue
            break
        for _ in range(n_args):
            cur_ws = _skip_ws(s, cur)
            if cur_ws < n and s[cur_ws] == "[":
                b = _extract_bracket_group(s, cur_ws)
                if b:
                    cur = b[1]
                    cur_ws = _skip_ws(s, cur)
            if cur_ws < n and s[cur_ws] == "{":
                g = _extract_brace_group(s, cur_ws)
                if g:
                    cur = g[1]
                else:
                    break
            elif cur_ws < n and s[cur_ws] == "\\" and cmd_raw in ("renewcommand", "newcommand", "providecommand", "setlength", "addtolength"):
                m_tok = re.match(r"\\[A-Za-z@]+", s[cur_ws:])
                if m_tok:
                    cur = cur_ws + m_tok.end()
                else:
                    break
            else:
                break
        out2.append(" ")
        pos = cur

    s2 = "".join(out2)
    s2 = re.sub(r"\\(?:vskip|hskip|kern)\s*[-+]?\d*(?:\.\d+)?\s*(?:pt|cm|mm|in|em|ex|bp|pc|sp)\b", " ", s2)
    return s2


def _unwrap_simple_command(text: str, cmd: str, prefix: str = "", suffix: str = "") -> str:
    pattern = re.compile(rf"\\{re.escape(cmd)}\*?(?![A-Za-z])\s*")
    out: list[str] = []
    pos = 0
    while pos < len(text):
        m = pattern.search(text, pos)
        if not m:
            out.append(text[pos:])
            break
        out.append(text[pos : m.start()])
        brace_idx = m.end()
        if brace_idx < len(text) and text[brace_idx] == "[":
            b = _extract_bracket_group(text, brace_idx)
            if b:
                brace_idx = _skip_ws(text, b[1])
        grp = _extract_brace_group(text, brace_idx)
        if grp is None:
            out.append(text[m.start() : m.end()])
            pos = m.end()
        else:
            inner, after = grp
            out.append(f"{prefix}{inner}{suffix}")
            pos = after
    return "".join(out)


def _apply_latex_diacritics(s: str) -> str:
    diac_map = {
        ('"', "u"): "ü", ('"', "U"): "Ü", ('"', "o"): "ö", ('"', "O"): "Ö", ('"', "a"): "ä", ('"', "A"): "Ä",
        ("'", "e"): "é", ("'", "E"): "É", ("'", "a"): "á", ("'", "o"): "ó", ("'", "i"): "í", ("'", "u"): "ú",
        ("`", "a"): "à", ("`", "e"): "è", ("`", "o"): "ò", ("`", "u"): "ù",
        ("^", "o"): "ô", ("^", "e"): "ê", ("^", "a"): "â", ("^", "i"): "î", ("^", "u"): "û",
        ("~", "n"): "ñ", ("~", "a"): "ã", ("~", "o"): "õ",
        ("c", "c"): "ç", ("c", "C"): "Ç",
    }
    s = re.sub(
        r"""\\(["'`^~])\{?([A-Za-z])\}?""",
        lambda m: diac_map.get((m.group(1), m.group(2)), m.group(2)),
        s,
    )
    s = re.sub(r"\\c\{([cCsS])\}", lambda m: diac_map.get(("c", m.group(1)), m.group(1)), s)
    s = s.replace(r"\aa ", "å").replace(r"\AA ", "Å").replace(r"\o ", "ø").replace(r"\O ", "Ø").replace(r"\ss ", "ß")
    return s


def _fallback_clean_unknown_macros(s: str) -> str:
    unknown_re = re.compile(r"\\([A-Za-z@]+)\*?(?![A-Za-z])")
    for _ in range(3):
        if "\\" not in s:
            break
        out: list[str] = []
        pos = 0
        n = len(s)
        changed = False
        while pos < n:
            m = unknown_re.search(s, pos)
            if not m:
                out.append(s[pos:])
                break
            out.append(s[pos : m.start()])
            cur = m.end()
            cur_ws = _skip_ws(s, cur)
            if cur_ws < n and s[cur_ws] == "[":
                b = _extract_bracket_group(s, cur_ws)
                if b:
                    cur = b[1]
                    cur_ws = _skip_ws(s, cur)
            if cur_ws < n and s[cur_ws] == "{":
                g = _extract_brace_group(s, cur_ws)
                if g:
                    inner, after = g
                    inner_s = inner.strip()
                    if not inner_s or _LATEX_STYLE_ARG_RE.match(inner_s):
                        out.append(" ")
                    else:
                        out.append(inner)
                    pos = after
                    changed = True
                    continue
            out.append(" ")
            pos = m.end()
            changed = True
        s = "".join(out)
        if not changed:
            break

    for _ in range(3):
        new_s = re.sub(r"\{([^{}⟦⟧]*)\}", r"\1", s)
        if new_s == s:
            break
        s = new_s
    return s


_SUP_MAP = str.maketrans("0123456789+-=()", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾")
_SUB_MAP = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")


def _parse_latex_hspace_em(raw_len: str) -> str | None:
    """Convert positive LaTeX horizontal length (em/ex/pt/cm/mm) to a clamped ⟦SP:...⟧ atom."""
    m = re.match(r"^\s*([+-]?\d+(?:\.\d+)?)\s*(em|ex|pt|cm|mm)\s*$", raw_len, re.IGNORECASE)
    if not m:
        return None
    val = float(m.group(1))
    if val <= 0:
        return None
    unit = m.group(2).lower()
    scale = {"em": 1.0, "ex": 0.5, "pt": 1.0 / 10.5, "cm": 2.7, "mm": 0.27}[unit]
    em = max(0.25, min(4.0, round(val * scale, 2)))
    s_em = f"{em:g}"
    return f"⟦SP:{s_em}⟧"


def normalize_latex_inline(
    raw: str,
    *,
    keep_bold_markers: bool = True,
    keep_spacing_atoms: bool = True,
    prose_macros: dict[str, str] | None = None,
    footnotes_out: dict[str, str] | None = None,
) -> str:
    s = raw
    s = re.sub(r"\s*\n\s*", " ", s)

    math_store: list[str] = []
    code_store: list[str] = []

    def _stash_math(expr: str) -> str:
        cleaned = re.sub(r"\s+", " ", expr.strip())
        idx = len(math_store)
        math_store.append(cleaned)
        return f"__MATH_HOLD_{idx}__"

    def _stash_code(txt: str) -> str:
        idx = len(code_store)
        code_store.append(txt)
        return f"__CODE_HOLD_{idx}__"

    # 0. Stash \verb|...| first
    s = re.sub(r"\\verb\*?(.)(.*?)\1", lambda m: _stash_code(m.group(2)), s)

    # 1. Stash inline math before stripping any LaTeX commands
    s = re.sub(r"\\\((.+?)\\\)", lambda m: _stash_math(m.group(1)), s)
    s = re.sub(r"(?<!\\)(?<!\$)\$(?!\$)(.+?)(?<!\\)\$(?!\$)", lambda m: _stash_math(m.group(1)), s)

    # 1b. Expand 0-arg preamble prose macros (e.g. \method -> AdaptRoute)
    if prose_macros:
        for cmd, val in sorted(prose_macros.items(), key=lambda kv: len(kv[0]), reverse=True):
            if cmd in s:
                s = re.sub(re.escape(cmd) + r"(?![A-Za-z])(?:\{\})?", lambda _m, v=val: v, s)

    # 1c. Convert \ce{...}, \SI{...}{...}, \qty{...}{...}, \num{...}, \ang{...}
    s = _convert_siunitx_and_mhchem(s, _stash_math)

    # 1d. Extract \footnote{...} into footnotes_out if provided
    if footnotes_out is not None and "\\footnote" in s:
        out_fn: list[str] = []
        pos = 0
        pat_fn = re.compile(r"\\footnote(?:\[[^\]]*\])?\s*")
        while pos < len(s):
            m = pat_fn.search(s, pos)
            if not m:
                out_fn.append(s[pos:])
                break
            out_fn.append(s[pos : m.start()])
            g = _extract_brace_group(s, m.end())
            if g:
                fn_id = str(len(footnotes_out) + 1)
                fn_clean = normalize_latex_inline(g[0], prose_macros=prose_macros)
                footnotes_out[fn_id] = fn_clean
                out_fn.append(f"⟦FN:{fn_id}⟧")
                pos = g[1]
            else:
                out_fn.append(s[m.start() : m.end()])
                pos = m.end()
        s = "".join(out_fn)

    # 1e. Preserve explicit horizontal spacing commands before Tier-2/0-arg stripping
    if keep_spacing_atoms:
        s = re.sub(r"\\enspace(?![A-Za-z])[ \t]*", "⟦SP:0.5⟧", s)
        s = re.sub(r"\\quad(?![A-Za-z])[ \t]*", "⟦SP:1⟧", s)
        s = re.sub(r"\\qquad(?![A-Za-z])[ \t]*", "⟦SP:2⟧", s)
        if "\\hspace" in s:
            s = re.sub(
                r"\\hspace\*?\{([^}]*)\}[ \t]*",
                lambda m: _parse_latex_hspace_em(m.group(1)) or " ",
                s,
            )

    # 2. Strip Tier-2 layout / header / footer / TOC / wallpaper control directives & wrapper envs
    s = _strip_latex_control_cmds(s)

    # 3. Protect semantic references & citations
    s = re.sub(
        r"\\(?:eq|c|C|auto|page|name)?ref\{([^}]+)\}",
        lambda m: f"⟦REF:{m.group(1).strip()}⟧",
        s,
    )
    s = re.sub(
        r"\\(?:auto|paren|text|foot)?cite[ptalh]*\*?(?:\[[^\]]*\])*\{([^}]+)\}",
        lambda m: "⟦CITE:" + re.sub(r"\s+", "", m.group(1).strip()) + "⟧",
        s,
    )

    # 4. \href{url}{label} and \url{url}
    if "\\href" in s:
        pat = re.compile(r"\\href\s*")
        out_h: list[str] = []
        pos = 0
        while pos < len(s):
            m = pat.search(s, pos)
            if not m:
                out_h.append(s[pos:])
                break
            out_h.append(s[pos : m.start()])
            g1 = _extract_brace_group(s, m.end())
            if not g1:
                out_h.append(s[m.start() : m.end()])
                pos = m.end()
                continue
            g2 = _extract_brace_group(s, _skip_ws(s, g1[1]))
            if not g2:
                out_h.append(g1[0])
                pos = g1[1]
                continue
            out_h.append(f"⟦LINK:{g2[0].strip()}|{g1[0].strip()}⟧")
            pos = g2[1]
        s = "".join(out_h)
    s = re.sub(r"\\url\{([^}]+)\}", lambda m: f"⟦LINK:{m.group(1).strip()}|{m.group(1).strip()}⟧", s)

    # 5. \texttt{...} -> inline code
    if "\\texttt" in s:
        pat = re.compile(r"\\texttt\s*")
        out_tt: list[str] = []
        pos = 0
        while pos < len(s):
            m = pat.search(s, pos)
            if not m:
                out_tt.append(s[pos:])
                break
            out_tt.append(s[pos : m.start()])
            g = _extract_brace_group(s, m.end())
            if not g:
                out_tt.append(s[m.start() : m.end()])
                pos = m.end()
            else:
                inner = g[0].replace("\\_", "_").replace("\\%", "%").replace("\\&", "&").strip()
                out_tt.append(_stash_code(inner))
                pos = g[1]
        s = "".join(out_tt)

    # 6. \textsuperscript / \textsubscript -> Unicode
    s = re.sub(r"\\textsuperscript\{([0-9+\-=()]+)\}", lambda m: m.group(1).translate(_SUP_MAP), s)
    s = re.sub(r"\\textsubscript\{([0-9+\-=()]+)\}", lambda m: m.group(1).translate(_SUB_MAP), s)

    # 7. \textcolor / \colorbox
    s = re.sub(r"\\(?:textcolor|colorbox)(?:\[[^\]]*\])?\{[^}]+\}\{([^}]*)\}", r"\1", s)

    # 8. Bold / Italic / Strikethrough (\sout)
    if keep_bold_markers:
        s = _unwrap_simple_command(s, "textbf", "⟦B⟧", "⟦/B⟧")
    else:
        s = _unwrap_simple_command(s, "textbf")
    s = _unwrap_simple_command(s, "textit", "⟦I⟧", "⟦/I⟧")
    s = _unwrap_simple_command(s, "emph", "⟦I⟧", "⟦/I⟧")
    s = _unwrap_simple_command(s, "sout", "⟦S⟧", "⟦/S⟧")

    # 9. Benign prose wrappers
    for _ in range(2):
        for cmd in (
            "textrm", "textsf", "textsc", "underline", "text", "mbox", "hbox",
            "hl", "footnote", "makecell", "thead", "textsuperscript", "textsubscript",
        ):
            if f"\\{cmd}" in s:
                s = _unwrap_simple_command(s, cmd)

    # 10. 0-arg directives & spacing
    s = re.sub(
        r"\\(?:" + "|".join(sorted(_LATEX_ZERO_ARG_DIRECTIVES, key=len, reverse=True)) + r")(?![A-Za-z])",
        " ",
        s,
    )
    s = re.sub(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])", r"\1\2", s)

    # 11. Diacritics, punctuation, quotes, dashes
    s = _apply_latex_diacritics(s)
    s = re.sub(r"\\[,;:!/\-]", " ", s)
    s = re.sub(r"\\\s+", " ", s)
    s = s.replace("~", " ")
    s = s.replace("``", "\u201c").replace("''", "\u201d")
    s = s.replace("---", "\u2014").replace("--", "\u2013")
    s = (
        s.replace("\\%", "%")
        .replace("\\&", "&")
        .replace("\\_", "_")
        .replace("\\#", "#")
        .replace("\\$", "$")
        .replace("\\{", "{")
        .replace("\\}", "}")
    )
    s = re.sub(r"\\\\(?:\[[^\]]*\])?", " ", s)

    # 12. Tier-3 fallback
    s = _fallback_clean_unknown_macros(s)

    # 13. Restore stashed inline math & code
    for idx, expr in enumerate(math_store):
        s = s.replace(f"__MATH_HOLD_{idx}__", f"⟦MATH:{expr}⟧")
    for idx, code_txt in enumerate(code_store):
        s = s.replace(f"__CODE_HOLD_{idx}__", f"⟦CODE:{code_txt}⟧")

    s = re.sub(r"\[(fig|tab|sec|eq|alg|app):([^\]]+)\]", r"⟦REF:\1:\2⟧", s)
    s = s.replace("⟦B⟧⟦/B⟧", "").replace("⟦I⟧⟦/I⟧", "").replace("⟦S⟧⟦/S⟧", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ============================================================================
# Tabular Parser WITH Exact Inner Cell Offsets (for surgical LaTeX patching!)
# ============================================================================

def _parse_latex_cell_rich(
    cell_raw: str,
    abs_start: int | None = None,
    prose_macros: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """
    Parse a single LaTeX tabular cell extracting colspan, rowspan, bold, clean text,
    AND exact (inner_s, inner_e, wrap_bold) character span in the original .tex!
    """
    raw_ltrim = len(cell_raw) - len(cell_raw.lstrip())
    raw_rtrim = len(cell_raw) - len(cell_raw.rstrip())
    cell_s = (abs_start + raw_ltrim) if abs_start is not None else None
    cell_e = (abs_start + len(cell_raw) - raw_rtrim) if abs_start is not None else None

    s = cell_raw.strip()
    colspan = 1
    rowspan = 1

    # Strip leading layout commands (do not alter inner_s/inner_e unless simple wrapper)
    s_clean_ctrl = _strip_latex_control_cmds(s).strip()
    # Adjust cell_s if leading rule/rowcolor was stripped
    if cell_s is not None and s_clean_ctrl and s_clean_ctrl in cell_raw:
        rel_idx = cell_raw.find(s_clean_ctrl)
        cell_s = abs_start + rel_idx
        cell_e = cell_s + len(s_clean_ctrl)
    s = s_clean_ctrl

    for _ in range(2):
        mc = re.match(r"\\multicolumn\s*\{(\d+)\}\s*\{[^}]*\}\s*\{", s)
        if mc:
            colspan = max(colspan, int(mc.group(1)))
            grp = _extract_brace_group(s, mc.end() - 1)
            if grp:
                if cell_s is not None:
                    cell_s = cell_s + mc.end()
                    cell_e = cell_s + len(grp[0])
                s = grp[0].strip()
                continue
        mr = re.match(r"\\multirow\s*(?:\[[^\]]*\])?\s*\{(\d+)\}\s*\{[^}]*\}\s*(?:\[[^\]]*\])?\s*\{", s)
        if mr:
            rowspan = max(rowspan, int(mr.group(1)))
            grp = _extract_brace_group(s, mr.end() - 1)
            if grp:
                if cell_s is not None:
                    cell_s = cell_s + mr.end()
                    cell_e = cell_s + len(grp[0])
                s = grp[0].strip()
                continue
        break

    is_bold = False
    outer_span = (cell_s, cell_e) if (cell_s is not None and cell_e is not None) else None
    mb = re.match(r"^\\(?:textbf|mathbf|bm)\s*\{", s)
    if mb:
        grp = _extract_brace_group(s, mb.end() - 1)
        if grp and grp[1] == len(s):
            is_bold = True
            s = grp[0].strip()
    elif re.search(r"\\textbf\{[^}]+\}", s) and len(re.sub(r"\\textbf\{[^}]+\}", "", s).strip()) <= 4:
        is_bold = True

    clean = normalize_latex_inline(s, keep_bold_markers=not is_bold, prose_macros=prose_macros)
    cell_dict = {"text": clean, "colspan": colspan, "rowspan": rowspan, "bold": is_bold}
    span_info = (
        {"outer_s": outer_span[0], "outer_e": outer_span[1], "was_bold": is_bold}
        if outer_span is not None
        else None
    )
    return cell_dict, span_info


def _split_top_level_latex(body: str, sep_pattern: re.Pattern[str]) -> list[tuple[int, int, str]]:
    """Split LaTeX text by separator regex ONLY at brace depth 0, returning (rel_start, rel_end, text)."""
    n = len(body)
    depth = 0
    in_math = False
    segments: list[tuple[int, int, str]] = []
    seg_start = 0
    i = 0
    while i < n:
        ch = body[i]
        if ch == "\\" and i + 1 < n:
            if depth == 0 and not in_math:
                m = sep_pattern.match(body, i)
                if m:
                    segments.append((seg_start, i, body[seg_start:i]))
                    i = m.end()
                    seg_start = i
                    continue
            i += 2
            continue
        if ch == "$":
            in_math = not in_math
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        elif depth == 0 and not in_math:
            m = sep_pattern.match(body, i)
            if m:
                segments.append((seg_start, i, body[seg_start:i]))
                i = m.end()
                seg_start = i
                continue
        i += 1
    segments.append((seg_start, n, body[seg_start:n]))
    return segments


_ROW_BREAK_RE = re.compile(r"\\\\(?:\s*\[[^\]]*\])?")
_COL_SEP_RE = re.compile(r"&")


def _parse_latex_tabular_rows(
    tabular_src: str,
    base_offset: int | None = None,
    prose_macros: dict[str, str] | None = None,
) -> tuple[list[list[dict[str, Any]]], list[list[dict[str, Any] | None]], list[str]]:
    """
    Parse \\begin{tabular...} ... \\end{tabular...} into:
    (rows, cell_spans_matrix, alignments).
    Preserves exact offsets into original .tex for surgical cell patching!
    """
    m_start = re.match(r"\\begin\{(?:tabular\*?|tabularx|longtable)\}", tabular_src)
    if not m_start:
        return [], [], []
    pos = m_start.end()
    pos = _skip_ws(tabular_src, pos)
    if pos < len(tabular_src) and tabular_src[pos] == "[":
        b = _extract_bracket_group(tabular_src, pos)
        if b:
            pos = b[1]

    col_spec_str = ""
    for _ in range(2):
        pos = _skip_ws(tabular_src, pos)
        if pos < len(tabular_src) and tabular_src[pos] == "{":
            grp = _extract_brace_group(tabular_src, pos)
            if grp:
                col_spec_str = grp[0]
                pos = grp[1]
            else:
                break
        else:
            break

    # Extract alignments from column spec (e.g. lccr, l|c|r, p{3cm}S)
    alignments: list[str] = []
    cs_clean = re.sub(r"\{[^{}]*\}", "", col_spec_str)
    for ch in cs_clean:
        if ch in ("l", "p", "X", "L"):
            alignments.append("left")
        elif ch in ("c", "m", "C", "S"):
            alignments.append("center")
        elif ch in ("r", "R"):
            alignments.append("right")

    m_end = re.search(r"\\end\{(?:tabular\*?|tabularx|longtable)\}\s*$", tabular_src)
    body_end_rel = m_end.start() if m_end else len(tabular_src)
    body = tabular_src[pos:body_end_rel]
    body_abs_start = (base_offset + pos) if base_offset is not None else None

    raw_row_segs = _split_top_level_latex(body, _ROW_BREAK_RE)
    rows: list[list[dict[str, Any]]] = []
    span_rows: list[list[dict[str, Any] | None]] = []
    active_rowspans: dict[int, int] = {}

    for r_rel_s, _r_rel_e, rr in raw_row_segs:
        # Check if row has any content after stripping rules
        rr_check = re.sub(
            r"\\(?:toprule|midrule|bottomrule|hline|endhead|endfirsthead|endfoot|endlastfoot)\b",
            " ",
            rr,
        )
        rr_check = re.sub(r"\\(?:cline|cmidrule)(?:\([^)]*\))?\{[^}]*\}", " ", rr_check)
        if not rr_check.strip():
            continue

        col_segs = _split_top_level_latex(rr, _COL_SEP_RE)
        row_out: list[dict[str, Any]] = []
        row_spans: list[dict[str, Any] | None] = []
        col_cursor = 0

        for c_rel_s, _c_rel_e, cr in col_segs:
            cell_abs = (body_abs_start + r_rel_s + c_rel_s) if body_abs_start is not None else None
            # Protect \makecell{a \\ b} newlines cleanly
            cr_proc = re.sub(
                r"\\(?:makecell|thead|shortstack)\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}",
                lambda m: re.sub(r"\\\\(?:\s*\[[^\]]*\])?", "⟦BR⟧", m.group(1)),
                cr,
            )
            cell, span_info = _parse_latex_cell_rich(
                cr_proc,
                abs_start=cell_abs if cr_proc == cr else None,
                prose_macros=prose_macros,
            )
            if active_rowspans.get(col_cursor, 0) > 0 and not cell["text"]:
                active_rowspans[col_cursor] -= 1
                col_cursor += cell["colspan"]
                continue
            row_out.append(cell)
            row_spans.append(span_info)
            if cell["rowspan"] > 1:
                for offset in range(cell["colspan"]):
                    active_rowspans[col_cursor + offset] = cell["rowspan"] - 1
            col_cursor += cell["colspan"]

        if row_out and any(c["text"] for c in row_out):
            rows.append(row_out)
            span_rows.append(row_spans)

    return rows, span_rows, alignments


# ============================================================================
# 4-Style Bibliography Formatter (GB/T 7714, Nature, IEEE, APA)
# ============================================================================

def format_bib_entry_text(key: str, entry: dict[str, Any], style: str = "gbt7714") -> str:
    author = (entry.get("author") or "").strip()
    year = (entry.get("year") or "").strip()
    title = (entry.get("title") or key).strip()
    venue = (entry.get("venue") or "").strip()
    doi = (entry.get("doi") or "").strip()

    if style == "nature":
        parts = []
        if author:
            parts.append(f"{author}.")
        if title:
            parts.append(f"{title}.")
        if venue:
            parts.append(f"⟦I⟧{venue}⟦/I⟧")
        if year:
            parts.append(f"({year}).")
        return " ".join(parts) if parts else key

    if style == "ieee":
        parts = []
        if author:
            parts.append(f"{author},")
        if title:
            parts.append(f"\u201c{title},\u201d")
        if venue:
            parts.append(f"⟦I⟧{venue}⟦/I⟧,")
        if year:
            parts.append(f"{year}.")
        return " ".join(parts) if parts else key

    if style == "apa":
        parts = []
        if author:
            parts.append(author)
        if year:
            parts.append(f"({year}).")
        if title:
            parts.append(f"{title}.")
        if venue:
            parts.append(f"⟦I⟧{venue}⟦/I⟧.")
        return " ".join(parts) if parts else key

    # Default GB/T 7714-2015 style
    parts = []
    if author:
        parts.append(f"{author}.")
    if title:
        parts.append(f"⟦B⟧{title}⟦/B⟧[J].")
    if venue:
        parts.append(f"⟦I⟧{venue}⟦/I⟧,")
    if year:
        parts.append(f"{year}.")
    if doi:
        parts.append(f"DOI:{doi}.")
    return " ".join(parts) if parts else key


def _parse_thebibliography_items(bib_src: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    body = re.sub(r"^.*?\\begin\{thebibliography\}(?:\{[^}]*\})?", "", bib_src, flags=re.DOTALL)
    body = re.sub(r"\\end\{thebibliography\}.*$", "", body, flags=re.DOTALL)
    for bm in re.finditer(
        r"\\bibitem(?:\[([^\]]*)\])?\s*\{([^}]+)\}([\s\S]*?)(?=\\bibitem\b|$)",
        body,
    ):
        key = bm.group(2).strip()
        raw_entry = bm.group(3).strip()
        clean_entry = normalize_latex_inline(raw_entry)
        if clean_entry:
            items.append((key, clean_entry))
    return items


def _parse_algorithmic_lines(alg_src: str, prose_macros: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Convert algorithmic / algorithmicx / algorithm2e pseudocode into indented display lines."""
    m_inner = re.search(r"\\begin\{algorithmic\}(?:\[[^\]]*\])?([\s\S]*?)\\end\{algorithmic\}", alg_src)
    body = m_inner.group(1) if m_inner else alg_src
    body = re.sub(r"\\begin\{algorithm\*?\}|\\end\{algorithm\*?\}", "", body)
    body = re.sub(r"\\caption(?:\[[^\]]*\])?\{[^{}]*\}", "", body)
    body = re.sub(r"\\label\{[^}]*\}", "", body)

    lines_out: list[dict[str, Any]] = []
    indent = 0
    for raw_ln in body.splitlines():
        s = raw_ln.strip()
        if not s:
            continue
        if re.match(r"^\\End(?:For|If|While|Loop|Function|Procedure)\b", s, re.IGNORECASE):
            indent = max(0, indent - 1)
            kw = re.sub(r"^\\End", "end ", s.split()[0], flags=re.IGNORECASE).lower()
            lines_out.append({"indent": indent, "text": f"⟦B⟧{kw}⟦/B⟧"})
            continue
        if re.match(r"^\\(?:Else|ElsIf)\b", s, re.IGNORECASE):
            cur_ind = max(0, indent - 1)
            m_el = re.match(r"^\\ElsIf\{(.*)\}", s, re.IGNORECASE)
            if m_el:
                lines_out.append({"indent": cur_ind, "text": f"⟦B⟧else if⟦/B⟧ {normalize_latex_inline(m_el.group(1), prose_macros=prose_macros)} ⟦B⟧then⟦/B⟧"})
            else:
                lines_out.append({"indent": cur_ind, "text": "⟦B⟧else⟦/B⟧"})
            continue

        matched_block = False
        for cmd, kw, suffix in (
            ("For", "for", "do"),
            ("ForAll", "for all", "do"),
            ("While", "while", "do"),
            ("If", "if", "then"),
            ("Function", "function", ""),
            ("Procedure", "procedure", ""),
        ):
            m_b = re.match(rf"^\\{cmd}(?![A-Za-z])\s*\{{(.*)\}}\s*$", s, re.IGNORECASE)
            if m_b:
                arg = normalize_latex_inline(m_b.group(1), prose_macros=prose_macros)
                tail = f" ⟦B⟧{suffix}⟦/B⟧" if suffix else ""
                lines_out.append({"indent": indent, "text": f"⟦B⟧{kw}⟦/B⟧ {arg}{tail}"})
                indent += 1
                matched_block = True
                break
        if matched_block:
            continue

        for cmd, kw in (("Require", "Require:"), ("Ensure", "Ensure:"), ("Input", "Input:"), ("Output", "Output:"), ("Return", "return")):
            m_k = re.match(rf"^\\{cmd}(?![A-Za-z])\s*(.*)", s, re.IGNORECASE)
            if m_k:
                rest = normalize_latex_inline(m_k.group(1).strip("{}"), prose_macros=prose_macros)
                lines_out.append({"indent": indent, "text": f"⟦B⟧{kw}⟦/B⟧ {rest}".strip()})
                matched_block = True
                break
        if matched_block:
            continue

        s_stmt = re.sub(r"^\\Statex?\s*", "", s, flags=re.IGNORECASE)
        clean_stmt = normalize_latex_inline(s_stmt, prose_macros=prose_macros)
        if clean_stmt:
            lines_out.append({"indent": indent, "text": clean_stmt})

    return lines_out


# ============================================================================
# Main AST-Powered LaTeX Document Parser (pylatexenc.LatexWalker)
# ============================================================================

def parse_latex_with_meta(
    content: str,
    asset_map: dict[str, str] | None = None,
    bib_entries: dict[str, Any] | None = None,
    bbl_content: str | None = None,
) -> tuple[list[DocumentBlock], dict[str, Any]]:
    """
    Parse a LaTeX manuscript using pylatexenc AST into rich DocumentBlocks +
    document metadata (latex_macros, footnotes, label_map).
    """
    katex_macros, prose_macros, theorem_titles = extract_latex_preamble_info(content)
    masked = _mask_latex_comments_preserve_offsets(content)
    blocks: list[DocumentBlock] = []
    doc_footnotes: dict[str, str] = {}
    label_map: dict[str, str] = {}

    eq_counter = 0
    fig_counter = 0
    tab_counter = 0
    alg_counter = 0
    sec_counter = 0
    thm_counters: dict[str, int] = {}

    # 1. Extract \title{...} from preamble/document
    m_title = re.search(r"\\title\s*(?:\[[^\]]*\])?\s*\{", masked)
    if m_title:
        brace_pos = m_title.end() - 1
        grp = _extract_brace_group(masked, brace_pos)
        if grp:
            inner_start = brace_pos + 1
            inner_end = grp[1] - 1
            title_clean = normalize_latex_inline(grp[0], keep_bold_markers=False, prose_macros=prose_macros)
            if title_clean:
                blocks.append(
                    DocumentBlock(
                        index=len(blocks),
                        block_type="title",
                        section_title="Title",
                        section_level=0,
                        raw_text=content[inner_start:inner_end].strip(),
                        clean_text=title_clean,
                        raw_start=inner_start,
                        raw_end=inner_end,
                        zone="body",
                        source_anchor={"kind": "latex_span", "start": inner_start, "end": inner_end},
                    )
                )

    m_begin = re.search(r"\\begin\{document\}", masked)
    m_end = re.search(r"\\end\{document\}", masked)
    body_start = m_begin.end() if m_begin else 0
    body_end = m_end.start() if m_end else len(masked)
    body_masked = masked[body_start:body_end]

    has_chapters = bool(re.search(r"\\chapter\*?\s*(?:\[[^\]]*\])?\s*\{", body_masked))
    level_map = (
        {"part": 1, "chapter": 1, "section": 2, "subsection": 3, "subsubsection": 4, "paragraph": 4}
        if has_chapters
        else {"part": 1, "chapter": 1, "section": 1, "subsection": 2, "subsubsection": 3, "paragraph": 4}
    )

    current_section = "正文" if any("\u4e00" <= ch <= "\u9fff" for ch in body_masked[:600]) else "Main Text"
    current_level = 1
    current_zone = "body"
    has_emitted_refs = False
    last_section_label_target = ""

    def _emit_prose(
        seg_start: int,
        seg_end: int,
        forced_zone: str | None = None,
        style_ctx: dict[str, Any] | None = None,
    ) -> None:
        nonlocal current_section, current_level, current_zone
        zone_here = forced_zone or current_zone
        chunk_masked = masked[seg_start:seg_end]
        if not chunk_masked.strip():
            return

        # Register any standalone \label{sec:...} right after a heading
        for lm in re.finditer(r"\\label\{([^}]+)\}", chunk_masked):
            lbl_k = lm.group(1).strip()
            if lbl_k and lbl_k not in label_map and last_section_label_target:
                label_map[lbl_k] = last_section_label_target

        para_iter = re.finditer(r"(?:^|\n[ \t]*\n+)([\s\S]*?)(?=\n[ \t]*\n+|$)", chunk_masked)
        for pm in para_iter:
            p_raw_start = seg_start + pm.start(1)
            p_raw_end = seg_start + pm.end(1)
            sub = chunk_masked[pm.start(1) : pm.end(1)]
            ltrim = len(sub) - len(sub.lstrip())
            rtrim = len(sub) - len(sub.rstrip())
            p_start = p_raw_start + ltrim
            p_end = p_raw_end - rtrim
            if p_start >= p_end:
                continue
            sub_masked = masked[p_start:p_end]

            p_style: dict[str, Any] = dict(style_ctx or {})
            if re.match(r"^(?:\s*\\(?:par|medskip|smallskip|bigskip)\b)*\s*\\noindent(?![A-Za-z])", sub_masked):
                p_style["explicit_indent"] = "none"
                p_style["first_line_indent_em"] = 0.0
            elif re.match(r"^(?:\s*\\(?:par|medskip|smallskip|bigskip)\b)*\s*\\indent(?![A-Za-z])", sub_masked):
                p_style["explicit_indent"] = "indent"
                p_style["first_line_indent_em"] = 2.0

            if "align" not in p_style:
                if re.search(r"\\centering(?![A-Za-z])", sub_masked):
                    p_style["align"] = "center"
                elif re.search(r"\\raggedleft(?![A-Za-z])", sub_masked):
                    p_style["align"] = "right"
                elif re.search(r"\\raggedright(?![A-Za-z])", sub_masked):
                    p_style["align"] = "left"

            clean = normalize_latex_inline(
                sub_masked,
                prose_macros=prose_macros,
                footnotes_out=doc_footnotes,
            )
            if not clean:
                continue
            plain_check = _strip_inline_markers_fast(clean).strip()
            if (
                len(plain_check) <= 40
                and _BACKMATTER_HEADING_RE.match(plain_check)
                and ("\\Large" in sub_masked or "\\large" in sub_masked or "\\bf" in sub_masked or "\\addcontentsline" in sub_masked)
            ):
                current_section = plain_check
                current_level = 1
                current_zone = "backmatter"
                blocks.append(
                    DocumentBlock(
                        index=len(blocks),
                        block_type="heading",
                        section_title=current_section,
                        section_level=1,
                        raw_text=content[p_start:p_end],
                        clean_text=plain_check,
                        raw_start=p_start,
                        raw_end=p_end,
                        zone="backmatter",
                        source_anchor={"kind": "latex_span", "start": p_start, "end": p_end},
                    )
                )
                continue

            norm_sty = normalize_block_style(p_style)
            is_quote_blk = bool(norm_sty.get("quote_depth"))
            meta_p: dict[str, Any] = {"style": norm_sty} if norm_sty else {}
            blocks.append(
                DocumentBlock(
                    index=len(blocks),
                    block_type="blockquote" if is_quote_blk else "paragraph",
                    section_title=current_section,
                    section_level=current_level,
                    raw_text=content[p_start:p_end],
                    clean_text=clean,
                    raw_start=p_start,
                    raw_end=p_end,
                    zone=zone_here,
                    source_anchor={"kind": "latex_span", "start": p_start, "end": p_end},
                    meta=meta_p,
                )
            )

    def _emit_reference_items(
        ref_items: list[tuple[str, str, dict[str, Any] | None]],
        raw_start: int | None = None,
        raw_end: int | None = None,
    ) -> None:
        nonlocal current_section, current_level, current_zone, has_emitted_refs
        if not ref_items:
            return
        has_emitted_refs = True
        current_zone = "backmatter"
        if not _REF_HEADING_RE.match(current_section):
            current_section = "References"
            current_level = 1
            blocks.append(
                DocumentBlock(
                    index=len(blocks),
                    block_type="heading",
                    section_title="References",
                    section_level=1,
                    raw_text="References",
                    clean_text="References",
                    zone="backmatter",
                )
            )
        for num, (key, txt, entry_dict) in enumerate(ref_items, start=1):
            meta_r: dict[str, Any] = {"ref_num": num, "bib_key": key}
            if entry_dict:
                meta_r["bib_entry"] = entry_dict
            blocks.append(
                DocumentBlock(
                    index=len(blocks),
                    block_type="reference_item",
                    section_title=current_section,
                    section_level=current_level,
                    raw_text=txt,
                    clean_text=txt,
                    raw_start=raw_start,
                    raw_end=raw_end,
                    zone="backmatter",
                    meta=meta_r,
                )
            )

    # Parse body AST via pylatexenc LatexWalker!
    try:
        walker = LatexWalker(body_masked, latex_context=_ACADEMIC_LATEX_DB, tolerant_parsing=True)
        nodelist, _, _ = walker.get_latex_nodes()
    except Exception:
        nodelist = []

    SECTION_MACROS = {"part", "chapter", "section", "subsection", "subsubsection", "paragraph"}
    ZONE_MACROS = {"frontmatter", "mainmatter", "backmatter", "appendix"}
    BOILERPLATE_MACROS = {"maketitle", "tableofcontents", "listoffigures", "listoftables", "bibliographystyle"}
    BIB_MACROS = {"bibliography", "printbibliography"}
    MATH_ENVS = {"equation", "equation*", "align", "align*", "gather", "gather*", "multline", "multline*", "eqnarray", "eqnarray*", "flalign", "flalign*"}
    FLOAT_ENVS = {"figure", "figure*", "sidewaysfigure", "table", "table*", "sidewaystable"}
    TABULAR_ENVS = {"tabular", "tabular*", "tabularx", "longtable"}
    LIST_ENVS = {"itemize", "enumerate", "description"}
    CODE_ENVS = {"lstlisting", "minted", "verbatim"}
    ALG_ENVS = {"algorithm", "algorithm*", "algorithm2e", "algorithmic"}
    THEOREM_ENVS = set(theorem_titles.keys())

    prose_buf_start: int | None = None
    prose_buf_end: int | None = None
    prose_buf_style_ctx: dict[str, Any] | None = None

    def _flush_prose(forced_zone: str | None = None, style_ctx: dict[str, Any] | None = None) -> None:
        nonlocal prose_buf_start, prose_buf_end, prose_buf_style_ctx
        if prose_buf_start is not None and prose_buf_end is not None and prose_buf_end > prose_buf_start:
            eff_ctx = prose_buf_style_ctx if prose_buf_style_ctx is not None else style_ctx
            _emit_prose(prose_buf_start, prose_buf_end, forced_zone=forced_zone, style_ctx=eff_ctx)
        prose_buf_start = None
        prose_buf_end = None
        prose_buf_style_ctx = None

    def _walk_list_env(
        env_node: LatexEnvironmentNode,
        *,
        depth: int = 0,
        forced_zone: str | None = None,
    ) -> None:
        """Recursively parse nested itemize/enumerate/description AST nodes preserving exact spans & depths."""
        is_ordered = env_node.environmentname == "enumerate"
        eff_depth = min(5, max(0, depth))
        item_num = 0
        in_item = False
        cur_opt = ""
        cur_s: int | None = None
        cur_e: int | None = None

        def _flush_item() -> None:
            nonlocal cur_s, cur_e, cur_opt
            if not in_item or cur_s is None or cur_e is None or cur_e <= cur_s:
                cur_s = None
                cur_e = None
                cur_opt = ""
                return
            seg = masked[cur_s:cur_e]
            lt = len(seg) - len(seg.lstrip())
            rt = len(seg) - len(seg.rstrip())
            is_s = cur_s + lt
            is_e = cur_e - rt
            if is_s < is_e:
                lead = (
                    f"⟦B⟧{normalize_latex_inline(cur_opt, keep_bold_markers=False, prose_macros=prose_macros)}⟦/B⟧: "
                    if cur_opt
                    else ""
                )
                clean = lead + normalize_latex_inline(
                    masked[is_s:is_e], prose_macros=prose_macros, footnotes_out=doc_footnotes
                )
                if clean.strip():
                    blocks.append(
                        DocumentBlock(
                            index=len(blocks),
                            block_type="list",
                            section_title=current_section,
                            section_level=current_level,
                            raw_text=content[is_s:is_e],
                            clean_text=clean,
                            raw_start=is_s,
                            raw_end=is_e,
                            zone=forced_zone or current_zone,
                            source_anchor={"kind": "latex_span", "start": is_s, "end": is_e},
                            meta={"ordered": is_ordered, "item_num": item_num, "depth": eff_depth},
                        )
                    )
            cur_s = None
            cur_e = None
            cur_opt = ""

        for ch in env_node.nodelist or []:
            if ch is None or isinstance(ch, LatexCommentNode):
                continue
            c_s = body_start + ch.pos
            c_e = c_s + ch.len
            if isinstance(ch, LatexMacroNode) and ch.macroname == "item":
                _flush_item()
                in_item = True
                item_num += 1
                m_opt = re.match(r"\\item\s*\[([^\]]*)\]", masked[c_s:c_e])
                cur_opt = m_opt.group(1) if m_opt else ""
                continue
            if isinstance(ch, LatexEnvironmentNode) and ch.environmentname in LIST_ENVS:
                _flush_item()
                _walk_list_env(ch, depth=depth + 1, forced_zone=forced_zone)
                continue
            if in_item:
                if cur_s is None:
                    cur_s = c_s
                cur_e = c_e

        _flush_item()

    def _walk_nodes(
        nodes: list[Any],
        forced_zone: str | None = None,
        style_ctx: dict[str, Any] | None = None,
    ) -> None:
        nonlocal prose_buf_start, prose_buf_end, prose_buf_style_ctx, current_section, current_level, current_zone
        nonlocal eq_counter, fig_counter, tab_counter, alg_counter, sec_counter, last_section_label_target

        for node in nodes:
            if node is None:
                continue
            abs_s = body_start + node.pos
            abs_e = abs_s + node.len

            if isinstance(node, LatexCommentNode):
                continue

            # Display math nodes ($$ ... $$ or \[ ... \])
            if isinstance(node, LatexMathNode) and node.displaytype == "display":
                _flush_prose(forced_zone)
                raw_math = content[abs_s:abs_e].strip()
                lbl_m = re.search(r"\\label\{([^}]+)\}", masked[abs_s:abs_e])
                lbl = lbl_m.group(1).strip() if lbl_m else ""
                inner_clean = _clean_latex_display_math(masked[abs_s:abs_e])
                if inner_clean:
                    blocks.append(
                        DocumentBlock(
                            index=len(blocks),
                            block_type="math",
                            section_title=current_section,
                            section_level=current_level,
                            raw_text=raw_math,
                            clean_text=f"⟦MATH:{inner_clean}⟧",
                            raw_start=abs_s,
                            raw_end=abs_e,
                            zone=forced_zone or current_zone,
                            source_anchor={"kind": "latex_span", "start": abs_s, "end": abs_e},
                            meta={"label": lbl, "eq_number": None},
                        )
                    )
                continue

            # Structural macros
            if isinstance(node, LatexMacroNode):
                mname = node.macroname
                if mname in ZONE_MACROS:
                    _flush_prose(forced_zone)
                    if mname == "frontmatter":
                        current_zone = "frontmatter"
                    elif mname == "mainmatter":
                        current_zone = "body"
                    elif mname == "backmatter":
                        current_zone = "backmatter"
                    continue

                if mname in BOILERPLATE_MACROS:
                    _flush_prose(forced_zone)
                    continue

                if mname in BIB_MACROS:
                    _flush_prose(forced_zone)
                    if not has_emitted_refs:
                        if bbl_content:
                            ref_items = [(k, txt, None) for k, txt in _parse_thebibliography_items(bbl_content)]
                            _emit_reference_items(ref_items)
                        elif bib_entries:
                            cited_order: list[str] = []
                            seen_keys: set[str] = set()
                            for blk in blocks:
                                for cm in re.finditer(r"⟦CITE:([^⟧]+)⟧", blk.clean_text):
                                    for ck in cm.group(1).split(","):
                                        ck = ck.strip()
                                        if ck and ck in bib_entries and ck not in seen_keys:
                                            seen_keys.add(ck)
                                            cited_order.append(ck)
                            for k in bib_entries:
                                if k not in seen_keys:
                                    cited_order.append(k)
                            synth = [
                                (k, format_bib_entry_text(k, bib_entries[k]), bib_entries[k])
                                for k in cited_order
                            ]
                            _emit_reference_items(synth)
                    continue

                if mname in SECTION_MACROS:
                    _flush_prose(forced_zone)
                    # Extract title argument inner span precisely
                    sec_src = masked[abs_s:abs_e]
                    b_pos = sec_src.find("{")
                    if b_pos != -1:
                        grp = _extract_brace_group(masked, abs_s + b_pos)
                        if grp:
                            inner_s = abs_s + b_pos + 1
                            inner_e = grp[1] - 1
                            sec_clean = normalize_latex_inline(grp[0], keep_bold_markers=False, prose_macros=prose_macros)
                            sec_plain = _strip_inline_markers_fast(sec_clean).strip()
                            if _BACKMATTER_HEADING_RE.match(sec_plain):
                                current_zone = "backmatter"
                            elif current_zone == "frontmatter" and _BODY_START_HEADING_RE.match(sec_plain):
                                current_zone = "body"
                            lvl = 4 if mname == "paragraph" else level_map.get(mname, 1)
                            if mname != "paragraph":
                                current_section = sec_plain or current_section
                                current_level = lvl
                                sec_counter += 1
                                last_section_label_target = f"Sec. {sec_counter}"
                            # Check for \label inside section title itself
                            lm_in = re.search(r"\\label\{([^}]+)\}", grp[0])
                            sec_lbl = lm_in.group(1).strip() if lm_in else ""
                            if sec_lbl:
                                label_map[sec_lbl] = last_section_label_target or sec_plain
                            blocks.append(
                                DocumentBlock(
                                    index=len(blocks),
                                    block_type="heading",
                                    section_title=current_section,
                                    section_level=lvl,
                                    raw_text=content[inner_s:inner_e].strip(),
                                    clean_text=sec_clean,
                                    raw_start=inner_s,
                                    raw_end=inner_e,
                                    zone=forced_zone or current_zone,
                                    source_anchor={"kind": "latex_span", "start": inner_s, "end": inner_e},
                                    meta={"label": sec_lbl} if sec_lbl else {},
                                )
                            )
                    continue

                # Non-structural inline macro -> stays in prose buffer!
                if prose_buf_start is None:
                    prose_buf_start = abs_s
                    prose_buf_style_ctx = style_ctx
                prose_buf_end = abs_e
                continue

            # Structural Environments
            if isinstance(node, LatexEnvironmentNode):
                env = node.environmentname

                # Wrapper environments: propagate alignment/quote style_ctx while recursing into children!
                if env in _LATEX_WRAPPER_ENV_ARGS and env != "titlepage":
                    _flush_prose(forced_zone, style_ctx)
                    child_ctx = dict(style_ctx or {})
                    if env == "center":
                        child_ctx["align"] = "center"
                    elif env == "flushright":
                        child_ctx["align"] = "right"
                    elif env == "flushleft":
                        child_ctx["align"] = "left"
                    elif env in ("quote", "quotation"):
                        child_ctx["quote_depth"] = min(4, int(child_ctx.get("quote_depth", 0)) + 1)
                        child_ctx["left_indent_em"] = max(1.5, float(child_ctx.get("left_indent_em", 0.0)))
                        child_ctx["right_indent_em"] = max(1.5, float(child_ctx.get("right_indent_em", 0.0)))
                    _walk_nodes(node.nodelist or [], forced_zone=forced_zone, style_ctx=child_ctx or None)
                    _flush_prose(forced_zone, child_ctx or None)
                    continue

                if env == "titlepage":
                    _flush_prose(forced_zone, style_ctx)
                    _walk_nodes(node.nodelist or [], forced_zone="frontmatter")
                    _flush_prose("frontmatter")
                    continue

                if env == "abstract":
                    _flush_prose(forced_zone, style_ctx)
                    current_section = "Abstract"
                    current_level = 1
                    current_zone = "body"
                    blocks.append(
                        DocumentBlock(
                            index=len(blocks),
                            block_type="heading",
                            section_title="Abstract",
                            section_level=1,
                            raw_text="Abstract",
                            clean_text="Abstract",
                            zone="body",
                        )
                    )
                    abs_ctx = {**(style_ctx or {}), "semantic_role": "abstract"}
                    _walk_nodes(node.nodelist or [], forced_zone="body", style_ctx=abs_ctx)
                    _flush_prose("body", abs_ctx)
                    continue

                if env == "thebibliography":
                    _flush_prose(forced_zone)
                    ref_items = [(k, txt, None) for k, txt in _parse_thebibliography_items(masked[abs_s:abs_e])]
                    _emit_reference_items(ref_items, raw_start=abs_s, raw_end=abs_e)
                    continue

                if env in MATH_ENVS:
                    _flush_prose(forced_zone)
                    is_numbered = not env.endswith("*")
                    if is_numbered:
                        eq_counter += 1
                    env_src = masked[abs_s:abs_e]
                    lbl_m = re.search(r"\\label\{([^}]+)\}", env_src)
                    lbl = lbl_m.group(1).strip() if lbl_m else ""
                    if lbl and is_numbered:
                        label_map[lbl] = f"Eq. ({eq_counter})"
                    inner_clean = _clean_latex_display_math(env_src, env_name=env.rstrip("*"))
                    blocks.append(
                        DocumentBlock(
                            index=len(blocks),
                            block_type="math",
                            section_title=current_section,
                            section_level=current_level,
                            raw_text=content[abs_s:abs_e].strip(),
                            clean_text=f"⟦MATH:{inner_clean}⟧",
                            raw_start=abs_s,
                            raw_end=abs_e,
                            zone=forced_zone or current_zone,
                            source_anchor={"kind": "latex_span", "start": abs_s, "end": abs_e},
                            meta={"label": lbl, "eq_number": eq_counter if is_numbered else None},
                        )
                    )
                    continue

                if env in LIST_ENVS:
                    _flush_prose(forced_zone, style_ctx)
                    _walk_list_env(node, depth=0, forced_zone=forced_zone)
                    continue

                if env in THEOREM_ENVS:
                    _flush_prose(forced_zone)
                    env_src = masked[abs_s:abs_e]
                    thm_title = theorem_titles.get(env, env.capitalize())
                    is_proof = env == "proof"
                    thm_num = None
                    if not is_proof:
                        thm_counters[env] = thm_counters.get(env, 0) + 1
                        thm_num = thm_counters[env]
                    m_open = re.match(rf"\\begin\{{{re.escape(env)}\}}\s*(?:\[([^\]]*)\])?", env_src)
                    opt_title = normalize_latex_inline(m_open.group(1), keep_bold_markers=False, prose_macros=prose_macros) if (m_open and m_open.group(1)) else ""
                    inner_rel_s = m_open.end() if m_open else 0
                    m_close = re.search(rf"\\end\{{{re.escape(env)}\}}\s*$", env_src)
                    inner_rel_e = m_close.start() if m_close else len(env_src)
                    inner_abs_s = abs_s + inner_rel_s
                    inner_abs_e = abs_s + inner_rel_e
                    lbl_m = re.search(r"\\label\{([^}]+)\}", env_src[inner_rel_s:inner_rel_e])
                    lbl = lbl_m.group(1).strip() if lbl_m else ""
                    if lbl and thm_num is not None:
                        label_map[lbl] = f"{thm_title} {thm_num}"
                    clean_thm = normalize_latex_inline(
                        masked[inner_abs_s:inner_abs_e],
                        prose_macros=prose_macros,
                        footnotes_out=doc_footnotes,
                    )
                    if clean_thm:
                        blocks.append(
                            DocumentBlock(
                                index=len(blocks),
                                block_type="theorem",
                                section_title=current_section,
                                section_level=current_level,
                                raw_text=content[inner_abs_s:inner_abs_e].strip(),
                                clean_text=clean_thm,
                                raw_start=inner_abs_s,
                                raw_end=inner_abs_e,
                                zone=forced_zone or current_zone,
                                source_anchor={"kind": "latex_span", "start": inner_abs_s, "end": inner_abs_e},
                                meta={
                                    "theorem_env": env,
                                    "theorem_title": thm_title,
                                    "theorem_num": thm_num,
                                    "optional_title": opt_title,
                                    "label": lbl,
                                    "is_proof": is_proof,
                                },
                            )
                        )
                    continue

                if env in ALG_ENVS:
                    _flush_prose(forced_zone)
                    alg_counter += 1
                    alg_src = masked[abs_s:abs_e]
                    cap_m = re.search(r"\\caption\s*(?:\[[^\]]*\])?\s*\{", alg_src)
                    cap_clean = ""
                    if cap_m:
                        g_c = _extract_brace_group(alg_src, cap_m.end() - 1)
                        if g_c:
                            cap_clean = normalize_latex_inline(g_c[0], keep_bold_markers=False, prose_macros=prose_macros)
                    lbl_m = re.search(r"\\label\{([^}]+)\}", alg_src)
                    lbl = lbl_m.group(1).strip() if lbl_m else ""
                    if lbl:
                        label_map[lbl] = f"Algorithm {alg_counter}"
                    alg_lines = _parse_algorithmic_lines(alg_src, prose_macros=prose_macros)
                    blocks.append(
                        DocumentBlock(
                            index=len(blocks),
                            block_type="algorithm",
                            section_title=current_section,
                            section_level=current_level,
                            raw_text=content[abs_s:abs_e].strip(),
                            clean_text="\n".join(ln["text"] for ln in alg_lines) or cap_clean,
                            raw_start=abs_s,
                            raw_end=abs_e,
                            zone=forced_zone or current_zone,
                            source_anchor={"kind": "latex_span", "start": abs_s, "end": abs_e},
                            meta={
                                "alg_num": alg_counter,
                                "caption": cap_clean,
                                "label": lbl,
                                "lines": alg_lines,
                            },
                        )
                    )
                    continue

                if env in CODE_ENVS:
                    _flush_prose(forced_zone)
                    code_src = content[abs_s:abs_e]
                    lang = ""
                    if env == "minted":
                        mm = re.match(r"\\begin\{minted\}(?:\[[^\]]*\])?\{([^}]+)\}", code_src)
                        if mm:
                            lang = mm.group(1).strip().lower()
                    elif env == "lstlisting":
                        lm = re.search(r"language\s*=\s*([A-Za-z0-9_+#]+)", code_src[:200])
                        if lm:
                            lang = lm.group(1).strip().lower()
                    inner = re.sub(rf"^\\begin\{{{re.escape(env)}\}}(?:\[[^\]]*\])?(?:\{{[^}}]*\}})?", "", code_src, count=1)
                    inner = re.sub(rf"\\end\{{{re.escape(env)}\}}\s*$", "", inner).strip("\n")
                    blocks.append(
                        DocumentBlock(
                            index=len(blocks),
                            block_type="code",
                            section_title=current_section,
                            section_level=current_level,
                            raw_text=code_src,
                            clean_text=inner,
                            raw_start=abs_s,
                            raw_end=abs_e,
                            zone=forced_zone or current_zone,
                            source_anchor={"kind": "latex_span", "start": abs_s, "end": abs_e},
                            meta={"lang": lang, "is_diagram": False},
                        )
                    )
                    continue

                if env in FLOAT_ENVS:
                    _flush_prose(forced_zone)
                    float_src = masked[abs_s:abs_e]
                    is_fig = env.rstrip("*") in ("figure", "sidewaysfigure")
                    outer_src = (
                        re.sub(
                            r"\\begin\{subfigure\}[\s\S]*?\\end\{subfigure\}",
                            lambda m: " " * len(m.group(0)),
                            float_src,
                        )
                        if is_fig
                        else float_src
                    )
                    lbl_m = re.search(r"\\label\{([^}]+)\}", outer_src) or re.search(r"\\label\{([^}]+)\}", float_src)
                    lbl = lbl_m.group(1).strip() if lbl_m else ""

                    if is_fig:
                        fig_counter += 1
                        if lbl:
                            label_map[lbl] = f"Fig. {fig_counter}"
                        # Collect all subfigures / includegraphics images!
                        images_list: list[dict[str, Any]] = []
                        subfig_matches = list(re.finditer(r"\\begin\{subfigure\}[\s\S]*?\\end\{subfigure\}", float_src))
                        if subfig_matches:
                            for sfm in subfig_matches:
                                sf_src = sfm.group(0)
                                im = re.search(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}", sf_src)
                                ip = im.group(1).strip() if im else ""
                                ak = _resolve_asset_key(ip, asset_map)
                                sc_m = re.search(r"\\caption\s*(?:\[[^\]]*\])?\s*\{", sf_src)
                                subcap = ""
                                if sc_m:
                                    g_sc = _extract_brace_group(sf_src, sc_m.end() - 1)
                                    if g_sc:
                                        subcap = normalize_latex_inline(g_sc[0], prose_macros=prose_macros)
                                sl_m = re.search(r"\\label\{([^}]+)\}", sf_src)
                                sublbl = sl_m.group(1).strip() if sl_m else ""
                                if sublbl:
                                    label_map[sublbl] = f"Fig. {fig_counter}{chr(97 + len(images_list))}"
                                if ip or ak:
                                    images_list.append(
                                        {"image_path": ip, "asset_key": ak, "subcaption": subcap, "label": sublbl}
                                    )
                        else:
                            for im in re.finditer(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}", float_src):
                                ip = im.group(1).strip()
                                ak = _resolve_asset_key(ip, asset_map)
                                images_list.append({"image_path": ip, "asset_key": ak, "subcaption": "", "label": ""})

                        # Find outer figure caption (subfigures already masked in outer_src)
                        cap_m = re.search(r"\\caption\s*(?:\[[^\]]*\])?\s*\{", outer_src)
                        cap_clean = ""
                        cap_raw = ""
                        cap_s = None
                        cap_e = None
                        if cap_m:
                            c_brace = cap_m.end() - 1
                            grp = _extract_brace_group(float_src, c_brace)
                            if grp:
                                cap_s = abs_s + c_brace + 1
                                cap_e = abs_s + grp[1] - 1
                                cap_raw = content[cap_s:cap_e].strip()
                                cap_clean = normalize_latex_inline(grp[0], prose_macros=prose_macros)

                        first_img = images_list[0] if images_list else {"image_path": "", "asset_key": None}
                        if images_list or cap_clean:
                            prefix = f"[Figure {fig_counter}{(' ' + lbl) if lbl else ''}] "
                            blocks.append(
                                DocumentBlock(
                                    index=len(blocks),
                                    block_type="figure",
                                    section_title=current_section,
                                    section_level=current_level,
                                    raw_text=cap_raw or content[abs_s:abs_e],
                                    clean_text=(prefix + cap_clean).strip(),
                                    raw_start=cap_s,
                                    raw_end=cap_e,
                                    zone=forced_zone or current_zone,
                                    source_anchor=(
                                        {"kind": "latex_span", "start": cap_s, "end": cap_e}
                                        if cap_s is not None and cap_e is not None
                                        else None
                                    ),
                                    meta={
                                        "env": "figure",
                                        "fig_num": fig_counter,
                                        "label": lbl,
                                        "image_path": first_img["image_path"],
                                        "asset_key": first_img["asset_key"],
                                        "images": images_list,
                                    },
                                )
                            )
                    else:
                        tab_counter += 1
                        if lbl:
                            label_map[lbl] = f"Table {tab_counter}"
                        cap_m = re.search(r"\\caption\s*(?:\[[^\]]*\])?\s*\{", float_src)
                        if cap_m:
                            c_brace = cap_m.end() - 1
                            grp = _extract_brace_group(float_src, c_brace)
                            if grp:
                                cap_s = abs_s + c_brace + 1
                                cap_e = abs_s + grp[1] - 1
                                cap_clean = normalize_latex_inline(grp[0], prose_macros=prose_macros)
                                prefix = f"[Table {tab_counter}{(' ' + lbl) if lbl else ''}] "
                                blocks.append(
                                    DocumentBlock(
                                        index=len(blocks),
                                        block_type="caption",
                                        section_title=current_section,
                                        section_level=current_level,
                                        raw_text=content[cap_s:cap_e].strip(),
                                        clean_text=prefix + cap_clean,
                                        raw_start=cap_s,
                                        raw_end=cap_e,
                                        zone=forced_zone or current_zone,
                                        source_anchor={"kind": "latex_span", "start": cap_s, "end": cap_e},
                                        meta={"env": "table", "tab_num": tab_counter, "label": lbl},
                                    )
                                )

                        # Extract optional threeparttable tablenotes
                        tn_notes: list[str] = []
                        tn_m = re.search(r"\\begin\{tablenotes\}(?:\[[^\]]*\])?([\s\S]*?)\\end\{tablenotes\}", float_src)
                        if tn_m:
                            for it_m in re.finditer(r"\\item(?:\[([^\]]*)\])?\s*([\s\S]*?)(?=\\item\b|$)", tn_m.group(1)):
                                tag_s = f"{it_m.group(1)} " if it_m.group(1) else ""
                                note_c = normalize_latex_inline(it_m.group(2), prose_macros=prose_macros)
                                if note_c:
                                    tn_notes.append((tag_s + note_c).strip())

                        tab_m = re.search(
                            r"\\begin\{(?:tabular\*?|tabularx|longtable)\}[\s\S]*?\\end\{(?:tabular\*?|tabularx|longtable)\}",
                            float_src,
                        )
                        if tab_m:
                            ts = abs_s + tab_m.start()
                            te = abs_s + tab_m.end()
                            rows, cell_spans, aligns = _parse_latex_tabular_rows(
                                tab_m.group(0),
                                base_offset=ts,
                                prose_macros=prose_macros,
                            )
                            if rows:
                                clean_tbl = "\n".join(" | ".join(c["text"] for c in r) for r in rows)
                                tbl_meta: dict[str, Any] = {
                                    "rows": rows,
                                    "alignments": aligns,
                                    "label": lbl,
                                    "tab_num": tab_counter,
                                    "table_role": "data_table",
                                }
                                if tn_notes:
                                    tbl_meta["table_notes"] = tn_notes
                                blocks.append(
                                    DocumentBlock(
                                        index=len(blocks),
                                        block_type="table",
                                        section_title=current_section,
                                        section_level=current_level,
                                        raw_text=content[ts:te],
                                        clean_text=clean_tbl,
                                        raw_start=ts,
                                        raw_end=te,
                                        zone=forced_zone or current_zone,
                                        source_anchor={
                                            "kind": "latex_table",
                                            "start": ts,
                                            "end": te,
                                            "cell_spans": cell_spans,
                                        },
                                        meta=tbl_meta,
                                    )
                                )
                    continue

                if env in TABULAR_ENVS:
                    _flush_prose(forced_zone)
                    rows, cell_spans, aligns = _parse_latex_tabular_rows(
                        masked[abs_s:abs_e],
                        base_offset=abs_s,
                        prose_macros=prose_macros,
                    )
                    if rows:
                        is_meta = _is_metadata_form_table(rows, borderless=True)
                        clean_tbl = "\n".join(" | ".join(c["text"] for c in r) for r in rows)
                        blocks.append(
                            DocumentBlock(
                                index=len(blocks),
                                block_type="table",
                                section_title="封面信息" if is_meta else current_section,
                                section_level=current_level,
                                raw_text=content[abs_s:abs_e],
                                clean_text=clean_tbl,
                                raw_start=abs_s,
                                raw_end=abs_e,
                                zone="frontmatter" if (is_meta or forced_zone == "frontmatter") else (forced_zone or current_zone),
                                source_anchor={
                                    "kind": "latex_table",
                                    "start": abs_s,
                                    "end": abs_e,
                                    "cell_spans": cell_spans,
                                },
                                meta={
                                    "rows": rows,
                                    "alignments": aligns,
                                    "label": "",
                                    "table_role": "metadata_form" if is_meta else "data_table",
                                },
                            )
                        )
                    continue

                # Any other environment -> keep as prose or recurse if it has subnodes
                if prose_buf_start is None:
                    prose_buf_start = abs_s
                    prose_buf_style_ctx = style_ctx
                prose_buf_end = abs_e
                continue

            # Regular chars, inline math, groups, specials -> accumulate in prose buffer!
            if prose_buf_start is None:
                prose_buf_start = abs_s
                prose_buf_style_ctx = style_ctx
            prose_buf_end = abs_e

        _flush_prose(forced_zone, style_ctx)

    _walk_nodes(nodelist)

    # Resolve cross-references ⟦REF:label⟧ -> ⟦REF:label|Display⟧ without duplicating preceding type words!
    # e.g., "Theorem~⟦REF:thm:1⟧" -> "Theorem ⟦REF:thm:1|1⟧", bare "⟦REF:thm:1⟧" -> "⟦REF:thm:1|Theorem 1⟧"
    if label_map:
        _PRECEDING_REF_TYPE_RE = re.compile(
            r"(?:Fig(?:ure)?s?\.?|Tab(?:le)?s?\.?|Eq(?:uation)?s?\.?|Sec(?:tion)?s?\.?|"
            r"Theorem|Lemma|Proposition|Corollary|Definition|Remark|Algorithm|Alg\.?|"
            r"图|表|公式|式|定理|引理|算法|第)\s*$",
            re.IGNORECASE,
        )

        def _resolve_refs_in_text(text_in: str) -> str:
            if "⟦REF:" not in text_in:
                return text_in
            out_parts: list[str] = []
            last_end = 0
            for m in re.finditer(r"⟦REF:([^|⟧]+)⟧", text_in):
                out_parts.append(text_in[last_end : m.start()])
                lbl_k = m.group(1).strip()
                disp = label_map.get(lbl_k)
                if disp:
                    prefix_ctx = text_in[max(0, m.start() - 24) : m.start()]
                    if _PRECEDING_REF_TYPE_RE.search(prefix_ctx):
                        # Extract just the number/tag (e.g. "(1)" from "Eq. (1)", "1" from "Theorem 1")
                        m_num = re.search(r"(\([^)]+\)|\d+[a-zA-Z]?)\s*$", disp)
                        short_disp = m_num.group(1) if m_num else disp
                        out_parts.append(f"⟦REF:{lbl_k}|{short_disp}⟧")
                    else:
                        out_parts.append(f"⟦REF:{lbl_k}|{disp}⟧")
                else:
                    out_parts.append(m.group(0))
                last_end = m.end()
            out_parts.append(text_in[last_end:])
            return "".join(out_parts)

        for blk in blocks:
            if "⟦REF:" in blk.clean_text:
                blk.clean_text = _resolve_refs_in_text(blk.clean_text)
            if blk.block_type == "table" and isinstance(blk.meta.get("rows"), list):
                for row in blk.meta["rows"]:
                    for cell in row:
                        ct = cell.get("text", "")
                        if "⟦REF:" in ct:
                            cell["text"] = _resolve_refs_in_text(ct)

    classified = _classify_document_zones(blocks, allow_h1_title_promote=False)
    doc_meta = {
        "latex_macros": katex_macros,
        "footnotes": doc_footnotes,
        "label_map": label_map,
    }
    if classified:
        if katex_macros:
            classified[0].meta["doc_latex_macros"] = katex_macros
        if doc_footnotes:
            classified[0].meta["doc_footnotes"] = doc_footnotes
        if label_map:
            classified[0].meta["doc_label_map"] = label_map
    return classified, doc_meta


def parse_latex_document(
    content: str,
    asset_map: dict[str, str] | None = None,
    bib_entries: dict[str, Any] | None = None,
    bbl_content: str | None = None,
) -> list[DocumentBlock]:
    blocks, _ = parse_latex_with_meta(
        content,
        asset_map=asset_map,
        bib_entries=bib_entries,
        bbl_content=bbl_content,
    )
    return blocks
