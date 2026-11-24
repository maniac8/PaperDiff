/**
 * @file api.ts
 * @description Unified REST API client and native macOS `DesktopBridge` (`window.pywebview.api`)
 * abstraction layer for PaperDiff Studio v1.1.0.
 *
 * Dual-mode delivery:
 * - Inside `PaperDiff.app` (pywebview), file saves and PDF exports invoke native macOS `NSSavePanel`
 *   and `NSPrintOperation` via `window.pywebview.api`.
 * - Inside a standard web browser, downloads gracefully fall back to Blob anchor downloads and
 *   server-side Headless Chrome PDF generation (`/api/export`).
 */

import type {
  AiLexiconConfig,
  ComparisonResult,
  DocType,
  DocumentSummary,
  LocalFolderValidation,
  LocalSaveEditsResult,
  LocalStatResponse,
  LocalTreeResponse,
  Project,
  ProjectCategory,
  ProjectMode,
  ProjectStatus,
  SingleDocPreview,
  TrackedChangesInfo,
  TypedPatchOp,
  TypographyPrefs,
  VersionSummary,
} from './types';

export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    let code: string | undefined;
    try {
      const err = await res.json();
      msg = err.detail || msg;
      code = err.code;
    } catch {
      /* ignore */
    }
    throw new ApiError(msg, res.status, code);
  }
  return res.json();
}

export interface RuntimeHealth {
  status: string;
  app: string;
  version: string;
  pid: number;
  port: number;
  data_dir: string;
  log_path: string;
  launch_mode: string;
  can_shutdown: boolean;
}

export const api = {
  getRuntimeHealth: () => jsonFetch<RuntimeHealth>('/api/health'),

  requestRuntimeShutdown: () =>
    jsonFetch<{ stopping: boolean; pid: number; port: number }>('/api/runtime/shutdown', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-PaperDiff-Client': 'web-ui',
      },
      body: JSON.stringify({}),
    }),

  // Local Folder Validation & Native Picker (W2, D-08)
  validateLocalFolder: (path: string) =>
    jsonFetch<LocalFolderValidation>('/api/local/validate-folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }),

  pickLocalFolder: async (
    initialDir?: string,
  ): Promise<{ picked: boolean; path?: string; cancelled?: boolean; supported?: boolean; detail?: string }> => {
    const desktopApi = getDesktopApi();
    if (desktopApi?.select_local_folder) {
      return desktopApi.select_local_folder(initialDir || '');
    }
    return jsonFetch('/api/local/pick-folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ initial_dir: initialDir || undefined }),
    });
  },

  // Projects
  listProjects: () => jsonFetch<Project[]>('/api/projects'),

  createProject: (payload: {
    name: string;
    description?: string;
    category?: ProjectCategory;
    status?: ProjectStatus;
    primary_format?: string;
    protected_terms?: string[];
    default_doc_name?: string;
    project_mode?: ProjectMode;
    local_root_path?: string;
  }) =>
    jsonFetch<Project>('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  updateProject: (
    projectId: number,
    payload: {
      name?: string;
      description?: string;
      category?: ProjectCategory;
      status?: ProjectStatus;
      pinned?: boolean;
      protected_terms?: string[];
      project_mode?: ProjectMode;
      local_root_path?: string;
    },
  ) =>
    jsonFetch<Project>(`/api/projects/${projectId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  deleteProject: (projectId: number) =>
    jsonFetch<{ deleted: boolean }>(`/api/projects/${projectId}`, { method: 'DELETE' }),

  // Local Folder Workspace APIs (W2)
  getLocalTree: (projectId: number, includeAux = false) =>
    jsonFetch<LocalTreeResponse>(
      `/api/projects/${projectId}/local/tree?include_aux=${includeAux ? 'true' : 'false'}`,
    ),

  getLocalStat: (projectId: number, relPaths: string[]) => {
    const qs = relPaths.map((p) => `rel_path=${encodeURIComponent(p)}`).join('&');
    return jsonFetch<LocalStatResponse>(`/api/projects/${projectId}/local/stat${qs ? `?${qs}` : ''}`);
  },

  previewLocalFile: (projectId: number, relPath: string) =>
    jsonFetch<SingleDocPreview>(`/api/projects/${projectId}/local/preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rel_path: relPath }),
    }),

  fetchLocalRawBlob: async (projectId: number, relPath: string): Promise<ArrayBuffer> => {
    const res = await fetch(
      `/api/projects/${projectId}/local/raw?rel_path=${encodeURIComponent(relPath)}`,
    );
    if (!res.ok) throw new ApiError(`加载本地原文档失败 (HTTP ${res.status})`, res.status);
    return res.arrayBuffer();
  },

  compareLocalFiles: (
    projectId: number,
    payload: {
      old_rel_path?: string;
      new_rel_path?: string;
      rel_path?: string;
      docx_tracked_split?: boolean;
    },
  ) =>
    jsonFetch<ComparisonResult>(`/api/projects/${projectId}/local/compare`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  saveLocalPairState: (
    projectId: number,
    payload: {
      old_rel_path: string;
      new_rel_path: string;
      acked_ids?: string[];
      decisions?: Record<string, string>;
    },
  ) =>
    jsonFetch<{ acked_ids: string[]; decisions: Record<string, string> }>(
      `/api/projects/${projectId}/local/pair-state`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      },
    ),

  saveLocalEdits: (
    projectId: number,
    payload: {
      rel_path: string;
      patches?: TypedPatchOp[];
      paragraph_edits?: Record<number, string>;
      mode: 'save_as' | 'overwrite';
      target_rel_path?: string;
      expected_sha256?: string;
      force?: boolean;
      docx_mode?: 'clean' | 'tracked';
    },
  ) =>
    jsonFetch<LocalSaveEditsResult>(`/api/projects/${projectId}/local/save-edits`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  // Documents
  createDocument: (
    projectId: number,
    payload: { name: string; doc_type?: DocType; primary_format?: string; notes?: string },
  ) =>
    jsonFetch<DocumentSummary>(`/api/projects/${projectId}/documents`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  updateDocument: (
    documentId: number,
    payload: { name?: string; doc_type?: DocType; primary_format?: string; notes?: string },
  ) =>
    jsonFetch<DocumentSummary>(`/api/documents/${documentId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  deleteDocument: (documentId: number) =>
    jsonFetch<{ deleted: boolean }>(`/api/documents/${documentId}`, { method: 'DELETE' }),

  // Versions (Document-Scoped)
  listDocVersions: (documentId: number) =>
    jsonFetch<VersionSummary[]>(`/api/documents/${documentId}/versions`),

  createDocVersionText: (
    documentId: number,
    payload: {
      label: string;
      source_tag: string;
      filename: string;
      format?: string;
      content: string;
      notes?: string;
      is_milestone?: boolean;
    },
  ) =>
    jsonFetch<VersionSummary>(`/api/documents/${documentId}/versions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  uploadDocVersionFile: (
    documentId: number,
    file: File,
    label: string,
    sourceTag: string,
    notes: string,
    isMilestone = false,
  ) => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('label', label);
    fd.append('source_tag', sourceTag);
    fd.append('notes', notes);
    fd.append('is_milestone', isMilestone ? 'true' : 'false');
    return jsonFetch<VersionSummary>(`/api/documents/${documentId}/versions/upload`, {
      method: 'POST',
      body: fd,
    });
  },

  inspectDocxTrackedChanges: (documentId: number, file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return jsonFetch<TrackedChangesInfo>(`/api/documents/${documentId}/versions/inspect-docx`, {
      method: 'POST',
      body: fd,
    });
  },

  importTrackedDocxSplit: (
    documentId: number,
    file: File,
    labelPrefix = '',
    notes = '',
  ) => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('label_prefix', labelPrefix);
    fd.append('notes', notes);
    return jsonFetch<{
      before_version: VersionSummary;
      after_version: VersionSummary;
      tracked_changes_info: TrackedChangesInfo;
    }>(`/api/documents/${documentId}/versions/import-tracked-docx`, {
      method: 'POST',
      body: fd,
    });
  },

  applyTypedPatches: (
    documentId: number,
    payload: {
      base_version_id: number;
      patches: TypedPatchOp[];
      label: string;
      source_tag: string;
      notes: string;
      is_milestone: boolean;
      docx_mode?: 'clean' | 'tracked';
    },
  ) =>
    jsonFetch<{ version: VersionSummary; applied_count: number; warnings: string[] }>(
      `/api/documents/${documentId}/apply-patches`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      },
    ),

  fetchVersionSourceBlob: async (versionId: number): Promise<ArrayBuffer> => {
    const res = await fetch(`/api/versions/${versionId}/source-blob`);
    if (!res.ok) throw new Error(`加载原文档失败 (HTTP ${res.status})`);
    return res.arrayBuffer();
  },

  updateVersion: (
    versionId: number,
    payload: { label?: string; source_tag?: string; notes?: string; is_milestone?: boolean },
  ) =>
    jsonFetch<VersionSummary>(`/api/versions/${versionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  deleteVersion: (versionId: number) =>
    jsonFetch<{ deleted: boolean }>(`/api/versions/${versionId}`, { method: 'DELETE' }),

  parseUploadFile: (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return jsonFetch<{
      filename: string;
      format: string;
      content: string;
      meta?: Record<string, unknown>;
    }>('/api/parse-upload', {
      method: 'POST',
      body: fd,
    });
  },

  // Single-Document Reading Preview & Self-Audit (v1.4.5)
  previewVersion: (versionId: number) =>
    jsonFetch<SingleDocPreview>(`/api/versions/${versionId}/preview`),

  quickPreview: (payload: {
    content: string;
    format?: string;
    label?: string;
    filename?: string;
    meta?: Record<string, unknown>;
    protected_terms?: string[];
  }) =>
    jsonFetch<SingleDocPreview>('/api/preview/quick', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  saveSingleAsVersion: (
    documentId: number,
    payload: {
      base_version_id: number;
      paragraph_edits: Record<number, string>;
      label: string;
      source_tag: string;
      notes: string;
      is_milestone: boolean;
    },
  ) =>
    jsonFetch<VersionSummary>(`/api/documents/${documentId}/save-single-version`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  // Compare & Fix-Save Loop
  compareDocVersions: (documentId: number, oldId: number, newId: number) =>
    jsonFetch<ComparisonResult>(
      `/api/documents/${documentId}/compare?old_id=${oldId}&new_id=${newId}`,
    ),

  quickCompare: (payload: {
    old_content: string;
    new_content: string;
    old_label?: string;
    new_label?: string;
    old_meta?: Record<string, unknown>;
    new_meta?: Record<string, unknown>;
    protected_terms?: string[];
  }) =>
    jsonFetch<ComparisonResult>('/api/compare/quick', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  saveDocMergeDecisions: (
    documentId: number,
    oldVersionId: number,
    newVersionId: number,
    decisions: Record<string, string>,
  ) =>
    jsonFetch<{ decisions: Record<string, string> }>(
      `/api/documents/${documentId}/merge-decisions`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          old_version_id: oldVersionId,
          new_version_id: newVersionId,
          decisions,
        }),
      },
    ),

  saveMergedAsVersion: (
    documentId: number,
    payload: {
      old_version_id: number;
      new_version_id: number;
      decisions: Record<string, string>;
      paragraph_edits: Record<number, string>;
      label: string;
      source_tag: string;
      notes: string;
      is_milestone: boolean;
    },
  ) =>
    jsonFetch<VersionSummary>(`/api/documents/${documentId}/save-merged-version`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  // Settings & Alert Acknowledgements (v1.3)
  getAiLexicon: () => jsonFetch<AiLexiconConfig>('/api/settings/ai-lexicon'),

  saveAiLexicon: (payload: { added_en: string[]; added_zh: string[]; muted: string[] }) =>
    jsonFetch<AiLexiconConfig>('/api/settings/ai-lexicon', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  saveAlertAcks: (
    documentId: number,
    oldVersionId: number,
    newVersionId: number,
    ackedIds: string[],
  ) =>
    jsonFetch<{ acked_ids: string[] }>(`/api/documents/${documentId}/ack-alerts`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        old_version_id: oldVersionId,
        new_version_id: newVersionId,
        acked_ids: ackedIds,
      }),
    }),

  exportContent: async (payload: {
    old_version_id?: number;
    new_version_id?: number;
    old_content?: string;
    new_content?: string;
    version_id?: number;
    single_content?: string;
    single_meta?: Record<string, unknown>;
    single_label?: string;
    old_label?: string;
    new_label?: string;
    project_name?: string;
    export_type:
      | 'merged'
      | 'html'
      | 'single_html'
      | 'single_source'
      | 'latexdiff'
      | 'markdown'
      | 'print_html_diff'
      | 'print_html_diff_compact'
      | 'print_html_single';
    view_mode?: 'split' | 'inline';
    decisions?: Record<string, string>;
    paragraph_edits?: Record<number, string>;
    patches?: TypedPatchOp[];
    protected_terms?: string[];
    commentary_note?: string;
    landscape?: boolean;
    typography_prefs?: TypographyPrefs;
    local_project_id?: number;
    local_rel_path?: string;
    local_old_rel_path?: string;
    local_new_rel_path?: string;
  }): Promise<string> => {
    const res = await fetch('/api/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`导出失败 (HTTP ${res.status})`);
    return res.text();
  },

  exportBinary: async (payload: {
    old_version_id?: number;
    new_version_id?: number;
    old_content?: string;
    new_content?: string;
    version_id?: number;
    single_content?: string;
    single_meta?: Record<string, unknown>;
    single_label?: string;
    old_label?: string;
    new_label?: string;
    project_name?: string;
    export_type:
      | 'docx_tracked'
      | 'docx_merged'
      | 'docx_patched'
      | 'docx_tracked_preserved'
      | 'latex_zip_patched'
      | 'pdf_diff_report'
      | 'pdf_diff_compact'
      | 'pdf_single';
    decisions?: Record<string, string>;
    paragraph_edits?: Record<number, string>;
    patches?: TypedPatchOp[];
    protected_terms?: string[];
    commentary_note?: string;
    landscape?: boolean;
    docx_mode?: 'clean' | 'tracked';
    typography_prefs?: TypographyPrefs;
    local_project_id?: number;
    local_rel_path?: string;
    local_old_rel_path?: string;
    local_new_rel_path?: string;
  }): Promise<Blob> => {
    const res = await fetch('/api/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      let msg = `导出失败 (HTTP ${res.status})`;
      try {
        const j = await res.json();
        if (j?.detail) msg = j.detail;
      } catch {
        /* ignore */
      }
      throw new Error(msg);
    }
    return res.blob();
  },
};

export interface CliInstallStatus {
  installed: boolean;
  script_path: string;
  bin_dir?: string;
  in_path?: boolean;
  path_hint?: string;
  removed?: boolean;
  error?: string;
}

interface PyWebViewDesktopApi {
  save_file_base64?: (filename: string, base64Data: string) => Promise<{ saved: boolean; path?: string }>;
  export_pdf_from_html?: (
    filename: string,
    htmlContent: string,
    landscape?: boolean,
  ) => Promise<{ saved: boolean; cancelled?: boolean; path?: string; error?: string; engine?: string }>;
  select_local_folder?: (
    initialDir?: string,
  ) => Promise<{ picked: boolean; path?: string; cancelled?: boolean; supported?: boolean }>;
  open_in_browser?: (
    relativeUrl?: string,
  ) => Promise<{ opened: boolean; url?: string; error?: string }>;
  open_logs_dir?: () => Promise<boolean>;
  get_cli_install_status?: () => Promise<CliInstallStatus>;
  install_cli_command?: () => Promise<CliInstallStatus>;
  uninstall_cli_command?: () => Promise<CliInstallStatus>;
}

export function getDesktopApi(): PyWebViewDesktopApi | null {
  const w = window as unknown as { pywebview?: { api?: PyWebViewDesktopApi } };
  return w.pywebview?.api ?? null;
}

export async function exportPrintableHtmlAsPdf(
  htmlContent: string,
  filename: string,
  landscape = false,
  fallbackBinaryFetcher?: () => Promise<Blob>,
): Promise<{ saved: boolean; cancelled?: boolean; method: string }> {
  const desktopApi = getDesktopApi();
  if (desktopApi?.export_pdf_from_html) {
    const res = await desktopApi.export_pdf_from_html(filename, htmlContent, landscape);
    if (res?.saved) return { saved: true, method: res.engine || 'desktop_wkwebview' };
    if (res?.cancelled) return { saved: false, cancelled: true, method: 'cancelled' };
  }
  if (fallbackBinaryFetcher) {
    try {
      const pdfBlob = await fallbackBinaryFetcher();
      triggerBlobDownload(pdfBlob, filename);
      return { saved: true, method: 'backend_chromium' };
    } catch {
      // Fall through to clean browser print popup
    }
  }
  // Universal browser fallback: open printable HTML in a clean print tab
  const win = window.open('', '_blank', 'width=1024,height=780');
  if (win) {
    win.document.open();
    win.document.write(htmlContent);
    win.document.close();
    setTimeout(() => {
      try {
        win.focus();
        win.print();
      } catch {
        /* ignore */
      }
    }, 600);
    return { saved: true, method: 'browser_print' };
  }
  triggerFileDownload(htmlContent, filename.replace(/\.pdf$/i, '.html'), 'text/html;charset=utf-8');
  return { saved: true, method: 'html_download' };
}

export function triggerFileDownload(
  content: string,
  filename: string,
  mime = 'text/plain;charset=utf-8',
) {
  const blob = new Blob([content], { type: mime });
  triggerBlobDownload(blob, filename);
}

export function triggerBlobDownload(blob: Blob, filename: string) {
  const desktopApi = getDesktopApi();
  if (desktopApi?.save_file_base64) {
    const reader = new FileReader();
    reader.onloadend = () => {
      const dataUrl = typeof reader.result === 'string' ? reader.result : '';
      const comma = dataUrl.indexOf(',');
      const b64 = comma >= 0 ? dataUrl.slice(comma + 1) : '';
      if (b64) {
        desktopApi.save_file_base64?.(filename, b64).catch(() => {});
      }
    };
    reader.readAsDataURL(blob);
    return;
  }

  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
