/**
 * @file FloatingStepper.tsx
 * @description Bottom floating navigation pill in Compare Mode for stepping through modified
 * paragraphs (`J`/`K`), fact-conservation alerts (`N`/`P`), and triggering quick save/export.
 */

import React, { useState } from 'react';
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Download,
  Keyboard,
  RotateCcw,
  Save,
} from 'lucide-react';

interface FloatingStepperProps {
  changedCount: number;
  currentChangeIdx: number;
  alertParaCount: number;
  currentAlertIdx: number;
  revertedCount: number;
  editedParaCount: number;
  canSaveVersion: boolean;
  onStepChange: (dir: 1 | -1) => void;
  onStepAlert: (dir: 1 | -1) => void;
  onExportMerged: () => void;
  onSaveAsNewVersion: () => void;
  onResetDecisions: () => void;
}

export const FloatingStepper: React.FC<FloatingStepperProps> = ({
  changedCount,
  currentChangeIdx,
  alertParaCount,
  currentAlertIdx,
  revertedCount,
  editedParaCount,
  canSaveVersion,
  onStepChange,
  onStepAlert,
  onExportMerged,
  onSaveAsNewVersion,
  onResetDecisions,
}) => {
  const [showKeys, setShowKeys] = useState(false);
  const hasEdits = revertedCount > 0 || editedParaCount > 0;

  if (changedCount === 0 && alertParaCount === 0 && !hasEdits) return null;

  return (
    <div className="fixed bottom-4 left-1/2 z-30 -translate-x-1/2">
      {showKeys && (
        <div className="mb-2 mx-auto w-max rounded-xl border border-slate-200 bg-slate-900/95 px-3.5 py-2 text-[11px] text-slate-200 shadow-xl backdrop-blur">
          <span className="font-semibold text-white">快捷键：</span>
          <kbd className="mx-1 rounded bg-slate-700 px-1.5 py-0.5 font-mono text-[10px]">J / K</kbd>
          <span>上/下处改动</span>
          <span className="mx-2 text-slate-500">·</span>
          <kbd className="mx-1 rounded bg-slate-700 px-1.5 py-0.5 font-mono text-[10px]">N / P</kbd>
          <span>上/下条告警</span>
          <span className="mx-2 text-slate-500">·</span>
          <kbd className="mx-1 rounded bg-slate-700 px-1.5 py-0.5 font-mono text-[10px]">R</kbd>
          <span>阅读预览</span>
          <span className="mx-2 text-slate-500">·</span>
          <kbd className="mx-1 rounded bg-slate-700 px-1.5 py-0.5 font-mono text-[10px]">V</kbd>
          <span>切左右/行内</span>
          <span className="mx-2 text-slate-500">·</span>
          <kbd className="mx-1 rounded bg-slate-700 px-1.5 py-0.5 font-mono text-[10px]">⌘1 / ⌘2</kbd>
          <span>层级树 / 审计</span>
        </div>
      )}

      <div className="flex items-center gap-1.5 rounded-full border border-slate-200/90 bg-white/95 px-2.5 py-1.5 shadow-[0_8px_28px_rgba(15,23,42,0.12)] backdrop-blur-md text-xs">
        {changedCount > 0 && (
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => onStepChange(-1)}
              title="上一处改动段落 (K)"
              className="rounded-full p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-900"
            >
              <ChevronUp className="h-3.5 w-3.5" />
            </button>
            <span className="px-1 text-[11.5px] font-medium text-slate-600 tabular-nums select-none">
              改动{' '}
              <strong className="text-slate-900">
                {currentChangeIdx >= 0 ? currentChangeIdx + 1 : '–'}
              </strong>
              /{changedCount}
            </span>
            <button
              type="button"
              onClick={() => onStepChange(1)}
              title="下一处改动段落 (J)"
              className="rounded-full p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-900"
            >
              <ChevronDown className="h-3.5 w-3.5" />
            </button>
          </div>
        )}

        {alertParaCount > 0 && (
          <>
            <div className="h-3.5 w-px bg-slate-200 mx-0.5" />
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => onStepAlert(-1)}
                title="上一条事实告警 (P)"
                className="rounded-full p-1 text-rose-500 hover:bg-rose-50"
              >
                <ChevronUp className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                onClick={() => onStepAlert(1)}
                className="inline-flex items-center gap-1 rounded-full bg-rose-50 px-2 py-0.5 text-[11.5px] font-semibold text-rose-700 hover:bg-rose-100 tabular-nums"
              >
                <AlertTriangle className="h-3 w-3" />
                告警 {currentAlertIdx >= 0 ? currentAlertIdx + 1 : '–'}/{alertParaCount}
              </button>
              <button
                type="button"
                onClick={() => onStepAlert(1)}
                title="下一条事实告警 (N)"
                className="rounded-full p-1 text-rose-500 hover:bg-rose-50"
              >
                <ChevronDown className="h-3.5 w-3.5" />
              </button>
            </div>
          </>
        )}

        {hasEdits && (
          <>
            <div className="h-3.5 w-px bg-slate-200 mx-0.5" />
            <div className="flex items-center gap-1.5 pl-0.5">
              <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-semibold text-blue-700">
                {revertedCount > 0 ? `回退 ${revertedCount} 处` : ''}
                {revertedCount > 0 && editedParaCount > 0 ? ' · ' : ''}
                {editedParaCount > 0 ? `微调 ${editedParaCount} 段` : ''}
              </span>
              <button
                type="button"
                onClick={onResetDecisions}
                title="重置全部回退与微调"
                className="rounded-full p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              >
                <RotateCcw className="h-3.5 w-3.5" />
              </button>
              {canSaveVersion && (
                <button
                  type="button"
                  onClick={onSaveAsNewVersion}
                  className="inline-flex items-center gap-1 rounded-full bg-emerald-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-emerald-700 transition-colors"
                >
                  <Save className="h-3 w-3" />
                  存为新版本
                </button>
              )}
              <button
                type="button"
                onClick={onExportMerged}
                className="inline-flex items-center gap-1 rounded-full bg-blue-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-blue-700 transition-colors"
              >
                <Download className="h-3 w-3" />
                导出
              </button>
            </div>
          </>
        )}

        <div className="h-3.5 w-px bg-slate-200 mx-0.5" />
        <button
          type="button"
          onClick={() => setShowKeys((v) => !v)}
          title="查看键盘快捷键"
          className={`rounded-full p-1 transition-colors ${
            showKeys ? 'bg-slate-900 text-white' : 'text-slate-400 hover:bg-slate-100 hover:text-slate-700'
          }`}
        >
          <Keyboard className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
};
