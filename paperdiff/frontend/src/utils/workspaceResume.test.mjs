import assert from 'node:assert/strict';
import test from 'node:test';
import {
  AUTO_RESUME_KEY,
  LAST_WORKSPACE_KEY,
  loadAutoResumePref,
  loadLastWorkspace,
  resolveResumeTarget,
  saveAutoResumePref,
  saveLastWorkspace,
  shouldAutoResumeOnStartup,
} from './workspaceResume.ts';

function makeMemoryStorage() {
  const map = new Map();
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
  };
}

const sampleProjects = [
  {
    id: 10,
    name: '大模型推理论文',
    project_mode: 'local_folder',
    local_root_path: '/tmp/llm_paper',
    local_status: 'ok',
    documents: [],
  },
  {
    id: 11,
    name: '失联目录项目',
    project_mode: 'local_folder',
    local_root_path: '/tmp/missing',
    local_status: 'missing',
    documents: [],
  },
  {
    id: 12,
    name: '托管项目',
    project_mode: 'managed',
    documents: [{ id: 101, name: '主文稿' }],
  },
];

test('W2-T03: auto-resume defaults to false (D-04 Option A) and round-trips cleanly', () => {
  const store = makeMemoryStorage();
  assert.equal(loadAutoResumePref(store), false);
  saveAutoResumePref(true, store);
  assert.equal(store.getItem(AUTO_RESUME_KEY), 'true');
  assert.equal(loadAutoResumePref(store), true);
  saveAutoResumePref(false, store);
  assert.equal(loadAutoResumePref(store), false);
});

test('W2-T03: resolveResumeTarget handles ready, missing_project, and root_invalid states', () => {
  const store = makeMemoryStorage();
  saveLastWorkspace(
    {
      projectId: 10,
      projectName: '大模型推理论文',
      projectMode: 'local_folder',
      localRootPath: '/tmp/llm_paper',
      localRelPath: 'sections/intro.tex',
      updatedAt: 1700000000000,
    },
    store,
  );
  const loaded = loadLastWorkspace(store);
  assert.ok(loaded && store.getItem(LAST_WORKSPACE_KEY));

  const ready = resolveResumeTarget(loaded, sampleProjects);
  assert.equal(ready.status, 'ready');
  assert.equal(ready.localRelPath, 'sections/intro.tex');

  const invalid = resolveResumeTarget({ ...loaded, projectId: 11 }, sampleProjects);
  assert.equal(invalid.status, 'root_invalid');
  assert.ok(invalid.reason.includes('移动'));

  const gone = resolveResumeTarget({ ...loaded, projectId: 999 }, sampleProjects);
  assert.equal(gone.status, 'missing_project');
});

test('W2-T03: explicit ?project= URL always takes precedence over auto-resume', () => {
  const ready = resolveResumeTarget(
    {
      projectId: 10,
      projectName: '大模型推理论文',
      projectMode: 'local_folder',
      localRelPath: 'v1.md',
      updatedAt: 1,
    },
    sampleProjects,
  );
  assert.equal(
    shouldAutoResumeOnStartup({
      explicitUrlProjectId: 12,
      autoResumeEnabled: true,
      resolution: ready,
    }),
    false,
  );
  assert.equal(
    shouldAutoResumeOnStartup({
      explicitUrlProjectId: null,
      autoResumeEnabled: true,
      resolution: ready,
    }),
    true,
  );
  assert.equal(
    shouldAutoResumeOnStartup({
      explicitUrlProjectId: null,
      autoResumeEnabled: false,
      resolution: ready,
    }),
    false,
  );
});
