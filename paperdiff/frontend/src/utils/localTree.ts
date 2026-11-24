/**
 * @file localTree.ts
 * @description Pure utility functions for local folder tree filtering, document flattening,
 * strict pairwise Diff selection (`D-04`, max 2 files), and revised filename suggestion.
 */

import type { LocalFormatFilter, LocalTreeNode } from '../types';

/** Recursively collects all primary document (`kind === 'doc'`) leaf nodes in tree order. */
export function flattenLocalDocs(nodes: LocalTreeNode[]): LocalTreeNode[] {
  const out: LocalTreeNode[] = [];
  for (const node of nodes) {
    if (node.node_type === 'file') {
      if (node.kind === 'doc') out.push(node);
    } else if (node.children && node.children.length > 0) {
      out.push(...flattenLocalDocs(node.children));
    }
  }
  return out;
}

/**
 * Filters a local folder tree by filename/path query and academic format chip,
 * pruning empty folders and returning ancestor folder paths that should auto-expand.
 */
export function filterLocalTree(
  nodes: LocalTreeNode[],
  query: string,
  formatFilter: LocalFormatFilter,
): { nodes: LocalTreeNode[]; autoExpandDirs: string[] } {
  const q = query.trim().toLowerCase();
  const expandSet = new Set<string>();

  const visit = (list: LocalTreeNode[]): LocalTreeNode[] => {
    const out: LocalTreeNode[] = [];
    for (const node of list) {
      if (node.node_type === 'dir') {
        const filteredChildren = visit(node.children || []);
        if (filteredChildren.length > 0) {
          if (q || formatFilter !== 'all') {
            expandSet.add(node.rel_path);
          }
          out.push({ ...node, children: filteredChildren });
        }
        continue;
      }
      if (formatFilter !== 'all' && node.format !== formatFilter) {
        continue;
      }
      if (q) {
        const hay = `${node.name} ${node.rel_path}`.toLowerCase();
        if (!hay.includes(q)) continue;
      }
      out.push(node);
    }
    return out;
  };

  return {
    nodes: visit(nodes),
    autoExpandDirs: Array.from(expandSet),
  };
}

/**
 * Toggles a document in the pairwise Diff selection (`D-04`: strictly max 2 files).
 * When 2 files are already selected and a 3rd file is clicked, preserves the existing 2
 * files unchanged and returns `pendingThirdRelPath` so UI offers Replace A / Replace B / Cancel.
 */
export function togglePairSelection(
  selectedPair: string[],
  relPath: string,
): { nextPair: string[]; pendingThirdRelPath: string | null } {
  const idx = selectedPair.indexOf(relPath);
  if (idx >= 0) {
    return {
      nextPair: selectedPair.filter((p) => p !== relPath),
      pendingThirdRelPath: null,
    };
  }
  if (selectedPair.length < 2) {
    return {
      nextPair: [...selectedPair, relPath],
      pendingThirdRelPath: null,
    };
  }
  return {
    nextPair: selectedPair.slice(0, 2),
    pendingThirdRelPath: relPath,
  };
}

/** Replaces slot 0 (Old / A) or slot 1 (New / B) cleanly without introducing duplicates. */
export function replacePairSlot(selectedPair: string[], slot: 0 | 1, relPath: string): string[] {
  const next = selectedPair.slice(0, 2);
  const existingIdx = next.indexOf(relPath);
  if (existingIdx >= 0) return next;
  if (next.length < 2) {
    return [...next, relPath].slice(0, 2);
  }
  next[slot] = relPath;
  return next;
}

/** Computes default sibling `_revised` relative path for `D-05` Save-As mode. */
export function suggestRevisedRelPath(relPath: string): string {
  const norm = relPath.replace(/\\/g, '/').trim();
  const slash = norm.lastIndexOf('/');
  const dir = slash >= 0 ? norm.slice(0, slash + 1) : '';
  const name = slash >= 0 ? norm.slice(slash + 1) : norm;
  const dot = name.lastIndexOf('.');
  if (dot > 0) {
    return `${dir}${name.slice(0, dot)}_revised${name.slice(dot)}`;
  }
  return `${dir}${name}_revised`;
}
