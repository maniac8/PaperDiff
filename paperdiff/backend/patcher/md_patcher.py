"""Format-preserving Markdown round-trip patcher using exact line-range anchors."""
from __future__ import annotations

import json
import re
from typing import Any


def _format_gfm_table(
    rows: list[list[dict[str, Any]]],
    alignments: list[str] | None = None,
    *,
    preserve_rich_comment: bool = False,
    table_meta: dict[str, Any] | None = None,
    anchor: dict[str, Any] | None = None,
) -> str:
    if not rows:
        return ""
    lines: list[str] = []
    if anchor and anchor.get("kind") == "docx_tbl":
        lines.append("<!-- PAPERDIFF_ANCHOR:" + json.dumps(anchor, ensure_ascii=False) + " -->")
    if table_meta:
        lines.append("<!-- PAPERDIFF_TABLE_META:" + json.dumps(table_meta, ensure_ascii=False) + " -->")
    if preserve_rich_comment:
        rich_out = [
            [
                {
                    "text": str(c.get("text", "")),
                    "colspan": int(c.get("colspan", 1)),
                    "rowspan": int(c.get("rowspan", 1)),
                    "bold": bool(c.get("bold", False)),
                }
                for c in r
            ]
            for r in rows
        ]
        lines.append("<!-- PAPERDIFF_TABLE:" + json.dumps(rich_out, ensure_ascii=False) + " -->")

    col_count = max(len(r) for r in rows)
    aligns = alignments or []
    sep_cells: list[str] = []
    for ci in range(col_count):
        al = aligns[ci] if ci < len(aligns) else "left"
        if al == "center":
            sep_cells.append(":---:")
        elif al == "right":
            sep_cells.append("---:")
        else:
            sep_cells.append("---")

    for r_idx, row in enumerate(rows):
        cells_str: list[str] = []
        for ci in range(col_count):
            if ci < len(row):
                c = row[ci]
                txt = str(c.get("text", "")).replace("|", "\\|").strip()
                if c.get("bold") and txt and not (txt.startswith("**") and txt.endswith("**")):
                    txt = f"**{txt}**"
                cells_str.append(txt)
            else:
                cells_str.append("")
        lines.append("| " + " | ".join(cells_str) + " |")
        if r_idx == 0:
            lines.append("| " + " | ".join(sep_cells) + " |")
    return "\n".join(lines)


def patch_markdown_content(
    content: str,
    blocks: list[dict[str, Any]],
    ops: list[dict[str, Any]],
) -> tuple[str, int, list[str]]:
    """Apply Typed Patch Ops directly to Markdown (or Word-intermediate Markdown) using exact line anchors."""
    norm = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = norm.split("\n")
    block_by_idx = {int(b["index"]): b for b in blocks}
    warnings: list[str] = []

    # Group ops by block_index so multiple cell edits on one table apply together cleanly
    ops_by_blk: dict[int, list[dict[str, Any]]] = {}
    for op in ops:
        bidx = int(op.get("block_index", -1))
        if bidx in block_by_idx:
            ops_by_blk.setdefault(bidx, []).append(op)
        else:
            warnings.append(f"跳过无效区块 #{bidx}")

    # Collect (line_start, line_end, replacement_lines)
    line_edits: list[tuple[int, int, list[str]]] = []
    applied = 0

    for bidx, b_ops in ops_by_blk.items():
        blk = block_by_idx[bidx]
        anchor = blk.get("source_anchor") or {}
        rs = blk.get("raw_start")
        re_pos = blk.get("raw_end")

        # Determine line span [ls, le)
        if anchor.get("kind") == "md_lines":
            ls = int(anchor["line_start"])
            le = int(anchor["line_end"])
        elif rs is not None and re_pos is not None:
            ls = norm[: int(rs)].count("\n")
            le = norm[: int(re_pos)].count("\n") + 1
        else:
            # Fallback: find raw_text occurrence
            raw_t = (blk.get("raw_text") or "").strip()
            pos = norm.find(raw_t) if raw_t else -1
            if pos == -1:
                warnings.append(f"区块 #{bidx} 未找到行锚点，已跳过")
                continue
            ls = norm[:pos].count("\n")
            le = norm[: pos + len(raw_t)].count("\n") + 1

        # Also include immediately preceding <!-- PAPERDIFF_TABLE... --> lines if editing a table
        if blk.get("block_type") == "table":
            scan = ls - 1
            while scan >= 0 and lines[scan].strip().startswith("<!-- PAPERDIFF_TABLE"):
                ls = scan
                scan -= 1

            # Clone current table rows
            cur_rows_raw = blk.get("table_rows") or []
            rows: list[list[dict[str, Any]]] = [
                [
                    {
                        "text": str(c.get("text", "")),
                        "colspan": int(c.get("colspan", 1)),
                        "rowspan": int(c.get("rowspan", 1)),
                        "bold": bool(c.get("bold", False)),
                    }
                    for c in r
                ]
                for r in cur_rows_raw
            ]
            for op in b_ops:
                kind = op.get("op", "")
                if kind == "edit_table_cell":
                    r_i = int(op.get("row", -1))
                    c_i = int(op.get("col", -1))
                    if 0 <= r_i < len(rows) and 0 <= c_i < len(rows[r_i]):
                        rows[r_i][c_i]["text"] = str(op.get("new_value", ""))
                        if "bold" in op:
                            rows[r_i][c_i]["bold"] = bool(op["bold"])
                        applied += 1
                elif kind == "insert_table_row":
                    after_r = int(op.get("after_row", len(rows) - 1))
                    cells = op.get("cells") or []
                    col_n = max((len(r) for r in rows), default=len(cells) or 1)
                    new_row = [
                        {
                            "text": str(cells[ci]) if ci < len(cells) else "",
                            "colspan": 1,
                            "rowspan": 1,
                            "bold": False,
                        }
                        for ci in range(col_n)
                    ]
                    ins_pos = max(0, min(after_r + 1, len(rows)))
                    rows.insert(ins_pos, new_row)
                    applied += 1
                elif kind == "delete_table_row":
                    r_del = int(op.get("row", -1))
                    if 0 <= r_del < len(rows):
                        if any(c.get("rowspan", 1) > 1 or c.get("colspan", 1) > 1 for c in rows[r_del]):
                            warnings.append(f"表格 #{bidx} 第 {r_del + 1} 行包含合并单元格，已跳过删除")
                            continue
                        rows.pop(r_del)
                        applied += 1

            has_rich = any(c["colspan"] > 1 or c["rowspan"] > 1 or c["bold"] for r in rows for c in r)
            new_tbl_md = _format_gfm_table(
                rows,
                alignments=blk.get("table_alignments"),
                preserve_rich_comment=has_rich,
                table_meta={"role": blk.get("table_role"), "zone": blk.get("zone")} if blk.get("table_role") == "metadata_form" else None,
            )
            line_edits.append((ls, le, new_tbl_md.split("\n")))
        else:
            op = b_ops[-1]
            kind = op.get("op", "")
            new_raw = str(op.get("new_raw", op.get("new_text", ""))).strip()
            if kind == "replace_math" and not new_raw.startswith(("$$", r"\[")):
                new_raw = f"$$\n{new_raw}\n$$"
            elif blk.get("block_type") == "heading" and not re.match(r"^#{1,6}\s+", new_raw):
                lvl = max(1, min(4, int(blk.get("section_level") or 1)))
                new_raw = f"{'#' * lvl} {new_raw}"
            elif blk.get("block_type") == "caption" and not new_raw.startswith(">"):
                cap_clean = re.sub(r"^\[Caption\]\s*", "", new_raw)
                new_raw = f"> [Caption] {cap_clean}"
            line_edits.append((ls, le, new_raw.split("\n")))
            applied += 1

    # Apply line edits from bottom to top
    line_edits.sort(key=lambda x: x[0], reverse=True)
    last_s = len(lines) + 1
    for ls, le, rep_lines in line_edits:
        if le > last_s:
            continue
        lines[ls:le] = rep_lines
        last_s = ls

    return "\n".join(lines), applied, warnings
