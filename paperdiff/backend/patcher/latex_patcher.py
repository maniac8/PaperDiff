"""Format-preserving LaTeX & Overleaf .zip round-trip patcher."""
from __future__ import annotations

import io
import re
import zipfile
from typing import Any


def _escape_latex_cell_text(txt: str) -> str:
    """Keep LaTeX math/commands intact; escape bare unescaped % or & if user typed plain prose."""
    s = txt.strip()
    # Do not double-escape already escaped characters or math
    if "$" not in s and "\\" not in s:
        s = s.replace("%", r"\%").replace("&", r"\&").replace("_", r"\_")
    return s


def _collect_latex_span_replacements(
    content: str,
    blocks: list[dict[str, Any]],
    ops: list[dict[str, Any]],
) -> tuple[list[tuple[int, int, str]], list[str]]:
    """Convert Typed Patch Ops into non-overlapping (start, end, replacement) character spans."""
    block_by_idx = {int(b["index"]): b for b in blocks}
    replacements: list[tuple[int, int, str]] = []
    warnings: list[str] = []

    # Group table ops by block_index so multiple cell edits in one table combine cleanly
    table_ops_by_blk: dict[int, list[dict[str, Any]]] = {}

    for op in ops:
        kind = op.get("op", "")
        bidx = int(op.get("block_index", -1))
        blk = block_by_idx.get(bidx)
        if not blk:
            warnings.append(f"跳过无效区块索引 #{bidx}")
            continue

        if kind in ("replace_block", "replace_math"):
            rs = blk.get("raw_start")
            re_pos = blk.get("raw_end")
            if rs is None or re_pos is None or rs < 0 or re_pos > len(content) or rs > re_pos:
                warnings.append(f"区块 #{bidx} 缺少精确源码偏移，已跳过")
                continue
            new_raw = str(op.get("new_raw", op.get("new_text", "")))
            if kind == "replace_math":
                # Preserve surrounding equation environment / $$ delimiters if user passed bare math expression
                orig_slice = content[rs:re_pos]
                if not new_raw.strip().startswith(("\\begin{", "$$", "\\[")):
                    m_env = re.match(r"^(\\begin\{[^}]+\}(?:\s*\\label\{[^}]+\})?\s*)([\s\S]*?)(\s*\\end\{[^}]+\})$", orig_slice)
                    if m_env:
                        new_raw = f"{m_env.group(1)}{new_raw.strip()}{m_env.group(3)}"
                    elif orig_slice.strip().startswith("$$") and orig_slice.strip().endswith("$$"):
                        new_raw = f"$$\n{new_raw.strip()}\n$$"
                    elif orig_slice.strip().startswith(r"\[") and orig_slice.strip().endswith(r"\]"):
                        new_raw = f"\\[\n{new_raw.strip()}\n\\]"
            replacements.append((int(rs), int(re_pos), new_raw))

        elif kind in ("edit_table_cell", "insert_table_row", "delete_table_row"):
            table_ops_by_blk.setdefault(bidx, []).append(op)

    # Apply table operations
    for bidx, t_ops in table_ops_by_blk.items():
        blk = block_by_idx[bidx]
        anchor = blk.get("source_anchor") or {}
        cell_spans = anchor.get("cell_spans") or []
        t_start = blk.get("raw_start")
        t_end = blk.get("raw_end")

        has_structural_row_op = any(o.get("op") in ("insert_table_row", "delete_table_row") for o in t_ops)

        if not has_structural_row_op and cell_spans:
            # Pure cell edits: surgical in-place span patching (preserves 100% of booktabs/cmidrule/comments!)
            for op in t_ops:
                r = int(op.get("row", -1))
                c = int(op.get("col", -1))
                if r < 0 or r >= len(cell_spans) or c < 0 or c >= len(cell_spans[r]):
                    warnings.append(f"表格 #{bidx} 单元格 ({r},{c}) 超出范围")
                    continue
                sp = cell_spans[r][c]
                if not sp or sp.get("outer_s") is None or sp.get("outer_e") is None:
                    warnings.append(f"表格 #{bidx} 单元格 ({r},{c}) 含复杂宏，无法原位定位")
                    continue
                val = _escape_latex_cell_text(str(op.get("new_value", "")))
                is_bold = bool(op.get("bold", sp.get("was_bold", False)))
                formatted = f"\\textbf{{{val}}}" if is_bold and val else val
                replacements.append((int(sp["outer_s"]), int(sp["outer_e"]), formatted))
        elif t_start is not None and t_end is not None:
            # Structural row insert/delete + cell edits inside tabular body
            tbl_src = content[t_start:t_end]
            # Apply cell edits first in reverse offset order relative to t_start
            local_cell_reps: list[tuple[int, int, str]] = []
            for op in t_ops:
                if op.get("op") == "edit_table_cell":
                    r = int(op.get("row", -1))
                    c = int(op.get("col", -1))
                    if 0 <= r < len(cell_spans) and 0 <= c < len(cell_spans[r]) and cell_spans[r][c]:
                        sp = cell_spans[r][c]
                        val = _escape_latex_cell_text(str(op.get("new_value", "")))
                        is_bold = bool(op.get("bold", sp.get("was_bold", False)))
                        formatted = f"\\textbf{{{val}}}" if is_bold and val else val
                        local_cell_reps.append((int(sp["outer_s"]) - t_start, int(sp["outer_e"]) - t_start, formatted))
            local_cell_reps.sort(key=lambda x: x[0], reverse=True)
            patched_tbl = tbl_src
            for ls, le, rep in local_cell_reps:
                if 0 <= ls <= le <= len(patched_tbl):
                    patched_tbl = patched_tbl[:ls] + rep + patched_tbl[le:]

            # Handle row insertions before \bottomrule or \end{tabular...}
            for op in t_ops:
                if op.get("op") == "insert_table_row":
                    cells = op.get("cells") or []
                    row_tex = " & ".join(_escape_latex_cell_text(str(x)) for x in cells) + r" \\"
                    m_ins = re.search(r"(\n[ \t]*\\bottomrule|\n[ \t]*\\hline\s*\n[ \t]*\\end\{tabular|\n[ \t]*\\end\{(?:tabular\*?|tabularx|longtable)\})", patched_tbl)
                    if m_ins:
                        pos_ins = m_ins.start()
                        patched_tbl = patched_tbl[:pos_ins] + "\n" + row_tex + patched_tbl[pos_ins:]
                    else:
                        patched_tbl = patched_tbl + "\n" + row_tex
                elif op.get("op") == "delete_table_row":
                    r_del = int(op.get("row", -1))
                    # Locate row using cell_spans first/last offset in that row if non-merged
                    if 0 <= r_del < len(cell_spans) and cell_spans[r_del]:
                        valid_sps = [s for s in cell_spans[r_del] if s and s.get("outer_s") is not None]
                        if valid_sps:
                            line_s = patched_tbl.rfind("\n", 0, max(0, int(valid_sps[0]["outer_s"]) - t_start))
                            line_s = line_s + 1 if line_s != -1 else 0
                            line_e = patched_tbl.find("\n", max(0, int(valid_sps[-1]["outer_e"]) - t_start))
                            line_e = (line_e + 1) if line_e != -1 else len(patched_tbl)
                            patched_tbl = patched_tbl[:line_s] + patched_tbl[line_e:]

            replacements.append((int(t_start), int(t_end), patched_tbl))

    return replacements, warnings


def patch_latex_content(
    content: str,
    blocks: list[dict[str, Any]],
    ops: list[dict[str, Any]],
) -> tuple[str, int, list[str]]:
    """Apply Typed Patch Ops directly to a single .tex string with zero unrelated drift."""
    replacements, warnings = _collect_latex_span_replacements(content, blocks, ops)
    # Sort descending and deduplicate overlapping spans defensively
    replacements.sort(key=lambda x: (x[0], x[1]), reverse=True)
    patched = content
    applied = 0
    last_start = len(content) + 1
    for rs, re_pos, rep in replacements:
        if re_pos > last_start:
            warnings.append(f"跳过重叠补丁区间 ({rs}, {re_pos})")
            continue
        patched = patched[:rs] + rep + patched[re_pos:]
        last_start = rs
        applied += 1
    return patched, applied, warnings


def patch_latex_zip_bytes(
    orig_zip_bytes: bytes,
    source_map: list[dict[str, Any]],
    expanded_content: str,
    blocks: list[dict[str, Any]],
    ops: list[dict[str, Any]],
) -> tuple[bytes, str, int, list[str]]:
    """
    Apply Typed Patch Ops to BOTH the expanded .tex string AND the original Overleaf .zip archive!
    Projects expanded offsets back to exact member files via source_map and repacks untouched assets byte-for-byte.
    """
    replacements, warnings = _collect_latex_span_replacements(expanded_content, blocks, ops)
    patched_expanded, applied, w2 = patch_latex_content(expanded_content, blocks, ops)
    warnings.extend(w2)

    # Project each (rs, re_pos, rep) into member file edits
    member_edits: dict[str, list[tuple[int, int, str]]] = {}
    for rs, re_pos, rep in replacements:
        mapped = False
        for seg in source_map:
            es = int(seg["exp_start"])
            ee = int(seg["exp_end"])
            if es <= rs and re_pos <= ee:
                ms = int(seg["member_start"]) + (rs - es)
                me = int(seg["member_start"]) + (re_pos - es)
                member_edits.setdefault(str(seg["member"]), []).append((ms, me, rep))
                mapped = True
                break
        if not mapped:
            warnings.append(f"补丁区间 ({rs}, {re_pos}) 跨越多个子文件边界，仅更新合并源码")

    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(orig_zip_bytes), "r") as zin, zipfile.ZipFile(
        buf, "w", compression=zipfile.ZIP_DEFLATED
    ) as zout:
        for info in zin.infolist():
            raw = zin.read(info.filename)
            norm_name = info.filename.lstrip("./")
            edits = member_edits.get(norm_name) or member_edits.get(info.filename)
            if edits:
                txt = raw.decode("utf-8", errors="replace")
                edits.sort(key=lambda x: (x[0], x[1]), reverse=True)
                last_s = len(txt) + 1
                for ms, me, rep in edits:
                    if 0 <= ms <= me <= len(txt) and me <= last_s:
                        txt = txt[:ms] + rep + txt[me:]
                        last_s = ms
                zout.writestr(info, txt.encode("utf-8"))
            else:
                zout.writestr(info, raw)
    return buf.getvalue(), patched_expanded, applied, warnings
