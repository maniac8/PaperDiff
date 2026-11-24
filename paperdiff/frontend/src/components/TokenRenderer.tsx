/**
 * @file TokenRenderer.tsx
 * @description Unified inline academic token renderer (`MathInline` with KaTeX + `mhchem`,
 * `CiteChip`, `FootnoteChip`, clickable cross-references, links, inline code, and nested styles).
 *
 * Architectural invariants:
 * - Bounded 4,000-entry global LRU cache (`KATEX_CACHE`) keeps scrolling O(1) for math-heavy papers.
 * - All hover popovers (`CiteChip`, `FootnoteChip`, and exported `FloatingHoverCard`) mount via
 *   `ReactDOM.createPortal(..., document.body)` with `position: fixed; z-index: 9999`, automatic
 *   vertical flip below the sticky header, viewport horizontal clamping, and instant scroll dismiss,
 *   guaranteeing zero clipping inside `.pd-virtual-block` (`contain: paint`) or scrollable tables.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import katex from 'katex';
import 'katex/contrib/mhchem';
import type { BibEntry, DisplayItem } from '../types';

export interface FloatingAnchorRect {
  top: number;
  bottom: number;
  left: number;
  width: number;
}

/**
 * Portal-based floating hover card rendered into `document.body` (`position: fixed`).
 * Immune to CSS `content-visibility: auto` (`contain: paint`) clipping, table `overflow-x-auto`,
 * and sticky header occlusion, with automatic vertical flip & horizontal viewport clamping.
 */
export const FloatingHoverCard: React.FC<{
  anchor: FloatingAnchorRect;
  width: number;
  prefer?: 'top' | 'bottom';
  onDismiss?: () => void;
  children: React.ReactNode;
}> = ({ anchor, width, prefer = 'top', onDismiss, children }) => {
  useEffect(() => {
    if (!onDismiss) return;
    const handleDismiss = () => onDismiss();
    window.addEventListener('scroll', handleDismiss, { capture: true, passive: true });
    window.addEventListener('resize', handleDismiss, { passive: true });
    return () => {
      window.removeEventListener('scroll', handleDismiss, { capture: true });
      window.removeEventListener('resize', handleDismiss);
    };
  }, [onDismiss]);

  if (typeof document === 'undefined') return null;

  const vw = window.innerWidth || 1280;
  const vh = window.innerHeight || 800;
  const clampedWidth = Math.min(width, Math.max(200, vw - 24));
  const rawLeft = anchor.left + anchor.width / 2 - clampedWidth / 2;
  const left = Math.max(12, Math.min(rawLeft, vw - clampedWidth - 12));

  // Keep safe clearance below sticky top header (~108px) and viewport bottom
  const spaceAbove = Math.max(0, anchor.top - 108);
  const spaceBelow = Math.max(0, vh - anchor.bottom - 16);
  const placeAbove =
    prefer === 'top'
      ? spaceAbove >= 180 || spaceAbove >= spaceBelow
      : spaceBelow < 180 && spaceAbove > spaceBelow;

  const style: React.CSSProperties = {
    position: 'fixed',
    left,
    width: clampedWidth,
    zIndex: 9999,
    maxHeight: Math.max(120, Math.min(360, (placeAbove ? spaceAbove : spaceBelow) - 8)),
    ...(placeAbove
      ? { bottom: Math.max(12, vh - anchor.top + 8) }
      : { top: Math.max(12, anchor.bottom + 8) }),
  };

  return createPortal(
    <div
      style={style}
      className="pointer-events-none overflow-hidden rounded-xl border border-slate-700/80 bg-slate-900/95 p-2.5 text-left font-sans text-[11px] leading-relaxed text-slate-200 shadow-2xl backdrop-blur"
    >
      {children}
    </div>,
    document.body,
  );
};

// Global bounded LRU cache for KaTeX HTML strings -> O(1) rendering on scroll/re-renders!
const KATEX_CACHE = new Map<string, string>();
const KATEX_CACHE_MAX = 4000;

function renderKatexCached(
  expr: string,
  displayMode: boolean,
  macros?: Record<string, string>,
): string | null {
  const macroSig = macros && Object.keys(macros).length > 0 ? Object.keys(macros).sort().join(',') : '';
  const key = `${displayMode ? 'D' : 'I'}|${macroSig}|${expr}`;
  const hit = KATEX_CACHE.get(key);
  if (hit !== undefined) {
    return hit;
  }
  try {
    const html = katex.renderToString(expr, {
      throwOnError: false,
      displayMode,
      strict: false,
      macros: macros ? { ...macros } : undefined,
    });
    if (KATEX_CACHE.size >= KATEX_CACHE_MAX) {
      const oldest = KATEX_CACHE.keys().next().value;
      if (oldest !== undefined) KATEX_CACHE.delete(oldest);
    }
    KATEX_CACHE.set(key, html);
    return html;
  } catch {
    return null;
  }
}

interface MathInlineProps {
  expr: string;
  displayMode?: boolean;
  latexMacros?: Record<string, string>;
}

export const MathInline: React.FC<MathInlineProps> = React.memo(
  ({ expr, displayMode = false, latexMacros }) => {
    const html = useMemo(
      () => renderKatexCached(expr, displayMode, latexMacros),
      [expr, displayMode, latexMacros],
    );

    if (!html) {
      return (
        <code className="rounded bg-teal-50 px-1.5 py-0.5 font-mono text-[13px] text-teal-700">
          ${expr}$
        </code>
      );
    }
    return (
      <span
        title={`LaTeX 公式: ${expr}`}
        className={displayMode ? 'block overflow-x-auto indent-0' : 'inline-block align-baseline mx-0.5 indent-0'}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    );
  },
);
MathInline.displayName = 'MathInline';

const CiteChip: React.FC<{ rawKeys: string; bibEntries?: Record<string, BibEntry> }> = React.memo(
  ({ rawKeys, bibEntries }) => {
    const [anchor, setAnchor] = useState<FloatingAnchorRect | null>(null);
    const dismiss = useCallback(() => setAnchor(null), []);
    const keys = useMemo(
      () =>
        rawKeys
          .split(',')
          .map((k) => k.trim())
          .filter(Boolean),
      [rawKeys],
    );

    const hasBib = Boolean(bibEntries && Object.keys(bibEntries).length > 0);
    const missingAny = hasBib && keys.some((k) => !bibEntries?.[k]);

    const handleEnter = useCallback((e: React.MouseEvent<HTMLSpanElement>) => {
      const r = e.currentTarget.getBoundingClientRect();
      setAnchor({ top: r.top, bottom: r.bottom, left: r.left, width: r.width });
    }, []);

    return (
      <span
        className="relative inline-block"
        onMouseEnter={handleEnter}
        onMouseLeave={dismiss}
      >
        <span
          className={`mx-0.5 inline-block rounded px-1.5 py-[0.5px] font-mono text-[0.78em] font-medium border cursor-help ${
            missingAny ? 'academic-cite-chip-missing' : 'academic-cite-chip'
          }`}
        >
          @{keys.join(', ')}
        </span>
        {anchor && (
          <FloatingHoverCard anchor={anchor} width={320} prefer="top" onDismiss={dismiss}>
            {!hasBib ? (
              <span className="block text-slate-300">
                LaTeX 引文：<code className="text-indigo-300">\cite&#123;{rawKeys}&#125;</code>
                <span className="mt-1 block text-[10px] text-slate-400">
                  上传含 .bib 的 Overleaf .zip 后可悬停查看完整文献标题与作者
                </span>
              </span>
            ) : (
              <span className="block space-y-2">
                {keys.map((k) => {
                  const entry = bibEntries?.[k];
                  if (!entry) {
                    return (
                      <span key={k} className="block text-rose-300">
                        <strong className="font-mono">@{k}</strong> — 未在项目 .bib 中找到定义
                      </span>
                    );
                  }
                  return (
                    <span key={k} className="block">
                      <span className="block font-semibold text-white">{entry.title || k}</span>
                      <span className="block text-[10.5px] text-slate-300">
                        {[entry.author, entry.year, entry.venue].filter(Boolean).join(' · ')}
                      </span>
                    </span>
                  );
                })}
              </span>
            )}
          </FloatingHoverCard>
        )}
      </span>
    );
  },
);
CiteChip.displayName = 'CiteChip';

const FootnoteChip: React.FC<{
  fnId: string;
  footnotes?: Record<string, string>;
  onJumpToFootnote?: (id: string) => void;
}> = React.memo(({ fnId, footnotes, onJumpToFootnote }) => {
  const [anchor, setAnchor] = useState<FloatingAnchorRect | null>(null);
  const dismiss = useCallback(() => setAnchor(null), []);
  const body = footnotes?.[fnId];

  const handleEnter = useCallback((e: React.MouseEvent<HTMLSpanElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    setAnchor({ top: r.top, bottom: r.bottom, left: r.left, width: r.width });
  }, []);

  return (
    <span
      className="relative inline-block"
      onMouseEnter={handleEnter}
      onMouseLeave={dismiss}
    >
      <sup
        onClick={(e) => {
          e.stopPropagation();
          if (onJumpToFootnote) {
            onJumpToFootnote(fnId);
          } else {
            document.getElementById(`pd-fn-${fnId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
        }}
        className="pd-fn-chip ml-0.5 cursor-pointer font-sans text-[0.72em] font-semibold"
        title={body ? `脚注 [${fnId}]: ${body}` : `脚注 [${fnId}]`}
      >
        [{fnId}]
      </sup>
      {anchor && body && (
        <FloatingHoverCard anchor={anchor} width={272} prefer="top" onDismiss={dismiss}>
          <span className="block font-semibold text-blue-300 mb-0.5">脚注 [{fnId}]</span>
          <span className="block text-slate-100">{body}</span>
        </FloatingHoverCard>
      )}
    </span>
  );
});
FootnoteChip.displayName = 'FootnoteChip';

interface TokenItemsProps {
  items: DisplayItem[];
  displayMath?: boolean;
  bibEntries?: Record<string, BibEntry>;
  latexMacros?: Record<string, string>;
  footnotes?: Record<string, string>;
  onJumpToLabel?: (label: string) => void;
  onJumpToFootnote?: (fnId: string) => void;
  highlightAiIsms?: boolean;
  aiIsms?: string[];
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function renderTextWithAiHighlights(text: string, regex: RegExp | null): React.ReactNode {
  if (!regex || !text) return text;
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  regex.lastIndex = 0;
  let m: RegExpExecArray | null;
  let keyIdx = 0;
  while ((m = regex.exec(text)) !== null) {
    if (m[0].length === 0) {
      regex.lastIndex += 1;
      continue;
    }
    if (m.index > lastIndex) {
      parts.push(text.slice(lastIndex, m.index));
    }
    parts.push(
      <mark
        key={`ai-${keyIdx++}`}
        title={`AI 高频表达：${m[0]}（双击该段可原位润色修改）`}
        className="ai-ism-mark"
      >
        {m[0]}
      </mark>,
    );
    lastIndex = m.index + m[0].length;
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  return parts.length > 0 ? parts : text;
}

const BARE_URL_RE = /(https?:\/\/[^\s<>"'）)，。；;]+)/g;

function renderTextWithLinksAndAi(text: string, aiRegex: RegExp | null): React.ReactNode {
  if (!text) return text;
  if (!text.includes('http://') && !text.includes('https://')) {
    return aiRegex ? renderTextWithAiHighlights(text, aiRegex) : text;
  }
  const segs = text.split(BARE_URL_RE);
  return segs.map((seg, i) => {
    if (seg.startsWith('http://') || seg.startsWith('https://')) {
      return (
        <a
          key={`u-${i}`}
          href={seg}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="pd-inline-link break-all"
        >
          {seg}
        </a>
      );
    }
    return (
      <React.Fragment key={`t-${i}`}>
        {aiRegex ? renderTextWithAiHighlights(seg, aiRegex) : seg}
      </React.Fragment>
    );
  });
}

function wrapInlineStyle(
  node: React.ReactNode,
  bold?: boolean,
  italic?: boolean,
  strike?: boolean,
  key?: number | string,
): React.ReactNode {
  let out = node;
  if (strike) out = <del className="line-through opacity-75">{out}</del>;
  if (italic) out = <em className="italic">{out}</em>;
  if (bold) out = <strong className="font-semibold text-slate-950">{out}</strong>;
  return <React.Fragment key={key}>{out}</React.Fragment>;
}

export const TokenItems: React.FC<TokenItemsProps> = React.memo(
  ({
    items,
    displayMath = false,
    bibEntries,
    latexMacros,
    footnotes,
    onJumpToLabel,
    onJumpToFootnote,
    highlightAiIsms = false,
    aiIsms,
  }) => {
    const aiRegex = useMemo(() => {
      if (!highlightAiIsms || !aiIsms || aiIsms.length === 0) return null;
      const uniq = Array.from(new Set(aiIsms.map((w) => w.trim()).filter(Boolean))).sort(
        (a, b) => b.length - a.length,
      );
      if (uniq.length === 0) return null;
      const alts = uniq.map((w) =>
        /^[A-Za-z][A-Za-z\s'-]*[A-Za-z]$|^[A-Za-z]$/.test(w)
          ? `\\b${escapeRegExp(w)}\\b`
          : escapeRegExp(w),
      );
      try {
        return new RegExp(`(${alts.join('|')})`, 'gi');
      } catch {
        return null;
      }
    }, [highlightAiIsms, aiIsms]);

    return (
      <>
        {items.map((item, idx) => {
          if (item.kind === 'br') {
            return <br key={idx} />;
          }
          if (item.kind === 'sp') {
            const rawW = Number.parseFloat(item.value || '1');
            const w = Number.isFinite(rawW) ? Math.min(4.0, Math.max(0.25, rawW)) : 1.0;
            return (
              <span
                key={idx}
                className="pd-inline-space inline-block align-baseline select-none"
                style={{ width: `${w}em` }}
                aria-hidden="true"
              />
            );
          }
          if (item.kind === 'text') {
            const inner = renderTextWithLinksAndAi(item.text, aiRegex);
            if (item.bold || item.italic || item.strike) {
              return wrapInlineStyle(inner, item.bold, item.italic, item.strike, idx);
            }
            return <React.Fragment key={idx}>{inner}</React.Fragment>;
          }
          if (item.kind === 'code') {
            const codeNode = <code className="pd-inline-code">{item.value ?? item.text}</code>;
            return item.bold || item.italic || item.strike
              ? wrapInlineStyle(codeNode, item.bold, item.italic, item.strike, idx)
              : <React.Fragment key={idx}>{codeNode}</React.Fragment>;
          }
          if (item.kind === 'link') {
            const linkNode = (
              <a
                href={item.value || item.text}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="pd-inline-link break-words"
              >
                {item.text}
              </a>
            );
            return item.bold || item.italic || item.strike
              ? wrapInlineStyle(linkNode, item.bold, item.italic, item.strike, idx)
              : <React.Fragment key={idx}>{linkNode}</React.Fragment>;
          }
          if (item.kind === 'ref') {
            const labelKey = item.value || '';
            const disp = item.text && !item.text.startsWith('⟦') ? item.text : labelKey;
            const isShortNum = /^\(?[0-9]+[a-zA-Z]?\)?$/.test(disp);
            return (
              <button
                key={idx}
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  if (onJumpToLabel && labelKey) onJumpToLabel(labelKey);
                }}
                title={`交叉引用 \\ref{${labelKey}}（点击跳转）`}
                className="academic-ref-chip inline-flex items-center font-medium hover:underline cursor-pointer"
              >
                {isShortNum ? disp : `[${disp}]`}
              </button>
            );
          }
          if (item.kind === 'fn') {
            return (
              <FootnoteChip
                key={idx}
                fnId={item.value || item.text}
                footnotes={footnotes}
                onJumpToFootnote={onJumpToFootnote}
              />
            );
          }
          if (item.kind === 'cite') {
            return <CiteChip key={idx} rawKeys={item.value || ''} bibEntries={bibEntries} />;
          }
          if (item.kind === 'math') {
            const mathNode = (
              <MathInline
                expr={item.value || ''}
                displayMode={displayMath}
                latexMacros={latexMacros}
              />
            );
            return item.bold ? (
              <strong key={idx} className="font-semibold">
                {mathNode}
              </strong>
            ) : (
              <React.Fragment key={idx}>{mathNode}</React.Fragment>
            );
          }
          return null;
        })}
      </>
    );
  },
);
TokenItems.displayName = 'TokenItems';
