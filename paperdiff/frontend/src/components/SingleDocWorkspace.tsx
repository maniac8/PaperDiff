/**
 * @file SingleDocWorkspace.tsx
 * @description 60 FPS single-document academic reading, three-zone layout, Word dual-view toggle
 * (`学术精读 ⇄ Word 原版`), and full-element in-place editing canvas (paragraphs, headings, captions,
 * display math with live KaTeX preview, and interactive `TableGridEditor`).
 *
 * Performance & UI invariants:
 * - Zero React re-renders during scroll: progress hairline updates via direct DOM `rAF` `scaleX`,
 *   and sticky TOC tracks active headings via `IntersectionObserver`.
 * - Every block row is wrapped in `React.memo` (`SingleDocBlockRow`) + CSS `.pd-virtual-block`
 *   (`content-visibility: auto`) for locked 60 FPS on 400+ block / 2,750+ KaTeX documents.
 * - Footnotes render richly via `preview.footnote_items` (`TokenItems`) so internal markers never leak.
 * - Header width stays locked to `articleWidthStyle` across Word dual-view toggles to prevent jumps.
 */

import React, {
  Suspense,
  lazy,
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  AlertCircle,
  AlertTriangle,
  BookOpen,
  Check,
  CheckSquare,
  ChevronDown,
  ChevronRight,
  Clock,
  Copy,
  FileText,
  Image as ImageIcon,
  Info,
  Lightbulb,
  ListTree,
  Maximize2,
  MessageSquare,
  PanelLeftClose,
  Pencil,
  RotateCcw,
  Save,
  Sparkles,
  Square,
  Undo2,
  X,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import type {
  BibEntry,
  CitationStyle,
  DocLanguage,
  FontMode,
  ReadWidthMode,
  SingleDocBlock,
  SingleDocPreview,
  TablePlainCell,
  TypedPatchOp,
  TypographyPrefs,
} from '../types';
import {
  DEFAULT_TYPOGRAPHY_PREFS,
  getListBullet,
  getListPaddingPx,
  getParagraphGapClass,
  getParentListMarginPx,
  resolveBlockTypography,
} from '../utils/typography';
import { CodeBlock } from './CodeBlock';
import { TableGridEditor } from './TableGridEditor';
import { MathInline, TokenItems } from './TokenRenderer';

const MermaidBlock = lazy(() => import('./MermaidBlock'));
const DocxOriginalViewer = lazy(() => import('./DocxOriginalViewer'));

interface SingleDocWorkspaceProps {
  preview: SingleDocPreview;
  showSource: boolean;
  fontMode: FontMode;
  fontSize: number;
  readWidth: ReadWidthMode;
  typographyPrefs?: TypographyPrefs;
  showFigures: boolean;
  highlightAiIsms: boolean;
  searchQuery: string;
  paragraphEdits: Record<number, string>;
  pendingPatches: TypedPatchOp[];
  highlightedBlock: number | null;
  canSaveVersion: boolean;
  localProjectId?: number | null;
  externalUpdateNotice?: boolean;
  onReloadExternal?: () => void;
  onDismissExternalNotice?: () => void;
  onSplitTrackedDocx?: () => void;
  scrollContainerRef?: React.RefObject<HTMLElement | null>;
  onSaveBlockEdit: (blockIndex: number, text: string | null) => void;
  onAddPatch: (op: TypedPatchOp) => void;
  onRemovePatchAt: (index: number) => void;
  onOpenSaveModal: () => void;
  onResetEdits: () => void;
  onCopySource: () => void;
  onJumpToBlock?: (blockIndex: number) => void;
}

function formatBibClientStyle(entry: BibEntry | undefined, style: CitationStyle, fallback: string): string {
  if (!entry) return fallback;
  const author = (entry.author || '').trim();
  const year = (entry.year || '').trim();
  const title = (entry.title || '').trim();
  const venue = (entry.venue || '').trim();
  if (style === 'nature') {
    return [author ? `${author}.` : '', title ? `${title}.` : '', venue, year ? `(${year}).` : '']
      .filter(Boolean)
      .join(' ');
  }
  if (style === 'ieee') {
    return [author ? `${author},` : '', title ? `“${title},”` : '', venue ? `${venue},` : '', year ? `${year}.` : '']
      .filter(Boolean)
      .join(' ');
  }
  if (style === 'apa') {
    return [author, year ? `(${year}).` : '', title ? `${title}.` : '', venue ? `${venue}.` : '']
      .filter(Boolean)
      .join(' ');
  }
  return [author ? `${author}.` : '', title ? `${title}[J].` : '', venue ? `${venue},` : '', year ? `${year}.` : '']
    .filter(Boolean)
    .join(' ');
}

const CALLOUT_STYLES: Record<
  string,
  { label: string; border: string; bg: string; icon: React.ReactNode; titleColor: string }
> = {
  note: {
    label: 'NOTE',
    border: 'border-l-blue-500 border-blue-200/70',
    bg: 'bg-blue-50/55',
    titleColor: 'text-blue-700',
    icon: <Info className="w-3.5 h-3.5 text-blue-600" />,
  },
  tip: {
    label: 'TIP',
    border: 'border-l-emerald-500 border-emerald-200/70',
    bg: 'bg-emerald-50/55',
    titleColor: 'text-emerald-700',
    icon: <Lightbulb className="w-3.5 h-3.5 text-emerald-600" />,
  },
  important: {
    label: 'IMPORTANT',
    border: 'border-l-violet-500 border-violet-200/70',
    bg: 'bg-violet-50/55',
    titleColor: 'text-violet-700',
    icon: <Sparkles className="w-3.5 h-3.5 text-violet-600" />,
  },
  warning: {
    label: 'WARNING',
    border: 'border-l-amber-500 border-amber-200/70',
    bg: 'bg-amber-50/60',
    titleColor: 'text-amber-700',
    icon: <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />,
  },
  caution: {
    label: 'CAUTION',
    border: 'border-l-rose-500 border-rose-200/70',
    bg: 'bg-rose-50/60',
    titleColor: 'text-rose-700',
    icon: <AlertCircle className="w-3.5 h-3.5 text-rose-600" />,
  },
};

interface SingleDocBlockRowProps {
  blk: SingleDocBlock;
  allBlocks: SingleDocBlock[];
  isHighlighted: boolean;
  isEditing: boolean;
  editedVal: string | undefined;
  draftText: string;
  showFigures: boolean;
  highlightAiIsms: boolean;
  proseClass: string;
  proseStyle: React.CSSProperties;
  fontSize: number;
  docLanguage?: DocLanguage;
  typographyPrefs: TypographyPrefs;
  bibEntries?: Record<string, BibEntry>;
  latexMacros?: Record<string, string>;
  footnotes?: Record<string, string>;
  citationStyle: CitationStyle;
  compactTop?: boolean;
  pendingPatches: TypedPatchOp[];
  onBeginEdit: (blk: SingleDocBlock) => void;
  onDraftChange: (v: string) => void;
  onCommitEdit: (blk: SingleDocBlock) => void;
  onCancelEdit: () => void;
  onSaveBlockEdit: (blockIndex: number, text: string | null) => void;
  onAddPatch: (op: TypedPatchOp) => void;
  onOpenLightbox: (src: string, caption: string, label?: string) => void;
  onJumpToBlock: (idx: number) => void;
  onJumpToLabel: (label: string) => void;
  renderMetadataFormTable: (rows: TablePlainCell[][], insideCard?: boolean) => React.ReactNode;
}

const SingleDocBlockRow: React.FC<SingleDocBlockRowProps> = React.memo(
  ({
    blk,
    allBlocks,
    isHighlighted,
    isEditing,
    editedVal,
    draftText,
    showFigures,
    highlightAiIsms,
    proseClass,
    proseStyle,
    fontSize,
    docLanguage,
    typographyPrefs,
    bibEntries,
    latexMacros,
    footnotes,
    citationStyle,
    compactTop,
    pendingPatches,
    onBeginEdit,
    onDraftChange,
    onCommitEdit,
    onCancelEdit,
    onSaveBlockEdit,
    onAddPatch,
    onOpenLightbox,
    onJumpToBlock,
    onJumpToLabel,
    renderMetadataFormTable,
  }) => {
    const [issueOpen, setIssueOpen] = useState(true);
    const [commentOpen, setCommentOpen] = useState(false);

    const isEdited = editedVal !== undefined;
    const hasIssues = blk.issues && blk.issues.length > 0;
    const hasComments = blk.comments && blk.comments.length > 0;
    const virtCls = isEditing ? '' : 'pd-virtual-block';
    const typo = resolveBlockTypography(blk, docLanguage, typographyPrefs);
    const parentListMarginPx =
      typo.parentListDepth !== null ? getParentListMarginPx(typo.parentListDepth) : 0;

    // Horizontal Rule
    if (blk.block_type === 'hr') {
      return <hr className="my-7 border-slate-200/80" />;
    }

    // Section Heading (editable on double-click!)
    if (blk.block_type === 'heading') {
      const lvl = blk.section_level || 1;
      const cls =
        lvl <= 1
          ? 'mt-11 mb-2 pt-4 border-t border-slate-100/90 text-[20px] font-bold tracking-tight text-slate-950'
          : lvl === 2
            ? 'mt-8 mb-1.5 text-[17px] font-bold text-slate-900'
            : 'mt-5 mb-1 text-[14.5px] font-semibold text-slate-800';
      if (isEditing) {
        return (
          <div id={`para-${blk.index}`} className="my-4 rounded-xl border border-blue-300 bg-blue-50/30 p-3">
            <div className="mb-1.5 flex items-center justify-between text-[11px] text-blue-700">
              <span className="font-semibold">编辑章节标题</span>
              <span>Enter 暂存 · Esc 取消</span>
            </div>
            <input
              autoFocus
              value={draftText}
              onChange={(e) => onDraftChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') onCancelEdit();
                if (e.key === 'Enter') onCommitEdit(blk);
              }}
              className="w-full rounded-lg border border-blue-400 bg-white px-3 py-1.5 text-[16px] font-bold text-slate-900 outline-none"
            />
            <div className="mt-2 flex justify-end gap-2">
              <button
                type="button"
                onClick={onCancelEdit}
                className="rounded-lg border border-slate-200 px-2.5 py-1 text-xs text-slate-600"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => onCommitEdit(blk)}
                className="rounded-lg bg-blue-600 px-3 py-1 text-xs font-semibold text-white"
              >
                暂存标题
              </button>
            </div>
          </div>
        );
      }
      const headAlignCls =
        blk.style?.align === 'center'
          ? 'justify-center text-center'
          : blk.style?.align === 'right'
            ? 'justify-end text-right'
            : '';
      return (
        <h2
          id={`para-${blk.index}`}
          onDoubleClick={() => onBeginEdit(blk)}
          className={`${virtCls} ${cls} ${headAlignCls} group flex flex-wrap items-center gap-2 scroll-mt-20 transition-colors cursor-text ${
            isHighlighted ? 'rounded-lg bg-blue-50/70 px-2 -mx-2' : ''
          }`}
        >
          <span>
            {isEdited ? (
              <span className="text-blue-700">{editedVal.replace(/^#+\s*/, '')}</span>
            ) : (
              <TokenItems
                items={blk.items}
                bibEntries={bibEntries}
                latexMacros={latexMacros}
                footnotes={footnotes}
                onJumpToLabel={onJumpToLabel}
              />
            )}
          </span>
          {blk.zone === 'backmatter' && (
            <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[10.5px] font-medium text-slate-500">
              后置与文献区
            </span>
          )}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onBeginEdit(blk);
            }}
            className="opacity-0 group-hover:opacity-100 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-blue-600 transition"
            title="编辑章节标题"
          >
            <Pencil className="w-3 h-3" />
          </button>
        </h2>
      );
    }

    // Fenced Code Block or Mermaid Diagram
    if (blk.block_type === 'code') {
      return (
        <div
          id={`para-${blk.index}`}
          data-parent-list-depth={typo.parentListDepth ?? undefined}
          style={parentListMarginPx > 0 ? { marginLeft: `${parentListMarginPx}px` } : undefined}
          className={`${virtCls} my-4 scroll-mt-20 ${isHighlighted ? 'ring-2 ring-blue-400/60 rounded-xl' : ''}`}
        >
          {blk.is_diagram ? (
            <Suspense fallback={<div className="py-6 text-center text-xs text-slate-400">加载流程图引擎…</div>}>
              <MermaidBlock code={blk.clean_text} />
            </Suspense>
          ) : (
            <CodeBlock code={blk.clean_text} lang={blk.code_lang} />
          )}
        </div>
      );
    }

    // Theorem / Lemma / Definition / Proof Academic Box
    if (blk.block_type === 'theorem') {
      const tm = blk.theorem_meta;
      const headLbl = `${tm?.theorem_title || 'Theorem'}${tm?.theorem_num ? ` ${tm.theorem_num}` : ''}${
        tm?.optional_title ? ` (${tm.optional_title})` : ''
      }`;
      return (
        <div
          id={`para-${blk.index}`}
          className={`${virtCls} pd-theorem-box my-4 rounded-r-lg border border-l-0 border-slate-200/90 bg-slate-50/60 pl-5 pr-4 py-3 scroll-mt-20 ${
            isHighlighted ? 'ring-2 ring-blue-400/60' : ''
          }`}
        >
          <div className="mb-1 flex items-center justify-between">
            <span className="font-semibold text-[14px] text-slate-900">{headLbl}.</span>
            {tm?.is_proof && <span className="font-mono text-xs text-slate-400">□</span>}
          </div>
          <div className={`${proseClass} text-[14.5px] leading-relaxed ${tm?.is_proof ? '' : 'italic'}`} style={{ fontSize: `${Math.max(13.5, fontSize - 0.5)}px` }}>
            <TokenItems
              items={blk.items}
              bibEntries={bibEntries}
              latexMacros={latexMacros}
              footnotes={footnotes}
              onJumpToLabel={onJumpToLabel}
            />
          </div>
        </div>
      );
    }

    // Algorithm Pseudocode Card
    if (blk.block_type === 'algorithm') {
      const am = blk.algorithm_meta;
      return (
        <div
          id={`para-${blk.index}`}
          className={`${virtCls} pd-algorithm-box my-5 rounded-none border-y-2 border-slate-800 bg-white/90 px-4 py-3 scroll-mt-20 ${
            isHighlighted ? 'ring-2 ring-blue-400/60' : ''
          }`}
        >
          <div className="border-b border-slate-200 pb-1.5 mb-2 font-semibold text-[13.5px] text-slate-900">
            Algorithm {am?.alg_num || ''}{am?.caption ? `: ${am.caption}` : ''}
          </div>
          <div className="space-y-1 font-mono text-[12.5px] leading-relaxed text-slate-800">
            {(am?.lines || []).map((ln, li) => (
              <div key={li} className="flex items-baseline gap-2.5">
                <span className="w-5 shrink-0 select-none text-right text-[11px] text-slate-400 tabular-nums">
                  {li + 1}:
                </span>
                <div style={{ paddingLeft: `${(ln.indent || 0) * 18}px` }}>
                  <TokenItems
                    items={ln.items || [{ kind: 'text', text: ln.text }]}
                    bibEntries={bibEntries}
                    latexMacros={latexMacros}
                    footnotes={footnotes}
                    onJumpToLabel={onJumpToLabel}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      );
    }

    // Blockquote / GitHub Callout Card
    if (blk.block_type === 'blockquote') {
      const callout = blk.callout_type ? CALLOUT_STYLES[blk.callout_type] : null;
      if (callout) {
        return (
          <div
            id={`para-${blk.index}`}
            className={`${virtCls} pd-callout my-4 rounded-r-xl border border-l-[3.5px] px-4 py-3 scroll-mt-20 ${callout.border} ${callout.bg} ${
              isHighlighted ? 'ring-2 ring-blue-400/60' : ''
            }`}
          >
            <div className={`mb-1 flex items-center gap-1.5 text-[11.5px] font-bold tracking-wider ${callout.titleColor}`}>
              {callout.icon}
              <span>{callout.label}</span>
            </div>
            <div className="text-[14px] leading-relaxed text-slate-700">
              <TokenItems
                items={blk.items}
                bibEntries={bibEntries}
                latexMacros={latexMacros}
                footnotes={footnotes}
                onJumpToLabel={onJumpToLabel}
                highlightAiIsms={highlightAiIsms}
                aiIsms={blk.ai_isms}
              />
            </div>
          </div>
        );
      }
      const quoteDepth = typo.quoteDepth || 1;
      const quoteDepthCls = quoteDepth >= 2 ? `pd-blockquote-d${quoteDepth}` : '';
      const quoteMarginLeftPx = parentListMarginPx + (quoteDepth - 1) * 18;
      const quoteStyle: React.CSSProperties = {
        ...(quoteMarginLeftPx > 0 ? { marginLeft: `${quoteMarginLeftPx}px` } : {}),
        ...(typo.paddingLeftEm > 0 && quoteDepth === 1 ? { paddingLeft: `${Math.max(1.25, typo.paddingLeftEm)}em` } : {}),
        ...(typo.paddingRightEm > 0 ? { paddingRight: `${Math.max(1.25, typo.paddingRightEm)}em` } : {}),
        lineHeight: typo.lineHeight,
      };
      return (
        <blockquote
          id={`para-${blk.index}`}
          data-quote-depth={quoteDepth}
          data-parent-list-depth={typo.parentListDepth ?? undefined}
          style={quoteStyle}
          className={`${virtCls} pd-blockquote ${quoteDepthCls} my-4 text-[14px] scroll-mt-20 ${
            isHighlighted ? 'ring-2 ring-blue-400/60' : ''
          }`}
        >
          <TokenItems
            items={blk.items}
            bibEntries={bibEntries}
            latexMacros={latexMacros}
            footnotes={footnotes}
            onJumpToLabel={onJumpToLabel}
            highlightAiIsms={highlightAiIsms}
            aiIsms={blk.ai_isms}
          />
        </blockquote>
      );
    }

    // Reference Bibliography Item (Supports 4 citation styles dynamically when bib_entry exists!)
    if (blk.block_type === 'reference_item') {
      const rnum = blk.ref_meta?.ref_num;
      const bibEntry = blk.ref_meta?.bib_entry;
      return (
        <p
          id={`para-${blk.index}`}
          className={`${virtCls} pd-ref-item text-[13.5px] text-slate-700 scroll-mt-20 ${
            compactTop ? '!mt-1.5' : ''
          } ${isHighlighted ? 'rounded-lg bg-blue-50/70 px-2' : ''}`}
        >
          {rnum !== null && rnum !== undefined && (
            <span className="mr-1.5 font-mono text-[12px] font-semibold text-slate-400 tabular-nums">
              [{rnum}]
            </span>
          )}
          {bibEntry && citationStyle !== 'gbt7714' ? (
            <span>{formatBibClientStyle(bibEntry, citationStyle, blk.clean_text)}</span>
          ) : (
            <TokenItems
              items={blk.items}
              bibEntries={bibEntries}
              latexMacros={latexMacros}
              footnotes={footnotes}
              onJumpToLabel={onJumpToLabel}
            />
          )}
        </p>
      );
    }

    // Figure Block (Single or Multi-Subfigure Grid!)
    if (blk.block_type === 'figure') {
      const fi = blk.figure_info;
      const subImages = fi?.images && fi.images.length > 0
        ? fi.images
        : fi?.asset_key
          ? [{ asset_key: fi.asset_key, image_path: fi.image_path, subcaption: '', label: fi.label }]
          : [];
      return (
        <figure
          id={`para-${blk.index}`}
          className={`${virtCls} my-7 w-full rounded-2xl border border-slate-200/75 bg-[#FAFBFD] p-5 transition-all scroll-mt-20 ${
            isHighlighted ? 'ring-2 ring-blue-400/60' : ''
          }`}
        >
          {showFigures && subImages.length > 0 ? (
            <div
              className={
                subImages.length > 1
                  ? `grid gap-4 ${subImages.length === 2 ? 'grid-cols-1 sm:grid-cols-2' : 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3'}`
                  : 'flex flex-col items-center'
              }
            >
              {subImages.map((im, imIdx) => {
                const url = im.asset_key ? `/api/assets/${im.asset_key}` : null;
                return (
                  <div key={imIdx} className="flex flex-col items-center">
                    {url ? (
                      <div
                        onClick={() => onOpenLightbox(url, im.subcaption || blk.clean_text, im.label || im.image_path)}
                        className="paper-figure-frame group/img relative cursor-zoom-in overflow-hidden rounded-xl border border-slate-200/60 bg-white p-2.5 shadow-2xs"
                      >
                        <img
                          src={url}
                          loading="lazy"
                          decoding="async"
                          alt={im.image_path || `figure-${imIdx + 1}`}
                          className="paper-figure-img max-h-[380px] w-auto object-contain rounded"
                        />
                        <span className="pointer-events-none absolute right-2.5 top-2.5 inline-flex items-center gap-1 rounded-md bg-slate-900/75 px-2 py-0.5 text-[10.5px] font-medium text-white opacity-0 group-hover/img:opacity-100 transition-opacity">
                          <Maximize2 className="h-3 w-3" />
                          放大查看
                        </span>
                      </div>
                    ) : (
                      <div className="flex items-center justify-center gap-2 rounded-xl border border-dashed border-slate-200 bg-white px-4 py-6 text-xs text-slate-400 w-full">
                        <ImageIcon className="h-4 w-4" />
                        <span>{im.image_path || '未嵌入子图'}</span>
                      </div>
                    )}
                    {im.subcaption && (
                      <div className="mt-1.5 text-center text-[12px] text-slate-500">
                        ({String.fromCharCode(97 + imIdx)}) {im.subcaption}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : showFigures ? (
            <div className="flex items-center justify-center gap-2 rounded-xl border border-dashed border-slate-200 bg-white py-6 text-xs text-slate-400">
              <ImageIcon className="h-4 w-4" />
              <span>插图占位：{fi?.image_path || fi?.label || '未嵌入图片文件'}</span>
            </div>
          ) : null}

          {blk.clean_text && (
            <figcaption className="mt-3.5 text-[13.5px] leading-relaxed text-slate-600 px-1">
              <TokenItems
                items={blk.items}
                bibEntries={bibEntries}
                latexMacros={latexMacros}
                footnotes={footnotes}
                onJumpToLabel={onJumpToLabel}
                highlightAiIsms={highlightAiIsms}
                aiIsms={blk.ai_isms}
              />
            </figcaption>
          )}
        </figure>
      );
    }

    // Table: Metadata Form Card vs Interactive Visual TableGridEditor!
    if (blk.block_type === 'table' && blk.table_rows && blk.table_rows.length > 0) {
      return (
        <div
          id={`para-${blk.index}`}
          className={`${virtCls} my-6 w-full rounded-xl transition-all scroll-mt-20 ${
            isHighlighted ? 'ring-2 ring-blue-400/60 p-2' : ''
          }`}
        >
          {blk.table_role === 'metadata_form' ? (
            renderMetadataFormTable(blk.table_rows)
          ) : (
            <TableGridEditor
              block={blk}
              allBlocks={allBlocks}
              bibEntries={bibEntries}
              latexMacros={latexMacros}
              footnotes={footnotes}
              pendingPatches={pendingPatches}
              onAddPatch={onAddPatch}
              onJumpToBlock={onJumpToBlock}
              onJumpToLabel={onJumpToLabel}
            />
          )}
        </div>
      );
    }

    // Display Math Block (Double-Click for Live KaTeX Math Editor!)
    if (blk.block_type === 'math') {
      if (isEditing) {
        const previewExpr = draftText
          .replace(/^\\begin\{[^}]+\}|\\end\{[^}]+\}$/g, '')
          .replace(/^\$\$|\$\$$/g, '')
          .replace(/^\\\[|\\\]$/g, '')
          .trim();
        return (
          <div id={`para-${blk.index}`} className="my-4 rounded-xl border border-blue-300 bg-blue-50/25 p-4 space-y-2.5">
            <div className="flex items-center justify-between text-[11px] text-blue-700">
              <span className="font-semibold">编辑独立公式（实时 KaTeX 渲染预览）</span>
              <span>⌘↵ 暂存 · Esc 取消</span>
            </div>
            <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-center overflow-x-auto">
              <MathInline expr={previewExpr} displayMode={true} latexMacros={latexMacros} />
            </div>
            <textarea
              rows={3}
              autoFocus
              value={draftText}
              onChange={(e) => onDraftChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') onCancelEdit();
                if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') onCommitEdit(blk);
              }}
              className="w-full rounded-lg border border-blue-300 bg-white p-2.5 font-mono text-[12.5px] text-slate-800 outline-none"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={onCancelEdit}
                className="rounded-lg border border-slate-200 px-3 py-1 text-xs text-slate-600"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => onCommitEdit(blk)}
                className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1 text-xs font-semibold text-white"
              >
                <Check className="w-3.5 h-3.5" /> 暂存公式
              </button>
            </div>
          </div>
        );
      }

      const displayTex = isEdited
        ? editedVal
            .replace(/^\\begin\{[^}]+\}|\\end\{[^}]+\}$/g, '')
            .replace(/^\$\$|\$\$$/g, '')
            .trim()
        : null;

      return (
        <div
          id={`para-${blk.index}`}
          data-parent-list-depth={typo.parentListDepth ?? undefined}
          style={parentListMarginPx > 0 ? { marginLeft: `${parentListMarginPx}px` } : undefined}
          onDoubleClick={() => onBeginEdit(blk)}
          className={`${virtCls} pd-math-box group my-4 flex items-center justify-between gap-4 rounded-xl bg-[#FAFBFD] border border-slate-200/70 px-5 py-3 transition-all scroll-mt-20 cursor-pointer ${
            isHighlighted ? 'ring-2 ring-blue-400/60' : isEdited ? 'border-blue-400 bg-blue-50/20' : ''
          }`}
        >
          <div className="flex-1 overflow-x-auto text-center">
            {displayTex !== null ? (
              <MathInline expr={displayTex} displayMode={true} latexMacros={latexMacros} />
            ) : (
              <TokenItems
                items={blk.items}
                displayMath={true}
                latexMacros={latexMacros}
              />
            )}
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onBeginEdit(blk);
              }}
              title="编辑公式"
              className="opacity-0 group-hover:opacity-100 rounded p-1 text-slate-400 hover:bg-slate-200/60 hover:text-blue-600 transition"
            >
              <Pencil className="w-3.5 h-3.5" />
            </button>
            {blk.eq_number && (
              <span className="font-academic-serif text-sm text-slate-400 tabular-nums">
                ({blk.eq_number})
              </span>
            )}
          </div>
        </div>
      );
    }

    // List Item / Paragraph / Caption
    const isList = blk.block_type === 'list';
    const isCaption = blk.block_type === 'caption';
    const taskChecked = blk.list_meta?.checked;
    const listDepth = Math.min(5, Math.max(0, blk.list_meta?.depth || 0));
    const paraStyle: React.CSSProperties = {
      ...proseStyle,
      lineHeight: typo.lineHeight,
      textAlign: typo.textAlign,
      textIndent: typo.textIndentEm !== 0 ? `${typo.textIndentEm}em` : '0',
      ...(typo.paddingLeftEm > 0 ? { paddingLeft: `${typo.paddingLeftEm}em` } : {}),
      ...(typo.paddingRightEm > 0 ? { paddingRight: `${typo.paddingRightEm}em` } : {}),
    };
    const captionStyle: React.CSSProperties | undefined =
      isCaption && blk.style?.align ? { textAlign: blk.style.align } : undefined;

    return (
      <div
        id={`para-${blk.index}`}
        data-block-type={blk.block_type}
        data-semantic-role={typo.isAbstract ? 'abstract' : undefined}
        data-parent-list-depth={typo.parentListDepth ?? undefined}
        style={!isList && parentListMarginPx > 0 ? { marginLeft: `${parentListMarginPx}px` } : undefined}
        onDoubleClick={() => onBeginEdit(blk)}
        className={`${virtCls} group relative rounded-xl px-3.5 ${
          isList ? (compactTop ? '!mt-1 py-0.5' : 'py-0.5') : 'py-1.5'
        } -mx-3.5 transition-colors scroll-mt-20 ${
          isHighlighted
            ? 'bg-blue-50/70 ring-1 ring-blue-300'
            : isEdited
              ? 'border-l-[3px] border-blue-500 bg-blue-50/25 pl-4'
              : 'hover:bg-slate-50/65'
        }`}
      >
        {!isEditing && (
          <div className="absolute right-2 top-1.5 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
            {isEdited && (
              <span className="rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-semibold text-blue-700">
                已微调
              </span>
            )}
            {hasComments && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setCommentOpen((v) => !v);
                }}
                className="inline-flex items-center gap-0.5 rounded bg-amber-50 px-1.5 py-0.5 text-[10.5px] font-semibold text-amber-700 border border-amber-200"
              >
                <MessageSquare className="h-3 w-3" />
                {blk.comments!.length}
              </button>
            )}
            {hasIssues && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setIssueOpen((v) => !v);
                }}
                className="inline-flex items-center gap-0.5 rounded bg-rose-50 px-1.5 py-0.5 text-[10.5px] font-semibold text-rose-700 border border-rose-200"
              >
                <AlertTriangle className="h-3 w-3" />
                {blk.issues.length}
              </button>
            )}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onBeginEdit(blk);
              }}
              title="原位微调此段（也可直接双击正文）"
              className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-600 shadow-2xs hover:border-blue-300 hover:text-blue-700"
            >
              <Pencil className="h-3 w-3" />
              微调
            </button>
          </div>
        )}

        {isEditing ? (
          <div className="space-y-2 py-1" onDoubleClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between text-[11px] text-slate-500">
              <span className="font-semibold text-blue-700">
                原位微调（保存后自动按原格式无损写回）
              </span>
              <span className="text-slate-400">⌘↵ 暂存 · Esc 取消</span>
            </div>
            <textarea
              rows={Math.min(10, Math.max(3, Math.ceil(draftText.length / 82)))}
              value={draftText}
              onChange={(e) => onDraftChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') onCancelEdit();
                if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') onCommitEdit(blk);
              }}
              autoFocus
              className="w-full rounded-xl border border-blue-300 bg-white p-3 font-mono text-[12.5px] leading-relaxed text-slate-800 shadow-xs focus:border-blue-500 focus:outline-none"
            />
            <div className="flex items-center justify-between">
              <div>
                {isEdited && (
                  <button
                    type="button"
                    onClick={() => {
                      onSaveBlockEdit(blk.index, null);
                      onCancelEdit();
                    }}
                    className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-rose-600 hover:bg-rose-50"
                  >
                    <RotateCcw className="h-3 w-3" />
                    恢复原稿
                  </button>
                )}
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={onCancelEdit}
                  className="rounded-lg border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={() => onCommitEdit(blk)}
                  className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1 text-xs font-semibold text-white hover:bg-blue-700"
                >
                  <Check className="h-3.5 w-3.5" />
                  暂存微调 (⌘↵)
                </button>
              </div>
            </div>
          </div>
        ) : isEdited ? (
          <div>
            <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold text-blue-700">
              <Pencil className="h-3 w-3" />
              已原位微调（双击继续编辑）
            </div>
            <p className={`${proseClass} pd-prose-academic whitespace-pre-wrap`} style={paraStyle}>
              {editedVal}
            </p>
          </div>
        ) : isList ? (
          <div
            data-list-depth={listDepth}
            className="flex items-baseline gap-2.5"
            style={{ paddingLeft: `${getListPaddingPx(listDepth)}px` }}
          >
            <span
              className="min-w-[22px] shrink-0 select-none font-sans font-medium text-slate-500 tabular-nums text-right pr-0.5 inline-flex justify-end items-center"
              style={{ fontSize: `${Math.max(13, fontSize - 1)}px` }}
            >
              {taskChecked === true ? (
                <CheckSquare className="w-3.5 h-3.5 text-emerald-600" />
              ) : taskChecked === false ? (
                <Square className="w-3.5 h-3.5 text-slate-400" />
              ) : blk.list_meta?.ordered ? (
                `${blk.list_meta.item_num}.`
              ) : (
                getListBullet(listDepth)
              )}
            </span>
            <div className={`${proseClass} pd-prose-academic flex-1`} style={proseStyle}>
              <TokenItems
                items={blk.items}
                bibEntries={bibEntries}
                latexMacros={latexMacros}
                footnotes={footnotes}
                onJumpToLabel={onJumpToLabel}
                highlightAiIsms={highlightAiIsms}
                aiIsms={blk.ai_isms}
              />
            </div>
          </div>
        ) : (
          <p
            lang={typo.hyphenate ? 'en' : undefined}
            className={
              isCaption
                ? 'text-[13.5px] leading-relaxed text-slate-500'
                : `${proseClass} pd-prose-academic ${typo.hyphenate ? 'pd-prose-hyphen' : ''} ${
                    typo.isAbstract ? 'pd-abstract-box' : ''
                  }`
            }
            style={isCaption ? captionStyle : paraStyle}
          >
            <TokenItems
              items={blk.items}
              bibEntries={bibEntries}
              latexMacros={latexMacros}
              footnotes={footnotes}
              onJumpToLabel={onJumpToLabel}
              highlightAiIsms={highlightAiIsms}
              aiIsms={blk.ai_isms}
            />
          </p>
        )}

        {/* Word Reviewer Comments Badge & Expandable Notes */}
        {hasComments && (commentOpen || blk.comments!.length <= 2) && (
          <div className="mt-2 space-y-1 rounded-xl border border-amber-200/80 bg-amber-50/55 px-3 py-2 text-[12px]">
            {blk.comments!.map((c) => (
              <div key={c.id} className="flex items-start gap-2">
                <MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />
                <div className="min-w-0">
                  <span className="font-semibold text-amber-900">{c.author}</span>
                  {c.date && <span className="ml-1.5 text-[10.5px] text-amber-700/70">{c.date}</span>}
                  <span className="mx-1 text-amber-400">·</span>
                  <span className="text-slate-700">{c.text}</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {hasIssues && issueOpen && (
          <div className="mt-2.5 space-y-1.5 rounded-xl border border-rose-200/80 bg-rose-50/50 px-3.5 py-2.5 text-xs">
            {blk.issues.map((iss) => (
              <div key={iss.issue_id} className="flex items-start gap-2">
                <AlertTriangle
                  className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${
                    iss.severity === 'high' ? 'text-rose-600' : 'text-amber-600'
                  }`}
                />
                <div className="min-w-0">
                  <span className="font-semibold text-slate-800">{iss.title}：</span>
                  <span className="text-slate-600">{iss.detail}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  },
);
SingleDocBlockRow.displayName = 'SingleDocBlockRow';

export const SingleDocWorkspace: React.FC<SingleDocWorkspaceProps> = ({
  preview,
  showSource,
  fontMode,
  fontSize,
  readWidth,
  typographyPrefs = DEFAULT_TYPOGRAPHY_PREFS,
  showFigures,
  highlightAiIsms,
  searchQuery,
  paragraphEdits,
  pendingPatches,
  highlightedBlock,
  canSaveVersion,
  localProjectId = null,
  externalUpdateNotice = false,
  onReloadExternal,
  onDismissExternalNotice,
  onSplitTrackedDocx,
  scrollContainerRef,
  onSaveBlockEdit,
  onAddPatch,
  onRemovePatchAt,
  onOpenSaveModal,
  onResetEdits,
  onCopySource,
  onJumpToBlock,
}) => {
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [draftText, setDraftText] = useState('');
  const [showInlineToc, setShowInlineToc] = useState(true);
  const [frontmatterOpen, setFrontmatterOpen] = useState(false);
  const [activeSecIdx, setActiveSecIdx] = useState<number>(0);
  const [docxViewMode, setDocxViewMode] = useState<'academic' | 'original'>('academic');
  const [citationStyle, setCitationStyle] = useState<CitationStyle>('gbt7714');
  const [draftDockExpanded, setDraftDockExpanded] = useState(false);
  const [lightbox, setLightbox] = useState<{ src: string; caption: string; label?: string } | null>(
    null,
  );
  const [lightboxFull, setLightboxFull] = useState(false);
  const [lightboxInvert, setLightboxInvert] = useState(false);

  const rootRef = useRef<HTMLDivElement | null>(null);
  const progressBarRef = useRef<HTMLDivElement | null>(null);

  // Reset Word view mode when switching documents
  useEffect(() => {
    setDocxViewMode('academic');
  }, [preview.version.id, preview.local_rel_path]);

  useEffect(() => {
    if (!lightbox) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setLightbox(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [lightbox]);

  // HIGH-PERFORMANCE SCROLL PROGRESS BAR: Direct DOM transform inside rAF (0 React re-renders per frame!)
  useEffect(() => {
    if (showSource || docxViewMode === 'original') return;
    const scroller =
      scrollContainerRef?.current ||
      (rootRef.current?.closest('main') as HTMLElement | null);
    if (!scroller) return;

    let rafId = 0;
    const updateProgress = () => {
      rafId = 0;
      const bar = progressBarRef.current;
      if (!bar) return;
      const maxScroll = scroller.scrollHeight - scroller.clientHeight;
      const ratio = maxScroll > 20 ? Math.min(1, Math.max(0, scroller.scrollTop / maxScroll)) : 0;
      bar.style.transform = `scaleX(${ratio})`;
    };

    const onScroll = () => {
      if (!rafId) {
        rafId = window.requestAnimationFrame(updateProgress);
      }
    };

    updateProgress();
    scroller.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      scroller.removeEventListener('scroll', onScroll);
      if (rafId) window.cancelAnimationFrame(rafId);
    };
  }, [showSource, docxViewMode, scrollContainerRef, preview.version.id]);

  // HIGH-PERFORMANCE TOC SCROLL-SPY: IntersectionObserver (0 getBoundingClientRect() loops!)
  useEffect(() => {
    if (showSource || docxViewMode === 'original' || preview.sections.length <= 1) return;
    const scroller =
      scrollContainerRef?.current ||
      (rootRef.current?.closest('main') as HTMLElement | null);
    if (!scroller) return;

    const idToSecIdx = new Map<string, number>();
    preview.sections.forEach((sec, idx) => {
      idToSecIdx.set(`para-${sec.first_block_index}`, idx);
    });

    const observer = new IntersectionObserver(
      (entries) => {
        let bestIdx: number | null = null;
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const idx = idToSecIdx.get(entry.target.id);
            if (idx !== undefined && (bestIdx === null || idx < bestIdx)) {
              bestIdx = idx;
            }
          }
        }
        if (bestIdx !== null) {
          setActiveSecIdx((prev) => (prev === bestIdx ? prev : bestIdx!));
        }
      },
      {
        root: scroller,
        rootMargin: '-10% 0px -75% 0px',
        threshold: 0,
      },
    );

    preview.sections.forEach((sec) => {
      const el = document.getElementById(`para-${sec.first_block_index}`);
      if (el) observer.observe(el);
    });

    return () => observer.disconnect();
  }, [preview.sections, showSource, docxViewMode, scrollContainerRef]);

  const proseClass =
    fontMode === 'serif'
      ? 'font-academic-serif text-[#1E2530]'
      : 'font-academic-sans text-[#1E2530]';
  const proseStyle = useMemo<React.CSSProperties>(
    () => ({ fontSize: `${fontSize}px`, lineHeight: typographyPrefs.lineHeight }),
    [fontSize, typographyPrefs.lineHeight],
  );

  // Deferred search query so typing never blocks large 50k-word documents
  const deferredSearch = useDeferredValue(searchQuery);
  const q = deferredSearch.trim().toLowerCase();
  const estMinutes = Math.max(1, Math.round(preview.summary.word_count / 260));
  const hasToc = preview.sections.length > 1 && docxViewMode === 'academic';
  const hasDocxBlob =
    preview.format === 'docx' &&
    (Boolean(preview.version.id > 0 && preview.version.source_blob_key) ||
      Boolean(preview.mode === 'local_folder' && localProjectId && preview.local_rel_path));

  const visibleBlocks = useMemo(() => {
    if (!q) return preview.blocks;
    return preview.blocks.filter(
      (b) =>
        b.block_type === 'heading' ||
        b.block_type === 'title' ||
        b.clean_text.toLowerCase().includes(q) ||
        b.raw_text.toLowerCase().includes(q) ||
        b.ai_isms.some((w) => w.toLowerCase().includes(q)),
    );
  }, [preview.blocks, q]);

  const titleBlock = useMemo(
    () => visibleBlocks.find((b) => b.block_type === 'title') || null,
    [visibleBlocks],
  );
  const frontmatterBlocks = useMemo(
    () => visibleBlocks.filter((b) => b.block_type !== 'title' && b.zone === 'frontmatter'),
    [visibleBlocks],
  );
  const bodyBlocks = useMemo(
    () => visibleBlocks.filter((b) => b.block_type !== 'title' && b.zone !== 'frontmatter'),
    [visibleBlocks],
  );

  const firstRefIndex = useMemo(() => {
    const found = bodyBlocks.find((b) => b.block_type === 'reference_item');
    return found ? found.index : -1;
  }, [bodyBlocks]);

  // Build label -> block_index lookup map for clickable \ref jumps
  const labelToBlockIndex = useMemo(() => {
    const m = new Map<string, number>();
    for (const b of preview.blocks) {
      if (b.label) m.set(b.label, b.index);
      if (b.figure_info?.label) m.set(b.figure_info.label, b.index);
      if (b.theorem_meta?.label) m.set(b.theorem_meta.label, b.index);
      if (b.algorithm_meta?.label) m.set(b.algorithm_meta.label, b.index);
      if (b.figure_info?.images) {
        for (const sub of b.figure_info.images) {
          if (sub.label) m.set(sub.label, b.index);
        }
      }
    }
    return m;
  }, [preview.blocks]);

  const jumpTo = useCallback(
    (idx: number) => {
      if (onJumpToBlock) {
        onJumpToBlock(idx);
        return;
      }
      const el = document.getElementById(`para-${idx}`);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    },
    [onJumpToBlock],
  );

  const handleJumpToLabel = useCallback(
    (label: string) => {
      const targetIdx = labelToBlockIndex.get(label);
      if (targetIdx !== undefined) {
        jumpTo(targetIdx);
      }
    },
    [labelToBlockIndex, jumpTo],
  );

  const beginEdit = useCallback(
    (blk: SingleDocBlock) => {
      if (blk.block_type === 'table' || blk.block_type === 'hr' || blk.block_type === 'code') return;
      setEditingIndex(blk.index);
      setDraftText(paragraphEdits[blk.index] ?? blk.raw_text);
    },
    [paragraphEdits],
  );

  const commitEdit = useCallback(
    (blk: SingleDocBlock) => {
      const trimmed = draftText.trim();
      if (!trimmed || trimmed === blk.raw_text.trim()) {
        onSaveBlockEdit(blk.index, null);
      } else {
        onSaveBlockEdit(blk.index, trimmed);
      }
      setEditingIndex(null);
    },
    [draftText, onSaveBlockEdit],
  );

  const cancelEdit = useCallback(() => setEditingIndex(null), []);

  const openLightbox = useCallback((src: string, caption: string, label?: string) => {
    setLightboxFull(false);
    setLightboxInvert(false);
    setLightbox({ src, caption, label });
  }, []);

  const stripKeyColon = useCallback((items: TablePlainCell['items'], fallback: string) => {
    if (!items || items.length === 0) return [{ kind: 'text' as const, text: fallback.replace(/[:：]\s*$/, '') }];
    return items.map((it, idx) =>
      idx === items.length - 1 && it.kind === 'text'
        ? { ...it, text: it.text.replace(/[:：]\s*$/, '') }
        : it,
    );
  }, []);

  const renderMetadataFormTable = useCallback(
    (rows: TablePlainCell[][], insideCard = false) => (
      <div
        className={
          insideCard
            ? 'overflow-x-auto'
            : 'overflow-x-auto rounded-xl border border-slate-200/75 bg-white/80 px-3 py-1.5'
        }
      >
        <table className="pd-meta-kv-table">
          <tbody>
            {rows.map((row, rIdx) => {
              const isColonTriplet =
                row.length === 3 && (row[1].text.trim() === ':' || row[1].text.trim() === '：');
              const isFullSpan = row.length === 1;
              if (isFullSpan) {
                return (
                  <tr key={rIdx}>
                    <td colSpan={2} className="pd-meta-kv-val font-semibold text-center py-2">
                      <TokenItems
                        items={row[0].items || [{ kind: 'text', text: row[0].text }]}
                        bibEntries={preview.bib_entries}
                        latexMacros={preview.latex_macros}
                      />
                    </td>
                  </tr>
                );
              }
              if (isColonTriplet) {
                return (
                  <tr key={rIdx}>
                    <td className="pd-meta-kv-key">
                      <TokenItems
                        items={stripKeyColon(row[0].items, row[0].text)}
                        bibEntries={preview.bib_entries}
                      />
                    </td>
                    <td className="pd-meta-kv-val">
                      <TokenItems
                        items={row[2].items || [{ kind: 'text', text: row[2].text }]}
                        bibEntries={preview.bib_entries}
                        latexMacros={preview.latex_macros}
                      />
                    </td>
                  </tr>
                );
              }
              return (
                <tr key={rIdx}>
                  {row.map((cell, cIdx) => (
                    <td
                      key={cIdx}
                      colSpan={cell.colspan > 1 ? cell.colspan : undefined}
                      rowSpan={cell.rowspan > 1 ? cell.rowspan : undefined}
                      className={cIdx === 0 ? 'pd-meta-kv-key' : 'pd-meta-kv-val'}
                    >
                      <TokenItems
                        items={
                          cIdx === 0
                            ? stripKeyColon(cell.items, cell.text)
                            : cell.items || [{ kind: 'text', text: cell.text }]
                        }
                        bibEntries={preview.bib_entries}
                        latexMacros={preview.latex_macros}
                      />
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    ),
    [preview.bib_entries, preview.latex_macros, stripKeyColon],
  );

  const totalPendingCount = Object.keys(paragraphEdits).length + pendingPatches.length;

  if (showSource) {
    const lines = (preview.raw_content || '').split('\n');
    return (
      <div className="min-h-full bg-[#F6F7F9] px-5 pt-5 pb-24">
        <div
          style={{ maxWidth: 'clamp(920px, 84vw, 1600px)' }}
          className="mx-auto w-full overflow-hidden rounded-2xl border border-[#E6E8EE] bg-white shadow-[0_2px_16px_rgba(15,23,42,0.03)]"
        >
          <div className="flex items-center justify-between border-b border-slate-100 bg-[#FAFBFC] px-5 py-3">
            <div className="flex items-center gap-2 text-xs">
              <span className="font-bold text-slate-800">{preview.version.label}</span>
              <span className="rounded bg-slate-200/70 px-1.5 py-0.5 font-mono text-[10.5px] uppercase text-slate-600">
                {preview.format}
              </span>
              <span className="text-slate-400 tabular-nums">{lines.length} 行</span>
            </div>
            <button
              type="button"
              onClick={onCopySource}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
            >
              <Copy className="h-3.5 w-3.5 text-blue-600" />
              复制全部源码
            </button>
          </div>
          <div className="overflow-x-auto bg-[#FCFDFE] p-4 font-mono text-[12.5px] leading-relaxed text-slate-700">
            {lines.map((ln, idx) => (
              <div key={idx} className="flex hover:bg-blue-50/40 rounded px-1">
                <span className="w-11 shrink-0 select-none pr-3 text-right text-[11px] text-slate-300 tabular-nums">
                  {idx + 1}
                </span>
                <span className="whitespace-pre-wrap break-all">{ln || ' '}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  const articleWidthStyle: React.CSSProperties = {
    maxWidth:
      readWidth === 'wide'
        ? 'clamp(960px, 78vw, 1520px)'
        : 'clamp(780px, 62vw, 1140px)',
  };

  const footnoteEntries = preview.footnotes ? Object.entries(preview.footnotes) : [];

  return (
    <div ref={rootRef} className="min-h-full bg-white">
      {/* Ultra-slim 2px GPU-Composited Reading Progress Hairline (0 React re-renders!) */}
      <div className="reading-progress-track sticky top-0 z-10 h-[2px] w-full overflow-hidden">
        <div
          ref={progressBarRef}
          className="h-full w-full bg-blue-600/80 origin-left will-change-transform"
          style={{ transform: 'scaleX(0)' }}
        />
      </div>

      {/* Fluid Elastic Multi-Zone Canvas */}
      <div
        className={`mx-auto w-full max-w-[1920px] px-6 sm:px-10 xl:px-12 pt-8 sm:pt-11 ${
          totalPendingCount > 0 ? 'pb-48' : 'pb-32'
        } ${
          hasToc
            ? showInlineToc
              ? 'xl:grid xl:grid-cols-[220px_minmax(0,1fr)_80px] xl:items-start xl:gap-8'
              : 'xl:grid xl:grid-cols-[72px_minmax(0,1fr)_72px] xl:items-start xl:gap-6'
            : 'flex justify-center'
        }`}
      >
        {/* Left Quiet Borderless Scroll-Spy TOC */}
        {hasToc && (
          <aside className="hidden xl:block sticky top-10">
            {showInlineToc ? (
              <nav className="w-[212px] max-h-[calc(100vh-150px)] overflow-y-auto pr-2">
                <div className="mb-3 flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  <span className="inline-flex items-center gap-1.5">
                    <ListTree className="h-3.5 w-3.5" />
                    目录 ({preview.sections.length})
                  </span>
                  <button
                    type="button"
                    onClick={() => setShowInlineToc(false)}
                    title="收起目录，进入纯禅阅读"
                    className="rounded p-0.5 text-slate-300 hover:bg-slate-100 hover:text-slate-600"
                  >
                    <PanelLeftClose className="h-3.5 w-3.5" />
                  </button>
                </div>
                <div className="border-l border-slate-100 space-y-0.5">
                  {preview.sections.map((sec, idx) => {
                    const isActive = idx === activeSecIdx;
                    return (
                      <button
                        key={`${sec.title}-${sec.first_block_index}`}
                        type="button"
                        onClick={() => jumpTo(sec.first_block_index)}
                        className={`-ml-px flex w-full items-center justify-between gap-1.5 border-l-2 py-1.5 pr-2 text-left text-[12px] transition-colors ${
                          isActive
                            ? 'border-blue-600 font-semibold text-slate-900'
                            : 'border-transparent text-slate-400 hover:border-slate-300 hover:text-slate-700'
                        }`}
                        style={{ paddingLeft: `${12 + Math.max(0, sec.level - 1) * 10}px` }}
                      >
                        <span className="truncate">{sec.title}</span>
                        {sec.issue_count > 0 && (
                          <span
                            title={`本节有 ${sec.issue_count} 条校验提示`}
                            className="h-1.5 w-1.5 shrink-0 rounded-full bg-rose-500"
                          />
                        )}
                      </button>
                    );
                  })}
                </div>
              </nav>
            ) : (
              <button
                type="button"
                onClick={() => setShowInlineToc(true)}
                title="展开左侧章节目录"
                className="inline-flex items-center gap-1.5 rounded-full border border-slate-200/80 bg-white px-2.5 py-1.5 text-[11px] font-medium text-slate-400 shadow-2xs hover:border-blue-300 hover:text-slate-700"
              >
                <ListTree className="h-3.5 w-3.5" />
                目录
              </button>
            )}
          </aside>
        )}

        {/* Center Full-Bleed Elastic Article Column */}
        <div className="w-full min-w-0 flex justify-center">
          <article
            style={docxViewMode === 'original' ? { maxWidth: '1080px' } : articleWidthStyle}
            className="w-full min-w-0"
          >
            {/* Editorial Article Header (stays locked at articleWidthStyle when toggling Word Original view) */}
            <header style={articleWidthStyle} className="mx-auto mb-8 border-b border-slate-100 pb-5">
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="inline-flex items-center gap-1.5 font-semibold text-slate-700">
                    <BookOpen className="h-3.5 w-3.5 text-blue-600" />
                    {preview.version.label}
                  </span>
                  {preview.version.source_tag &&
                    preview.version.source_tag.trim().toLowerCase() !==
                      (preview.format || '').trim().toLowerCase() && (
                      <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">
                        {preview.version.source_tag}
                      </span>
                    )}
                  <span className="rounded-md border border-slate-200 px-1.5 py-0.5 font-mono text-[10.5px] uppercase text-slate-500">
                    {preview.format}
                  </span>
                  <span className="text-slate-200">·</span>
                  <span className="inline-flex items-center gap-1 tabular-nums text-slate-400">
                    <Clock className="h-3 w-3" />
                    预计阅读 {estMinutes} 分钟
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  {/* Word Dual-View Toggle (Academic Refined vs Pixel-Identical Word Original) */}
                  {hasDocxBlob && (
                    <div className="inline-flex items-center rounded-lg border border-slate-200 bg-slate-100/80 p-0.5 text-[11px]">
                      <button
                        type="button"
                        onClick={() => setDocxViewMode('academic')}
                        className={`rounded-md px-2.5 py-0.5 font-medium transition ${
                          docxViewMode === 'academic'
                            ? 'bg-white text-slate-900 shadow-2xs'
                            : 'text-slate-500 hover:text-slate-800'
                        }`}
                      >
                        学术精读
                      </button>
                      <button
                        type="button"
                        onClick={() => setDocxViewMode('original')}
                        className={`rounded-md px-2.5 py-0.5 font-medium transition ${
                          docxViewMode === 'original'
                            ? 'bg-white text-blue-700 shadow-2xs'
                            : 'text-slate-500 hover:text-slate-800'
                        }`}
                      >
                        Word 原版
                      </button>
                    </div>
                  )}
                  <span className="text-[11px] text-slate-400 hidden sm:inline">
                    双击段落/公式/表格原位修改 · 悬停 <span className="font-mono text-indigo-600">@引文</span> 查看文献
                  </span>
                </div>
              </div>

              {docxViewMode === 'academic' && titleBlock && (
                <h1
                  id={`para-${titleBlock.index}`}
                  style={{ textWrap: 'balance' } as React.CSSProperties}
                  className={`${proseClass} mt-5 text-[24px] sm:text-[28px] font-bold tracking-tight leading-[1.34] text-slate-950`}
                >
                  <TokenItems
                    items={titleBlock.items}
                    bibEntries={preview.bib_entries}
                    latexMacros={preview.latex_macros}
                  />
                </h1>
              )}
            </header>

            {/* W2 External File Update / Track Changes / Encoding Notice Banners */}
            {externalUpdateNotice && (
              <div
                data-external-update-banner="true"
                style={articleWidthStyle}
                className="mx-auto mb-4 flex items-center justify-between gap-3 rounded-xl border border-blue-200 bg-blue-50/80 px-3.5 py-2 text-xs text-blue-900"
              >
                <span className="font-medium">检测到磁盘原文件已在外部更新（AI 工具或其他编辑器写入）</span>
                <div className="flex items-center gap-1.5 shrink-0">
                  {onReloadExternal && (
                    <button
                      type="button"
                      data-reload-external="true"
                      onClick={onReloadExternal}
                      className="rounded-lg bg-blue-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-blue-700"
                    >
                      一键重载最新内容
                    </button>
                  )}
                  {onDismissExternalNotice && (
                    <button
                      type="button"
                      onClick={onDismissExternalNotice}
                      className="rounded-lg border border-blue-200 bg-white px-2 py-1 text-[11px] text-blue-700 hover:bg-blue-50"
                    >
                      忽略
                    </button>
                  )}
                </div>
              </div>
            )}

            {preview.tracked_changes_info?.has_tracked_changes && onSplitTrackedDocx && (
              <div
                data-local-tracked-banner="true"
                style={articleWidthStyle}
                className="mx-auto mb-4 flex items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50/80 px-3.5 py-2 text-xs text-amber-900"
              >
                <span className="font-medium">
                  检测到 Word 原生修订记录（+{preview.tracked_changes_info.ins_count} 处新增 / -
                  {preview.tracked_changes_info.del_count} 处删除）
                </span>
                <button
                  type="button"
                  data-local-split-tracked="true"
                  onClick={onSplitTrackedDocx}
                  className="shrink-0 rounded-lg bg-amber-600 px-3 py-1 text-[11px] font-semibold text-white hover:bg-amber-700"
                >
                  一键展开修订前 vs 修订后对比
                </button>
              </div>
            )}

            {preview.encoding_warning && (
              <div
                style={articleWidthStyle}
                className="mx-auto mb-4 rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2 text-[11.5px] text-slate-600"
              >
                {preview.encoding_warning}
              </div>
            )}

            {/* Word Original Pixel-Identical View (docx-preview lazy loaded!) */}
            {docxViewMode === 'original' && hasDocxBlob ? (
              <Suspense
                fallback={
                  <div className="py-20 text-center text-sm text-slate-400">
                    正在加载 Word 原版排版视图…
                  </div>
                }
              >
                <DocxOriginalViewer
                  versionId={preview.mode === 'local_folder' ? undefined : preview.version.id}
                  localFile={
                    preview.mode === 'local_folder' && localProjectId && preview.local_rel_path
                      ? { projectId: localProjectId, relPath: preview.local_rel_path }
                      : null
                  }
                />
              </Suspense>
            ) : (
              <>
                {/* Collapsible Frontmatter Card */}
                {frontmatterBlocks.length > 0 && (
                  <section className="pd-frontmatter-card mb-7 overflow-hidden">
                    <button
                      type="button"
                      onClick={() => setFrontmatterOpen((v) => !v)}
                      className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-xs transition-colors hover:bg-slate-100/70"
                    >
                      <span className="inline-flex items-center gap-2 font-semibold text-slate-700">
                        {frontmatterOpen ? (
                          <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
                        ) : (
                          <ChevronRight className="h-3.5 w-3.5 text-slate-400" />
                        )}
                        <FileText className="h-3.5 w-3.5 text-blue-600" />
                        封面与前置信息（含封面表单 / 作者单位 / 目录，共 {frontmatterBlocks.length} 项）
                      </span>
                      <span className="text-[11px] text-slate-400">
                        {frontmatterOpen ? '收起' : '展开查看 · 不计入正文词数与 AI 体检'}
                      </span>
                    </button>
                    {frontmatterOpen && (
                      <div className="space-y-2.5 border-t border-slate-200/70 px-4 py-3">
                        {frontmatterBlocks.map((fblk) => {
                          if (fblk.block_type === 'table' && fblk.table_rows && fblk.table_rows.length > 0) {
                            return (
                              <div key={fblk.index}>
                                {renderMetadataFormTable(fblk.table_rows, true)}
                              </div>
                            );
                          }
                          if (fblk.block_type === 'hr') {
                            return <hr key={fblk.index} className="my-2 border-slate-200/70" />;
                          }
                          const txt = fblk.clean_text.trim();
                          if (/^(?:(?:分类号|密级|UDC|学校代码|学号)\s*[:：]\s*)+$/i.test(txt)) {
                            return null;
                          }
                          return (
                            <p key={fblk.index} className="text-[12.5px] leading-relaxed text-slate-500">
                              <TokenItems
                                items={fblk.items}
                                bibEntries={preview.bib_entries}
                                latexMacros={preview.latex_macros}
                              />
                            </p>
                          );
                        })}
                      </div>
                    )}
                  </section>
                )}

                {/* Article Body Blocks (Memoized + CSS content-visibility: auto!) */}
                <div className={getParagraphGapClass(typographyPrefs.paragraphGap)}>
                  {bodyBlocks.map((blk, bi) => {
                    const prevBlk = bi > 0 ? bodyBlocks[bi - 1] : null;
                    const compactTop =
                      (blk.block_type === 'list' && prevBlk?.block_type === 'list') ||
                      (blk.block_type === 'reference_item' && prevBlk?.block_type === 'reference_item');
                    return (
                    <React.Fragment key={blk.index}>
                      {/* 4-Style Citation Switcher Bar above References list */}
                      {blk.index === firstRefIndex && blk.ref_meta?.bib_entry && (
                        <div className="mb-2 flex items-center justify-between rounded-lg bg-slate-50 border border-slate-200/70 px-3 py-1.5 text-[11px]">
                          <span className="font-medium text-slate-500">参考文献引文样式</span>
                          <div className="flex items-center gap-1">
                            {(['gbt7714', 'nature', 'ieee', 'apa'] as CitationStyle[]).map((st) => (
                              <button
                                key={st}
                                type="button"
                                onClick={() => setCitationStyle(st)}
                                className={`rounded px-2 py-0.5 font-medium transition ${
                                  citationStyle === st
                                    ? 'bg-blue-600 text-white'
                                    : 'text-slate-600 hover:bg-slate-200/60'
                                }`}
                              >
                                {st === 'gbt7714' ? 'GB/T 7714' : st.toUpperCase()}
                              </button>
                            ))}
                          </div>
                        </div>
                      )}

                      <SingleDocBlockRow
                        blk={blk}
                        allBlocks={preview.blocks}
                        isHighlighted={highlightedBlock === blk.index}
                        isEditing={editingIndex === blk.index}
                        editedVal={paragraphEdits[blk.index]}
                        draftText={editingIndex === blk.index ? draftText : ''}
                        showFigures={showFigures}
                        highlightAiIsms={highlightAiIsms}
                        proseClass={proseClass}
                        proseStyle={proseStyle}
                        fontSize={fontSize}
                        docLanguage={preview.doc_language}
                        typographyPrefs={typographyPrefs}
                        bibEntries={preview.bib_entries}
                        latexMacros={preview.latex_macros}
                        footnotes={preview.footnotes}
                        citationStyle={citationStyle}
                        compactTop={compactTop}
                        pendingPatches={pendingPatches}
                        onBeginEdit={beginEdit}
                        onDraftChange={setDraftText}
                        onCommitEdit={commitEdit}
                        onCancelEdit={cancelEdit}
                        onSaveBlockEdit={onSaveBlockEdit}
                        onAddPatch={onAddPatch}
                        onOpenLightbox={openLightbox}
                        onJumpToBlock={jumpTo}
                        onJumpToLabel={handleJumpToLabel}
                        renderMetadataFormTable={renderMetadataFormTable}
                      />
                    </React.Fragment>
                    );
                  })}

                  {bodyBlocks.length === 0 && !titleBlock && (
                    <div className="py-16 text-center text-xs text-slate-400">
                      当前搜索词「{searchQuery}」未匹配到任何段落
                    </div>
                  )}
                </div>

                {/* Bottom Document Footnotes Section */}
                {footnoteEntries.length > 0 && (
                  <section className="mt-12 border-t border-slate-200/80 pt-5">
                    <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
                      注释 / Footnotes ({footnoteEntries.length})
                    </h3>
                    <div className="space-y-2 text-[13px] leading-relaxed text-slate-600">
                      {footnoteEntries.map(([fid, fbody]) => (
                        <div key={fid} id={`pd-fn-${fid}`} className="flex items-baseline gap-2 scroll-mt-24">
                          <span className="font-mono text-[11px] font-semibold text-blue-600 shrink-0">
                            [{fid}]
                          </span>
                          <span className="min-w-0 flex-1">
                            <TokenItems
                              items={preview.footnote_items?.[fid] || [{ kind: 'text', text: fbody }]}
                              bibEntries={preview.bib_entries}
                              latexMacros={preview.latex_macros}
                              onJumpToLabel={handleJumpToLabel}
                            />
                          </span>
                        </div>
                      ))}
                    </div>
                  </section>
                )}
              </>
            )}
          </article>
        </div>

        {/* Right Optical Balance Column */}
        {hasToc && <div className="hidden xl:block" aria-hidden="true" />}
      </div>

      {/* Bottom Floating Structured Draft Dock (Unified for text + table + math patches!) */}
      {totalPendingCount > 0 && (
        <div className="fixed bottom-4 left-1/2 z-30 -translate-x-1/2 max-w-[92vw]">
          {draftDockExpanded && pendingPatches.length > 0 && (
            <div className="mb-2 max-h-56 overflow-y-auto rounded-2xl border border-slate-200 bg-white p-3 shadow-2xl text-xs space-y-1.5">
              <div className="flex items-center justify-between border-b border-slate-100 pb-1.5 font-semibold text-slate-700">
                <span>已暂存表格/结构化补丁 ({pendingPatches.length})</span>
                <button
                  type="button"
                  onClick={() => setDraftDockExpanded(false)}
                  className="text-slate-400 hover:text-slate-700"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
              {pendingPatches.map((op, idx) => (
                <div
                  key={idx}
                  className="flex items-center justify-between gap-3 rounded-lg bg-slate-50 px-2.5 py-1.5"
                >
                  <span className="truncate text-slate-700">
                    {op.summary || `${op.op} (#${op.block_index})`}
                  </span>
                  <button
                    type="button"
                    onClick={() => onRemovePatchAt(idx)}
                    title="撤销此项"
                    className="inline-flex items-center gap-0.5 text-[11px] text-rose-600 hover:underline shrink-0"
                  >
                    <Undo2 className="w-3 h-3" /> 撤回
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="flex items-center gap-2 rounded-full border border-blue-200 bg-white px-3.5 py-2 shadow-[0_10px_32px_rgba(15,23,42,0.18)] text-xs">
            <button
              type="button"
              onClick={() => pendingPatches.length > 0 && setDraftDockExpanded((v) => !v)}
              className="inline-flex items-center gap-1.5 font-semibold text-blue-700"
            >
              <Sparkles className="h-3.5 w-3.5" />
              已暂存 {totalPendingCount} 处原位修订
              {pendingPatches.length > 0 && (
                <ChevronDown className={`w-3.5 h-3.5 transition-transform ${draftDockExpanded ? 'rotate-180' : ''}`} />
              )}
            </button>
            <button
              type="button"
              onClick={onResetEdits}
              className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-slate-500 hover:bg-slate-100 hover:text-slate-800"
            >
              <RotateCcw className="h-3 w-3" />
              撤销全部
            </button>
            {canSaveVersion && (
              <button
                type="button"
                data-draft-save-btn="true"
                onClick={onOpenSaveModal}
                className="inline-flex items-center gap-1 rounded-full bg-emerald-600 px-3 py-1 font-semibold text-white hover:bg-emerald-700 shadow-xs transition-colors"
              >
                <Save className="h-3.5 w-3.5" />
                {preview.mode === 'local_folder' ? '保存到本地' : '无损存为新版本并对比'}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Fullscreen Figure Lightbox Modal */}
      {lightbox && (
        <div
          onClick={() => setLightbox(null)}
          className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-slate-950/85 p-6 backdrop-blur-sm"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="flex max-h-[90vh] max-w-[92vw] flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
          >
            <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5 text-xs">
              <span className="font-semibold text-slate-700 truncate max-w-[60vw]">
                {lightbox.label || '插图预览'}
              </span>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => setLightboxInvert((v) => !v)}
                  title="适用于黑白线条图/公式图夜间柔和反色"
                  className={`rounded-lg border px-2.5 py-1 font-medium transition-colors ${
                    lightboxInvert
                      ? 'border-blue-400 bg-blue-50 text-blue-700'
                      : 'border-slate-200 text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  {lightboxInvert ? '还原原色' : '线条反色'}
                </button>
                <button
                  type="button"
                  onClick={() => setLightboxFull((v) => !v)}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1 font-medium text-slate-600 hover:bg-slate-50"
                >
                  {lightboxFull ? (
                    <>
                      <ZoomOut className="h-3.5 w-3.5" />
                      适应屏幕
                    </>
                  ) : (
                    <>
                      <ZoomIn className="h-3.5 w-3.5" />
                      100% 原图
                    </>
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => setLightbox(null)}
                  className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
            <div className="paper-figure-frame overflow-auto bg-slate-50 p-4 flex justify-center">
              <img
                src={lightbox.src}
                alt="figure preview"
                className={`${
                  lightboxFull ? 'max-w-none' : 'max-h-[70vh] max-w-full object-contain'
                } ${lightboxInvert ? 'paper-figure-img-invert' : 'paper-figure-img'}`}
              />
            </div>
            {lightbox.caption && (
              <div className="border-t border-slate-100 bg-white px-5 py-3 text-xs leading-relaxed text-slate-600">
                {lightbox.caption}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
