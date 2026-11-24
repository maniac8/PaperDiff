"""Deep Word OOXML (.docx) parser with original blob archiving, numbering.xml resolution,
footnotes/endnotes, reviewer comments, mc:Choice deduped textboxes, OMML + MathType OLE fallback,
XML anchors for in-place patching, and Track Changes (<w:ins>/<w:del>) pre-check & split import.
"""
from __future__ import annotations

import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from docx import Document
from docx.oxml.ns import qn
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from ..assets import save_asset_bytes, save_blob_bytes
from .ir import normalize_block_style
from .omml import M_NS, format_word_vert_align, omml_to_latex
from .zones import _is_metadata_form_table

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC_NS = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

_CN_DIGITS = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]


def _format_num_value(val: int, num_fmt: str) -> str:
    if num_fmt == "lowerLetter":
        return chr(ord("a") + ((val - 1) % 26))
    if num_fmt == "upperLetter":
        return chr(ord("A") + ((val - 1) % 26))
    if num_fmt in ("lowerRoman", "upperRoman"):
        romans = [
            (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
            (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
            (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
        ]
        n = max(1, val)
        out = []
        for arabic, sym in romans:
            while n >= arabic:
                out.append(sym)
                n -= arabic
        res = "".join(out)
        return res.lower() if num_fmt == "lowerRoman" else res
    if "chinese" in num_fmt.lower() or "ideograph" in num_fmt.lower():
        if 0 <= val <= 10:
            return _CN_DIGITS[val]
        if 11 <= val <= 19:
            return "十" + _CN_DIGITS[val - 10]
        if 20 <= val <= 99:
            tens, ones = divmod(val, 10)
            return _CN_DIGITS[tens] + "十" + (_CN_DIGITS[ones] if ones else "")
    return str(val)


class _WordNumberingResolver:
    """Resolve word/numbering.xml multi-level section & list numbering."""

    def __init__(self, raw_bytes: bytes) -> None:
        self.num_to_abstract: dict[str, str] = {}
        self.abstract_lvls: dict[str, dict[int, dict[str, Any]]] = {}
        self.counters: dict[str, dict[int, int]] = {}
        self._load(raw_bytes)

    def _load(self, raw_bytes: bytes) -> None:
        try:
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                if "word/numbering.xml" not in zf.namelist():
                    return
                root = ET.fromstring(zf.read("word/numbering.xml"))
        except Exception:
            return

        for ab in root.findall(f"{W_NS}abstractNum"):
            ab_id = ab.get(f"{W_NS}abstractNumId", "")
            if not ab_id:
                continue
            lvls: dict[int, dict[str, Any]] = {}
            for lvl in ab.findall(f"{W_NS}lvl"):
                try:
                    ilvl = int(lvl.get(f"{W_NS}ilvl", "0"))
                except ValueError:
                    ilvl = 0
                start_el = lvl.find(f"{W_NS}start")
                fmt_el = lvl.find(f"{W_NS}numFmt")
                txt_el = lvl.find(f"{W_NS}lvlText")
                start_v = 1
                if start_el is not None:
                    try:
                        start_v = int(start_el.get(f"{W_NS}val", "1"))
                    except ValueError:
                        start_v = 1
                lvls[ilvl] = {
                    "start": start_v,
                    "numFmt": fmt_el.get(f"{W_NS}val", "decimal") if fmt_el is not None else "decimal",
                    "lvlText": txt_el.get(f"{W_NS}val", f"%{ilvl + 1}.") if txt_el is not None else f"%{ilvl + 1}.",
                }
            self.abstract_lvls[ab_id] = lvls

        for num in root.findall(f"{W_NS}num"):
            num_id = num.get(f"{W_NS}numId", "")
            ab_ref = num.find(f"{W_NS}abstractNumId")
            if num_id and ab_ref is not None:
                ab_id = ab_ref.get(f"{W_NS}val", "")
                if ab_id:
                    self.num_to_abstract[num_id] = ab_id

    def resolve(self, num_id: str, ilvl: int) -> tuple[str, bool]:
        """Advance counter and return (formatted_prefix, is_ordered)."""
        ab_id = self.num_to_abstract.get(num_id)
        if not ab_id or ab_id not in self.abstract_lvls:
            return "", False
        lvl_map = self.abstract_lvls[ab_id]
        lvl_info = lvl_map.get(ilvl)
        if not lvl_info:
            return "", False

        num_fmt = lvl_info["numFmt"]
        if num_fmt in ("bullet", "none"):
            return "", False

        ctrs = self.counters.setdefault(ab_id, {})
        # Reset deeper levels
        for deeper in [k for k in ctrs if k > ilvl]:
            del ctrs[deeper]
        if ilvl not in ctrs:
            ctrs[ilvl] = lvl_info["start"]
        else:
            ctrs[ilvl] += 1

        # Fill %1, %2, ... placeholders in lvlText
        lvl_text = lvl_info["lvlText"]

        def _repl(m: re.Match[str]) -> str:
            ref_idx = int(m.group(1)) - 1
            ref_info = lvl_map.get(ref_idx, {"numFmt": "decimal", "start": 1})
            v = ctrs.get(ref_idx, ref_info["start"])
            return _format_num_value(v, ref_info["numFmt"])

        prefix = re.sub(r"%(\d+)", _repl, lvl_text).strip()
        return prefix, True


def _extract_aux_ooxml_parts(raw_bytes: bytes) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Extract word/footnotes.xml, word/endnotes.xml, and word/comments.xml."""
    footnotes: dict[str, str] = {}
    comments: dict[str, dict[str, str]] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            names = set(zf.namelist())
            for part_name, tag_name, key_prefix in (
                ("word/footnotes.xml", "footnote", ""),
                ("word/endnotes.xml", "endnote", "e"),
            ):
                if part_name in names:
                    root = ET.fromstring(zf.read(part_name))
                    for fn in root.findall(f"{W_NS}{tag_name}"):
                        fid = fn.get(f"{W_NS}id", "")
                        ftype = fn.get(f"{W_NS}type", "")
                        if not fid or ftype in ("separator", "continuationSeparator") or fid in ("-1", "0"):
                            continue
                        texts = [t.text or "" for t in fn.iter(f"{W_NS}t")]
                        body = re.sub(r"\s+", " ", "".join(texts)).strip()
                        if body:
                            footnotes[f"{key_prefix}{fid}"] = body

            if "word/comments.xml" in names:
                root = ET.fromstring(zf.read("word/comments.xml"))
                for cmt in root.findall(f"{W_NS}comment"):
                    cid = cmt.get(f"{W_NS}id", "")
                    author = cmt.get(f"{W_NS}author", "") or "Reviewer"
                    date = cmt.get(f"{W_NS}date", "")
                    texts = [t.text or "" for t in cmt.iter(f"{W_NS}t")]
                    body = re.sub(r"\s+", " ", "".join(texts)).strip()
                    if cid and body:
                        comments[cid] = {
                            "id": cid,
                            "author": author,
                            "date": date[:10] if date else "",
                            "text": body,
                        }
    except Exception:
        pass
    return footnotes, comments


def inspect_docx_tracked_changes(raw_bytes: bytes) -> dict[str, Any]:
    """
    Quickly inspect a .docx file for Word Track Changes (<w:ins> / <w:del>) before import.
    Enables the UI to offer one-click split import into vN (修订前) vs vN+1 (修订后).
    """
    ins_count = 0
    del_count = 0
    authors: set[str] = set()
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            if "word/document.xml" in zf.namelist():
                root = ET.fromstring(zf.read("word/document.xml"))
                for el in root.iter():
                    if el.tag == f"{W_NS}ins":
                        txt = "".join(t.text or "" for t in el.iter(f"{W_NS}t")).strip()
                        if txt:
                            ins_count += 1
                            a = el.get(f"{W_NS}author", "").strip()
                            if a:
                                authors.add(a)
                    elif el.tag == f"{W_NS}del":
                        txt = "".join(t.text or "" for t in el.iter(f"{W_NS}delText")).strip()
                        if txt:
                            del_count += 1
                            a = el.get(f"{W_NS}author", "").strip()
                            if a:
                                authors.add(a)
    except Exception:
        pass
    has_tc = (ins_count + del_count) > 0
    return {
        "has_tracked_changes": has_tc,
        "ins_count": ins_count,
        "del_count": del_count,
        "authors": sorted(authors),
        "summary": f"检测到 {ins_count} 处插入与 {del_count} 处删除修订" if has_tc else "",
    }


def _extract_paragraph_runs_to_md(
    p_el: Any,
    *,
    preserve_styles: bool = True,
    track_mode: str = "after",  # 'after' (accept ins, drop del) | 'before' (drop ins, keep del)
    footnotes_available: dict[str, str] | None = None,
) -> tuple[str, list[str], list[str], list[Any]]:
    """
    Walk a Word <w:p> XML element in exact document order:
    - Interleaves text runs (<w:r>), inline OMML equations (<m:oMath>), footnotes/endnotes
    - Collects standalone display OMML equations (<m:oMathPara>)
    - Handles Track Changes cleanly per track_mode ('after' vs 'before')
    - Collects comment IDs attached to this paragraph
    - Extracts deduplicated textbox inner <w:p> elements (mc:Choice only, skipping mc:Fallback!)
    Returns (inline_markdown_text, display_math_latex_list, comment_ids, textbox_paragraphs).
    """
    display_maths: list[str] = []
    pieces: list[tuple[str, bool, bool, bool]] = []
    comment_ids: list[str] = []
    textbox_ps: list[Any] = []
    in_field_instr = False

    def _walk(node: Any, in_del: bool = False) -> None:
        nonlocal in_field_instr
        for ch in node:
            tag = ch.tag
            local = tag.split("}", 1)[1] if "}" in tag else tag

            if local in ("commentRangeStart", "commentReference"):
                cid = ch.get(qn("w:id")) or ch.get(f"{W_NS}id")
                if cid and cid not in comment_ids:
                    comment_ids.append(cid)
                continue

            if local in ("instrText", "pPr", "proofErr", "bookmarkStart", "bookmarkEnd", "commentRangeEnd"):
                continue

            # Track Changes mode routing!
            if local == "del":
                if track_mode == "before":
                    _walk(ch, in_del=True)
                continue
            if local == "ins":
                if track_mode == "after":
                    _walk(ch, in_del=False)
                continue

            # AlternateContent: ONLY descend into mc:Choice (skip mc:Fallback duplicate!)
            if local == "AlternateContent":
                choice = ch.find(f"{MC_NS}Choice")
                if choice is not None:
                    _walk(choice, in_del=in_del)
                continue
            if local == "Fallback":
                continue

            # Textbox content: extract inner paragraphs cleanly without duplicating VML
            if local == "txbxContent":
                for sub_p in ch.findall(qn("w:p")):
                    textbox_ps.append(sub_p)
                continue

            if tag == f"{M_NS}oMathPara":
                tex = omml_to_latex(ch)
                if tex:
                    display_maths.append(tex)
                continue

            if tag == f"{M_NS}oMath":
                tex = omml_to_latex(ch)
                if tex:
                    pieces.append((f"${tex}$", False, False, True))
                continue

            if local in ("hyperlink", "smartTag", "sdt", "sdtContent", "customXml", "drawing", "pict", "Choice"):
                _walk(ch, in_del=in_del)
                continue

            # Descend into drawingML containers to reach w:txbxContent
            if local in ("inline", "anchor", "graphic", "graphicData", "wsp", "txbx", "textbox", "shape", "group"):
                _walk(ch, in_del=in_del)
                continue

            if local == "r":
                # Check for commentReference inside run
                for cref in ch.findall(qn("w:commentReference")):
                    cid = cref.get(qn("w:id"))
                    if cid and cid not in comment_ids:
                        comment_ids.append(cid)

                # Descend into any embedded drawings/textboxes inside run
                for dr in ch:
                    dloc = dr.tag.split("}", 1)[1] if "}" in dr.tag else dr.tag
                    if dloc in ("drawing", "pict", "AlternateContent"):
                        _walk(dr, in_del=in_del)

                fld = ch.find(qn("w:fldChar"))
                if fld is not None:
                    ftype = fld.get(qn("w:fldCharType"), "")
                    if ftype == "begin":
                        in_field_instr = True
                    elif ftype in ("separate", "end"):
                        in_field_instr = False
                    continue
                if in_field_instr:
                    continue

                # Footnote / Endnote references
                fn_ref = ch.find(qn("w:footnoteReference"))
                if fn_ref is not None:
                    fid = fn_ref.get(qn("w:id"), "")
                    if fid and (footnotes_available is None or fid in footnotes_available):
                        pieces.append((f"[^{fid}]", False, False, True))
                    continue
                en_ref = ch.find(qn("w:endnoteReference"))
                if en_ref is not None:
                    eid = en_ref.get(qn("w:id"), "")
                    ekey = f"e{eid}"
                    if eid and (footnotes_available is None or ekey in footnotes_available):
                        pieces.append((f"[^{ekey}]", False, False, True))
                    continue

                rPr = ch.find(qn("w:rPr"))
                is_bold = False
                is_italic = False
                vert_align = ""
                if rPr is not None:
                    b_el = rPr.find(qn("w:b"))
                    if b_el is not None and b_el.get(qn("w:val"), "true") not in ("0", "false"):
                        is_bold = True
                    i_el = rPr.find(qn("w:i"))
                    if i_el is not None and i_el.get(qn("w:val"), "true") not in ("0", "false"):
                        is_italic = True
                    va_el = rPr.find(qn("w:vertAlign"))
                    if va_el is not None:
                        vert_align = va_el.get(qn("w:val"), "")

                run_parts: list[str] = []

                def _flush_run_parts() -> None:
                    nonlocal run_parts
                    if not run_parts:
                        return
                    run_txt = "".join(run_parts)
                    run_parts = []
                    if vert_align in ("superscript", "subscript"):
                        formatted = format_word_vert_align(run_txt, vert_align)
                        pieces.append((formatted, False, False, True))
                    else:
                        pieces.append((run_txt, is_bold and preserve_styles, is_italic and preserve_styles, False))

                for sub in ch:
                    sloc = sub.tag.split("}", 1)[1] if "}" in sub.tag else sub.tag
                    if sloc == "t" and sub.text and not in_del:
                        run_parts.append(sub.text)
                    elif sloc == "delText" and sub.text and in_del:
                        run_parts.append(sub.text)
                    elif sloc == "tab":
                        _flush_run_parts()
                        pieces.append(("⟦SP:2⟧", False, False, True))
                    elif sloc in ("br", "cr"):
                        br_type = sub.get(qn("w:type"), "")
                        if br_type != "page":
                            run_parts.append(" ")
                    elif sloc == "noBreakHyphen":
                        run_parts.append("-")
                _flush_run_parts()

    _walk(p_el)

    if not pieces:
        return "", display_maths, comment_ids, textbox_ps

    non_ws = [p for p in pieces if p[0].strip() and not p[3]]
    all_bold = bool(non_ws) and all(p[1] for p in non_ws)

    merged: list[tuple[str, bool, bool, bool]] = []
    for txt, b, it, raw_atom in pieces:
        eff_b = False if all_bold else b
        if merged and not raw_atom and not merged[-1][3] and merged[-1][1] == eff_b and merged[-1][2] == it:
            merged[-1] = (merged[-1][0] + txt, eff_b, it, False)
        else:
            merged.append((txt, eff_b, it, raw_atom))

    out: list[str] = []
    for txt, b, it, raw_atom in merged:
        if raw_atom or not txt.strip():
            out.append(txt)
            continue
        lead_sp = txt[: len(txt) - len(txt.lstrip())]
        trail_sp = txt[len(txt.rstrip()) :]
        core = txt.strip()
        if not core:
            out.append(txt)
            continue
        if b and it and len(core) >= 2:
            out.append(f"{lead_sp}***{core}***{trail_sp}")
        elif b and len(core) >= 2:
            out.append(f"{lead_sp}**{core}**{trail_sp}")
        elif it and len(core) >= 2 and re.search(r"[A-Za-z\u4e00-\u9fff]", core):
            out.append(f"{lead_sp}*{core}*{trail_sp}")
        else:
            out.append(txt)

    # Preserve leading full-width spaces (\u3000) for paragraph indent extraction; only strip ASCII whitespace.
    joined = re.sub(r"[ \t]+", " ", "".join(out)).strip(" \t\r\n")
    return joined, display_maths, comment_ids, textbox_ps


def _consume_leading_visual_indent(text: str) -> tuple[str, float | None]:
    """Extract leading full-width spaces (\\u3000) or leading tab atoms into first-line indent em."""
    if not text:
        return text, None
    em = 0.0
    pos = 0
    n = len(text)
    while pos < n:
        if text[pos] == "\u3000":
            em += 1.0
            pos += 1
        elif text.startswith("⟦SP:2⟧", pos):
            em += 2.0
            pos += len("⟦SP:2⟧")
        elif text[pos] in (" ", "\t"):
            pos += 1
        else:
            break
    if em <= 0.0:
        return text, None
    rest = text[pos:].strip(" \t\r\n")
    return rest, min(4.0, round(em, 2))


def _extract_docx_paragraph_style(p_el: Any, para: Paragraph, doc: Document) -> dict[str, Any]:
    """Resolve Word paragraph indentation (<w:ind>) and alignment (<w:jc>) along the OOXML style chain."""
    ppr_chain: list[Any] = []
    direct_ppr = p_el.find(qn("w:pPr"))
    if direct_ppr is not None:
        ppr_chain.append(direct_ppr)

    cur_style = getattr(para, "style", None)
    visited: set[str] = set()
    while cur_style is not None:
        sid = getattr(cur_style, "style_id", "") or ""
        if sid and sid in visited:
            break
        if sid:
            visited.add(sid)
        s_el = getattr(cur_style, "element", None)
        if s_el is not None:
            sppr = s_el.find(qn("w:pPr"))
            if sppr is not None:
                ppr_chain.append(sppr)
        cur_style = getattr(cur_style, "base_style", None)

    styles_root = getattr(getattr(doc, "styles", None), "element", None)
    if styles_root is not None:
        def_ppr = styles_root.find(f".//{qn('w:docDefaults')}/{qn('w:pPrDefault')}/{qn('w:pPr')}")
        if def_ppr is not None:
            ppr_chain.append(def_ppr)

    def _int_attr(el: Any, attr_name: str) -> int | None:
        val = el.get(qn(attr_name))
        if val is None:
            return None
        try:
            return int(val)
        except ValueError:
            return None

    first_line_em: float | None = None
    explicit_indent: str | None = None
    hanging_em: float | None = None
    left_em: float | None = None
    right_em: float | None = None
    align_val: str | None = None

    # Walk from most specific (direct pPr) to least specific (docDefaults); first hit per logical slot wins.
    for ppr in ppr_chain:
        ind = ppr.find(qn("w:ind"))
        if ind is not None:
            if first_line_em is None and hanging_em is None:
                fl_chars = _int_attr(ind, "w:firstLineChars")
                fl_twips = _int_attr(ind, "w:firstLine")
                hg_chars = _int_attr(ind, "w:hangingChars")
                hg_twips = _int_attr(ind, "w:hanging")
                if hg_chars is not None and hg_chars > 0:
                    hanging_em = round(hg_chars / 100.0, 2)
                elif hg_twips is not None and hg_twips > 0:
                    hanging_em = round(hg_twips / 210.0, 2)
                elif fl_chars is not None:
                    first_line_em = round(fl_chars / 100.0, 2)
                    explicit_indent = "indent" if fl_chars > 0 else "none"
                elif fl_twips is not None:
                    first_line_em = round(fl_twips / 210.0, 2)
                    explicit_indent = "indent" if fl_twips > 0 else "none"

            if left_em is None:
                lc = _int_attr(ind, "w:leftChars")
                lt = _int_attr(ind, "w:left")
                if lt is None:
                    lt = _int_attr(ind, "w:start")
                if lc is not None and lc > 0:
                    left_em = round(lc / 100.0, 2)
                elif lt is not None and lt > 0:
                    left_em = round(lt / 210.0, 2)

            if right_em is None:
                rc = _int_attr(ind, "w:rightChars")
                rt = _int_attr(ind, "w:right")
                if rt is None:
                    rt = _int_attr(ind, "w:end")
                if rc is not None and rc > 0:
                    right_em = round(rc / 100.0, 2)
                elif rt is not None and rt > 0:
                    right_em = round(rt / 210.0, 2)

        if align_val is None:
            jc = ppr.find(qn("w:jc"))
            if jc is not None:
                raw_jc = (jc.get(qn("w:val")) or "").strip().lower()
                jc_map = {
                    "both": "justify",
                    "distribute": "justify",
                    "center": "center",
                    "right": "right",
                    "end": "right",
                    "left": "left",
                    "start": "left",
                }
                if raw_jc in jc_map:
                    align_val = jc_map[raw_jc]

    raw_style: dict[str, Any] = {}
    if first_line_em is not None:
        raw_style["first_line_indent_em"] = first_line_em
    if explicit_indent is not None:
        raw_style["explicit_indent"] = explicit_indent
    if hanging_em is not None:
        raw_style["hanging_indent_em"] = hanging_em
    if left_em is not None:
        raw_style["left_indent_em"] = left_em
    if right_em is not None:
        raw_style["right_indent_em"] = right_em
    if align_val is not None:
        raw_style["align"] = align_val
    return normalize_block_style(raw_style)


def _get_paragraph_numpr(p_el: Any, para: Paragraph) -> tuple[str | None, int]:
    """Extract (numId, ilvl) from paragraph XML or style chain."""
    pPr = p_el.find(qn("w:pPr"))
    if pPr is not None:
        numPr = pPr.find(qn("w:numPr"))
        if numPr is not None:
            nid_el = numPr.find(qn("w:numId"))
            ilvl_el = numPr.find(qn("w:ilvl"))
            nid = nid_el.get(qn("w:val")) if nid_el is not None else None
            ilvl = int(ilvl_el.get(qn("w:val"), "0")) if ilvl_el is not None else 0
            if nid and nid != "0":
                return nid, ilvl
    if para.style is not None:
        cur = para.style
        seen: set[str] = set()
        while cur is not None and cur.style_id not in seen:
            seen.add(cur.style_id)
            s_el = getattr(cur, "element", None)
            if s_el is not None:
                spPr = s_el.find(qn("w:pPr"))
                if spPr is not None:
                    numPr = spPr.find(qn("w:numPr"))
                    if numPr is not None:
                        nid_el = numPr.find(qn("w:numId"))
                        ilvl_el = numPr.find(qn("w:ilvl"))
                        nid = nid_el.get(qn("w:val")) if nid_el is not None else None
                        ilvl = int(ilvl_el.get(qn("w:val"), "0")) if ilvl_el is not None else 0
                        if nid and nid != "0":
                            return nid, ilvl
            cur = getattr(cur, "base_style", None)
    return None, 0


def _resolve_docx_outline_level(p_el: Any, para: Paragraph) -> tuple[str, int]:
    style_name = (para.style.name or "").strip() if para.style else ""
    style_low = style_name.lower()

    if re.match(r"^(?:toc\s*\d*|目录\s*\d*|table of contents)", style_low):
        return ("toc", 0)
    for instr in p_el.findall(f".//{qn('w:instrText')}"):
        if instr.text and ("_Toc" in instr.text or "TOC " in instr.text or "PAGEREF" in instr.text):
            return ("toc", 0)

    if ("title" in style_low and "subtitle" not in style_low) or style_low in ("标题", "论文题目"):
        return ("title", 0)

    if "caption" in style_low or "题注" in style_low or "图注" in style_low or "表注" in style_low:
        return ("caption", 0)

    outline_lvl: int | None = None
    pPr = p_el.find(qn("w:pPr"))
    if pPr is not None:
        ol = pPr.find(qn("w:outlineLvl"))
        if ol is not None:
            try:
                v = int(ol.get(qn("w:val"), "9"))
                if 0 <= v <= 5:
                    outline_lvl = v + 1
            except ValueError:
                pass

    if outline_lvl is None and para.style is not None:
        cur_style = para.style
        visited_styles: set[str] = set()
        while cur_style is not None and cur_style.style_id not in visited_styles:
            visited_styles.add(cur_style.style_id)
            s_el = getattr(cur_style, "element", None)
            if s_el is not None:
                spPr = s_el.find(qn("w:pPr"))
                if spPr is not None:
                    sol = spPr.find(qn("w:outlineLvl"))
                    if sol is not None:
                        try:
                            v = int(sol.get(qn("w:val"), "9"))
                            if 0 <= v <= 5:
                                outline_lvl = v + 1
                                break
                        except ValueError:
                            pass
            cur_style = getattr(cur_style, "base_style", None)

    if outline_lvl is None:
        m_en = re.search(r"heading\s*(\d)", style_low)
        m_zh = re.search(r"标题\s*(\d)", style_low)
        if m_en:
            outline_lvl = int(m_en.group(1))
        elif m_zh:
            outline_lvl = int(m_zh.group(1))
        elif any(k in style_low for k in ("章标题", "一级标题", "chapter")):
            outline_lvl = 1
        elif any(k in style_low for k in ("节标题", "二级标题")):
            outline_lvl = 2
        elif any(k in style_low for k in ("条标题", "三级标题")):
            outline_lvl = 3

    plain_txt = para.text.strip()

    if outline_lvl is not None and outline_lvl >= 3 and len(plain_txt) > 120 and plain_txt.count(",") >= 3:
        return ("frontmatter_para", 0)

    if outline_lvl is not None:
        return ("heading", min(4, max(1, outline_lvl)))

    has_numPr = p_el.find(f".//{qn('w:numPr')}") is not None
    if "list number" in style_low:
        return ("list_num", 0)
    if has_numPr or "list" in style_low:
        return ("list_bullet", 0)

    if 2 <= len(plain_txt) <= 50 and not plain_txt.endswith(("。", ".", "；", ";", "，", ",")):
        if re.match(r"^第[一二三四五六七八九十百\d]+[章节篇]\s*\S*", plain_txt):
            return ("heading", 1)
        if re.match(r"^(?:摘\s*要|Abstract|参考文献|References|致\s*谢|Acknowledgements?|附\s*录\s*[A-Z\d]?)$", plain_txt, re.IGNORECASE):
            return ("heading", 1)
        runs = p_el.findall(f".//{qn('w:r')}")
        non_empty_runs = [r for r in runs if "".join(t.text or "" for t in r.findall(qn("w:t"))).strip()]
        is_all_bold = bool(non_empty_runs) and all(
            (
                r.find(qn("w:rPr")) is not None
                and r.find(qn("w:rPr")).find(qn("w:b")) is not None
                and r.find(qn("w:rPr")).find(qn("w:b")).get(qn("w:val"), "true") not in ("0", "false")
            )
            for r in non_empty_runs
        )
        if is_all_bold:
            if re.match(r"^[一二三四五六七八九十]+、\S+", plain_txt) or re.match(r"^\d+\s+[\u4e00-\u9fffA-Za-z]", plain_txt):
                return ("heading", 1)
            if re.match(r"^\d+\.\d+\s+\S+", plain_txt):
                return ("heading", 2)
            if re.match(r"^\d+\.\d+\.\d+\s+\S+", plain_txt):
                return ("heading", 3)

    return ("paragraph", 0)


def _is_docx_table_borderless(tbl: Table) -> bool:
    tblPr = tbl._tbl.find(qn("w:tblPr"))
    if tblPr is None:
        return False
    borders = tblPr.find(qn("w:tblBorders"))
    if borders is None:
        return False
    vals = []
    for side in ("top", "bottom", "left", "right", "insideH", "insideV"):
        el = borders.find(qn(f"w:{side}"))
        if el is not None:
            vals.append(el.get(qn("w:val"), ""))
    return bool(vals) and all(v in ("none", "nil") for v in vals)


def _extract_docx_table_rich(
    tbl: Table,
    *,
    track_mode: str = "after",
    footnotes_available: dict[str, str] | None = None,
) -> tuple[list[list[dict[str, Any]]], list[list[dict[str, int]]]]:
    """
    Parse a Word table preserving merged cells (colspan/rowspan), OMML math, bold formatting,
    AND exact XML cell coordinate mapping (xml_tr, xml_tc) for in-place patching!
    """
    tr_list = tbl._tbl.findall(qn("w:tr"))
    if not tr_list:
        return [], []

    raw_grid: list[list[dict[str, Any] | None]] = []
    for tr_idx, tr in enumerate(tr_list):
        row_cells: list[dict[str, Any] | None] = []
        for tc_idx, tc in enumerate(tr.findall(qn("w:tc"))):
            tcPr = tc.find(qn("w:tcPr"))
            colspan = 1
            vmerge: str | None = None
            if tcPr is not None:
                gs = tcPr.find(qn("w:gridSpan"))
                if gs is not None:
                    try:
                        colspan = max(1, int(gs.get(qn("w:val"), "1")))
                    except ValueError:
                        colspan = 1
                vm = tcPr.find(qn("w:vMerge"))
                if vm is not None:
                    val = vm.get(qn("w:val"))
                    vmerge = "restart" if val == "restart" else "continue"

            texts: list[str] = []
            non_empty_runs = 0
            bold_runs = 0
            for p_el in tc.findall(qn("w:p")):
                for r_el in p_el.findall(f".//{qn('w:r')}"):
                    rtxt = "".join(t.text or "" for t in r_el.findall(qn("w:t")))
                    if rtxt.strip():
                        non_empty_runs += 1
                        rPr = r_el.find(qn("w:rPr"))
                        if rPr is not None and rPr.find(qn("w:b")) is not None:
                            b_el = rPr.find(qn("w:b"))
                            if b_el.get(qn("w:val"), "true") not in ("0", "false"):
                                bold_runs += 1
                p_md, p_dmaths, _, _ = _extract_paragraph_runs_to_md(
                    p_el,
                    preserve_styles=False,
                    track_mode=track_mode,
                    footnotes_available=footnotes_available,
                )
                if p_md:
                    texts.append(p_md)
                for dm in p_dmaths:
                    texts.append(f"${dm}$")

            cell_text = re.sub(r"\s+", " ", " ".join(texts)).strip()
            is_bold = non_empty_runs > 0 and bold_runs == non_empty_runs

            if vmerge == "continue":
                row_cells.append({"_vmerge_cont": True, "colspan": colspan})
            else:
                row_cells.append(
                    {
                        "text": cell_text,
                        "colspan": colspan,
                        "rowspan": 1,
                        "bold": is_bold,
                        "_xml_tr": tr_idx,
                        "_xml_tc": tc_idx,
                    }
                )
            for _ in range(colspan - 1):
                row_cells.append(None)
        raw_grid.append(row_cells)

    for r_idx in range(len(raw_grid)):
        for c_idx, cell in enumerate(raw_grid[r_idx]):
            if cell and cell.get("_vmerge_cont"):
                up = r_idx - 1
                while up >= 0:
                    above = raw_grid[up][c_idx] if c_idx < len(raw_grid[up]) else None
                    if above and not above.get("_vmerge_cont"):
                        above["rowspan"] = int(above.get("rowspan", 1)) + 1
                        break
                    up -= 1
                raw_grid[r_idx][c_idx] = None

    final_rows: list[list[dict[str, Any]]] = []
    cell_map: list[list[dict[str, int]]] = []
    for row in raw_grid:
        clean_row = [c for c in row if c is not None and not c.get("_vmerge_cont")]
        if clean_row and any(c["text"] for c in clean_row):
            out_r = []
            map_r = []
            for c in clean_row:
                out_r.append(
                    {
                        "text": c["text"],
                        "colspan": c["colspan"],
                        "rowspan": c["rowspan"],
                        "bold": c["bold"],
                    }
                )
                map_r.append({"tr": int(c["_xml_tr"]), "tc": int(c["_xml_tc"])})
            final_rows.append(out_r)
            cell_map.append(map_r)
    return final_rows, cell_map


def _extract_docx_paragraph_images(p_el: Any, doc: Document) -> list[str]:
    """Extract embedded image asset keys (including MathType OLE preview images!) skipping mc:Fallback."""
    asset_keys: list[str] = []

    def _scan(el: Any) -> None:
        local = el.tag.split("}", 1)[1] if "}" in el.tag else el.tag
        if local == "Fallback":
            return
        if local == "blip":
            r_id = el.get(qn("r:embed")) or el.get(f"{R_NS}embed")
            if r_id and r_id in doc.part.related_parts:
                part = doc.part.related_parts[r_id]
                ext = Path(str(part.partname)).suffix or ".png"
                key = save_asset_bytes(part.blob, ext)
                if key:
                    asset_keys.append(key)
        elif local == "imagedata":
            r_id = el.get(f"{R_NS}id")
            if r_id and r_id in doc.part.related_parts:
                part = doc.part.related_parts[r_id]
                ext = Path(str(part.partname)).suffix or ".png"
                key = save_asset_bytes(part.blob, ext)
                if key:
                    asset_keys.append(key)
        for ch in el:
            _scan(ch)

    _scan(p_el)
    return asset_keys


def extract_docx_with_assets(
    raw_bytes: bytes,
    *,
    track_mode: str = "after",
) -> tuple[str, dict[str, Any]]:
    """
    Convert .docx bytes into structured Markdown preserving:
    - Original .docx blob archived in DATA_DIR/blobs/ (source_blob_key) for dual-view & in-place patching
    - word/numbering.xml multi-level section/list numbering
    - word/footnotes.xml & word/endnotes.xml
    - word/comments.xml reviewer comments
    - mc:Choice deduplicated textboxes (w:txbxContent)
    - OMML math equations + MathType OLE preview fallback
    - Exact XML anchors (PAPERDIFF_ANCHOR) for format-preserving round-trip patching
    - Track Changes mode ('after' | 'before')
    """
    source_blob_key = save_blob_bytes(raw_bytes, ".docx")
    numbering = _WordNumberingResolver(raw_bytes)
    footnotes_map, comments_map = _extract_aux_ooxml_parts(raw_bytes)
    tc_info = inspect_docx_tracked_changes(raw_bytes)

    doc = Document(io.BytesIO(raw_bytes))
    lines: list[str] = []
    asset_map: dict[str, str] = {}
    img_counter = 0
    body_p_counter = -1
    body_tbl_counter = -1

    def _emit_paragraph(p_el: Any, forced_frontmatter: bool = False, xml_anchor: dict[str, Any] | None = None) -> None:
        nonlocal img_counter
        img_keys = _extract_docx_paragraph_images(p_el, doc)
        for key in img_keys:
            img_counter += 1
            ref_name = f"docx_img_{img_counter}"
            asset_map[ref_name] = key
            asset_map[key] = key
            lines.append(f"![Figure {img_counter}](asset://{key})")
            lines.append("")

        para = Paragraph(p_el, doc)
        kind, lvl = _resolve_docx_outline_level(p_el, para)
        preserve_styles = kind not in ("title", "heading", "toc")
        text, display_maths, cids, textbox_ps = _extract_paragraph_runs_to_md(
            p_el,
            preserve_styles=preserve_styles,
            track_mode=track_mode,
            footnotes_available=footnotes_map,
        )

        # Resolve numbering.xml prefix for headings and lists!
        num_id, ilvl = _get_paragraph_numpr(p_el, para)
        num_prefix = ""
        is_ordered_num = False
        if num_id:
            num_prefix, is_ordered_num = numbering.resolve(num_id, ilvl)
            if kind == "list_bullet" and is_ordered_num:
                kind = "list_num"

        if text:
            p_style = _extract_docx_paragraph_style(p_el, para, doc)
            text, lead_em = _consume_leading_visual_indent(text)
            if (
                lead_em is not None
                and kind == "paragraph"
                and "first_line_indent_em" not in p_style
                and "hanging_indent_em" not in p_style
            ):
                p_style["first_line_indent_em"] = lead_em
                p_style["explicit_indent"] = "indent"

            if kind == "heading" and num_prefix:
                # Only prepend auto-number if text does not already start with a number
                if not re.match(r"^(?:\d+(?:\.\d+)*|第[一二三四五六七八九十\d]+[章节]|[一二三四五六七八九十]+、)", text):
                    text = f"{num_prefix} {text}"

            if kind in ("list_num", "list_bullet"):
                p_style["list_depth"] = min(5, max(0, ilvl))
            p_style = normalize_block_style(p_style)

            attached_comments = [comments_map[c] for c in cids if c in comments_map]
            if xml_anchor:
                lines.append("<!-- PAPERDIFF_ANCHOR:" + json.dumps(xml_anchor, ensure_ascii=False) + " -->")
            if p_style:
                lines.append("<!-- PAPERDIFF_STYLE:" + json.dumps(p_style, ensure_ascii=False) + " -->")
            if attached_comments:
                lines.append("<!-- PAPERDIFF_COMMENTS:" + json.dumps(attached_comments, ensure_ascii=False) + " -->")

            if kind == "toc" or forced_frontmatter:
                clean_toc = re.sub(r"[\.·…\s]{3,}\d+\s*$", "", text).strip()
                if clean_toc:
                    lines.append("<!-- PAPERDIFF_ZONE:frontmatter -->")
                    lines.append(clean_toc)
                    lines.append("")
            elif kind == "frontmatter_para":
                lines.append("<!-- PAPERDIFF_ZONE:frontmatter -->")
                lines.append(text)
                lines.append("")
            elif kind == "title":
                lines.append(f"# {text}")
                lines.append("")
            elif kind == "heading":
                hashes = "#" * max(1, min(4, lvl))
                lines.append(f"{hashes} {text}")
                lines.append("")
            elif kind == "caption":
                lines.append(f"> [Caption] {text}")
                lines.append("")
            elif kind == "list_num":
                # Emit at column 0 and pass exact ilvl via PAPERDIFF_STYLE so 4+ leading spaces never trigger CommonMark code blocks.
                lines.append(f"1. {text}")
                lines.append("")
            elif kind == "list_bullet":
                lines.append(f"- {text}")
                lines.append("")
            else:
                lines.append(text)
                lines.append("")

        for dm in display_maths:
            lines.append(f"$$\n{dm}\n$$")
            lines.append("")

        # Emit deduplicated textbox paragraphs right after host paragraph
        for tb_p in textbox_ps:
            _emit_paragraph(tb_p, forced_frontmatter=forced_frontmatter, xml_anchor=None)

    def _emit_table(tbl_el: Any, forced_frontmatter: bool = False, xml_anchor: dict[str, Any] | None = None) -> None:
        tbl = Table(tbl_el, doc)
        rich_rows, cell_map = _extract_docx_table_rich(
            tbl,
            track_mode=track_mode,
            footnotes_available=footnotes_map,
        )
        if not rich_rows:
            return
        borderless = _is_docx_table_borderless(tbl)
        is_meta_form = _is_metadata_form_table(rich_rows, borderless=borderless)
        has_rich = any(
            c["colspan"] > 1 or c["rowspan"] > 1 or c["bold"]
            for r in rich_rows
            for c in r
        )
        md_rows: list[str] = []
        if xml_anchor is not None:
            anc_full = dict(xml_anchor)
            anc_full["cell_map"] = cell_map
            md_rows.append("<!-- PAPERDIFF_ANCHOR:" + json.dumps(anc_full, ensure_ascii=False) + " -->")
        if is_meta_form or forced_frontmatter:
            tmeta = {"role": "metadata_form" if is_meta_form else "data_table", "zone": "frontmatter"}
            md_rows.append("<!-- PAPERDIFF_TABLE_META:" + json.dumps(tmeta, ensure_ascii=False) + " -->")
        if has_rich or is_meta_form:
            md_rows.append("<!-- PAPERDIFF_TABLE:" + json.dumps(rich_rows, ensure_ascii=False) + " -->")
        for r_idx, row in enumerate(rich_rows):
            cells = [c["text"].replace("|", "\\|") for c in row]
            md_rows.append("| " + " | ".join(cells) + " |")
            if r_idx == 0:
                md_rows.append("| " + " | ".join(["---"] * len(cells)) + " |")
        lines.append("\n".join(md_rows))
        lines.append("")

    def _walk_body_children(container: Any, forced_frontmatter: bool = False, top_level: bool = False) -> None:
        nonlocal body_p_counter, body_tbl_counter
        for child in container.iterchildren():
            if isinstance(child, CT_P):
                anc = None
                if top_level:
                    body_p_counter += 1
                    anc = {"kind": "docx_p", "body_idx": body_p_counter}
                _emit_paragraph(child, forced_frontmatter=forced_frontmatter, xml_anchor=anc)
            elif isinstance(child, CT_Tbl):
                anc = None
                if top_level:
                    body_tbl_counter += 1
                    anc = {"kind": "docx_tbl", "tbl_idx": body_tbl_counter}
                _emit_table(child, forced_frontmatter=forced_frontmatter, xml_anchor=anc)
            elif child.tag == qn("w:sdt"):
                sdtPr = child.find(qn("w:sdtPr"))
                gallery = ""
                if sdtPr is not None:
                    gal_el = sdtPr.find(f".//{qn('w:docPartGallery')}")
                    if gal_el is not None:
                        gallery = (gal_el.get(qn("w:val"), "") or "").lower()
                sdtContent = child.find(qn("w:sdtContent"))
                if sdtContent is not None:
                    is_fm = forced_frontmatter or any(
                        k in gallery for k in ("table of contents", "table of figures", "cover", "toc", "目录", "封面")
                    )
                    _walk_body_children(sdtContent, forced_frontmatter=is_fm, top_level=False)

    _walk_body_children(doc.element.body, forced_frontmatter=False, top_level=True)

    if footnotes_map:
        lines.append("<!-- PAPERDIFF_FOOTNOTES:" + json.dumps(footnotes_map, ensure_ascii=False) + " -->")

    meta_out: dict[str, Any] = {
        "assets": asset_map,
        "bib": {},
        "source_blob_key": source_blob_key,
        "footnotes": footnotes_map,
        "tracked_changes_info": tc_info,
    }
    return "\n".join(lines).strip(), meta_out


def extract_docx_bytes(raw_bytes: bytes) -> str:
    text, _ = extract_docx_with_assets(raw_bytes)
    return text
