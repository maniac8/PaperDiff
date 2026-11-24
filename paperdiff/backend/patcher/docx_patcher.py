"""Format-preserving in-place Word (.docx) XML patcher.

Opens the original archived .docx template (source_blob_key), locates exact <w:p> and <w:tbl>/<w:tr>/<w:tc>
nodes via source_anchor, and patches them IN-PLACE — preserving cover pages, fonts, styles, headers/footers,
grant form borders, comments, and images in both Clean Revised and Native Track Changes (<w:ins>/<w:del>) modes!
"""
from __future__ import annotations

import copy
import datetime
import difflib
import io
import re
from typing import Any

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P


def _clone_first_rpr(p_el: Any) -> Any | None:
    for r in p_el.findall(qn("w:r")):
        rPr = r.find(qn("w:rPr"))
        if rPr is not None:
            return copy.deepcopy(rPr)
    return None


def _clear_paragraph_runs(p_el: Any) -> None:
    """Remove text runs / tracked changes while preserving <w:pPr>, bookmarks, and comment markers."""
    keep_tags = {
        qn("w:pPr"),
        qn("w:bookmarkStart"),
        qn("w:bookmarkEnd"),
        qn("w:commentRangeStart"),
        qn("w:commentRangeEnd"),
    }
    for ch in list(p_el):
        if ch.tag not in keep_tags:
            p_el.remove(ch)


def _make_run(text: str, base_rpr: Any | None = None, *, bold_override: bool | None = None, is_del: bool = False) -> Any:
    r = OxmlElement("w:r")
    rPr = copy.deepcopy(base_rpr) if base_rpr is not None else OxmlElement("w:rPr")
    if bold_override is not None:
        existing_b = rPr.find(qn("w:b"))
        if bold_override:
            if existing_b is None:
                rPr.append(OxmlElement("w:b"))
            else:
                existing_b.attrib.pop(qn("w:val"), None)
        else:
            if existing_b is not None:
                rPr.remove(existing_b)
    if len(rPr) > 0:
        r.append(rPr)
    t_tag = "w:delText" if is_del else "w:t"
    t = OxmlElement(t_tag)
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text
    r.append(t)
    return r


def _set_paragraph_text_clean(p_el: Any, new_text: str, *, bold_override: bool | None = None) -> None:
    base_rpr = _clone_first_rpr(p_el)
    _clear_paragraph_runs(p_el)
    p_el.append(_make_run(new_text, base_rpr, bold_override=bold_override))


def _set_paragraph_text_tracked(
    p_el: Any,
    old_text: str,
    new_text: str,
    *,
    author: str,
    date_iso: str,
    rev_id_box: list[int],
    bold_override: bool | None = None,
) -> None:
    base_rpr = _clone_first_rpr(p_el)
    _clear_paragraph_runs(p_el)
    if old_text == new_text:
        p_el.append(_make_run(new_text, base_rpr, bold_override=bold_override))
        return

    tok_re = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9._%+-]+|\s+|[^\s]")
    a = tok_re.findall(old_text)
    b = tok_re.findall(new_text)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        old_seg = "".join(a[i1:i2])
        new_seg = "".join(b[j1:j2])
        if tag == "equal":
            if new_seg:
                p_el.append(_make_run(new_seg, base_rpr, bold_override=bold_override))
        elif tag in ("delete", "replace"):
            if old_seg:
                rev_id_box[0] += 1
                del_el = OxmlElement("w:del")
                del_el.set(qn("w:id"), str(rev_id_box[0]))
                del_el.set(qn("w:author"), author)
                del_el.set(qn("w:date"), date_iso)
                del_el.append(_make_run(old_seg, base_rpr, is_del=True))
                p_el.append(del_el)
            if tag == "replace" and new_seg:
                rev_id_box[0] += 1
                ins_el = OxmlElement("w:ins")
                ins_el.set(qn("w:id"), str(rev_id_box[0]))
                ins_el.set(qn("w:author"), author)
                ins_el.set(qn("w:date"), date_iso)
                ins_el.append(_make_run(new_seg, base_rpr, bold_override=bold_override))
                p_el.append(ins_el)
        elif tag == "insert":
            if new_seg:
                rev_id_box[0] += 1
                ins_el = OxmlElement("w:ins")
                ins_el.set(qn("w:id"), str(rev_id_box[0]))
                ins_el.set(qn("w:author"), author)
                ins_el.set(qn("w:date"), date_iso)
                ins_el.append(_make_run(new_seg, base_rpr, bold_override=bold_override))
                p_el.append(ins_el)


def _get_p_plain_text(p_el: Any) -> str:
    return "".join(t.text or "" for t in p_el.iter(qn("w:t")))


def patch_docx_bytes(
    orig_docx_bytes: bytes,
    blocks: list[dict[str, Any]],
    ops: list[dict[str, Any]],
    *,
    mode: str = "clean",  # 'clean' | 'tracked'
    author: str = "PaperDiff",
) -> tuple[bytes, int, list[str]]:
    """
    Patch an original .docx archive IN-PLACE using Typed Patch Ops & XML source_anchors.
    Preserves cover pages, fonts, styles, headers/footers, grant borders, and untouched elements!
    """
    doc = Document(io.BytesIO(orig_docx_bytes))
    body_ps: list[Any] = [ch for ch in doc.element.body.iterchildren() if isinstance(ch, CT_P)]
    body_tbls: list[Any] = [ch for ch in doc.element.body.iterchildren() if isinstance(ch, CT_Tbl)]

    block_by_idx = {int(b["index"]): b for b in blocks}
    warnings: list[str] = []
    applied = 0
    date_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rev_id_box = [5000]

    for op in ops:
        kind = op.get("op", "")
        bidx = int(op.get("block_index", -1))
        blk = block_by_idx.get(bidx)
        if not blk:
            warnings.append(f"跳过无效区块 #{bidx}")
            continue
        anchor = blk.get("source_anchor") or {}

        if kind == "replace_block":
            if anchor.get("kind") != "docx_p":
                warnings.append(f"段落 #{bidx} 缺少 Word XML 锚点，无法原位修改")
                continue
            p_idx = int(anchor.get("body_idx", -1))
            if p_idx < 0 or p_idx >= len(body_ps):
                warnings.append(f"段落 #{bidx} 锚点 body_idx={p_idx} 超出范围")
                continue
            p_el = body_ps[p_idx]
            new_txt = str(op.get("new_raw", op.get("new_text", ""))).strip()
            # Strip markdown heading prefixes if editing a heading block
            if blk.get("block_type") in ("heading", "title"):
                new_txt = re.sub(r"^#{1,6}\s+", "", new_txt).strip()
            if mode == "tracked":
                old_txt = _get_p_plain_text(p_el)
                _set_paragraph_text_tracked(
                    p_el, old_txt, new_txt, author=author, date_iso=date_iso, rev_id_box=rev_id_box
                )
            else:
                _set_paragraph_text_clean(p_el, new_txt)
            applied += 1

        elif kind == "edit_table_cell":
            if anchor.get("kind") != "docx_tbl":
                warnings.append(f"表格 #{bidx} 缺少 Word 表格锚点")
                continue
            t_idx = int(anchor.get("tbl_idx", -1))
            cell_map = anchor.get("cell_map") or []
            r = int(op.get("row", -1))
            c = int(op.get("col", -1))
            if t_idx < 0 or t_idx >= len(body_tbls):
                warnings.append(f"表格 #{bidx} 锚点 tbl_idx={t_idx} 超出范围")
                continue
            if r < 0 or r >= len(cell_map) or c < 0 or c >= len(cell_map[r]):
                warnings.append(f"表格 #{bidx} 单元格 ({r},{c}) 越界")
                continue
            coord = cell_map[r][c]
            tbl_el = body_tbls[t_idx]
            trs = tbl_el.findall(qn("w:tr"))
            tr_i, tc_i = int(coord["tr"]), int(coord["tc"])
            if tr_i >= len(trs):
                continue
            tcs = trs[tr_i].findall(qn("w:tc"))
            if tc_i >= len(tcs):
                continue
            tc_el = tcs[tc_i]
            ps = tc_el.findall(qn("w:p"))
            if not ps:
                p_new = OxmlElement("w:p")
                tc_el.append(p_new)
                ps = [p_new]
            first_p = ps[0]
            # Collapse extra paragraphs in edited cell cleanly
            old_cell_txt = " ".join(_get_p_plain_text(p) for p in ps).strip()
            for extra_p in ps[1:]:
                tc_el.remove(extra_p)
            new_val = str(op.get("new_value", ""))
            bold_flag = op.get("bold")
            bold_ov = bool(bold_flag) if bold_flag is not None else None
            if mode == "tracked":
                _set_paragraph_text_tracked(
                    first_p,
                    old_cell_txt,
                    new_val,
                    author=author,
                    date_iso=date_iso,
                    rev_id_box=rev_id_box,
                    bold_override=bold_ov,
                )
            else:
                _set_paragraph_text_clean(first_p, new_val, bold_override=bold_ov)
            applied += 1

        elif kind == "insert_table_row":
            if anchor.get("kind") != "docx_tbl":
                continue
            t_idx = int(anchor.get("tbl_idx", -1))
            if t_idx < 0 or t_idx >= len(body_tbls):
                continue
            tbl_el = body_tbls[t_idx]
            trs = tbl_el.findall(qn("w:tr"))
            if not trs:
                continue
            after_row = int(op.get("after_row", len(trs) - 1))
            ref_idx = max(0, min(after_row, len(trs) - 1))
            new_tr = copy.deepcopy(trs[ref_idx])
            cells_data = op.get("cells") or []
            tcs = new_tr.findall(qn("w:tc"))
            for ci, tc in enumerate(tcs):
                # Strip vMerge from cloned row so it doesn't corrupt table topology
                tcPr = tc.find(qn("w:tcPr"))
                if tcPr is not None:
                    vm = tcPr.find(qn("w:vMerge"))
                    if vm is not None:
                        tcPr.remove(vm)
                ps = tc.findall(qn("w:p"))
                if not ps:
                    p_new = OxmlElement("w:p")
                    tc.append(p_new)
                    ps = [p_new]
                for extra_p in ps[1:]:
                    tc.remove(extra_p)
                val = str(cells_data[ci]) if ci < len(cells_data) else ""
                _set_paragraph_text_clean(ps[0], val, bold_override=False)
            trs[ref_idx].addnext(new_tr)
            applied += 1

        elif kind == "delete_table_row":
            if anchor.get("kind") != "docx_tbl":
                continue
            t_idx = int(anchor.get("tbl_idx", -1))
            cell_map = anchor.get("cell_map") or []
            r_del = int(op.get("row", -1))
            if t_idx < 0 or t_idx >= len(body_tbls) or r_del < 0 or r_del >= len(cell_map):
                continue
            tr_i = int(cell_map[r_del][0]["tr"]) if cell_map[r_del] else r_del
            tbl_el = body_tbls[t_idx]
            trs = tbl_el.findall(qn("w:tr"))
            if tr_i < 0 or tr_i >= len(trs):
                continue
            # Refuse to delete row with vertical merge to keep OOXML valid
            has_vmerge = any(tc.find(f".//{qn('w:vMerge')}") is not None for tc in trs[tr_i].findall(qn("w:tc")))
            if has_vmerge:
                warnings.append(f"表格 #{bidx} 第 {r_del + 1} 行包含跨行合并单元格，已跳过删除")
                continue
            tbl_el.remove(trs[tr_i])
            applied += 1

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue(), applied, warnings
