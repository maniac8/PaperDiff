import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildBrowserHandoffPath,
  evaluateStopGuard,
  parseStartupUrlContext,
} from './runtime.ts';

test('W1-T10: parseStartupUrlContext extracts valid project and decoded relative file', () => {
  assert.deepEqual(parseStartupUrlContext('?project=12&file=sections%2Fintro.tex'), {
    projectId: 12,
    fileRelPath: 'sections/intro.tex',
  });
  assert.deepEqual(parseStartupUrlContext('?project=7'), {
    projectId: 7,
    fileRelPath: null,
  });
  // Rejects invalid project IDs and path traversal attempts
  assert.deepEqual(parseStartupUrlContext('?project=-5&file=..%2Fsecret.tex'), {
    projectId: null,
    fileRelPath: null,
  });
  assert.deepEqual(parseStartupUrlContext('?project=abc&file=%2Fetc%2Fpasswd'), {
    projectId: null,
    fileRelPath: null,
  });
});

test('W1-T10: buildBrowserHandoffPath produces safe relative paths starting with /', () => {
  assert.equal(buildBrowserHandoffPath({ screen: 'home', projectId: 5 }), '/');
  assert.equal(buildBrowserHandoffPath({ screen: 'studio', projectId: null }), '/');
  assert.equal(buildBrowserHandoffPath({ screen: 'studio', projectId: 5 }), '/?project=5');
  assert.equal(
    buildBrowserHandoffPath({ screen: 'studio', projectId: 5, localRelPath: 'sections/intro.tex' }),
    '/?project=5&file=sections%2Fintro.tex',
  );
});

test('W1-T10: evaluateStopGuard requires confirmation iff unsaved draft edits exist', () => {
  assert.deepEqual(evaluateStopGuard(0), { requiresDraftConfirm: false, draftCount: 0 });
  assert.deepEqual(evaluateStopGuard(-1), { requiresDraftConfirm: false, draftCount: 0 });
  assert.deepEqual(evaluateStopGuard(3), { requiresDraftConfirm: true, draftCount: 3 });
});
