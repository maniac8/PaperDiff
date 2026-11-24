"""Academic Manuscript Analysis, 4-Dimension Fact-Conservation Audit & LRU Preview Engine.

Upstream:
    Consumes structured `DocumentBlock` IR from `backend.parsers.parse_document_with_meta`
    and alignment/diff primitives from `backend.diff_engine`.

Downstream:
    Produces serialized payloads for `SingleDocWorkspace` (`preview_document`),
    `DiffWorkspace` (`compare_documents`), and `backend.export.html_print`.

Key capabilities & invariants:
    - Bounded in-memory LRU caches (`_PREVIEW_CACHE`, `_COMPARE_CACHE`, max 32 entries)
      keyed by SHA-256 of content + settings, accelerating repeated large-manuscript loads >15x.
    - Pure-local 4-dimension fact conservation: numeric/percentage/p-value drift, citation add/drop
      & undefined `.bib` keys, broken cross-references, math symbol changes, protected-term swaps,
      claim-strength escalation, and table bold-optimum drift (`+B / -B`).
    - Footnotes are exported BOTH as marker-stripped plain text (`footnotes`) and parsed
      `DisplayItem[]` trees (`footnote_items`) so internal `⟦CODE⟧/⟦MATH⟧` markers never leak.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter, OrderedDict
from typing import Any

from .diff_engine import (
    ATOMIC_TOKEN_RE,
    _extract_math_inner,
    align_blocks,
    count_academic_words,
    diff_math_expression,
    diff_paragraph,
    diff_table_rows,
    serialize_plain_table_rows,
    strip_rich_markers,
    strip_style_markers,
    text_to_display_items,
)
from .parsers import parse_document_with_meta

# Bounded in-memory LRU caches so switching documents/tabs on 50k-word theses takes < 5 ms!
_PREVIEW_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_COMPARE_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_CACHE_MAX = 32


def _make_cache_key(*parts: Any) -> str:
    h = hashlib.sha256()
    for p in parts:
        if isinstance(p, str):
            h.update(p.encode("utf-8", errors="ignore"))
        else:
            h.update(json.dumps(p, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _cache_get(cache: OrderedDict[str, dict[str, Any]], key: str) -> dict[str, Any] | None:
    hit = cache.get(key)
    if hit is not None:
        cache.move_to_end(key)
        return copy.deepcopy(hit)
    return None


def _cache_put(cache: OrderedDict[str, dict[str, Any]], key: str, val: dict[str, Any]) -> None:
    cache[key] = copy.deepcopy(val)
    cache.move_to_end(key)
    while len(cache) > _CACHE_MAX:
        cache.popitem(last=False)

EN_AI_CLICHES_WORDS = {
    "delve", "delves", "delving", "tapestry", "paradigm", "paradigms",
    "fundamental", "fundamentally", "pervasive", "multifaceted", "intricate",
    "pivotal", "paramount", "underscore", "underscores", "underscoring",
    "leverage", "leverages", "leveraging", "foster", "fosters", "fostering",
    "bolster", "bolsters", "seamless", "seamlessly", "holistic", "realm",
    "nuanced", "exhibits", "exhibit", "auditable", "moreover", "furthermore",
    "notably", "crucially", "meticulous", "meticulously", "comprehensive",
    "groundbreaking", "unprecedented", "myriad", "plethora", "endeavor",
    "facilitate", "facilitates", "utilize", "utilizes", "utilizing",
    "harness", "harnessing", "elucidate", "elucidates", "testament",
    "aforementioned", "robustness", "synergy", "cornerstone", "transformative",
}

EN_AI_CLICHES_PHRASES = [
    "in the realm of",
    "it is worth noting",
    "plays a pivotal role",
    "sheds light on",
    "paves the way",
    "in this context",
    "a testament to",
    "stands as a",
    "serves as a",
    "in conclusion, it is",
]

ZH_AI_CLICHES = [
    "值得注意的是", "总而言之", "综上所述", "不可或缺", "至关重要",
    "赋能", "显著提升", "全方位", "深度融合", "与此同时",
    "显而易见", "不容忽视", "进一步地", "具有重要意义", "不言而喻",
    "毋庸置疑", "极大程度", "提供有力支撑", "奠定坚实基础",
]

DEFAULT_EN_AI_WORDS = sorted(EN_AI_CLICHES_WORDS)
DEFAULT_EN_AI_PHRASES = list(EN_AI_CLICHES_PHRASES)
DEFAULT_ZH_AI_CLICHES = list(ZH_AI_CLICHES)

EN_HEDGES = {
    "may", "might", "could", "can", "suggest", "suggests", "suggested",
    "appear", "appears", "seem", "seems", "largely", "mostly", "partially",
    "likely", "potentially", "approximately", "roughly", "indicate", "indicates",
    "tend", "tends", "often", "typically", "commonly", "relatively",
}

EN_BOOSTERS = {
    "prove", "proves", "proven", "conclusively", "undoubtedly", "always",
    "never", "completely", "guarantee", "guarantees", "eliminates",
    "definitively", "unquestionably", "clearly", "obviously", "certainly",
    "dramatically", "overwhelmingly", "entirely", "exact",
}

ZH_HEDGES = ["可能", "或许", "表明", "倾向于", "在一定程度上", "大致", "相对", "初步", "往往"]
ZH_BOOSTERS = ["绝对", "完全证明", "必然", "毫无疑问", "彻底消除", "始终", "显著优于", "完全解决"]

NUMBER_RE = re.compile(
    r"(?:p\s*[<>≤≥=]\s*0?\.\d+(?:[eE][+-]?\d+)?|"
    r"n\s*=\s*\d+|"
    r"(?<![A-Za-z_])\d+(?:\.\d+)?(?:\s*[±]\s*\d+(?:\.\d+)?)?(?:[eE][+-]?\d+)?%?)",
    re.IGNORECASE,
)

TEXT_REF_RE = re.compile(
    r"\b(?:Fig(?:ure)?s?\.?|Tab(?:le)?s?\.?|Eq(?:uation)?s?\.?|Sec(?:tion)?s?\.?)\s*\d+[A-Za-z]?|"
    r"(?:图|表|公式|第)\s*\d+(?:\.\d+)?",
    re.IGNORECASE,
)
TEXT_CITE_RE = re.compile(r"\[[0-9,\s–-]{1,20}\]|\([A-Z][A-Za-z-]+(?:\s+et\s+al\.)?,\s*(?:19|20)\d{2}[a-z]?\)")


def _strip_atomic(text: str) -> str:
    s = strip_style_markers(text)

    def _repl(m: re.Match[str]) -> str:
        kind, val = m.group(1), m.group(2)
        if kind == "CODE":
            return f" {val} "
        if kind == "LINK":
            return f" {val.split('|', 1)[0]} "
        return " "

    return ATOMIC_TOKEN_RE.sub(_repl, s)


def _compute_doc_language(clean_body_text: str) -> tuple[str, float]:
    """Classify dominant manuscript language from body prose CJK ratio.

    Args:
        clean_body_text: Concatenated body prose `clean_text` (excluding code/tables/frontmatter).

    Returns:
        Tuple `(doc_language, cjk_ratio)` where `doc_language` is `'zh'` (`>= 0.25`),
        `'en'` (`< 0.05`), or `'mixed'`.
    """
    plain = _strip_atomic(clean_body_text)
    cjk_cnt = len(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", plain))
    latin_cnt = len(re.findall(r"[A-Za-z]", plain))
    total = cjk_cnt + latin_cnt
    if total == 0:
        return "en", 0.0
    ratio = round(cjk_cnt / total, 4)
    if ratio >= 0.25:
        return "zh", ratio
    if ratio < 0.05:
        return "en", ratio
    return "mixed", ratio


def _resolve_lexicon(custom_lexicon: dict[str, list[str]] | None) -> tuple[set[str], list[str], list[str]]:
    muted = {x.strip().lower() for x in (custom_lexicon or {}).get("muted", []) if x.strip()}
    added_en = [x.strip().lower() for x in (custom_lexicon or {}).get("added_en", []) if x.strip()]
    added_zh = [x.strip() for x in (custom_lexicon or {}).get("added_zh", []) if x.strip()]

    en_words = (EN_AI_CLICHES_WORDS | {w for w in added_en if " " not in w}) - muted
    en_phrases = [p for p in EN_AI_CLICHES_PHRASES if p.lower() not in muted] + [
        p for p in added_en if " " in p and p not in muted
    ]
    zh_words = [z for z in ZH_AI_CLICHES if z.lower() not in muted] + [
        z for z in added_zh if z.lower() not in muted
    ]
    return en_words, en_phrases, zh_words


def extract_ai_isms(text: str, custom_lexicon: dict[str, list[str]] | None = None) -> list[str]:
    en_words, en_phrases, zh_words = _resolve_lexicon(custom_lexicon)
    plain = _strip_atomic(text)
    low = plain.lower()
    found: list[str] = []
    for phrase in en_phrases:
        for _ in re.finditer(re.escape(phrase), low):
            found.append(phrase)
    for w in re.findall(r"\b[a-z]+\b", low):
        if w in en_words:
            found.append(w)
    for zh in zh_words:
        for _ in re.finditer(re.escape(zh), plain):
            found.append(zh)
    return found


def _extract_facts(text: str) -> dict[str, list[str]]:
    refs: list[str] = []
    cites: list[str] = []
    maths: list[str] = []
    for m in ATOMIC_TOKEN_RE.finditer(text):
        kind, val = m.group(1), m.group(2)
        if kind == "REF":
            refs.append(val)
        elif kind == "CITE":
            for k in val.split(","):
                k = k.strip()
                if k:
                    cites.append(k)
        elif kind == "MATH":
            maths.append(val)

    plain = _strip_atomic(text)
    for m in TEXT_REF_RE.finditer(plain):
        refs.append(re.sub(r"\s+", " ", m.group(0).strip()))

    for m in TEXT_CITE_RE.finditer(plain):
        raw_cite = m.group(0).strip()
        if raw_cite.startswith("[") and raw_cite.endswith("]"):
            inner = raw_cite[1:-1]
            for piece in re.split(r"\s*,\s*", inner):
                piece = piece.strip()
                if not piece:
                    continue
                rng = re.fullmatch(r"(\d+)\s*[–-]\s*(\d+)", piece)
                if rng:
                    start_n, end_n = int(rng.group(1)), int(rng.group(2))
                    if 0 < end_n - start_n <= 20:
                        for k in range(start_n, end_n + 1):
                            cites.append(f"[{k}]")
                    else:
                        cites.append(f"[{piece}]")
                else:
                    cites.append(f"[{piece}]")
        else:
            cites.append(raw_cite)

    plain_for_nums = TEXT_CITE_RE.sub(" ", plain)
    plain_for_nums = TEXT_REF_RE.sub(" ", plain_for_nums)

    nums: list[str] = []
    for m in NUMBER_RE.finditer(plain_for_nums):
        val = re.sub(r"\s+", "", m.group(0))
        if re.search(r"[.%=<>±eE]", val) or len(val) >= 2:
            nums.append(val)

    return {"numbers": nums, "citations": cites, "refs": refs, "maths": maths}


def _count_syllables_en(word: str) -> int:
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    groups = re.findall(r"[aeiouy]{1,2}", w)
    return max(1, len(groups))


def compute_style_metrics(text: str, custom_lexicon: dict[str, list[str]] | None = None) -> dict[str, Any]:
    plain = _strip_atomic(text).strip()
    if not plain:
        return {
            "word_count": 0,
            "sentence_count": 0,
            "avg_sentence_len": 0.0,
            "long_sentence_ratio": 0.0,
            "flesch_kincaid_grade": None,
            "flesch_reading_ease": None,
            "lexical_diversity": 0.0,
            "passive_voice_ratio": 0.0,
            "ai_ism_count": 0,
            "ai_ism_density": 0.0,
            "ai_isms": [],
            "hedge_count": 0,
            "booster_count": 0,
        }

    raw_sents = [s.strip() for s in re.split(r"(?<=[.!?。！？])\s+", plain) if len(s.strip()) > 2]
    if not raw_sents:
        raw_sents = [plain]

    en_words = re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)*", plain)
    zh_chars = re.findall(r"[\u4e00-\u9fff]", plain)
    is_mostly_zh = len(zh_chars) > len(en_words)

    total_words = max(1, count_academic_words(text))
    sent_lens = [count_academic_words(s) for s in raw_sents]
    avg_sent_len = sum(sent_lens) / max(1, len(sent_lens))
    long_thresh = 55 if is_mostly_zh else 35
    long_sents = sum(1 for l in sent_lens if l > long_thresh)
    long_ratio = long_sents / max(1, len(sent_lens))

    fk_grade = None
    fk_ease = None
    if len(en_words) >= 15 and not is_mostly_zh:
        syllables = sum(_count_syllables_en(w) for w in en_words)
        wps = len(en_words) / max(1, len(raw_sents))
        spw = syllables / max(1, len(en_words))
        fk_grade = round(0.39 * wps + 11.8 * spw - 15.59, 1)
        fk_ease = round(206.835 - 1.015 * wps - 84.6 * spw, 1)

    low_en = [w.lower() for w in en_words]
    all_lex = low_en + zh_chars
    ttr = len(set(all_lex)) / max(1, len(all_lex))

    passive_hits = len(
        re.findall(
            r"\b(?:is|are|was|were|be|been|being)\s+(?:\w+ly\s+)?(?:[a-z]+ed|shown|given|taken|made|seen|found|known|used|built|driven|written)\b",
            plain,
            re.IGNORECASE,
        )
    )
    passive_ratio = min(1.0, passive_hits / max(1, len(raw_sents)))

    ai_isms = extract_ai_isms(text, custom_lexicon)
    ai_density = round((len(ai_isms) / max(1, total_words)) * 1000, 1)

    hedge_cnt = sum(1 for w in low_en if w in EN_HEDGES) + sum(plain.count(z) for z in ZH_HEDGES)
    booster_cnt = sum(1 for w in low_en if w in EN_BOOSTERS) + sum(plain.count(z) for z in ZH_BOOSTERS)

    return {
        "word_count": total_words,
        "sentence_count": len(raw_sents),
        "avg_sentence_len": round(avg_sent_len, 1),
        "long_sentence_ratio": round(long_ratio * 100, 1),
        "flesch_kincaid_grade": fk_grade,
        "flesch_reading_ease": fk_ease,
        "lexical_diversity": round(ttr * 100, 1),
        "passive_voice_ratio": round(passive_ratio * 100, 1),
        "ai_ism_count": len(ai_isms),
        "ai_ism_density": ai_density,
        "ai_isms": sorted(set(ai_isms)),
        "hedge_count": hedge_cnt,
        "booster_count": booster_cnt,
    }


def _make_alert_id(category: str, para_index: int, title: str, detail: str) -> str:
    raw = f"{category}|{para_index}|{title}|{detail}".encode("utf-8")
    return f"{category}_{para_index}_{hashlib.md5(raw).hexdigest()[:8]}"


def audit_paragraph_pair(
    old_text: str,
    new_text: str,
    para_index: int,
    section_title: str,
    protected_terms: list[str],
    block_type: str = "paragraph",
    acked_set: set[str] | None = None,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    acks = acked_set or set()
    old_f = _extract_facts(old_text)
    new_f = _extract_facts(new_text)

    def _push(category: str, severity: str, title: str, detail: str, items: list[str]) -> None:
        aid = _make_alert_id(category, para_index, title, detail)
        alerts.append(
            {
                "alert_id": aid,
                "acked": aid in acks,
                "para_index": para_index,
                "section": section_title,
                "category": category,
                "severity": severity,
                "title": title,
                "detail": detail,
                "items": items,
            }
        )

    old_c = Counter(old_f["citations"])
    new_c = Counter(new_f["citations"])
    dropped_cites = list((old_c - new_c).elements())
    added_cites = list((new_c - old_c).elements())
    if dropped_cites:
        _push("citation", "high", "引文丢失", f"新版移除了 {len(dropped_cites)} 处引文：{', '.join(dropped_cites[:5])}", dropped_cites)
    if added_cites:
        _push("citation", "info", "新增引文（请核对真实性）", f"新版新增 {len(added_cites)} 处引文：{', '.join(added_cites[:5])}", added_cites)

    old_r = Counter(old_f["refs"])
    new_r = Counter(new_f["refs"])
    dropped_refs = list((old_r - new_r).elements())
    if dropped_refs:
        _push("reference", "high", "图表/公式引用丢失", f"新版丢失引用：{', '.join(dropped_refs[:5])}", dropped_refs)

    old_n = Counter(old_f["numbers"])
    new_n = Counter(new_f["numbers"])
    removed_nums = list((old_n - new_n).elements())
    added_nums = list((new_n - old_n).elements())
    if removed_nums:
        sev = "high" if added_nums else "medium"
        title = "表格数值变动" if block_type == "table" else "数值/统计量变动"
        msg = (
            f"数值变动：旧版 [{', '.join(removed_nums[:6])}] → 新版 [{', '.join(added_nums[:6])}]"
            if added_nums
            else f"旧版数值在新版中消失：{', '.join(removed_nums[:6])}"
        )
        _push("number", sev, title, msg, removed_nums + added_nums)

    if old_f["maths"] != new_f["maths"]:
        _push(
            "math",
            "medium",
            "数学公式变动",
            f"本段公式发生变化（旧 {len(old_f['maths'])} 处 → 新 {len(new_f['maths'])} 处），请核对符号与下标",
            [],
        )

    if protected_terms and old_text and new_text:
        old_low = old_text.lower()
        new_low = new_text.lower()
        missing_terms = [
            t.strip() for t in protected_terms if t.strip() and t.strip().lower() in old_low and t.strip().lower() not in new_low
        ]
        if missing_terms:
            _push("terminology", "medium", "核心术语被替换", f"受保护术语在新版消失：{', '.join(missing_terms[:5])}", missing_terms)

    if old_text and new_text and block_type != "table":
        old_m = compute_style_metrics(old_text)
        new_m = compute_style_metrics(new_text)
        if new_m["booster_count"] > old_m["booster_count"] and new_m["hedge_count"] <= old_m["hedge_count"]:
            _push(
                "claim_drift",
                "medium",
                "断言强度抬升",
                f"强断言词增加 ({old_m['booster_count']}→{new_m['booster_count']})，谨慎词 ({old_m['hedge_count']}→{new_m['hedge_count']})，请核对是否夸大结论",
                [],
            )

    return alerts


def compare_documents(
    old_content: str,
    new_content: str,
    old_fmt: str = "auto",
    new_fmt: str = "auto",
    old_filename: str = "",
    new_filename: str = "",
    protected_terms: list[str] | None = None,
    custom_lexicon: dict[str, list[str]] | None = None,
    acked_alert_ids: list[str] | set[str] | None = None,
    old_meta: dict[str, Any] | None = None,
    new_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare two manuscript versions and run 4-dimension fact-conservation auditing.

    Results are cached in `_COMPARE_CACHE` (bounded LRU, max 32 entries) keyed by SHA-256
    across inputs, protected terms, custom AI lexicon, alert acks, and metadata keys.

    Args:
        old_content: Source text of the baseline (older) version.
        new_content: Source text of the revised (newer) version.
        old_fmt: Format hint (`"auto"`, `"latex"`, `"docx"`, `"markdown"`, `"text"`).
        new_fmt: Format hint for the revised version.
        old_filename: Original filename of the older version (aids auto-detection).
        new_filename: Original filename of the newer version.
        protected_terms: Project-level domain terms guarded against unauthorized replacement.
        custom_lexicon: User-configured AI cliche word overrides (`add_en`, `add_zh`, `ignore`).
        acked_alert_ids: Set of previously acknowledged alert hashes to mark as resolved.
        old_meta: Metadata dict for the older version (`assets`, `bib`, `bbl`, `source_map`).
        new_meta: Metadata dict for the newer version.

    Returns:
        Full comparison report dictionary containing aligned paragraphs, diff segments,
        table/math diffs, fact-conservation alerts, health score, style metrics, and macros.
    """
    terms = protected_terms or []
    acks = set(acked_alert_ids or [])
    old_assets = (old_meta or {}).get("assets") or {}
    new_assets = (new_meta or {}).get("assets") or {}
    old_bib = (old_meta or {}).get("bib") or {}
    new_bib = (new_meta or {}).get("bib") or {}
    bib_entries = {**old_bib, **new_bib}

    cache_k = _make_cache_key(
        "cmp", old_content, new_content, old_fmt, new_fmt, old_filename, new_filename,
        terms, custom_lexicon or {}, sorted(acks), old_assets, new_assets,
        list(old_bib.keys()), list(new_bib.keys()), bool((old_meta or {}).get("bbl")), bool((new_meta or {}).get("bbl")),
    )
    cached = _cache_get(_COMPARE_CACHE, cache_k)
    if cached is not None:
        return cached

    det_old_fmt, old_blocks, old_doc_meta = parse_document_with_meta(
        old_content,
        old_fmt,
        old_filename,
        asset_map=old_assets,
        bib_entries=old_bib,
        bbl_content=(old_meta or {}).get("bbl"),
    )
    det_new_fmt, new_blocks, new_doc_meta = parse_document_with_meta(
        new_content,
        new_fmt,
        new_filename,
        asset_map=new_assets,
        bib_entries=new_bib,
        bbl_content=(new_meta or {}).get("bbl"),
    )
    merged_latex_macros = {
        **(old_doc_meta.get("latex_macros") or {}),
        **(new_doc_meta.get("latex_macros") or {}),
    }
    merged_footnotes = {
        **(old_doc_meta.get("footnotes") or {}),
        **(new_doc_meta.get("footnotes") or {}),
    }

    aligned = align_blocks(old_blocks, new_blocks)

    paragraphs: list[dict[str, Any]] = []
    all_alerts: list[dict[str, Any]] = []
    section_stats: dict[str, dict[str, Any]] = {}
    section_order: list[str] = []

    total_old_words = 0
    total_new_words = 0
    total_added_words = 0
    total_deleted_words = 0
    weighted_sim_num = 0.0
    weighted_sim_den = 0.0
    modified_paras = 0
    added_paras = 0
    deleted_paras = 0
    unchanged_paras = 0

    old_ai_all: Counter[str] = Counter()
    new_ai_all: Counter[str] = Counter()

    for idx, (ob, nb, status, moved_peer_idx) in enumerate(aligned):
        sec = strip_rich_markers((nb.section_title if nb else ob.section_title) if (ob or nb) else "Main Text")
        sec_level = (nb.section_level if nb else ob.section_level) if (ob or nb) else 1
        btype = (nb.block_type if nb else ob.block_type) if (ob or nb) else "paragraph"
        zone = (nb.zone if nb else ob.zone) if (ob or nb) else "body"
        table_role = ((nb.meta if nb else None) or (ob.meta if ob else None) or {}).get("table_role")
        table_alignments = ((nb.meta if nb else None) or (ob.meta if ob else None) or {}).get("alignments")
        code_lang = ((nb.meta if nb else None) or (ob.meta if ob else None) or {}).get("lang")
        ref_meta = (nb.meta if nb and btype == "reference_item" else (ob.meta if ob and btype == "reference_item" else None))

        old_clean = ob.clean_text if ob else ""
        new_clean = nb.clean_text if nb else ""
        old_raw = ob.raw_text if ob else ""
        new_raw = nb.raw_text if nb else ""

        diff_res = diff_paragraph(old_clean, new_clean, idx)
        math_diff = (
            diff_math_expression(old_clean, new_clean)
            if btype == "math" and status == "modified"
            else []
        )
        if btype == "math" and status == "modified" and math_diff:
            eq_len = sum(len(seg["text"].split()) for seg in math_diff if seg["type"] == "equal")
            tot_old = sum(len(seg["text"].split()) for seg in math_diff if seg["type"] in ("equal", "delete"))
            tot_new = sum(len(seg["text"].split()) for seg in math_diff if seg["type"] in ("equal", "insert"))
            msim = (2.0 * eq_len / max(1, tot_old + tot_new)) * 100.0
            diff_res["similarity"] = round(msim, 1)
            diff_res["similarity_int"] = int(round(msim))

        table_diff = None
        if btype == "table":
            old_rows = (ob.meta.get("rows") if ob else []) or []
            new_rows = (nb.meta.get("rows") if nb else []) or []
            table_diff = diff_table_rows(old_rows, new_rows, idx)
            if table_diff["changed_cells"] > 0 and status == "unchanged":
                status = "modified"

        figure_info = None
        if btype == "figure":
            old_ak = ob.meta.get("asset_key") if ob else None
            new_ak = nb.meta.get("asset_key") if nb else None
            old_p = ob.meta.get("image_path", "") if ob else ""
            new_p = nb.meta.get("image_path", "") if nb else ""
            lbl = (nb.meta.get("label") if nb else None) or (ob.meta.get("label") if ob else "")
            if not old_ak and not new_ak:
                img_status = "no_preview"
            elif old_ak and not new_ak:
                img_status = "deleted"
            elif new_ak and not old_ak:
                img_status = "added"
            elif old_ak != new_ak:
                img_status = "updated"
                if status == "unchanged":
                    status = "modified"
            else:
                img_status = "unchanged"
            figure_info = {
                "old_asset": old_ak,
                "new_asset": new_ak,
                "old_path": old_p,
                "new_path": new_p,
                "label": lbl,
                "image_status": img_status,
            }

        if status == "moved_from" or btype == "hr" or (zone == "frontmatter" and table_role == "metadata_form"):
            para_alerts = []
        elif status == "moved_to" and moved_peer_idx is not None:
            peer_old_block = aligned[moved_peer_idx][0]
            peer_old_clean = peer_old_block.clean_text if peer_old_block else ""
            para_alerts = (
                audit_paragraph_pair(peer_old_clean, new_clean, idx, sec, terms, btype, acks)
                if peer_old_clean != new_clean
                else []
            )
        elif status != "unchanged":
            para_alerts = audit_paragraph_pair(old_clean, new_clean, idx, sec, terms, btype, acks)
        else:
            para_alerts = []

        # Table optimal-value bold shift notice (skip frontmatter cover metadata tables)
        if btype == "table" and table_role != "metadata_form" and table_diff and table_diff.get("bold_changed_cells", 0) > 0:
            bc = table_diff["bold_changed_cells"]
            detail = f"表格中有 {bc} 个单元格的粗体最优值标记发生变化，请核对是否误移加粗"
            aid = _make_alert_id("table_bold", idx, "表格最优值加粗变动", detail)
            para_alerts.append(
                {
                    "alert_id": aid,
                    "acked": aid in acks,
                    "para_index": idx,
                    "section": sec,
                    "category": "number",
                    "severity": "medium",
                    "title": "表格最优值加粗变动",
                    "detail": detail,
                    "items": [],
                }
            )

        # Undefined BibTeX citation verification when .bib is present in project zip
        if new_bib and new_clean:
            new_latex_cites = []
            for cm in ATOMIC_TOKEN_RE.finditer(new_clean):
                if cm.group(1) == "CITE":
                    for ck in cm.group(2).split(","):
                        ck = ck.strip()
                        if ck and ck not in new_bib:
                            new_latex_cites.append(ck)
            if new_latex_cites:
                uniq_missing = sorted(set(new_latex_cites))
                detail = f"以下引文键未在项目 .bib 中找到定义：{', '.join(uniq_missing[:5])}"
                aid = _make_alert_id("bib_missing", idx, "未在 .bib 中定义的引文", detail)
                para_alerts.append(
                    {
                        "alert_id": aid,
                        "acked": aid in acks,
                        "para_index": idx,
                        "section": sec,
                        "category": "citation",
                        "severity": "high",
                        "title": "未在 .bib 中定义的引文",
                        "detail": detail,
                        "items": uniq_missing,
                    }
                )

        moved_peer_section = None
        if moved_peer_idx is not None:
            p_ob, p_nb, _, _ = aligned[moved_peer_idx]
            moved_peer_section = (p_nb.section_title if p_nb else p_ob.section_title) if (p_ob or p_nb) else None

        skip_ai = btype in ("table", "math", "code", "hr", "reference_item") or zone in ("frontmatter", "backmatter")
        old_ai = extract_ai_isms(old_clean, custom_lexicon) if not skip_ai else []
        new_ai = extract_ai_isms(new_clean, custom_lexicon) if not skip_ai else []
        old_ai_all.update(old_ai)
        new_ai_all.update(new_ai)

        if btype not in ("heading", "hr") and zone != "frontmatter":
            total_old_words += diff_res["old_word_count"]
            total_new_words += diff_res["new_word_count"]
            total_added_words += diff_res["added_words"]
            total_deleted_words += diff_res["deleted_words"]
            weight = diff_res["old_word_count"] + diff_res["new_word_count"]
            weighted_sim_num += (diff_res["similarity"] / 100.0) * weight
            weighted_sim_den += weight

            if status == "unchanged":
                unchanged_paras += 1
            elif status == "modified":
                modified_paras += 1
            elif status in ("added", "moved_to"):
                added_paras += 1
            elif status in ("deleted", "moved_from"):
                deleted_paras += 1

        if zone != "frontmatter" and sec not in section_stats:
            section_order.append(sec)
            section_stats[sec] = {
                "title": sec,
                "level": sec_level,
                "first_para_index": idx,
                "para_count": 0,
                "changed_para_count": 0,
                "old_words": 0,
                "new_words": 0,
                "word_delta": 0,
                "sim_num": 0.0,
                "sim_den": 0.0,
                "alert_count": 0,
            }
        if zone != "frontmatter" and sec in section_stats:
            st = section_stats[sec]
            if btype not in ("heading", "hr"):
                st["para_count"] += 1
                if status != "unchanged":
                    st["changed_para_count"] += 1
                st["old_words"] += diff_res["old_word_count"]
                st["new_words"] += diff_res["new_word_count"]
                st["word_delta"] = st["new_words"] - st["old_words"]
                w = diff_res["old_word_count"] + diff_res["new_word_count"]
                st["sim_num"] += (diff_res["similarity"] / 100.0) * w
                st["sim_den"] += w
                st["alert_count"] += sum(1 for a in para_alerts if not a["acked"])

        all_alerts.extend(para_alerts)
        heading_items = text_to_display_items(new_clean or old_clean) if btype == "heading" else None
        active_meta = (nb.meta if nb else None) or (ob.meta if ob else None) or {}
        alg_meta_cmp = None
        if btype == "algorithm":
            alg_meta_cmp = {
                "alg_num": active_meta.get("alg_num"),
                "caption": active_meta.get("caption", ""),
                "label": active_meta.get("label", ""),
                "lines": [
                    {
                        "indent": ln.get("indent", 0),
                        "text": ln.get("text", ""),
                        "items": text_to_display_items(ln.get("text", "")),
                    }
                    for ln in (active_meta.get("lines") or [])
                ],
            }
        paragraphs.append(
            {
                "index": idx,
                "block_type": btype,
                "zone": zone,
                "section_title": sec,
                "section_level": sec_level,
                "status": status,
                "old_raw": old_raw,
                "new_raw": new_raw,
                "old_raw_start": ob.raw_start if ob else None,
                "old_raw_end": ob.raw_end if ob else None,
                "new_raw_start": nb.raw_start if nb else None,
                "new_raw_end": nb.raw_end if nb else None,
                "old_clean": old_clean,
                "new_clean": new_clean,
                "heading_items": heading_items,
                "ai_isms_old": old_ai,
                "ai_isms_new": new_ai,
                "alerts": para_alerts,
                "moved_peer_index": moved_peer_idx,
                "moved_peer_section": moved_peer_section,
                "math_diff": math_diff,
                "table_diff": table_diff,
                "table_role": table_role,
                "table_alignments": table_alignments,
                "table_notes": active_meta.get("table_notes"),
                "code_lang": code_lang,
                "is_diagram": bool(active_meta.get("is_diagram", False)),
                "callout_type": active_meta.get("callout_type"),
                "quote_depth": (active_meta.get("style") or {}).get("quote_depth"),
                "theorem_meta": active_meta if btype == "theorem" else None,
                "algorithm_meta": alg_meta_cmp,
                "comments": active_meta.get("comments") or [],
                "ref_meta": ref_meta,
                "figure_info": figure_info,
                "list_meta": (nb.meta if nb and btype == "list" else (ob.meta if ob and btype == "list" else None)),
                "eq_number": (nb.meta.get("eq_number") if nb and btype == "math" else (ob.meta.get("eq_number") if ob and btype == "math" else None)),
                "source_anchor": nb.source_anchor if nb else (ob.source_anchor if ob else None),
                **diff_res,
            }
        )

    overall_sim = round((weighted_sim_num / max(1.0, weighted_sim_den)) * 100, 1)
    old_full_clean = "\n\n".join(b.clean_text for b in old_blocks if b.block_type not in ("heading", "table"))
    new_full_clean = "\n\n".join(b.clean_text for b in new_blocks if b.block_type not in ("heading", "table"))
    old_style = compute_style_metrics(old_full_clean, custom_lexicon)
    new_style = compute_style_metrics(new_full_clean, custom_lexicon)

    sections = []
    for sec_name in section_order:
        st = section_stats[sec_name]
        sim_val = round((st["sim_num"] / max(1.0, st["sim_den"])) * 100, 1) if st["sim_den"] > 0 else 100.0
        sections.append(
            {
                "title": st["title"],
                "level": st["level"],
                "first_para_index": st["first_para_index"],
                "para_count": st["para_count"],
                "changed_para_count": st["changed_para_count"],
                "old_words": st["old_words"],
                "new_words": st["new_words"],
                "word_delta": st["word_delta"],
                "similarity": sim_val,
                "change_intensity": round(100.0 - sim_val, 1),
                "alert_count": st["alert_count"],
            }
        )

    active_alerts = [a for a in all_alerts if not a["acked"]]
    acked_count = sum(1 for a in all_alerts if a["acked"])
    high_alerts = sum(1 for a in active_alerts if a["severity"] == "high")
    med_alerts = sum(1 for a in active_alerts if a["severity"] == "medium")
    fact_safety_score = max(15, 100 - high_alerts * 22 - med_alerts * 8)

    ai_density = new_style["ai_ism_density"]
    ai_naturalness_score = max(20, min(100, int(round(100 - ai_density * 2.2))))

    avg_sl = new_style["avg_sentence_len"]
    sl_penalty = max(0.0, (avg_sl - 26.0) * 1.8) if avg_sl > 26.0 else 0.0
    readability_score = max(30, min(100, int(round(92 - sl_penalty - new_style["long_sentence_ratio"] * 0.4))))

    total_para_cnt = max(1, unchanged_paras + modified_paras + added_paras + deleted_paras)
    overall_health = int(round(0.45 * fact_safety_score + 0.30 * ai_naturalness_score + 0.25 * readability_score))

    removed_ai_words = list((old_ai_all - new_ai_all).elements())
    added_ai_words = list((new_ai_all - old_ai_all).elements())

    result = {
        "formats": {"old": det_old_fmt, "new": det_new_fmt},
        "summary": {
            "overall_similarity": overall_sim,
            "rewrite_ratio": round(100.0 - overall_sim, 1),
            "old_words": total_old_words,
            "new_words": total_new_words,
            "word_delta": total_new_words - total_old_words,
            "added_words": total_added_words,
            "deleted_words": total_deleted_words,
            "total_paragraphs": total_para_cnt,
            "modified_paragraphs": modified_paras,
            "added_paragraphs": added_paras,
            "deleted_paragraphs": deleted_paras,
            "unchanged_paragraphs": unchanged_paras,
            "alert_counts": {
                "high": high_alerts,
                "medium": med_alerts,
                "info": sum(1 for a in active_alerts if a["severity"] == "info"),
                "total": len(active_alerts),
                "acked": acked_count,
            },
        },
        "evaluation": {
            "overall_health": overall_health,
            "scores": {
                "fact_safety": fact_safety_score,
                "ai_naturalness": ai_naturalness_score,
                "readability": readability_score,
            },
            "old_style": old_style,
            "new_style": new_style,
            "ai_ism_diff": {
                "old_count": sum(old_ai_all.values()),
                "new_count": sum(new_ai_all.values()),
                "delta": sum(new_ai_all.values()) - sum(old_ai_all.values()),
                "removed": [{"word": k, "count": v} for k, v in Counter(removed_ai_words).most_common(25)],
                "added": [{"word": k, "count": v} for k, v in Counter(added_ai_words).most_common(25)],
            },
        },
        "sections": sections,
        "alerts": all_alerts,
        "bib_entries": bib_entries,
        "latex_macros": merged_latex_macros,
        "footnotes": merged_footnotes,
        "paragraphs": paragraphs,
    }
    _cache_put(_COMPARE_CACHE, cache_k, result)
    return result


LATEX_LABEL_RE = re.compile(r"\\label\{([^{}]+)\}")


def preview_document(
    content: str,
    fmt: str = "auto",
    filename: str = "",
    protected_terms: list[str] | None = None,
    custom_lexicon: dict[str, list[str]] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    v1.1.0 Single-Document AST Reading & Self-Audit Engine (with bounded LRU cache):
    Parses one manuscript into structured blocks (headings, paragraphs, figures w/ subfigures,
    merged tables, numbered math, theorems, algorithms, callouts, lists, footnotes, comments)
    and runs standalone quality checks without needing a second version.
    """
    terms = protected_terms or []
    assets = (meta or {}).get("assets") or {}
    bib_entries = (meta or {}).get("bib") or {}

    cache_k = _make_cache_key(
        "prev_v12", content, fmt, filename, terms, custom_lexicon or {}, assets,
        list(bib_entries.keys()), bool((meta or {}).get("bbl")),
    )
    cached = _cache_get(_PREVIEW_CACHE, cache_k)
    if cached is not None:
        return cached

    det_fmt, raw_blocks, doc_meta = parse_document_with_meta(
        content,
        fmt,
        filename,
        asset_map=assets,
        bib_entries=bib_entries,
        bbl_content=(meta or {}).get("bbl"),
    )
    latex_macros = doc_meta.get("latex_macros") or {}
    footnotes_map = {**((meta or {}).get("footnotes") or {}), **(doc_meta.get("footnotes") or {})}
    label_map = doc_meta.get("label_map") or {}

    # Collect defined LaTeX labels for broken \ref{} verification
    defined_labels: set[str] = set()
    for lm in LATEX_LABEL_RE.finditer(content):
        lbl = lm.group(1).strip()
        if lbl:
            defined_labels.add(lbl)
    for rb in raw_blocks:
        meta_lbl = (rb.meta or {}).get("label")
        if meta_lbl:
            defined_labels.add(str(meta_lbl).strip())

    check_broken_refs = det_fmt == "latex" and (
        "\\begin{document}" in content or len(defined_labels) > 0
    )

    blocks_out: list[dict[str, Any]] = []
    all_issues: list[dict[str, Any]] = []
    section_stats: dict[str, dict[str, Any]] = {}
    section_order: list[str] = []

    ai_counter: Counter[str] = Counter()
    unique_cites: set[str] = set()
    total_cites = 0
    total_refs = 0
    total_words = 0
    para_cnt = 0
    heading_cnt = 0
    figure_cnt = 0
    table_cnt = 0
    math_cnt = 0
    list_cnt = 0

    for idx, b in enumerate(raw_blocks):
        btype = b.block_type
        zone = b.zone or "body"
        sec = strip_rich_markers(b.section_title or "Main Text")
        sec_level = b.section_level or 1
        clean = b.clean_text
        bm = b.meta or {}
        table_role = bm.get("table_role")
        table_alignments = bm.get("alignments")
        table_notes = bm.get("table_notes")
        code_lang = bm.get("lang")
        is_diagram = bool(bm.get("is_diagram", False))
        callout_type = bm.get("callout_type")
        comments = bm.get("comments") or []
        ref_meta = (bm if btype == "reference_item" else None)
        theorem_meta = (bm if btype == "theorem" else None)
        algorithm_meta = None
        if btype == "algorithm":
            algorithm_meta = {
                "alg_num": bm.get("alg_num"),
                "caption": bm.get("caption", ""),
                "label": bm.get("label", ""),
                "lines": [
                    {
                        "indent": ln.get("indent", 0),
                        "text": ln.get("text", ""),
                        "items": text_to_display_items(ln.get("text", "")),
                    }
                    for ln in (bm.get("lines") or [])
                ],
            }

        if btype == "math":
            inner_math = _extract_math_inner(clean)
            items = [{"kind": "math", "text": clean, "value": inner_math}]
        elif btype in ("hr", "code", "algorithm"):
            items = []
        else:
            items = text_to_display_items(clean)

        is_frontmatter = zone == "frontmatter"
        wc = count_academic_words(clean) if (btype not in ("heading", "table", "hr") and not is_frontmatter) else 0
        skip_ai = btype in ("table", "math", "code", "hr", "reference_item", "algorithm") or zone in ("frontmatter", "backmatter")
        block_ai = extract_ai_isms(clean, custom_lexicon) if not skip_ai else []
        ai_counter.update(block_ai)

        facts = _extract_facts(clean) if not is_frontmatter else {"numbers": [], "citations": [], "refs": [], "maths": []}
        total_cites += len(facts["citations"])
        unique_cites.update(facts["citations"])
        total_refs += len(facts["refs"])

        block_issues: list[dict[str, Any]] = []

        if bib_entries and clean and not is_frontmatter:
            missing_bib: list[str] = []
            for cm in ATOMIC_TOKEN_RE.finditer(clean):
                if cm.group(1) == "CITE":
                    for ck in cm.group(2).split(","):
                        ck = ck.strip()
                        if ck and ck not in bib_entries:
                            missing_bib.append(ck)
            if missing_bib:
                uniq = sorted(set(missing_bib))
                detail = f"以下引文键未在项目 .bib 中找到定义：{', '.join(uniq[:5])}"
                block_issues.append(
                    {
                        "issue_id": _make_alert_id("single_bib", idx, "未在 .bib 中定义的引文", detail),
                        "block_index": idx,
                        "section": sec,
                        "category": "citation",
                        "severity": "high",
                        "title": "未在 .bib 中定义的引文",
                        "detail": detail,
                        "items": uniq,
                    }
                )

        if check_broken_refs and clean and not is_frontmatter:
            missing_refs: list[str] = []
            for rm in ATOMIC_TOKEN_RE.finditer(clean):
                if rm.group(1) == "REF":
                    rk = rm.group(2).split("|", 1)[0].strip()
                    if rk and rk not in defined_labels:
                        missing_refs.append(rk)
            if missing_refs:
                uniq_r = sorted(set(missing_refs))
                detail = f"以下交叉引用在当前文档中未找到对应 \\label：{'、'.join(uniq_r[:5])}"
                block_issues.append(
                    {
                        "issue_id": _make_alert_id("single_ref", idx, "断链交叉引用", detail),
                        "block_index": idx,
                        "section": sec,
                        "category": "reference",
                        "severity": "medium",
                        "title": "断链交叉引用",
                        "detail": detail,
                        "items": uniq_r,
                    }
                )

        table_rows = serialize_plain_table_rows(bm.get("rows") or []) if btype == "table" else None
        figure_info = None
        if btype == "figure":
            figure_info = {
                "asset_key": bm.get("asset_key"),
                "image_path": bm.get("image_path", ""),
                "label": bm.get("label", ""),
                "images": bm.get("images") or [],
            }
        list_meta = None
        if btype == "list":
            list_meta = {
                "ordered": bool(bm.get("ordered", False)),
                "item_num": int(bm.get("item_num", 1)),
                "depth": int(bm.get("depth", 0)),
                "checked": bm.get("checked"),
            }
        eq_number = bm.get("eq_number") if btype == "math" else None

        if not is_frontmatter and btype != "hr":
            if btype == "heading":
                heading_cnt += 1
            else:
                total_words += wc
                if btype == "figure":
                    figure_cnt += 1
                elif btype == "table":
                    if table_role != "metadata_form":
                        table_cnt += 1
                elif btype == "math":
                    math_cnt += 1
                elif btype == "list":
                    list_cnt += 1
                else:
                    para_cnt += 1

        if not is_frontmatter:
            if sec not in section_stats:
                section_order.append(sec)
                section_stats[sec] = {
                    "title": sec,
                    "level": sec_level,
                    "first_block_index": idx,
                    "block_count": 0,
                    "word_count": 0,
                    "ai_ism_count": 0,
                    "issue_count": 0,
                    "zone": zone,
                }
            st = section_stats[sec]
            if btype not in ("heading", "hr"):
                st["block_count"] += 1
                st["word_count"] += wc
                st["ai_ism_count"] += len(block_ai)
                st["issue_count"] += len(block_issues)

        all_issues.extend(block_issues)
        blocks_out.append(
            {
                "index": idx,
                "block_type": btype,
                "zone": zone,
                "section_title": sec,
                "section_level": sec_level,
                "raw_text": b.raw_text,
                "clean_text": clean,
                "raw_start": b.raw_start,
                "raw_end": b.raw_end,
                "source_anchor": b.source_anchor,
                "label": bm.get("label", ""),
                "items": items,
                "word_count": wc,
                "ai_isms": sorted(set(block_ai)),
                "table_rows": table_rows,
                "table_role": table_role,
                "table_alignments": table_alignments,
                "table_notes": table_notes,
                "code_lang": code_lang,
                "is_diagram": is_diagram,
                "callout_type": callout_type,
                "style": bm.get("style") or None,
                "theorem_meta": theorem_meta,
                "algorithm_meta": algorithm_meta,
                "comments": comments,
                "ref_meta": ref_meta,
                "figure_info": figure_info,
                "list_meta": list_meta,
                "eq_number": eq_number,
                "issues": block_issues,
            }
        )

    full_clean = "\n\n".join(
        b.clean_text
        for b in raw_blocks
        if b.block_type not in ("heading", "table", "hr", "code", "reference_item", "algorithm")
        and (b.zone or "body") == "body"
    )
    style = compute_style_metrics(full_clean, custom_lexicon)
    doc_language, cjk_ratio = _compute_doc_language(full_clean)

    term_coverage: list[dict[str, Any]] = []
    for t in terms:
        t_clean = t.strip()
        if not t_clean:
            continue
        pat = re.compile(rf"(?<!\w){re.escape(t_clean)}(?!\w)", re.IGNORECASE) if re.match(r"^[A-Za-z0-9_-]+$", t_clean) else re.compile(re.escape(t_clean), re.IGNORECASE)
        cnt = len(pat.findall(full_clean))
        term_coverage.append({"term": t_clean, "count": cnt})

    high_issues = sum(1 for x in all_issues if x["severity"] == "high")
    med_issues = sum(1 for x in all_issues if x["severity"] == "medium")
    info_issues = sum(1 for x in all_issues if x["severity"] == "info")

    ai_penalty = min(35, int(round(style["ai_ism_density"] * 1.4)))
    long_pen = max(0, int(round((style["long_sentence_ratio"] - 25.0) * 0.6)))
    issue_pen = min(45, high_issues * 15 + med_issues * 7)
    health_score = max(10, min(100, 100 - ai_penalty - long_pen - issue_pen))

    sections = [section_stats[s] for s in section_order]

    out_prev = {
        "format": det_fmt,
        "doc_language": doc_language,
        "cjk_ratio": cjk_ratio,
        "raw_content": content,
        "health_score": health_score,
        "summary": {
            "word_count": total_words,
            "paragraph_count": para_cnt,
            "heading_count": heading_cnt,
            "figure_count": figure_cnt,
            "table_count": table_cnt,
            "math_count": math_cnt,
            "list_count": list_cnt,
            "citation_count": len(unique_cites),
            "citation_total": total_cites,
            "reference_count": total_refs,
            "ai_ism_count": sum(ai_counter.values()),
            "issue_counts": {
                "high": high_issues,
                "medium": med_issues,
                "info": info_issues,
                "total": len(all_issues),
            },
        },
        "style": style,
        "ai_ism_breakdown": [{"word": k, "count": v} for k, v in ai_counter.most_common(30)],
        "term_coverage": term_coverage,
        "sections": sections,
        "issues": all_issues,
        "bib_entries": bib_entries,
        "latex_macros": latex_macros,
        "footnotes": {k: strip_rich_markers(v) for k, v in footnotes_map.items()},
        "footnote_items": {k: text_to_display_items(v) for k, v in footnotes_map.items()},
        "label_map": label_map,
        "blocks": blocks_out,
    }
    _cache_put(_PREVIEW_CACHE, cache_k, out_prev)
    return out_prev
