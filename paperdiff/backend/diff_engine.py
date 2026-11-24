r"""Zero-Loss Bilingual Academic Tokenizer, Block Alignment & Structured Diff Engine.

Core responsibilities:
    - `text_to_display_items`: Lossless direct-pass conversion from internal `clean_text`
      rich markers (`⟦MATH/REF/CITE/CODE/LINK/FN⟧` and `⟦B/I/S/BR⟧`) to frontend `DisplayItem[]`
      without re-tokenizing or guessing whitespace.
    - `tokenize_academic`: Bilingual EN/ZH (`jieba`) tokenizer preserving atomic academic chips,
      nested inline styles, exact `had_space_before` flags, and ALL Unicode characters.
    - `align_blocks`: Dynamic-programming paragraph alignment with cross-section move detection.
    - `diff_paragraph` / `diff_table_rows` / `diff_math_expression`: Word-, cell-, and
      LaTeX-symbol-level diffing with orphan-stopword smoothing (strictly shielding atoms).

Architectural invariant:
    `SUB_TOKEN_RE` ends with `[^\s]` (NEVER `[^\w\s]`), preventing silent drops of underscores
    (`sparse_attn`), accented Latin characters (`Debye–Hückel`), or Greek symbols (`μ`, `Ω`).
"""
from __future__ import annotations

import difflib
import re
import threading
from dataclasses import dataclass
from typing import Any

from .database import DATA_DIR
from .parsers import DocumentBlock

_JIEBA_LOCK = threading.Lock()
_JIEBA_MOD: Any = None


def _get_jieba() -> Any:
    """Lazily import and configure `jieba` on first Chinese tokenization to keep cold startup fast."""
    global _JIEBA_MOD
    if _JIEBA_MOD is not None:
        return _JIEBA_MOD
    with _JIEBA_LOCK:
        if _JIEBA_MOD is None:
            import jieba as _jieba_pkg

            _jieba_pkg.setLogLevel(20)
            cache_dir = DATA_DIR / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            _jieba_pkg.dt.tmp_dir = str(cache_dir)
            _JIEBA_MOD = _jieba_pkg
    return _JIEBA_MOD

ATOMIC_TOKEN_RE = re.compile(r"⟦(REF|CITE|MATH|CODE|LINK|FN|SP):(.*?)⟧")
STYLE_MARKER_RE = re.compile(r"⟦(/B|B|/I|I|/S|S|BR)⟧")
INLINE_TOKEN_RE = re.compile(r"⟦(REF|CITE|MATH|CODE|LINK|FN|SP):(.*?)⟧|⟦(/B|B|/I|I|/S|S|BR)⟧")

# Never use [^\w\s] because \w includes '_', accented Latin (ü, é, ø), Greek (μ, α, Ω), etc.
SUB_TOKEN_RE = re.compile(
    r"(\d+(?:[.,]\d+)*(?:[eE][+-]?\d+)?%?|"
    r"[A-Za-z\u00C0-\u024F\u0370-\u03FF]+(?:[-_'’][A-Za-z0-9\u00C0-\u024F\u0370-\u03FF]+)*|"
    r"[\u4e00-\u9fff\u3400-\u4dbf]+|"
    r"\s+|"
    r"[^\s])"
)
CJK_RE = re.compile(r"^[\u4e00-\u9fff\u3400-\u4dbf]+$")


def strip_style_markers(text: str) -> str:
    """Remove inline ⟦B⟧/⟦I⟧/⟦S⟧ formatting tags and turn ⟦BR⟧ into spaces, keeping text & atoms."""
    if not text or "⟦" not in text:
        return text
    s = text.replace("⟦BR⟧", " ")
    return re.sub(r"⟦/?[BIS]⟧", "", s)


def strip_rich_markers(text: str, *, keep_math_plain: bool = True) -> str:
    """Convert rich clean_text with ⟦...⟧ markers into clean human-readable plain text (e.g., for TOC labels)."""
    if not text or "⟦" not in text:
        return text

    def _repl(m: re.Match[str]) -> str:
        if m.group(1):
            tag, val = m.group(1), m.group(2)
            if tag == "CODE":
                return val
            if tag == "LINK":
                return val.split("|", 1)[0] if "|" in val else val
            if tag == "REF":
                return f"[{val.split('|', 1)[1]}]" if "|" in val else f"[{val}]"
            if tag == "CITE":
                return f"[@{val}]"
            if tag == "FN":
                return f"[{val}]"
            if tag == "SP":
                return " "
            if tag == "MATH":
                return val if keep_math_plain else f"${val}$"
            return val
        ctrl = m.group(3)
        return " " if ctrl == "BR" else ""

    return re.sub(r"\s+", " ", INLINE_TOKEN_RE.sub(_repl, text)).strip()


@dataclass
class Token:
    text: str
    kind: str  # 'word' | 'cjk' | 'num' | 'punct' | 'space' | 'ref' | 'cite' | 'math' | 'code' | 'link' | 'fn' | 'br'
    value: str
    norm: str
    bold: bool = False
    italic: bool = False
    had_space_before: bool = False
    strike: bool = False


def tokenize_academic(text: str, *, segment_cjk: bool = True) -> list[Token]:
    """
    Tokenize academic EN/ZH text while preserving atomic chips
    (⟦REF⟧, ⟦CITE⟧, ⟦MATH⟧, ⟦CODE⟧, ⟦LINK⟧, ⟦FN⟧), inline style state (⟦B⟧/⟦I⟧/⟦S⟧),
    exact leading-space flags, and ALL Unicode characters without silent drops.
    """
    tokens: list[Token] = []
    pos = 0
    bold_depth = 0
    italic_depth = 0
    strike_depth = 0
    pending_space = False

    def _emit_plain(seg: str) -> None:
        nonlocal pending_space
        for m in SUB_TOKEN_RE.finditer(seg):
            piece = m.group(0)
            if piece.isspace():
                pending_space = True
                tokens.append(Token(text=" ", kind="space", value=" ", norm=" "))
            elif CJK_RE.match(piece):
                first = True
                cjk_parts = _get_jieba().lcut(piece) if segment_cjk else (piece,)
                for w in cjk_parts:
                    if w:
                        tokens.append(
                            Token(
                                text=w,
                                kind="cjk",
                                value=w,
                                norm=w,
                                bold=bold_depth > 0,
                                italic=italic_depth > 0,
                                had_space_before=pending_space if first else False,
                                strike=strike_depth > 0,
                            )
                        )
                        first = False
                pending_space = False
            elif re.match(r"^\d", piece):
                tokens.append(
                    Token(
                        text=piece,
                        kind="num",
                        value=piece,
                        norm=piece,
                        bold=bold_depth > 0,
                        italic=italic_depth > 0,
                        had_space_before=pending_space,
                        strike=strike_depth > 0,
                    )
                )
                pending_space = False
            elif re.match(r"^[A-Za-z\u00C0-\u024F\u0370-\u03FF]", piece):
                tokens.append(
                    Token(
                        text=piece,
                        kind="word",
                        value=piece,
                        norm=piece.lower(),
                        bold=bold_depth > 0,
                        italic=italic_depth > 0,
                        had_space_before=pending_space,
                        strike=strike_depth > 0,
                    )
                )
                pending_space = False
            else:
                tokens.append(
                    Token(
                        text=piece,
                        kind="punct",
                        value=piece,
                        norm=piece,
                        bold=bold_depth > 0,
                        italic=italic_depth > 0,
                        had_space_before=pending_space,
                        strike=strike_depth > 0,
                    )
                )
                pending_space = False

    for m in INLINE_TOKEN_RE.finditer(text):
        if m.start() > pos:
            _emit_plain(text[pos : m.start()])
        if m.group(1):
            tag = m.group(1).lower()
            val = m.group(2)
            # Treat explicit horizontal spacing atoms as whitespace so word counts & fact diffs stay invariant.
            if tag == "sp":
                pending_space = True
                tokens.append(Token(text=" ", kind="space", value=" ", norm=" "))
            else:
                if tag == "link" and "|" in val:
                    disp_txt = val.split("|", 1)[0]
                    norm_val = val
                elif tag == "ref" and "|" in val:
                    ref_key, ref_disp = val.split("|", 1)
                    disp_txt = ref_disp
                    norm_val = ref_key
                elif tag == "code":
                    disp_txt = val
                    norm_val = val
                elif tag == "fn":
                    disp_txt = val
                    norm_val = val
                else:
                    disp_txt = m.group(0)
                    norm_val = val
                tokens.append(
                    Token(
                        text=disp_txt,
                        kind=tag,
                        value=val,
                        norm=f"<{tag}:{norm_val}>",
                        bold=bold_depth > 0,
                        italic=italic_depth > 0,
                        had_space_before=pending_space,
                        strike=strike_depth > 0,
                    )
                )
                pending_space = False
        else:
            ctrl = m.group(3)
            if ctrl == "B":
                bold_depth += 1
            elif ctrl == "/B":
                bold_depth = max(0, bold_depth - 1)
            elif ctrl == "I":
                italic_depth += 1
            elif ctrl == "/I":
                italic_depth = max(0, italic_depth - 1)
            elif ctrl == "S":
                strike_depth += 1
            elif ctrl == "/S":
                strike_depth = max(0, strike_depth - 1)
            elif ctrl == "BR":
                tokens.append(Token(text="\n", kind="br", value="\n", norm="<br>"))
                pending_space = False
        pos = m.end()
    if pos < len(text):
        _emit_plain(text[pos:])
    return tokens


def count_academic_words(text: str) -> int:
    """Count English words/numbers + Chinese characters + atomic math/ref/cite/code tokens."""
    tokens = tokenize_academic(text, segment_cjk=False)
    total = 0
    for t in tokens:
        if t.kind in ("word", "num"):
            total += 1
        elif t.kind == "cjk":
            total += len(t.text)
        elif t.kind in ("ref", "cite", "math", "code", "link"):
            total += 1
    return total


def _content_tokens(tokens: list[Token]) -> list[Token]:
    return [t for t in tokens if t.kind != "space"]


def _word_tokens_for_sim(tokens: list[Token]) -> list[str]:
    out: list[str] = []
    for t in tokens:
        if t.kind in ("word", "num", "ref", "cite", "math", "code", "link"):
            out.append(t.norm)
        elif t.kind == "cjk":
            out.extend(list(t.text))
    return out


MATH_SYM_RE = re.compile(r"\\[A-Za-z]+|[A-Za-z0-9]+|[^\s]")


def tokenize_latex_math(expr: str) -> list[str]:
    return MATH_SYM_RE.findall(expr)


def _extract_math_inner(clean_text: str) -> str:
    m = re.fullmatch(r"⟦MATH:(.*)⟧", clean_text.strip(), re.DOTALL)
    return m.group(1).strip() if m else clean_text.strip()


def diff_math_expression(old_clean: str, new_clean: str) -> list[dict[str, str]]:
    """Symbol-level diff of two display LaTeX math expressions."""
    old_syms = tokenize_latex_math(_extract_math_inner(old_clean))
    new_syms = tokenize_latex_math(_extract_math_inner(new_clean))
    sm = difflib.SequenceMatcher(a=old_syms, b=new_syms, autojunk=False)
    out: list[dict[str, str]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out.append({"type": "equal", "text": " ".join(old_syms[i1:i2])})
        elif tag == "replace":
            if i2 > i1:
                out.append({"type": "delete", "text": " ".join(old_syms[i1:i2])})
            if j2 > j1:
                out.append({"type": "insert", "text": " ".join(new_syms[j1:j2])})
        elif tag == "delete":
            out.append({"type": "delete", "text": " ".join(old_syms[i1:i2])})
        elif tag == "insert":
            out.append({"type": "insert", "text": " ".join(new_syms[j1:j2])})
    return out


def _block_sim_tokens(block: DocumentBlock) -> list[str]:
    if block.block_type == "math":
        return tokenize_latex_math(_extract_math_inner(block.clean_text))
    return _word_tokens_for_sim(tokenize_academic(block.clean_text))


def _types_compatible(t1: str, t2: str) -> bool:
    if t1 == t2:
        return True
    pair = {t1, t2}
    if pair in (
        {"paragraph", "caption"},
        {"paragraph", "list"},
        {"paragraph", "blockquote"},
        {"figure", "caption"},
    ):
        return True
    return False


def _para_alignment_score(a: DocumentBlock, b: DocumentBlock) -> float:
    if not _types_compatible(a.block_type, b.block_type):
        return -1.0
    if a.block_type == "figure" and b.block_type == "figure":
        a_lbl = (a.meta.get("label") or "").strip().lower()
        b_lbl = (b.meta.get("label") or "").strip().lower()
        a_ak = a.meta.get("asset_key")
        b_ak = b.meta.get("asset_key")
        if a_lbl and a_lbl == b_lbl:
            return 0.92
        if a_ak and a_ak == b_ak:
            return 0.90
    wa = _block_sim_tokens(a)
    wb = _block_sim_tokens(b)
    if not wa and not wb:
        return 1.0
    if not wa or not wb:
        return 0.0
    set_a, set_b = set(wa), set(wb)
    jacc = len(set_a & set_b) / max(1, len(set_a | set_b))
    bg_a = set(zip(wa, wa[1:])) if len(wa) > 1 else set_a
    bg_b = set(zip(wb, wb[1:])) if len(wb) > 1 else set_b
    bg_jacc = len(bg_a & bg_b) / max(1, len(bg_a | bg_b))
    len_ratio = min(len(wa), len(wb)) / max(len(wa), len(wb))
    sec_bonus = 0.06 if a.section_title.lower() == b.section_title.lower() else 0.0
    return min(1.0, 0.55 * jacc + 0.30 * bg_jacc + 0.15 * len_ratio + sec_bonus)


def align_blocks(
    old_blocks: list[DocumentBlock], new_blocks: list[DocumentBlock]
) -> list[tuple[DocumentBlock | None, DocumentBlock | None, str, int | None]]:
    """
    Needleman-Wunsch DP alignment of document blocks.
    Returns list of (old_block, new_block, status, moved_peer_index) where status in
    {'unchanged', 'modified', 'added', 'deleted', 'moved_from', 'moved_to'}.
    """
    n, m = len(old_blocks), len(new_blocks)
    if n == 0:
        return [(None, b, "added", None) for b in new_blocks]
    if m == 0:
        return [(a, None, "deleted", None) for a in old_blocks]

    gap_penalty = -0.18
    match_threshold = 0.22

    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    bt = [[0] * (m + 1) for _ in range(n + 1)]

    for i in range(1, n + 1):
        dp[i][0] = i * gap_penalty
        bt[i][0] = 1
    for j in range(1, m + 1):
        dp[0][j] = j * gap_penalty
        bt[0][j] = 2

    old_sets, old_bgs, old_lens = [], [], []
    for a in old_blocks:
        wa = _block_sim_tokens(a)
        old_sets.append(set(wa))
        old_bgs.append(set(zip(wa, wa[1:])) if len(wa) > 1 else set(wa))
        old_lens.append(len(wa))

    new_sets, new_bgs, new_lens = [], [], []
    for b in new_blocks:
        wb = _block_sim_tokens(b)
        new_sets.append(set(wb))
        new_bgs.append(set(zip(wb, wb[1:])) if len(wb) > 1 else set(wb))
        new_lens.append(len(wb))

    for i in range(1, n + 1):
        a = old_blocks[i - 1]
        sa, bga, la = old_sets[i - 1], old_bgs[i - 1], old_lens[i - 1]
        a_sec = a.section_title.lower()
        for j in range(1, m + 1):
            b = new_blocks[j - 1]
            if not _types_compatible(a.block_type, b.block_type):
                sim = -1.0
            elif a.block_type == "figure" and b.block_type == "figure":
                a_lbl = (a.meta.get("label") or "").strip().lower()
                b_lbl = (b.meta.get("label") or "").strip().lower()
                a_ak = a.meta.get("asset_key")
                b_ak = b.meta.get("asset_key")
                if a.clean_text == b.clean_text and a_ak == b_ak:
                    sim = 1.05
                elif (a_lbl and a_lbl == b_lbl) or (a_ak and a_ak == b_ak):
                    sim = 0.88
                else:
                    sb, bgb, lb = new_sets[j - 1], new_bgs[j - 1], new_lens[j - 1]
                    sim = (len(sa & sb) / max(1, len(sa | sb))) if (la and lb) else 0.35
            elif a.clean_text == b.clean_text:
                sim = 1.05
            else:
                sb, bgb, lb = new_sets[j - 1], new_bgs[j - 1], new_lens[j - 1]
                if la == 0 or lb == 0:
                    sim = 0.0
                else:
                    jacc = len(sa & sb) / max(1, len(sa | sb))
                    bg_j = len(bga & bgb) / max(1, len(bga | bgb))
                    lr = min(la, lb) / max(la, lb)
                    sec_b = 0.05 if a_sec == b.section_title.lower() else 0.0
                    sim = 0.55 * jacc + 0.30 * bg_j + 0.15 * lr + sec_b

            pair_score = (sim - match_threshold) if sim >= match_threshold else -0.65
            diag = dp[i - 1][j - 1] + pair_score
            up = dp[i - 1][j] + gap_penalty
            left = dp[i][j - 1] + gap_penalty

            if diag >= up and diag >= left:
                dp[i][j] = diag
                bt[i][j] = 0
            elif up >= left:
                dp[i][j] = up
                bt[i][j] = 1
            else:
                dp[i][j] = left
                bt[i][j] = 2

    aligned: list[tuple[DocumentBlock | None, DocumentBlock | None, str, int | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        move = bt[i][j]
        if i > 0 and j > 0 and move == 0:
            a, b = old_blocks[i - 1], new_blocks[j - 1]
            status = "unchanged" if a.clean_text == b.clean_text else "modified"
            aligned.append((a, b, status, None))
            i -= 1
            j -= 1
        elif i > 0 and (j == 0 or move == 1):
            aligned.append((old_blocks[i - 1], None, "deleted", None))
            i -= 1
        else:
            aligned.append((None, new_blocks[j - 1], "added", None))
            j -= 1

    aligned.reverse()

    del_indices = [
        idx for idx, (a, _, st, _) in enumerate(aligned) if st == "deleted" and a and a.block_type == "paragraph"
    ]
    add_indices = [
        idx for idx, (_, b, st, _) in enumerate(aligned) if st == "added" and b and b.block_type == "paragraph"
    ]
    used_add: set[int] = set()
    for d_idx in del_indices:
        a = aligned[d_idx][0]
        assert a is not None
        best_j = -1
        best_s = 0.0
        for a_idx in add_indices:
            if a_idx in used_add:
                continue
            b = aligned[a_idx][1]
            assert b is not None
            s = _para_alignment_score(a, b)
            if s > best_s:
                best_s = s
                best_j = a_idx
        if best_j != -1 and best_s >= 0.65:
            used_add.add(best_j)
            aligned[d_idx] = (aligned[d_idx][0], None, "moved_from", best_j)
            aligned[best_j] = (None, aligned[best_j][1], "moved_to", d_idx)

    return aligned


def _needs_space_between(prev: Token | None, curr: Token) -> bool:
    if prev is None:
        return False
    if prev.kind == "br" or curr.kind == "br":
        return False
    return bool(curr.had_space_before)


def _tokens_to_display_items(tokens: list[Token]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    buf: list[Token] = []
    buf_style: tuple[bool, bool, bool] = (False, False, False)

    def _flush_buf() -> None:
        if not buf:
            return
        parts: list[str] = []
        prev: Token | None = None
        for tok in buf:
            if prev is not None and _needs_space_between(prev, tok):
                parts.append(" ")
            parts.append(tok.text)
            prev = tok
        item: dict[str, Any] = {"kind": "text", "text": "".join(parts)}
        if buf_style[0]:
            item["bold"] = True
        if buf_style[1]:
            item["italic"] = True
        if buf_style[2]:
            item["strike"] = True
        items.append(item)
        buf.clear()

    prev_tok: Token | None = None
    for tok in tokens:
        if tok.kind in ("ref", "cite", "math", "code", "link", "fn", "br"):
            if prev_tok is not None and tok.had_space_before and tok.kind not in ("br", "fn"):
                if buf:
                    buf_text_has_trailing = False
                    _flush_buf()
                    if items and items[-1]["kind"] == "text":
                        items[-1]["text"] += " "
                        buf_text_has_trailing = True
                    if not buf_text_has_trailing:
                        items.append({"kind": "text", "text": " "})
                elif items:
                    items.append({"kind": "text", "text": " "})
            else:
                _flush_buf()
            if tok.kind == "link":
                lbl, url = tok.value.split("|", 1) if "|" in tok.value else (tok.value, tok.value)
                it: dict[str, Any] = {"kind": "link", "text": lbl, "value": url}
            elif tok.kind == "ref" and "|" in tok.value:
                rk, rdisp = tok.value.split("|", 1)
                it = {"kind": "ref", "value": rk, "text": rdisp}
            elif tok.kind == "code":
                it = {"kind": "code", "text": tok.value, "value": tok.value}
            elif tok.kind == "fn":
                it = {"kind": "fn", "text": tok.value, "value": tok.value}
            elif tok.kind == "br":
                it = {"kind": "br", "text": "\n"}
            else:
                it = {"kind": tok.kind, "value": tok.value, "text": tok.text}
            if tok.bold:
                it["bold"] = True
            if tok.italic:
                it["italic"] = True
            if tok.strike:
                it["strike"] = True
            items.append(it)
            prev_tok = tok
        else:
            st = (tok.bold, tok.italic, tok.strike)
            if buf and st != buf_style:
                carry_space = tok.had_space_before
                _flush_buf()
                if carry_space:
                    items.append({"kind": "text", "text": " "})
                buf_style = st
                buf.append(Token(tok.text, tok.kind, tok.value, tok.norm, tok.bold, tok.italic, False, tok.strike))
            else:
                if not buf:
                    if prev_tok is not None and prev_tok.kind in ("ref", "cite", "math", "code", "link", "fn") and tok.had_space_before:
                        items.append({"kind": "text", "text": " "})
                    buf_style = st
                    buf.append(Token(tok.text, tok.kind, tok.value, tok.norm, tok.bold, tok.italic, False, tok.strike))
                else:
                    buf.append(tok)
            prev_tok = tok
    _flush_buf()
    return items


def _join_tokens_text(tokens: list[Token]) -> str:
    parts: list[str] = []
    prev: Token | None = None
    for tok in tokens:
        if _needs_space_between(prev, tok):
            parts.append(" ")
        if tok.kind == "ref":
            rk = tok.value.split("|", 1)[0] if "|" in tok.value else tok.value
            parts.append(f"\\ref{{{rk}}}")
        elif tok.kind == "cite":
            parts.append(f"\\cite{{{tok.value}}}")
        elif tok.kind == "math":
            parts.append(f"${tok.value}$")
        elif tok.kind == "code":
            parts.append(f"`{tok.value}`")
        elif tok.kind == "fn":
            parts.append(f"[^{tok.value}]")
        elif tok.kind == "link":
            lbl, url = tok.value.split("|", 1) if "|" in tok.value else (tok.value, tok.value)
            parts.append(f"[{lbl}]({url})" if lbl != url else url)
        elif tok.kind == "br":
            parts.append("\n")
        else:
            parts.append(tok.text)
        prev = tok
    return "".join(parts)


def diff_paragraph(old_text: str, new_text: str, para_index: int) -> dict[str, Any]:
    """
    Compute word/phrase-level diff matching the clean academic pill style.
    Returns structured segments for both split view and inline view, plus
    per-paragraph metrics (word_delta, similarity, jaccard_similarity, bigram_similarity).
    """
    old_toks = _content_tokens(tokenize_academic(old_text))
    new_toks = _content_tokens(tokenize_academic(new_text))

    old_keys = [t.norm for t in old_toks]
    new_keys = [t.norm for t in new_toks]

    sm = difflib.SequenceMatcher(a=old_keys, b=new_keys, autojunk=False)
    opcodes = _coalesce_fragmented_opcodes(sm.get_opcodes(), old_toks, new_toks)

    old_words = _word_tokens_for_sim(old_toks)
    new_words = _word_tokens_for_sim(new_toks)
    old_wc = count_academic_words(old_text)
    new_wc = count_academic_words(new_text)
    word_delta = new_wc - old_wc

    if not old_words and not new_words:
        lcs_sim = 1.0
        jacc_sim = 1.0
        bigram_sim = 1.0
        matched_words = 0
    elif not old_words or not new_words:
        lcs_sim = 0.0
        jacc_sim = 0.0
        bigram_sim = 0.0
        matched_words = 0
    else:
        sm_w = difflib.SequenceMatcher(a=old_words, b=new_words, autojunk=False)
        matched_words = sum(block.size for block in sm_w.get_matching_blocks())
        lcs_sim = (2.0 * matched_words) / (len(old_words) + len(new_words))
        sa, sb = set(old_words), set(new_words)
        jacc_sim = len(sa & sb) / max(1, len(sa | sb))
        bga = set(zip(old_words, old_words[1:])) if len(old_words) > 1 else sa
        bgb = set(zip(new_words, new_words[1:])) if len(new_words) > 1 else sb
        bigram_sim = len(bga & bgb) / max(1, len(bga | bgb))

    added_words = max(0, len(new_words) - matched_words)
    deleted_words = max(0, len(old_words) - matched_words)

    segments: list[dict[str, Any]] = []
    hunk_counter = 0
    prev_old_tok: Token | None = None
    prev_new_tok: Token | None = None

    for tag, i1, i2, j1, j2 in opcodes:
        old_slice = old_toks[i1:i2]
        new_slice = new_toks[j1:j2]

        if tag == "equal":
            if not new_slice:
                continue
            lead_old = _needs_space_between(prev_old_tok, old_slice[0])
            lead_new = _needs_space_between(prev_new_tok, new_slice[0])
            segments.append(
                {
                    "type": "equal",
                    "items": _tokens_to_display_items(new_slice),
                    "old_items": _tokens_to_display_items(old_slice),
                    "raw": _join_tokens_text(new_slice),
                    "lead_space_old": lead_old,
                    "lead_space_new": lead_new,
                }
            )
            prev_old_tok = old_slice[-1]
            prev_new_tok = new_slice[-1]
        elif tag == "replace":
            hunk_id = f"p{para_index}_h{hunk_counter}"
            hunk_counter += 1
            lead_old = _needs_space_between(prev_old_tok, old_slice[0]) if old_slice else False
            lead_new = _needs_space_between(prev_new_tok, new_slice[0]) if new_slice else False
            segments.append(
                {
                    "type": "replace",
                    "hunk_id": hunk_id,
                    "old_items": _tokens_to_display_items(old_slice),
                    "new_items": _tokens_to_display_items(new_slice),
                    "old_raw": _join_tokens_text(old_slice),
                    "new_raw": _join_tokens_text(new_slice),
                    "lead_space_old": lead_old,
                    "lead_space_new": lead_new,
                }
            )
            if old_slice:
                prev_old_tok = old_slice[-1]
            if new_slice:
                prev_new_tok = new_slice[-1]
        elif tag == "delete":
            hunk_id = f"p{para_index}_h{hunk_counter}"
            hunk_counter += 1
            lead_old = _needs_space_between(prev_old_tok, old_slice[0]) if old_slice else False
            segments.append(
                {
                    "type": "delete",
                    "hunk_id": hunk_id,
                    "old_items": _tokens_to_display_items(old_slice),
                    "old_raw": _join_tokens_text(old_slice),
                    "lead_space_old": lead_old,
                    "lead_space_new": False,
                }
            )
            if old_slice:
                prev_old_tok = old_slice[-1]
        elif tag == "insert":
            hunk_id = f"p{para_index}_h{hunk_counter}"
            hunk_counter += 1
            lead_new = _needs_space_between(prev_new_tok, new_slice[0]) if new_slice else False
            segments.append(
                {
                    "type": "insert",
                    "hunk_id": hunk_id,
                    "new_items": _tokens_to_display_items(new_slice),
                    "new_raw": _join_tokens_text(new_slice),
                    "lead_space_old": False,
                    "lead_space_new": lead_new,
                }
            )
            if new_slice:
                prev_new_tok = new_slice[-1]

    return {
        "segments": segments,
        "hunk_count": hunk_counter,
        "old_word_count": old_wc,
        "new_word_count": new_wc,
        "word_delta": word_delta,
        "added_words": added_words,
        "deleted_words": deleted_words,
        "similarity": round(lcs_sim * 100, 1),
        "similarity_int": int(round(lcs_sim * 100)),
        "jaccard_similarity": round(jacc_sim * 100, 1),
        "bigram_similarity": round(bigram_sim * 100, 1),
    }


# ---------------- v1.3: Orphan Stopword Diff Coalescing & Table Cell Diff ----------------

_GLUE_WORDS = {
    "a", "an", "the", "of", "in", "to", "for", "and", "or", "on", "at", "by", "as",
    "is", "are", "was", "were", "be", "with", "that", "this", "it", "from", "its",
    "的", "了", "和", "与", "在", "对", "中", "及", "为", "是", "于", "将",
    ",", ";", ":", "，", "、",
}


def _is_orphan_glue(tokens: list[Token]) -> bool:
    if not tokens or len(tokens) > 2:
        return False
    for t in tokens:
        # Never absorb atomic academic tokens, numbers, or sentence-ending punctuation!
        if t.kind in ("ref", "cite", "math", "num"):
            return False
        if t.norm not in _GLUE_WORDS:
            return False
    return True


def _coalesce_fragmented_opcodes(
    opcodes: list[tuple[str, int, int, int, int]],
    old_toks: list[Token],
    new_toks: list[Token],
) -> list[tuple[str, int, int, int, int]]:
    """
    Smooth over noisy single-stopword matches trapped between two adjacent edits
    (e.g. [del/ins] 'of' [del/ins] -> single clean phrase replace) while strictly
    protecting numbers, citations, cross-refs, formulas, and sentence boundaries.
    """
    if len(opcodes) < 3:
        return opcodes
    out: list[tuple[str, int, int, int, int]] = []
    i = 0
    while i < len(opcodes):
        cur = opcodes[i]
        if (
            out
            and cur[0] == "equal"
            and i + 1 < len(opcodes)
            and out[-1][0] != "equal"
            and opcodes[i + 1][0] != "equal"
        ):
            eq_toks = old_toks[cur[1] : cur[2]]
            prev = out[-1]
            nxt = opcodes[i + 1]
            merged_old_len = nxt[2] - prev[1]
            merged_new_len = nxt[4] - prev[3]
            if _is_orphan_glue(eq_toks) and merged_old_len <= 16 and merged_new_len <= 16:
                out[-1] = ("replace", prev[1], nxt[2], prev[3], nxt[4])
                i += 2
                continue
        out.append(cur)
        i += 1
    return out


_CELL_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _norm_rich_cell(cell: Any) -> dict[str, Any]:
    if isinstance(cell, dict):
        return {
            "text": str(cell.get("text", "")),
            "colspan": max(1, int(cell.get("colspan", 1))),
            "rowspan": max(1, int(cell.get("rowspan", 1))),
            "bold": bool(cell.get("bold", False)),
        }
    return {"text": str(cell), "colspan": 1, "rowspan": 1, "bold": False}


def _compute_cell_numeric_delta(old_txt: str, new_txt: str) -> dict[str, Any] | None:
    o_plain = ATOMIC_TOKEN_RE.sub("", strip_style_markers(old_txt)).strip()
    n_plain = ATOMIC_TOKEN_RE.sub("", strip_style_markers(new_txt)).strip()
    o_nums = _CELL_NUM_RE.findall(o_plain)
    n_nums = _CELL_NUM_RE.findall(n_plain)
    if len(o_nums) != 1 or len(n_nums) != 1:
        return None
    if len(re.sub(r"[\d.\-+%\s±,]", "", o_plain)) > 6 or len(re.sub(r"[\d.\-+%\s±,]", "", n_plain)) > 6:
        return None
    try:
        ov = float(o_nums[0])
        nv = float(n_nums[0])
    except ValueError:
        return None
    if ov == nv:
        return None
    delta = nv - ov
    pct = round((delta / abs(ov)) * 100.0, 1) if ov != 0 else None
    return {
        "old_num": ov,
        "new_num": nv,
        "delta": round(delta, 4),
        "pct": pct,
    }


def text_to_display_items(text: str) -> list[dict[str, Any]]:
    """
    Parse clean academic text (with ⟦REF/CITE/MATH/CODE/LINK/FN⟧ atoms and ⟦B⟧/⟦I⟧/⟦S⟧/⟦BR⟧ markers)
    verbatim into DisplayItem chips without destructive re-tokenization or space guessing.
    """
    if not text:
        return []
    items: list[dict[str, Any]] = []
    bold_depth = 0
    italic_depth = 0
    strike_depth = 0
    pos = 0

    def _emit_plain(chunk: str) -> None:
        if not chunk:
            return
        item: dict[str, Any] = {"kind": "text", "text": chunk}
        if bold_depth > 0:
            item["bold"] = True
        if italic_depth > 0:
            item["italic"] = True
        if strike_depth > 0:
            item["strike"] = True
        items.append(item)

    for m in INLINE_TOKEN_RE.finditer(text):
        if m.start() > pos:
            _emit_plain(text[pos : m.start()])
        if m.group(1):
            tag = m.group(1).lower()
            val = m.group(2)
            if tag == "link":
                lbl, url = val.split("|", 1) if "|" in val else (val, val)
                item = {"kind": "link", "text": lbl, "value": url}
            elif tag == "ref" and "|" in val:
                rk, rdisp = val.split("|", 1)
                item = {"kind": "ref", "value": rk, "text": rdisp}
            elif tag == "code":
                item = {"kind": "code", "text": val, "value": val}
            elif tag == "fn":
                item = {"kind": "fn", "text": val, "value": val}
            elif tag == "sp":
                item = {"kind": "sp", "text": " ", "value": val}
            else:
                item = {"kind": tag, "value": val, "text": m.group(0)}
            if bold_depth > 0:
                item["bold"] = True
            if italic_depth > 0:
                item["italic"] = True
            if strike_depth > 0:
                item["strike"] = True
            items.append(item)
        else:
            ctrl = m.group(3)
            if ctrl == "B":
                bold_depth += 1
            elif ctrl == "/B":
                bold_depth = max(0, bold_depth - 1)
            elif ctrl == "I":
                italic_depth += 1
            elif ctrl == "/I":
                italic_depth = max(0, italic_depth - 1)
            elif ctrl == "S":
                strike_depth += 1
            elif ctrl == "/S":
                strike_depth = max(0, strike_depth - 1)
            elif ctrl == "BR":
                items.append({"kind": "br", "text": "\n"})
        pos = m.end()
    if pos < len(text):
        _emit_plain(text[pos:])
    return items


def _cell_display_items(text: str) -> list[dict[str, Any]]:
    return text_to_display_items(text)


def serialize_plain_table_rows(rows_raw: list[list[Any]]) -> list[list[dict[str, Any]]]:
    """Normalize raw table rows into DisplayItem-enriched plain cells for single-doc preview."""
    norm_rows = [[_norm_rich_cell(c) for c in r] for r in rows_raw]
    return [
        [
            {
                "text": c["text"],
                "items": _cell_display_items(c["text"]),
                "colspan": c["colspan"],
                "rowspan": c["rowspan"],
                "bold": c["bold"],
            }
            for c in r
        ]
        for r in norm_rows
    ]


def diff_table_rows(
    old_rows_raw: list[list[Any]],
    new_rows_raw: list[list[Any]],
    para_index: int,
) -> dict[str, Any]:
    """
    v1.4 Rich Table Diff:
    Preserves colspan/rowspan/bold, renders KaTeX atoms inside cells,
    tracks optimal-value bold shifts, computes hover numeric delta (Δ / %),
    and returns old_rows/new_rows for Single-Table vs Dual-Table view toggle!
    """
    old_rows = [[_norm_rich_cell(c) for c in r] for r in old_rows_raw]
    new_rows = [[_norm_rich_cell(c) for c in r] for r in new_rows_raw]

    old_sigs = [" | ".join(c["text"] for c in r).lower() for r in old_rows]
    new_sigs = [" | ".join(c["text"] for c in r).lower() for r in new_rows]
    sm = difflib.SequenceMatcher(a=old_sigs, b=new_sigs, autojunk=False)

    aligned_rows: list[dict[str, Any]] = []
    changed_cells = 0
    bold_changed_cells = 0
    total_cells = 0

    def _make_cell_payload(
        oc: dict[str, Any] | None,
        nc: dict[str, Any] | None,
        row_idx: int,
        c_idx: int,
    ) -> tuple[dict[str, Any], bool, bool]:
        if oc is None and nc is not None:
            return (
                {
                    "status": "added",
                    "old": "",
                    "new": nc["text"],
                    "items": _cell_display_items(nc["text"]),
                    "colspan": nc["colspan"],
                    "rowspan": nc["rowspan"],
                    "old_bold": False,
                    "new_bold": nc["bold"],
                    "bold_changed": False,
                    "numeric_delta": None,
                    "segments": [],
                },
                True,
                False,
            )
        if nc is None and oc is not None:
            return (
                {
                    "status": "deleted",
                    "old": oc["text"],
                    "new": "",
                    "items": _cell_display_items(oc["text"]),
                    "colspan": oc["colspan"],
                    "rowspan": oc["rowspan"],
                    "old_bold": oc["bold"],
                    "new_bold": False,
                    "bold_changed": False,
                    "numeric_delta": None,
                    "segments": [],
                },
                True,
                False,
            )
        assert oc is not None and nc is not None
        bold_changed = oc["bold"] != nc["bold"]
        if oc["text"] == nc["text"]:
            return (
                {
                    "status": "modified" if bold_changed else "unchanged",
                    "old": oc["text"],
                    "new": nc["text"],
                    "items": _cell_display_items(nc["text"]),
                    "colspan": nc["colspan"],
                    "rowspan": nc["rowspan"],
                    "old_bold": oc["bold"],
                    "new_bold": nc["bold"],
                    "bold_changed": bold_changed,
                    "numeric_delta": None,
                    "segments": [],
                },
                bold_changed,
                bold_changed,
            )
        cd = diff_paragraph(oc["text"], nc["text"], para_index * 1000 + row_idx * 30 + c_idx)
        num_delta = _compute_cell_numeric_delta(oc["text"], nc["text"])
        return (
            {
                "status": "modified",
                "old": oc["text"],
                "new": nc["text"],
                "items": _cell_display_items(nc["text"]),
                "colspan": nc["colspan"],
                "rowspan": nc["rowspan"],
                "old_bold": oc["bold"],
                "new_bold": nc["bold"],
                "bold_changed": bold_changed,
                "numeric_delta": num_delta,
                "segments": cd["segments"],
            },
            True,
            bold_changed,
        )

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for r_i, r_j in zip(range(i1, i2), range(j1, j2)):
                orow, nrow = old_rows[r_i], new_rows[r_j]
                row_cells = []
                row_changed = False
                for c_idx in range(max(len(orow), len(nrow))):
                    oc = orow[c_idx] if c_idx < len(orow) else None
                    nc = nrow[c_idx] if c_idx < len(nrow) else None
                    total_cells += 1
                    cp, is_ch, is_bc = _make_cell_payload(oc, nc, len(aligned_rows), c_idx)
                    if is_ch:
                        changed_cells += 1
                        row_changed = True
                    if is_bc:
                        bold_changed_cells += 1
                    row_cells.append(cp)
                aligned_rows.append({"status": "modified" if row_changed else "unchanged", "cells": row_cells})
        elif tag == "replace":
            pair_n = min(i2 - i1, j2 - j1)
            for k in range(pair_n):
                orow = old_rows[i1 + k]
                nrow = new_rows[j1 + k]
                row_cells = []
                row_changed = False
                if len(orow) != len(nrow) and all(c["colspan"] == 1 for c in orow) and all(c["colspan"] == 1 for c in nrow):
                    csm = difflib.SequenceMatcher(
                        a=[c["text"].lower() for c in orow],
                        b=[c["text"].lower() for c in nrow],
                        autojunk=False,
                    )
                    col_k = 0
                    for ctag, ci1, ci2, cj1, cj2 in csm.get_opcodes():
                        if ctag == "equal":
                            for ci, cj in zip(range(ci1, ci2), range(cj1, cj2)):
                                total_cells += 1
                                cp, is_ch, is_bc = _make_cell_payload(orow[ci], nrow[cj], len(aligned_rows), col_k)
                                col_k += 1
                                if is_ch:
                                    changed_cells += 1
                                    row_changed = True
                                if is_bc:
                                    bold_changed_cells += 1
                                row_cells.append(cp)
                        elif ctag == "replace":
                            pn = min(ci2 - ci1, cj2 - cj1)
                            for m in range(pn):
                                total_cells += 1
                                cp, is_ch, is_bc = _make_cell_payload(orow[ci1 + m], nrow[cj1 + m], len(aligned_rows), col_k)
                                col_k += 1
                                if is_ch:
                                    changed_cells += 1
                                    row_changed = True
                                if is_bc:
                                    bold_changed_cells += 1
                                row_cells.append(cp)
                            for m in range(pn, ci2 - ci1):
                                total_cells += 1
                                cp, _, _ = _make_cell_payload(orow[ci1 + m], None, len(aligned_rows), col_k)
                                col_k += 1
                                changed_cells += 1
                                row_changed = True
                                row_cells.append(cp)
                            for m in range(pn, cj2 - cj1):
                                total_cells += 1
                                cp, _, _ = _make_cell_payload(None, nrow[cj1 + m], len(aligned_rows), col_k)
                                col_k += 1
                                changed_cells += 1
                                row_changed = True
                                row_cells.append(cp)
                        elif ctag == "delete":
                            for ci in range(ci1, ci2):
                                total_cells += 1
                                cp, _, _ = _make_cell_payload(orow[ci], None, len(aligned_rows), col_k)
                                col_k += 1
                                changed_cells += 1
                                row_changed = True
                                row_cells.append(cp)
                        elif ctag == "insert":
                            for cj in range(cj1, cj2):
                                total_cells += 1
                                cp, _, _ = _make_cell_payload(None, nrow[cj], len(aligned_rows), col_k)
                                col_k += 1
                                changed_cells += 1
                                row_changed = True
                                row_cells.append(cp)
                else:
                    cols = max(len(orow), len(nrow))
                    for c_idx in range(cols):
                        oc = orow[c_idx] if c_idx < len(orow) else None
                        nc = nrow[c_idx] if c_idx < len(nrow) else None
                        total_cells += 1
                        cp, is_ch, is_bc = _make_cell_payload(oc, nc, len(aligned_rows), c_idx)
                        if is_ch:
                            changed_cells += 1
                            row_changed = True
                        if is_bc:
                            bold_changed_cells += 1
                        row_cells.append(cp)
                aligned_rows.append({"status": "modified" if row_changed else "unchanged", "cells": row_cells})

            for k in range(pair_n, i2 - i1):
                orow = old_rows[i1 + k]
                total_cells += len(orow)
                changed_cells += len(orow)
                aligned_rows.append(
                    {"status": "deleted", "cells": [_make_cell_payload(c, None, len(aligned_rows), ci)[0] for ci, c in enumerate(orow)]}
                )
            for k in range(pair_n, j2 - j1):
                nrow = new_rows[j1 + k]
                total_cells += len(nrow)
                changed_cells += len(nrow)
                aligned_rows.append(
                    {"status": "added", "cells": [_make_cell_payload(None, c, len(aligned_rows), ci)[0] for ci, c in enumerate(nrow)]}
                )
        elif tag == "delete":
            for r_i in range(i1, i2):
                orow = old_rows[r_i]
                total_cells += len(orow)
                changed_cells += len(orow)
                aligned_rows.append(
                    {"status": "deleted", "cells": [_make_cell_payload(c, None, len(aligned_rows), ci)[0] for ci, c in enumerate(orow)]}
                )
        elif tag == "insert":
            for r_j in range(j1, j2):
                nrow = new_rows[r_j]
                total_cells += len(nrow)
                changed_cells += len(nrow)
                aligned_rows.append(
                    {"status": "added", "cells": [_make_cell_payload(None, c, len(aligned_rows), ci)[0] for ci, c in enumerate(nrow)]}
                )

    def _serialize_plain_rows(rlist: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
        return [
            [
                {
                    "text": c["text"],
                    "items": _cell_display_items(c["text"]),
                    "colspan": c["colspan"],
                    "rowspan": c["rowspan"],
                    "bold": c["bold"],
                }
                for c in r
            ]
            for r in rlist
        ]

    return {
        "rows": aligned_rows,
        "old_rows": _serialize_plain_rows(old_rows),
        "new_rows": _serialize_plain_rows(new_rows),
        "changed_cells": changed_cells,
        "bold_changed_cells": bold_changed_cells,
        "total_cells": total_cells,
    }

