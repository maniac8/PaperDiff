/**
 * @file typography.test.mjs
 * @description Node built-in `node --test` unit suite for W1-T09 (typography solver precedence &
 * semantic block exemptions) and W1-T10 (preference normalization & v1.1.0 localStorage migration).
 * Zero external test dependencies.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DEFAULT_TYPOGRAPHY_PREFS,
  LIST_BULLETS,
  applyTypographyPreset,
  getListBullet,
  getListPaddingPx,
  getParagraphGapClass,
  getParentListMarginPx,
  normalizeTypographyPrefs,
  resolveBlockTypography,
  updateTypographyPref,
} from './typography.ts';

test('W1-T09: auto preset indents Chinese prose 2em, leaves English 0, honors explicit source directives', () => {
  const autoPrefs = applyTypographyPreset('auto');
  assert.equal(autoPrefs.typographyPreset, 'auto');
  assert.equal(autoPrefs.indentMode, 'auto');
  assert.equal(autoPrefs.lineHeight, 1.88);
  assert.equal(autoPrefs.paragraphGap, 'normal');
  assert.equal(autoPrefs.textAlign, 'auto');

  const zhPlain = resolveBlockTypography({ block_type: 'paragraph', zone: 'body' }, 'zh', autoPrefs);
  assert.equal(zhPlain.textIndentEm, 2.0);
  assert.equal(zhPlain.textAlign, 'justify');
  assert.equal(zhPlain.lineHeight, 1.88);

  const enPlain = resolveBlockTypography({ block_type: 'paragraph', zone: 'body' }, 'en', autoPrefs);
  assert.equal(enPlain.textIndentEm, 0);
  assert.equal(enPlain.textAlign, 'left');

  const zhNoIndent = resolveBlockTypography(
    {
      block_type: 'paragraph',
      zone: 'body',
      style: { explicit_indent: 'none', first_line_indent_em: 0 },
    },
    'zh',
    autoPrefs,
  );
  assert.equal(zhNoIndent.textIndentEm, 0);

  const enExplicitIndent = resolveBlockTypography(
    {
      block_type: 'paragraph',
      zone: 'body',
      style: { explicit_indent: 'indent', first_line_indent_em: 1.5 },
    },
    'en',
    autoPrefs,
  );
  assert.equal(enExplicitIndent.textIndentEm, 1.5);
});

test('W1-T09: all 4 named academic presets and manual custom override work per spec', () => {
  const sourcePrefs = applyTypographyPreset('source');
  assert.equal(sourcePrefs.indentMode, 'source');
  assert.equal(sourcePrefs.lineHeight, 1.85);
  assert.equal(
    resolveBlockTypography({ block_type: 'paragraph', zone: 'body' }, 'zh', sourcePrefs).textIndentEm,
    0,
  );
  assert.equal(
    resolveBlockTypography(
      { block_type: 'paragraph', zone: 'body', style: { first_line_indent_em: 2.0 } },
      'zh',
      sourcePrefs,
    ).textIndentEm,
    2.0,
  );

  const zhThesis = applyTypographyPreset('zh_thesis');
  assert.equal(zhThesis.indentMode, '2em');
  assert.equal(zhThesis.lineHeight, 1.92);
  assert.equal(zhThesis.paragraphGap, 'compact');
  assert.equal(zhThesis.textAlign, 'justify');
  assert.equal(
    resolveBlockTypography({ block_type: 'paragraph', zone: 'body' }, 'en', zhThesis).textIndentEm,
    2.0,
  );
  // Explicit \noindent still respected under zh_thesis
  assert.equal(
    resolveBlockTypography(
      { block_type: 'paragraph', zone: 'body', style: { explicit_indent: 'none', first_line_indent_em: 0 } },
      'zh',
      zhThesis,
    ).textIndentEm,
    0,
  );

  const enJournal = applyTypographyPreset('en_journal');
  assert.equal(enJournal.indentMode, 'source');
  assert.equal(enJournal.lineHeight, 1.76);
  assert.equal(enJournal.textAlign, 'justify');
  const enJournalPara = resolveBlockTypography({ block_type: 'paragraph', zone: 'body' }, 'en', enJournal);
  assert.equal(enJournalPara.textIndentEm, 0);
  assert.equal(enJournalPara.textAlign, 'justify');
  assert.equal(enJournalPara.hyphenate, true);

  const modernNote = applyTypographyPreset('modern_note');
  assert.equal(modernNote.indentMode, 'none');
  assert.equal(modernNote.paragraphGap, 'relaxed');
  assert.equal(modernNote.textAlign, 'left');
  assert.equal(
    resolveBlockTypography(
      { block_type: 'paragraph', zone: 'body', style: { first_line_indent_em: 2.0 } },
      'zh',
      modernNote,
    ).textIndentEm,
    0,
  );

  const custom = updateTypographyPref(zhThesis, 'lineHeight', 2.05);
  assert.equal(custom.typographyPreset, 'custom');
  assert.equal(custom.lineHeight, 2.05);
  assert.equal(custom.indentMode, '2em');
});

test('W1-T09: semantic exemptions, hanging indent, center/right alignment, abstract, list depth & nested quote', () => {
  const zhThesis = applyTypographyPreset('zh_thesis');

  // Center and right aligned paragraphs must never get first-line indent
  const centered = resolveBlockTypography(
    { block_type: 'paragraph', zone: 'body', style: { align: 'center', first_line_indent_em: 2.0 } },
    'zh',
    zhThesis,
  );
  assert.equal(centered.textAlign, 'center');
  assert.equal(centered.textIndentEm, 0);

  const rightAligned = resolveBlockTypography(
    { block_type: 'paragraph', zone: 'body', style: { align: 'right' } },
    'zh',
    zhThesis,
  );
  assert.equal(rightAligned.textAlign, 'right');
  assert.equal(rightAligned.textIndentEm, 0);

  // Hanging indent takes precedence and uses max(left, hanging) per OOXML
  const hanging = resolveBlockTypography(
    {
      block_type: 'paragraph',
      zone: 'body',
      style: { left_indent_em: 2.0, hanging_indent_em: 2.0 },
    },
    'zh',
    zhThesis,
  );
  assert.equal(hanging.isHanging, true);
  assert.equal(hanging.paddingLeftEm, 2.0);
  assert.equal(hanging.textIndentEm, -2.0);

  // Non-body-paragraph semantic blocks are exempt from positive first-line indent
  for (const btype of ['title', 'heading', 'caption', 'table', 'math', 'code', 'figure', 'list', 'reference_item']) {
    const res = resolveBlockTypography({ block_type: btype, zone: 'body' }, 'zh', zhThesis);
    assert.equal(res.textIndentEm, 0, `${btype} must not receive positive first-line indent`);
  }
  // Frontmatter paragraphs are exempt
  const fm = resolveBlockTypography({ block_type: 'paragraph', zone: 'frontmatter' }, 'zh', zhThesis);
  assert.equal(fm.textIndentEm, 0);

  // Reference item signals hanging semantics
  const ref = resolveBlockTypography({ block_type: 'reference_item', zone: 'backmatter' }, 'zh', zhThesis);
  assert.equal(ref.isHanging, true);
  assert.equal(ref.textIndentEm, 0);

  // Abstract gets left/right inset semantics
  const abs = resolveBlockTypography(
    { block_type: 'paragraph', zone: 'body', style: { semantic_role: 'abstract' } },
    'zh',
    zhThesis,
  );
  assert.equal(abs.isAbstract, true);
  assert.ok(abs.paddingLeftEm >= 1.25);
  assert.ok(abs.paddingRightEm >= 1.25);

  // Nested blockquote depth & list child block alignment
  const quote2 = resolveBlockTypography(
    { block_type: 'blockquote', zone: 'body', style: { quote_depth: 2, left_indent_em: 1.5, right_indent_em: 1.5 } },
    'zh',
    zhThesis,
  );
  assert.equal(quote2.quoteDepth, 2);
  assert.equal(quote2.paddingLeftEm, 1.5);
  assert.equal(quote2.paddingRightEm, 1.5);

  const listChild = resolveBlockTypography(
    { block_type: 'paragraph', zone: 'body', style: { parent_list_depth: 2 } },
    'zh',
    zhThesis,
  );
  assert.equal(listChild.parentListDepth, 2);
  assert.equal(listChild.textIndentEm, 0);

  // 6-level list bullets & spacing helpers
  assert.equal(LIST_BULLETS.length, 6);
  assert.equal(getListBullet(0), '•');
  assert.equal(getListBullet(1), '◦');
  assert.equal(getListBullet(2), '▪');
  assert.equal(getListBullet(3), '‣');
  assert.equal(getListBullet(4), '–');
  assert.equal(getListBullet(5), '·');
  assert.equal(getListBullet(9), '·');
  assert.ok(getListPaddingPx(3) > getListPaddingPx(2));
  assert.ok(getParentListMarginPx(2) > getListPaddingPx(2));
  assert.notEqual(getParagraphGapClass('compact'), getParagraphGapClass('relaxed'));
});

test('W1-T10: normalizeTypographyPrefs handles v1.1.0 legacy localStorage and clamps invalid values', () => {
  // Legacy v1.1.0 localStorage payload without any typography keys
  const legacy = {
    fontMode: 'serif',
    fontSize: 15.5,
    readWidth: 'standard',
    smartFold: true,
    showFigures: true,
    highlightAiIsms: true,
  };
  const upgraded = normalizeTypographyPrefs(legacy);
  assert.deepEqual(upgraded, DEFAULT_TYPOGRAPHY_PREFS);

  // Valid custom prefs round-trip cleanly
  const persisted = normalizeTypographyPrefs({
    typographyPreset: 'custom',
    indentMode: '2em',
    lineHeight: 2.0,
    paragraphGap: 'relaxed',
    textAlign: 'left',
  });
  assert.deepEqual(persisted, {
    typographyPreset: 'custom',
    indentMode: '2em',
    lineHeight: 2.0,
    paragraphGap: 'relaxed',
    textAlign: 'left',
  });

  // Out-of-range values clamp safely, invalid enum falls back
  const noisy = normalizeTypographyPrefs({
    typographyPreset: 'unknown_preset',
    indentMode: 'bad',
    lineHeight: 9.9,
    paragraphGap: 'huge',
    textAlign: 'weird',
  });
  assert.equal(noisy.typographyPreset, 'auto');
  assert.equal(noisy.indentMode, 'auto');
  assert.equal(noisy.lineHeight, 2.3);
  assert.equal(noisy.paragraphGap, 'normal');
  assert.equal(noisy.textAlign, 'auto');
});
