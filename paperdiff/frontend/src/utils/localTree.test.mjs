/**
 * @file localTree.test.mjs
 * @description Node built-in `node --test` unit suite for W2-T11 (local folder tree search/filter,
 * D-04 strict 2-file pairwise cap with 3rd-file intercept, and revised path suggestion).
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import {
  filterLocalTree,
  flattenLocalDocs,
  replacePairSlot,
  suggestRevisedRelPath,
  togglePairSelection,
} from './localTree.ts';

const SAMPLE_TREE = [
  {
    name: 'sections',
    rel_path: 'sections',
    node_type: 'dir',
    children: [
      { name: 'intro.tex', rel_path: 'sections/intro.tex', node_type: 'file', kind: 'doc', format: 'latex', ext: '.tex' },
      { name: 'notes.md', rel_path: 'sections/notes.md', node_type: 'file', kind: 'doc', format: 'markdown', ext: '.md' },
    ],
  },
  { name: 'draft_v1.docx', rel_path: 'draft_v1.docx', node_type: 'file', kind: 'doc', format: 'docx', ext: '.docx' },
  { name: 'refs.bib', rel_path: 'refs.bib', node_type: 'file', kind: 'aux', format: 'bib', ext: '.bib' },
];

test('W2-T11: flattenLocalDocs extracts only primary doc files in deterministic order', () => {
  const docs = flattenLocalDocs(SAMPLE_TREE);
  assert.deepEqual(
    docs.map((d) => d.rel_path),
    ['sections/intro.tex', 'sections/notes.md', 'draft_v1.docx'],
  );
});

test('W2-T11: filterLocalTree searches by filename, filters by format, and reports ancestor dirs to auto-expand', () => {
  const byQuery = filterLocalTree(SAMPLE_TREE, 'intro', 'all');
  assert.equal(byQuery.nodes.length, 1);
  assert.equal(byQuery.nodes[0].rel_path, 'sections');
  assert.equal(byQuery.nodes[0].children.length, 1);
  assert.equal(byQuery.nodes[0].children[0].rel_path, 'sections/intro.tex');
  assert.deepEqual(byQuery.autoExpandDirs, ['sections']);

  const byFormat = filterLocalTree(SAMPLE_TREE, '', 'docx');
  assert.deepEqual(
    byFormat.nodes.map((n) => n.rel_path),
    ['draft_v1.docx'],
  );
});

test('W2-T11: togglePairSelection enforces D-04 strict 2-file cap and intercepts 3rd file cleanly', () => {
  const s1 = togglePairSelection([], 'a.tex');
  assert.deepEqual(s1.nextPair, ['a.tex']);
  assert.equal(s1.pendingThirdRelPath, null);

  const s2 = togglePairSelection(s1.nextPair, 'b.tex');
  assert.deepEqual(s2.nextPair, ['a.tex', 'b.tex']);
  assert.equal(s2.pendingThirdRelPath, null);

  // Clicking a 3rd file MUST NOT add a 3rd item or drop existing pair!
  const s3 = togglePairSelection(s2.nextPair, 'c.tex');
  assert.deepEqual(s3.nextPair, ['a.tex', 'b.tex']);
  assert.equal(s3.nextPair.length, 2);
  assert.equal(s3.pendingThirdRelPath, 'c.tex');

  // Unchecking an already selected file removes it cleanly
  const uncheck = togglePairSelection(s2.nextPair, 'a.tex');
  assert.deepEqual(uncheck.nextPair, ['b.tex']);
  assert.equal(uncheck.pendingThirdRelPath, null);

  // Explicit slot replacement
  assert.deepEqual(replacePairSlot(['a.tex', 'b.tex'], 0, 'c.tex'), ['c.tex', 'b.tex']);
  assert.deepEqual(replacePairSlot(['a.tex', 'b.tex'], 1, 'c.tex'), ['a.tex', 'c.tex']);
});

test('W2-T11: suggestRevisedRelPath appends _revised before extension preserving subdirectories', () => {
  assert.equal(suggestRevisedRelPath('draft.tex'), 'draft_revised.tex');
  assert.equal(suggestRevisedRelPath('chapters/ch1.docx'), 'chapters/ch1_revised.docx');
  assert.equal(suggestRevisedRelPath('README'), 'README_revised');
});
