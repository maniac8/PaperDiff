"""Pure-Python converter from Word OMML (<m:oMath> / <m:oMathPara>) XML to LaTeX,
plus Unicode superscript/subscript helpers for rich Word text runs.
"""
from __future__ import annotations

import re
from typing import Any

M_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"

_UNICODE_TO_LATEX: dict[str, str] = {
    "×": r"\times ",
    "÷": r"\div ",
    "±": r"\pm ",
    "∓": r"\mp ",
    "·": r"\cdot ",
    "∙": r"\cdot ",
    "⋅": r"\cdot ",
    "≤": r"\le ",
    "≥": r"\ge ",
    "≠": r"\ne ",
    "≈": r"\approx ",
    "≡": r"\equiv ",
    "∼": r"\sim ",
    "∝": r"\propto ",
    "∞": r"\infty ",
    "∂": r"\partial ",
    "∇": r"\nabla ",
    "∑": r"\sum ",
    "∏": r"\prod ",
    "∫": r"\int ",
    "∬": r"\iint ",
    "∭": r"\iiint ",
    "∮": r"\oint ",
    "√": r"\sqrt ",
    "→": r"\to ",
    "←": r"\leftarrow ",
    "↔": r"\leftrightarrow ",
    "⇒": r"\Rightarrow ",
    "⇐": r"\Leftarrow ",
    "⇔": r"\Leftrightarrow ",
    "∈": r"\in ",
    "∉": r"\notin ",
    "⊂": r"\subset ",
    "⊆": r"\subseteq ",
    "∪": r"\cup ",
    "∩": r"\cap ",
    "∅": r"\emptyset ",
    "∀": r"\forall ",
    "∃": r"\exists ",
    "°": r"^\circ ",
    "−": "-",
    "–": "-",
    "—": "-",
    "′": "'",
    "″": "''",
    "…": r"\dots ",
    "⋯": r"\cdots ",
    "α": r"\alpha ",
    "β": r"\beta ",
    "γ": r"\gamma ",
    "δ": r"\delta ",
    "ε": r"\varepsilon ",
    "ϵ": r"\epsilon ",
    "ζ": r"\zeta ",
    "η": r"\eta ",
    "θ": r"\theta ",
    "ϑ": r"\vartheta ",
    "ι": r"\iota ",
    "κ": r"\kappa ",
    "λ": r"\lambda ",
    "μ": r"\mu ",
    "µ": r"\mu ",
    "ν": r"\nu ",
    "ξ": r"\xi ",
    "π": r"\pi ",
    "ρ": r"\rho ",
    "ϱ": r"\varrho ",
    "σ": r"\sigma ",
    "ς": r"\varsigma ",
    "τ": r"\tau ",
    "υ": r"\upsilon ",
    "φ": r"\varphi ",
    "ϕ": r"\phi ",
    "χ": r"\chi ",
    "ψ": r"\psi ",
    "ω": r"\omega ",
    "Γ": r"\Gamma ",
    "Δ": r"\Delta ",
    "Θ": r"\Theta ",
    "Λ": r"\Lambda ",
    "Ξ": r"\Xi ",
    "Π": r"\Pi ",
    "Σ": r"\Sigma ",
    "Υ": r"\Upsilon ",
    "Φ": r"\Phi ",
    "Ψ": r"\Psi ",
    "Ω": r"\Omega ",
    "Ω": r"\Omega ",
    "ℝ": r"\mathbb{R}",
    "ℕ": r"\mathbb{N}",
    "ℤ": r"\mathbb{Z}",
    "ℂ": r"\mathbb{C}",
    "ℚ": r"\mathbb{Q}",
    "𝔼": r"\mathbb{E}",
}

_KNOWN_FUNCS = {
    "sin", "cos", "tan", "cot", "sec", "csc",
    "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh",
    "log", "ln", "exp", "lim", "limsup", "liminf",
    "max", "min", "sup", "inf", "arg", "det", "dim", "gcd", "Pr", "mod",
}

_ACCENT_MAP: dict[str, str] = {
    "\u0302": r"\hat",
    "^": r"\hat",
    "\u0304": r"\bar",
    "\u00af": r"\bar",
    "\u20d7": r"\vec",
    "→": r"\vec",
    "\u0303": r"\tilde",
    "~": r"\tilde",
    "\u0307": r"\dot",
    "\u0308": r"\ddot",
    "\u0301": r"\acute",
    "\u0300": r"\grave",
    "\u0306": r"\breve",
    "\u030c": r"\check",
}

_NARY_MAP: dict[str, str] = {
    "∑": r"\sum",
    "∏": r"\prod",
    "∐": r"\coprod",
    "∫": r"\int",
    "∬": r"\iint",
    "∭": r"\iiint",
    "∮": r"\oint",
    "⋃": r"\bigcup",
    "⋂": r"\bigcap",
    "⋁": r"\bigvee",
    "⋀": r"\bigwedge",
    "⨁": r"\bigoplus",
    "⨂": r"\bigotimes",
}

_DELIM_ESCAPE = {
    "{": r"\{",
    "}": r"\}",
    "|": r"|",
    "‖": r"\|",
    "⟨": r"\langle ",
    "⟩": r"\rangle ",
    "⌊": r"\lfloor ",
    "⌋": r"\rfloor ",
    "⌈": r"\lceil ",
    "⌉": r"\rceil ",
    "": ".",
}

SUP_CHAR_MAP = str.maketrans(
    "0123456789+-=()nijkabcmrtxy,",
    "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱʲᵏᵃᵇᶜᵐʳᵗˣʸ˒",
)
SUB_CHAR_MAP = str.maketrans(
    "0123456789+-=()aehijklmnoprstuvx,",
    "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ,",
)


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _mval(el: Any, prop_tag: str, default: str = "") -> str:
    if el is None:
        return default
    node = el.find(f"{M_NS}{prop_tag}")
    if node is None:
        return default
    return node.get(f"{M_NS}val", default)


def _escape_math_text(raw: str) -> str:
    out: list[str] = []
    for ch in raw:
        if ch in _UNICODE_TO_LATEX:
            out.append(_UNICODE_TO_LATEX[ch])
        elif ch in ("%", "&", "#", "$"):
            out.append("\\" + ch)
        elif ch == "\u2061":
            continue
        elif ch == "\u00a0":
            out.append(r"\ ")
        else:
            out.append(ch)
    return "".join(out)


def _convert_children(elem: Any) -> str:
    if elem is None:
        return ""
    return "".join(_convert_node(child) for child in elem)


def _convert_node(elem: Any) -> str:
    name = _local(elem.tag)

    if name in ("oMath", "oMathPara", "e", "num", "den", "sub", "sup", "deg", "fName", "lim", "box", "borderBox", "phant"):
        if name == "oMathPara":
            parts = [_convert_node(ch) for ch in elem if _local(ch.tag) == "oMath"]
            if len(parts) > 1:
                return r"\begin{aligned} " + r" \\ ".join(p.strip() for p in parts if p.strip()) + r" \end{aligned}"
            return parts[0] if parts else _convert_children(elem)
        return _convert_children(elem)

    if name in (
        "rPr", "ctrlPr", "fPr", "sSupPr", "sSubPr", "sSubSupPr", "sPrePr", "radPr", "naryPr", "dPr", "mPr",
        "funcPr", "accPr", "barPr", "limLowPr", "limUppPr", "eqArrPr", "oMathParaPr", "groupChrPr",
        "boxPr", "borderBoxPr", "phantPr", "argPr",
    ):
        return ""

    if name == "r":
        texts = [t.text or "" for t in elem.findall(f"{M_NS}t")]
        raw = "".join(texts)
        if not raw:
            return ""
        rpr = elem.find(f"{M_NS}rPr")
        sty = _mval(rpr, "sty", "")
        scr = _mval(rpr, "scr", "")
        nor = rpr is not None and rpr.find(f"{M_NS}nor") is not None
        converted = _escape_math_text(raw)
        if nor and re.search(r"[A-Za-z\u4e00-\u9fff]", raw):
            safe_txt = raw.replace("\\", r"\backslash ").replace("{", r"\{").replace("}", r"\}")
            return rf"\mathrm{{{safe_txt}}}" if re.fullmatch(r"[A-Za-z0-9\s.,+\-:/%()]+", raw) else rf"\text{{{safe_txt}}}"
        if scr == "double-struck" and re.fullmatch(r"[A-Za-z0-9]+", raw):
            return rf"\mathbb{{{converted}}}"
        if scr == "script" and re.fullmatch(r"[A-Za-z]+", raw):
            return rf"\mathcal{{{converted}}}"
        if sty == "b" and re.fullmatch(r"[A-Za-z0-9]+", raw):
            return rf"\mathbf{{{converted}}}"
        if sty == "p" and len(raw) > 1 and re.fullmatch(r"[A-Za-z0-9]+", raw):
            return rf"\mathrm{{{converted}}}"
        return converted

    if name == "t":
        return _escape_math_text(elem.text or "")

    if name == "f":
        fpr = elem.find(f"{M_NS}fPr")
        ftype = _mval(fpr, "type", "bar")
        num = _convert_children(elem.find(f"{M_NS}num")).strip()
        den = _convert_children(elem.find(f"{M_NS}den")).strip()
        if ftype == "lin":
            return f"({num})/({den})"
        if ftype == "noBar":
            return rf"\binom{{{num}}}{{{den}}}"
        return rf"\dfrac{{{num}}}{{{den}}}"

    if name == "sSup":
        base = _convert_children(elem.find(f"{M_NS}e")).strip()
        sup = _convert_children(elem.find(f"{M_NS}sup")).strip()
        return f"{{{base}}}^{{{sup}}}" if len(base) > 1 else f"{base}^{{{sup}}}"

    if name == "sSub":
        base = _convert_children(elem.find(f"{M_NS}e")).strip()
        sub = _convert_children(elem.find(f"{M_NS}sub")).strip()
        return f"{{{base}}}_{{{sub}}}" if len(base) > 1 else f"{base}_{{{sub}}}"

    if name == "sSubSup":
        base = _convert_children(elem.find(f"{M_NS}e")).strip()
        sub = _convert_children(elem.find(f"{M_NS}sub")).strip()
        sup = _convert_children(elem.find(f"{M_NS}sup")).strip()
        b = f"{{{base}}}" if len(base) > 1 else base
        return f"{b}_{{{sub}}}^{{{sup}}}"

    if name == "sPre":
        base = _convert_children(elem.find(f"{M_NS}e")).strip()
        sub = _convert_children(elem.find(f"{M_NS}sub")).strip()
        sup = _convert_children(elem.find(f"{M_NS}sup")).strip()
        return f"{{}}_{{{sub}}}^{{{sup}}}{{{base}}}"

    if name == "rad":
        deg = _convert_children(elem.find(f"{M_NS}deg")).strip()
        body = _convert_children(elem.find(f"{M_NS}e")).strip()
        if deg:
            return rf"\sqrt[{deg}]{{{body}}}"
        return rf"\sqrt{{{body}}}"

    if name == "nary":
        npr = elem.find(f"{M_NS}naryPr")
        chr_val = _mval(npr, "chr", "∫")
        op = _NARY_MAP.get(chr_val, _UNICODE_TO_LATEX.get(chr_val, r"\int").strip())
        sub = _convert_children(elem.find(f"{M_NS}sub")).strip()
        sup = _convert_children(elem.find(f"{M_NS}sup")).strip()
        body = _convert_children(elem.find(f"{M_NS}e")).strip()
        out = op
        if sub:
            out += f"_{{{sub}}}"
        if sup:
            out += f"^{{{sup}}}"
        return f"{out} {body}"

    if name == "d":
        dpr = elem.find(f"{M_NS}dPr")
        beg = _mval(dpr, "begChr", "(")
        end = _mval(dpr, "endChr", ")")
        sep = _mval(dpr, "sepChr", ",")
        lb = _DELIM_ESCAPE.get(beg, beg or ".")
        rb = _DELIM_ESCAPE.get(end, end or ".")
        items = [_convert_children(e).strip() for e in elem.findall(f"{M_NS}e")]
        sep_s = f" {sep} " if sep else ", "
        return rf"\left{lb} {sep_s.join(items)} \right{rb}"

    if name == "m":
        rows_tex: list[str] = []
        for mr in elem.findall(f"{M_NS}mr"):
            cells = [_convert_children(e).strip() for e in mr.findall(f"{M_NS}e")]
            rows_tex.append(" & ".join(cells))
        return r"\begin{matrix} " + r" \\ ".join(rows_tex) + r" \end{matrix}"

    if name == "eqArr":
        lines = [_convert_children(e).strip() for e in elem.findall(f"{M_NS}e")]
        lines = [ln for ln in lines if ln]
        if len(lines) <= 1:
            return lines[0] if lines else ""
        return r"\begin{aligned} " + r" \\ ".join(lines) + r" \end{aligned}"

    if name == "func":
        fn = _convert_children(elem.find(f"{M_NS}fName")).strip()
        arg = _convert_children(elem.find(f"{M_NS}e")).strip()
        fn_plain = re.sub(r"\\mathrm\{([^}]+)\}", r"\1", fn).strip()
        if fn_plain in _KNOWN_FUNCS:
            return rf"\{fn_plain} {arg}"
        return f"{fn} {arg}"

    if name == "acc":
        apr = elem.find(f"{M_NS}accPr")
        chr_val = _mval(apr, "chr", "\u0302")
        cmd = _ACCENT_MAP.get(chr_val, r"\hat")
        body = _convert_children(elem.find(f"{M_NS}e")).strip()
        return rf"{cmd}{{{body}}}"

    if name == "bar":
        bpr = elem.find(f"{M_NS}barPr")
        pos = _mval(bpr, "pos", "top")
        body = _convert_children(elem.find(f"{M_NS}e")).strip()
        return rf"\underline{{{body}}}" if pos == "bot" else rf"\overline{{{body}}}"

    if name == "limLow":
        body = _convert_children(elem.find(f"{M_NS}e")).strip()
        lim = _convert_children(elem.find(f"{M_NS}lim")).strip()
        if re.sub(r"\\mathrm\{([^}]+)\}", r"\1", body).strip() == "lim":
            return rf"\lim_{{{lim}}}"
        return rf"\underset{{{lim}}}{{{body}}}"

    if name == "limUpp":
        body = _convert_children(elem.find(f"{M_NS}e")).strip()
        lim = _convert_children(elem.find(f"{M_NS}lim")).strip()
        return rf"\overset{{{lim}}}{{{body}}}"

    if name == "groupChr":
        gpr = elem.find(f"{M_NS}groupChrPr")
        pos = _mval(gpr, "pos", "bot")
        body = _convert_children(elem.find(f"{M_NS}e")).strip()
        return rf"\overbrace{{{body}}}" if pos == "top" else rf"\underbrace{{{body}}}"

    return _convert_children(elem)


def omml_to_latex(elem: Any) -> str:
    """Convert an lxml <m:oMath> or <m:oMathPara> element into clean KaTeX-compatible LaTeX."""
    raw = _convert_node(elem)
    return re.sub(r"\s+", " ", raw).strip()


def format_word_vert_align(text: str, align: str) -> str:
    """Format Word superscript/subscript run cleanly as Unicode or lightweight inline math."""
    s = text.strip()
    if not s:
        return text
    if align == "superscript":
        if all(ch in "0123456789+-=()nijkabcmrtxy, " for ch in s):
            return s.translate(SUP_CHAR_MAP)
        return f"$^{{{s}}}$"
    if align == "subscript":
        if all(ch in "0123456789+-=()aehijklmnoprstuvx, " for ch in s):
            return s.translate(SUB_CHAR_MAP)
        return f"$_{{{s}}}$"
    return text
