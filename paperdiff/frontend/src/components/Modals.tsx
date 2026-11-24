/**
 * @file Modals.tsx
 * @description Modal dialogs for PaperDiff Studio v1.1.0, including New Project, New Document,
 * Version Upload (with automatic `.docx` Track Changes pre-inspection and one-click before/after
 * split import), Quick Open/Compare, AI Lexicon Editor, and 3-template Offline PDF Export Modal.
 */

import React, { useEffect, useState } from 'react';
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  FileDown,
  FileUp,
  FolderOpen,
  GitCompareArrows,
  Plus,
  RefreshCw,
  Save,
  ShieldCheck,
  Star,
  Trash2,
  Unlink,
  X,
  Zap,
} from 'lucide-react';
import { ApiError, api } from '../api';
import type {
  AiLexiconConfig,
  DocType,
  LocalFolderValidation,
  LocalSaveEditsResult,
  Project,
  ProjectCategory,
  ProjectMode,
  ProjectStatus,
  TrackedChangesInfo,
  TypedPatchOp,
  VersionSummary,
} from '../types';
import { suggestRevisedRelPath } from '../utils/localTree';

const SOURCE_TAGS = ['AI润色', '去AI味', 'AI初稿', '人工修复', '手改', '导师批注', '返修'];

/* ---------------- New Project Modal (Dual Mode: Managed Upload | Local Folder Binding) ---------------- */
export const NewProjectModal: React.FC<{
  open: boolean;
  onClose: () => void;
  onCreated: (projectId: number, defaultDocId: number | null, projectMode?: ProjectMode) => void;
  onOpenGuide?: () => void;
}> = ({ open, onClose, onCreated, onOpenGuide }) => {
  const [projectMode, setProjectMode] = useState<ProjectMode>('managed');
  const [localPath, setLocalPath] = useState('');
  const [folderVal, setFolderVal] = useState<LocalFolderValidation | null>(null);
  const [picking, setPicking] = useState(false);
  const [name, setName] = useState('');
  const [category, setCategory] = useState<ProjectCategory>('paper');
  const [status, setStatus] = useState<ProjectStatus>('polishing');
  const [fmt, setFmt] = useState('latex');
  const [defaultDoc, setDefaultDoc] = useState('');
  const [desc, setDesc] = useState('');
  const [terms, setTerms] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  if (!open) return null;

  const placeholderDoc =
    category === 'paper'
      ? '主论文正文'
      : category === 'grant'
        ? '基金申请书正文'
        : category === 'report'
          ? '结题总报告'
          : '主文稿';

  const runValidateFolder = async (candidatePath: string) => {
    const trimmed = candidatePath.trim();
    if (!trimmed) {
      setFolderVal({ valid: false, detail: '请输入或选择本地论文目录路径' });
      return null;
    }
    try {
      const res = await api.validateLocalFolder(trimmed);
      setFolderVal(res);
      if (res.valid && res.resolved_path) {
        setLocalPath(res.resolved_path);
        if (!name.trim()) {
          const segs = res.resolved_path.replace(/\/+$/, '').split('/');
          const base = segs[segs.length - 1];
          if (base) setName(base);
        }
      }
      return res;
    } catch (e: unknown) {
      const fallback: LocalFolderValidation = {
        valid: false,
        detail: e instanceof Error ? e.message : '路径校验失败',
      };
      setFolderVal(fallback);
      return fallback;
    }
  };

  const handlePickFolder = async () => {
    setPicking(true);
    setErr('');
    try {
      const res = await api.pickLocalFolder(localPath || undefined);
      if (res.picked && res.path) {
        setLocalPath(res.path);
        await runValidateFolder(res.path);
      } else if (res.supported === false) {
        setErr(res.detail || '当前环境请直接粘贴本地文件夹绝对路径');
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : '无法打开文件夹选择器，请手动粘贴路径');
    } finally {
      setPicking(false);
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return setErr('请输入项目名称');
    if (projectMode === 'local_folder') {
      if (!localPath.trim()) return setErr('请先选择或输入本地文件夹路径');
      const v = await runValidateFolder(localPath);
      if (!v?.valid) return setErr(v?.detail || '本地目录路径无效或不可读');
    }
    setBusy(true);
    setErr('');
    try {
      const termList = terms
        .split(/[,，\n]+/)
        .map((s) => s.trim())
        .filter(Boolean);
      const proj = await api.createProject({
        name: name.trim(),
        description: desc.trim(),
        category,
        status,
        primary_format: fmt,
        protected_terms: termList,
        default_doc_name: projectMode === 'managed' ? defaultDoc.trim() || undefined : undefined,
        project_mode: projectMode,
        local_root_path: projectMode === 'local_folder' ? localPath.trim() : undefined,
      });
      setName('');
      setDesc('');
      setTerms('');
      setDefaultDoc('');
      setLocalPath('');
      setFolderVal(null);
      setProjectMode('managed');
      onCreated(proj.id, proj.documents[0]?.id ?? null, proj.project_mode || projectMode);
      onClose();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : '创建失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell title="新建项目" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        {/* Dual Project Mode Switcher (Managed Upload vs Local Folder Binding) */}
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1.5">文件管理方式</label>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <button
              type="button"
              data-new-proj-mode="managed"
              onClick={() => setProjectMode('managed')}
              className={`rounded-xl border p-2.5 text-left transition-all ${
                projectMode === 'managed'
                  ? 'border-blue-600 bg-blue-50/70 text-blue-900 ring-1 ring-blue-500/30'
                  : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
              }`}
            >
              <div className="font-bold">上传管理</div>
              <div className="mt-0.5 text-[10.5px] opacity-80">手动上传文件并保存历史版本</div>
            </button>
            <button
              type="button"
              data-new-proj-mode="local_folder"
              onClick={() => setProjectMode('local_folder')}
              className={`rounded-xl border p-2.5 text-left transition-all ${
                projectMode === 'local_folder'
                  ? 'border-teal-600 bg-teal-50/70 text-teal-900 ring-1 ring-teal-500/30'
                  : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
              }`}
            >
              <div className="flex items-center gap-1 font-bold">
                <FolderOpen className="h-3.5 w-3.5" />
                绑定本地文件夹
              </div>
              <div className="mt-0.5 text-[10.5px] opacity-80">直接打开本机目录，任选两份对比</div>
            </button>
          </div>
        </div>

        {projectMode === 'local_folder' && (
          <div className="rounded-xl border border-teal-200/80 bg-teal-50/35 p-3 space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-teal-900">绑定本地目录路径 *</label>
              <button
                type="button"
                data-local-pick-btn="true"
                disabled={picking}
                onClick={handlePickFolder}
                className="inline-flex items-center gap-1 rounded-lg bg-teal-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-teal-700 disabled:opacity-50"
              >
                <FolderOpen className="h-3 w-3" />
                {picking ? '等待选择...' : '选择文件夹'}
              </button>
            </div>
            <div className="flex gap-1.5">
              <input
                data-local-folder-input="true"
                value={localPath}
                onChange={(e) => {
                  setLocalPath(e.target.value);
                  setFolderVal(null);
                }}
                placeholder="例如：/Users/yourname/Papers/NeurIPS_2026_Draft"
                className="flex-1 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 font-mono text-xs focus:border-teal-500 focus:outline-none"
              />
              <button
                type="button"
                data-local-validate-btn="true"
                onClick={() => runValidateFolder(localPath)}
                className="rounded-lg border border-teal-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-teal-700 hover:bg-teal-50 shrink-0"
              >
                校验路径
              </button>
            </div>
            {folderVal && (
              <div
                data-local-folder-validation={folderVal.valid ? 'valid' : 'invalid'}
                className={`flex items-center gap-1.5 text-[11px] ${
                  folderVal.valid ? 'text-emerald-700' : 'text-rose-600'
                }`}
              >
                {folderVal.valid ? (
                  <>
                    <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                    <span>
                      路径有效 · 已识别 <strong>{folderVal.doc_count ?? 0}</strong> 个受支持文稿（浏览全程不改动原文件）
                    </span>
                  </>
                ) : (
                  <>
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                    <span>{folderVal.detail || '目录不可用'}</span>
                  </>
                )}
              </div>
            )}
          </div>
        )}

        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1.5">项目类型</label>
          <div className="grid grid-cols-4 gap-1.5 text-xs">
            {(
              [
                ['paper', '学术论文', 'latex'],
                ['grant', '基金申报', 'docx'],
                ['report', '结题报告', 'docx'],
                ['other', '其他文稿', 'markdown'],
              ] as [ProjectCategory, string, string][]
            ).map(([k, label, recFmt]) => (
              <button
                key={k}
                type="button"
                onClick={() => {
                  setCategory(k);
                  setFmt(recFmt);
                }}
                className={`rounded-lg border py-1.5 font-semibold transition-colors ${
                  category === k
                    ? 'border-blue-600 bg-blue-600 text-white'
                    : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">项目名称 *</label>
          <input
            data-new-proj-name="true"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="例如：多模态临床诊断论文 / 2026 国家自然科学基金"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            autoFocus
          />
        </div>

        {projectMode === 'managed' && (
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                首篇文档名（可选）
              </label>
              <input
                value={defaultDoc}
                onChange={(e) => setDefaultDoc(e.target.value)}
                placeholder={`默认：${placeholderDoc}`}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">默认格式 / 状态</label>
              <div className="flex gap-1.5">
                <select
                  value={fmt}
                  onChange={(e) => setFmt(e.target.value)}
                  className="flex-1 rounded-lg border border-slate-300 px-2 py-2 text-xs bg-white"
                >
                  <option value="latex">LaTeX</option>
                  <option value="docx">Word</option>
                  <option value="markdown">Markdown</option>
                </select>
                <select
                  value={status}
                  onChange={(e) => setStatus(e.target.value as ProjectStatus)}
                  className="flex-1 rounded-lg border border-slate-300 px-2 py-2 text-xs bg-white"
                >
                  <option value="drafting">撰写中</option>
                  <option value="polishing">润色中</option>
                  <option value="revising">返修中</option>
                  <option value="done">已定稿</option>
                </select>
              </div>
            </div>
          </div>
        )}

        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">备注（可选）</label>
          <input
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            placeholder="目标期刊、资助类别或截稿日期"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs focus:border-blue-500 focus:outline-none"
          />
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">
            受保护术语（可选，逗号或换行分隔）
          </label>
          <textarea
            rows={2}
            value={terms}
            onChange={(e) => setTerms(e.target.value)}
            placeholder="例如：Transformer, AUC, p-value, 核心模型名"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs focus:border-blue-500 focus:outline-none"
          />
        </div>

        {err && <p className="text-xs text-rose-600">{err}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            取消
          </button>
          <button
            type="submit"
            disabled={busy}
            className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {busy ? '创建中...' : '创建项目'}
          </button>
        </div>
      </form>
    </ModalShell>
  );
};

/* ---------------- New Document Modal ---------------- */
export const NewDocumentModal: React.FC<{
  open: boolean;
  projectId: number;
  projectName: string;
  onClose: () => void;
  onCreated: (documentId: number) => void;
}> = ({ open, projectId, projectName, onClose, onCreated }) => {
  const [name, setName] = useState('');
  const [docType, setDocType] = useState<DocType>('si');
  const [fmt, setFmt] = useState('latex');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  if (!open) return null;

  const presets: [DocType, string][] = [
    ['manuscript', '主论文正文'],
    ['si', '补充材料 (SI)'],
    ['rebuttal', '审稿回复 (Response)'],
    ['proposal', '立项依据 / 专项章节'],
    ['report', '子课题结题报告'],
    ['other', '其他文档'],
  ];

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return setErr('请输入文档名称');
    setBusy(true);
    setErr('');
    try {
      const doc = await api.createDocument(projectId, {
        name: name.trim(),
        doc_type: docType,
        primary_format: fmt,
        notes: notes.trim(),
      });
      setName('');
      setNotes('');
      onCreated(doc.id);
      onClose();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : '创建文档失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell title={`在「${projectName}」下添加文档`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1.5">文档类型（点选自动填充）</label>
          <div className="flex flex-wrap gap-1.5">
            {presets.map(([k, label]) => (
              <button
                key={k}
                type="button"
                onClick={() => {
                  setDocType(k);
                  if (!name.trim()) setName(label);
                }}
                className={`rounded-full px-3 py-1 text-xs font-medium border transition-colors ${
                  docType === k
                    ? 'border-blue-600 bg-blue-600 text-white'
                    : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div className="col-span-2">
            <label className="block text-xs font-semibold text-slate-700 mb-1">文档名称 *</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：Supporting Information / 审稿回复"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs focus:border-blue-500 focus:outline-none"
              autoFocus
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">格式</label>
            <select
              value={fmt}
              onChange={(e) => setFmt(e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-2.5 py-2 text-xs bg-white"
            >
              <option value="latex">LaTeX</option>
              <option value="docx">Word</option>
              <option value="markdown">Markdown</option>
            </select>
          </div>
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">备注（可选）</label>
          <input
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="例如：一审大修附带补充图说明"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs focus:border-blue-500 focus:outline-none"
          />
        </div>

        {err && <p className="text-xs text-rose-600">{err}</p>}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            取消
          </button>
          <button
            type="submit"
            disabled={busy}
            className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {busy ? '创建中...' : '添加文档'}
          </button>
        </div>
      </form>
    </ModalShell>
  );
};

/* ---------------- Upload Version Modal (Document-Scoped) ---------------- */
export const UploadVersionModal: React.FC<{
  open: boolean;
  documentId: number;
  documentName: string;
  nextVersionNum: number;
  preloadedFile?: File | null;
  onClose: () => void;
  onUploaded: (newVersionId: number) => void;
}> = ({ open, documentId, documentName, nextVersionNum, preloadedFile = null, onClose, onUploaded }) => {
  const [mode, setMode] = useState<'file' | 'paste'>('file');
  const [file, setFile] = useState<File | null>(preloadedFile);
  const [text, setText] = useState('');
  const [label, setLabel] = useState('');
  const [sourceTag, setSourceTag] = useState('AI润色');
  const [notes, setNotes] = useState('');
  const [isMilestone, setIsMilestone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [tcInfo, setTcInfo] = useState<TrackedChangesInfo | null>(null);

  React.useEffect(() => {
    if (preloadedFile) {
      setFile(preloadedFile);
      setMode('file');
    }
  }, [preloadedFile]);

  // Auto-inspect .docx files for Word Track Changes (<w:ins>/<w:del>)!
  React.useEffect(() => {
    let cancelled = false;
    setTcInfo(null);
    if (!file || !file.name.toLowerCase().endsWith('.docx')) return;
    api
      .inspectDocxTrackedChanges(documentId, file)
      .then((info) => {
        if (!cancelled && info.has_tracked_changes) {
          setTcInfo(info);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [file, documentId]);

  if (!open) return null;

  const handleSplitTrackedImport = async () => {
    if (!file) return;
    setErr('');
    setBusy(true);
    try {
      const res = await api.importTrackedDocxSplit(documentId, file, label.trim(), notes.trim());
      setFile(null);
      setLabel('');
      setNotes('');
      setTcInfo(null);
      onUploaded(res.after_version.id);
      onClose();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Word 修订拆分导入失败');
    } finally {
      setBusy(false);
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr('');
    setBusy(true);
    try {
      const effLabel = label.trim() || `v${nextVersionNum} · ${sourceTag}`;
      if (mode === 'file') {
        if (!file) {
          setErr('请选择或拖入 .tex / .zip / .docx / .md / .txt 文件');
          setBusy(false);
          return;
        }
        const v = await api.uploadDocVersionFile(documentId, file, effLabel, sourceTag, notes, isMilestone);
        setFile(null);
        setLabel('');
        setNotes('');
        setIsMilestone(false);
        onUploaded(v.id);
        onClose();
      } else {
        if (!text.trim()) {
          setErr('请粘贴文稿内容');
          setBusy(false);
          return;
        }
        const v = await api.createDocVersionText(documentId, {
          label: effLabel,
          source_tag: sourceTag,
          filename: 'pasted.tex',
          format: 'auto',
          content: text,
          notes,
          is_milestone: isMilestone,
        });
        setText('');
        setLabel('');
        setNotes('');
        setIsMilestone(false);
        onUploaded(v.id);
        onClose();
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : '上传失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell title={`导入新版本 →「${documentName}」`} onClose={onClose} width="max-w-xl">
      <form onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-2 rounded-lg bg-slate-100 p-1 text-xs font-semibold">
          <button
            type="button"
            onClick={() => setMode('file')}
            className={`rounded-md py-1.5 transition-all ${
              mode === 'file' ? 'bg-white text-slate-900 shadow-xs' : 'text-slate-500'
            }`}
          >
            上传文件 (.tex / .zip / .docx / .md)
          </button>
          <button
            type="button"
            onClick={() => setMode('paste')}
            className={`rounded-md py-1.5 transition-all ${
              mode === 'paste' ? 'bg-white text-slate-900 shadow-xs' : 'text-slate-500'
            }`}
          >
            直接粘贴源码 / 正文
          </button>
        </div>

        {mode === 'file' ? (
          <label
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
            }}
            className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-300 bg-slate-50/70 px-6 py-7 text-center cursor-pointer hover:border-blue-400 hover:bg-blue-50/30 transition-colors"
          >
            <FileUp className="h-7 w-7 text-blue-500 mb-2" />
            <div className="text-sm font-semibold text-slate-700">
              {file ? file.name : '点击选择或拖拽文稿文件到此'}
            </div>
            <div className="mt-1 text-xs text-slate-400">
              支持 .tex、Overleaf .zip（自动展开 \input）、Word .docx、.md / .txt
            </div>
            <input
              type="file"
              accept=".tex,.ltx,.zip,.docx,.md,.markdown,.txt"
              className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </label>
        ) : (
          <textarea
            rows={7}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="直接粘贴 LaTeX 源码、Markdown 或 Word 正文..."
            className="w-full rounded-xl border border-slate-300 p-3 font-mono text-xs leading-relaxed focus:border-blue-500 focus:outline-none"
          />
        )}

        {/* Word Track Changes Split-Import Callout */}
        {mode === 'file' && tcInfo?.has_tracked_changes && (
          <div className="rounded-xl border border-blue-200 bg-blue-50/75 p-3 text-xs text-blue-950">
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="font-bold text-blue-800 flex items-center gap-1.5">
                  <GitCompareArrows className="h-3.5 w-3.5" />
                  {tcInfo.summary}
                </div>
                <p className="mt-1 text-[11px] leading-relaxed text-blue-800/80">
                  可一键拆分为「修订前原稿 (v{nextVersionNum})」与「修订后新稿 (v{nextVersionNum + 1})」两版入库并直接进入词级对比
                  {tcInfo.authors.length > 0 ? `（修订者：${tcInfo.authors.join('、')}）` : ''}。
                </p>
              </div>
              <button
                type="button"
                disabled={busy}
                onClick={handleSplitTrackedImport}
                className="shrink-0 rounded-lg bg-blue-600 px-3 py-1.5 text-[11.5px] font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
              >
                拆分导入并对比
              </button>
            </div>
          </div>
        )}

        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1.5">版本来源标签</label>
          <div className="flex flex-wrap gap-1.5">
            {SOURCE_TAGS.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setSourceTag(t)}
                className={`rounded-full px-3 py-1 text-xs font-medium border transition-colors ${
                  sourceTag === t
                    ? 'border-blue-600 bg-blue-600 text-white'
                    : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">版本名称（可选）</label>
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder={`默认：v${nextVersionNum} · ${sourceTag}`}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs focus:border-blue-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">修改说明（可选）</label>
            <input
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="例如：压缩引言 + 核对 p 值"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs focus:border-blue-500 focus:outline-none"
            />
          </div>
        </div>

        <label className="flex items-center gap-2 text-xs text-slate-600 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={isMilestone}
            onChange={(e) => setIsMilestone(e.target.checked)}
            className="rounded border-slate-300"
          />
          <Star className="h-3.5 w-3.5 text-amber-400 fill-amber-400" />
          设为里程碑版本（如投稿版、终审版，便于后续一键对比）
        </label>

        {err && <p className="text-xs text-rose-600">{err}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            取消
          </button>
          <button
            type="submit"
            disabled={busy}
            className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {busy ? '解析入库中...' : nextVersionNum <= 1 ? '入库并阅读预览' : '入库并自动对比'}
          </button>
        </div>
      </form>
    </ModalShell>
  );
};

/* ---------------- Save Merged / Single-Revised Version Modal ---------------- */
export const SaveMergedVersionModal: React.FC<{
  open: boolean;
  mode?: 'compare' | 'read';
  nextVersionNum: number;
  revertedCount: number;
  editedParaCount: number;
  onClose: () => void;
  onConfirm: (payload: {
    label: string;
    source_tag: string;
    notes: string;
    is_milestone: boolean;
  }) => Promise<void>;
}> = ({ open, mode = 'compare', nextVersionNum, revertedCount, editedParaCount, onClose, onConfirm }) => {
  const [label, setLabel] = useState('');
  const [sourceTag, setSourceTag] = useState('人工修复');
  const [notes, setNotes] = useState('');
  const [isMilestone, setIsMilestone] = useState(false);
  const [busy, setBusy] = useState(false);

  if (!open) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await onConfirm({
        label: label.trim() || `v${nextVersionNum} · ${sourceTag}`,
        source_tag: sourceTag,
        notes: notes.trim(),
        is_milestone: isMilestone,
      });
      setLabel('');
      setNotes('');
      setIsMilestone(false);
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell
      title={mode === 'read' ? '将阅读态修订存为新版本' : '将当前修复结果存为新版本'}
      onClose={onClose}
    >
      <form onSubmit={submit} className="space-y-4">
        <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-3 text-xs text-emerald-900">
          {mode === 'read' ? (
            <>
              本次包含阅读态原位微调 <strong>{editedParaCount}</strong> 段。保存后将采用无损回写作为{' '}
              <strong>v{nextVersionNum}</strong> 写入当前文档版本链，并自动进入与上一版的对比校验。
            </>
          ) : (
            <>
              本次合成包含 <strong>{revertedCount}</strong> 处逐块回退与{' '}
              <strong>{editedParaCount}</strong> 段原地手动微调。保存后将直接作为{' '}
              <strong>v{nextVersionNum}</strong> 写入当前文档版本链，可立即作为基准继续下一轮修改。
            </>
          )}
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">新版本名称</label>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder={`默认：v${nextVersionNum} · ${sourceTag}`}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs focus:border-blue-500 focus:outline-none"
            autoFocus
          />
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1.5">来源标签</label>
          <div className="flex flex-wrap gap-1.5">
            {SOURCE_TAGS.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setSourceTag(t)}
                className={`rounded-full px-2.5 py-1 text-xs font-medium border ${
                  sourceTag === t
                    ? 'border-emerald-600 bg-emerald-600 text-white'
                    : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">修复说明（可选）</label>
          <input
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="留空将自动记录回退与微调统计"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs focus:border-blue-500 focus:outline-none"
          />
        </div>

        <label className="flex items-center gap-2 text-xs text-slate-600 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={isMilestone}
            onChange={(e) => setIsMilestone(e.target.checked)}
            className="rounded border-slate-300"
          />
          <Star className="h-3.5 w-3.5 text-amber-400 fill-amber-400" />
          设为星标里程碑版本
        </label>

        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            取消
          </button>
          <button
            type="submit"
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-2 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            <Save className="h-3.5 w-3.5" />
            {busy ? '正在入库...' : `保存为 v${nextVersionNum}`}
          </button>
        </div>
      </form>
    </ModalShell>
  );
};

/* ---------------- Edit Version Metadata Modal ---------------- */
export const EditVersionModal: React.FC<{
  version: VersionSummary | null;
  onClose: () => void;
  onSaved: () => Promise<void>;
}> = ({ version, onClose, onSaved }) => {
  const [label, setLabel] = useState(version?.label || '');
  const [sourceTag, setSourceTag] = useState(version?.source_tag || '手改');
  const [notes, setNotes] = useState(version?.notes || '');
  const [isMilestone, setIsMilestone] = useState(Boolean(version?.is_milestone));
  const [busy, setBusy] = useState(false);

  React.useEffect(() => {
    if (version) {
      setLabel(version.label);
      setSourceTag(version.source_tag);
      setNotes(version.notes);
      setIsMilestone(Boolean(version.is_milestone));
    }
  }, [version]);

  if (!version) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.updateVersion(version.id, {
        label: label.trim() || version.label,
        source_tag: sourceTag,
        notes,
        is_milestone: isMilestone,
      });
      await onSaved();
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell title="编辑版本信息" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">版本名称</label>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs focus:border-blue-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1.5">来源标签</label>
          <div className="flex flex-wrap gap-1.5">
            {SOURCE_TAGS.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setSourceTag(t)}
                className={`rounded-full px-2.5 py-1 text-xs font-medium border ${
                  sourceTag === t
                    ? 'border-blue-600 bg-blue-600 text-white'
                    : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">修改备注</label>
          <input
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs focus:border-blue-500 focus:outline-none"
          />
        </div>
        <label className="flex items-center gap-2 text-xs text-slate-600 cursor-pointer">
          <input
            type="checkbox"
            checked={isMilestone}
            onChange={(e) => setIsMilestone(e.target.checked)}
            className="rounded border-slate-300"
          />
          <Star className="h-3.5 w-3.5 text-amber-400 fill-amber-400" />
          设为星标里程碑版本
        </label>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            取消
          </button>
          <button
            type="submit"
            disabled={busy}
            className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {busy ? '保存中...' : '保存'}
          </button>
        </div>
      </form>
    </ModalShell>
  );
};

/* ---------------- Quick Compare / Quick Single-Doc Preview Modal ---------------- */
export const QuickCompareModal: React.FC<{
  open: boolean;
  initialOld?: string;
  initialNew?: string;
  initialOldLabel?: string;
  initialOldMeta?: Record<string, unknown>;
  onClose: () => void;
  onCompare: (
    oldText: string,
    newText: string,
    oldLabel: string,
    newLabel: string,
    oldMeta?: Record<string, unknown>,
    newMeta?: Record<string, unknown>,
  ) => void;
  onPreviewSingle?: (
    content: string,
    label: string,
    meta?: Record<string, unknown>,
  ) => void;
}> = ({
  open,
  initialOld = '',
  initialNew = '',
  initialOldLabel,
  initialOldMeta,
  onClose,
  onCompare,
  onPreviewSingle,
}) => {
  const [oldText, setOldText] = useState(initialOld);
  const [newText, setNewText] = useState(initialNew);
  const [oldMeta, setOldMeta] = useState<Record<string, unknown>>(initialOldMeta || {});
  const [newMeta, setNewMeta] = useState<Record<string, unknown>>({});
  const [oldLabel, setOldLabel] = useState(initialOldLabel || '旧版本 (Before)');
  const [newLabel, setNewLabel] = useState('新版本 (After)');
  const [err, setErr] = useState('');

  React.useEffect(() => {
    if (open) {
      if (initialOld) setOldText(initialOld);
      if (initialNew) setNewText(initialNew);
      if (initialOldLabel) setOldLabel(initialOldLabel);
      if (initialOldMeta) setOldMeta(initialOldMeta);
    }
  }, [open, initialOld, initialNew, initialOldLabel, initialOldMeta]);

  if (!open) return null;

  const handleFilePick = async (side: 'old' | 'new', file: File | undefined) => {
    if (!file) return;
    setErr('');
    try {
      const res = await api.parseUploadFile(file);
      if (side === 'old') {
        setOldText(res.content);
        setOldLabel(res.filename);
        setOldMeta(res.meta || {});
      } else {
        setNewText(res.content);
        setNewLabel(res.filename);
        setNewMeta(res.meta || {});
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : '文件读取失败');
    }
  };

  return (
    <ModalShell title="快速阅读 / 对比" onClose={onClose} width="max-w-4xl">
      <div className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <input
                value={oldLabel}
                onChange={(e) => setOldLabel(e.target.value)}
                className="text-xs font-semibold text-rose-700 bg-rose-50 rounded px-2 py-0.5 border border-rose-200 focus:outline-none"
              />
              <label className="text-[11px] font-medium text-blue-600 hover:underline cursor-pointer">
                导入文件 (.tex/.zip/.docx)
                <input
                  type="file"
                  accept=".tex,.ltx,.zip,.docx,.md,.txt"
                  className="hidden"
                  onChange={(e) => handleFilePick('old', e.target.files?.[0])}
                />
              </label>
            </div>
            <textarea
              rows={11}
              value={oldText}
              onChange={(e) => setOldText(e.target.value)}
              placeholder="粘贴旧版本文本或 LaTeX 源码（只填此侧也可直接「单稿阅读预览」）..."
              className="w-full rounded-xl border border-slate-300 p-3 font-mono text-xs leading-relaxed focus:border-blue-500 focus:outline-none"
            />
          </div>
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <input
                value={newLabel}
                onChange={(e) => setNewLabel(e.target.value)}
                className="text-xs font-semibold text-emerald-700 bg-emerald-50 rounded px-2 py-0.5 border border-emerald-200 focus:outline-none"
              />
              <label className="text-[11px] font-medium text-blue-600 hover:underline cursor-pointer">
                导入文件 (.tex/.zip/.docx)
                <input
                  type="file"
                  accept=".tex,.ltx,.zip,.docx,.md,.txt"
                  className="hidden"
                  onChange={(e) => handleFilePick('new', e.target.files?.[0])}
                />
              </label>
            </div>
            <textarea
              rows={11}
              value={newText}
              onChange={(e) => setNewText(e.target.value)}
              placeholder="粘贴 AI 修改后的新版本文本或 LaTeX 源码..."
              className="w-full rounded-xl border border-slate-300 p-3 font-mono text-xs leading-relaxed focus:border-blue-500 focus:outline-none"
            />
          </div>
        </div>
        {err && <p className="text-xs text-rose-600">{err}</p>}
        <div className="flex items-center justify-between pt-1">
          <span className="text-[11.5px] text-slate-400">纯本地计算，文稿不会上传外部服务器</span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
            >
              取消
            </button>
            {onPreviewSingle && (
              <button
                type="button"
                onClick={() => {
                  const chosenText = newText.trim() ? newText : oldText;
                  const chosenLabel = newText.trim() ? newLabel : oldLabel;
                  const chosenMeta = newText.trim() ? newMeta : oldMeta;
                  if (!chosenText.trim()) {
                    setErr('请至少在一侧填入或导入文稿以阅读预览');
                    return;
                  }
                  onPreviewSingle(chosenText, chosenLabel, chosenMeta);
                  onClose();
                }}
                className="inline-flex items-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 px-4 py-2 text-xs font-semibold text-blue-700 hover:bg-blue-100"
              >
                <BookOpen className="h-3.5 w-3.5" />
                单稿阅读预览
              </button>
            )}
            <button
              type="button"
              onClick={() => {
                if (!oldText.trim() || !newText.trim()) {
                  setErr('双稿对比需要在左右两侧都填入内容；如仅看单篇，请点「单稿阅读预览」');
                  return;
                }
                onCompare(oldText, newText, oldLabel, newLabel, oldMeta, newMeta);
                onClose();
              }}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700"
            >
              <Zap className="h-3.5 w-3.5" />
              双稿立即对比
            </button>
          </div>
        </div>
      </div>
    </ModalShell>
  );
};

/* ---------------- Glossary Modal ---------------- */
export const GlossaryModal: React.FC<{
  open: boolean;
  projectName?: string;
  terms: string[];
  onClose: () => void;
  onSave: (terms: string[]) => Promise<void>;
}> = ({ open, projectName, terms, onClose, onSave }) => {
  const [list, setList] = useState<string[]>(terms);
  const [input, setInput] = useState('');
  const [saving, setSaving] = useState(false);

  React.useEffect(() => {
    setList(terms);
  }, [terms, open]);

  if (!open) return null;

  const addTerm = () => {
    const parts = input
      .split(/[,，\n]+/)
      .map((s) => s.trim())
      .filter((s) => s && !list.includes(s));
    if (parts.length) {
      setList([...list, ...parts]);
      setInput('');
    }
  };

  return (
    <ModalShell title={`受保护专业术语表${projectName ? ` · ${projectName}` : ''}`} onClose={onClose}>
      <div className="space-y-4">
        <p className="text-xs leading-relaxed text-slate-500">
          该项目下的所有文档（主论文 / SI / 审稿回复等）共享此术语保护表。若旧版出现而新版消失，审计引擎将自动触发告警。
        </p>
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                addTerm();
              }
            }}
            placeholder="输入术语后回车（支持逗号批量添加）"
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-xs focus:border-blue-500 focus:outline-none"
          />
          <button
            type="button"
            onClick={addTerm}
            className="inline-flex items-center gap-1 rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white hover:bg-slate-800"
          >
            <Plus className="h-3.5 w-3.5" />
            添加
          </button>
        </div>

        <div className="flex flex-wrap gap-1.5 min-h-[56px] rounded-xl border border-slate-200 bg-slate-50/60 p-3">
          {list.length === 0 ? (
            <span className="text-xs text-slate-400">暂无受保护术语</span>
          ) : (
            list.map((t) => (
              <span
                key={t}
                className="inline-flex items-center gap-1 rounded-full bg-white border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-700"
              >
                <ShieldCheck className="h-3 w-3 text-blue-600" />
                {t}
                <button
                  type="button"
                  onClick={() => setList(list.filter((x) => x !== t))}
                  className="text-slate-400 hover:text-rose-600"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))
          )}
        </div>

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            取消
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={async () => {
              setSaving(true);
              try {
                await onSave(list);
                onClose();
              } finally {
                setSaving(false);
              }
            }}
            className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? '保存中...' : '保存术语表'}
          </button>
        </div>
      </div>
    </ModalShell>
  );
};

/* ---------------- Editable AI-ism Lexicon Modal (v1.3) ---------------- */
export const AiLexiconModal: React.FC<{
  open: boolean;
  onClose: () => void;
  onSaved: () => Promise<void>;
}> = ({ open, onClose, onSaved }) => {
  const [config, setConfig] = useState<AiLexiconConfig | null>(null);
  const [addedEn, setAddedEn] = useState<string[]>([]);
  const [addedZh, setAddedZh] = useState<string[]>([]);
  const [muted, setMuted] = useState<string[]>([]);
  const [newWord, setNewWord] = useState('');
  const [saving, setSaving] = useState(false);

  React.useEffect(() => {
    if (!open) return;
    api.getAiLexicon().then((data) => {
      setConfig(data);
      setAddedEn(data.added_en || []);
      setAddedZh(data.added_zh || []);
      setMuted(data.muted || []);
    });
  }, [open]);

  if (!open) return null;

  const toggleMute = (word: string) => {
    const key = word.toLowerCase();
    setMuted((prev) => (prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key]));
  };

  const addCustomWord = () => {
    const parts = newWord
      .split(/[,，\n]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (!parts.length) return;
    const nextEn = [...addedEn];
    const nextZh = [...addedZh];
    for (const p of parts) {
      if (/[\u4e00-\u9fff]/.test(p)) {
        if (!nextZh.includes(p)) nextZh.push(p);
      } else {
        const low = p.toLowerCase();
        if (!nextEn.includes(low)) nextEn.push(low);
      }
    }
    setAddedEn(nextEn);
    setAddedZh(nextZh);
    setNewWord('');
  };

  const save = async () => {
    setSaving(true);
    try {
      await api.saveAiLexicon({ added_en: addedEn, added_zh: addedZh, muted });
      await onSaved();
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <ModalShell title="自定义 AI 套话词典（屏蔽误报 / 新增个人避雷词）" onClose={onClose} width="max-w-2xl">
      {!config ? (
        <div className="py-8 text-center text-xs text-slate-400">加载词典中...</div>
      ) : (
        <div className="space-y-4">
          <p className="text-xs leading-relaxed text-slate-500">
            点击任意内置默认词即可<strong>屏蔽/恢复</strong>（例如你所在学科常把 <code>fundamental</code> 或{' '}
            <code>robustness</code> 作为正常术语时可一键屏蔽），也可以在下方添加导师或个人避雷词（自动区分中英文）。
          </p>

          {/* Add Custom Word */}
          <div className="flex gap-2">
            <input
              value={newWord}
              onChange={(e) => setNewWord(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  addCustomWord();
                }
              }}
              placeholder="输入想监控的英文或中文词（如：obviously, 显而易见, 众所周知），支持逗号批量添加"
              className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-xs focus:border-blue-500 focus:outline-none"
            />
            <button
              type="button"
              onClick={addCustomWord}
              className="inline-flex items-center gap-1 rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white hover:bg-slate-800"
            >
              <Plus className="h-3.5 w-3.5" />
              添加避雷词
            </button>
          </div>

          {/* Custom Added Words */}
          {(addedEn.length > 0 || addedZh.length > 0) && (
            <div className="rounded-xl border border-blue-200/80 bg-blue-50/40 p-3">
              <div className="mb-1.5 text-[11px] font-semibold text-blue-900">
                已添加的自定义监控词 ({addedEn.length + addedZh.length})
              </div>
              <div className="flex flex-wrap gap-1.5">
                {addedEn.map((w) => (
                  <span
                    key={`en-${w}`}
                    className="inline-flex items-center gap-1 rounded-full bg-white border border-blue-200 px-2.5 py-0.5 text-[11px] font-medium text-blue-800"
                  >
                    {w}
                    <button
                      type="button"
                      onClick={() => setAddedEn(addedEn.filter((x) => x !== w))}
                      className="text-slate-400 hover:text-rose-600"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
                {addedZh.map((w) => (
                  <span
                    key={`zh-${w}`}
                    className="inline-flex items-center gap-1 rounded-full bg-white border border-blue-200 px-2.5 py-0.5 text-[11px] font-medium text-blue-800"
                  >
                    {w}
                    <button
                      type="button"
                      onClick={() => setAddedZh(addedZh.filter((x) => x !== w))}
                      className="text-slate-400 hover:text-rose-600"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Built-in EN Words (Click to Mute/Unmute) */}
          <div>
            <div className="mb-1.5 flex items-center justify-between text-[11px] font-semibold text-slate-600">
              <span>内置英文 AI 套话词（点击屏蔽误报，划线为已屏蔽）</span>
              <span className="font-normal text-slate-400">已屏蔽 {muted.length} 个</span>
            </div>
            <div className="max-h-36 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50/60 p-2.5 flex flex-wrap gap-1.5">
              {[...config.defaults.en_words, ...config.defaults.en_phrases].map((w) => {
                const isMuted = muted.includes(w.toLowerCase());
                return (
                  <button
                    key={w}
                    type="button"
                    onClick={() => toggleMute(w)}
                    className={`rounded-md px-2 py-0.5 text-[11px] border transition-colors ${
                      isMuted
                        ? 'bg-slate-100 text-slate-400 border-slate-200 line-through'
                        : 'bg-white text-slate-700 border-slate-200 hover:border-rose-300'
                    }`}
                  >
                    {w}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Built-in ZH Words */}
          <div>
            <div className="mb-1.5 text-[11px] font-semibold text-slate-600">
              内置中文 AI 套话词（点击屏蔽/恢复）
            </div>
            <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-2.5 flex flex-wrap gap-1.5">
              {config.defaults.zh_words.map((w) => {
                const isMuted = muted.includes(w.toLowerCase());
                return (
                  <button
                    key={w}
                    type="button"
                    onClick={() => toggleMute(w)}
                    className={`rounded-md px-2 py-0.5 text-[11px] border transition-colors ${
                      isMuted
                        ? 'bg-slate-100 text-slate-400 border-slate-200 line-through'
                        : 'bg-white text-slate-700 border-slate-200 hover:border-rose-300'
                    }`}
                  >
                    {w}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
            >
              取消
            </button>
            <button
              type="button"
              disabled={saving}
              onClick={save}
              className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? '保存并重算中...' : '保存并重新审计'}
            </button>
          </div>
        </div>
      )}
    </ModalShell>
  );
};

/* ---------------- Publication-Grade Offline PDF Export Modal (v1.1) ---------------- */
export const PdfExportModal: React.FC<{
  open: boolean;
  mode: 'read' | 'compare';
  onClose: () => void;
  onExportPdf: (opts: {
    template: 'pdf_diff_report' | 'pdf_diff_compact' | 'pdf_single';
    commentaryNote: string;
    landscape: boolean;
  }) => Promise<void>;
}> = ({ open, mode, onClose, onExportPdf }) => {
  const [template, setTemplate] = useState<'pdf_diff_report' | 'pdf_diff_compact' | 'pdf_single'>(
    mode === 'read' ? 'pdf_single' : 'pdf_diff_report',
  );
  const [commentaryNote, setCommentaryNote] = useState('');
  const [landscape, setLandscape] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  React.useEffect(() => {
    if (open) {
      setTemplate(mode === 'read' ? 'pdf_single' : 'pdf_diff_report');
      setErr('');
    }
  }, [open, mode]);

  if (!open) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr('');
    try {
      await onExportPdf({ template, commentaryNote, landscape });
      onClose();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'PDF 导出失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell title="导出 PDF" onClose={onClose} width="max-w-lg">
      <form onSubmit={submit} className="space-y-4">
        <div className="space-y-2">
          <label className="block text-xs font-semibold text-slate-700">选择模板</label>
          {mode === 'compare' ? (
            <div className="grid grid-cols-1 gap-2">
              <button
                type="button"
                onClick={() => setTemplate('pdf_diff_report')}
                className={`rounded-xl border p-3 text-left transition ${
                  template === 'pdf_diff_report'
                    ? 'border-blue-500 bg-blue-50/70'
                    : 'border-slate-200 hover:bg-slate-50'
                }`}
              >
                <div className="text-xs font-bold text-slate-900">
                  完整对比报告（推荐）
                </div>
                <div className="mt-0.5 text-[11px] text-slate-500">
                  含改动摘要、逐段红绿对比、表格差值与修改说明
                </div>
              </button>
              <button
                type="button"
                onClick={() => setTemplate('pdf_diff_compact')}
                className={`rounded-xl border p-3 text-left transition ${
                  template === 'pdf_diff_compact'
                    ? 'border-blue-500 bg-blue-50/70'
                    : 'border-slate-200 hover:bg-slate-50'
                }`}
              >
                <div className="text-xs font-bold text-slate-900">
                  精简修订清单
                </div>
                <div className="mt-0.5 text-[11px] text-slate-500">
                  仅保留有改动的段落和表格，方便导师快速核对
                </div>
              </button>
            </div>
          ) : (
            <div className="rounded-xl border border-blue-500 bg-blue-50/70 p-3 text-xs">
              <div className="font-bold text-slate-900">单稿阅读版 PDF</div>
              <div className="mt-0.5 text-[11px] text-slate-500">
                保留公式、表格、插图与脚注，已应用当前暂存修改
              </div>
            </div>
          )}
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">
            页面方向（A4 标准打印）
          </label>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <button
              type="button"
              onClick={() => setLandscape(false)}
              className={`rounded-lg border py-2 font-medium transition ${
                !landscape ? 'border-blue-600 bg-blue-600 text-white' : 'border-slate-200 text-slate-600'
              }`}
            >
              A4 纵向（常规论文）
            </button>
            <button
              type="button"
              onClick={() => setLandscape(true)}
              className={`rounded-lg border py-2 font-medium transition ${
                landscape ? 'border-blue-600 bg-blue-600 text-white' : 'border-slate-200 text-slate-600'
              }`}
            >
              A4 横向（宽表友好）
            </button>
          </div>
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">
            作者 / 导师审校批注（可选，将印刷于报告首页）
          </label>
          <textarea
            rows={3}
            value={commentaryNote}
            onChange={(e) => setCommentaryNote(e.target.value)}
            placeholder="例如：本轮重点核对了表 2 的 RMSE 与正文第 3.2 节的 p 值，所有去 AI 味修改均保持原始实验结论不变。"
            className="w-full rounded-xl border border-slate-300 p-2.5 text-xs leading-relaxed focus:border-blue-500 focus:outline-none"
          />
        </div>

        {err && <p className="text-xs text-rose-600">{err}</p>}
        <div className="flex items-center justify-between pt-1">
          <span className="text-[11px] text-slate-400">
            本地离线生成 · 矢量文字与公式清晰可搜索
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
            >
              <FileDown className="h-3.5 w-3.5" />
              {busy ? '正在生成 PDF…' : '导出 PDF'}
            </button>
          </div>
        </div>
      </form>
    </ModalShell>
  );
};

/* ---------------- Local Folder Binding Management Modal (AC-08 / AC-18) ---------------- */
export const LocalBindingModal: React.FC<{
  project: Project | null;
  onClose: () => void;
  onRelocated: (project: Project) => void;
  onUnbound: (project: Project) => void;
  onDeleted: (projectId: number) => void;
}> = ({ project, onClose, onRelocated, onUnbound, onDeleted }) => {
  const [newPath, setNewPath] = useState('');
  const [valRes, setValRes] = useState<LocalFolderValidation | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    if (project) {
      setNewPath(project.local_root_path || '');
      setValRes(null);
      setErr('');
    }
  }, [project]);

  if (!project) return null;

  const handlePick = async () => {
    setErr('');
    try {
      const res = await api.pickLocalFolder(newPath || undefined);
      if (res.picked && res.path) {
        setNewPath(res.path);
        const v = await api.validateLocalFolder(res.path);
        setValRes(v);
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : '无法打开目录选择器');
    }
  };

  const handleRelocate = async () => {
    if (!newPath.trim()) return setErr('请输入有效的本地目录路径');
    setBusy(true);
    setErr('');
    try {
      const updated = await api.updateProject(project.id, {
        project_mode: 'local_folder',
        local_root_path: newPath.trim(),
      });
      onRelocated(updated);
      onClose();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : '重新定位失败');
    } finally {
      setBusy(false);
    }
  };

  const handleUnbind = async () => {
    setBusy(true);
    setErr('');
    try {
      const updated = await api.updateProject(project.id, {
        project_mode: 'managed',
        local_root_path: '',
      });
      onUnbound(updated);
      onClose();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : '解除绑定失败');
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    setBusy(true);
    setErr('');
    try {
      await api.deleteProject(project.id);
      onDeleted(project.id);
      onClose();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : '移除项目失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell title={`本地目录绑定管理 · ${project.name}`} onClose={onClose}>
      <div data-local-binding-modal="true" className="space-y-4 text-xs">
        <div className="rounded-xl border border-emerald-200 bg-emerald-50/70 px-3.5 py-2.5 text-emerald-900 flex items-start gap-2">
          <ShieldCheck className="h-4 w-4 shrink-0 mt-0.5 text-emerald-600" />
          <div className="leading-relaxed">
            仅调整项目关联，<strong>绝不删除或修改您磁盘上的任何原文件</strong>。
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="font-semibold text-slate-700">重新定位本地目录（保留历史消警）</label>
            <button
              type="button"
              onClick={handlePick}
              className="inline-flex items-center gap-1 rounded-lg bg-teal-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-teal-700"
            >
              <FolderOpen className="h-3 w-3" />
              选择新目录
            </button>
          </div>
          <input
            data-relocate-path-input="true"
            value={newPath}
            onChange={(e) => {
              setNewPath(e.target.value);
              setValRes(null);
            }}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-xs focus:border-teal-500 focus:outline-none"
          />
          {valRes && (
            <div className={valRes.valid ? 'text-emerald-700' : 'text-rose-600'}>
              {valRes.valid ? `目录有效，识别到 ${valRes.doc_count ?? 0} 个受支持文稿` : valRes.detail}
            </div>
          )}
          <button
            type="button"
            data-relocate-submit="true"
            disabled={busy}
            onClick={handleRelocate}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3.5 py-1.5 font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            保存新目录路径
          </button>
        </div>

        <div className="border-t border-slate-100 pt-3 flex flex-wrap items-center justify-between gap-2">
          <button
            type="button"
            data-unbind-project-btn="true"
            disabled={busy}
            onClick={handleUnbind}
            className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 font-semibold text-amber-800 hover:bg-amber-100 disabled:opacity-50"
          >
            <Unlink className="h-3.5 w-3.5" />
            解除本地绑定（不删盘）
          </button>
          <button
            type="button"
            data-delete-local-project-btn="true"
            disabled={busy}
            onClick={handleDelete}
            className="inline-flex items-center gap-1.5 rounded-lg border border-rose-300 bg-rose-50 px-3 py-1.5 font-semibold text-rose-700 hover:bg-rose-100 disabled:opacity-50"
          >
            <Trash2 className="h-3.5 w-3.5" />
            移除项目记录（不删盘）
          </button>
        </div>
        {err && <p className="text-xs text-rose-600">{err}</p>}
      </div>
    </ModalShell>
  );
};

/* ---------------- Save Local Edits Modal (D-05 Choice C: Save-As Default | Overwrite + .bak) ---------------- */
export const SaveLocalEditsModal: React.FC<{
  open: boolean;
  projectId: number;
  relPath: string;
  expectedSha256?: string;
  patches: TypedPatchOp[];
  paragraphEdits: Record<number, string>;
  onClose: () => void;
  onSaved: (res: LocalSaveEditsResult) => void;
}> = ({ open, projectId, relPath, expectedSha256, patches, paragraphEdits, onClose, onSaved }) => {
  const [mode, setMode] = useState<'save_as' | 'overwrite'>('save_as');
  const [targetRelPath, setTargetRelPath] = useState('');
  const [conflictPrompt, setConflictPrompt] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    if (open) {
      setMode('save_as');
      setTargetRelPath(suggestRevisedRelPath(relPath));
      setConflictPrompt(false);
      setErr('');
    }
  }, [open, relPath]);

  if (!open) return null;

  const doSave = async (force = false) => {
    setBusy(true);
    setErr('');
    try {
      const res = await api.saveLocalEdits(projectId, {
        rel_path: relPath,
        patches,
        paragraph_edits: paragraphEdits,
        mode,
        target_rel_path: mode === 'save_as' ? targetRelPath.trim() || undefined : undefined,
        expected_sha256: mode === 'overwrite' ? expectedSha256 : undefined,
        force,
      });
      onSaved(res);
      onClose();
    } catch (e: unknown) {
      if (e instanceof ApiError && e.status === 409 && e.code === 'EXTERNAL_MODIFIED') {
        setConflictPrompt(true);
        setErr('磁盘原文件已被外部工具更新！建议切换为「另存为新文件」，或确认强制覆盖（仍会自动保留 .bak 备份）。');
      } else {
        setErr(e instanceof Error ? e.message : '保存失败');
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell title="保存本地文稿修订" onClose={onClose}>
      <div data-save-local-modal="true" className="space-y-4 text-xs">
        <div className="rounded-lg bg-slate-50 border border-slate-200 px-3 py-2 font-mono text-[11px] text-slate-600 truncate">
          当前文件：{relPath}
        </div>

        <div className="space-y-2">
          <label
            className={`flex items-start gap-2.5 rounded-xl border p-3 cursor-pointer transition-all ${
              mode === 'save_as'
                ? 'border-blue-500 bg-blue-50/50 ring-1 ring-blue-500/20'
                : 'border-slate-200 hover:bg-slate-50'
            }`}
          >
            <input
              type="radio"
              name="local_save_mode"
              data-save-mode="save_as"
              checked={mode === 'save_as'}
              onChange={() => {
                setMode('save_as');
                setConflictPrompt(false);
              }}
              className="mt-0.5"
            />
            <div className="flex-1 space-y-1.5">
              <div className="font-bold text-slate-800">另存为新文件（推荐）</div>
              <p className="text-[11px] text-slate-500">
                在当前目录保存修改后的副本，原文件保持不变。
              </p>
              {mode === 'save_as' && (
                <input
                  data-save-target-input="true"
                  value={targetRelPath}
                  onChange={(e) => setTargetRelPath(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 font-mono text-[11.5px] focus:border-blue-500 focus:outline-none"
                />
              )}
            </div>
          </label>

          <label
            className={`flex items-start gap-2.5 rounded-xl border p-3 cursor-pointer transition-all ${
              mode === 'overwrite'
                ? 'border-amber-500 bg-amber-50/50 ring-1 ring-amber-500/20'
                : 'border-slate-200 hover:bg-slate-50'
            }`}
          >
            <input
              type="radio"
              name="local_save_mode"
              data-save-mode="overwrite"
              checked={mode === 'overwrite'}
              onChange={() => setMode('overwrite')}
              className="mt-0.5"
            />
            <div className="flex-1">
              <div className="font-bold text-slate-800">覆盖原文件</div>
              <p className="mt-0.5 text-[11px] text-slate-500">
                覆盖前自动在同目录生成 <code className="font-mono">.paperdiff.bak</code> 备份。
              </p>
            </div>
          </label>
        </div>

        {err && (
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[11.5px] text-rose-700">
            {err}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-4 py-2 font-medium text-slate-600 hover:bg-slate-50"
          >
            取消
          </button>
          {conflictPrompt ? (
            <button
              type="button"
              data-save-force-overwrite="true"
              disabled={busy}
              onClick={() => doSave(true)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 px-4 py-2 font-semibold text-white hover:bg-amber-700 disabled:opacity-50"
            >
              <Save className="h-3.5 w-3.5" />
              仍要覆盖（保留 .bak）
            </button>
          ) : (
            <button
              type="button"
              data-save-local-confirm="true"
              disabled={busy}
              onClick={() => doSave(false)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-2 font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              <Save className="h-3.5 w-3.5" />
              {busy ? '正在写入...' : mode === 'save_as' ? '另存为新文件' : '备份并覆盖原文件'}
            </button>
          )}
        </div>
      </div>
    </ModalShell>
  );
};

/* ---------------- External Modification Conflict Modal (D-06 / AC-15) ---------------- */
export const ExternalConflictModal: React.FC<{
  open: boolean;
  relPath: string;
  pendingEditCount: number;
  onKeepDrafts: () => void;
  onDiscardAndReload: () => void;
}> = ({ open, relPath, pendingEditCount, onKeepDrafts, onDiscardAndReload }) => {
  if (!open) return null;
  return (
    <ModalShell title="检测到磁盘文件已在外部更新" onClose={onKeepDrafts}>
      <div data-external-conflict-modal="true" className="space-y-4 text-xs">
        <div className="flex items-start gap-2.5 rounded-xl border border-amber-200 bg-amber-50/70 p-3 text-amber-900">
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5 text-amber-600" />
          <div className="leading-relaxed">
            本地文件 <code className="font-mono font-semibold">{relPath}</code> 已被外部编辑器或 AI 工具更新，但您当前阅读器内仍有{' '}
            <strong>{pendingEditCount}</strong> 处未保存的原位微调。系统已阻止自动覆盖，请选择处理方式：
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            data-conflict-keep="true"
            onClick={onKeepDrafts}
            className="rounded-lg bg-blue-600 px-4 py-2 font-semibold text-white hover:bg-blue-700"
          >
            保留当前暂存微调
          </button>
          <button
            type="button"
            data-conflict-reload="true"
            onClick={onDiscardAndReload}
            className="rounded-lg border border-rose-300 bg-rose-50 px-4 py-2 font-semibold text-rose-700 hover:bg-rose-100"
          >
            放弃微调并重载磁盘最新版
          </button>
        </div>
      </div>
    </ModalShell>
  );
};

/* ---------------- Shared Modal Shell ---------------- */
const ModalShell: React.FC<{
  title: string;
  onClose: () => void;
  width?: string;
  children: React.ReactNode;
}> = ({ title, onClose, width = 'max-w-lg', children }) => (
  <div
    className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 backdrop-blur-[2px] p-4"
    onMouseDown={(e) => {
      if (e.target === e.currentTarget) onClose();
    }}
  >
    <div className={`w-full ${width} rounded-2xl border border-slate-200 bg-white shadow-2xl overflow-hidden`}>
      <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5">
        <h3 className="text-[14.5px] font-bold text-slate-900">{title}</h3>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="p-5">{children}</div>
    </div>
  </div>
);
