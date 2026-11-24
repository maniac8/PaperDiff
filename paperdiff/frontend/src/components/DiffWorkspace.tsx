/**
 * @file DiffWorkspace.tsx
 * @description Multi-version academic comparison canvas supporting Split (side-by-side), Inline,
 * and Source diff modes with bidirectional hover linking, unchanged-block folding, merged-cell
 * table comparison (`Δ / %` & `+B / -B`), math symbol diffing, and inline fact-conservation alerts.
 *
 * Rendering invariants:
 * - Search filtering uses `useDeferredValue` to keep typing responsive on 50k-word theses.
 * - Gutter metric hover cards render via `FloatingHoverCard` (`ReactDOM.createPortal`) to avoid
 *   paint clipping from `.pd-virtual-block { content-visibility: auto; }`.
 */

import React, { useCallback, useDeferredValue, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  ArrowLeft,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Code2,
  Copy,
  Image as ImageIcon,
  Maximize2,
  Pencil,
  RotateCcw,
  Sparkles,
  Table2,
  UnfoldVertical,
  X,
} from 'lucide-react';
import type {
  BibEntry,
  ComparisonResult,
  DiffSegment,
  FilterMode,
  FontMode,
  ParagraphDiff,
  TablePlainCell,
  ViewMode,
} from '../types';
import { FloatingHoverCard, TokenItems, type FloatingAnchorRect } from './TokenRenderer';
import { getListBullet } from '../utils/typography';

interface DiffWorkspaceProps {
  comparison: ComparisonResult;
  viewMode: ViewMode;
  filterMode: FilterMode;
  fontMode: FontMode;
  fontSize: number;
  smartFold: boolean;
  showFigures: boolean;
  searchQuery: string;
  decisions: Record<string, 'accept_new' | 'keep_old'>;
  paragraphEdits: Record<number, string>;
  expandedAlerts: Record<number, boolean>;
  onToggleParaAlerts: (paraIndex: number) => void;
  onToggleAlertAck: (alertId: string) => void;
  onSetHunkDecision: (hunkId: string, choice: 'accept_new' | 'keep_old') => void;
  onSetParagraphDecision: (para: ParagraphDiff, choice: 'accept_new' | 'keep_old') => void;
  onSaveParagraphEdit: (paraIndex: number, text: string | null) => void;
  highlightedPara: number | null;
  onJumpToParagraph: (paraIndex: number) => void;
}

interface HunkPopoverState {
  hunkId: string;
  oldPreview: string;
  newPreview: string;
  x: number;
  y: number;
  placeBelow: boolean;
}

function formatWordDelta(delta: number): string {
  if (delta > 0) return `+${delta} 词`;
  return `${delta} 词`;
}

function deltaBadgeClass(delta: number): string {
  if (delta < 0) return 'bg-[#E3EEFF] text-[#2563EB]';
  if (delta > 0) return 'bg-emerald-50 text-emerald-700 border border-emerald-200/70';
  return 'bg-slate-100 text-slate-400';
}

function simColorClass(sim: number): string {
  if (sim === 100) return 'text-slate-400';
  if (sim < 45) return 'text-amber-600 font-medium';
  return 'text-slate-500';
}

function matchesPara(p: ParagraphDiff, filterMode: FilterMode, q: string): boolean {
  if (filterMode === 'changed' && p.status === 'unchanged') return false;
  if (filterMode === 'heavy' && (p.status === 'unchanged' || p.similarity >= 60)) return false;
  if (filterMode === 'alerts' && !p.alerts.some((a) => !a.acked)) return false;
  if (q) {
    const hay = `${p.old_clean} ${p.new_clean} ${p.section_title}`.toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

type RenderGroup =
  | { kind: 'single'; para: ParagraphDiff }
  | { kind: 'folded'; key: string; paras: ParagraphDiff[] };

export const DiffWorkspace: React.FC<DiffWorkspaceProps> = ({
  comparison,
  viewMode,
  filterMode,
  fontMode,
  fontSize,
  smartFold,
  showFigures,
  searchQuery,
  decisions,
  paragraphEdits,
  expandedAlerts,
  onToggleParaAlerts,
  onToggleAlertAck,
  onSetHunkDecision,
  onSetParagraphDecision,
  onSaveParagraphEdit,
  highlightedPara,
  onJumpToParagraph,
}) => {
  const [expandedSource, setExpandedSource] = useState<Record<number, boolean>>({});
  const [expandedFoldKeys, setExpandedFoldKeys] = useState<Record<string, boolean>>({});
  const [tableViewModes, setTableViewModes] = useState<Record<number, 'merged' | 'dual'>>({});
  const [lightbox, setLightbox] = useState<{
    src: string;
    caption: string;
    fullSize: boolean;
    invert?: boolean;
  } | null>(null);
  const [copiedPara, setCopiedPara] = useState<number | null>(null);
  const [popover, setPopover] = useState<HunkPopoverState | null>(null);
  const [hoveredGutter, setHoveredGutter] = useState<{ index: number; anchor: FloatingAnchorRect } | null>(null);
  const dismissGutterHover = useCallback(() => setHoveredGutter(null), []);
  const [hoveredHunkId, setHoveredHunkId] = useState<string | null>(null);
  const [editingPara, setEditingPara] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState('');

  const bibEntries: Record<string, BibEntry> | undefined = comparison.bib_entries;
  const latexMacros = comparison.latex_macros;
  const footnotes = comparison.footnotes;
  const deferredSearch = useDeferredValue(searchQuery);

  useEffect(() => {
    if (!lightbox) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setLightbox(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [lightbox]);

  // Close Cherry-Pick popover on Escape or scroll
  useEffect(() => {
    if (!popover) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setPopover(null);
    };
    const onDown = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && target.closest('[data-hunk-popover="true"]')) return;
      if (target && target.closest('[data-diff-pill="true"]')) return;
      setPopover(null);
    };
    const onScroll = () => setPopover(null);
    window.addEventListener('keydown', onKey);
    window.addEventListener('mousedown', onDown);
    window.addEventListener('scroll', onScroll, true);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('mousedown', onDown);
      window.removeEventListener('scroll', onScroll, true);
    };
  }, [popover]);

  const proseFontClass = fontMode === 'serif' ? 'font-serif' : 'font-sans';
  const q = deferredSearch.trim().toLowerCase();

  const filteredParagraphs = useMemo(
    () =>
      comparison.paragraphs.filter((p) => {
        if (p.block_type === 'heading') {
          if (filterMode === 'all' && !q) return true;
          return comparison.paragraphs.some((other) => {
            if (other.block_type === 'heading' || other.section_title !== p.section_title) return false;
            return matchesPara(other, filterMode, q);
          });
        }
        return matchesPara(p, filterMode, q);
      }),
    [comparison.paragraphs, filterMode, q],
  );

  // Build smart-folded groups for consecutive unchanged body paragraphs
  const renderGroups = useMemo<RenderGroup[]>(() => {
    const canFold = smartFold && filterMode === 'all' && !q;
    if (!canFold) {
      return filteredParagraphs.map((para) => ({ kind: 'single', para }));
    }
    const groups: RenderGroup[] = [];
    let buf: ParagraphDiff[] = [];

    const flush = () => {
      if (buf.length >= 2) {
        const key = `fold-${buf[0].index}-${buf[buf.length - 1].index}`;
        if (expandedFoldKeys[key]) {
          for (const p of buf) groups.push({ kind: 'single', para: p });
        } else {
          groups.push({ kind: 'folded', key, paras: [...buf] });
        }
      } else {
        for (const p of buf) groups.push({ kind: 'single', para: p });
      }
      buf = [];
    };

    for (const p of filteredParagraphs) {
      const isFoldable = p.status === 'unchanged' && p.block_type !== 'heading' && p.block_type !== 'title';
      if (isFoldable) {
        buf.push(p);
      } else {
        flush();
        groups.push({ kind: 'single', para: p });
      }
    }
    flush();
    return groups;
  }, [filteredParagraphs, smartFold, filterMode, q, expandedFoldKeys]);

  const openHunkPopover = (e: React.MouseEvent<HTMLSpanElement>, seg: DiffSegment) => {
    // Allow native drag-to-copy text selection without opening popover!
    const sel = window.getSelection()?.toString().trim();
    if (sel && sel.length > 0) return;

    e.stopPropagation();
    const rect = e.currentTarget.getBoundingClientRect();
    const clampedX = Math.min(Math.max(rect.left + rect.width / 2, 160), window.innerWidth - 160);
    const placeBelow = rect.top < 120;
    const y = placeBelow ? rect.bottom + 8 : rect.top - 8;

    setPopover({
      hunkId: seg.hunk_id!,
      oldPreview: (seg.old_raw || '').slice(0, 60),
      newPreview: (seg.new_raw || '').slice(0, 60),
      x: clampedX,
      y,
      placeBelow,
    });
  };

  const handleCopyPara = (p: ParagraphDiff) => {
    const text = p.new_raw || p.new_clean || p.old_raw;
    navigator.clipboard.writeText(text).then(() => {
      setCopiedPara(p.index);
      setTimeout(() => setCopiedPara(null), 1400);
    });
  };

  const renderSplitLeft = (segments: DiffSegment[], isMathBlock: boolean) => {
    let hasPrev = false;
    return segments.map((seg, i) => {
      if (seg.type === 'insert') return null;
      const space = hasPrev && seg.lead_space_old ? ' ' : '';
      hasPrev = true;

      if (seg.type === 'equal') {
        return (
          <React.Fragment key={i}>
            {space}
            <TokenItems items={seg.old_items || seg.items || []} displayMath={isMathBlock} bibEntries={bibEntries} latexMacros={latexMacros} footnotes={footnotes} />
          </React.Fragment>
        );
      }
      const hid = seg.hunk_id!;
      const keptOld = decisions[hid] === 'keep_old';
      const activePop = popover?.hunkId === hid;
      const isLinkedHover = hoveredHunkId === hid;
      return (
        <React.Fragment key={i}>
          {space}
          <span
            data-diff-pill="true"
            onMouseEnter={() => setHoveredHunkId(hid)}
            onMouseLeave={() => setHoveredHunkId((cur) => (cur === hid ? null : cur))}
            onClick={(e) => openHunkPopover(e, seg)}
            className={`cursor-pointer ${keptOld ? 'diff-pill-kept-old' : 'diff-pill-del'} ${
              activePop
                ? 'ring-2 ring-blue-500/60'
                : isLinkedHover
                  ? 'ring-2 ring-rose-400/70 shadow-xs'
                  : ''
            }`}
          >
            <TokenItems items={seg.old_items || []} displayMath={isMathBlock} bibEntries={bibEntries} latexMacros={latexMacros} footnotes={footnotes} />
          </span>
        </React.Fragment>
      );
    });
  };

  const renderSplitRight = (segments: DiffSegment[], isMathBlock: boolean) => {
    let hasPrev = false;
    return segments.map((seg, i) => {
      if (seg.type === 'delete') return null;
      const space = hasPrev && seg.lead_space_new ? ' ' : '';
      hasPrev = true;

      if (seg.type === 'equal') {
        return (
          <React.Fragment key={i}>
            {space}
            <TokenItems items={seg.items || []} displayMath={isMathBlock} bibEntries={bibEntries} latexMacros={latexMacros} footnotes={footnotes} />
          </React.Fragment>
        );
      }
      const hid = seg.hunk_id!;
      const keptOld = decisions[hid] === 'keep_old';
      const activePop = popover?.hunkId === hid;
      const isLinkedHover = hoveredHunkId === hid;
      return (
        <React.Fragment key={i}>
          {space}
          <span
            data-diff-pill="true"
            onMouseEnter={() => setHoveredHunkId(hid)}
            onMouseLeave={() => setHoveredHunkId((cur) => (cur === hid ? null : cur))}
            onClick={(e) => openHunkPopover(e, seg)}
            className={`cursor-pointer ${keptOld ? 'diff-pill-rejected-new' : 'diff-pill-add'} ${
              activePop
                ? 'ring-2 ring-blue-500/60'
                : isLinkedHover
                  ? 'ring-2 ring-emerald-500/75 shadow-xs'
                  : ''
            }`}
          >
            <TokenItems items={seg.new_items || []} displayMath={isMathBlock} bibEntries={bibEntries} latexMacros={latexMacros} footnotes={footnotes} />
          </span>
        </React.Fragment>
      );
    });
  };

  const renderInline = (segments: DiffSegment[], isMathBlock: boolean) => {
    let hasPrev = false;
    return segments.map((seg, i) => {
      const space = hasPrev && (seg.lead_space_old || seg.lead_space_new) ? ' ' : '';
      hasPrev = true;

      if (seg.type === 'equal') {
        return (
          <React.Fragment key={i}>
            {space}
            <TokenItems items={seg.items || []} displayMath={isMathBlock} bibEntries={bibEntries} latexMacros={latexMacros} footnotes={footnotes} />
          </React.Fragment>
        );
      }
      const hid = seg.hunk_id!;
      const keptOld = decisions[hid] === 'keep_old';
      const activePop = popover?.hunkId === hid;

      if (seg.type === 'replace') {
        return (
          <React.Fragment key={i}>
            {space}
            <span
              data-diff-pill="true"
              onClick={(e) => openHunkPopover(e, seg)}
              className={`cursor-pointer ${keptOld ? 'diff-pill-kept-old' : 'diff-pill-del'} ${
                activePop ? 'ring-2 ring-blue-500/50' : ''
              }`}
            >
              <TokenItems items={seg.old_items || []} displayMath={isMathBlock} bibEntries={bibEntries} latexMacros={latexMacros} footnotes={footnotes} />
            </span>{' '}
            <span
              data-diff-pill="true"
              onClick={(e) => openHunkPopover(e, seg)}
              className={`cursor-pointer ${keptOld ? 'diff-pill-rejected-new' : 'diff-pill-add'} ${
                activePop ? 'ring-2 ring-blue-500/50' : ''
              }`}
            >
              <TokenItems items={seg.new_items || []} displayMath={isMathBlock} bibEntries={bibEntries} latexMacros={latexMacros} footnotes={footnotes} />
            </span>
          </React.Fragment>
        );
      }
      if (seg.type === 'delete') {
        return (
          <React.Fragment key={i}>
            {space}
            <span
              data-diff-pill="true"
              onClick={(e) => openHunkPopover(e, seg)}
              className={`cursor-pointer ${keptOld ? 'diff-pill-kept-old' : 'diff-pill-del'} ${
                activePop ? 'ring-2 ring-blue-500/50' : ''
              }`}
            >
              <TokenItems items={seg.old_items || []} displayMath={isMathBlock} bibEntries={bibEntries} latexMacros={latexMacros} footnotes={footnotes} />
            </span>
          </React.Fragment>
        );
      }
      return (
        <React.Fragment key={i}>
          {space}
          <span
            data-diff-pill="true"
            onClick={(e) => openHunkPopover(e, seg)}
            className={`cursor-pointer ${keptOld ? 'diff-pill-rejected-new' : 'diff-pill-add'} ${
              activePop ? 'ring-2 ring-blue-500/50' : ''
            }`}
          >
            <TokenItems items={seg.new_items || []} displayMath={isMathBlock} bibEntries={bibEntries} latexMacros={latexMacros} footnotes={footnotes} />
          </span>
        </React.Fragment>
      );
    });
  };

  if (filteredParagraphs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-28 text-slate-400">
        <p className="text-sm font-medium text-slate-500">当前筛选条件下没有匹配的段落</p>
        <p className="mt-1 text-xs">尝试切换为「全部」或清空搜索关键词</p>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-[1720px] px-4 sm:px-8 pt-5 pb-24">
      <div className="rounded-2xl border border-[#E6E8EE] bg-white shadow-[0_2px_20px_rgba(15,23,42,0.03)]">
        {/* Subtle sticky column header for Split / Source */}
        {viewMode !== 'inline' && (
          <div className="sticky top-0 z-10 grid grid-cols-[minmax(0,1fr)_84px_minmax(0,1fr)] items-center rounded-t-2xl border-b border-slate-100 bg-white/95 backdrop-blur px-7 sm:px-10 py-2.5 text-xs text-slate-500">
            <div className="flex items-center gap-2 truncate">
              <span className="h-2 w-2 rounded-full bg-rose-400 shrink-0" />
              <span className="truncate font-semibold text-slate-700">
                {comparison.old_version.label}
              </span>
              <span className="text-slate-400 tabular-nums">{comparison.summary.old_words} 词</span>
            </div>
            <div className="text-center text-[10.5px] font-medium tracking-wider text-slate-400">
              变化 / 相似
            </div>
            <div className="flex items-center gap-2 truncate">
              <span className="h-2 w-2 rounded-full bg-emerald-500 shrink-0" />
              <span className="truncate font-semibold text-slate-700">
                {comparison.new_version.label}
              </span>
              <span className="text-slate-400 tabular-nums">{comparison.summary.new_words} 词</span>
            </div>
          </div>
        )}

        <div
          style={viewMode === 'inline' ? { maxWidth: 'clamp(780px, 64vw, 1180px)' } : undefined}
          className={viewMode === 'inline' ? 'mx-auto w-full px-7 sm:px-10 py-6' : 'px-7 sm:px-10 py-3'}
        >
          {renderGroups.map((grp) => {
            if (grp.kind === 'folded') {
              return (
                <button
                  key={grp.key}
                  type="button"
                  onClick={() => setExpandedFoldKeys((prev) => ({ ...prev, [grp.key]: true }))}
                  className="my-2 flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-slate-200 bg-slate-50/70 py-2 text-xs text-slate-500 hover:border-blue-300 hover:bg-blue-50/40 hover:text-blue-700 transition-colors"
                >
                  <UnfoldVertical className="h-3.5 w-3.5" />
                  <span>已折叠 {grp.paras.length} 段未修改正文（点击展开）</span>
                </button>
              );
            }

            const para = grp.para;
            const isHighlighted = highlightedPara === para.index;

            if (para.block_type === 'hr') {
              return <hr key={para.index} className="my-5 border-slate-200/80" />;
            }

            if (para.block_type === 'heading') {
              const titleText = para.new_clean || para.old_clean;
              const sizeCls =
                para.section_level <= 1
                  ? 'text-[17px] font-bold text-slate-900 mt-7 mb-2 pb-2 border-b border-slate-100'
                  : para.section_level === 2
                    ? 'text-[15px] font-semibold text-slate-800 mt-6 mb-1.5'
                    : 'text-[13.5px] font-semibold text-slate-700 mt-4 mb-1';

              return (
                <div
                  key={para.index}
                  id={`para-${para.index}`}
                  className={`pd-virtual-block flex items-center justify-between ${sizeCls} ${
                    isHighlighted ? 'para-flash rounded-lg px-2 -mx-2' : ''
                  }`}
                >
                  <span>
                    {para.heading_items && para.heading_items.length > 0 ? (
                      <TokenItems
                        items={para.heading_items}
                        bibEntries={bibEntries}
                        latexMacros={latexMacros}
                        footnotes={footnotes}
                      />
                    ) : (
                      titleText
                    )}
                  </span>
                  {para.status === 'modified' && (
                    <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700 border border-amber-200">
                      标题已改
                    </span>
                  )}
                </div>
              );
            }

            const isMathBlock = para.block_type === 'math';
            const isTableBlock = para.block_type === 'table' && Boolean(para.table_diff);
            const isFigureBlock = para.block_type === 'figure' && Boolean(para.figure_info);
            const isListBlock = para.block_type === 'list';
            const isQuoteBlock = para.block_type === 'blockquote';
            const isTitle = para.block_type === 'title';
            const tableView = tableViewModes[para.index] || 'merged';
            const listDepth = isListBlock ? Math.min(5, Math.max(0, para.list_meta?.depth || 0)) : 0;
            const quoteDepth = isQuoteBlock ? Math.min(4, Math.max(1, para.quote_depth || 1)) : 0;
            const listMarker = isListBlock
              ? para.list_meta?.ordered
                ? `${para.list_meta.item_num || 1}.`
                : getListBullet(listDepth)
              : null;
            const activeParaAlerts = para.alerts.filter((a) => !a.acked);
            const hasAlerts = para.alerts.length > 0;
            const hasActiveAlerts = activeParaAlerts.length > 0;
            const highAlert = activeParaAlerts.some((a) => a.severity === 'high');
            const aiReduced = para.ai_isms_old.length - para.ai_isms_new.length;
            const paraHunks = para.segments.filter((s) => s.type !== 'equal').map((s) => s.hunk_id!);
            const customRevertedCount = paraHunks.filter((id) => decisions[id] === 'keep_old').length;
            const showRaw = expandedSource[para.index] || viewMode === 'source';
            const alertsOpen = Boolean(expandedAlerts[para.index]);

            // D-03: DiffWorkspace keeps body paragraphs compact left-aligned (textIndent: 0)
            // while preserving list depth (0..5) and blockquote nesting (1..4) cues.
            const textStyle: React.CSSProperties = {
              fontSize: isTitle ? `${fontSize + 3.5}px` : `${fontSize}px`,
              lineHeight: isTitle ? 1.42 : 1.9,
              textIndent: 0,
              textAlign: 'left',
              ...(isListBlock ? { paddingLeft: `${12 + listDepth * 20}px` } : {}),
              ...(isQuoteBlock && quoteDepth > 1 ? { marginLeft: `${(quoteDepth - 1) * 14}px` } : {}),
            };

            return (
              <div
                key={para.index}
                id={`para-${para.index}`}
                className={`${editingPara === para.index ? '' : 'pd-virtual-block'} group relative border-b border-slate-100/80 last:border-b-0 py-5 transition-colors ${
                  isHighlighted ? 'para-flash rounded-xl bg-blue-50/35 -mx-4 px-4' : ''
                }`}
              >
                {/* Floating hover micro-actions at top-right (hidden on tables where controls sit cleanly inline!) */}
                {!isTableBlock && (
                <div className="pointer-events-none absolute right-0 top-2 z-10 flex items-center gap-1 opacity-0 group-hover:opacity-100 group-hover:pointer-events-auto transition-opacity">
                  <div className="flex items-center gap-0.5 rounded-lg border border-slate-200/90 bg-white/95 p-0.5 shadow-sm backdrop-blur text-[11px]">
                    {para.hunk_count > 0 && (
                      <>
                        <button
                          type="button"
                          onClick={() => onSetParagraphDecision(para, 'keep_old')}
                          title="本段全部回退旧版"
                          className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-slate-600 hover:bg-slate-100"
                        >
                          <RotateCcw className="h-3 w-3" />
                          旧版
                        </button>
                        <button
                          type="button"
                          onClick={() => onSetParagraphDecision(para, 'accept_new')}
                          title="本段全部采纳新版"
                          className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-slate-600 hover:bg-slate-100"
                        >
                          <Check className="h-3 w-3" />
                          新版
                        </button>
                      </>
                    )}
                    {viewMode !== 'source' && (
                      <button
                        type="button"
                        onClick={() =>
                          setExpandedSource((prev) => ({ ...prev, [para.index]: !prev[para.index] }))
                        }
                        title="查看/收起原始 LaTeX 源码"
                        className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 ${
                          showRaw ? 'bg-blue-50 text-blue-700 font-medium' : 'text-slate-600 hover:bg-slate-100'
                        }`}
                      >
                        <Code2 className="h-3 w-3" />
                        源码
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => {
                        setEditingPara(para.index);
                        setEditDraft(paragraphEdits[para.index] ?? para.new_raw ?? para.new_clean ?? para.old_raw);
                      }}
                      title="原地微调本段文本（修复后可一键存为新版本）"
                      className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 ${
                        paragraphEdits[para.index] !== undefined
                          ? 'bg-emerald-50 text-emerald-700 font-medium'
                          : 'text-slate-600 hover:bg-slate-100'
                      }`}
                    >
                      <Pencil className="h-3 w-3" />
                      微调
                    </button>
                    <button
                      type="button"
                      onClick={() => handleCopyPara(para)}
                      title="复制本段新版源码"
                      className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-slate-600 hover:bg-slate-100"
                    >
                      {copiedPara === para.index ? (
                        <Check className="h-3 w-3 text-emerald-600" />
                      ) : (
                        <Copy className="h-3 w-3" />
                      )}
                    </button>
                  </div>
                </div>
                )}

                {/* Moved Paragraph Bidirectional Anchor Chip (only shown for moved paras) */}
                {(para.status === 'moved_from' || para.status === 'moved_to') && (
                  <div className="mb-2.5 flex items-center gap-2">
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-purple-50 border border-purple-200/80 px-2.5 py-0.5 text-[11px] font-medium text-purple-700">
                      {para.status === 'moved_from'
                        ? `段落已移动至「${para.moved_peer_section || '其他章节'}」`
                        : `段落由「${para.moved_peer_section || '其他章节'}」移入`}
                    </span>
                    {para.moved_peer_index !== null && para.moved_peer_index !== undefined && (
                      <button
                        type="button"
                        onClick={() => onJumpToParagraph(para.moved_peer_index!)}
                        className="inline-flex items-center gap-1 text-[11px] font-semibold text-blue-600 hover:underline"
                      >
                        {para.status === 'moved_from' ? (
                          <>
                            定位新位置 <ArrowRight className="h-3 w-3" />
                          </>
                        ) : (
                          <>
                            <ArrowLeft className="h-3 w-3" /> 回到原位置
                          </>
                        )}
                      </button>
                    )}
                  </div>
                )}

                {/* COMPACT FIGURE PREVIEW CARD (v1.4: Visual context only, no pixel diff) */}
                {isFigureBlock && para.figure_info && viewMode !== 'source' && (
                  <div className="mb-3">
                    {!showFigures ? (
                      <div className="inline-flex items-center gap-1.5 rounded-lg bg-slate-50 border border-slate-200/70 px-2.5 py-1 text-[11.5px] text-slate-500">
                        <ImageIcon className="h-3.5 w-3.5 text-slate-400" />
                        <span>
                          插图预览已隐藏{para.figure_info.label ? ` (${para.figure_info.label})` : ''} · 可在右上角 ⚙ 开启
                        </span>
                      </div>
                    ) : para.figure_info.image_status === 'no_preview' ? (
                      <div className="inline-flex items-center gap-1.5 rounded-lg bg-slate-50 border border-slate-200/70 px-2.5 py-1 text-[11.5px] text-slate-500">
                        <ImageIcon className="h-3.5 w-3.5 text-blue-500" />
                        <span className="font-mono text-[11px]">
                          {para.figure_info.new_path || para.figure_info.old_path || para.figure_info.label || 'Figure'}
                        </span>
                        <span className="text-slate-400">· 上传含图片的 Overleaf .zip 或 Word .docx 可同步预览插图</span>
                      </div>
                    ) : para.figure_info.image_status === 'unchanged' && para.figure_info.new_asset ? (
                      <div className="relative flex flex-col items-center rounded-xl border border-slate-100 bg-[#FAFBFC] p-3">
                        <div className="paper-figure-frame rounded-xl p-1.5">
                          <img
                            src={`/api/assets/${para.figure_info.new_asset}`}
                            alt={para.figure_info.label || 'Figure'}
                            onClick={() =>
                              setLightbox({
                                src: `/api/assets/${para.figure_info!.new_asset}`,
                                caption: para.new_clean || para.old_clean,
                                fullSize: false,
                                invert: false,
                              })
                            }
                            className="paper-figure-img max-h-[220px] max-w-full rounded-lg object-contain cursor-zoom-in transition-transform hover:scale-[1.01]"
                          />
                        </div>
                        <span className="mt-1.5 inline-flex items-center gap-1 text-[10.5px] text-slate-400">
                          <Maximize2 className="h-2.5 w-2.5" />
                          插图未变动 · 点击放大查看细节
                        </span>
                      </div>
                    ) : (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 rounded-xl border border-slate-100 bg-[#FAFBFC] p-3">
                        <div className="flex flex-col items-center justify-center">
                          <div className="mb-1.5 flex items-center gap-1.5 text-[10.5px] text-slate-400">
                            <span>旧版插图</span>
                            {para.figure_info.image_status === 'deleted' && (
                              <span className="rounded bg-rose-100 px-1.5 py-0 text-[10px] font-semibold text-rose-700">
                                已移除
                              </span>
                            )}
                          </div>
                          {para.figure_info.old_asset ? (
                            <div className="paper-figure-frame rounded-lg border border-slate-200/70 bg-white p-1">
                              <img
                                src={`/api/assets/${para.figure_info.old_asset}`}
                                alt="Old Figure"
                                onClick={() =>
                                  setLightbox({
                                    src: `/api/assets/${para.figure_info!.old_asset}`,
                                    caption: `旧版：${para.old_clean}`,
                                    fullSize: false,
                                    invert: false,
                                  })
                                }
                                className="paper-figure-img max-h-[210px] max-w-full rounded object-contain cursor-zoom-in"
                              />
                            </div>
                          ) : (
                            <div className="flex h-28 w-full items-center justify-center rounded-lg border border-dashed border-slate-200 text-xs text-slate-400">
                              — 旧版无此插图 —
                            </div>
                          )}
                        </div>
                        <div className="flex flex-col items-center justify-center">
                          <div className="mb-1.5 flex items-center gap-1.5 text-[10.5px] text-slate-400">
                            <span>新版插图</span>
                            {para.figure_info.image_status === 'updated' && (
                              <span className="rounded bg-amber-100 px-1.5 py-0 text-[10px] font-semibold text-amber-800">
                                图片已更新
                              </span>
                            )}
                            {para.figure_info.image_status === 'added' && (
                              <span className="rounded bg-emerald-100 px-1.5 py-0 text-[10px] font-semibold text-emerald-700">
                                新增插图
                              </span>
                            )}
                          </div>
                          {para.figure_info.new_asset ? (
                            <div className="paper-figure-frame rounded-lg border border-slate-200/70 bg-white p-1">
                              <img
                                src={`/api/assets/${para.figure_info.new_asset}`}
                                alt="New Figure"
                                onClick={() =>
                                  setLightbox({
                                    src: `/api/assets/${para.figure_info!.new_asset}`,
                                    caption: `新版：${para.new_clean}`,
                                    fullSize: false,
                                    invert: false,
                                  })
                                }
                                className="paper-figure-img max-h-[210px] max-w-full rounded object-contain cursor-zoom-in"
                              />
                            </div>
                          ) : (
                            <div className="flex h-28 w-full items-center justify-center rounded-lg border border-dashed border-slate-200 text-xs text-slate-400">
                              — 新版已移除此插图 —
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* ACADEMIC THREE-LINE TABLE DIFF VIEW (v1.4: Colspan/Rowspan + KaTeX + Bold + Numeric Delta + Dual Toggle) */}
                {isTableBlock && para.table_diff && viewMode !== 'source' && (
                  <div className="my-1">
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
                      <span className="inline-flex items-center gap-1.5 font-semibold text-slate-700">
                        <Table2 className="h-3.5 w-3.5 text-blue-600" />
                        数据表格对比
                        <span className="font-normal text-slate-400">
                          （{para.table_diff.rows.length} 行 ·{' '}
                          {para.table_diff.changed_cells > 0
                            ? `${para.table_diff.changed_cells} 格变动`
                            : '无变动'}
                          {(para.table_diff.bold_changed_cells || 0) > 0
                            ? ` · ${para.table_diff.bold_changed_cells} 处加粗变动`
                            : ''}
                          ）
                        </span>
                      </span>

                      <div className="flex flex-wrap items-center gap-2">
                        {para.table_diff.old_rows && para.table_diff.new_rows && (
                          <div className="pd-seg-track flex items-center rounded-lg bg-slate-100 p-0.5 text-[11px]">
                            <button
                              type="button"
                              onClick={() =>
                                setTableViewModes((prev) => ({ ...prev, [para.index]: 'merged' }))
                              }
                              className={`rounded-md px-2 py-0.5 font-medium transition-colors ${
                                tableView === 'merged'
                                  ? 'pd-seg-active bg-white text-slate-900 shadow-xs'
                                  : 'text-slate-500 hover:text-slate-800'
                              }`}
                            >
                              融合对比
                            </button>
                            <button
                              type="button"
                              onClick={() =>
                                setTableViewModes((prev) => ({ ...prev, [para.index]: 'dual' }))
                              }
                              className={`rounded-md px-2 py-0.5 font-medium transition-colors ${
                                tableView === 'dual'
                                  ? 'pd-seg-active bg-white text-slate-900 shadow-xs'
                                  : 'text-slate-500 hover:text-slate-800'
                              }`}
                            >
                              双表对照
                            </button>
                          </div>
                        )}

                        {hasAlerts && (
                          <button
                            type="button"
                            onClick={() => onToggleParaAlerts(para.index)}
                            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-semibold border ${
                              !hasActiveAlerts
                                ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                                : highAlert
                                  ? 'bg-rose-50 text-rose-700 border-rose-200'
                                  : 'bg-amber-50 text-amber-700 border-amber-200'
                            }`}
                          >
                            {hasActiveAlerts ? (
                              <>
                                <AlertTriangle className="h-3 w-3" />
                                {activeParaAlerts.length} 项告警
                              </>
                            ) : (
                              <>
                                <CheckCircle2 className="h-3 w-3" />
                                已核对
                              </>
                            )}
                          </button>
                        )}

                        {/* Inline subtle table tools (zero overlap with toggle/alerts!) */}
                        <div className="flex items-center gap-0.5 border-l border-slate-200 pl-2 text-[11px]">
                          <button
                            type="button"
                            onClick={() =>
                              setExpandedSource((prev) => ({ ...prev, [para.index]: !prev[para.index] }))
                            }
                            title="查看/收起表格原始源码"
                            className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 ${
                              showRaw ? 'bg-blue-50 text-blue-700 font-medium' : 'text-slate-500 hover:bg-slate-100'
                            }`}
                          >
                            <Code2 className="h-3 w-3" />
                            源码
                          </button>
                          <button
                            type="button"
                            onClick={() => handleCopyPara(para)}
                            title="复制表格新版源码"
                            className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-slate-500 hover:bg-slate-100"
                          >
                            {copiedPara === para.index ? (
                              <Check className="h-3 w-3 text-emerald-600" />
                            ) : (
                              <Copy className="h-3 w-3" />
                            )}
                          </button>
                        </div>
                      </div>
                    </div>

                    {tableView === 'dual' && para.table_diff.old_rows && para.table_diff.new_rows ? (
                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                        <PlainAcademicTable
                          label="旧版表格"
                          rows={para.table_diff.old_rows}
                          bibEntries={bibEntries}
                          latexMacros={latexMacros}
                          footnotes={footnotes}
                        />
                        <PlainAcademicTable
                          label="新版表格"
                          rows={para.table_diff.new_rows}
                          bibEntries={bibEntries}
                          latexMacros={latexMacros}
                          footnotes={footnotes}
                        />
                      </div>
                    ) : (
                      <div className="pd-table-wrap overflow-x-auto">
                        <table className="pd-table w-full border-collapse text-[13px] font-sans">
                          <tbody>
                            {para.table_diff.rows.map((row, rIdx) => {
                              const isHeader = rIdx === 0;
                              const rowHasChangedCell = row.cells.some((c) => c.status !== 'unchanged');
                              const rowCls =
                                row.status === 'added'
                                  ? 'pd-table-row-add'
                                  : row.status === 'deleted'
                                    ? 'pd-table-row-del'
                                    : isHeader
                                      ? 'pd-table-head'
                                      : rowHasChangedCell
                                        ? 'pd-table-row pd-table-row-mod'
                                        : rIdx % 2 === 0
                                          ? 'pd-table-row pd-table-row-stripe'
                                          : 'pd-table-row';
                              return (
                                <tr key={rIdx} className={rowCls}>
                                  {row.cells.map((cell, cIdx) => {
                                    const nd = cell.numeric_delta;
                                    const deltaTitle = nd
                                      ? `数值变化：${nd.old_num} → ${nd.new_num}（差值 ${nd.delta > 0 ? '+' : ''}${nd.delta}${nd.pct !== null ? ` / ${nd.pct > 0 ? '+' : ''}${nd.pct}%` : ''}）`
                                      : undefined;
                                    const cellStatusCls =
                                      cell.status === 'modified'
                                        ? 'pd-table-cell-mod'
                                        : cell.status === 'added'
                                          ? 'pd-table-cell-add'
                                          : cell.status === 'deleted'
                                            ? 'pd-table-cell-del'
                                            : '';
                                    const CellTag = isHeader ? 'th' : 'td';
                                    return (
                                      <CellTag
                                        key={cIdx}
                                        colSpan={cell.colspan || 1}
                                        rowSpan={cell.rowspan || 1}
                                        title={deltaTitle}
                                        className={`px-3.5 py-2.5 text-left align-top tabular-nums ${cellStatusCls} ${
                                          cell.new_bold ? 'font-bold text-slate-900' : ''
                                        }`}
                                      >
                                        {cell.status === 'unchanged' ? (
                                          <span className={cell.new_bold ? 'font-bold text-slate-900' : 'text-slate-700'}>
                                            {cell.items ? (
                                              <TokenItems items={cell.items} bibEntries={bibEntries} latexMacros={latexMacros} footnotes={footnotes} />
                                            ) : (
                                              cell.new
                                            )}
                                          </span>
                                        ) : cell.status === 'added' ? (
                                          <span className="diff-pill-add">
                                            {cell.items ? (
                                              <TokenItems items={cell.items} bibEntries={bibEntries} latexMacros={latexMacros} footnotes={footnotes} />
                                            ) : (
                                              cell.new
                                            )}
                                          </span>
                                        ) : cell.status === 'deleted' ? (
                                          <span className="diff-pill-del">
                                            {cell.items ? (
                                              <TokenItems items={cell.items} bibEntries={bibEntries} latexMacros={latexMacros} footnotes={footnotes} />
                                            ) : (
                                              cell.old
                                            )}
                                          </span>
                                        ) : cell.segments.length === 0 ? (
                                          <span className={cell.new_bold ? 'font-bold text-slate-900' : 'text-slate-700'}>
                                            {cell.items ? (
                                              <TokenItems items={cell.items} bibEntries={bibEntries} latexMacros={latexMacros} footnotes={footnotes} />
                                            ) : (
                                              cell.new
                                            )}
                                          </span>
                                        ) : (
                                          <span>
                                            {cell.segments.map((s, si) => {
                                              const sp = si > 0 && (s.lead_space_old || s.lead_space_new) ? ' ' : '';
                                              if (s.type === 'equal') {
                                                return (
                                                  <React.Fragment key={si}>
                                                    {sp}
                                                    <TokenItems items={s.items || []} bibEntries={bibEntries} latexMacros={latexMacros} footnotes={footnotes} />
                                                  </React.Fragment>
                                                );
                                              }
                                              if (s.type === 'replace') {
                                                return (
                                                  <React.Fragment key={si}>
                                                    {sp}
                                                    <span className="diff-pill-del">
                                                      <TokenItems items={s.old_items || []} bibEntries={bibEntries} latexMacros={latexMacros} footnotes={footnotes} />
                                                    </span>{' '}
                                                    <span className="diff-pill-add">
                                                      <TokenItems items={s.new_items || []} bibEntries={bibEntries} latexMacros={latexMacros} footnotes={footnotes} />
                                                    </span>
                                                  </React.Fragment>
                                                );
                                              }
                                              if (s.type === 'delete') {
                                                return (
                                                  <React.Fragment key={si}>
                                                    {sp}
                                                    <span className="diff-pill-del">
                                                      <TokenItems items={s.old_items || []} bibEntries={bibEntries} latexMacros={latexMacros} footnotes={footnotes} />
                                                    </span>
                                                  </React.Fragment>
                                                );
                                              }
                                              return (
                                                <React.Fragment key={si}>
                                                  {sp}
                                                  <span className="diff-pill-add">
                                                    <TokenItems items={s.new_items || []} bibEntries={bibEntries} latexMacros={latexMacros} footnotes={footnotes} />
                                                  </span>
                                                </React.Fragment>
                                              );
                                            })}
                                          </span>
                                        )}

                                        {/* Subtle badges for bold shift or numeric delta */}
                                        {cell.bold_changed && (
                                          <span
                                            title={cell.new_bold ? '新版新增粗体标记' : '新版取消了粗体最优值标记'}
                                            className="pd-bold-badge ml-1.5 inline-block rounded px-1.5 py-0 text-[9.5px] font-bold align-middle"
                                          >
                                            {cell.new_bold ? '+B' : '-B'}
                                          </span>
                                        )}
                                        {nd && (
                                          <span className="pd-delta-badge ml-1.5 inline-block rounded px-1.5 py-0 text-[10px] font-medium align-middle">
                                            {nd.delta > 0 ? `+${nd.delta}` : nd.delta}
                                            {nd.pct !== null ? ` (${nd.pct > 0 ? '+' : ''}${nd.pct}%)` : ''}
                                          </span>
                                        )}
                                      </CellTag>
                                    );
                                  })}
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                )}

                {/* VIEW 1: SPLIT SIDE-BY-SIDE (Pure Editorial Reference Design) */}
                {viewMode === 'split' && !isTableBlock && (
                  <div className="grid grid-cols-[minmax(0,1fr)_84px_minmax(0,1fr)] items-start gap-6">
                    <div
                      data-diff-pane="left"
                      data-block-type={para.block_type}
                      data-list-depth={isListBlock ? listDepth : undefined}
                      data-quote-depth={isQuoteBlock ? quoteDepth : undefined}
                      style={textStyle}
                      className={`${proseFontClass} ${isTitle ? 'font-semibold' : ''} ${
                        isListBlock ? 'flex items-start gap-2' : ''
                      } ${isQuoteBlock ? 'pd-diff-quote' : ''} ${
                        isMathBlock && para.eq_number ? 'flex items-center justify-between gap-3' : ''
                      } text-[#1F2937] break-words`}
                    >
                      {isListBlock && para.old_clean && (
                        <span className="shrink-0 font-sans text-slate-400 select-none mt-[1px]">
                          {listMarker}
                        </span>
                      )}
                      <div className="min-w-0 flex-1">
                        {para.old_clean ? (
                          renderSplitLeft(para.segments, isMathBlock)
                        ) : (
                          <span className="font-sans text-xs italic text-slate-300">
                            — 旧版无此段 —
                          </span>
                        )}
                      </div>
                      {isMathBlock && para.eq_number && para.old_clean && (
                        <span className="shrink-0 font-serif text-xs text-slate-400 select-none">
                          ({para.eq_number})
                        </span>
                      )}
                    </div>

                    {/* Center Gutter Information Hub */}
                    <div
                      className="relative flex flex-col items-center pt-1 select-none"
                      onMouseEnter={(e) => {
                        const r = e.currentTarget.getBoundingClientRect();
                        setHoveredGutter({
                          index: para.index,
                          anchor: { top: r.top, bottom: r.bottom, left: r.left, width: r.width },
                        });
                      }}
                      onMouseLeave={() =>
                        setHoveredGutter((cur) => (cur?.index === para.index ? null : cur))
                      }
                    >
                      <span
                        className={`inline-flex items-center justify-center rounded-md px-2 py-0.5 text-[12px] font-semibold tabular-nums ${deltaBadgeClass(
                          para.word_delta,
                        )}`}
                      >
                        {formatWordDelta(para.word_delta)}
                      </span>
                      <span className={`mt-1.5 text-[11.5px] tabular-nums ${simColorClass(para.similarity_int)}`}>
                        相似 {para.similarity_int}%
                      </span>

                      {/* Subtle contextual micro-badges under similarity */}
                      {aiReduced > 0 && (
                        <span
                          title={`消除 ${aiReduced} 个 AI 高频词`}
                          className="mt-1.5 inline-flex items-center gap-0.5 rounded-full bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700"
                        >
                          <Sparkles className="h-2.5 w-2.5" />-{aiReduced}
                        </span>
                      )}
                      {hasAlerts && (
                        <button
                          type="button"
                          onClick={() => onToggleParaAlerts(para.index)}
                          title="点击在段底原地展开/收起事实审计详情"
                          className={`mt-1.5 inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-bold border transition-all ${
                            !hasActiveAlerts
                              ? 'bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100'
                              : highAlert
                                ? 'bg-rose-50 text-rose-700 border-rose-200 hover:bg-rose-100'
                                : 'bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100'
                          }`}
                        >
                          {hasActiveAlerts ? (
                            <>
                              <AlertTriangle className="h-2.5 w-2.5" />
                              {activeParaAlerts.length}
                            </>
                          ) : (
                            <CheckCircle2 className="h-2.5 w-2.5" />
                          )}
                          {alertsOpen ? (
                            <ChevronUp className="h-2.5 w-2.5" />
                          ) : (
                            <ChevronDown className="h-2.5 w-2.5" />
                          )}
                        </button>
                      )}
                      {customRevertedCount > 0 && (
                        <span className="mt-1 rounded bg-blue-50 px-1.5 py-0 text-[9.5px] font-semibold text-blue-700">
                          回退 {customRevertedCount}
                        </span>
                      )}

                      {/* Rich hover metric tooltip card (portaled to body — zero paint-containment clipping!) */}
                      {hoveredGutter?.index === para.index && (
                        <FloatingHoverCard
                          anchor={hoveredGutter.anchor}
                          width={216}
                          prefer="bottom"
                          onDismiss={dismissGutterHover}
                        >
                          <div className="flex justify-between">
                            <span className="text-slate-400">词数</span>
                            <span className="font-semibold text-white tabular-nums">
                              {para.old_word_count} → {para.new_word_count}
                            </span>
                          </div>
                          <div className="mt-1 flex justify-between">
                            <span className="text-slate-400">词序 LCS</span>
                            <span className="tabular-nums">{para.similarity}%</span>
                          </div>
                          <div className="mt-0.5 flex justify-between">
                            <span className="text-slate-400">词汇 Jaccard</span>
                            <span className="tabular-nums">{para.jaccard_similarity}%</span>
                          </div>
                          <div className="mt-0.5 flex justify-between">
                            <span className="text-slate-400">短语重合</span>
                            <span className="tabular-nums">{para.bigram_similarity}%</span>
                          </div>
                          {para.ai_isms_old.length > 0 && (
                            <div className="mt-1.5 border-t border-slate-700 pt-1.5 text-[10px] text-emerald-300">
                              旧版 AI 词：{para.ai_isms_old.slice(0, 5).join(', ')}
                            </div>
                          )}
                        </FloatingHoverCard>
                      )}
                    </div>

                    <div
                      data-diff-pane="right"
                      data-block-type={para.block_type}
                      data-list-depth={isListBlock ? listDepth : undefined}
                      data-quote-depth={isQuoteBlock ? quoteDepth : undefined}
                      style={textStyle}
                      className={`${proseFontClass} ${isTitle ? 'font-semibold' : ''} ${
                        isListBlock ? 'flex items-start gap-2' : ''
                      } ${isQuoteBlock ? 'pd-diff-quote' : ''} ${
                        isMathBlock && para.eq_number ? 'flex items-center justify-between gap-3' : ''
                      } text-[#1F2937] break-words`}
                    >
                      {isListBlock && para.new_clean && (
                        <span className="shrink-0 font-sans text-slate-400 select-none mt-[1px]">
                          {listMarker}
                        </span>
                      )}
                      <div className="min-w-0 flex-1">
                        {para.new_clean ? (
                          renderSplitRight(para.segments, isMathBlock)
                        ) : (
                          <span className="font-sans text-xs italic text-slate-300">
                            — 新版已删除 —
                          </span>
                        )}
                      </div>
                      {isMathBlock && para.eq_number && para.new_clean && (
                        <span className="shrink-0 font-serif text-xs text-slate-400 select-none">
                          ({para.eq_number})
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {/* VIEW 2: INLINE UNIFIED (Clean Book-Margin Style) */}
                {viewMode === 'inline' && !isTableBlock && (
                  <div className="relative">
                    <div className="mb-1.5 flex items-center justify-end gap-2 text-xs">
                      {aiReduced > 0 && (
                        <span className="inline-flex items-center gap-0.5 rounded-full bg-emerald-50 px-2 py-0.5 text-[10.5px] font-medium text-emerald-700">
                          <Sparkles className="h-3 w-3" /> 去 AI 词 -{aiReduced}
                        </span>
                      )}
                      {hasAlerts && (
                        <button
                          type="button"
                          onClick={() => onToggleParaAlerts(para.index)}
                          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-semibold border ${
                            !hasActiveAlerts
                              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                              : highAlert
                                ? 'bg-rose-50 text-rose-700 border-rose-200'
                                : 'bg-amber-50 text-amber-700 border-amber-200'
                          }`}
                        >
                          {hasActiveAlerts ? (
                            <>
                              <AlertTriangle className="h-3 w-3" />
                              {activeParaAlerts.length} 项告警
                            </>
                          ) : (
                            <>
                              <CheckCircle2 className="h-3 w-3" />
                              已核对
                            </>
                          )}
                        </button>
                      )}
                      <span
                        className={`rounded-md px-1.5 py-0.5 text-[11px] font-semibold tabular-nums ${deltaBadgeClass(
                          para.word_delta,
                        )}`}
                      >
                        {formatWordDelta(para.word_delta)}
                      </span>
                      <span className={`text-[11px] tabular-nums ${simColorClass(para.similarity_int)}`}>
                        相似 {para.similarity_int}%
                      </span>
                    </div>
                    <div
                      data-diff-pane="inline"
                      data-block-type={para.block_type}
                      data-list-depth={isListBlock ? listDepth : undefined}
                      data-quote-depth={isQuoteBlock ? quoteDepth : undefined}
                      style={textStyle}
                      className={`${proseFontClass} ${isTitle ? 'font-semibold' : ''} ${
                        isListBlock ? 'flex items-start gap-2' : ''
                      } ${isQuoteBlock ? 'pd-diff-quote' : ''} ${
                        isMathBlock && para.eq_number ? 'flex items-center justify-between gap-3' : ''
                      } text-[#1F2937] break-words`}
                    >
                      {isListBlock && (
                        <span className="shrink-0 font-sans text-slate-400 select-none mt-[1px]">
                          {listMarker}
                        </span>
                      )}
                      <div className="min-w-0 flex-1">{renderInline(para.segments, isMathBlock)}</div>
                      {isMathBlock && para.eq_number && (
                        <span className="shrink-0 font-serif text-xs text-slate-400 select-none">
                          ({para.eq_number})
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {/* Display Math Symbol-Level Diff Bar (V1.1 Fix!) */}
                {isMathBlock && para.math_diff && para.math_diff.length > 0 && viewMode !== 'source' && (
                  <div className="mt-3 rounded-xl border border-teal-200/70 bg-teal-50/40 px-3.5 py-2.5">
                    <div className="mb-1 text-[10.5px] font-semibold text-teal-800">
                      公式符号级变更明细（LaTeX）
                    </div>
                    <div className="font-mono text-[12px] leading-relaxed text-slate-700 break-all">
                      {para.math_diff.map((part, idx) => {
                        if (part.type === 'equal') return <span key={idx}> {part.text} </span>;
                        if (part.type === 'delete') {
                          return (
                            <span key={idx} className="diff-pill-del mx-0.5">
                              {part.text}
                            </span>
                          );
                        }
                        return (
                          <span key={idx} className="diff-pill-add mx-0.5">
                            {part.text}
                          </span>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* IN-PLACE DIAGNOSTIC STRIP with ✓ Acknowledge Toggle (v1.3) */}
                {hasAlerts && alertsOpen && (
                  <div className="mt-3.5 rounded-xl border border-rose-200/80 bg-rose-50/40 px-4 py-2.5 space-y-2">
                    {para.alerts.map((a) => (
                      <div
                        key={a.alert_id}
                        className={`flex items-start justify-between gap-3 text-xs ${
                          a.acked ? 'opacity-55' : ''
                        }`}
                      >
                        <div className="flex items-start gap-2 min-w-0">
                          <span
                            className={`mt-0.5 shrink-0 rounded px-1.5 py-0 text-[10px] font-bold ${
                              a.acked
                                ? 'bg-emerald-600 text-white'
                                : a.severity === 'high'
                                  ? 'bg-rose-600 text-white'
                                  : a.severity === 'medium'
                                    ? 'bg-amber-500 text-white'
                                    : 'bg-sky-600 text-white'
                            }`}
                          >
                            {a.acked
                              ? '已核对'
                              : a.severity === 'high'
                                ? '高风险'
                                : a.severity === 'medium'
                                  ? '需核对'
                                  : '提示'}
                          </span>
                          <span className={`font-semibold text-slate-800 shrink-0 ${a.acked ? 'line-through' : ''}`}>
                            {a.title}：
                          </span>
                          <span className="text-slate-600 break-words">{a.detail}</span>
                        </div>
                        <button
                          type="button"
                          onClick={() => onToggleAlertAck(a.alert_id)}
                          className={`shrink-0 inline-flex items-center gap-1 rounded-lg border px-2 py-0.5 text-[11px] font-medium transition-colors ${
                            a.acked
                              ? 'border-slate-200 bg-white text-slate-500 hover:text-slate-800'
                              : 'border-emerald-200 bg-white text-emerald-700 hover:bg-emerald-50'
                          }`}
                        >
                          <Check className="h-3 w-3" />
                          {a.acked ? '恢复告警' : '已核对无误'}
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                {/* IN-PLACE QUICK-FIX EDITOR */}
                {(editingPara === para.index || paragraphEdits[para.index] !== undefined) && (
                  <div className="mt-3 rounded-xl border border-blue-200 bg-blue-50/35 p-3">
                    <div className="mb-1.5 flex items-center justify-between text-xs">
                      <span className="font-semibold text-blue-900">
                        {editingPara === para.index ? '原地微调本段（将应用于融合稿与「存为新版本」）' : '已保存本段手动微调'}
                      </span>
                      <div className="flex items-center gap-2">
                        {editingPara !== para.index && (
                          <button
                            type="button"
                            onClick={() => {
                              setEditingPara(para.index);
                              setEditDraft(paragraphEdits[para.index]);
                            }}
                            className="text-blue-700 hover:underline font-medium"
                          >
                            继续编辑
                          </button>
                        )}
                        {paragraphEdits[para.index] !== undefined && (
                          <button
                            type="button"
                            onClick={() => {
                              onSaveParagraphEdit(para.index, null);
                              if (editingPara === para.index) setEditingPara(null);
                            }}
                            className="text-slate-500 hover:text-rose-600"
                          >
                            撤销微调
                          </button>
                        )}
                      </div>
                    </div>
                    {editingPara === para.index ? (
                      <>
                        <textarea
                          rows={4}
                          value={editDraft}
                          onChange={(e) => setEditDraft(e.target.value)}
                          className="w-full rounded-lg border border-blue-200 bg-white p-2.5 font-mono text-xs leading-relaxed text-slate-800 focus:border-blue-500 focus:outline-none"
                        />
                        <div className="mt-2 flex justify-end gap-2">
                          <button
                            type="button"
                            onClick={() => setEditingPara(null)}
                            className="rounded-lg border border-slate-200 bg-white px-3 py-1 text-xs text-slate-600 hover:bg-slate-50"
                          >
                            取消
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              onSaveParagraphEdit(para.index, editDraft);
                              setEditingPara(null);
                            }}
                            className="rounded-lg bg-blue-600 px-3 py-1 text-xs font-semibold text-white hover:bg-blue-700"
                          >
                            暂存本段修复
                          </button>
                        </div>
                      </>
                    ) : (
                      <pre className="whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed text-slate-700">
                        {paragraphEdits[para.index]}
                      </pre>
                    )}
                  </div>
                )}

                {/* Raw LaTeX Source Comparison */}
                {showRaw && (
                  <div
                    className={`${
                      viewMode === 'source' ? '' : 'mt-3 pt-3 border-t border-dashed border-slate-200'
                    } grid grid-cols-1 md:grid-cols-2 gap-3`}
                  >
                    <div className="rounded-lg bg-slate-50 border border-slate-200/70 p-3">
                      <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wider text-slate-400">
                        Old Raw Source
                      </div>
                      <pre className="whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed text-slate-600">
                        {para.old_raw || '（空）'}
                      </pre>
                    </div>
                    <div className="rounded-lg bg-slate-50 border border-slate-200/70 p-3">
                      <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wider text-slate-400">
                        New Raw Source
                      </div>
                      <pre className="whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed text-slate-700">
                        {para.new_raw || '（空）'}
                      </pre>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Popover-Driven Cherry-Pick Bubble (Prevents Accidental Clicks!) */}
      {popover && (
        <div
          data-hunk-popover="true"
          style={{
            position: 'fixed',
            left: `${popover.x}px`,
            top: `${popover.y}px`,
            transform: popover.placeBelow ? 'translate(-50%, 0)' : 'translate(-50%, -100%)',
          }}
          className="z-50 w-max max-w-[320px] rounded-xl border border-slate-200 bg-white p-2.5 shadow-[0_12px_36px_rgba(15,23,42,0.18)]"
        >
          <div className="mb-2 max-w-[290px] truncate text-[11px] text-slate-500">
            {popover.oldPreview && (
              <span className="line-through text-rose-700">{popover.oldPreview}</span>
            )}
            {popover.oldPreview && popover.newPreview && <span className="mx-1.5 text-slate-300">→</span>}
            {popover.newPreview && (
              <span className="font-medium text-emerald-700">{popover.newPreview}</span>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => {
                onSetHunkDecision(popover.hunkId, 'accept_new');
                setPopover(null);
              }}
              className={`flex-1 inline-flex items-center justify-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-colors ${
                (decisions[popover.hunkId] || 'accept_new') === 'accept_new'
                  ? 'bg-emerald-600 text-white'
                  : 'bg-slate-100 text-slate-700 hover:bg-emerald-50 hover:text-emerald-700'
              }`}
            >
              <Check className="h-3.5 w-3.5" />
              保留新版
            </button>
            <button
              type="button"
              onClick={() => {
                onSetHunkDecision(popover.hunkId, 'keep_old');
                setPopover(null);
              }}
              className={`flex-1 inline-flex items-center justify-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-colors ${
                decisions[popover.hunkId] === 'keep_old'
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-100 text-slate-700 hover:bg-blue-50 hover:text-blue-700'
              }`}
            >
              <RotateCcw className="h-3.5 w-3.5" />
              回退旧版
            </button>
          </div>
        </div>
      )}
      {/* Fullscreen Figure Lightbox Modal */}
      {lightbox && (
        <div
          className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-slate-950/80 backdrop-blur-sm p-6"
          onClick={() => setLightbox(null)}
        >
          <div
            className="relative flex max-h-[90vh] max-w-[92vw] flex-col items-center"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex w-full items-center justify-between gap-4 text-xs text-slate-200">
              <span className="truncate max-w-[70vw]">{lightbox.caption || '插图预览'}</span>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  type="button"
                  onClick={() => setLightbox((cur) => (cur ? { ...cur, invert: !cur.invert } : null))}
                  title="适用于黑白线条图/公式图夜间柔和反色"
                  className="rounded-lg bg-white/15 px-2.5 py-1 text-white hover:bg-white/25"
                >
                  {lightbox.invert ? '还原原色' : '线条反色'}
                </button>
                <button
                  type="button"
                  onClick={() => setLightbox((cur) => (cur ? { ...cur, fullSize: !cur.fullSize } : null))}
                  className="rounded-lg bg-white/15 px-2.5 py-1 text-white hover:bg-white/25"
                >
                  {lightbox.fullSize ? '适应屏幕' : '100% 原始尺寸'}
                </button>
                <button
                  type="button"
                  onClick={() => setLightbox(null)}
                  className="rounded-lg bg-white/15 p-1 text-white hover:bg-white/25"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
            <div className="paper-figure-frame overflow-auto rounded-2xl bg-white p-3 shadow-2xl max-h-[82vh] max-w-[90vw]">
              <img
                src={lightbox.src}
                alt={lightbox.caption}
                className={`${
                  lightbox.fullSize ? 'max-w-none' : 'max-h-[76vh] max-w-[85vw] object-contain'
                } ${lightbox.invert ? 'paper-figure-img-invert' : 'paper-figure-img'}`}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const PlainAcademicTable: React.FC<{
  label: string;
  rows: TablePlainCell[][];
  bibEntries?: Record<string, BibEntry>;
  latexMacros?: Record<string, string>;
  footnotes?: Record<string, string>;
}> = ({ label, rows, bibEntries, latexMacros, footnotes }) => (
  <div className="pd-table-wrap overflow-x-auto">
    <div className="mb-1.5 text-[11px] font-semibold text-slate-400">{label}</div>
    <table className="pd-table w-full border-collapse text-[12.5px] font-sans">
      <tbody>
        {rows.map((row, rIdx) => {
          const isHeader = rIdx === 0;
          const CellTag = isHeader ? 'th' : 'td';
          return (
            <tr
              key={rIdx}
              className={
                isHeader
                  ? 'pd-table-head'
                  : rIdx % 2 === 0
                    ? 'pd-table-row pd-table-row-stripe'
                    : 'pd-table-row'
              }
            >
              {row.map((cell, cIdx) => (
                <CellTag
                  key={cIdx}
                  colSpan={cell.colspan || 1}
                  rowSpan={cell.rowspan || 1}
                  className={`px-3 py-2 text-left align-top tabular-nums ${
                    cell.bold ? 'font-bold text-slate-900' : 'text-slate-700'
                  }`}
                >
                  {cell.items ? <TokenItems items={cell.items} bibEntries={bibEntries} latexMacros={latexMacros} footnotes={footnotes} /> : cell.text}
                </CellTag>
              ))}
            </tr>
          );
        })}
      </tbody>
    </table>
  </div>
);
