/**
 * @file OverlayDrawers.tsx
 * @description On-demand slide-over drawers for Studio workspace:
 * - Left Drawer (`⌘1`): Three-tier Project / Document / Version navigation tree with milestone (`★`)
 *   presets and version management actions.
 * - Right Drawer (`⌘2`): Single-Document Self-Audit & Multi-Version 4-Dimension Fact-Conservation
 *   Audit inspector with one-click alert acknowledgement ("✓ 已核对无误") and AI cliche breakdown.
 */

import React, { useState } from 'react';
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  FilePlus2,
  FileText,
  FolderPlus,
  History,
  Home,
  Pencil,
  Plus,
  ShieldAlert,
  Sparkles,
  Star,
  Trash2,
  TrendingDown,
  X,
  Zap,
} from 'lucide-react';
import type {
  ComparisonResult,
  Project,
  SingleDocPreview,
  VersionSummary,
} from '../types';
import { CATEGORY_META } from './ProjectsHome';
import { BrandAppIcon } from './BrandMark';

const TAG_STYLE: Record<string, string> = {
  AI初稿: 'bg-violet-50 text-violet-700 border-violet-200/70',
  AI润色: 'bg-sky-50 text-sky-700 border-sky-200/70',
  去AI味: 'bg-emerald-50 text-emerald-700 border-emerald-200/70',
  导师批注: 'bg-amber-50 text-amber-700 border-amber-200/70',
  返修: 'bg-rose-50 text-rose-700 border-rose-200/70',
  人工修复: 'bg-blue-50 text-blue-700 border-blue-200/70',
  手改: 'bg-slate-100 text-slate-700 border-slate-200',
};

/* ============================================================================
 * LEFT OVERLAY DRAWER (⌘1): 3-Level Collapsible Hierarchy Tree
 * Project -> Document -> Version Timeline (with Milestones & 3 Presets!)
 * ========================================================================== */
interface ProjectDrawerProps {
  open: boolean;
  onClose: () => void;
  projects: Project[];
  activeProjectId: number | null;
  activeDocumentId: number | null;
  versions: VersionSummary[];
  oldVersionId: number | null;
  newVersionId: number | null;
  readVersionId?: number | null;
  isReadMode?: boolean;
  isQuickMode: boolean;
  onGoHome: () => void;
  onSelectDocument: (projectId: number, documentId: number) => void;
  onDeleteProject: (id: number) => void;
  onDeleteDocument: (projectId: number, documentId: number) => void;
  onOpenNewProject: () => void;
  onOpenNewDocument: (projectId: number) => void;
  onOpenUploadVersion: () => void;
  onOpenQuickCompare: () => void;
  onOpenGuide?: () => void;
  onSelectVersionPair: (oldId: number, newId: number) => void;
  onReadVersion?: (versionId: number) => void;
  onToggleMilestone: (version: VersionSummary) => void;
  onEditVersion: (version: VersionSummary) => void;
  onDeleteVersion: (versionId: number) => void;
}

export const ProjectDrawer: React.FC<ProjectDrawerProps> = ({
  open,
  onClose,
  projects,
  activeProjectId,
  activeDocumentId,
  versions,
  oldVersionId,
  newVersionId,
  readVersionId,
  isReadMode,
  isQuickMode,
  onGoHome,
  onSelectDocument,
  onDeleteProject,
  onDeleteDocument,
  onOpenNewProject,
  onOpenNewDocument,
  onOpenUploadVersion,
  onOpenQuickCompare,
  onOpenGuide,
  onSelectVersionPair,
  onReadVersion,
  onToggleMilestone,
  onEditVersion,
  onDeleteVersion,
}) => {
  const [expandedProjects, setExpandedProjects] = useState<Record<number, boolean>>({});

  if (!open) return null;

  const latestVer = versions[versions.length - 1];
  const prevVer = versions.length >= 2 ? versions[versions.length - 2] : null;
  const firstVer = versions.length >= 2 ? versions[0] : null;
  const latestMilestone = [...versions]
    .reverse()
    .find((v) => v.is_milestone && latestVer && v.id !== latestVer.id);

  const visibleProjects = projects.filter((p) => p.status !== 'archived' || p.id === activeProjectId);

  return (
    <div className="fixed inset-0 z-40 flex">
      <div className="fixed inset-0 bg-slate-900/15 backdrop-blur-[1px]" onClick={onClose} />
      <aside className="relative z-10 flex h-full w-[356px] max-w-[90vw] flex-col border-r border-slate-200 bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3.5">
          <div className="flex items-center gap-2">
            <BrandAppIcon size={28} />
            <div>
              <div className="text-[13.5px] font-bold text-slate-900 leading-none">
                工作区导航
              </div>
              <div className="mt-1 text-[10.5px] text-slate-400 leading-none">
                项目 · 文档 · 版本链（⌘1 收起）
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Top quick buttons: Home + Quick Compare */}
        <div className="grid grid-cols-2 gap-2 px-4 pt-3 pb-2">
          <button
            type="button"
            onClick={() => {
              onClose();
              onGoHome();
            }}
            className="flex items-center justify-center gap-1.5 rounded-xl border border-slate-200 bg-[#FAFBFC] px-2.5 py-2 text-xs font-semibold text-slate-700 hover:border-blue-300 hover:bg-blue-50/40"
          >
            <Home className="h-3.5 w-3.5 text-blue-600" />
            全部项目大厅
          </button>
          <button
            type="button"
            onClick={() => {
              onClose();
              onOpenQuickCompare();
            }}
            className={`flex items-center justify-center gap-1.5 rounded-xl border px-2.5 py-2 text-xs font-semibold transition-all ${
              isQuickMode
                ? 'border-blue-600 bg-blue-600 text-white'
                : 'border-blue-200 bg-blue-50/70 text-blue-700 hover:bg-blue-100/80'
            }`}
          >
            <Zap className="h-3.5 w-3.5" />
            快速对比
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-5">
          {/* 3-Level Collapsible Tree: Projects -> Documents */}
          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                项目与文档 ({visibleProjects.length})
              </span>
              <button
                type="button"
                onClick={() => {
                  onClose();
                  onOpenNewProject();
                }}
                className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11.5px] font-semibold text-blue-600 hover:bg-blue-50"
              >
                <FolderPlus className="h-3.5 w-3.5" />
                新建项目
              </button>
            </div>

            <div className="space-y-1.5">
              {visibleProjects.map((p) => {
                const isProjActive = !isQuickMode && p.id === activeProjectId;
                const isOpen = expandedProjects[p.id] ?? isProjActive;
                const cat = CATEGORY_META[p.category] || CATEGORY_META.paper;

                return (
                  <div
                    key={p.id}
                    className={`rounded-xl border transition-all ${
                      isProjActive ? 'border-blue-200/90 bg-blue-50/20' : 'border-slate-200/70 bg-white'
                    }`}
                  >
                    <div
                      onClick={() =>
                        setExpandedProjects((prev) => ({ ...prev, [p.id]: !isOpen }))
                      }
                      className="group flex items-center justify-between gap-1.5 px-2.5 py-2 cursor-pointer"
                    >
                      <div className="flex items-center gap-1.5 min-w-0 flex-1">
                        <ChevronRight
                          className={`h-3.5 w-3.5 shrink-0 text-slate-400 transition-transform ${
                            isOpen ? 'rotate-90 text-blue-600' : ''
                          }`}
                        />
                        <span className={`h-2 w-2 rounded-full shrink-0 ${cat.dot}`} title={cat.label} />
                        <span className="truncate text-[12.5px] font-bold text-slate-800">
                          {p.name}
                        </span>
                      </div>
                      <div className="flex items-center gap-0.5 shrink-0">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onClose();
                            onOpenNewDocument(p.id);
                          }}
                          title="在此项目下添加新文档（如 SI / 审稿回复）"
                          className="opacity-0 group-hover:opacity-100 rounded p-1 text-slate-400 hover:bg-blue-50 hover:text-blue-600"
                        >
                          <Plus className="h-3.5 w-3.5" />
                        </button>
                        {projects.length > 1 && (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              onDeleteProject(p.id);
                            }}
                            title="删除项目"
                            className="opacity-0 group-hover:opacity-100 rounded p-1 text-slate-400 hover:text-rose-600"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Nested Documents */}
                    {isOpen && (
                      <div className="px-2 pb-2 pt-0.5 space-y-1">
                        {p.documents.map((doc) => {
                          const isDocActive = !isQuickMode && doc.id === activeDocumentId;
                          return (
                            <div
                              key={doc.id}
                              onClick={() => onSelectDocument(p.id, doc.id)}
                              className={`group/d flex items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 cursor-pointer text-[12px] transition-colors ${
                                isDocActive
                                  ? 'bg-blue-600 text-white font-semibold shadow-xs'
                                  : 'text-slate-600 hover:bg-slate-100'
                              }`}
                            >
                              <div className="flex items-center gap-2 min-w-0">
                                <FileText className="h-3.5 w-3.5 shrink-0 opacity-80" />
                                <span className="truncate">{doc.name}</span>
                              </div>
                              <div className="flex items-center gap-1 shrink-0">
                                <span
                                  className={`rounded px-1.5 py-0 text-[10px] tabular-nums ${
                                    isDocActive
                                      ? 'bg-white/20 text-white'
                                      : 'bg-slate-100 text-slate-500'
                                  }`}
                                >
                                  {doc.version_count}版
                                </span>
                                {p.documents.length > 1 && (
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onDeleteDocument(p.id, doc.id);
                                    }}
                                    title="删除文档"
                                    className={`opacity-0 group-hover/d:opacity-100 rounded p-0.5 ${
                                      isDocActive
                                        ? 'text-white/70 hover:text-white'
                                        : 'text-slate-400 hover:text-rose-600'
                                    }`}
                                  >
                                    <Trash2 className="h-3 w-3" />
                                  </button>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Current Document Version Timeline */}
          {!isQuickMode && activeDocumentId && (
            <div>
              <div className="mb-2 flex items-center justify-between">
                <span className="inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  <History className="h-3 w-3" />
                  当前文档版本链 ({versions.length})
                </span>
                <button
                  type="button"
                  onClick={() => {
                    onClose();
                    onOpenUploadVersion();
                  }}
                  className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11.5px] font-semibold text-blue-600 hover:bg-blue-50"
                >
                  <FilePlus2 className="h-3.5 w-3.5" />
                  导入新版
                </button>
              </div>

              {/* 3 Quick Comparison Presets */}
              {versions.length >= 2 && latestVer && prevVer && firstVer && (
                <div className="mb-2.5 flex flex-wrap gap-1.5">
                  <button
                    type="button"
                    onClick={() => {
                      onSelectVersionPair(prevVer.id, latestVer.id);
                      onClose();
                    }}
                    className="rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-medium text-slate-700 hover:border-blue-300 hover:bg-blue-50/50"
                  >
                    最新 vs 上一版
                  </button>
                  {latestMilestone && (
                    <button
                      type="button"
                      onClick={() => {
                        onSelectVersionPair(latestMilestone.id, latestVer.id);
                        onClose();
                      }}
                      className="rounded-lg border border-amber-200 bg-amber-50/60 px-2 py-1 text-[11px] font-medium text-amber-800 hover:bg-amber-100/70"
                    >
                      最新 vs ★里程碑
                    </button>
                  )}
                  {versions.length >= 3 && (
                    <button
                      type="button"
                      onClick={() => {
                        onSelectVersionPair(firstVer.id, latestVer.id);
                        onClose();
                      }}
                      className="rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-medium text-slate-700 hover:border-blue-300 hover:bg-blue-50/50"
                    >
                      最新 vs 初稿 v1
                    </button>
                  )}
                </div>
              )}

              <div className="space-y-1.5">
                {versions.map((v, idx) => {
                  const isOld = !isReadMode && v.id === oldVersionId;
                  const isNew = !isReadMode && v.id === newVersionId;
                  const isReading = Boolean(isReadMode && v.id === readVersionId);
                  const prevW = idx > 0 ? versions[idx - 1].word_count : null;
                  const diffW = prevW !== null ? v.word_count - prevW : null;
                  const tagCls = TAG_STYLE[v.source_tag] || TAG_STYLE['手改'];

                  return (
                    <div
                      key={v.id}
                      onClick={() => {
                        if (versions.length === 1 && onReadVersion) {
                          onReadVersion(v.id);
                        } else if (idx > 0) {
                          onSelectVersionPair(versions[idx - 1].id, v.id);
                        } else if (versions.length > 1) {
                          onSelectVersionPair(v.id, versions[1].id);
                        }
                        onClose();
                      }}
                      className={`group rounded-xl border px-3 py-2 cursor-pointer transition-all ${
                        isReading
                          ? 'border-blue-300 bg-blue-50/45'
                          : isNew
                            ? 'border-emerald-300 bg-emerald-50/40'
                            : isOld
                              ? 'border-rose-300 bg-rose-50/35'
                              : 'border-slate-200/80 bg-white hover:border-slate-300'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-1.5">
                        <div className="flex items-center gap-1.5 min-w-0">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              onToggleMilestone(v);
                            }}
                            title={v.is_milestone ? '取消星标里程碑' : '设为星标里程碑（如投稿版）'}
                            className="shrink-0"
                          >
                            <Star
                              className={`h-3.5 w-3.5 transition-colors ${
                                v.is_milestone
                                  ? 'fill-amber-400 text-amber-400'
                                  : 'text-slate-300 hover:text-amber-400'
                              }`}
                            />
                          </button>
                          <span className="truncate text-[12px] font-semibold text-slate-800">
                            {v.label}
                          </span>
                        </div>
                        <div className="flex items-center gap-1 shrink-0">
                          {isReading && (
                            <span className="rounded bg-blue-100 px-1.5 py-0 text-[10px] font-bold text-blue-700">
                              阅读中
                            </span>
                          )}
                          {isOld && (
                            <span className="rounded bg-rose-100 px-1.5 py-0 text-[10px] font-bold text-rose-700">
                              旧
                            </span>
                          )}
                          {isNew && (
                            <span className="rounded bg-emerald-100 px-1.5 py-0 text-[10px] font-bold text-emerald-700">
                              新
                            </span>
                          )}
                          {onReadVersion && (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                onReadVersion(v.id);
                                onClose();
                              }}
                              title="单独阅读此版本"
                              className="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-blue-600 p-0.5"
                            >
                              <BookOpen className="h-3 w-3" />
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              onEditVersion(v);
                            }}
                            title="重命名或编辑备注"
                            className="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-blue-600 p-0.5"
                          >
                            <Pencil className="h-3 w-3" />
                          </button>
                          {versions.length > 1 && (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                onDeleteVersion(v.id);
                              }}
                              title="删除版本"
                              className="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-rose-600 p-0.5"
                            >
                              <Trash2 className="h-3 w-3" />
                            </button>
                          )}
                        </div>
                      </div>
                      <div className="mt-1.5 flex items-center justify-between text-[10.5px] text-slate-500">
                        <span className={`rounded border px-1.5 py-0 text-[10px] font-medium ${tagCls}`}>
                          {v.source_tag}
                        </span>
                        <span className="tabular-nums">
                          {v.word_count} 词
                          {diffW !== null && diffW !== 0 && (
                            <span className={diffW < 0 ? 'text-blue-600 ml-1' : 'text-emerald-600 ml-1'}>
                              ({diffW > 0 ? `+${diffW}` : diffW})
                            </span>
                          )}
                          {' · '}AI词 {v.ai_ism_count}
                        </span>
                      </div>
                      {v.notes && (
                        <div className="mt-1 truncate text-[10.5px] text-slate-400" title={v.notes}>
                          {v.notes}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
        {onOpenGuide && (
          <div className="border-t border-slate-100 px-4 py-2.5 bg-[#FAFBFC]">
            <button
              type="button"
              onClick={() => {
                onClose();
                onOpenGuide();
              }}
              className="flex w-full items-center justify-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:border-blue-300 hover:bg-blue-50/40 hover:text-blue-700 transition-colors"
            >
              <BookOpen className="h-3.5 w-3.5 text-blue-600" />
              产品功能介绍与使用指南
            </button>
          </div>
        )}
      </aside>
    </div>
  );
};

/* ============================================================================
 * RIGHT OVERLAY DRAWER (⌘2): Evaluation, Guardrail Alerts & AI-ism Telemetry
 * ========================================================================== */
interface EvaluationDrawerProps {
  open: boolean;
  onClose: () => void;
  comparison: ComparisonResult;
  versions: VersionSummary[];
  onJumpToAlertParagraph: (paraIndex: number) => void;
  onToggleAlertAck: (alertId: string) => void;
}

export const EvaluationDrawer: React.FC<EvaluationDrawerProps> = ({
  open,
  onClose,
  comparison,
  versions,
  onJumpToAlertParagraph,
  onToggleAlertAck,
}) => {
  const [tab, setTab] = useState<'audit' | 'style'>('audit');

  if (!open) return null;

  const { evaluation, alerts, summary } = comparison;
  const activeAlerts = alerts.filter((a) => !a.acked);
  const ackedAlerts = alerts.filter((a) => a.acked);
  const healthColor =
    evaluation.overall_health >= 80
      ? 'text-emerald-600'
      : evaluation.overall_health >= 60
        ? 'text-amber-600'
        : 'text-rose-600';

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="fixed inset-0 bg-slate-900/15 backdrop-blur-[1px]" onClick={onClose} />
      <aside className="relative z-10 flex h-full w-[388px] max-w-[92vw] flex-col border-l border-slate-200 bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3.5">
          <div>
            <div className="text-[14px] font-bold text-slate-900 leading-none">
              论文修改评判与事实审计
            </div>
            <div className="mt-1 text-[10.5px] text-slate-400 leading-none">
              纯本地算法 · 快捷键 ⌘2 随时收起
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="grid grid-cols-2 border-b border-slate-100 bg-[#FAFBFC] p-1.5 gap-1">
          <button
            type="button"
            onClick={() => setTab('audit')}
            className={`flex items-center justify-center gap-1.5 rounded-lg py-1.5 text-xs font-semibold transition-all ${
              tab === 'audit'
                ? 'bg-white text-slate-900 shadow-xs ring-1 ring-slate-200/80'
                : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            事实审计与得分
            {activeAlerts.length > 0 && (
              <span
                className={`rounded-full px-1.5 py-0 text-[10px] font-bold ${
                  summary.alert_counts.high > 0
                    ? 'bg-rose-100 text-rose-700'
                    : 'bg-amber-100 text-amber-700'
                }`}
              >
                {activeAlerts.length}
              </span>
            )}
          </button>
          <button
            type="button"
            onClick={() => setTab('style')}
            className={`flex items-center justify-center gap-1.5 rounded-lg py-1.5 text-xs font-semibold transition-all ${
              tab === 'style'
                ? 'bg-white text-slate-900 shadow-xs ring-1 ring-slate-200/80'
                : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            风格与去 AI 味
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-5">
          {tab === 'audit' ? (
            <>
              <div className="rounded-2xl border border-slate-200/80 bg-[#FAFBFC] p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                      综合改稿健康度
                    </div>
                    <div className="mt-0.5 text-xs text-slate-500">
                      事实核查 45% · 表达自然 30% · 可读性 25%
                    </div>
                  </div>
                  <div className={`text-3xl font-bold tabular-nums ${healthColor}`}>
                    {evaluation.overall_health}
                    <span className="text-xs font-normal text-slate-400">/100</span>
                  </div>
                </div>
                <div className="mt-3.5 space-y-2.5">
                  <ScoreBar label="事实核查（数值 / 引文 / 公式 / 术语）" value={evaluation.scores.fact_safety} />
                  <ScoreBar label="表达自然度" value={evaluation.scores.ai_naturalness} />
                  <ScoreBar label="可读与简洁度" value={evaluation.scores.readability} />
                </div>
              </div>

              <div>
                <div className="mb-2.5 flex items-center justify-between text-xs font-semibold text-slate-800">
                  <span className="inline-flex items-center gap-1.5">
                    <ShieldAlert className="h-4 w-4 text-rose-500" />
                    待处理事实告警 ({activeAlerts.length})
                  </span>
                  {ackedAlerts.length > 0 && (
                    <span className="text-[11px] font-normal text-emerald-600">
                      已核对 {ackedAlerts.length} 项
                    </span>
                  )}
                </div>

                {activeAlerts.length === 0 ? (
                  <div className="flex items-center gap-2.5 rounded-xl border border-emerald-200 bg-emerald-50/60 p-3.5 text-xs text-emerald-800">
                    <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
                    <div>
                      <div className="font-semibold">全部检查通过</div>
                      <div className="mt-0.5 text-[11px] text-emerald-700/80">
                        {ackedAlerts.length > 0
                          ? `已有 ${ackedAlerts.length} 项告警标记为「已核对无误」。`
                          : '未发现引文丢失、图表编号缺失、数值变动或受保护术语替换。'}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {activeAlerts.map((a) => {
                      const cls =
                        a.severity === 'high'
                          ? 'border-rose-200 bg-rose-50/55 hover:bg-rose-50'
                          : a.severity === 'medium'
                            ? 'border-amber-200 bg-amber-50/55 hover:bg-amber-50'
                            : 'border-sky-200 bg-sky-50/55 hover:bg-sky-50';
                      const badgeCls =
                        a.severity === 'high'
                          ? 'bg-rose-600 text-white'
                          : a.severity === 'medium'
                            ? 'bg-amber-500 text-white'
                            : 'bg-sky-600 text-white';

                      return (
                        <div
                          key={a.alert_id}
                          onClick={() => {
                            onClose();
                            onJumpToAlertParagraph(a.para_index);
                          }}
                          className={`w-full rounded-xl border p-3 text-left transition-colors cursor-pointer ${cls}`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-slate-900">
                              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                              {a.title}
                            </span>
                            <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${badgeCls}`}>
                              {a.severity === 'high' ? '高风险' : a.severity === 'medium' ? '需核对' : '提示'}
                            </span>
                          </div>
                          <p className="mt-1.5 text-[11.5px] leading-relaxed text-slate-600">
                            {a.detail}
                          </p>
                          <div className="mt-2 flex items-center justify-between text-[10.5px]">
                            <span className="font-medium text-blue-600">章节：{a.section} · 定位 →</span>
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                onToggleAlertAck(a.alert_id);
                              }}
                              className="rounded-md border border-emerald-200 bg-white px-2 py-0.5 font-semibold text-emerald-700 hover:bg-emerald-50"
                            >
                              ✓ 已核对无误
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}

                {ackedAlerts.length > 0 && (
                  <div className="mt-3 space-y-1.5">
                    <div className="text-[11px] font-medium text-slate-400">
                      已核对无误 ({ackedAlerts.length})
                    </div>
                    {ackedAlerts.map((a) => (
                      <div
                        key={a.alert_id}
                        className="flex items-center justify-between gap-2 rounded-lg border border-slate-100 bg-slate-50/70 px-3 py-2 text-[11px] text-slate-500"
                      >
                        <span className="truncate line-through">
                          [{a.section}] {a.title}：{a.detail}
                        </span>
                        <button
                          type="button"
                          onClick={() => onToggleAlertAck(a.alert_id)}
                          className="shrink-0 text-blue-600 hover:underline font-medium"
                        >
                          恢复
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {versions.length >= 2 && (
                <div className="rounded-xl border border-slate-200/80 p-3.5">
                  <div className="mb-2 text-xs font-semibold text-slate-800">
                    多版本演进趋势 ({versions.length} 版)
                  </div>
                  <VersionSparkline versions={versions} />
                </div>
              )}
            </>
          ) : (
            <>
              <div className="rounded-2xl border border-slate-200/80 bg-[#FAFBFC] p-4">
                <div className="flex items-center justify-between">
                  <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-800">
                    <Sparkles className="h-4 w-4 text-emerald-600" />
                    AI 高频浮夸词体检
                  </span>
                  <span
                    className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-bold ${
                      evaluation.ai_ism_diff.delta <= 0
                        ? 'bg-emerald-100 text-emerald-700'
                        : 'bg-rose-100 text-rose-700'
                    }`}
                  >
                    <TrendingDown className="h-3 w-3" />
                    {evaluation.ai_ism_diff.old_count} → {evaluation.ai_ism_diff.new_count} (
                    {evaluation.ai_ism_diff.delta > 0
                      ? `+${evaluation.ai_ism_diff.delta}`
                      : evaluation.ai_ism_diff.delta}
                    )
                  </span>
                </div>

                {evaluation.ai_ism_diff.removed.length > 0 && (
                  <div className="mt-3">
                    <div className="mb-1.5 text-[11px] font-medium text-emerald-700">
                      本轮已消除的 AI 套话词：
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {evaluation.ai_ism_diff.removed.map((item) => (
                        <span
                          key={item.word}
                          className="rounded-md bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-800 border border-emerald-200/80 line-through decoration-emerald-500/60"
                        >
                          {item.word}
                          {item.count > 1 ? ` ×${item.count}` : ''}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {evaluation.ai_ism_diff.added.length > 0 && (
                  <div className="mt-3">
                    <div className="mb-1.5 text-[11px] font-medium text-rose-700">
                      本轮新引入的 AI 套话词（建议精简）：
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {evaluation.ai_ism_diff.added.map((item) => (
                        <span
                          key={item.word}
                          className="rounded-md bg-rose-50 px-2 py-0.5 text-[11px] font-medium text-rose-800 border border-rose-200/80"
                        >
                          +{item.word}
                          {item.count > 1 ? ` ×${item.count}` : ''}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="rounded-2xl border border-slate-200/80 overflow-hidden">
                <div className="bg-[#FAFBFC] px-4 py-2.5 text-xs font-semibold text-slate-700 border-b border-slate-100">
                  学术写作风格指标（旧版 → 新版）
                </div>
                <div className="divide-y divide-slate-100 text-[12px]">
                  <MetricRow label="总词数" oldVal={`${evaluation.old_style.word_count}`} newVal={`${evaluation.new_style.word_count}`} />
                  <MetricRow label="句子数" oldVal={`${evaluation.old_style.sentence_count}`} newVal={`${evaluation.new_style.sentence_count}`} />
                  <MetricRow label="平均句长（词/句）" oldVal={`${evaluation.old_style.avg_sentence_len}`} newVal={`${evaluation.new_style.avg_sentence_len}`} betterWhenLower />
                  <MetricRow label="超长句占比" oldVal={`${evaluation.old_style.long_sentence_ratio}%`} newVal={`${evaluation.new_style.long_sentence_ratio}%`} betterWhenLower />
                  {evaluation.new_style.flesch_kincaid_grade !== null && (
                    <MetricRow label="Flesch-Kincaid 年级" oldVal={`${evaluation.old_style.flesch_kincaid_grade ?? '-'}`} newVal={`${evaluation.new_style.flesch_kincaid_grade}`} />
                  )}
                  <MetricRow label="词汇多样性 (TTR)" oldVal={`${evaluation.old_style.lexical_diversity}%`} newVal={`${evaluation.new_style.lexical_diversity}%`} />
                  <MetricRow label="被动语态估计" oldVal={`${evaluation.old_style.passive_voice_ratio}%`} newVal={`${evaluation.new_style.passive_voice_ratio}%`} />
                  <MetricRow label="AI 套话密度 (每千词)" oldVal={`${evaluation.old_style.ai_ism_density}`} newVal={`${evaluation.new_style.ai_ism_density}`} betterWhenLower />
                  <MetricRow
                    label="谨慎词 / 强断言词"
                    oldVal={`${evaluation.old_style.hedge_count} / ${evaluation.old_style.booster_count}`}
                    newVal={`${evaluation.new_style.hedge_count} / ${evaluation.new_style.booster_count}`}
                  />
                </div>
              </div>
            </>
          )}
        </div>
      </aside>
    </div>
  );
};

const ScoreBar: React.FC<{ label: string; value: number }> = ({ label, value }) => {
  const barCls = value >= 80 ? 'bg-emerald-500' : value >= 60 ? 'bg-amber-500' : 'bg-rose-500';
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-[11.5px]">
        <span className="text-slate-600">{label}</span>
        <span className="font-semibold tabular-nums text-slate-800">{value}</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200/80">
        <div className={`h-full rounded-full transition-all ${barCls}`} style={{ width: `${value}%` }} />
      </div>
    </div>
  );
};

const MetricRow: React.FC<{
  label: string;
  oldVal: string;
  newVal: string;
  betterWhenLower?: boolean;
}> = ({ label, oldVal, newVal, betterWhenLower }) => {
  const nOld = parseFloat(oldVal);
  const nNew = parseFloat(newVal);
  let deltaCls = 'text-slate-800';
  if (!Number.isNaN(nOld) && !Number.isNaN(nNew) && nOld !== nNew && betterWhenLower) {
    deltaCls = nNew < nOld ? 'text-emerald-700 font-semibold' : 'text-amber-700 font-semibold';
  }
  return (
    <div className="flex items-center justify-between px-4 py-2">
      <span className="text-slate-600">{label}</span>
      <span className="tabular-nums">
        <span className="text-slate-400">{oldVal}</span>
        <span className="mx-1.5 text-slate-300">→</span>
        <span className={deltaCls}>{newVal}</span>
      </span>
    </div>
  );
};

const VersionSparkline: React.FC<{ versions: VersionSummary[] }> = ({ versions }) => {
  const W = 310;
  const H = 76;
  const padX = 16;
  const padY = 12;
  const words = versions.map((v) => v.word_count);
  const ais = versions.map((v) => v.ai_ism_count);
  const minW = Math.min(...words);
  const maxW = Math.max(...words, minW + 1);
  const maxAi = Math.max(...ais, 1);

  const ptsW = versions
    .map((v, i) => {
      const x = padX + (i / Math.max(1, versions.length - 1)) * (W - padX * 2);
      const y = H - padY - ((v.word_count - minW) / (maxW - minW)) * (H - padY * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  const ptsAi = versions
    .map((v, i) => {
      const x = padX + (i / Math.max(1, versions.length - 1)) * (W - padX * 2);
      const y = H - padY - (v.ai_ism_count / maxAi) * (H - padY * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-[78px] overflow-visible">
        <polyline fill="none" stroke="#2563EB" strokeWidth="2" points={ptsW} />
        <polyline fill="none" stroke="#10B981" strokeWidth="2" strokeDasharray="4 3" points={ptsAi} />
        {versions.map((v, i) => {
          const x = padX + (i / Math.max(1, versions.length - 1)) * (W - padX * 2);
          const yW = H - padY - ((v.word_count - minW) / (maxW - minW)) * (H - padY * 2);
          const yA = H - padY - (v.ai_ism_count / maxAi) * (H - padY * 2);
          return (
            <g key={v.id}>
              <circle cx={x} cy={yW} r="3.4" fill="#2563EB" />
              <circle cx={x} cy={yA} r="2.8" fill="#10B981" />
            </g>
          );
        })}
      </svg>
      <div className="mt-1 flex items-center justify-between text-[10.5px] text-slate-400">
        <span className="inline-flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-blue-600" /> 词数 ({words[0]}→{words[words.length - 1]})
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-emerald-500" /> AI 词 ({ais[0]}→{ais[ais.length - 1]})
        </span>
      </div>
    </div>
  );
};

/* ============================================================================
 * RIGHT OVERLAY DRAWER FOR READ MODE (⌘2): Single-Document Self-Audit Drawer
 * ========================================================================== */
interface SingleAuditDrawerProps {
  open: boolean;
  onClose: () => void;
  preview: SingleDocPreview;
  highlightAiIsms: boolean;
  onToggleHighlightAiIsms: () => void;
  onJumpToBlock: (blockIndex: number) => void;
  onFilterWord: (word: string) => void;
  onOpenLexicon: () => void;
}

export const SingleAuditDrawer: React.FC<SingleAuditDrawerProps> = ({
  open,
  onClose,
  preview,
  highlightAiIsms,
  onToggleHighlightAiIsms,
  onJumpToBlock,
  onFilterWord,
  onOpenLexicon,
}) => {
  if (!open) return null;

  const s = preview.summary;
  const st = preview.style;
  const scoreColor =
    preview.health_score >= 82
      ? 'text-emerald-600'
      : preview.health_score >= 65
        ? 'text-amber-600'
        : 'text-rose-600';

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="fixed inset-0 bg-slate-900/15 backdrop-blur-[1px]" onClick={onClose} />
      <aside className="relative z-10 flex h-full w-[400px] max-w-[92vw] flex-col border-l border-slate-200 bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5">
          <div>
            <div className="text-[14px] font-bold text-slate-900 leading-none">
              单稿体检
            </div>
            <div className="mt-1 text-[10.5px] text-slate-400 leading-none">
              {preview.version.label} · ⌘2 收起
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {/* Health Score + Structure Grid */}
          <div className="rounded-2xl border border-slate-200/80 bg-[#FAFBFC] p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  单稿文本健康度
                </div>
                <div className="mt-0.5 text-[11px] text-slate-500">
                  基于引文完整性、AI 腔密度与句式可读性
                </div>
              </div>
              <div className={`text-3xl font-bold tabular-nums ${scoreColor}`}>
                {preview.health_score}
              </div>
            </div>

            <div className="mt-3.5 grid grid-cols-3 gap-2 text-center">
              {[
                ['总词数', s.word_count],
                ['正文段', s.paragraph_count],
                ['插图', s.figure_count],
                ['表格', s.table_count],
                ['独立公式', s.math_count],
                ['独立引文', s.citation_count],
              ].map(([label, val]) => (
                <div key={String(label)} className="rounded-xl border border-slate-200/70 bg-white py-2">
                  <div className="text-[14px] font-bold text-slate-800 tabular-nums">{val}</div>
                  <div className="text-[10.5px] text-slate-400">{label}</div>
                </div>
              ))}
            </div>
          </div>

          {/* AI-ism Self-Check & Gentle Lavender Highlight Toggle */}
          <div className="rounded-2xl border border-violet-200/80 bg-violet-50/35 p-4 space-y-3">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-1.5">
                <Sparkles className="h-4 w-4 text-violet-600" />
                <span className="text-xs font-bold text-slate-800">
                  AI 腔自查（命中 {s.ai_ism_count} 次）
                </span>
              </div>
              <span className="text-[11px] font-medium text-violet-700 tabular-nums">
                {st.ai_ism_density} / 千词
              </span>
            </div>

            <div className="flex items-center justify-between rounded-xl border border-violet-200/70 bg-white px-3 py-2 text-xs">
              <span className="font-medium text-slate-700">在阅读正文中淡紫标出 AI 腔</span>
              <button
                type="button"
                onClick={onToggleHighlightAiIsms}
                className={`relative h-5 w-9 rounded-full transition-colors ${
                  highlightAiIsms ? 'bg-violet-600' : 'bg-slate-300'
                }`}
              >
                <span
                  className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${
                    highlightAiIsms ? 'left-[18px]' : 'left-0.5'
                  }`}
                />
              </button>
            </div>

            {preview.ai_ism_breakdown.length === 0 ? (
              <div className="flex items-center gap-1.5 text-xs text-emerald-700">
                <CheckCircle2 className="h-3.5 w-3.5" />
                未命中 AI 高频套话，行文自然！
              </div>
            ) : (
              <div>
                <div className="mb-1.5 flex items-center justify-between text-[11px] text-slate-500">
                  <span>点击任意词条可在正文快速筛选定位：</span>
                  <button
                    type="button"
                    onClick={() => {
                      onClose();
                      onOpenLexicon();
                    }}
                    className="font-semibold text-violet-700 hover:underline"
                  >
                    编辑词典
                  </button>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {preview.ai_ism_breakdown.map((item) => (
                    <button
                      key={item.word}
                      type="button"
                      onClick={() => {
                        onFilterWord(item.word);
                        onClose();
                      }}
                      className="inline-flex items-center gap-1 rounded-full border border-violet-200 bg-white px-2.5 py-0.5 text-[11.5px] font-medium text-violet-800 hover:bg-violet-100/70 transition-colors"
                    >
                      <span>{item.word}</span>
                      <span className="text-[10px] text-violet-500 tabular-nums">×{item.count}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Integrity Issues (.bib missing / broken \ref) */}
          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="inline-flex items-center gap-1.5 text-xs font-bold text-slate-800">
                <ShieldAlert className="h-4 w-4 text-rose-500" />
                引文与引用完整性 ({preview.issues.length})
              </span>
            </div>
            {preview.issues.length === 0 ? (
              <div className="flex items-center gap-2 rounded-xl border border-emerald-200/80 bg-emerald-50/50 px-3.5 py-2.5 text-xs text-emerald-800">
                <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
                未发现悬空 .bib 引文或断链交叉引用
              </div>
            ) : (
              <div className="space-y-2">
                {preview.issues.map((iss) => (
                  <button
                    key={iss.issue_id}
                    type="button"
                    onClick={() => {
                      onJumpToBlock(iss.block_index);
                      onClose();
                    }}
                    className={`w-full rounded-xl border p-3 text-left text-xs transition-colors ${
                      iss.severity === 'high'
                        ? 'border-rose-200 bg-rose-50/50 hover:bg-rose-50'
                        : 'border-amber-200 bg-amber-50/50 hover:bg-amber-50'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="inline-flex items-center gap-1 font-bold text-slate-800">
                        <AlertTriangle
                          className={`h-3.5 w-3.5 ${
                            iss.severity === 'high' ? 'text-rose-600' : 'text-amber-600'
                          }`}
                        />
                        {iss.title}
                      </span>
                      <span className="truncate text-[10.5px] text-slate-400 max-w-[120px]">
                        {iss.section}
                      </span>
                    </div>
                    <p className="mt-1 text-[11.5px] leading-relaxed text-slate-600">{iss.detail}</p>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Protected Terms Coverage */}
          {preview.term_coverage.length > 0 && (
            <div>
              <div className="mb-2 text-xs font-bold text-slate-800">
                项目受保护术语出现频次
              </div>
              <div className="flex flex-wrap gap-1.5">
                {preview.term_coverage.map((tc) => (
                  <button
                    key={tc.term}
                    type="button"
                    onClick={() => {
                      onFilterWord(tc.term);
                      onClose();
                    }}
                    className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${
                      tc.count > 0
                        ? 'border-blue-200 bg-blue-50/70 text-blue-700 hover:bg-blue-100'
                        : 'border-slate-200 bg-slate-50 text-slate-400'
                    }`}
                  >
                    <span>{tc.term}</span>
                    <span className="tabular-nums opacity-75">×{tc.count}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Style & Readability Reference */}
          <div className="rounded-2xl border border-slate-200/80 bg-white p-4">
            <div className="mb-2.5 text-xs font-bold text-slate-800">学术文风与句式参考</div>
            <div className="grid grid-cols-2 gap-y-2 gap-x-3 text-xs">
              <div className="flex justify-between">
                <span className="text-slate-400">平均句长</span>
                <strong className="text-slate-700 tabular-nums">{st.avg_sentence_len} 词</strong>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">超长句占比</span>
                <strong className="text-slate-700 tabular-nums">{st.long_sentence_ratio}%</strong>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">词汇多样性</span>
                <strong className="text-slate-700 tabular-nums">{st.lexical_diversity}%</strong>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">被动语态</span>
                <strong className="text-slate-700 tabular-nums">{st.passive_voice_ratio}%</strong>
              </div>
              {st.flesch_kincaid_grade !== null && (
                <div className="flex justify-between">
                  <span className="text-slate-400">FK 可读年级</span>
                  <strong className="text-slate-700 tabular-nums">{st.flesch_kincaid_grade}</strong>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-slate-400">谨慎 / 强断言</span>
                <strong className="text-slate-700 tabular-nums">
                  {st.hedge_count} / {st.booster_count}
                </strong>
              </div>
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
};
