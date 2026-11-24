"""Three-Zone document classifier (frontmatter / body / backmatter) and metadata table heuristics."""
from __future__ import annotations

import re
from typing import Any

from .ir import DocumentBlock, _strip_inline_markers_fast

_COVER_KV_KEYS = (
    "题目", "论文题目", "題目", "姓名", "学号", "學號", "院系", "学院", "學院",
    "专业", "專業", "导师", "指导教师", "指導老師", "指导老师", "学位", "學位",
    "课程", "課程", "日期", "年级", "班级", "分类号", "密级", "项目名称",
    "申请人", "依托单位", "资助类别", "亚类说明", "附注说明", "学科代码",
    "student no", "supervisor", "advisor", "faculty", "department", "program", "major", "degree",
)

_COVER_LINE_RE = re.compile(
    r"^(?:"
    r".*(?:研究生学位论文|学位论文|毕业论文|申请书|申报书|开题报告|Supplementary Information for).*|"
    r"(?:分类号|密级|UDC|学校代码|学号|學號|姓名|指导教师|导师|学院|专业|日期|二[〇零一二三四五六七八九十]{2,4}年[一二三四五六七八九十]{1,2}月).*|"
    r"(?:原创性声明|独创性声明|关于论文使用授权的说明|学位论文版权使用授权书|版权声明).*|"
    r"(?:目\s*录|图\s*目\s*录|表\s*目\s*录|Contents|Table of Contents|List of Figures|List of Tables)$"
    r")",
    re.IGNORECASE,
)

_BODY_START_HEADING_RE = re.compile(
    r"^(?:"
    r"摘\s*要|中文摘要|英文摘要|Abstract|Executive Summary|"
    r"引\s*言|绪\s*论|背\s*景|Introduction|Background|Overview|"
    r"第[一二三四五六七八九十百\d]+[章节篇部分]|"
    r"Chapter\s+1\b|1[\.\s、]+\S+|I\.\s+\S+|"
    r"一、\S+|Part\s+1\b|Section\s+1\b"
    r")",
    re.IGNORECASE,
)

_REF_HEADING_RE = re.compile(
    r"^(?:参考文献|References|Bibliography|Works Cited|Literature Cited)$",
    re.IGNORECASE,
)

_BACKMATTER_HEADING_RE = re.compile(
    r"^(?:参考文献|References|Bibliography|Works Cited|致\s*谢|鸣\s*谢|Acknowledgements?|Acknowledgments?)$",
    re.IGNORECASE,
)


def _is_metadata_form_table(rows: list[list[dict[str, Any]]], *, borderless: bool = False) -> bool:
    """Detect thesis cover / grant application key-value layout tables so they are NOT rendered as 3-line data tables."""
    if not rows or len(rows) < 2:
        return False
    max_cols = max(len(r) for r in rows)
    if max_cols > 4:
        return False

    kv_hits = 0
    colon_rows = 0
    for row in rows:
        texts = [_strip_inline_markers_fast(str(c.get("text", ""))).strip() for c in row]
        joined_first = re.sub(r"\s+", "", texts[0]).lower() if texts else ""
        joined_row = " ".join(texts).lower()
        if any(k in joined_first or (len(texts) >= 2 and k in texts[0].lower()) for k in _COVER_KV_KEYS):
            kv_hits += 1
        if len(texts) >= 2 and (
            texts[0].endswith((":", "："))
            or (len(texts) >= 3 and texts[1] in (":", "："))
        ):
            colon_rows += 1
        elif any(k in joined_row for k in ("student no", "supervisor", "指导教师", "导师姓名", "依托单位", "项目名称")):
            kv_hits += 1

    if kv_hits >= 2:
        return True
    if borderless and colon_rows >= 3 and len(rows) <= 15:
        return True
    return False


def _classify_document_zones(
    blocks: list[DocumentBlock],
    *,
    allow_h1_title_promote: bool = True,
) -> list[DocumentBlock]:
    """
    Detect thesis/grant cover pages & frontmatter cleanly WITHOUT false-positively hiding
    normal opening paragraphs of regular articles or manuals.
    """
    if not blocks:
        return blocks

    first_body_heading_idx: int | None = None
    for idx, b in enumerate(blocks):
        if b.block_type == "heading" and b.zone != "frontmatter":
            plain = _strip_inline_markers_fast(b.clean_text).strip()
            if _BODY_START_HEADING_RE.match(plain):
                first_body_heading_idx = idx
                break

    scan_end = first_body_heading_idx if first_body_heading_idx is not None else min(len(blocks), 18)
    has_strong_fm_signal = False
    for b in blocks[:scan_end]:
        if b.zone == "frontmatter" or (b.meta or {}).get("table_role") == "metadata_form":
            has_strong_fm_signal = True
            break
        plain = _strip_inline_markers_fast(b.clean_text).strip()
        if _COVER_LINE_RE.match(plain):
            has_strong_fm_signal = True
            break

    if has_strong_fm_signal:
        if first_body_heading_idx is not None:
            fm_cutoff = first_body_heading_idx
        else:
            fm_cutoff = 0
            for idx, b in enumerate(blocks[: min(len(blocks), 35)]):
                plain = _strip_inline_markers_fast(b.clean_text).strip()
                is_affil = bool(re.match(r"^[⁰¹²³⁴⁵⁶⁷⁸⁹\d]{1,2}\s*[A-Z\u4e00-\u9fff]", plain)) and len(plain) < 160
                if (
                    b.zone == "frontmatter"
                    or (b.meta or {}).get("table_role") == "metadata_form"
                    or _COVER_LINE_RE.match(plain)
                    or is_affil
                    or (b.block_type == "paragraph" and len(plain) < 60 and idx <= fm_cutoff + 2)
                ):
                    fm_cutoff = idx + 1
                elif b.block_type == "heading":
                    break
        for idx in range(fm_cutoff):
            if blocks[idx].block_type != "title":
                blocks[idx].zone = "frontmatter"

    if allow_h1_title_promote and not any(b.block_type == "title" for b in blocks):
        h1_indices = [
            idx
            for idx, b in enumerate(blocks)
            if b.block_type == "heading" and b.section_level == 1 and b.zone == "body"
        ]
        h2_plus = any(b.block_type == "heading" and b.section_level >= 2 and b.zone == "body" for b in blocks)
        if len(h1_indices) == 1 and h2_plus and h1_indices[0] <= 1:
            tb = blocks[h1_indices[0]]
            plain_t = _strip_inline_markers_fast(tb.clean_text).strip()
            if not _BODY_START_HEADING_RE.match(plain_t):
                tb.block_type = "title"
                tb.section_level = 0

    for idx, b in enumerate(blocks):
        b.index = idx
    return blocks
