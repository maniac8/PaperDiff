/**
 * @file workspaceResume.ts
 * @description Pure helpers for W2 Last Workspace Resume (AC-12 / D-04 Option A):
 * persists the most recently opened project/document/local file, enforces default-OFF
 * auto-resume preference, prioritizes explicit `?project=` URL handoff, and gracefully
 * detects deleted projects or moved/unreadable local folders.
 */

import type { Project, ProjectMode } from '../types';

export const LAST_WORKSPACE_KEY = 'paperdiff_last_workspace';
export const AUTO_RESUME_KEY = 'paperdiff_auto_resume';

export interface LastWorkspaceRecord {
  projectId: number;
  projectName: string;
  projectMode: ProjectMode;
  localRootPath?: string | null;
  localRelPath?: string | null;
  documentId?: number | null;
  documentName?: string | null;
  updatedAt: number;
}

export type ResumeResolution =
  | { status: 'none' }
  | { status: 'missing_project' }
  | {
      status: 'root_invalid';
      project: Project;
      record: LastWorkspaceRecord;
      reason: string;
    }
  | {
      status: 'ready';
      project: Project;
      record: LastWorkspaceRecord;
      localRelPath: string | null;
      documentId: number | null;
    };

export function parseLastWorkspaceRecord(raw: string | null | undefined): LastWorkspaceRecord | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<LastWorkspaceRecord>;
    if (!parsed || typeof parsed !== 'object') return null;
    const pid = Number(parsed.projectId);
    if (!Number.isSafeInteger(pid) || pid <= 0) return null;
    const mode: ProjectMode = parsed.projectMode === 'local_folder' ? 'local_folder' : 'managed';
    return {
      projectId: pid,
      projectName: String(parsed.projectName || '未命名项目'),
      projectMode: mode,
      localRootPath: parsed.localRootPath ? String(parsed.localRootPath) : null,
      localRelPath: parsed.localRelPath ? String(parsed.localRelPath) : null,
      documentId:
        parsed.documentId != null && Number.isSafeInteger(Number(parsed.documentId)) && Number(parsed.documentId) > 0
          ? Number(parsed.documentId)
          : null,
      documentName: parsed.documentName ? String(parsed.documentName) : null,
      updatedAt: Number.isFinite(Number(parsed.updatedAt)) ? Number(parsed.updatedAt) : Date.now(),
    };
  } catch {
    return null;
  }
}

export function loadLastWorkspace(storage?: Pick<Storage, 'getItem'> | null): LastWorkspaceRecord | null {
  const store = storage ?? (typeof window !== 'undefined' ? window.localStorage : null);
  if (!store) return null;
  try {
    return parseLastWorkspaceRecord(store.getItem(LAST_WORKSPACE_KEY));
  } catch {
    return null;
  }
}

export function saveLastWorkspace(
  record: LastWorkspaceRecord,
  storage?: Pick<Storage, 'setItem'> | null,
): void {
  const store = storage ?? (typeof window !== 'undefined' ? window.localStorage : null);
  if (!store) return;
  try {
    store.setItem(LAST_WORKSPACE_KEY, JSON.stringify(record));
  } catch {
    /* ignore storage quota errors */
  }
}

export function clearLastWorkspace(storage?: Pick<Storage, 'removeItem'> | null): void {
  const store = storage ?? (typeof window !== 'undefined' ? window.localStorage : null);
  if (!store) return;
  try {
    store.removeItem(LAST_WORKSPACE_KEY);
  } catch {
    /* ignore */
  }
}

export function loadAutoResumePref(storage?: Pick<Storage, 'getItem'> | null): boolean {
  const store = storage ?? (typeof window !== 'undefined' ? window.localStorage : null);
  if (!store) return false;
  try {
    return store.getItem(AUTO_RESUME_KEY) === 'true';
  } catch {
    return false;
  }
}

export function saveAutoResumePref(
  enabled: boolean,
  storage?: Pick<Storage, 'setItem'> | null,
): void {
  const store = storage ?? (typeof window !== 'undefined' ? window.localStorage : null);
  if (!store) return;
  try {
    store.setItem(AUTO_RESUME_KEY, enabled ? 'true' : 'false');
  } catch {
    /* ignore */
  }
}

export function resolveResumeTarget(
  record: LastWorkspaceRecord | null,
  projects: Project[],
): ResumeResolution {
  if (!record) return { status: 'none' };
  const proj = projects.find((p) => p.id === record.projectId);
  if (!proj) return { status: 'missing_project' };

  if (proj.project_mode === 'local_folder') {
    if (proj.local_status && proj.local_status !== 'ok') {
      const reason =
        proj.local_status === 'missing'
          ? '原绑定目录已移动或不存在'
          : proj.local_status === 'unreadable'
            ? '原绑定目录当前无读取权限'
            : '原绑定目录状态异常';
      return { status: 'root_invalid', project: proj, record, reason };
    }
    return {
      status: 'ready',
      project: proj,
      record,
      localRelPath: record.localRelPath || null,
      documentId: null,
    };
  }

  const targetDoc =
    (record.documentId ? proj.documents.find((d) => d.id === record.documentId) : undefined) ||
    proj.documents[0] ||
    null;
  if (!targetDoc) return { status: 'missing_project' };
  return {
    status: 'ready',
    project: proj,
    record,
    localRelPath: null,
    documentId: targetDoc.id,
  };
}

export function shouldAutoResumeOnStartup(opts: {
  explicitUrlProjectId: number | null;
  autoResumeEnabled: boolean;
  resolution: ResumeResolution;
}): boolean {
  if (opts.explicitUrlProjectId != null && opts.explicitUrlProjectId > 0) {
    return false;
  }
  return opts.autoResumeEnabled && opts.resolution.status === 'ready';
}
