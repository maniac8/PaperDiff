/**
 * @file FloatingOutline.tsx
 * @description Hover-triggered left-edge section heatmap outline for quick jumping across changed
 * sections and alerted headings in Compare Mode.
 */

import React, { useState } from 'react';
import { AlertCircle, ListTree } from 'lucide-react';
import type { SectionSummary, SingleDocSection } from '../types';

interface FloatingOutlineProps {
  sections?: SectionSummary[];
  readSections?: SingleDocSection[];
  hideOnXl?: boolean;
  onJumpToParagraph: (paraIndex: number) => void;
}

/**
 * Ultra-slim left-edge floating TOC rail (zero horizontal width stolen from canvas).
 * Supports both Compare Mode (change heatmap) and Read Mode (clean section outline).
 */
export const FloatingOutline: React.FC<FloatingOutlineProps> = ({
  sections,
  readSections,
  hideOnXl = false,
  onJumpToParagraph,
}) => {
  const [expanded, setExpanded] = useState(false);

  const isRead = Boolean(readSections && !sections);
  const count = isRead ? (readSections?.length || 0) : (sections?.length || 0);
  if (count <= 1) return null;

  return (
    <div
      onMouseEnter={() => setExpanded(true)}
      onMouseLeave={() => setExpanded(false)}
      className={`fixed left-2.5 top-1/2 z-30 -translate-y-1/2 hidden md:block ${
        hideOnXl ? 'xl:hidden' : ''
      }`}
    >
      {/* Collapsed slim heatmap ticks */}
      {!expanded ? (
        <div
          title={isRead ? '章节目录（悬停展开）' : '章节目录与改动热力（悬停展开）'}
          className="flex flex-col items-start gap-2 rounded-full bg-white/80 backdrop-blur border border-slate-200/80 px-1.5 py-2.5 shadow-sm cursor-pointer hover:border-blue-300 transition-all"
        >
          {isRead
            ? (readSections || []).map((sec) => {
                const widthPx = sec.level <= 1 ? 18 : sec.level === 2 ? 13 : 9;
                const colorCls =
                  sec.issue_count > 0
                    ? 'bg-rose-400'
                    : sec.ai_ism_count > 0
                      ? 'bg-violet-400'
                      : 'bg-slate-300';
                return (
                  <div
                    key={`${sec.title}-${sec.first_block_index}`}
                    className={`h-[3px] rounded-full transition-all ${colorCls}`}
                    style={{ width: `${widthPx}px` }}
                  />
                );
              })
            : (sections || []).map((sec) => {
                const intensity = Math.min(100, Math.max(0, sec.change_intensity));
                const widthPx = intensity === 0 ? 8 : intensity < 25 ? 12 : intensity < 55 ? 16 : 20;
                const colorCls =
                  sec.alert_count > 0
                    ? 'bg-rose-400'
                    : intensity === 0
                      ? 'bg-slate-300'
                      : intensity < 25
                        ? 'bg-emerald-400'
                        : intensity < 55
                          ? 'bg-blue-500'
                          : 'bg-amber-500';
                return (
                  <div
                    key={`${sec.title}-${sec.first_para_index}`}
                    className={`h-[3px] rounded-full transition-all ${colorCls}`}
                    style={{ width: `${widthPx}px` }}
                  />
                );
              })}
        </div>
      ) : (
        /* Expanded floating outline card */
        <div className="w-[248px] max-h-[68vh] overflow-y-auto rounded-2xl border border-slate-200/90 bg-white/95 backdrop-blur-md p-3 shadow-[0_12px_36px_rgba(15,23,42,0.12)]">
          <div className="mb-2 flex items-center gap-1.5 px-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            <ListTree className="h-3.5 w-3.5" />
            章节导航 ({count})
          </div>
          <div className="space-y-1">
            {isRead
              ? (readSections || []).map((sec) => (
                  <button
                    key={`${sec.title}-${sec.first_block_index}`}
                    type="button"
                    onClick={() => {
                      onJumpToParagraph(sec.first_block_index);
                      setExpanded(false);
                    }}
                    className="w-full rounded-lg px-2 py-1.5 text-left hover:bg-slate-100/90 transition-colors"
                  >
                    <div className="flex items-center justify-between gap-1.5">
                      <span
                        className="truncate text-[12px] font-medium text-slate-700"
                        style={{ paddingLeft: `${Math.max(0, sec.level - 1) * 10}px` }}
                      >
                        {sec.title}
                      </span>
                      <div className="flex items-center gap-1 shrink-0">
                        {sec.issue_count > 0 && <AlertCircle className="h-3 w-3 text-rose-500" />}
                        <span className="text-[10.5px] tabular-nums text-slate-400">
                          {sec.word_count}词
                        </span>
                      </div>
                    </div>
                  </button>
                ))
              : (sections || []).map((sec) => {
                  const intensity = Math.min(100, Math.max(0, sec.change_intensity));
                  const barColor =
                    intensity === 0
                      ? 'bg-slate-200'
                      : intensity < 25
                        ? 'bg-emerald-400'
                        : intensity < 55
                          ? 'bg-blue-500'
                          : 'bg-amber-500';
                  const deltaStr = sec.word_delta > 0 ? `+${sec.word_delta}` : `${sec.word_delta}`;

                  return (
                    <button
                      key={`${sec.title}-${sec.first_para_index}`}
                      type="button"
                      onClick={() => {
                        onJumpToParagraph(sec.first_para_index);
                        setExpanded(false);
                      }}
                      className="w-full rounded-lg px-2 py-1.5 text-left hover:bg-slate-100/90 transition-colors"
                    >
                      <div className="flex items-center justify-between gap-1.5">
                        <span
                          className="truncate text-[12px] font-medium text-slate-700"
                          style={{ paddingLeft: `${Math.max(0, sec.level - 1) * 10}px` }}
                        >
                          {sec.title}
                        </span>
                        <div className="flex items-center gap-1 shrink-0">
                          {sec.alert_count > 0 && (
                            <AlertCircle className="h-3 w-3 text-rose-500" />
                          )}
                          <span className="text-[10.5px] tabular-nums text-slate-400">
                            {deltaStr}
                          </span>
                        </div>
                      </div>
                      <div className="mt-1 flex items-center gap-2">
                        <div className="h-1 flex-1 overflow-hidden rounded-full bg-slate-200/80">
                          <div
                            className={`h-full rounded-full ${barColor}`}
                            style={{ width: `${Math.max(intensity > 0 ? 10 : 0, intensity)}%` }}
                          />
                        </div>
                        <span className="text-[10px] tabular-nums text-slate-400 w-8 text-right">
                          {Math.round(sec.similarity)}%
                        </span>
                      </div>
                    </button>
                  );
                })}
          </div>
        </div>
      )}
    </div>
  );
};
