/**
 * @file ProjectsHome.tsx
 * @description Three-tier Projects Home dashboard (`Category -> Project -> Document -> Version`)
 * supporting card-grid and hierarchical tree views, status/pin management, onboarding banner,
 * and quick-open actions.
 */

import React, { useMemo, useState } from 'react';
import {
  AlertTriangle,
  Archive,
  ArrowRight,
  BookOpen,
  Check,
  FilePlus2,
  FileText,
  FolderOpen,
  FolderPlus,
  HelpCircle,
  LayoutGrid,
  List,
  Pencil,
  Pin,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Star,
  Trash2,
  X,
  Zap,
} from 'lucide-react';
import type { Project, ProjectCategory, ProjectStatus, ThemePreference } from '../types';
import type { ResumeResolution } from '../utils/workspaceResume';
import { ThemeMenuButton } from './ThemeSwitcher';
import { BrandLockup } from './BrandMark';

export const CATEGORY_META: Record<
  ProjectCategory,
  { label: string; badge: string; dot: string }
> = {
  paper: {
    label: '学术论文',
    badge: 'bg-blue-50 text-blue-700 border-blue-200/80',
    dot: 'bg-blue-500',
  },
  grant: {
    label: '基金申报',
    badge: 'bg-violet-50 text-violet-700 border-violet-200/80',
    dot: 'bg-violet-500',
  },
  report: {
    label: '结题报告',
    badge: 'bg-emerald-50 text-emerald-700 border-emerald-200/80',
    dot: 'bg-emerald-500',
  },
  other: {
    label: '其他文稿',
    badge: 'bg-slate-100 text-slate-600 border-slate-200',
    dot: 'bg-slate-400',
  },
};

export const STATUS_META: Record<ProjectStatus, { label: string; cls: string }> = {
  drafting: { label: '撰写中', cls: 'bg-slate-100 text-slate-600' },
  polishing: { label: '润色中', cls: 'bg-sky-50 text-sky-700' },
  revising: { label: '返修中', cls: 'bg-amber-50 text-amber-700' },
  done: { label: '已定稿', cls: 'bg-emerald-50 text-emerald-700' },
  archived: { label: '已归档', cls: 'bg-slate-100 text-slate-400' },
};

const DOC_TYPE_LABEL: Record<string, string> = {
  manuscript: '主论文',
  si: '补充材料',
  rebuttal: '审稿回复',
  proposal: '申请书',
  report: '报告正文',
  other: '文档',
};

interface ProjectsHomeProps {
  projects: Project[];
  onOpenDocument: (projectId: number, documentId: number) => void;
  onOpenLocalProject: (projectId: number) => void;
  onManageLocalBinding: (project: Project) => void;
  onNewProject: () => void;
  onNewDocument: (projectId: number) => void;
  onUploadToDocument: (projectId: number, documentId: number) => void;
  onUpdateProject: (
    projectId: number,
    patch: {
      name?: string;
      description?: string;
      category?: ProjectCategory;
      status?: ProjectStatus;
      pinned?: boolean;
    },
  ) => Promise<void>;
  onDeleteProject: (projectId: number) => Promise<void>;
  onDeleteDocument: (projectId: number, documentId: number) => Promise<void>;
  onOpenQuickCompare: () => void;
  onOpenGlossary: (projectId: number) => void;
  onOpenGuide: () => void;
  theme: ThemePreference;
  onChangeTheme: (pref: ThemePreference) => void;
  runtimeSlot?: React.ReactNode;
  resumeResolution?: ResumeResolution;
  autoResumeEnabled?: boolean;
  onToggleAutoResume?: (enabled: boolean) => void;
  onResumeWorkspace?: () => void;
  onDismissResume?: () => void;
}

export const ProjectsHome: React.FC<ProjectsHomeProps> = ({
  projects,
  onOpenDocument,
  onOpenLocalProject,
  onManageLocalBinding,
  onNewProject,
  onNewDocument,
  onUploadToDocument,
  onUpdateProject,
  onDeleteProject,
  onDeleteDocument,
  onOpenQuickCompare,
  onOpenGlossary,
  onOpenGuide,
  theme,
  onChangeTheme,
  runtimeSlot,
  resumeResolution,
  autoResumeEnabled = false,
  onToggleAutoResume,
  onResumeWorkspace,
  onDismissResume,
}) => {
  const [catFilter, setCatFilter] = useState<'all' | ProjectCategory>('all');
  const [showArchived, setShowArchived] = useState(false);
  const [layout, setLayout] = useState<'grid' | 'tree'>('grid');
  const [search, setSearch] = useState('');
  const [editingProjId, setEditingProjId] = useState<number | null>(null);
  const [editName, setEditName] = useState('');
  const [editDesc, setEditDesc] = useState('');
  const [editSaving, setEditSaving] = useState(false);

  const startEditProject = (proj: Project) => {
    setEditingProjId(proj.id);
    setEditName(proj.name);
    setEditDesc(proj.description || '');
  };

  const cancelEditProject = () => {
    setEditingProjId(null);
    setEditName('');
    setEditDesc('');
  };

  const commitEditProject = async (proj: Project) => {
    const trimmedName = editName.trim();
    if (!trimmedName || editSaving) return;
    const trimmedDesc = editDesc.trim();
    if (trimmedName === proj.name && trimmedDesc === (proj.description || '')) {
      cancelEditProject();
      return;
    }
    setEditSaving(true);
    try {
      await onUpdateProject(proj.id, { name: trimmedName, description: trimmedDesc });
      cancelEditProject();
    } finally {
      setEditSaving(false);
    }
  };
  const [welcomeDismissed, setWelcomeDismissed] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem('paperdiff_welcome_dismissed') === '1';
    } catch {
      return false;
    }
  });

  const dismissWelcome = () => {
    setWelcomeDismissed(true);
    try {
      window.localStorage.setItem('paperdiff_welcome_dismissed', '1');
    } catch {
      /* ignore */
    }
  };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return projects.filter((p) => {
      if (!showArchived && p.status === 'archived') return false;
      if (catFilter !== 'all' && p.category !== catFilter) return false;
      if (q) {
        const docNames = p.documents.map((d) => d.name).join(' ');
        const hay = `${p.name} ${p.description} ${docNames}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [projects, catFilter, showArchived, search]);

  const countsByCat = useMemo(() => {
    const active = projects.filter((p) => showArchived || p.status !== 'archived');
    return {
      all: active.length,
      paper: active.filter((p) => p.category === 'paper').length,
      grant: active.filter((p) => p.category === 'grant').length,
      report: active.filter((p) => p.category === 'report').length,
      other: active.filter((p) => p.category === 'other').length,
    };
  }, [projects, showArchived]);

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-[#F6F7F9]">
      {/* Home Top Bar */}
      <header className="z-30 flex h-[56px] shrink-0 items-center justify-between gap-4 border-b border-[#E6E8EE] bg-white px-6">
        <div className="flex items-center gap-3">
          <BrandLockup subtitle="论文阅读与版本比对" />
        </div>

        <div className="flex items-center gap-2.5">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索项目或文档名..."
              className="w-52 rounded-xl border border-slate-200 bg-[#FAFBFC] pl-8 pr-3 py-1.5 text-xs focus:border-blue-400 focus:bg-white focus:outline-none"
            />
          </div>
          <ThemeMenuButton value={theme} onChange={onChangeTheme} />
          {runtimeSlot}
          <button
            type="button"
            onClick={onOpenGuide}
            title="查看「对稿 · PaperDiff」产品使用指南"
            className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:border-blue-300 hover:bg-blue-50/40 hover:text-blue-700 transition-colors"
          >
            <HelpCircle className="h-3.5 w-3.5 text-blue-600" />
            使用指南
          </button>
          <button
            type="button"
            onClick={onOpenQuickCompare}
            className="inline-flex items-center gap-1.5 rounded-xl border border-blue-200 bg-blue-50/70 px-3 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-100/80 transition-colors"
          >
            <Zap className="h-3.5 w-3.5" />
            快速对比
          </button>
          <button
            type="button"
            onClick={onNewProject}
            className="inline-flex items-center gap-1.5 rounded-xl bg-blue-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 shadow-xs transition-colors"
          >
            <FolderPlus className="h-3.5 w-3.5" />
            新建项目
          </button>
        </div>
      </header>

      {/* Top Last-Workspace Quick Resume Card */}
      {resumeResolution && (resumeResolution.status === 'ready' || resumeResolution.status === 'root_invalid') && (
        <div className="mx-auto w-full max-w-[1600px] px-6 pt-4">
          <div
            data-resume-workspace-card="true"
            data-resume-status={resumeResolution.status}
            className="pd-resume-card flex flex-wrap items-center justify-between gap-3 rounded-2xl border px-4 py-3 shadow-2xs"
          >
            <div className="flex min-w-0 items-center gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-blue-500/12 text-blue-600">
                {resumeResolution.project.project_mode === 'local_folder' ? (
                  <FolderOpen className="h-4 w-4" />
                ) : (
                  <BookOpen className="h-4 w-4" />
                )}
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[11px] font-semibold uppercase tracking-wider pd-resume-muted">
                    上次工作区
                  </span>
                  <span className="truncate text-sm font-bold">
                    {resumeResolution.project.name}
                  </span>
                  <span className="rounded-md border border-slate-300/70 px-1.5 py-0.5 text-[10.5px] font-medium pd-resume-muted">
                    {resumeResolution.project.project_mode === 'local_folder' ? '本地目录' : '托管项目'}
                  </span>
                  {resumeResolution.status === 'root_invalid' && (
                    <span
                      data-resume-invalid-badge="true"
                      className="pd-resume-warn inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-semibold"
                    >
                      <AlertTriangle className="h-3 w-3" />
                      目录已移动（{resumeResolution.reason}）
                    </span>
                  )}
                </div>
                <div className="mt-0.5 truncate text-xs pd-resume-muted">
                  {resumeResolution.project.project_mode === 'local_folder'
                    ? resumeResolution.record.localRelPath
                      ? `上次文稿：${resumeResolution.record.localRelPath}`
                      : `目录路径：${resumeResolution.project.local_root_path || ''}`
                    : resumeResolution.record.documentName
                      ? `上次文档：${resumeResolution.record.documentName}`
                      : '点击继续阅读与编辑'}
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2.5">
              {onToggleAutoResume && (
                <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs pd-resume-muted select-none">
                  <input
                    type="checkbox"
                    data-auto-resume-toggle="true"
                    checked={autoResumeEnabled}
                    onChange={(e) => onToggleAutoResume(e.target.checked)}
                    className="h-3.5 w-3.5 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                  />
                  <span>启动自动打开</span>
                </label>
              )}
              {resumeResolution.status === 'root_invalid' ? (
                <button
                  type="button"
                  data-resume-relocate-btn="true"
                  onClick={() => onManageLocalBinding(resumeResolution.project)}
                  className="pd-resume-cta inline-flex items-center gap-1.5 rounded-xl px-3.5 py-1.5 text-xs font-semibold transition-colors"
                >
                  <Settings2 className="h-3.5 w-3.5" />
                  重新定位目录
                </button>
              ) : (
                <button
                  type="button"
                  data-resume-open-btn="true"
                  onClick={onResumeWorkspace}
                  className="pd-resume-cta inline-flex items-center gap-1.5 rounded-xl px-3.5 py-1.5 text-xs font-semibold transition-colors"
                >
                  继续上次工作区
                  <ArrowRight className="h-3.5 w-3.5" />
                </button>
              )}
              {onDismissResume && (
                <button
                  type="button"
                  title="隐藏此卡片"
                  onClick={onDismissResume}
                  className="rounded-lg p-1 pd-resume-muted hover:bg-slate-200/50"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Filter & View Switcher Strip */}
      <div className="mx-auto flex w-full max-w-[1600px] flex-wrap items-center justify-between gap-3 px-6 pt-5 pb-3">
        <div className="flex flex-wrap items-center gap-1.5">
          {(
            [
              ['all', '全部项目'],
              ['paper', '学术论文'],
              ['grant', '基金申报'],
              ['report', '结题报告'],
              ['other', '其他'],
            ] as ['all' | ProjectCategory, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setCatFilter(key)}
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold transition-all ${
                catFilter === key
                  ? 'bg-slate-900 text-white shadow-xs'
                  : 'bg-white text-slate-600 border border-slate-200/80 hover:border-slate-300'
              }`}
            >
              <span>{label}</span>
              <span
                className={`rounded-full px-1.5 py-0 text-[10.5px] tabular-nums ${
                  catFilter === key ? 'bg-white/20 text-white' : 'bg-slate-100 text-slate-500'
                }`}
              >
                {countsByCat[key]}
              </span>
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowArchived((v) => !v)}
            className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors ${
              showArchived
                ? 'border-slate-400 bg-slate-200/70 text-slate-800'
                : 'border-slate-200 bg-white text-slate-500 hover:text-slate-800'
            }`}
          >
            <Archive className="h-3.5 w-3.5" />
            {showArchived ? '隐藏已归档' : '显示归档'}
          </button>

          <div className="flex items-center rounded-lg border border-slate-200 bg-white p-0.5 text-xs">
            <button
              type="button"
              onClick={() => setLayout('grid')}
              title="卡片视图"
              className={`rounded-md p-1.5 ${
                layout === 'grid' ? 'bg-slate-900 text-white' : 'text-slate-400 hover:text-slate-700'
              }`}
            >
              <LayoutGrid className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={() => setLayout('tree')}
              title="层级列表视图"
              className={`rounded-md p-1.5 ${
                layout === 'tree' ? 'bg-slate-900 text-white' : 'text-slate-400 hover:text-slate-700'
              }`}
            >
              <List className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Main Scrollable Projects List */}
      <main className="flex-1 overflow-y-auto px-6 pb-12">
        <div className="mx-auto w-full max-w-[1600px]">
          {/* Minimal First-Visit Tip Bar */}
          {!welcomeDismissed && (
            <div className="mb-4 mt-1 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200/80 bg-white px-4 py-2.5 text-xs text-slate-600">
              <div className="flex items-center gap-2 min-w-0">
                <BookOpen className="h-3.5 w-3.5 shrink-0 text-blue-600" />
                <span className="truncate">
                  支持 LaTeX、Word 与 Markdown，绑定本地文件夹即可直读与两两对比，全部数据仅存于本机。
                </span>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  type="button"
                  onClick={onOpenGuide}
                  className="font-medium text-blue-600 hover:text-blue-700"
                >
                  查看指南
                </button>
                <button
                  type="button"
                  onClick={dismissWelcome}
                  title="收起提示"
                  className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          )}

          {filtered.length === 0 ? (
            <div className="mt-12 flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white py-16 text-center">
              <p className="text-sm font-semibold text-slate-700">当前分类下还没有项目</p>
              <p className="mt-1 text-xs text-slate-400">
                新建一个论文、基金或结题项目，即可在内部按文档和版本层级管理所有修改记录
              </p>
              <button
                type="button"
                onClick={onNewProject}
                className="mt-4 inline-flex items-center gap-1.5 rounded-xl bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700"
              >
                <FolderPlus className="h-3.5 w-3.5" />
                新建第一个项目
              </button>
            </div>
          ) : layout === 'grid' ? (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-4 mt-2">
              {filtered.map((p) => {
                const cat = CATEGORY_META[p.category] || CATEGORY_META.paper;
                const st = STATUS_META[p.status] || STATUS_META.polishing;
                const isLocal = p.project_mode === 'local_folder';
                const primaryDoc = p.documents[0];

                return (
                  <div
                    key={p.id}
                    data-project-card={p.name}
                    data-project-mode={isLocal ? 'local_folder' : 'managed'}
                    className="group flex flex-col rounded-2xl border border-[#E6E8EE] bg-white p-4 shadow-[0_2px_12px_rgba(15,23,42,0.025)] hover:border-blue-300/80 hover:shadow-[0_6px_24px_rgba(15,23,42,0.06)] transition-all"
                  >
                    {/* Card Header */}
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <select
                          aria-label="项目分类"
                          value={p.category}
                          onChange={(e) =>
                            onUpdateProject(p.id, { category: e.target.value as ProjectCategory })
                          }
                          className={`rounded-md border px-2 py-0.5 text-[11px] font-semibold cursor-pointer focus:outline-none ${cat.badge}`}
                        >
                          {Object.entries(CATEGORY_META).map(([k, v]) => (
                            <option key={k} value={k}>
                              {v.label}
                            </option>
                          ))}
                        </select>
                        {isLocal && (
                          <span
                            data-local-badge="true"
                            className="inline-flex items-center gap-1 rounded-md border border-teal-200 bg-teal-50 px-2 py-0.5 text-[11px] font-semibold text-teal-700"
                          >
                            <FolderOpen className="h-3 w-3" />
                            本地绑定
                          </span>
                        )}
                        <select
                          value={p.status}
                          onChange={(e) =>
                            onUpdateProject(p.id, { status: e.target.value as ProjectStatus })
                          }
                          className={`rounded-md px-2 py-0.5 text-[11px] font-medium border-0 cursor-pointer focus:outline-none ${st.cls}`}
                        >
                          {Object.entries(STATUS_META).map(([k, v]) => (
                            <option key={k} value={k}>
                              {v.label}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div className="flex items-center gap-0.5 shrink-0">
                        <button
                          type="button"
                          data-edit-project-btn={p.id}
                          onClick={() =>
                            editingProjId === p.id ? cancelEditProject() : startEditProject(p)
                          }
                          title="编辑项目名称与简介"
                          className={`rounded-lg p-1.5 transition-colors ${
                            editingProjId === p.id
                              ? 'text-blue-600 bg-blue-50'
                              : 'text-slate-300 hover:text-blue-600 hover:bg-blue-50'
                          }`}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => onUpdateProject(p.id, { pinned: !p.pinned })}
                          title={p.pinned ? '取消置顶' : '置顶项目'}
                          className={`rounded-lg p-1.5 transition-colors ${
                            p.pinned
                              ? 'text-amber-500 bg-amber-50'
                              : 'text-slate-300 hover:text-slate-600 hover:bg-slate-100'
                          }`}
                        >
                          <Pin className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => (isLocal ? onManageLocalBinding(p) : onDeleteProject(p.id))}
                          title={isLocal ? '管理绑定 / 移除项目（不删除磁盘文件）' : '删除项目'}
                          className="rounded-lg p-1.5 text-slate-300 hover:text-rose-600 hover:bg-rose-50 opacity-0 group-hover:opacity-100 transition-opacity"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>

                    {/* Title & Desc (inline real-time editing) */}
                    {editingProjId === p.id ? (
                      <div
                        data-project-inline-editor={p.id}
                        className="mt-2.5 space-y-2 rounded-xl border border-blue-200/90 bg-blue-50/30 p-2.5"
                      >
                        <input
                          type="text"
                          autoFocus
                          data-edit-project-name="true"
                          value={editName}
                          onChange={(e) => setEditName(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
                              e.preventDefault();
                              void commitEditProject(p);
                            } else if (e.key === 'Escape') {
                              e.preventDefault();
                              cancelEditProject();
                            }
                          }}
                          placeholder="输入项目名称"
                          className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[14px] font-bold text-slate-900 focus:border-blue-500 focus:outline-none"
                        />
                        <textarea
                          rows={2}
                          data-edit-project-desc="true"
                          value={editDesc}
                          onChange={(e) => setEditDesc(e.target.value)}
                          onKeyDown={(e) => {
                            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                              e.preventDefault();
                              void commitEditProject(p);
                            } else if (e.key === 'Escape') {
                              e.preventDefault();
                              cancelEditProject();
                            }
                          }}
                          placeholder="添加项目简介或备注（可选）"
                          className="w-full resize-none rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[12px] text-slate-700 leading-relaxed focus:border-blue-500 focus:outline-none"
                        />
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[10.5px] text-slate-400">
                            Enter 保存 · Esc 取消
                          </span>
                          <div className="flex items-center gap-1.5">
                            <button
                              type="button"
                              onClick={cancelEditProject}
                              disabled={editSaving}
                              className="rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-600 hover:bg-slate-50"
                            >
                              取消
                            </button>
                            <button
                              type="button"
                              data-save-project-edit="true"
                              onClick={() => void commitEditProject(p)}
                              disabled={editSaving || !editName.trim()}
                              className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
                            >
                              <Check className="h-3 w-3" />
                              {editSaving ? '保存中...' : '保存'}
                            </button>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div
                        onClick={() => startEditProject(p)}
                        title="点击修改项目名称与简介"
                        className="mt-2.5 -mx-1.5 rounded-lg px-1.5 py-0.5 cursor-text hover:bg-slate-50/90 transition-colors"
                      >
                        <h3 className="text-[15px] font-bold text-slate-900 leading-snug line-clamp-1">
                          {p.name}
                        </h3>
                        <p className="mt-1 text-[11.5px] text-slate-400 line-clamp-2 min-h-[16px]">
                          {p.description || (isLocal ? '免上传直读本地文件夹，自由挑选两文件 Diff' : '点击下方文档即可阅读或比对版本')}
                        </p>
                      </div>
                    )}

                    {/* Body: Local Folder Binding Card vs Managed Documents List */}
                    <div className="mt-3.5 flex-1 space-y-1.5 border-t border-slate-100 pt-3">
                      {isLocal ? (
                        <div
                          data-open-local-project={p.name}
                          onClick={() => onOpenLocalProject(p.id)}
                          className={`group/doc flex flex-col gap-2 rounded-xl border px-3 py-2.5 cursor-pointer transition-all ${
                            p.local_status && p.local_status !== 'ok'
                              ? 'border-amber-200 bg-amber-50/50 hover:border-amber-400'
                              : 'border-teal-200/70 bg-teal-50/30 hover:border-blue-300 hover:bg-blue-50/40'
                          }`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2 min-w-0">
                              {p.local_status && p.local_status !== 'ok' ? (
                                <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600" />
                              ) : (
                                <FolderOpen className="h-4 w-4 shrink-0 text-teal-600 group-hover/doc:text-blue-600" />
                              )}
                              <div className="min-w-0">
                                <div className="text-[12.5px] font-semibold text-slate-800 truncate">
                                  {p.local_status === 'missing'
                                    ? '目录已失联 · 点击重新定位'
                                    : p.local_status === 'unreadable'
                                      ? '目录无读取权限 · 点击处理'
                                      : `已识别 ${p.local_doc_count ?? 0} 个受支持文稿`}
                                </div>
                                <div
                                  className="truncate font-mono text-[10.5px] text-slate-500"
                                  title={p.local_root_path || ''}
                                >
                                  {p.local_root_path || '未绑定路径'}
                                </div>
                              </div>
                            </div>
                            <ArrowRight className="h-3.5 w-3.5 shrink-0 text-slate-400 group-hover/doc:text-blue-600 group-hover/doc:translate-x-0.5 transition-all" />
                          </div>
                        </div>
                      ) : (
                        p.documents.map((doc) => (
                          <div
                            key={doc.id}
                            onClick={() => onOpenDocument(p.id, doc.id)}
                            className="group/doc flex items-center justify-between gap-2 rounded-xl border border-slate-100 bg-[#FAFBFC] px-3 py-2 cursor-pointer hover:border-blue-300 hover:bg-blue-50/40 transition-all"
                          >
                            <div className="flex items-center gap-2 min-w-0">
                              <FileText className="h-3.5 w-3.5 text-slate-400 group-hover/doc:text-blue-600 shrink-0" />
                              <div className="min-w-0">
                                <div className="flex items-center gap-1.5">
                                  <span className="truncate text-[12.5px] font-semibold text-slate-800">
                                    {doc.name}
                                  </span>
                                  {doc.milestone_count > 0 && (
                                    <Star className="h-3 w-3 fill-amber-400 text-amber-400 shrink-0" />
                                  )}
                                </div>
                                <div className="text-[10.5px] text-slate-400 tabular-nums">
                                  {DOC_TYPE_LABEL[doc.doc_type] || '文稿'} · {doc.version_count} 个版本
                                  {doc.latest_version ? ` · ${doc.latest_version.word_count} 词` : ''}
                                </div>
                              </div>
                            </div>

                            <div className="flex items-center gap-1 shrink-0">
                              {doc.version_count === 1 && (
                                <span className="rounded-md bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-600">
                                  阅读预览
                                </span>
                              )}
                              {p.documents.length > 1 && (
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    onDeleteDocument(p.id, doc.id);
                                  }}
                                  title="删除此文档"
                                  className="opacity-0 group-hover/doc:opacity-100 rounded p-1 text-slate-400 hover:text-rose-600"
                                >
                                  <Trash2 className="h-3 w-3" />
                                </button>
                              )}
                              <ArrowRight className="h-3.5 w-3.5 text-slate-300 group-hover/doc:text-blue-600 group-hover/doc:translate-x-0.5 transition-all" />
                            </div>
                          </div>
                        ))
                      )}
                    </div>

                    {/* Card Footer Actions */}
                    <div className="mt-3.5 flex items-center justify-between border-t border-slate-100 pt-2.5 text-[11px]">
                      <div className="flex items-center gap-1.5">
                        {isLocal ? (
                          <>
                            <button
                              type="button"
                              onClick={() => onOpenLocalProject(p.id)}
                              className="inline-flex items-center gap-1 rounded-lg bg-teal-50 px-2 py-1 font-semibold text-teal-700 hover:bg-teal-100"
                            >
                              <FolderOpen className="h-3 w-3" />
                              打开目录
                            </button>
                            <button
                              type="button"
                              data-manage-local-binding={p.name}
                              onClick={() => onManageLocalBinding(p)}
                              className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 font-medium text-slate-600 hover:bg-slate-50"
                            >
                              <Settings2 className="h-3 w-3" />
                              目录管理
                            </button>
                          </>
                        ) : (
                          <>
                            {primaryDoc && (
                              <button
                                type="button"
                                onClick={() => onUploadToDocument(p.id, primaryDoc.id)}
                                className="inline-flex items-center gap-1 rounded-lg bg-blue-50 px-2 py-1 font-semibold text-blue-700 hover:bg-blue-100"
                              >
                                <FilePlus2 className="h-3 w-3" />
                                导入新版
                              </button>
                            )}
                            <button
                              type="button"
                              onClick={() => onNewDocument(p.id)}
                              className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 font-medium text-slate-600 hover:bg-slate-50"
                            >
                              <Plus className="h-3 w-3" />
                              加文档
                            </button>
                          </>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={() => onOpenGlossary(p.id)}
                        title="管理项目共享的受保护术语"
                        className="inline-flex items-center gap-1 text-slate-400 hover:text-blue-600"
                      >
                        <ShieldCheck className="h-3.5 w-3.5" />
                        术语 {p.protected_terms.length}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            /* Hierarchy Tree List View */
            <div className="mt-2 rounded-2xl border border-[#E6E8EE] bg-white divide-y divide-slate-100 overflow-hidden">
              {filtered.map((p) => {
                const cat = CATEGORY_META[p.category] || CATEGORY_META.paper;
                const st = STATUS_META[p.status] || STATUS_META.polishing;
                const isLocal = p.project_mode === 'local_folder';
                return (
                  <div key={p.id} className="p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2.5 min-w-0">
                        <span
                          className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-semibold ${cat.badge}`}
                        >
                          {cat.label}
                        </span>
                        {isLocal && (
                          <span className="inline-flex items-center gap-1 rounded-md border border-teal-200 bg-teal-50 px-2 py-0.5 text-[11px] font-semibold text-teal-700">
                            <FolderOpen className="h-3 w-3" />
                            本地绑定
                          </span>
                        )}
                        <span
                          onClick={() => startEditProject(p)}
                          title="点击编辑项目名称与简介"
                          className="text-[14px] font-bold text-slate-900 truncate cursor-text hover:text-blue-700"
                        >
                          {p.name}
                        </span>
                        <span className={`rounded-md px-2 py-0.5 text-[11px] font-medium ${st.cls}`}>
                          {st.label}
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            editingProjId === p.id ? cancelEditProject() : startEditProject(p)
                          }
                          title="编辑项目名称与简介"
                          className="rounded-md p-1 text-slate-400 hover:bg-blue-50 hover:text-blue-600"
                        >
                          <Pencil className="h-3 w-3" />
                        </button>
                      </div>
                      <div className="flex items-center gap-2 text-xs">
                        {isLocal ? (
                          <button
                            type="button"
                            onClick={() => onOpenLocalProject(p.id)}
                            className="inline-flex items-center gap-1 rounded-lg bg-teal-600 px-2.5 py-1 font-semibold text-white hover:bg-teal-700"
                          >
                            <FolderOpen className="h-3.5 w-3.5" />
                            进入本地目录
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => onNewDocument(p.id)}
                            className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1 text-slate-600 hover:bg-slate-50"
                          >
                            <Plus className="h-3.5 w-3.5" />
                            添加文档
                          </button>
                        )}
                      </div>
                    </div>
                    {editingProjId === p.id ? (
                      <div className="mt-2.5 space-y-2 rounded-xl border border-blue-200/90 bg-blue-50/30 p-2.5 max-w-xl">
                        <input
                          type="text"
                          autoFocus
                          value={editName}
                          onChange={(e) => setEditName(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
                              e.preventDefault();
                              void commitEditProject(p);
                            } else if (e.key === 'Escape') {
                              e.preventDefault();
                              cancelEditProject();
                            }
                          }}
                          placeholder="输入项目名称"
                          className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[13px] font-bold text-slate-900 focus:border-blue-500 focus:outline-none"
                        />
                        <textarea
                          rows={2}
                          value={editDesc}
                          onChange={(e) => setEditDesc(e.target.value)}
                          onKeyDown={(e) => {
                            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                              e.preventDefault();
                              void commitEditProject(p);
                            } else if (e.key === 'Escape') {
                              e.preventDefault();
                              cancelEditProject();
                            }
                          }}
                          placeholder="添加项目简介或备注（可选）"
                          className="w-full resize-none rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-700 focus:border-blue-500 focus:outline-none"
                        />
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            type="button"
                            onClick={cancelEditProject}
                            disabled={editSaving}
                            className="rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-600 hover:bg-slate-50"
                          >
                            取消
                          </button>
                          <button
                            type="button"
                            onClick={() => void commitEditProject(p)}
                            disabled={editSaving || !editName.trim()}
                            className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
                          >
                            <Check className="h-3 w-3" />
                            {editSaving ? '保存中...' : '保存'}
                          </button>
                        </div>
                      </div>
                    ) : p.description ? (
                      <p
                        onClick={() => startEditProject(p)}
                        className="mt-1 ml-1 text-xs text-slate-400 cursor-text hover:text-slate-600"
                      >
                        {p.description}
                      </p>
                    ) : null}
                    {isLocal ? (
                      <div
                        onClick={() => onOpenLocalProject(p.id)}
                        className="mt-2 ml-4 flex items-center justify-between rounded-xl border border-teal-100 bg-teal-50/30 px-3 py-2 text-xs cursor-pointer hover:bg-blue-50/40"
                      >
                        <span className="font-mono text-slate-600 truncate">{p.local_root_path}</span>
                        <span className="shrink-0 text-teal-700 font-semibold">
                          {p.local_doc_count ?? 0} 个文稿 →
                        </span>
                      </div>
                    ) : (
                      <div className="mt-2.5 ml-4 pl-3 border-l-2 border-slate-100 space-y-1.5">
                        {p.documents.map((doc) => (
                          <div
                            key={doc.id}
                            onClick={() => onOpenDocument(p.id, doc.id)}
                            className="flex items-center justify-between rounded-xl px-3 py-2 hover:bg-blue-50/50 cursor-pointer transition-colors"
                          >
                            <div className="flex items-center gap-2.5">
                              <FileText className="h-4 w-4 text-slate-400" />
                              <span className="text-[13px] font-semibold text-slate-800">{doc.name}</span>
                              <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10.5px] text-slate-500">
                                {doc.version_count} 版
                              </span>
                              {doc.latest_version && (
                                <span className="text-[11.5px] text-slate-400">
                                  最新：{doc.latest_version.label} ({doc.latest_version.word_count} 词)
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-2">
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  onUploadToDocument(p.id, doc.id);
                                }}
                                className="rounded-lg bg-blue-50 px-2 py-1 text-[11px] font-semibold text-blue-700 hover:bg-blue-100"
                              >
                                + 导入新版
                              </button>
                              <ArrowRight className="h-4 w-4 text-slate-300" />
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </main>
    </div>
  );
};
