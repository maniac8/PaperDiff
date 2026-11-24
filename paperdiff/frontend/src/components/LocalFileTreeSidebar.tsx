/**
 * @file LocalFileTreeSidebar.tsx
 * @description Collapsible left file-tree explorer for local-folder-bound projects (W2).
 * Supports recursive directory browsing, filename search, format filtering, D-07 auxiliary
 * resource toggle, manual refresh, strict D-04 pairwise Diff selection (max 2 files with
 * explicit 3rd-file intercept banner), and AC-18 missing/unreadable folder recovery actions.
 */

import React, { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  FileCode2,
  FileText,
  Folder,
  FolderOpen,
  GitCompareArrows,
  Image as ImageIcon,
  PanelLeftClose,
  RefreshCw,
  Search,
  Settings2,
  X,
} from 'lucide-react';
import type { LocalFormatFilter, LocalTreeNode, LocalTreeResponse, Project } from '../types';
import { filterLocalTree } from '../utils/localTree';

interface LocalFileTreeSidebarProps {
  project: Project;
  tree: LocalTreeResponse | null;
  loading: boolean;
  error: { code?: string; message: string } | null;
  includeAux: boolean;
  onToggleIncludeAux: (next: boolean) => void;
  activeRelPath: string | null;
  selectedPair: string[];
  pendingThirdRelPath: string | null;
  onSelectFile: (node: LocalTreeNode) => void;
  onTogglePickForDiff: (relPath: string) => void;
  onReplacePairSlot: (slot: 0 | 1, relPath: string) => void;
  onCancelPendingThird: () => void;
  onClearPair: () => void;
  onStartPairCompare: () => void;
  onRefresh: () => void;
  onOpenBindingSettings: () => void;
  onCloseSidebar: () => void;
}

const FMT_BADGE: Record<string, { label: string; cls: string }> = {
  latex: { label: 'TEX', cls: 'bg-violet-50 text-violet-700 border-violet-200/80' },
  docx: { label: 'DOCX', cls: 'bg-blue-50 text-blue-700 border-blue-200/80' },
  markdown: { label: 'MD', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200/80' },
  bib: { label: 'BIB', cls: 'bg-amber-50 text-amber-700 border-amber-200/80' },
  image: { label: 'IMG', cls: 'bg-slate-100 text-slate-600 border-slate-200' },
  pdf: { label: 'PDF', cls: 'bg-rose-50 text-rose-700 border-rose-200/80' },
};

export const LocalFileTreeSidebar: React.FC<LocalFileTreeSidebarProps> = ({
  project,
  tree,
  loading,
  error,
  includeAux,
  onToggleIncludeAux,
  activeRelPath,
  selectedPair,
  pendingThirdRelPath,
  onSelectFile,
  onTogglePickForDiff,
  onReplacePairSlot,
  onCancelPendingThird,
  onClearPair,
  onStartPairCompare,
  onRefresh,
  onOpenBindingSettings,
  onCloseSidebar,
}) => {
  const [query, setQuery] = useState('');
  const [formatFilter, setFormatFilter] = useState<LocalFormatFilter>('all');
  const [expandedDirs, setExpandedDirs] = useState<Record<string, boolean>>({});

  const filtered = useMemo(() => {
    if (!tree) return { nodes: [], autoExpandDirs: [] };
    return filterLocalTree(tree.nodes, query, formatFilter);
  }, [tree, query, formatFilter]);

  // Auto-expand top-level folders on initial load or matching ancestors during search
  useEffect(() => {
    if (!tree) return;
    setExpandedDirs((prev) => {
      const next = { ...prev };
      for (const n of tree.nodes) {
        if (n.node_type === 'dir' && next[n.rel_path] === undefined) {
          next[n.rel_path] = true;
        }
      }
      for (const dirPath of filtered.autoExpandDirs) {
        next[dirPath] = true;
      }
      return next;
    });
  }, [tree, filtered.autoExpandDirs]);

  const toggleDir = (relPath: string) => {
    setExpandedDirs((prev) => ({ ...prev, [relPath]: !prev[relPath] }));
  };

  const rootBasename = useMemo(() => {
    const p = (project.local_root_path || '').replace(/\/+$/, '');
    const idx = p.lastIndexOf('/');
    return idx >= 0 ? p.slice(idx + 1) : p || '本地目录';
  }, [project.local_root_path]);

  const renderNodes = (nodes: LocalTreeNode[], depth = 0): React.ReactNode =>
    nodes.map((node) => {
      if (node.node_type === 'dir') {
        const isOpen = Boolean(expandedDirs[node.rel_path]);
        return (
          <div key={node.rel_path}>
            <button
              type="button"
              onClick={() => toggleDir(node.rel_path)}
              style={{ paddingLeft: `${8 + depth * 14}px` }}
              className="flex w-full items-center gap-1.5 rounded-lg py-1.5 pr-2 text-left text-[12px] font-medium text-slate-700 hover:bg-slate-100/80 transition-colors"
            >
              {isOpen ? (
                <ChevronDown className="h-3.5 w-3.5 shrink-0 text-slate-400" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-400" />
              )}
              {isOpen ? (
                <FolderOpen className="h-3.5 w-3.5 shrink-0 text-amber-500" />
              ) : (
                <Folder className="h-3.5 w-3.5 shrink-0 text-amber-500" />
              )}
              <span className="truncate">{node.name}</span>
            </button>
            {isOpen && node.children && <div>{renderNodes(node.children, depth + 1)}</div>}
          </div>
        );
      }

      const isDoc = node.kind === 'doc';
      const isActive = activeRelPath === node.rel_path;
      const pairIdx = selectedPair.indexOf(node.rel_path);
      const badge = FMT_BADGE[node.format || ''] || {
        label: (node.ext || '').replace('.', '').toUpperCase() || 'FILE',
        cls: 'bg-slate-100 text-slate-500 border-slate-200',
      };

      return (
        <div
          key={node.rel_path}
          data-local-file={node.rel_path}
          data-local-kind={node.kind || 'doc'}
          style={{ paddingLeft: `${12 + depth * 14}px` }}
          className={`group flex items-center justify-between gap-1.5 rounded-lg py-1.5 pr-1.5 text-[12px] transition-colors ${
            isActive
              ? 'bg-blue-50 text-blue-800 font-semibold'
              : 'text-slate-700 hover:bg-slate-100/75'
          }`}
        >
          <button
            type="button"
            onClick={() => onSelectFile(node)}
            title={node.rel_path}
            className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
          >
            {node.format === 'image' ? (
              <ImageIcon className="h-3.5 w-3.5 shrink-0 text-slate-400" />
            ) : node.format === 'latex' ? (
              <FileCode2 className="h-3.5 w-3.5 shrink-0 text-violet-500" />
            ) : (
              <FileText className="h-3.5 w-3.5 shrink-0 text-slate-400" />
            )}
            <span className="truncate">{node.name}</span>
            <span
              className={`shrink-0 rounded border px-1 py-0 text-[9.5px] font-semibold ${badge.cls}`}
            >
              {badge.label}
            </span>
          </button>

          {isDoc && (
            <button
              type="button"
              data-local-pick={node.rel_path}
              onClick={(e) => {
                e.stopPropagation();
                onTogglePickForDiff(node.rel_path);
              }}
              title={
                pairIdx === 0
                  ? '已选为对比文件 A（点击取消）'
                  : pairIdx === 1
                    ? '已选为对比文件 B（点击取消）'
                    : '勾选参与两两对比'
              }
              className={`shrink-0 rounded-md border px-1.5 py-0.5 text-[10px] font-bold transition-all ${
                pairIdx === 0
                  ? 'border-rose-300 bg-rose-50 text-rose-700'
                  : pairIdx === 1
                    ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
                    : 'border-slate-200 bg-white text-slate-500 opacity-75 group-hover:opacity-100 hover:border-blue-300 hover:text-blue-700'
              }`}
            >
              {pairIdx === 0 ? 'A' : pairIdx === 1 ? 'B' : '对比'}
            </button>
          )}
        </div>
      );
    });

  return (
    <aside
      data-local-sidebar="true"
      className="pd-local-sidebar flex w-72 shrink-0 flex-col border-r border-[#E6E8EE] bg-[#FAFBFC] select-none"
    >
      {/* Top Folder Header */}
      <div className="border-b border-[#E6E8EE] px-3 py-2.5">
        <div className="flex items-center justify-between gap-1.5">
          <div className="flex min-w-0 items-center gap-1.5">
            <FolderOpen className="h-4 w-4 shrink-0 text-blue-600" />
            <span className="truncate text-xs font-bold text-slate-800" title={project.local_root_path || ''}>
              {rootBasename}
            </span>
          </div>
          <div className="flex items-center gap-0.5 shrink-0">
            <button
              type="button"
              data-local-refresh="true"
              onClick={onRefresh}
              title="手动刷新本地文件夹"
              className="rounded-lg p-1 text-slate-500 hover:bg-slate-200/60 hover:text-slate-800 transition-colors"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin text-blue-600' : ''}`} />
            </button>
            <button
              type="button"
              data-local-settings="true"
              onClick={onOpenBindingSettings}
              title="管理绑定目录（重定位 / 解除绑定）"
              className="rounded-lg p-1 text-slate-500 hover:bg-slate-200/60 hover:text-slate-800 transition-colors"
            >
              <Settings2 className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={onCloseSidebar}
              title="收起文件树 (⌘1)"
              className="rounded-lg p-1 text-slate-400 hover:bg-slate-200/60 hover:text-slate-700 transition-colors"
            >
              <PanelLeftClose className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
        <div
          className="mt-1 truncate font-mono text-[10px] text-slate-500"
          title={project.local_root_path || ''}
        >
          {project.local_root_path}
        </div>

        {/* Search + Format Filter + Aux Toggle (D-07) */}
        <div className="mt-2.5 relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
          <input
            data-local-tree-search="true"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索文件名或子目录..."
            className="w-full rounded-lg border border-slate-200 bg-white pl-7 pr-6 py-1 text-[11.5px] text-slate-800 focus:border-blue-400 focus:outline-none"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery('')}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-slate-400 hover:text-slate-600"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>

        <div className="mt-2 flex items-center justify-between gap-1">
          <div className="flex items-center gap-0.5 rounded-lg bg-slate-200/60 p-0.5 text-[10.5px]">
            {(
              [
                ['all', '全部'],
                ['latex', 'TeX'],
                ['docx', 'Word'],
                ['markdown', 'MD'],
              ] as [LocalFormatFilter, string][]
            ).map(([k, lbl]) => (
              <button
                key={k}
                type="button"
                data-local-fmt={k}
                onClick={() => setFormatFilter(k)}
                className={`rounded-md px-1.5 py-0.5 font-medium transition-colors ${
                  formatFilter === k ? 'bg-white text-slate-900 shadow-2xs' : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                {lbl}
              </button>
            ))}
          </div>

          <label className="inline-flex items-center gap-1 text-[10.5px] text-slate-600 cursor-pointer">
            <input
              type="checkbox"
              data-local-tree-aux="true"
              checked={includeAux}
              onChange={(e) => onToggleIncludeAux(e.target.checked)}
              className="h-3 w-3 rounded border-slate-300 text-blue-600"
            />
            <span>辅助文件</span>
          </label>
        </div>
      </div>

      {/* Truncation Warning Banner (AC-18 / D-07) */}
      {tree?.truncated && (
        <div
          data-local-truncated="true"
          className="border-b border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-800 flex items-start gap-1.5"
        >
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5 text-amber-600" />
          <span>{tree.truncated_reason || '目录条目较多，已按安全上限截断显示'}</span>
        </div>
      )}

      {/* Scrollable File Tree Body or Recovery Card (AC-18) */}
      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-0.5">
        {error ? (
          <div
            data-local-recovery-card="true"
            className="m-1 rounded-xl border border-rose-200 bg-rose-50/70 p-3 text-xs space-y-2.5"
          >
            <div className="flex items-start gap-2 text-rose-800 font-semibold">
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5 text-rose-600" />
              <span>
                {error.code === 'ROOT_MISSING'
                  ? '绑定的本地文件夹已失联'
                  : error.code === 'ROOT_UNREADABLE'
                    ? '无权限读取绑定目录'
                    : '无法加载本地目录'}
              </span>
            </div>
            <p className="text-[11px] text-rose-700/90 leading-relaxed break-all">{error.message}</p>
            <div className="flex flex-wrap gap-1.5">
              <button
                type="button"
                onClick={onOpenBindingSettings}
                className="rounded-lg bg-blue-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-blue-700"
              >
                重新定位目录 / 解绑
              </button>
              <button
                type="button"
                onClick={onRefresh}
                className="rounded-lg border border-rose-200 bg-white px-2.5 py-1 text-[11px] font-medium text-rose-700 hover:bg-rose-50"
              >
                重试
              </button>
            </div>
          </div>
        ) : filtered.nodes.length === 0 ? (
          <div className="py-10 text-center text-xs text-slate-400 space-y-2">
            <p>{loading ? '正在扫描本地目录...' : '未找到匹配的受支持文稿'}</p>
            {(query || formatFilter !== 'all') && (
              <button
                type="button"
                onClick={() => {
                  setQuery('');
                  setFormatFilter('all');
                }}
                className="rounded-md border border-slate-200 bg-white px-2.5 py-1 text-[11px] text-slate-600 hover:bg-slate-50"
              >
                重置筛选
              </button>
            )}
          </div>
        ) : (
          renderNodes(filtered.nodes, 0)
        )}
      </div>

      {/* Strict 2-File Pairwise Limit Intercept Banner (D-04 / AC-13) */}
      {pendingThirdRelPath && (
        <div
          data-pair-limit-banner="true"
          className="border-t border-amber-200 bg-amber-50 px-3 py-2.5 text-[11px] text-amber-900 space-y-2"
        >
          <div className="font-semibold leading-snug">
            当前仅支持选择 2 个文件两两对比（已选满 2/2）
          </div>
          <div className="truncate font-mono text-[10.5px] text-amber-800">
            待选：{pendingThirdRelPath}
          </div>
          <div className="flex flex-wrap gap-1">
            <button
              type="button"
              data-pair-replace="0"
              onClick={() => onReplacePairSlot(0, pendingThirdRelPath)}
              className="rounded-md bg-rose-600 px-2 py-1 text-[10.5px] font-semibold text-white hover:bg-rose-700"
            >
              替换 A（旧）
            </button>
            <button
              type="button"
              data-pair-replace="1"
              onClick={() => onReplacePairSlot(1, pendingThirdRelPath)}
              className="rounded-md bg-emerald-600 px-2 py-1 text-[10.5px] font-semibold text-white hover:bg-emerald-700"
            >
              替换 B（新）
            </button>
            <button
              type="button"
              data-pair-cancel="true"
              onClick={onCancelPendingThird}
              className="rounded-md border border-amber-300 bg-white px-2 py-1 text-[10.5px] font-medium text-amber-900 hover:bg-amber-100"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {/* Bottom Sticky Pairwise Diff Action Bar */}
      <div className="border-t border-[#E6E8EE] bg-white px-3 py-2.5 space-y-2">
        <div className="flex items-center justify-between text-[11px]">
          <span className="font-semibold text-slate-600">
            两两对比已选 <span className="tabular-nums text-blue-700">{selectedPair.length}/2</span>
          </span>
          {selectedPair.length > 0 && (
            <button
              type="button"
              onClick={onClearPair}
              className="text-[10.5px] text-slate-400 hover:text-slate-700"
            >
              清空
            </button>
          )}
        </div>

        {selectedPair.length > 0 ? (
          <div className="space-y-1 text-[10.5px]">
            <div className="flex items-center gap-1.5 truncate">
              <span className="rounded bg-rose-100 px-1 py-0 font-bold text-rose-700 shrink-0">A</span>
              <span className="truncate font-mono text-slate-700" title={selectedPair[0]}>
                {selectedPair[0]}
              </span>
            </div>
            {selectedPair[1] ? (
              <div className="flex items-center gap-1.5 truncate">
                <span className="rounded bg-emerald-100 px-1 py-0 font-bold text-emerald-700 shrink-0">B</span>
                <span className="truncate font-mono text-slate-700" title={selectedPair[1]}>
                  {selectedPair[1]}
                </span>
              </div>
            ) : (
              <div className="text-[10.5px] text-slate-400">请再勾选 1 个文件作为 B（新）</div>
            )}
          </div>
        ) : (
          <div className="text-[10.5px] text-slate-400">
            点击文件直接阅读 · 勾选任意 2 个文件发起两两对比
          </div>
        )}

        <button
          type="button"
          data-local-compare-btn="true"
          disabled={selectedPair.length !== 2}
          onClick={onStartPairCompare}
          className={`flex w-full items-center justify-center gap-1.5 rounded-xl py-1.5 text-xs font-semibold transition-colors ${
            selectedPair.length === 2
              ? 'bg-blue-600 text-white hover:bg-blue-700 shadow-xs'
              : 'bg-slate-100 text-slate-400 cursor-not-allowed'
          }`}
        >
          <GitCompareArrows className="h-3.5 w-3.5" />
          {selectedPair.length === 2 ? '对比所选 (2/2)' : `对比所选 (${selectedPair.length}/2)`}
        </button>
      </div>
    </aside>
  );
};
