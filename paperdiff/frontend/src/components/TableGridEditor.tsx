/**
 * @file TableGridEditor.tsx
 * @description Interactive academic three-line (booktabs) table grid editor for in-place editing.
 *
 * Features & safety invariants:
 * - Double-click any cell to edit; `Tab`/`Shift+Tab` moves horizontally, `Enter` moves down, `Esc` cancels.
 * - Compact Bold (`\textbf` / `<w:b/>`) & Commit mini-toolbar floats above the active cell so column
 *   widths remain rock-steady during editing.
 * - Merged-cell topology guard: row insertion/deletion is disabled on tables with `colspan`/`rowspan`
 *   to guarantee zero structural corruption on round-trip export.
 * - Live Table-to-Prose cross-check: modifying a single numerical cell scans body paragraphs for the
 *   stale value and surfaces a jumpable consistency alert.
 */

import React, { useCallback, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Bold,
  Check,
  Edit3,
  Plus,
  Trash2,
  X,
} from 'lucide-react';
import type { BibEntry, SingleDocBlock, TablePlainCell, TypedPatchOp } from '../types';
import { TokenItems } from './TokenRenderer';

interface TableGridEditorProps {
  block: SingleDocBlock;
  allBlocks: SingleDocBlock[];
  bibEntries?: Record<string, BibEntry>;
  latexMacros?: Record<string, string>;
  footnotes?: Record<string, string>;
  pendingPatches: TypedPatchOp[];
  onAddPatch: (op: TypedPatchOp) => void;
  onJumpToBlock?: (blockIndex: number) => void;
  onJumpToLabel?: (label: string) => void;
}

const NUM_EXTRACT_RE = /\b\d+(?:\.\d+)?%?/g;

export const TableGridEditor: React.FC<TableGridEditorProps> = React.memo(
  ({
    block,
    allBlocks,
    bibEntries,
    latexMacros,
    footnotes,
    pendingPatches,
    onAddPatch,
    onJumpToBlock,
    onJumpToLabel,
  }) => {
    const [editMode, setEditMode] = useState(false);
    const [activeCell, setActiveCell] = useState<{ r: number; c: number } | null>(null);
    const [draftVal, setDraftVal] = useState('');
    const [draftBold, setDraftBold] = useState(false);
    const [crossCheckAlert, setCrossCheckAlert] = useState<{
      oldNum: string;
      newNum: string;
      matches: { blockIndex: number; snippet: string }[];
    } | null>(null);

    const baseRows = block.table_rows || [];
    const aligns = block.table_alignments || [];

    // Compute live preview rows by folding pending patches for this table onto baseRows
    const tablePatches = useMemo(
      () => pendingPatches.filter((p) => p.block_index === block.index),
      [pendingPatches, block.index],
    );

    const liveRows: TablePlainCell[][] = useMemo(() => {
      const cloned = baseRows.map((r) => r.map((c) => ({ ...c })));
      for (const p of tablePatches) {
        if (p.op === 'edit_table_cell') {
          if (cloned[p.row]?.[p.col]) {
            cloned[p.row][p.col] = {
              ...cloned[p.row][p.col],
              text: p.new_value,
              items: [{ kind: 'text', text: p.new_value }],
              bold: p.bold ?? cloned[p.row][p.col].bold,
            };
          }
        } else if (p.op === 'insert_table_row') {
          const colN = Math.max(1, cloned[0]?.length || p.cells.length);
          const newRow: TablePlainCell[] = Array.from({ length: colN }, (_, ci) => ({
            text: p.cells[ci] || '',
            items: [{ kind: 'text', text: p.cells[ci] || '' }],
            colspan: 1,
            rowspan: 1,
            bold: false,
          }));
          const pos = Math.max(0, Math.min(p.after_row + 1, cloned.length));
          cloned.splice(pos, 0, newRow);
        } else if (p.op === 'delete_table_row') {
          if (p.row >= 0 && p.row < cloned.length) {
            cloned.splice(p.row, 1);
          }
        }
      }
      return cloned;
    }, [baseRows, tablePatches]);

    const hasMergedCells = useMemo(
      () => liveRows.some((r) => r.some((c) => c.colspan > 1 || c.rowspan > 1)),
      [liveRows],
    );

    const startCellEdit = useCallback(
      (r: number, c: number) => {
        const cell = liveRows[r]?.[c];
        if (!cell) return;
        setEditMode(true);
        setActiveCell({ r, c });
        setDraftVal(cell.text);
        setDraftBold(Boolean(cell.bold));
      },
      [liveRows],
    );

    const runBodyCrossCheck = useCallback(
      (oldText: string, newText: string) => {
        const oldNums = oldText.match(NUM_EXTRACT_RE) || [];
        const newNums = newText.match(NUM_EXTRACT_RE) || [];
        if (oldNums.length === 1 && newNums.length === 1 && oldNums[0] !== newNums[0]) {
          const oldNum = oldNums[0];
          const hits: { blockIndex: number; snippet: string }[] = [];
          for (const b of allBlocks) {
            if (b.block_type === 'paragraph' && b.zone !== 'frontmatter' && b.clean_text.includes(oldNum)) {
              const idx = b.clean_text.indexOf(oldNum);
              const snip = b.clean_text.slice(Math.max(0, idx - 24), idx + oldNum.length + 30);
              hits.push({ blockIndex: b.index, snippet: `…${snip}…` });
              if (hits.length >= 3) break;
            }
          }
          if (hits.length > 0) {
            setCrossCheckAlert({ oldNum, newNum: newNums[0], matches: hits });
          } else {
            setCrossCheckAlert(null);
          }
        }
      },
      [allBlocks],
    );

    const commitActiveCell = useCallback(
      (moveNext?: 'next' | 'prev' | 'down') => {
        if (!activeCell) return;
        const { r, c } = activeCell;
        const prev = liveRows[r]?.[c];
        if (prev && (draftVal !== prev.text || draftBold !== Boolean(prev.bold))) {
          onAddPatch({
            op: 'edit_table_cell',
            block_index: block.index,
            row: r,
            col: c,
            old_value: prev.text,
            new_value: draftVal,
            bold: draftBold,
            summary: `表格 #${block.index} (${r + 1},${c + 1}): ${prev.text.slice(0, 12)} → ${draftVal.slice(0, 12)}`,
          });
          runBodyCrossCheck(prev.text, draftVal);
        }
        if (moveNext === 'next') {
          if (c + 1 < (liveRows[r]?.length || 0)) {
            startCellEdit(r, c + 1);
            return;
          }
          if (r + 1 < liveRows.length) {
            startCellEdit(r + 1, 0);
            return;
          }
        } else if (moveNext === 'prev') {
          if (c - 1 >= 0) {
            startCellEdit(r, c - 1);
            return;
          }
          if (r - 1 >= 0) {
            startCellEdit(r - 1, Math.max(0, (liveRows[r - 1]?.length || 1) - 1));
            return;
          }
        } else if (moveNext === 'down') {
          if (r + 1 < liveRows.length && c < (liveRows[r + 1]?.length || 0)) {
            startCellEdit(r + 1, c);
            return;
          }
        }
        setActiveCell(null);
      },
      [activeCell, block.index, draftBold, draftVal, liveRows, onAddPatch, runBodyCrossCheck, startCellEdit],
    );

    const handleInsertRow = () => {
      const colN = liveRows[0]?.length || 2;
      onAddPatch({
        op: 'insert_table_row',
        block_index: block.index,
        after_row: liveRows.length - 1,
        cells: Array.from({ length: colN }, () => '—'),
        summary: `表格 #${block.index} 末尾新增一行`,
      });
    };

    const handleDeleteRow = (rowIdx: number) => {
      const row = liveRows[rowIdx];
      if (!row || row.some((c) => c.colspan > 1 || c.rowspan > 1)) return;
      onAddPatch({
        op: 'delete_table_row',
        block_index: block.index,
        row: rowIdx,
        summary: `表格 #${block.index} 删除第 ${rowIdx + 1} 行`,
      });
    };

    if (liveRows.length === 0) return null;

    return (
      <div className="my-4 group/tbl">
        {/* Compact Table Edit Toolbar */}
        <div className="mb-1.5 flex items-center justify-between gap-2 text-[11px]">
          <div className="flex items-center gap-2">
            {tablePatches.length > 0 && (
              <span className="rounded-full bg-amber-100 px-2 py-0.5 font-medium text-amber-800">
                已暂存 {tablePatches.length} 处表内修订
              </span>
            )}
            {editMode && hasMergedCells && (
              <span className="text-slate-500">
                含合并单元格：支持双击修改数值/加粗，结构增删行已锁定以防跨行错位
              </span>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            {editMode && !hasMergedCells && (
              <button
                type="button"
                onClick={handleInsertRow}
                className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-0.5 text-slate-600 hover:border-blue-300 hover:text-blue-600 transition"
              >
                <Plus className="w-3 h-3" /> 新增行
              </button>
            )}
            <button
              type="button"
              onClick={() => {
                if (editMode && activeCell) commitActiveCell();
                setEditMode((v) => !v);
                setActiveCell(null);
              }}
              className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 transition ${
                editMode
                  ? 'bg-blue-600 text-white font-medium'
                  : 'opacity-0 group-hover/tbl:opacity-100 border border-slate-200 bg-white text-slate-600 hover:text-blue-600'
              }`}
            >
              {editMode ? <Check className="w-3 h-3" /> : <Edit3 className="w-3 h-3" />}
              {editMode ? '完成编辑表格' : '编辑表格'}
            </button>
          </div>
        </div>

        {/* Live Table-to-Prose Cross-Check Warning */}
        {crossCheckAlert && (
          <div className="mb-2 flex items-start justify-between gap-2 rounded-lg border border-amber-200 bg-amber-50/90 px-3 py-2 text-[12px] text-amber-900">
            <div className="flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
              <div>
                <div className="font-medium">
                  正文一致性提示：表内数值已由 <code>{crossCheckAlert.oldNum}</code> 改为{' '}
                  <code>{crossCheckAlert.newNum}</code>，正文以下段落仍提及旧值：
                </div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {crossCheckAlert.matches.map((m) => (
                    <button
                      key={m.blockIndex}
                      type="button"
                      onClick={() => onJumpToBlock?.(m.blockIndex)}
                      className="rounded bg-white/90 border border-amber-300 px-2 py-0.5 text-[11px] hover:bg-amber-100 text-amber-900 transition"
                    >
                      跳转第 #{m.blockIndex + 1} 段：{m.snippet}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setCrossCheckAlert(null)}
              className="text-amber-600 hover:text-amber-800 p-0.5"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        <div className="overflow-x-auto">
          <table className="pd-booktabs w-full text-[13.5px]">
            <thead>
              <tr>
                {liveRows[0].map((cell, ci) => {
                  const isEditing = activeCell?.r === 0 && activeCell?.c === ci;
                  const alignCls =
                    aligns[ci] === 'center'
                      ? 'text-center'
                      : aligns[ci] === 'right'
                        ? 'text-right'
                        : 'text-left';
                  return (
                    <th
                      key={ci}
                      colSpan={cell.colspan > 1 ? cell.colspan : undefined}
                      rowSpan={cell.rowspan > 1 ? cell.rowspan : undefined}
                      onDoubleClick={() => startCellEdit(0, ci)}
                      onClick={() => editMode && !isEditing && startCellEdit(0, ci)}
                      className={`${alignCls} px-3 py-2 font-semibold ${
                        editMode ? 'cursor-pointer hover:bg-blue-50/70' : ''
                      }`}
                    >
                      {isEditing ? (
                        <div className="flex items-center gap-1">
                          <input
                            autoFocus
                            value={draftVal}
                            onChange={(e) => setDraftVal(e.target.value)}
                            onBlur={() => commitActiveCell()}
                            onKeyDown={(e) => {
                              if (e.key === 'Tab') {
                                e.preventDefault();
                                commitActiveCell(e.shiftKey ? 'prev' : 'next');
                              } else if (e.key === 'Enter') {
                                e.preventDefault();
                                commitActiveCell('down');
                              } else if (e.key === 'Escape') {
                                setActiveCell(null);
                              }
                            }}
                            className="w-full min-w-[72px] rounded border border-blue-500 bg-white px-1.5 py-0.5 text-[13px] font-normal text-slate-900 outline-none"
                          />
                        </div>
                      ) : (
                        <TokenItems
                          items={cell.items || [{ kind: 'text', text: cell.text }]}
                          bibEntries={bibEntries}
                          latexMacros={latexMacros}
                          footnotes={footnotes}
                          onJumpToLabel={onJumpToLabel}
                        />
                      )}
                    </th>
                  );
                })}
                {editMode && !hasMergedCells && <th className="w-8 px-1" />}
              </tr>
            </thead>
            <tbody>
              {liveRows.slice(1).map((row, rOffset) => {
                const rIdx = rOffset + 1;
                const rowHasMerge = row.some((c) => c.colspan > 1 || c.rowspan > 1);
                return (
                  <tr key={rIdx} className="group/tr">
                    {row.map((cell, ci) => {
                      const isEditing = activeCell?.r === rIdx && activeCell?.c === ci;
                      const alignCls =
                        aligns[ci] === 'center'
                          ? 'text-center'
                          : aligns[ci] === 'right'
                            ? 'text-right'
                            : 'text-left';
                      return (
                        <td
                          key={ci}
                          colSpan={cell.colspan > 1 ? cell.colspan : undefined}
                          rowSpan={cell.rowspan > 1 ? cell.rowspan : undefined}
                          onDoubleClick={() => startCellEdit(rIdx, ci)}
                          onClick={() => editMode && !isEditing && startCellEdit(rIdx, ci)}
                          className={`relative ${alignCls} px-3 py-1.5 align-top ${
                            cell.bold ? 'font-semibold' : ''
                          } ${editMode ? 'cursor-pointer hover:bg-blue-50/60' : ''}`}
                        >
                          {isEditing ? (
                            <div className="relative">
                              {/* Floating compact cell toolbar above cell -> zero column expansion! */}
                              <div className="absolute -top-9 right-0 z-30 flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-1.5 py-1 shadow-lg">
                                <button
                                  type="button"
                                  onMouseDown={(e) => e.preventDefault()}
                                  onClick={() => setDraftBold((b) => !b)}
                                  title="切换最优值加粗 (\\textbf)"
                                  className={`rounded p-1 border transition ${
                                    draftBold
                                      ? 'bg-blue-600 text-white border-blue-600'
                                      : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
                                  }`}
                                >
                                  <Bold className="w-3 h-3" />
                                </button>
                                <button
                                  type="button"
                                  onMouseDown={(e) => e.preventDefault()}
                                  onClick={() => commitActiveCell()}
                                  title="确认修改 (Enter)"
                                  className="rounded bg-emerald-600 p-1 text-white hover:bg-emerald-700"
                                >
                                  <Check className="w-3 h-3" />
                                </button>
                              </div>
                              <input
                                autoFocus
                                value={draftVal}
                                onChange={(e) => setDraftVal(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Tab') {
                                    e.preventDefault();
                                    commitActiveCell(e.shiftKey ? 'prev' : 'next');
                                  } else if (e.key === 'Enter') {
                                    e.preventDefault();
                                    commitActiveCell('down');
                                  } else if (e.key === 'Escape') {
                                    setActiveCell(null);
                                  }
                                }}
                                className="w-full max-w-[180px] box-border rounded border border-blue-500 bg-white px-1.5 py-0.5 text-[13px] font-normal text-slate-900 outline-none"
                              />
                            </div>
                          ) : (
                            <TokenItems
                              items={cell.items || [{ kind: 'text', text: cell.text }]}
                              bibEntries={bibEntries}
                              latexMacros={latexMacros}
                              footnotes={footnotes}
                              onJumpToLabel={onJumpToLabel}
                            />
                          )}
                        </td>
                      );
                    })}
                    {editMode && !hasMergedCells && (
                      <td className="px-1 py-1 text-center align-middle">
                        {!rowHasMerge && (
                          <button
                            type="button"
                            onClick={() => handleDeleteRow(rIdx)}
                            title="删除该行"
                            className="rounded p-1 text-slate-400 hover:bg-rose-50 hover:text-rose-600 transition"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Optional threeparttable tablenotes */}
        {block.table_notes && block.table_notes.length > 0 && (
          <div className="mt-1.5 space-y-0.5 text-[12px] text-slate-500">
            {block.table_notes.map((n, ni) => (
              <div key={ni}>{n}</div>
            ))}
          </div>
        )}
      </div>
    );
  },
);
TableGridEditor.displayName = 'TableGridEditor';
