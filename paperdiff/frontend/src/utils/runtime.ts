/**
 * @file runtime.ts
 * @description Pure helpers for startup URL context handoff (`?project=&file=`),
 * desktop-to-browser relative path building, and Web shutdown draft protection.
 */

export interface StartupUrlContext {
  projectId: number | null;
  fileRelPath: string | null;
}

export function parseStartupUrlContext(search: string): StartupUrlContext {
  const raw = (search || '').trim();
  if (!raw) return { projectId: null, fileRelPath: null };
  const params = new URLSearchParams(raw.startsWith('?') ? raw.slice(1) : raw);
  const projRaw = params.get('project');
  let projectId: number | null = null;
  if (projRaw && /^\d+$/.test(projRaw.trim())) {
    const parsed = Number(projRaw.trim());
    if (Number.isSafeInteger(parsed) && parsed > 0) {
      projectId = parsed;
    }
  }
  const fileRaw = params.get('file');
  const trimmedFile = fileRaw ? fileRaw.trim() : '';
  const fileRelPath =
    trimmedFile && !trimmedFile.startsWith('/') && !trimmedFile.includes('..')
      ? trimmedFile
      : null;
  return { projectId, fileRelPath };
}

export function buildBrowserHandoffPath(opts: {
  screen: 'home' | 'studio' | 'guide';
  projectId: number | null;
  localRelPath?: string | null;
}): string {
  if (opts.screen !== 'studio' || !opts.projectId || opts.projectId <= 0) {
    return '/';
  }
  const params = new URLSearchParams();
  params.set('project', String(opts.projectId));
  if (opts.localRelPath && opts.localRelPath.trim()) {
    params.set('file', opts.localRelPath.trim());
  }
  return `/?${params.toString()}`;
}

export interface StopGuardDecision {
  requiresDraftConfirm: boolean;
  draftCount: number;
}

export function evaluateStopGuard(draftEditsCount: number): StopGuardDecision {
  const safeCount = Number.isFinite(draftEditsCount) && draftEditsCount > 0 ? Math.floor(draftEditsCount) : 0;
  return {
    requiresDraftConfirm: safeCount > 0,
    draftCount: safeCount,
  };
}
