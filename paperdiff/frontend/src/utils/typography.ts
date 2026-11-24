/**
 * @file typography.ts
 * @description Single-source academic reading typography solver (`resolveBlockTypography`),
 * 5-preset definitions (`auto` + 4 named academic presets), and backward-compatible
 * `localStorage` preference normalizer shared across `SingleDocWorkspace` and PDF exports.
 */

import type {
  BlockStyle,
  BlockType,
  DocLanguage,
  DocumentZone,
  IndentMode,
  ListMeta,
  ParagraphGap,
  TextAlignMode,
  TypographyPrefs,
  TypographyPreset,
} from '../types';

export interface ResolvedBlockTypography {
  /** Positive for first-line indent, negative for hanging indent, 0 for none (CSS `text-indent`). */
  textIndentEm: number;
  /** Block left padding in `em` (includes hanging indent inset or abstract/quote inset). */
  paddingLeftEm: number;
  /** Block right padding in `em`. */
  paddingRightEm: number;
  /** Effective horizontal text alignment. */
  textAlign: 'left' | 'center' | 'right' | 'justify';
  /** Effective line-height ratio. */
  lineHeight: number;
  /** True when `semantic_role === 'abstract'`. */
  isAbstract: boolean;
  /** True when block uses hanging indent (explicit `hanging_indent_em` or `reference_item`). */
  isHanging: boolean;
  /** Nested blockquote depth (1..4) for `blockquote` blocks, else 0. */
  quoteDepth: number;
  /** Parent list depth (0..5) for child blocks nested inside list items, else null. */
  parentListDepth: number | null;
  /** Enable CSS hyphenation on justified English prose to avoid wide word-spacing rivers. */
  hyphenate: boolean;
}

export const LIST_BULLETS = ['•', '◦', '▪', '‣', '–', '·'] as const;

export const DEFAULT_TYPOGRAPHY_PREFS: TypographyPrefs = {
  typographyPreset: 'auto',
  indentMode: 'auto',
  lineHeight: 1.88,
  paragraphGap: 'normal',
  textAlign: 'auto',
};

export const TYPOGRAPHY_PRESETS: Record<
  Exclude<TypographyPreset, 'custom'>,
  Omit<TypographyPrefs, 'typographyPreset'>
> = {
  auto: { indentMode: 'auto', lineHeight: 1.88, paragraphGap: 'normal', textAlign: 'auto' },
  source: { indentMode: 'source', lineHeight: 1.85, paragraphGap: 'normal', textAlign: 'auto' },
  zh_thesis: { indentMode: '2em', lineHeight: 1.92, paragraphGap: 'compact', textAlign: 'justify' },
  en_journal: { indentMode: 'source', lineHeight: 1.76, paragraphGap: 'normal', textAlign: 'justify' },
  modern_note: { indentMode: 'none', lineHeight: 1.82, paragraphGap: 'relaxed', textAlign: 'left' },
};

export const TYPOGRAPHY_PRESET_ITEMS: {
  id: Exclude<TypographyPreset, 'custom'>;
  label: string;
  desc: string;
}[] = [
  { id: 'auto', label: '智能默认', desc: '尊重原稿指令；中文正文自动 2em 首行缩进，英文段距' },
  { id: 'source', label: '原稿保真', desc: '严格按原稿缩进与对齐渲染，无声明不额外缩进' },
  { id: 'zh_thesis', label: '中文论文', desc: '统一 2em 首行缩进、两端对齐、紧凑段距' },
  { id: 'en_journal', label: '英文期刊', desc: 'Nature / IEEE 期刊风：两端对齐、自动连字、紧凑行距' },
  { id: 'modern_note', label: '现代笔记', desc: '无首行缩进、左对齐、舒朗段距' },
];

const VALID_PRESETS = new Set<TypographyPreset>([
  'auto',
  'source',
  'zh_thesis',
  'en_journal',
  'modern_note',
  'custom',
]);
const VALID_INDENT_MODES = new Set<IndentMode>(['auto', 'source', '2em', 'none']);
const VALID_GAPS = new Set<ParagraphGap>(['compact', 'normal', 'relaxed']);
const VALID_ALIGNS = new Set<TextAlignMode>(['auto', 'justify', 'left']);
const VALID_BLOCK_ALIGNS = new Set(['left', 'center', 'right', 'justify']);

function clampNum(val: number, lo: number, hi: number): number {
  if (!Number.isFinite(val)) return lo;
  return Math.round(Math.min(hi, Math.max(lo, val)) * 100) / 100;
}

function clampInt(val: number, lo: number, hi: number): number {
  if (!Number.isFinite(val)) return lo;
  return Math.min(hi, Math.max(lo, Math.trunc(val)));
}

/**
 * Safely normalizes persisted preferences (including legacy v1.1.0 `localStorage` blobs
 * lacking typography keys) into a complete, bounded `TypographyPrefs` object.
 */
export function normalizeTypographyPrefs(raw: unknown): TypographyPrefs {
  if (!raw || typeof raw !== 'object') {
    return { ...DEFAULT_TYPOGRAPHY_PREFS };
  }
  const obj = raw as Record<string, unknown>;
  const preset: TypographyPreset =
    typeof obj.typographyPreset === 'string' && VALID_PRESETS.has(obj.typographyPreset as TypographyPreset)
      ? (obj.typographyPreset as TypographyPreset)
      : 'auto';

  const base = preset !== 'custom' ? TYPOGRAPHY_PRESETS[preset] : DEFAULT_TYPOGRAPHY_PREFS;

  const indentMode: IndentMode =
    typeof obj.indentMode === 'string' && VALID_INDENT_MODES.has(obj.indentMode as IndentMode)
      ? (obj.indentMode as IndentMode)
      : base.indentMode;

  const lineHeight =
    typeof obj.lineHeight === 'number' && Number.isFinite(obj.lineHeight)
      ? clampNum(obj.lineHeight, 1.5, 2.3)
      : base.lineHeight;

  const paragraphGap: ParagraphGap =
    typeof obj.paragraphGap === 'string' && VALID_GAPS.has(obj.paragraphGap as ParagraphGap)
      ? (obj.paragraphGap as ParagraphGap)
      : base.paragraphGap;

  const textAlign: TextAlignMode =
    typeof obj.textAlign === 'string' && VALID_ALIGNS.has(obj.textAlign as TextAlignMode)
      ? (obj.textAlign as TextAlignMode)
      : base.textAlign;

  return {
    typographyPreset: preset,
    indentMode,
    lineHeight,
    paragraphGap,
    textAlign,
  };
}

/** Applies a named academic typography preset and returns complete settings. */
export function applyTypographyPreset(preset: Exclude<TypographyPreset, 'custom'>): TypographyPrefs {
  const cfg = TYPOGRAPHY_PRESETS[preset] || TYPOGRAPHY_PRESETS.auto;
  return {
    typographyPreset: preset,
    ...cfg,
  };
}

/** Updates a single fine-grained typography parameter and switches preset tag to `'custom'`. */
export function updateTypographyPref<K extends keyof Omit<TypographyPrefs, 'typographyPreset'>>(
  cur: TypographyPrefs,
  key: K,
  value: TypographyPrefs[K],
): TypographyPrefs {
  const next = {
    ...cur,
    typographyPreset: 'custom' as TypographyPreset,
    [key]: key === 'lineHeight' && typeof value === 'number' ? clampNum(value, 1.5, 2.3) : value,
  };
  return normalizeTypographyPrefs(next);
}

/** Returns the 6-level unordered list bullet symbol for depth 0..5. */
export function getListBullet(depth: number): string {
  return LIST_BULLETS[clampInt(depth, 0, LIST_BULLETS.length - 1)];
}

/** Computes progressive left padding in pixels for list items of depth 0..5. */
export function getListPaddingPx(depth: number): number {
  return 12 + clampInt(depth, 0, 5) * 22;
}

/**
 * Computes left margin in pixels for child blocks (continuation paragraphs, fenced code,
 * display math, nested blockquotes) inside a list item so their left edge aligns with the
 * parent list item's text column (padding + 22px marker + 10px gap).
 */
export function getParentListMarginPx(parentListDepth: number): number {
  return getListPaddingPx(parentListDepth) + 32;
}

/** Maps `paragraphGap` setting to Tailwind vertical spacing class on the article body container. */
export function getParagraphGapClass(gap: ParagraphGap): string {
  if (gap === 'compact') return 'space-y-2.5';
  if (gap === 'relaxed') return 'space-y-6';
  return 'space-y-4';
}

/**
 * Resolves effective CSS typography properties for a single IR block according to W1-TYPO §3.3.
 *
 * Precedence:
 * 1. Explicit source structural constraints (hanging indent, center/right align, `\noindent`).
 * 2. User panel overrides (`indentMode`, `textAlign`, `lineHeight`).
 * 3. Smart academic language default (`D-01`: Chinese body prose -> 2em, English -> 0).
 */
export function resolveBlockTypography(
  block: {
    block_type: BlockType;
    zone?: DocumentZone;
    style?: BlockStyle | null;
    list_meta?: ListMeta | null;
  },
  docLang: DocLanguage | undefined,
  prefs: TypographyPrefs,
): ResolvedBlockTypography {
  const style: BlockStyle = block.style || {};
  const zone: DocumentZone = block.zone || 'body';
  const btype = block.block_type;
  const lineHeight = clampNum(prefs.lineHeight, 1.5, 2.3);

  const isAbstract = style.semantic_role === 'abstract';
  const parentListDepth =
    typeof style.parent_list_depth === 'number' && Number.isFinite(style.parent_list_depth)
      ? clampInt(style.parent_list_depth, 0, 5)
      : null;
  const quoteDepth =
    btype === 'blockquote'
      ? clampInt(typeof style.quote_depth === 'number' ? style.quote_depth : 1, 1, 4)
      : 0;

  // 1. Resolve horizontal text alignment (source explicit align always wins)
  let textAlign: 'left' | 'center' | 'right' | 'justify' = 'left';
  if (typeof style.align === 'string' && VALID_BLOCK_ALIGNS.has(style.align)) {
    textAlign = style.align;
  } else if (btype === 'paragraph' && zone === 'body') {
    if (prefs.textAlign === 'left') {
      textAlign = 'left';
    } else if (prefs.textAlign === 'justify') {
      textAlign = 'justify';
    } else {
      // 'auto': justified CJK prose, clean ragged-right English prose
      textAlign = docLang === 'en' ? 'left' : 'justify';
    }
  }

  // 2. Resolve left/right block indents & semantic insets
  let paddingLeftEm =
    typeof style.left_indent_em === 'number' ? clampNum(style.left_indent_em, 0, 8) : 0;
  let paddingRightEm =
    typeof style.right_indent_em === 'number' ? clampNum(style.right_indent_em, 0, 8) : 0;

  if (isAbstract) {
    paddingLeftEm = Math.max(paddingLeftEm, 1.25);
    paddingRightEm = Math.max(paddingRightEm, 1.25);
  }

  // 3. Reference items keep hanging semantics via `.pd-ref-item` and are exempt from first-line indent
  if (btype === 'reference_item') {
    return {
      textIndentEm: 0,
      paddingLeftEm,
      paddingRightEm,
      textAlign,
      lineHeight,
      isAbstract: false,
      isHanging: true,
      quoteDepth: 0,
      parentListDepth,
      hyphenate: false,
    };
  }

  // 4. Non-body-paragraph blocks are exempt from body first-line indent
  if (zone !== 'body' || btype !== 'paragraph') {
    return {
      textIndentEm: 0,
      paddingLeftEm,
      paddingRightEm,
      textAlign,
      lineHeight,
      isAbstract,
      isHanging: false,
      quoteDepth,
      parentListDepth,
      hyphenate: false,
    };
  }

  // 5. Explicit hanging indent (OOXML w:left is wrapped-line margin; w:hanging pulls line 1 left)
  const hanging =
    typeof style.hanging_indent_em === 'number' ? clampNum(style.hanging_indent_em, 0, 4) : 0;
  if (hanging > 0) {
    return {
      textIndentEm: -hanging,
      paddingLeftEm: Math.max(paddingLeftEm, hanging),
      paddingRightEm,
      textAlign,
      lineHeight,
      isAbstract,
      isHanging: true,
      quoteDepth: 0,
      parentListDepth,
      hyphenate: docLang === 'en' && textAlign === 'justify',
    };
  }

  // 6. First-line indent resolution for body paragraphs
  let textIndentEm = 0;
  const hasExplicitFirstLine =
    typeof style.first_line_indent_em === 'number' && Number.isFinite(style.first_line_indent_em);
  const explicitFirstLine = hasExplicitFirstLine
    ? clampNum(style.first_line_indent_em as number, 0, 4)
    : 0;

  if (textAlign === 'center' || textAlign === 'right') {
    textIndentEm = 0;
  } else if (parentListDepth !== null) {
    // Continuation paragraphs inside list items align flush with list text unless explicitly indented
    textIndentEm =
      style.explicit_indent === 'indent' && hasExplicitFirstLine ? explicitFirstLine : 0;
  } else if (isAbstract) {
    // Abstract callout boxes only indent if source explicitly requests it
    textIndentEm =
      style.explicit_indent === 'none'
        ? 0
        : hasExplicitFirstLine && prefs.indentMode !== 'none'
          ? explicitFirstLine
          : 0;
  } else if (prefs.indentMode === 'none') {
    textIndentEm = 0;
  } else if (prefs.indentMode === '2em') {
    textIndentEm = style.explicit_indent === 'none' ? 0 : 2.0;
  } else if (prefs.indentMode === 'source') {
    textIndentEm =
      style.explicit_indent === 'none' ? 0 : hasExplicitFirstLine ? explicitFirstLine : 0;
  } else {
    // prefs.indentMode === 'auto' (D-01 smart academic default)
    if (style.explicit_indent === 'none') {
      textIndentEm = 0;
    } else if (hasExplicitFirstLine) {
      textIndentEm = explicitFirstLine;
    } else if (docLang === 'zh') {
      textIndentEm = 2.0;
    } else {
      textIndentEm = 0;
    }
  }

  return {
    textIndentEm,
    paddingLeftEm,
    paddingRightEm,
    textAlign,
    lineHeight,
    isAbstract,
    isHanging: false,
    quoteDepth: 0,
    parentListDepth,
    hyphenate: docLang === 'en' && textAlign === 'justify',
  };
}
