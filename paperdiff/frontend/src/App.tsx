/**
 * @file App.tsx
 * @description Root application shell and state orchestrator for 对稿 · PaperDiff Studio (v1.1.0).
 *
 * Manages:
 * - Screen routing between Projects Home (`home`), Studio Workspace (`studio`), and User Guide (`guide`).
 * - Adaptive Read vs Compare routing (single-version docs open directly in Read Mode; multi-version
 *   docs open in Split/Inline Compare Mode with `R` / `V` / `J/K` / `N/P` / `⌘1` / `⌘2` shortcuts).
 * - Draft edit queues (`singleEdits` & `singlePatches`), guaranteed to reset automatically whenever
 *   `activeDocumentId` or `readVersionId` changes so pending patches never leak across documents.
 * - Export orchestration bridging both browser Blob downloads and native macOS `DesktopBridge`
 *   (`NSSavePanel` + offscreen `WKWebView` `NSPrintOperation` vector PDF export).
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  AlignJustify,
  ArrowLeftRight,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  Code2,
  Columns2,
  Copy,
  Download,
  FileCode2,
  FilePlus2,
  FileText,
  FileUp,
  FolderOpen,
  Globe,
  HelpCircle,
  Home,
  PanelLeftOpen,
  Plus,
  Save,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Zap,
} from 'lucide-react';
import { ApiError, api, exportPrintableHtmlAsPdf, triggerBlobDownload, triggerFileDownload, type RuntimeHealth } from './api';
import type {
  AppScreen,
  ComparisonResult,
  FilterMode,
  FontMode,
  IndentMode,
  LocalTreeNode,
  LocalTreeResponse,
  ParagraphDiff,
  ParagraphGap,
  Project,
  ReadWidthMode,
  SingleDocPreview,
  TextAlignMode,
  ThemePreference,
  TypedPatchOp,
  TypographyPrefs,
  VersionSummary,
  ViewMode,
} from './types';
import {
  TYPOGRAPHY_PRESET_ITEMS,
  applyTypographyPreset,
  normalizeTypographyPrefs,
  updateTypographyPref,
} from './utils/typography';
import {
  flattenLocalDocs,
  replacePairSlot,
  togglePairSelection,
} from './utils/localTree';
import { ProjectsHome, CATEGORY_META } from './components/ProjectsHome';
import { BrandAppIcon } from './components/BrandMark';
import { ProductGuideView } from './components/ProductGuideView';
import {
  applyThemePreference,
  loadSavedThemePreference,
  ThemeSegmentedControl,
} from './components/ThemeSwitcher';
import { DiffWorkspace } from './components/DiffWorkspace';
import { SingleDocWorkspace } from './components/SingleDocWorkspace';
import { LocalFileTreeSidebar } from './components/LocalFileTreeSidebar';
import { RuntimeControl, ServiceStoppedOverlay } from './components/RuntimeControl';
import { buildBrowserHandoffPath, parseStartupUrlContext } from './utils/runtime';
import {
  clearLastWorkspace,
  loadAutoResumePref,
  loadLastWorkspace,
  resolveResumeTarget,
  saveAutoResumePref,
  saveLastWorkspace,
  shouldAutoResumeOnStartup,
  type LastWorkspaceRecord,
} from './utils/workspaceResume';
import { FloatingOutline } from './components/FloatingOutline';
import { FloatingStepper } from './components/FloatingStepper';
import { EvaluationDrawer, ProjectDrawer, SingleAuditDrawer } from './components/OverlayDrawers';
import {
  AiLexiconModal,
  EditVersionModal,
  ExternalConflictModal,
  GlossaryModal,
  LocalBindingModal,
  NewDocumentModal,
  NewProjectModal,
  PdfExportModal,
  QuickCompareModal,
  SaveLocalEditsModal,
  SaveMergedVersionModal,
  UploadVersionModal,
} from './components/Modals';

const PREFS_KEY = 'paperdiff_ui_prefs';

function loadUiPrefs(): {
  fontMode: FontMode;
  fontSize: number;
  readWidth: ReadWidthMode;
  smartFold: boolean;
  showFigures: boolean;
  highlightAiIsms: boolean;
  typography: TypographyPrefs;
} {
  const defaults = {
    fontMode: 'serif' as FontMode,
    fontSize: 15.5,
    readWidth: 'standard' as ReadWidthMode,
    smartFold: true,
    showFigures: true,
    highlightAiIsms: true,
    typography: normalizeTypographyPrefs(null),
  };
  try {
    const raw = window.localStorage.getItem(PREFS_KEY);
    if (!raw) return defaults;
    const p = JSON.parse(raw);
    return {
      fontMode: p.fontMode === 'sans' ? 'sans' : 'serif',
      fontSize: typeof p.fontSize === 'number' ? Math.min(18.5, Math.max(13.5, p.fontSize)) : 15.5,
      readWidth: p.readWidth === 'wide' ? 'wide' : 'standard',
      smartFold: typeof p.smartFold === 'boolean' ? p.smartFold : true,
      showFigures: typeof p.showFigures === 'boolean' ? p.showFigures : true,
      highlightAiIsms: typeof p.highlightAiIsms === 'boolean' ? p.highlightAiIsms : true,
      typography: normalizeTypographyPrefs(p),
    };
  } catch {
    return defaults;
  }
}

export default function App() {
  const [screen, setScreen] = useState<AppScreen>('home');
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProjectId, setActiveProjectId] = useState<number | null>(null);
  const [activeDocumentId, setActiveDocumentId] = useState<number | null>(null);
  const [versions, setVersions] = useState<VersionSummary[]>([]);
  const [oldVersionId, setOldVersionId] = useState<number | null>(null);
  const [newVersionId, setNewVersionId] = useState<number | null>(null);
  const [readVersionId, setReadVersionId] = useState<number | null>(null);

  const [comparison, setComparison] = useState<ComparisonResult | null>(null);
  const [singlePreview, setSinglePreview] = useState<SingleDocPreview | null>(null);
  const [decisions, setDecisions] = useState<Record<string, 'accept_new' | 'keep_old'>>({});
  const [paragraphEdits, setParagraphEdits] = useState<Record<number, string>>({});
  const [singleEdits, setSingleEdits] = useState<Record<number, string>>({});
  const [singlePatches, setSinglePatches] = useState<TypedPatchOp[]>([]);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  // Quick mode state (supports both Quick Compare & Quick Single-Doc Preview)
  const [isQuickMode, setIsQuickMode] = useState(false);
  const [quickRaw, setQuickRaw] = useState<{
    oldText: string;
    newText: string;
    oldLabel: string;
    newLabel: string;
    oldMeta?: Record<string, unknown>;
    newMeta?: Record<string, unknown>;
  } | null>(null);
  const [quickSingleRaw, setQuickSingleRaw] = useState<{
    content: string;
    label: string;
    meta?: Record<string, unknown>;
  } | null>(null);

  // Studio UI controls (persisted locally for 1.0 desktop consistency)
  const initialPrefs = useMemo(() => loadUiPrefs(), []);
  const [viewMode, setViewMode] = useState<ViewMode>('split');
  const [lastNonSourceMode, setLastNonSourceMode] = useState<'read' | 'split' | 'inline'>('split');
  const [filterMode, setFilterMode] = useState<FilterMode>('all');
  const [fontMode, setFontMode] = useState<FontMode>(initialPrefs.fontMode);
  const [fontSize, setFontSize] = useState<number>(initialPrefs.fontSize);
  const [readWidth, setReadWidth] = useState<ReadWidthMode>(initialPrefs.readWidth);
  const [theme, setTheme] = useState<ThemePreference>(() => loadSavedThemePreference());
  const [smartFold, setSmartFold] = useState<boolean>(initialPrefs.smartFold);
  const [showFigures, setShowFigures] = useState<boolean>(initialPrefs.showFigures);
  const [highlightAiIsms, setHighlightAiIsms] = useState<boolean>(initialPrefs.highlightAiIsms);
  const [typographyPrefs, setTypographyPrefs] = useState<TypographyPrefs>(initialPrefs.typography);
  const [searchQuery, setSearchQuery] = useState('');
  const [highlightedPara, setHighlightedPara] = useState<number | null>(null);
  const [expandedAlerts, setExpandedAlerts] = useState<Record<number, boolean>>({});
  const mainScrollRef = useRef<HTMLElement | null>(null);

  const isReadContext = viewMode === 'read' || (viewMode === 'source' && lastNonSourceMode === 'read');

  // Overlay Drawers & Menus
  const [projectDrawerOpen, setProjectDrawerOpen] = useState(false);
  const [auditDrawerOpen, setAuditDrawerOpen] = useState(false);
  const [docMenuOpen, setDocMenuOpen] = useState(false);
  const [exportMenuOpen, setExportMenuOpen] = useState(false);
  const [settingsMenuOpen, setSettingsMenuOpen] = useState(false);

  // Stepper cursors
  const [changeCursor, setChangeCursor] = useState(-1);
  const [alertCursor, setAlertCursor] = useState(-1);

  // Global drag-and-drop file upload
  const [dragActive, setDragActive] = useState(false);
  const [droppedFile, setDroppedFile] = useState<File | null>(null);

  // Modals
  const [newProjOpen, setNewProjOpen] = useState(false);
  const [newDocProjectId, setNewDocProjectId] = useState<number | null>(null);
  const [uploadTarget, setUploadTarget] = useState<{ docId: number; docName: string; nextVer: number } | null>(null);
  const [saveMergedOpen, setSaveMergedOpen] = useState(false);
  const [editingVersion, setEditingVersion] = useState<VersionSummary | null>(null);
  const [quickOpen, setQuickOpen] = useState(false);
  const [glossaryProjectId, setGlossaryProjectId] = useState<number | null>(null);
  const [lexiconOpen, setLexiconOpen] = useState(false);
  const [pdfExportOpen, setPdfExportOpen] = useState(false);

  // W2 Local Folder Workspace state (isolated from managed upload flow)
  const [localSidebarOpen, setLocalSidebarOpen] = useState(true);
  const [localTree, setLocalTree] = useState<LocalTreeResponse | null>(null);
  const [localTreeLoading, setLocalTreeLoading] = useState(false);
  const [localTreeError, setLocalTreeError] = useState<{ code?: string; message: string } | null>(null);
  const [localIncludeAux, setLocalIncludeAux] = useState(false);
  const [localActiveRelPath, setLocalActiveRelPath] = useState<string | null>(null);
  const [localAuxPreview, setLocalAuxPreview] = useState<{
    relPath: string;
    kind: 'image' | 'text';
    text?: string;
  } | null>(null);
  const [localSelectedPair, setLocalSelectedPair] = useState<string[]>([]);
  const [localPendingThird, setLocalPendingThird] = useState<string | null>(null);
  const [localComparePair, setLocalComparePair] = useState<{ oldRel: string; newRel: string } | null>(null);
  const [localBindingModalProj, setLocalBindingModalProj] = useState<Project | null>(null);
  const [saveLocalModalOpen, setSaveLocalModalOpen] = useState(false);
  const [localExternalNotice, setLocalExternalNotice] = useState(false);
  const [localConflictOpen, setLocalConflictOpen] = useState(false);
  const [localFileError, setLocalFileError] = useState<string | null>(null);
  const lastFocusSyncRef = useRef<number>(0);

  // Runtime status & graceful shutdown state
  const [runtimeHealth, setRuntimeHealth] = useState<RuntimeHealth | null>(null);
  const [serviceStopped, setServiceStopped] = useState(false);
  const startupUrlHandledRef = useRef(false);

  // Last Workspace Resume & auto-resume toggle (default OFF)
  const [lastWorkspace, setLastWorkspace] = useState<LastWorkspaceRecord | null>(() => loadLastWorkspace());
  const [autoResumeEnabled, setAutoResumeEnabled] = useState<boolean>(() => loadAutoResumePref());
  const [resumeDismissed, setResumeDismissed] = useState(false);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast((cur) => (cur === msg ? null : cur)), 2400);
  }, []);

  const activeProject = projects.find((p) => p.id === activeProjectId) || null;
  const isLocalProject = !isQuickMode && activeProject?.project_mode === 'local_folder';
  const localDocs = useMemo(
    () => (localTree ? flattenLocalDocs(localTree.nodes) : []),
    [localTree],
  );
  const activeDocument =
    activeProject?.documents.find((d) => d.id === activeDocumentId) ||
    activeProject?.documents[0] ||
    null;

  const loadProjects = useCallback(async (selectProjId?: number, selectDocId?: number | null) => {
    const list = await api.listProjects();
    setProjects(list);
    const chosenProj =
      (selectProjId ? list.find((p) => p.id === selectProjId) : undefined) ||
      list.find((p) => p.id === activeProjectId) ||
      list[0] ||
      null;

    if (chosenProj) {
      setActiveProjectId(chosenProj.id);
      const chosenDoc =
        (selectDocId ? chosenProj.documents.find((d) => d.id === selectDocId) : undefined) ||
        chosenProj.documents.find((d) => d.id === activeDocumentId) ||
        chosenProj.documents[0] ||
        null;
      setActiveDocumentId(chosenDoc ? chosenDoc.id : null);
    } else {
      setActiveProjectId(null);
      setActiveDocumentId(null);
    }
    return list;
  }, [activeProjectId, activeDocumentId]);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        PREFS_KEY,
        JSON.stringify({
          fontMode,
          fontSize,
          readWidth,
          smartFold,
          showFigures,
          highlightAiIsms,
          ...typographyPrefs,
        }),
      );
    } catch {
      /* ignore */
    }
  }, [fontMode, fontSize, readWidth, smartFold, showFigures, highlightAiIsms, typographyPrefs]);

  useEffect(() => {
    applyThemePreference(theme);
    if (theme !== 'auto' || !window.matchMedia) return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onSystemChange = () => applyThemePreference('auto');
    mq.addEventListener('change', onSystemChange);
    return () => mq.removeEventListener('change', onSystemChange);
  }, [theme]);

  useEffect(() => {
    loadProjects();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadVersionsForDocument = useCallback(async (docId: number, preferredNewId?: number) => {
    const vers = await api.listDocVersions(docId);
    setVersions(vers);
    if (vers.length >= 2) {
      let chosenOld = vers[vers.length - 2].id;
      let chosenNew = vers[vers.length - 1].id;
      if (preferredNewId) {
        const idx = vers.findIndex((v) => v.id === preferredNewId);
        if (idx > 0) {
          chosenOld = vers[idx - 1].id;
          chosenNew = vers[idx].id;
        }
      } else {
        const isDemo = vers.length === 3 && vers[0].label.includes('v1 · AI 初稿');
        if (isDemo) {
          chosenOld = vers[0].id;
          chosenNew = vers[1].id;
        }
      }
      setOldVersionId(chosenOld);
      setNewVersionId(chosenNew);
      setReadVersionId(chosenNew);
      setViewMode('split');
      setLastNonSourceMode('split');
      return vers.length;
    }
    if (vers.length === 1) {
      setOldVersionId(null);
      setNewVersionId(null);
      setComparison(null);
      setReadVersionId(vers[0].id);
      setViewMode('read');
      setLastNonSourceMode('read');
      return 1;
    }
    setOldVersionId(null);
    setNewVersionId(null);
    setReadVersionId(null);
    setComparison(null);
    setSinglePreview(null);
    return 0;
  }, []);

  useEffect(() => {
    if (screen === 'studio' && !isQuickMode && activeDocumentId) {
      loadVersionsForDocument(activeDocumentId);
    }
  }, [screen, isQuickMode, activeDocumentId, loadVersionsForDocument]);

  const runDocumentCompare = useCallback(
    async (docId: number, oid: number, nid: number) => {
      setLoading(true);
      try {
        const res = await api.compareDocVersions(docId, oid, nid);
        setComparison(res);
        setDecisions(res.decisions || {});
        setParagraphEdits({});
        setChangeCursor(-1);
        setAlertCursor(-1);
        setExpandedAlerts({});
      } catch (e: unknown) {
        showToast(e instanceof Error ? e.message : '对比失败');
      } finally {
        setLoading(false);
      }
    },
    [showToast],
  );

  const runSinglePreview = useCallback(
    async (verId: number) => {
      setLoading(true);
      try {
        const res = await api.previewVersion(verId);
        setSinglePreview(res);
        setSingleEdits({});
        setSinglePatches([]);
      } catch (e: unknown) {
        showToast(e instanceof Error ? e.message : '文档预览加载失败');
      } finally {
        setLoading(false);
      }
    },
    [showToast],
  );

  useEffect(() => {
    if (
      screen === 'studio' &&
      !isQuickMode &&
      !isReadContext &&
      activeDocumentId &&
      oldVersionId &&
      newVersionId
    ) {
      runDocumentCompare(activeDocumentId, oldVersionId, newVersionId);
    }
  }, [screen, isQuickMode, isReadContext, activeDocumentId, oldVersionId, newVersionId, runDocumentCompare]);

  useEffect(() => {
    if (screen === 'studio' && !isQuickMode && isReadContext && readVersionId) {
      runSinglePreview(readVersionId);
    }
  }, [screen, isQuickMode, isReadContext, readVersionId, runSinglePreview]);

  useEffect(() => {
    setSinglePatches([]);
  }, [activeDocumentId, readVersionId]);

  const openDocumentInStudio = (projId: number, docId: number) => {
    setIsQuickMode(false);
    setQuickRaw(null);
    setQuickSingleRaw(null);
    setLocalTree(null);
    setLocalTreeError(null);
    setLocalActiveRelPath(null);
    setLocalAuxPreview(null);
    setLocalSelectedPair([]);
    setLocalPendingThird(null);
    setLocalComparePair(null);
    setLocalExternalNotice(false);
    setLocalConflictOpen(false);
    setLocalFileError(null);
    setActiveProjectId(projId);
    setActiveDocumentId(docId);
    setOldVersionId(null);
    setNewVersionId(null);
    setReadVersionId(null);
    setComparison(null);
    setSinglePreview(null);
    setSingleEdits({});
    setSinglePatches([]);
    setParagraphEdits({});
    setScreen('studio');
  };

  // ---------------- W2 Local Folder Workspace Actions ----------------

  const openLocalFileForRead = useCallback(
    async (projId: number, relPath: string) => {
      setLoading(true);
      setLocalFileError(null);
      setLocalAuxPreview(null);
      setLocalExternalNotice(false);
      setLocalConflictOpen(false);
      try {
        const prev = await api.previewLocalFile(projId, relPath);
        setSinglePreview(prev);
        setLocalActiveRelPath(prev.local_rel_path || relPath);
        setSingleEdits({});
        setSinglePatches([]);
        setViewMode('read');
        setLastNonSourceMode('read');
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : '读取本地文件失败';
        setSinglePreview(null);
        setLocalActiveRelPath(relPath);
        setLocalFileError(msg);
        showToast(msg);
      } finally {
        setLoading(false);
      }
    },
    [showToast],
  );

  const loadLocalTree = useCallback(
    async (projId: number, includeAux: boolean, autoOpenFirst = false) => {
      setLocalTreeLoading(true);
      setLocalTreeError(null);
      try {
        const treeRes = await api.getLocalTree(projId, includeAux);
        setLocalTree(treeRes);
        if (autoOpenFirst) {
          const docs = flattenLocalDocs(treeRes.nodes);
          if (docs.length > 0) {
            await openLocalFileForRead(projId, docs[0].rel_path);
          }
        }
        return treeRes;
      } catch (e: unknown) {
        const code = e instanceof ApiError ? e.code : undefined;
        const msg = e instanceof Error ? e.message : '扫描本地目录失败';
        setLocalTree(null);
        setLocalTreeError({ code, message: msg });
        return null;
      } finally {
        setLocalTreeLoading(false);
      }
    },
    [openLocalFileForRead],
  );

  const openLocalProjectInStudio = useCallback(
    async (projId: number, initialRelPath?: string | null) => {
      setIsQuickMode(false);
      setQuickRaw(null);
      setQuickSingleRaw(null);
      setActiveProjectId(projId);
      setActiveDocumentId(null);
      setVersions([]);
      setOldVersionId(null);
      setNewVersionId(null);
      setReadVersionId(null);
      setComparison(null);
      setSinglePreview(null);
      setSingleEdits({});
      setSinglePatches([]);
      setParagraphEdits({});
      setLocalActiveRelPath(null);
      setLocalAuxPreview(null);
      setLocalSelectedPair([]);
      setLocalPendingThird(null);
      setLocalComparePair(null);
      setLocalExternalNotice(false);
      setLocalConflictOpen(false);
      setLocalFileError(null);
      setLocalSidebarOpen(true);
      setViewMode('read');
      setLastNonSourceMode('read');
      setScreen('studio');
      const treeRes = await loadLocalTree(projId, localIncludeAux, !initialRelPath);
      if (initialRelPath && treeRes) {
        await openLocalFileForRead(projId, initialRelPath);
      }
    },
    [loadLocalTree, localIncludeAux, openLocalFileForRead],
  );

  // Fetch runtime health metadata and honor startup `?project=&file=` handoff
  useEffect(() => {
    api.getRuntimeHealth().then(setRuntimeHealth).catch(() => {});
  }, []);

  // Track last visited workspace whenever user enters or switches file/doc in Studio
  useEffect(() => {
    if (screen !== 'studio' || isQuickMode || !activeProject) return;
    const rec: LastWorkspaceRecord = {
      projectId: activeProject.id,
      projectName: activeProject.name,
      projectMode: activeProject.project_mode || 'managed',
      localRootPath: activeProject.local_root_path ?? null,
      localRelPath: activeProject.project_mode === 'local_folder' ? localActiveRelPath : null,
      documentId: activeProject.project_mode === 'local_folder' ? null : activeDocumentId,
      documentName: activeProject.project_mode === 'local_folder' ? null : activeDocument?.name ?? null,
      updatedAt: Date.now(),
    };
    saveLastWorkspace(rec);
    setLastWorkspace(rec);
    setResumeDismissed(false);
  }, [screen, isQuickMode, activeProject, activeDocumentId, activeDocument?.name, localActiveRelPath]);

  const resumeResolution = useMemo(
    () => (resumeDismissed ? ({ status: 'none' } as const) : resolveResumeTarget(lastWorkspace, projects)),
    [resumeDismissed, lastWorkspace, projects],
  );

  useEffect(() => {
    if (startupUrlHandledRef.current || projects.length === 0) return;
    startupUrlHandledRef.current = true;
    const ctx = parseStartupUrlContext(window.location.search);
    if (ctx.projectId) {
      const target = projects.find((p) => p.id === ctx.projectId);
      if (target) {
        if (target.project_mode === 'local_folder') {
          void openLocalProjectInStudio(target.id, ctx.fileRelPath);
        } else if (target.documents.length > 0) {
          setActiveProjectId(target.id);
          setActiveDocumentId(target.documents[0].id);
          setScreen('studio');
          void loadVersionsForDocument(target.documents[0].id);
        }
        return;
      }
    }

    const res = resolveResumeTarget(lastWorkspace, projects);
    if (res.status === 'missing_project') {
      clearLastWorkspace();
      setLastWorkspace(null);
      return;
    }
    if (autoResumeEnabled && res.status === 'root_invalid') {
      showToast(`上次本地目录不可用：${res.reason}，已返回项目首页`);
      return;
    }
    if (
      shouldAutoResumeOnStartup({
        explicitUrlProjectId: ctx.projectId,
        autoResumeEnabled,
        resolution: res,
      }) &&
      res.status === 'ready'
    ) {
      if (res.project.project_mode === 'local_folder') {
        void openLocalProjectInStudio(res.project.id, res.localRelPath);
      } else if (res.documentId) {
        setActiveProjectId(res.project.id);
        setActiveDocumentId(res.documentId);
        setScreen('studio');
        void loadVersionsForDocument(res.documentId);
      }
    }
  }, [projects, lastWorkspace, autoResumeEnabled, openLocalProjectInStudio, loadVersionsForDocument, showToast]);

  const runLocalPairCompare = useCallback(
    async (projId: number, oldRel: string, newRel: string, targetMode: 'split' | 'inline' = 'split') => {
      setLoading(true);
      setLocalFileError(null);
      try {
        const res = await api.compareLocalFiles(projId, {
          old_rel_path: oldRel,
          new_rel_path: newRel,
        });
        setComparison(res);
        setDecisions(res.decisions || {});
        setParagraphEdits({});
        setExpandedAlerts({});
        setLocalComparePair({ oldRel, newRel });
        setViewMode(targetMode);
        setLastNonSourceMode(targetMode);
      } catch (e: unknown) {
        showToast(e instanceof Error ? e.message : '本地文件两两对比失败');
      } finally {
        setLoading(false);
      }
    },
    [showToast],
  );

  const runLocalTrackedSplit = useCallback(
    async (projId: number, relPath: string) => {
      setLoading(true);
      try {
        const res = await api.compareLocalFiles(projId, {
          rel_path: relPath,
          docx_tracked_split: true,
        });
        setComparison(res);
        setDecisions(res.decisions || {});
        setParagraphEdits({});
        setExpandedAlerts({});
        setLocalComparePair(null);
        setViewMode('split');
        setLastNonSourceMode('split');
        showToast('已展开 Word 修订前 vs 修订后对比（不修改原文件）');
      } catch (e: unknown) {
        showToast(e instanceof Error ? e.message : '拆版对比失败');
      } finally {
        setLoading(false);
      }
    },
    [showToast],
  );

  const handleSelectLocalNode = useCallback(
    async (node: LocalTreeNode) => {
      if (!activeProjectId) return;
      if (node.kind === 'doc') {
        await openLocalFileForRead(activeProjectId, node.rel_path);
        return;
      }
      if (node.format === 'image') {
        setLocalAuxPreview({ relPath: node.rel_path, kind: 'image' });
        setLocalActiveRelPath(node.rel_path);
        setViewMode('read');
        setLastNonSourceMode('read');
        return;
      }
      try {
        const buf = await api.fetchLocalRawBlob(activeProjectId, node.rel_path);
        const txt = new TextDecoder('utf-8', { fatal: false }).decode(buf);
        setLocalAuxPreview({ relPath: node.rel_path, kind: 'text', text: txt });
        setLocalActiveRelPath(node.rel_path);
        setViewMode('read');
        setLastNonSourceMode('read');
      } catch (e: unknown) {
        showToast(e instanceof Error ? e.message : '无法预览辅助文件');
      }
    },
    [activeProjectId, openLocalFileForRead, showToast],
  );

  const syncLocalExternalChanges = useCallback(
    async (manual = false) => {
      if (!isLocalProject || !activeProjectId) return;
      const now = Date.now();
      if (!manual && now - lastFocusSyncRef.current < 1500) return;
      lastFocusSyncRef.current = now;

      await loadLocalTree(activeProjectId, localIncludeAux, false);

      const watchPaths: string[] = [];
      if (isReadContext && localActiveRelPath && singlePreview?.file_sha256) {
        watchPaths.push(localActiveRelPath);
      }
      if (!isReadContext && localComparePair) {
        watchPaths.push(localComparePair.oldRel, localComparePair.newRel);
      }
      if (watchPaths.length === 0) return;

      try {
        const st = await api.getLocalStat(activeProjectId, watchPaths);
        if (isReadContext && localActiveRelPath && singlePreview?.file_sha256) {
          const item = st.files[localActiveRelPath];
          if (item && item.exists && item.sha256 && item.sha256 !== singlePreview.file_sha256) {
            const hasUnsaved = Object.keys(singleEdits).length > 0 || singlePatches.length > 0;
            if (hasUnsaved) {
              setLocalConflictOpen(true);
            } else {
              setLocalExternalNotice(true);
            }
          }
        }
      } catch {
        /* ignore transient stat errors; tree recovery banner handles root loss */
      }
    },
    [
      isLocalProject,
      activeProjectId,
      loadLocalTree,
      localIncludeAux,
      isReadContext,
      localActiveRelPath,
      singlePreview?.file_sha256,
      localComparePair,
      singleEdits,
      singlePatches.length,
    ],
  );

  // D-06: Lightweight window-focus & visibilitychange auto-refresh for local bound projects
  useEffect(() => {
    if (screen !== 'studio' || !isLocalProject) return;
    const onFocus = () => {
      syncLocalExternalChanges(false);
    };
    const onVis = () => {
      if (document.visibilityState === 'visible') syncLocalExternalChanges(false);
    };
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onVis);
    return () => {
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [screen, isLocalProject, syncLocalExternalChanges]);

  const persistDecisions = useCallback(
    async (next: Record<string, 'accept_new' | 'keep_old'>) => {
      setDecisions(next);
      if (
        isLocalProject &&
        activeProjectId &&
        comparison?.local_old_rel_path &&
        comparison?.local_new_rel_path
      ) {
        try {
          await api.saveLocalPairState(activeProjectId, {
            old_rel_path: comparison.local_old_rel_path,
            new_rel_path: comparison.local_new_rel_path,
            decisions: next,
          });
        } catch {
          /* ignore */
        }
        return;
      }
      if (!isQuickMode && activeDocumentId && oldVersionId && newVersionId) {
        try {
          await api.saveDocMergeDecisions(activeDocumentId, oldVersionId, newVersionId, next);
        } catch {
          /* ignore */
        }
      }
    },
    [
      isLocalProject,
      activeProjectId,
      comparison?.local_old_rel_path,
      comparison?.local_new_rel_path,
      isQuickMode,
      activeDocumentId,
      oldVersionId,
      newVersionId,
    ],
  );

  const handleSetHunkDecision = (hunkId: string, choice: 'accept_new' | 'keep_old') => {
    const next = { ...decisions };
    if (choice === 'accept_new') delete next[hunkId];
    else next[hunkId] = 'keep_old';
    persistDecisions(next);
    showToast(choice === 'keep_old' ? '已回退保留旧版片段' : '已恢复采纳新版片段');
  };

  const handleSetParagraphDecision = (para: ParagraphDiff, choice: 'accept_new' | 'keep_old') => {
    const next = { ...decisions };
    for (const seg of para.segments) {
      if (seg.hunk_id) {
        if (choice === 'accept_new') delete next[seg.hunk_id];
        else next[seg.hunk_id] = 'keep_old';
      }
    }
    persistDecisions(next);
    showToast(choice === 'keep_old' ? '本段已全部回退旧版' : '本段已全部采纳新版');
  };

  const handleSaveParagraphEdit = (paraIndex: number, text: string | null) => {
    setParagraphEdits((prev) => {
      const next = { ...prev };
      if (text === null) delete next[paraIndex];
      else next[paraIndex] = text;
      return next;
    });
    showToast(text === null ? '已撤销本段微调' : '已暂存本段微调，可在底部「存为新版本」');
  };

  const handleSaveSingleEdit = (blockIndex: number, text: string | null) => {
    setSingleEdits((prev) => {
      const next = { ...prev };
      if (text === null) delete next[blockIndex];
      else next[blockIndex] = text;
      return next;
    });
    showToast(text === null ? '已恢复该段原稿' : '已暂存阅读态微调，可一键「存为新版本并对比」');
  };

  const handleJumpToParagraph = useCallback((paraIndex: number, openAlerts = false) => {
    if (openAlerts) {
      setExpandedAlerts((prev) => ({ ...prev, [paraIndex]: true }));
    }
    setHighlightedPara(paraIndex);
    requestAnimationFrame(() => {
      const el = document.getElementById(`para-${paraIndex}`);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
    setTimeout(() => setHighlightedPara((cur) => (cur === paraIndex ? null : cur)), 1800);
  }, []);

  const changedParaIndices = useMemo(
    () =>
      (comparison?.paragraphs || [])
        .filter((p) => p.block_type !== 'heading' && p.status !== 'unchanged')
        .map((p) => p.index),
    [comparison],
  );
  const alertParaIndices = useMemo(
    () =>
      (comparison?.paragraphs || [])
        .filter((p) => p.alerts.some((a) => !a.acked))
        .map((p) => p.index),
    [comparison],
  );

  const stepChange = useCallback(
    (dir: 1 | -1) => {
      if (changedParaIndices.length === 0) return;
      const next =
        changeCursor < 0
          ? dir === 1
            ? 0
            : changedParaIndices.length - 1
          : (changeCursor + dir + changedParaIndices.length) % changedParaIndices.length;
      setChangeCursor(next);
      handleJumpToParagraph(changedParaIndices[next]);
    },
    [changedParaIndices, changeCursor, handleJumpToParagraph],
  );

  const stepAlert = useCallback(
    (dir: 1 | -1) => {
      if (alertParaIndices.length === 0) return;
      const next =
        alertCursor < 0
          ? dir === 1
            ? 0
            : alertParaIndices.length - 1
          : (alertCursor + dir + alertParaIndices.length) % alertParaIndices.length;
      setAlertCursor(next);
      handleJumpToParagraph(alertParaIndices[next], true);
    },
    [alertParaIndices, alertCursor, handleJumpToParagraph],
  );

  const openUploadForDoc = useCallback(
    (projId: number, docId: number, preload: File | null = null) => {
      const p = projects.find((x) => x.id === projId);
      const d = p?.documents.find((x) => x.id === docId);
      setDroppedFile(preload);
      setUploadTarget({
        docId,
        docName: d?.name || '主文稿',
        nextVer: (d?.version_count || 0) + 1,
      });
    },
    [projects],
  );

  const handleQuickPreview = useCallback(
    async (
      content: string,
      label: string,
      meta?: Record<string, unknown>,
      preserveCompare = false,
    ) => {
      setLoading(true);
      try {
        const res = await api.quickPreview({
          content,
          label,
          filename: label,
          meta,
        });
        setIsQuickMode(true);
        if (!preserveCompare) {
          setQuickRaw(null);
          setComparison(null);
        }
        setQuickSingleRaw({ content, label, meta });
        setSinglePreview(res);
        setSingleEdits({});
        setSinglePatches([]);
        setViewMode('read');
        setLastNonSourceMode('read');
        setScreen('studio');
        showToast('单稿阅读预览就绪');
      } catch (e: unknown) {
        showToast(e instanceof Error ? e.message : '单稿预览失败');
      } finally {
        setLoading(false);
      }
    },
    [showToast],
  );

  const handleSwitchViewMode = useCallback(
    (nextMode: ViewMode) => {
      if (nextMode === 'source') {
        setViewMode('source');
        return;
      }
      if (nextMode === 'read') {
        if (isLocalProject) {
          setViewMode('read');
          setLastNonSourceMode('read');
          if (!singlePreview && activeProjectId) {
            const firstRel = localActiveRelPath || localComparePair?.newRel || localDocs[0]?.rel_path;
            if (firstRel) openLocalFileForRead(activeProjectId, firstRel);
          }
          return;
        }
        if (isQuickMode) {
          if (singlePreview) {
            setViewMode('read');
            setLastNonSourceMode('read');
          } else if (quickRaw) {
            handleQuickPreview(quickRaw.newText, quickRaw.newLabel, quickRaw.newMeta, true);
          }
          return;
        }
        const targetId = newVersionId || readVersionId || versions[versions.length - 1]?.id || null;
        if (targetId) setReadVersionId(targetId);
        setViewMode('read');
        setLastNonSourceMode('read');
        return;
      }

      // Switching to 'split' or 'inline' (Compare Mode)
      if (isLocalProject) {
        if (comparison) {
          setViewMode(nextMode);
          setLastNonSourceMode(nextMode);
          return;
        }
        if (activeProjectId && localSelectedPair.length === 2) {
          runLocalPairCompare(activeProjectId, localSelectedPair[0], localSelectedPair[1], nextMode);
          return;
        }
        setLocalSidebarOpen(true);
        showToast('请在左侧文件树勾选任意 2 个文件发起两两对比');
        return;
      }
      if (isQuickMode) {
        if (!quickRaw) {
          showToast('当前为单稿预览，添加第二份文稿即可开始对比');
          setQuickOpen(true);
          return;
        }
        setViewMode(nextMode);
        setLastNonSourceMode(nextMode);
        return;
      }

      if (versions.length < 2) {
        showToast('当前仅有 1 个版本，导入第二版即可开启对比');
        if (activeProjectId && activeDocumentId) {
          openUploadForDoc(activeProjectId, activeDocumentId);
        }
        return;
      }

      if (!oldVersionId || !newVersionId || oldVersionId === newVersionId) {
        const curNew =
          readVersionId && versions.some((v) => v.id === readVersionId)
            ? readVersionId
            : versions[versions.length - 1].id;
        const idx = versions.findIndex((v) => v.id === curNew);
        const curOld = idx > 0 ? versions[idx - 1].id : versions[0].id;
        const resolvedNew = curOld === curNew ? versions[versions.length - 1].id : curNew;
        setOldVersionId(curOld);
        setNewVersionId(resolvedNew);
      }
      setViewMode(nextMode);
      setLastNonSourceMode(nextMode);
    },
    [
      isQuickMode,
      singlePreview,
      quickRaw,
      handleQuickPreview,
      newVersionId,
      readVersionId,
      versions,
      showToast,
      activeProjectId,
      activeDocumentId,
      openUploadForDoc,
      oldVersionId,
    ],
  );

  // Global keyboard shortcuts in Studio
  useEffect(() => {
    if (screen !== 'studio') return;
    const onKeyDown = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName?.toLowerCase();
      const inInput = tag === 'input' || tag === 'textarea' || tag === 'select';

      if ((e.metaKey || e.ctrlKey) && e.key === '1') {
        e.preventDefault();
        setAuditDrawerOpen(false);
        if (isLocalProject) {
          setLocalSidebarOpen((v) => !v);
        } else {
          setProjectDrawerOpen((v) => !v);
        }
        return;
      }
      if ((e.metaKey || e.ctrlKey) && e.key === '2') {
        e.preventDefault();
        setProjectDrawerOpen(false);
        setAuditDrawerOpen((v) => !v);
        return;
      }
      if (e.key === 'Escape') {
        setProjectDrawerOpen(false);
        setAuditDrawerOpen(false);
        setDocMenuOpen(false);
        setExportMenuOpen(false);
        setSettingsMenuOpen(false);
        return;
      }
      if (
        inInput ||
        newProjOpen ||
        newDocProjectId !== null ||
        uploadTarget !== null ||
        saveMergedOpen ||
        editingVersion !== null ||
        quickOpen ||
        glossaryProjectId !== null ||
        lexiconOpen
      ) {
        return;
      }

      if (e.key === 'r' || e.key === 'R') {
        e.preventDefault();
        handleSwitchViewMode('read');
      } else if (!isReadContext && (e.key === 'j' || e.key === 'J')) {
        e.preventDefault();
        stepChange(1);
      } else if (!isReadContext && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault();
        stepChange(-1);
      } else if (!isReadContext && (e.key === 'n' || e.key === 'N')) {
        e.preventDefault();
        stepAlert(1);
      } else if (!isReadContext && (e.key === 'p' || e.key === 'P')) {
        e.preventDefault();
        stepAlert(-1);
      } else if (e.key === 'v' || e.key === 'V') {
        e.preventDefault();
        handleSwitchViewMode(viewMode === 'split' ? 'inline' : 'split');
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [
    screen,
    isReadContext,
    viewMode,
    handleSwitchViewMode,
    stepChange,
    stepAlert,
    newProjOpen,
    newDocProjectId,
    uploadTarget,
    saveMergedOpen,
    editingVersion,
    quickOpen,
    glossaryProjectId,
    lexiconOpen,
  ]);

  useEffect(() => {
    if (!exportMenuOpen && !settingsMenuOpen && !docMenuOpen) return;
    const onClick = (e: MouseEvent) => {
      const el = e.target as HTMLElement | null;
      if (el?.closest('[data-top-menu="true"]')) return;
      setExportMenuOpen(false);
      setSettingsMenuOpen(false);
      setDocMenuOpen(false);
    };
    window.addEventListener('mousedown', onClick);
    return () => window.removeEventListener('mousedown', onClick);
  }, [exportMenuOpen, settingsMenuOpen, docMenuOpen]);

  const handleQuickCompare = async (
    oldText: string,
    newText: string,
    oldLabel: string,
    newLabel: string,
    oldMeta?: Record<string, unknown>,
    newMeta?: Record<string, unknown>,
  ) => {
    setLoading(true);
    try {
      const res = await api.quickCompare({
        old_content: oldText,
        new_content: newText,
        old_label: oldLabel,
        new_label: newLabel,
        old_meta: oldMeta,
        new_meta: newMeta,
      });
      setIsQuickMode(true);
      setQuickRaw({ oldText, newText, oldLabel, newLabel, oldMeta, newMeta });
      setQuickSingleRaw(null);
      setSinglePreview(null);
      setComparison(res);
      setDecisions({});
      setParagraphEdits({});
      setExpandedAlerts({});
      setViewMode('split');
      setLastNonSourceMode('split');
      setScreen('studio');
      showToast('快速对比完成');
    } catch (e: unknown) {
      showToast(e instanceof Error ? e.message : '快速对比失败');
    } finally {
      setLoading(false);
    }
  };

  const handleToggleAlertAck = async (alertId: string) => {
    if (!comparison) return;
    const current = new Set(comparison.acked_alert_ids || []);
    const wasAcked = current.has(alertId);
    if (wasAcked) current.delete(alertId);
    else current.add(alertId);
    const nextIds = Array.from(current);

    if (
      isLocalProject &&
      activeProjectId &&
      comparison.local_old_rel_path &&
      comparison.local_new_rel_path
    ) {
      await api.saveLocalPairState(activeProjectId, {
        old_rel_path: comparison.local_old_rel_path,
        new_rel_path: comparison.local_new_rel_path,
        acked_ids: nextIds,
      });
      const updatedAlerts = comparison.alerts.map((a) =>
        a.alert_id === alertId ? { ...a, acked: !wasAcked } : a,
      );
      const activeCnt = updatedAlerts.filter((a) => !a.acked);
      setComparison({
        ...comparison,
        acked_alert_ids: nextIds,
        alerts: updatedAlerts,
        paragraphs: comparison.paragraphs.map((p) => ({
          ...p,
          alerts: p.alerts.map((a) => (a.alert_id === alertId ? { ...a, acked: !wasAcked } : a)),
        })),
        summary: {
          ...comparison.summary,
          alert_counts: {
            high: activeCnt.filter((a) => a.severity === 'high').length,
            medium: activeCnt.filter((a) => a.severity === 'medium').length,
            info: activeCnt.filter((a) => a.severity === 'info').length,
            total: activeCnt.length,
            acked: updatedAlerts.length - activeCnt.length,
          },
        },
      });
    } else if (!isQuickMode && activeDocumentId && oldVersionId && newVersionId) {
      await api.saveAlertAcks(activeDocumentId, oldVersionId, newVersionId, nextIds);
      await runDocumentCompare(activeDocumentId, oldVersionId, newVersionId);
    } else {
      // Quick mode local state update
      const updatedAlerts = comparison.alerts.map((a) =>
        a.alert_id === alertId ? { ...a, acked: !wasAcked } : a,
      );
      const activeCnt = updatedAlerts.filter((a) => !a.acked);
      setComparison({
        ...comparison,
        acked_alert_ids: nextIds,
        alerts: updatedAlerts,
        paragraphs: comparison.paragraphs.map((p) => ({
          ...p,
          alerts: p.alerts.map((a) => (a.alert_id === alertId ? { ...a, acked: !wasAcked } : a)),
        })),
        summary: {
          ...comparison.summary,
          alert_counts: {
            high: activeCnt.filter((a) => a.severity === 'high').length,
            medium: activeCnt.filter((a) => a.severity === 'medium').length,
            info: activeCnt.filter((a) => a.severity === 'info').length,
            total: activeCnt.length,
            acked: updatedAlerts.length - activeCnt.length,
          },
        },
      });
    }
    showToast(wasAcked ? '已恢复该告警' : '已标记为「核对无误」');
  };

  const handleExport = async (
    type: 'merged' | 'html' | 'latexdiff' | 'markdown' | 'docx_tracked' | 'docx_merged',
  ) => {
    if (!comparison) return;
    setExportMenuOpen(false);
    const isLatex = comparison.formats.new === 'latex' || comparison.formats.old === 'latex';
    const base = (activeDocument?.name || activeProject?.name || 'paperdiff').replace(
      /[^\w\u4e00-\u9fff-]+/g,
      '_',
    );
    const commonPayload = {
      local_project_id: isLocalProject && activeProjectId ? activeProjectId : undefined,
      local_old_rel_path: isLocalProject ? localComparePair?.oldRel : undefined,
      local_new_rel_path: isLocalProject ? localComparePair?.newRel : undefined,
      old_version_id: isQuickMode || isLocalProject ? undefined : oldVersionId || undefined,
      new_version_id: isQuickMode || isLocalProject ? undefined : newVersionId || undefined,
      old_content: isQuickMode ? quickRaw?.oldText : undefined,
      new_content: isQuickMode ? quickRaw?.newText : undefined,
      old_label: comparison.old_version.label,
      new_label: comparison.new_version.label,
      project_name: isQuickMode
        ? '快速对比'
        : isLocalProject
          ? activeProject?.name || '本地项目'
          : `${activeProject?.name || ''} · ${activeDocument?.name || ''}`,
      decisions,
      paragraph_edits: paragraphEdits,
      protected_terms: activeProject?.protected_terms || [],
    };

    if (type === 'docx_tracked' || type === 'docx_merged') {
      const blob = await api.exportBinary({ ...commonPayload, export_type: type });
      triggerBlobDownload(
        blob,
        `${base}_${type === 'docx_tracked' ? 'tracked_changes' : 'merged'}.docx`,
      );
      showToast(type === 'docx_tracked' ? '原生修订 Word (.docx) 已导出' : '干净融合 Word (.docx) 已导出');
      return;
    }

    const content = await api.exportContent({
      ...commonPayload,
      export_type: type,
      view_mode: viewMode === 'inline' ? 'inline' : 'split',
    });

    if (type === 'html') {
      triggerFileDownload(content, `${base}_diff_report.html`, 'text/html;charset=utf-8');
    } else if (type === 'latexdiff') {
      triggerFileDownload(content, `${base}_latexdiff.tex`);
    } else if (type === 'markdown') {
      triggerFileDownload(content, `${base}_revision_audit.md`, 'text/markdown;charset=utf-8');
    } else {
      triggerFileDownload(content, `${base}_merged.${isLatex ? 'tex' : 'md'}`);
    }
    showToast('文件已导出');
  };

  const handleCopyMerged = async () => {
    if (!comparison) return;
    setExportMenuOpen(false);
    const content = await api.exportContent({
      old_version_id: isQuickMode ? undefined : oldVersionId || undefined,
      new_version_id: isQuickMode ? undefined : newVersionId || undefined,
      old_content: isQuickMode ? quickRaw?.oldText : undefined,
      new_content: isQuickMode ? quickRaw?.newText : undefined,
      export_type: 'merged',
      decisions,
      paragraph_edits: paragraphEdits,
    });
    await navigator.clipboard.writeText(content);
    showToast('融合稿已复制到剪贴板');
  };

  const buildCombinedSinglePatches = useCallback((): TypedPatchOp[] => {
    const out: TypedPatchOp[] = [];
    const blkMap = new Map<number, string>();
    for (const b of singlePreview?.blocks || []) {
      blkMap.set(b.index, b.block_type);
    }
    for (const [kStr, val] of Object.entries(singleEdits)) {
      const idx = Number(kStr);
      const btype = blkMap.get(idx);
      out.push({
        op: btype === 'math' ? 'replace_math' : 'replace_block',
        block_index: idx,
        new_raw: val,
      });
    }
    out.push(...singlePatches);
    return out;
  }, [singleEdits, singlePatches, singlePreview]);

  const handleExportSingle = async (
    type:
      | 'single_html'
      | 'single_source'
      | 'docx_patched'
      | 'docx_tracked_preserved'
      | 'latex_zip_patched',
  ) => {
    if (!singlePreview) return;
    setExportMenuOpen(false);
    const isLatex = singlePreview.format === 'latex';
    const base = (
      activeDocument?.name ||
      activeProject?.name ||
      singlePreview.version.label ||
      'paperdiff'
    ).replace(/[^\w\u4e00-\u9fff-]+/g, '_');
    const combinedPatches = buildCombinedSinglePatches();

    if (
      type === 'docx_patched' ||
      type === 'docx_tracked_preserved' ||
      type === 'latex_zip_patched'
    ) {
      try {
        const blob = await api.exportBinary({
          version_id: isQuickMode ? undefined : readVersionId || undefined,
          single_content: isQuickMode ? quickSingleRaw?.content || singlePreview.raw_content : undefined,
          single_meta: isQuickMode ? quickSingleRaw?.meta : undefined,
          single_label: singlePreview.version.label,
          project_name: isQuickMode
            ? singlePreview.version.label
            : `${activeProject?.name || ''} · ${activeDocument?.name || ''}`,
          export_type: type,
          patches: combinedPatches,
          protected_terms: activeProject?.protected_terms || [],
        });
        const ext = type === 'latex_zip_patched' ? 'zip' : 'docx';
        const suffix =
          type === 'docx_tracked_preserved'
            ? 'tracked_preserved'
            : type === 'latex_zip_patched'
              ? 'overleaf_patched'
              : 'revised_preserved';
        triggerBlobDownload(blob, `${base}_${suffix}.${ext}`);
        showToast(
          type === 'latex_zip_patched'
            ? '无损 Overleaf 工程包 (.zip) 已导出'
            : type === 'docx_tracked_preserved'
              ? '保留原模板样式的红线修订 Word 已导出'
              : '保留原封面/样式的修订 Word 已导出',
        );
      } catch (e: unknown) {
        showToast(e instanceof Error ? e.message : '原格式回写导出失败');
      }
      return;
    }

    const content = await api.exportContent({
      version_id: isQuickMode ? undefined : readVersionId || undefined,
      single_content: isQuickMode ? quickSingleRaw?.content || singlePreview.raw_content : undefined,
      single_meta: isQuickMode ? quickSingleRaw?.meta : undefined,
      single_label: singlePreview.version.label,
      project_name: isQuickMode
        ? singlePreview.version.label
        : `${activeProject?.name || ''} · ${activeDocument?.name || ''}`,
      export_type: type,
      paragraph_edits: singleEdits,
      patches: combinedPatches,
      protected_terms: activeProject?.protected_terms || [],
      typography_prefs: type === 'single_html' ? typographyPrefs : undefined,
    });

    if (type === 'single_html') {
      triggerFileDownload(content, `${base}_reading.html`, 'text/html;charset=utf-8');
      showToast('独立阅读版 HTML 已导出（插图已内联，可离线打开）');
    } else {
      triggerFileDownload(content, `${base}_clean.${isLatex ? 'tex' : 'md'}`);
      showToast('干净源码已导出');
    }
  };

  const handleExportPdf = async (opts: {
    template: 'pdf_diff_report' | 'pdf_diff_compact' | 'pdf_single';
    commentaryNote: string;
    landscape: boolean;
  }) => {
    const base = (
      activeDocument?.name ||
      activeProject?.name ||
      singlePreview?.version.label ||
      'paperdiff'
    ).replace(/[^\w\u4e00-\u9fff-]+/g, '_');

    if (opts.template === 'pdf_single') {
      if (!singlePreview) return;
      const combinedPatches = buildCombinedSinglePatches();
      const basePayload = {
        local_project_id: isLocalProject && activeProjectId ? activeProjectId : undefined,
        local_rel_path: isLocalProject ? singlePreview.local_rel_path : undefined,
        version_id: isQuickMode || isLocalProject ? undefined : readVersionId || undefined,
        single_content: isQuickMode ? quickSingleRaw?.content || singlePreview.raw_content : undefined,
        single_meta: isQuickMode ? quickSingleRaw?.meta : undefined,
        single_label: singlePreview.version.label,
        project_name: isQuickMode
          ? singlePreview.version.label
          : isLocalProject
            ? `${activeProject?.name || ''} · ${singlePreview.local_rel_path || ''}`
            : `${activeProject?.name || ''} · ${activeDocument?.name || ''}`,
        paragraph_edits: singleEdits,
        patches: combinedPatches,
        protected_terms: activeProject?.protected_terms || [],
        commentary_note: opts.commentaryNote,
        landscape: opts.landscape,
        typography_prefs: typographyPrefs,
      };
      const printHtml = await api.exportContent({ ...basePayload, export_type: 'print_html_single' });
      const res = await exportPrintableHtmlAsPdf(
        printHtml,
        `${base}_reading.pdf`,
        opts.landscape,
        () => api.exportBinary({ ...basePayload, export_type: 'pdf_single' }),
      );
      if (res.saved) showToast('精排阅读版 PDF 已导出');
      return;
    }

    if (!comparison) return;
    const isCompact = opts.template === 'pdf_diff_compact';
    const basePayload = {
      local_project_id: isLocalProject && activeProjectId ? activeProjectId : undefined,
      local_old_rel_path: isLocalProject ? localComparePair?.oldRel : undefined,
      local_new_rel_path: isLocalProject ? localComparePair?.newRel : undefined,
      old_version_id: isQuickMode || isLocalProject ? undefined : oldVersionId || undefined,
      new_version_id: isQuickMode || isLocalProject ? undefined : newVersionId || undefined,
      old_content: isQuickMode ? quickRaw?.oldText : undefined,
      new_content: isQuickMode ? quickRaw?.newText : undefined,
      old_label: comparison.old_version.label,
      new_label: comparison.new_version.label,
      project_name: isQuickMode
        ? '快速对比'
        : isLocalProject
          ? activeProject?.name || '本地项目'
          : `${activeProject?.name || ''} · ${activeDocument?.name || ''}`,
      decisions,
      paragraph_edits: paragraphEdits,
      protected_terms: activeProject?.protected_terms || [],
      commentary_note: opts.commentaryNote,
      landscape: opts.landscape,
    };
    const printHtml = await api.exportContent({
      ...basePayload,
      export_type: isCompact ? 'print_html_diff_compact' : 'print_html_diff',
    });
    const res = await exportPrintableHtmlAsPdf(
      printHtml,
      `${base}_${isCompact ? 'diff_compact' : 'diff_report'}.pdf`,
      opts.landscape,
      () => api.exportBinary({ ...basePayload, export_type: opts.template }),
    );
    if (res.saved) showToast(isCompact ? '精简修订清单 PDF 已导出' : '版本对比与审校讲解报告 PDF 已导出');
  };

  const handleCopySingleSource = async () => {
    if (!singlePreview) return;
    setExportMenuOpen(false);
    if (Object.keys(singleEdits).length === 0) {
      await navigator.clipboard.writeText(singlePreview.raw_content);
      showToast('当前源码已复制到剪贴板');
      return;
    }
    const content = await api.exportContent({
      version_id: isQuickMode ? undefined : readVersionId || undefined,
      single_content: isQuickMode ? quickSingleRaw?.content || singlePreview.raw_content : undefined,
      single_meta: isQuickMode ? quickSingleRaw?.meta : undefined,
      single_label: singlePreview.version.label,
      export_type: 'single_source',
      paragraph_edits: singleEdits,
    });
    await navigator.clipboard.writeText(content);
    showToast('含微调的源码已复制到剪贴板');
  };

  const handleSaveMergedAsNewVersion = async (meta: {
    label: string;
    source_tag: string;
    notes: string;
    is_milestone: boolean;
  }) => {
    if (!activeDocumentId) return;
    if (isReadContext) {
      if (!readVersionId) return;
      const combined = buildCombinedSinglePatches();
      let created: VersionSummary;
      if (combined.length > 0) {
        const res = await api.applyTypedPatches(activeDocumentId, {
          base_version_id: readVersionId,
          patches: combined,
          ...meta,
        });
        created = res.version;
      } else {
        created = await api.saveSingleAsVersion(activeDocumentId, {
          base_version_id: readVersionId,
          paragraph_edits: singleEdits,
          ...meta,
        });
      }
      setSingleEdits({});
      setSinglePatches([]);
      await loadProjects(activeProjectId || undefined, activeDocumentId);
      await loadVersionsForDocument(activeDocumentId, created.id);
      showToast(`已无损存为新版本：${created.label}，自动进入对比校验`);
      return;
    }
    if (!oldVersionId || !newVersionId) return;
    const created = await api.saveMergedAsVersion(activeDocumentId, {
      old_version_id: oldVersionId,
      new_version_id: newVersionId,
      decisions,
      paragraph_edits: paragraphEdits,
      ...meta,
    });
    await loadProjects(activeProjectId || undefined, activeDocumentId);
    await loadVersionsForDocument(activeDocumentId, created.id);
    showToast(`已保存为新版本：${created.label}`);
  };

  const sum = comparison?.summary;
  const ev = comparison?.evaluation;
  const revertedCount = Object.values(decisions).filter((v) => v === 'keep_old').length;
  const editedParaCount = Object.keys(paragraphEdits).length;
  const singleEditedCount = Object.keys(singleEdits).length + singlePatches.length;
  const totalDraftEditsCount = editedParaCount + singleEditedCount;
  const browserHandoffPath = buildBrowserHandoffPath({
    screen,
    projectId: activeProjectId,
    localRelPath: isLocalProject ? localActiveRelPath : null,
  });

  const handleRequestRuntimeShutdown = useCallback(async () => {
    try {
      await api.requestRuntimeShutdown();
      setServiceStopped(true);
    } catch (e: unknown) {
      showToast(e instanceof Error ? e.message : '停止本地服务失败');
    }
  }, [showToast]);

  const runtimeControlNode = (
    <RuntimeControl
      health={runtimeHealth}
      handoffPath={browserHandoffPath}
      draftEditsCount={totalDraftEditsCount}
      onRequestShutdown={handleRequestRuntimeShutdown}
      onNotify={showToast}
    />
  );

  if (serviceStopped) {
    return <ServiceStoppedOverlay port={runtimeHealth?.port} />;
  }
  const newDocProject = projects.find((p) => p.id === newDocProjectId) || null;
  const glossaryProject = projects.find((p) => p.id === glossaryProjectId) || null;

  return (
    <>
      {screen === 'guide' ? (
        <ProductGuideView
          hasDemoProject={Boolean(projects[0]?.documents?.[0])}
          theme={theme}
          onChangeTheme={setTheme}
          onBackHome={() => setScreen('home')}
          onCreateProject={() => {
            setScreen('home');
            setNewProjOpen(true);
          }}
          onOpenDemo={() => {
            const p = projects[0];
            const d = p?.documents?.[0];
            if (p && d) openDocumentInStudio(p.id, d.id);
          }}
          onOpenQuick={() => setQuickOpen(true)}
        />
      ) : screen === 'home' ? (
        <ProjectsHome
          projects={projects}
          onOpenDocument={(pid, did) => openDocumentInStudio(pid, did)}
          onOpenLocalProject={(pid) => openLocalProjectInStudio(pid)}
          onManageLocalBinding={(proj) => setLocalBindingModalProj(proj)}
          onNewProject={() => setNewProjOpen(true)}
          onNewDocument={(pid) => setNewDocProjectId(pid)}
          onUploadToDocument={(pid, did) => openUploadForDoc(pid, did)}
          onUpdateProject={async (pid, patch) => {
            await api.updateProject(pid, patch);
            await loadProjects(pid);
            if (patch.name !== undefined || patch.description !== undefined) {
              showToast('已更新项目信息');
            }
          }}
          onDeleteProject={async (pid) => {
            if (!window.confirm('确定删除该项目及下属所有文档与版本吗？')) return;
            await api.deleteProject(pid);
            await loadProjects();
            showToast('已删除项目');
          }}
          onDeleteDocument={async (pid, did) => {
            if (!window.confirm('确定删除该文档及其全部历史版本吗？')) return;
            await api.deleteDocument(did);
            await loadProjects(pid);
            showToast('已删除文档');
          }}
          onOpenQuickCompare={() => setQuickOpen(true)}
          onOpenGlossary={(pid) => setGlossaryProjectId(pid)}
          onOpenGuide={() => setScreen('guide')}
          theme={theme}
          onChangeTheme={setTheme}
          runtimeSlot={runtimeControlNode}
          resumeResolution={resumeResolution}
          autoResumeEnabled={autoResumeEnabled}
          onToggleAutoResume={(enabled) => {
            setAutoResumeEnabled(enabled);
            saveAutoResumePref(enabled);
            showToast(enabled ? '已开启：下次启动将自动恢复上次工作区' : '已关闭启动自动恢复');
          }}
          onResumeWorkspace={() => {
            if (resumeResolution.status !== 'ready') return;
            if (resumeResolution.project.project_mode === 'local_folder') {
              void openLocalProjectInStudio(resumeResolution.project.id, resumeResolution.localRelPath);
            } else if (resumeResolution.documentId) {
              openDocumentInStudio(resumeResolution.project.id, resumeResolution.documentId);
            }
          }}
          onDismissResume={() => setResumeDismissed(true)}
        />
      ) : (
        <div
          className="relative flex h-screen w-screen flex-col overflow-hidden bg-[#F6F7F9] text-slate-900"
          onDragOver={(e) => {
            if (e.dataTransfer.types.includes('Files')) {
              e.preventDefault();
              if (!dragActive) setDragActive(true);
            }
          }}
          onDragLeave={(e) => {
            if (e.currentTarget === e.target) setDragActive(false);
          }}
          onDrop={(e) => {
            e.preventDefault();
            setDragActive(false);
            const f = e.dataTransfer.files?.[0];
            if (f && activeProjectId && activeDocumentId) {
              openUploadForDoc(activeProjectId, activeDocumentId, f);
            }
          }}
        >
          {/* =====================================================================
           * SINGLE UNIFIED TOP BAR (52px) with 3-Level Breadcrumb!
           * =================================================================== */}
          <header className="z-30 flex h-[52px] shrink-0 items-center justify-between gap-2 border-b border-[#E6E8EE] bg-white px-3.5">
            {/* Left: Home + Breadcrumb (Project / Document) + Version Pair */}
            <div className="flex items-center gap-1.5 min-w-0" data-top-menu="true">
              <button
                type="button"
                onClick={() => setScreen('home')}
                title="返回项目工作台"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl transition-opacity hover:opacity-80"
              >
                <BrandAppIcon size={28} />
              </button>

              {isQuickMode ? (
                <div className="flex items-center gap-1.5">
                  <span className="rounded-lg bg-blue-50 border border-blue-200 px-2.5 py-1 text-xs font-semibold text-blue-700">
                    {isReadContext && !quickRaw ? '单稿阅读预览' : '快速对比模式'}
                  </span>
                  <button
                    type="button"
                    onClick={() => setQuickOpen(true)}
                    className="rounded-lg border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
                  >
                    {isReadContext && !quickRaw ? '添加对比稿' : '修改文本'}
                  </button>
                </div>
              ) : isLocalProject && activeProject ? (
                <div className="flex items-center gap-1.5 min-w-0">
                  {!localSidebarOpen && (
                    <button
                      type="button"
                      onClick={() => setLocalSidebarOpen(true)}
                      title="展开本地文件树 (⌘1)"
                      className="rounded-lg border border-slate-200 bg-white p-1.5 text-slate-600 hover:bg-slate-50"
                    >
                      <PanelLeftOpen className="h-3.5 w-3.5" />
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setLocalSidebarOpen((v) => !v)}
                    title="展开/收起本地文件夹树 (⌘1)"
                    className="flex items-center gap-1.5 rounded-lg border border-teal-200 bg-teal-50/70 px-2 py-1 text-xs font-bold text-teal-800 hover:bg-teal-100/70 max-w-[165px]"
                  >
                    <FolderOpen className="h-3.5 w-3.5 shrink-0 text-teal-600" />
                    <span className="truncate">{activeProject.name}</span>
                  </button>
                  <span className="text-slate-300 text-xs select-none">/</span>

                  {isReadContext ? (
                    <select
                      data-local-read-select="true"
                      value={localActiveRelPath || ''}
                      onChange={(e) => {
                        if (e.target.value && activeProjectId) {
                          openLocalFileForRead(activeProjectId, e.target.value);
                        }
                      }}
                      className="max-w-[230px] truncate rounded-lg border border-blue-200/90 bg-blue-50/40 px-2.5 py-1 text-xs font-semibold text-slate-800 focus:border-blue-500 focus:outline-none"
                    >
                      {localDocs.length === 0 && <option value="">本地目录暂无文稿</option>}
                      {localDocs.map((d) => (
                        <option key={d.rel_path} value={d.rel_path}>
                          阅读：{d.rel_path}
                        </option>
                      ))}
                    </select>
                  ) : localComparePair ? (
                    <div className="flex items-center gap-1">
                      <select
                        data-local-diff-old-select="true"
                        value={localComparePair.oldRel}
                        onChange={(e) => {
                          if (activeProjectId && e.target.value) {
                            runLocalPairCompare(activeProjectId, e.target.value, localComparePair.newRel, viewMode === 'inline' ? 'inline' : 'split');
                          }
                        }}
                        className="max-w-[148px] truncate rounded-lg border border-rose-200/90 bg-rose-50/40 px-2 py-1 text-xs font-semibold text-slate-800 focus:border-blue-500 focus:outline-none"
                      >
                        {localDocs.map((d) => (
                          <option key={d.rel_path} value={d.rel_path}>
                            A：{d.rel_path}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        data-local-diff-swap="true"
                        onClick={() => {
                          if (activeProjectId) {
                            runLocalPairCompare(
                              activeProjectId,
                              localComparePair.newRel,
                              localComparePair.oldRel,
                              viewMode === 'inline' ? 'inline' : 'split',
                            );
                          }
                        }}
                        title="一键互换对比文件 A ⇄ B"
                        className="rounded-md p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-800"
                      >
                        <ArrowLeftRight className="h-3.5 w-3.5" />
                      </button>
                      <select
                        data-local-diff-new-select="true"
                        value={localComparePair.newRel}
                        onChange={(e) => {
                          if (activeProjectId && e.target.value) {
                            runLocalPairCompare(activeProjectId, localComparePair.oldRel, e.target.value, viewMode === 'inline' ? 'inline' : 'split');
                          }
                        }}
                        className="max-w-[148px] truncate rounded-lg border border-emerald-200/90 bg-emerald-50/40 px-2 py-1 text-xs font-semibold text-slate-800 focus:border-blue-500 focus:outline-none"
                      >
                        {localDocs.map((d) => (
                          <option key={d.rel_path} value={d.rel_path}>
                            B：{d.rel_path}
                          </option>
                        ))}
                      </select>
                    </div>
                  ) : (
                    <span className="rounded-lg bg-amber-50 border border-amber-200 px-2.5 py-1 text-xs font-semibold text-amber-800">
                      {comparison ? `${comparison.old_version.label} ⇄ ${comparison.new_version.label}` : '在左侧勾选 2 个文件对比'}
                    </span>
                  )}
                </div>
              ) : (
                <>
                  {/* Project Breadcrumb Trigger -> Opens ⌘1 3-Level Drawer */}
                  <button
                    type="button"
                    onClick={() => setProjectDrawerOpen(true)}
                    title="打开三级层级导航树 (⌘1)"
                    className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-bold text-slate-700 hover:bg-slate-100 max-w-[160px]"
                  >
                    {activeProject && (
                      <span
                        className={`h-2 w-2 rounded-full shrink-0 ${
                          (CATEGORY_META[activeProject.category] || CATEGORY_META.paper).dot
                        }`}
                      />
                    )}
                    <span className="truncate">{activeProject?.name || '项目'}</span>
                  </button>

                  <span className="text-slate-300 text-xs select-none">/</span>

                  {/* Document Switcher Dropdown */}
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => {
                        setExportMenuOpen(false);
                        setSettingsMenuOpen(false);
                        setDocMenuOpen((v) => !v);
                      }}
                      className="inline-flex items-center gap-1 rounded-lg border border-slate-200/80 bg-[#FAFBFC] px-2 py-1 text-xs font-semibold text-slate-800 hover:border-blue-300 max-w-[155px]"
                    >
                      <FileText className="h-3.5 w-3.5 text-blue-600 shrink-0" />
                      <span className="truncate">{activeDocument?.name || '主文稿'}</span>
                      <ChevronDown className="h-3 w-3 text-slate-400 shrink-0" />
                    </button>
                    {docMenuOpen && activeProject && (
                      <div className="absolute left-0 mt-1.5 w-60 rounded-2xl border border-slate-200 bg-white p-1.5 shadow-xl z-40">
                        <div className="px-2.5 py-1 text-[10.5px] font-semibold uppercase tracking-wider text-slate-400">
                          本项目下的文档 ({activeProject.documents.length})
                        </div>
                        {activeProject.documents.map((doc) => (
                          <button
                            key={doc.id}
                            type="button"
                            onClick={() => {
                              setDocMenuOpen(false);
                              openDocumentInStudio(activeProject.id, doc.id);
                            }}
                            className={`flex w-full items-center justify-between rounded-xl px-2.5 py-2 text-xs ${
                              doc.id === activeDocumentId
                                ? 'bg-blue-50 font-semibold text-blue-700'
                                : 'text-slate-700 hover:bg-slate-50'
                            }`}
                          >
                            <span className="truncate">{doc.name}</span>
                            <span className="text-[10.5px] text-slate-400 tabular-nums">
                              {doc.version_count} 版
                            </span>
                          </button>
                        ))}
                        <div className="mt-1 border-t border-slate-100 pt-1">
                          <button
                            type="button"
                            onClick={() => {
                              setDocMenuOpen(false);
                              setNewDocProjectId(activeProject.id);
                            }}
                            className="flex w-full items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-xs font-semibold text-blue-600 hover:bg-blue-50"
                          >
                            <Plus className="h-3.5 w-3.5" />
                            添加新文档（如 SI / 回复）
                          </button>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Adaptive Version Selector: Single selector in Read Mode, Pair selector in Compare Mode */}
                  {versions.length >= 1 ? (
                    isReadContext ? (
                      <div className="flex items-center gap-1.5 ml-1">
                        {versions.length > 1 ? (
                          <select
                            value={readVersionId ?? ''}
                            onChange={(e) => {
                              setReadVersionId(Number(e.target.value));
                              setSingleEdits({});
                              setSinglePatches([]);
                            }}
                            className="max-w-[168px] truncate rounded-lg border border-blue-200/90 bg-blue-50/40 px-2.5 py-1 text-xs font-semibold text-slate-800 focus:border-blue-500 focus:outline-none"
                          >
                            {versions.map((v) => (
                              <option key={v.id} value={v.id}>
                                {v.is_milestone ? '★ ' : ''}阅读：{v.label}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="max-w-[168px] truncate rounded-lg border border-blue-200/80 bg-blue-50/50 px-2.5 py-1 text-xs font-semibold text-blue-800">
                            {versions[0].is_milestone ? '★ ' : ''}
                            {versions[0].label}
                          </span>
                        )}
                        {activeProjectId && activeDocumentId && (
                          <button
                            type="button"
                            onClick={() => openUploadForDoc(activeProjectId, activeDocumentId)}
                            className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 shrink-0"
                          >
                            <FilePlus2 className="h-3.5 w-3.5" />
                            {versions.length === 1 ? '导入新版并对比' : '传新版'}
                          </button>
                        )}
                      </div>
                    ) : (
                      <div className="flex items-center gap-1 ml-1">
                        <select
                          value={oldVersionId ?? ''}
                          onChange={(e) => setOldVersionId(Number(e.target.value))}
                          className="max-w-[132px] truncate rounded-lg border border-rose-200/90 bg-rose-50/40 px-2 py-1 text-xs font-semibold text-slate-800 focus:border-blue-500 focus:outline-none"
                        >
                          {versions.map((v) => (
                            <option key={v.id} value={v.id}>
                              {v.is_milestone ? '★ ' : ''}旧：{v.label}
                            </option>
                          ))}
                        </select>
                        <button
                          type="button"
                          onClick={() => {
                            if (oldVersionId && newVersionId) {
                              setOldVersionId(newVersionId);
                              setNewVersionId(oldVersionId);
                            }
                          }}
                          title="互换新旧版本"
                          className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                        >
                          <ArrowLeftRight className="h-3.5 w-3.5" />
                        </button>
                        <select
                          value={newVersionId ?? ''}
                          onChange={(e) => setNewVersionId(Number(e.target.value))}
                          className="max-w-[132px] truncate rounded-lg border border-emerald-200/90 bg-emerald-50/40 px-2 py-1 text-xs font-semibold text-slate-800 focus:border-blue-500 focus:outline-none"
                        >
                          {versions.map((v) => (
                            <option key={v.id} value={v.id}>
                              {v.is_milestone ? '★ ' : ''}新：{v.label}
                            </option>
                          ))}
                        </select>
                        {activeProjectId && activeDocumentId && (
                          <button
                            type="button"
                            onClick={() => openUploadForDoc(activeProjectId, activeDocumentId)}
                            className="ml-0.5 inline-flex items-center gap-1 rounded-lg bg-blue-600 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 shrink-0"
                          >
                            <FilePlus2 className="h-3.5 w-3.5" />
                            传新版
                          </button>
                        )}
                      </div>
                    )
                  ) : (
                    activeProjectId &&
                    activeDocumentId && (
                      <button
                        type="button"
                        onClick={() => openUploadForDoc(activeProjectId, activeDocumentId)}
                        className="ml-1 inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700"
                      >
                        <FilePlus2 className="h-3.5 w-3.5" />
                        导入第一版
                      </button>
                    )
                  )}
                </>
              )}
            </div>

            {/* Center: Unified 4-State View Switcher (Read | Split | Inline | Source) */}
            <div className="flex items-center rounded-xl bg-slate-100 p-0.5 text-xs font-medium shrink-0">
              <button
                type="button"
                onClick={() => handleSwitchViewMode('read')}
                title="单文档纯净阅读预览 (R)"
                className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 transition-all ${
                  viewMode === 'read'
                    ? 'bg-white text-blue-700 shadow-xs font-semibold'
                    : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                <BookOpen className="h-3.5 w-3.5" />
                阅读
              </button>
              <button
                type="button"
                onClick={() => handleSwitchViewMode('split')}
                className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 transition-all ${
                  viewMode === 'split'
                    ? 'bg-white text-slate-900 shadow-xs font-semibold'
                    : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                <Columns2 className="h-3.5 w-3.5" />
                左右对照
              </button>
              <button
                type="button"
                onClick={() => handleSwitchViewMode('inline')}
                className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 transition-all ${
                  viewMode === 'inline'
                    ? 'bg-white text-slate-900 shadow-xs font-semibold'
                    : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                <AlignJustify className="h-3.5 w-3.5" />
                行内融合
              </button>
              <button
                type="button"
                onClick={() => handleSwitchViewMode('source')}
                className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 transition-all ${
                  viewMode === 'source'
                    ? 'bg-white text-slate-900 shadow-xs font-semibold'
                    : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                <Code2 className="h-3.5 w-3.5" />
                源码
              </button>
            </div>

            {/* Right: Adaptive Audit Drawer Trigger + Export Dropdown + Settings */}
            <div className="flex items-center gap-1.5 shrink-0" data-top-menu="true">
              {isReadContext && singlePreview ? (
                <button
                  type="button"
                  onClick={() => setAuditDrawerOpen(true)}
                  title="打开单稿自检与学术体检抽屉 (⌘2)"
                  className={`inline-flex items-center gap-1.5 rounded-xl border px-2.5 py-1.5 text-xs font-semibold transition-all ${
                    singlePreview.summary.issue_counts.high > 0
                      ? 'border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100'
                      : singlePreview.summary.issue_counts.total > 0 || singlePreview.summary.ai_ism_count > 0
                        ? 'border-violet-200 bg-violet-50 text-violet-700 hover:bg-violet-100'
                        : 'border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
                  }`}
                >
                  {singlePreview.summary.issue_counts.total > 0 ? (
                    <>
                      <AlertTriangle className="h-3.5 w-3.5" />
                      <span>{singlePreview.summary.issue_counts.total} 提示</span>
                    </>
                  ) : (
                    <>
                      <Sparkles className="h-3.5 w-3.5" />
                      <span>单稿体检</span>
                    </>
                  )}
                  <span className="opacity-40">·</span>
                  <span className="tabular-nums">{singlePreview.health_score}分</span>
                </button>
              ) : (
                !isReadContext &&
                sum &&
                ev && (
                  <button
                    type="button"
                    onClick={() => setAuditDrawerOpen(true)}
                    title="打开评判与事实审计抽屉 (⌘2)"
                    className={`inline-flex items-center gap-1.5 rounded-xl border px-2.5 py-1.5 text-xs font-semibold transition-all ${
                      sum.alert_counts.high > 0
                        ? 'border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100'
                        : sum.alert_counts.total > 0
                          ? 'border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100'
                          : 'border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
                    }`}
                  >
                    {sum.alert_counts.total > 0 ? (
                      <>
                        <AlertTriangle className="h-3.5 w-3.5" />
                        <span>{sum.alert_counts.total} 告警</span>
                      </>
                    ) : (
                      <>
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        <span>守恒通过</span>
                      </>
                    )}
                    <span className="opacity-40">·</span>
                    <span className="tabular-nums">{ev.overall_health}分</span>
                  </button>
                )
              )}

              {(isReadContext ? Boolean(singlePreview) : Boolean(comparison)) && (
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => {
                      setSettingsMenuOpen(false);
                      setDocMenuOpen(false);
                      setExportMenuOpen((v) => !v);
                    }}
                    className="inline-flex items-center gap-1 rounded-xl border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                  >
                    <Download className="h-3.5 w-3.5" />
                    导出
                    <ChevronDown className="h-3 w-3 text-slate-400" />
                  </button>
                  {exportMenuOpen && isReadContext && singlePreview && (
                    <div className="absolute right-0 mt-2 w-64 rounded-2xl border border-slate-200 bg-white p-1.5 shadow-xl z-40">
                      {!isQuickMode && activeDocumentId && singleEditedCount > 0 && (
                        <button
                          type="button"
                          onClick={() => {
                            setExportMenuOpen(false);
                            setSaveMergedOpen(true);
                          }}
                          className="flex w-full items-center gap-2.5 rounded-xl bg-emerald-50/70 px-3 py-2 text-left text-xs hover:bg-emerald-100/70 mb-1"
                        >
                          <Save className="h-4 w-4 text-emerald-600 shrink-0" />
                          <div>
                            <div className="font-bold text-emerald-800">
                              修订稿存为新版本 (v{versions.length + 1})
                            </div>
                            <div className="text-[10.5px] text-emerald-700/80">
                              微调 {singleEditedCount} 段无损入库并进入对比
                            </div>
                          </div>
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => {
                          setExportMenuOpen(false);
                          setPdfExportOpen(true);
                        }}
                        className="flex w-full items-center gap-2.5 rounded-xl bg-blue-50/70 px-3 py-2 text-left text-xs hover:bg-blue-100/70 mb-1"
                      >
                        <Download className="h-4 w-4 text-blue-600 shrink-0" />
                        <div>
                          <div className="font-bold text-blue-800">导出精排阅读版 PDF</div>
                          <div className="text-[10.5px] text-blue-700/80">100% 离线矢量公式、三线表与插图</div>
                        </div>
                      </button>
                      {singlePreview.format === 'docx' && singlePreview.version.source_blob_key && (
                        <>
                          <button
                            type="button"
                            onClick={() => handleExportSingle('docx_patched')}
                            className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-xs hover:bg-slate-50"
                          >
                            <FileText className="h-4 w-4 text-indigo-600 shrink-0" />
                            <div>
                              <div className="font-semibold text-slate-800">导出原格式修订 Word (.docx)</div>
                              <div className="text-[10.5px] text-slate-400">原位写回模板，完整保留封面与样式</div>
                            </div>
                          </button>
                          <button
                            type="button"
                            onClick={() => handleExportSingle('docx_tracked_preserved')}
                            className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-xs hover:bg-slate-50"
                          >
                            <FileText className="h-4 w-4 text-sky-600 shrink-0" />
                            <div>
                              <div className="font-semibold text-slate-800">导出保留模板红线修订 Word</div>
                              <div className="text-[10.5px] text-slate-400">在原封面模板内写入原生修订标记</div>
                            </div>
                          </button>
                        </>
                      )}
                      {singlePreview.format === 'latex' && singlePreview.version.source_blob_key && (
                        <button
                          type="button"
                          onClick={() => handleExportSingle('latex_zip_patched')}
                          className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-xs hover:bg-slate-50"
                        >
                          <FileCode2 className="h-4 w-4 text-violet-600 shrink-0" />
                          <div>
                            <div className="font-semibold text-slate-800">导出无损 Overleaf 工程包 (.zip)</div>
                            <div className="text-[10.5px] text-slate-400">多文件原位回写，保留所有插图与 .bib</div>
                          </div>
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => handleExportSingle('single_html')}
                        className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-xs hover:bg-slate-50"
                      >
                        <Globe className="h-4 w-4 text-emerald-600 shrink-0" />
                        <div>
                          <div className="font-semibold text-slate-800">导出离线阅读版 (HTML)</div>
                          <div className="text-[10.5px] text-slate-400">插图内联，离线用浏览器直接打开</div>
                        </div>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleExportSingle('single_source')}
                        className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-xs hover:bg-slate-50"
                      >
                        <FileText className="h-4 w-4 text-blue-600 shrink-0" />
                        <div>
                          <div className="font-semibold text-slate-800">导出当前源码 (.tex/.md)</div>
                          <div className="text-[10.5px] text-slate-400">保留原结构并应用阅读态微调</div>
                        </div>
                      </button>
                      <button
                        type="button"
                        onClick={handleCopySingleSource}
                        className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-xs hover:bg-slate-50"
                      >
                        <Copy className="h-4 w-4 text-slate-600 shrink-0" />
                        <div>
                          <div className="font-semibold text-slate-800">复制全文源码</div>
                          <div className="text-[10.5px] text-slate-400">粘贴回 Overleaf 或本地编辑器</div>
                        </div>
                      </button>
                    </div>
                  )}
                  {exportMenuOpen && !isReadContext && comparison && (
                    <div className="absolute right-0 mt-2 w-64 rounded-2xl border border-slate-200 bg-white p-1.5 shadow-xl z-40">
                      {!isQuickMode && activeDocumentId && (
                        <button
                          type="button"
                          onClick={() => {
                            setExportMenuOpen(false);
                            setSaveMergedOpen(true);
                          }}
                          className="flex w-full items-center gap-2.5 rounded-xl bg-emerald-50/70 px-3 py-2 text-left text-xs hover:bg-emerald-100/70 mb-1"
                        >
                          <Save className="h-4 w-4 text-emerald-600 shrink-0" />
                          <div>
                            <div className="font-bold text-emerald-800">
                              融合稿存为新版本 (v{versions.length + 1})
                            </div>
                            <div className="text-[10.5px] text-emerald-700/80">
                              回退 {revertedCount} 处 · 微调 {editedParaCount} 段直接入库
                            </div>
                          </div>
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => {
                          setExportMenuOpen(false);
                          setPdfExportOpen(true);
                        }}
                        className="flex w-full items-center gap-2.5 rounded-xl bg-blue-50/75 px-3 py-2 text-left text-xs hover:bg-blue-100/75 mb-1"
                      >
                        <Download className="h-4 w-4 text-blue-600 shrink-0" />
                        <div>
                          <div className="font-bold text-blue-800">导出审校讲解报告 PDF</div>
                          <div className="text-[10.5px] text-blue-700/80">含 4 维评分卡、自动中文讲解与精简版</div>
                        </div>
                      </button>
                      <button
                        type="button"
                        onClick={handleCopyMerged}
                        className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-xs hover:bg-slate-50"
                      >
                        <Copy className="h-4 w-4 text-blue-600 shrink-0" />
                        <div>
                          <div className="font-semibold text-slate-800">复制融合后源码</div>
                          <div className="text-[10.5px] text-slate-400">粘贴回 Overleaf 或本地编辑器</div>
                        </div>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleExport('merged')}
                        className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-xs hover:bg-slate-50"
                      >
                        <FileText className="h-4 w-4 text-blue-600 shrink-0" />
                        <div>
                          <div className="font-semibold text-slate-800">导出无损融合稿 (.tex/.md)</div>
                          <div className="text-[10.5px] text-slate-400">完整保留 LaTeX 导言区与插图</div>
                        </div>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleExport('docx_tracked')}
                        className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-xs hover:bg-slate-50"
                      >
                        <FileText className="h-4 w-4 text-sky-600 shrink-0" />
                        <div>
                          <div className="font-semibold text-slate-800">导出红线修订 Word (.docx)</div>
                          <div className="text-[10.5px] text-slate-400">原生修订批注，支持直接接受/拒绝</div>
                        </div>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleExport('docx_merged')}
                        className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-xs hover:bg-slate-50"
                      >
                        <FileText className="h-4 w-4 text-indigo-600 shrink-0" />
                        <div>
                          <div className="font-semibold text-slate-800">导出干净融合 Word (.docx)</div>
                          <div className="text-[10.5px] text-slate-400">应用全部回退与微调，含数据表</div>
                        </div>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleExport('html')}
                        className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-xs hover:bg-slate-50"
                      >
                        <Globe className="h-4 w-4 text-emerald-600 shrink-0" />
                        <div>
                          <div className="font-semibold text-slate-800">导出对比报告 (HTML)</div>
                          <div className="text-[10.5px] text-slate-400">离线打开，适合归档与打印 PDF</div>
                        </div>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleExport('latexdiff')}
                        className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-xs hover:bg-slate-50"
                      >
                        <FileCode2 className="h-4 w-4 text-violet-600 shrink-0" />
                        <div>
                          <div className="font-semibold text-slate-800">导出 latexdiff 源码</div>
                          <div className="text-[10.5px] text-slate-400">含 \DIFdel / \DIFadd 标记宏</div>
                        </div>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleExport('markdown')}
                        className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-xs hover:bg-slate-50"
                      >
                        <Download className="h-4 w-4 text-amber-600 shrink-0" />
                        <div>
                          <div className="font-semibold text-slate-800">导出修订摘要 (Markdown)</div>
                          <div className="text-[10.5px] text-slate-400">变动统计表与核查清单</div>
                        </div>
                      </button>
                    </div>
                  )}
                </div>
              )}

              {/* Settings Popover */}
              <div className="relative">
                <button
                  type="button"
                  onClick={() => {
                    setExportMenuOpen(false);
                    setDocMenuOpen(false);
                    setSettingsMenuOpen((v) => !v);
                  }}
                  title="排版设置与工具"
                  className={`rounded-xl border p-1.5 transition-colors ${
                    settingsMenuOpen
                      ? 'border-blue-300 bg-blue-50 text-blue-700'
                      : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  <Settings2 className="h-4 w-4" />
                </button>
                {settingsMenuOpen && (
                  <div className="absolute right-0 mt-2 w-80 max-h-[82vh] overflow-y-auto rounded-2xl border border-slate-200 bg-white p-3.5 shadow-xl z-40 space-y-3 text-xs">
                    <ThemeSegmentedControl value={theme} onChange={setTheme} />
                    <div className="border-t border-slate-100 pt-2.5 flex items-center justify-between">
                      <span className="font-medium text-slate-600">正文字体</span>
                      <div className="flex rounded-lg bg-slate-100 p-0.5">
                        <button
                          type="button"
                          onClick={() => setFontMode('serif')}
                          className={`rounded-md px-2.5 py-1 font-medium ${
                            fontMode === 'serif' ? 'bg-white text-slate-900 shadow-xs' : 'text-slate-500'
                          }`}
                        >
                          衬线
                        </button>
                        <button
                          type="button"
                          onClick={() => setFontMode('sans')}
                          className={`rounded-md px-2.5 py-1 font-medium ${
                            fontMode === 'sans' ? 'bg-white text-slate-900 shadow-xs' : 'text-slate-500'
                          }`}
                        >
                          无衬线
                        </button>
                      </div>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-slate-600">字号</span>
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => setFontSize((s) => Math.max(13.5, s - 1))}
                          className="rounded-md border border-slate-200 px-2 py-0.5 hover:bg-slate-50"
                        >
                          A-
                        </button>
                        <span className="w-10 text-center tabular-nums text-slate-500">{fontSize}</span>
                        <button
                          type="button"
                          onClick={() => setFontSize((s) => Math.min(18.5, s + 1))}
                          className="rounded-md border border-slate-200 px-2 py-0.5 hover:bg-slate-50"
                        >
                          A+
                        </button>
                      </div>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-slate-600">阅读页宽</span>
                      <div className="flex rounded-lg bg-slate-100 p-0.5">
                        <button
                          type="button"
                          onClick={() => setReadWidth('standard')}
                          className={`rounded-md px-2.5 py-1 font-medium ${
                            readWidth === 'standard'
                              ? 'bg-white text-slate-900 shadow-xs'
                              : 'text-slate-500'
                          }`}
                        >
                          标准
                        </button>
                        <button
                          type="button"
                          onClick={() => setReadWidth('wide')}
                          className={`rounded-md px-2.5 py-1 font-medium ${
                            readWidth === 'wide'
                              ? 'bg-white text-slate-900 shadow-xs'
                              : 'text-slate-500'
                          }`}
                        >
                          宽屏
                        </button>
                      </div>
                    </div>

                    {/* W1 Academic Typography Presets & Fine Controls (D-01 / D-02) */}
                    <div className="border-t border-slate-100 pt-2.5 space-y-2.5">
                      <div className="flex items-center justify-between">
                        <span className="font-medium text-slate-600">学术排版预设</span>
                        {typographyPrefs.typographyPreset === 'custom' && (
                          <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-semibold text-blue-700">
                            自定义
                          </span>
                        )}
                      </div>
                      <div className="grid grid-cols-3 gap-1">
                        {TYPOGRAPHY_PRESET_ITEMS.map((item) => {
                          const active = typographyPrefs.typographyPreset === item.id;
                          return (
                            <button
                              key={item.id}
                              type="button"
                              data-typo-preset={item.id}
                              title={item.desc}
                              onClick={() => setTypographyPrefs(applyTypographyPreset(item.id))}
                              className={`rounded-lg border px-2 py-1.5 text-[11px] font-medium transition-colors ${
                                active
                                  ? 'border-blue-500 bg-blue-50 text-blue-700 shadow-2xs'
                                  : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                              }`}
                            >
                              {item.label}
                            </button>
                          );
                        })}
                      </div>

                      <div className="flex items-center justify-between">
                        <span className="font-medium text-slate-600">首行缩进</span>
                        <div className="flex rounded-lg bg-slate-100 p-0.5">
                          {(
                            [
                              ['auto', '智能'],
                              ['source', '原稿'],
                              ['2em', '2字'],
                              ['none', '无'],
                            ] as [IndentMode, string][]
                          ).map(([mode, lbl]) => (
                            <button
                              key={mode}
                              type="button"
                              data-typo-indent={mode}
                              onClick={() =>
                                setTypographyPrefs((cur) => updateTypographyPref(cur, 'indentMode', mode))
                              }
                              className={`rounded-md px-2 py-0.5 text-[11px] font-medium ${
                                typographyPrefs.indentMode === mode
                                  ? 'bg-white text-slate-900 shadow-xs'
                                  : 'text-slate-500'
                              }`}
                            >
                              {lbl}
                            </button>
                          ))}
                        </div>
                      </div>

                      <div className="flex items-center justify-between">
                        <span className="font-medium text-slate-600">行距</span>
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            data-typo-lh="dec"
                            onClick={() =>
                              setTypographyPrefs((cur) =>
                                updateTypographyPref(
                                  cur,
                                  'lineHeight',
                                  Math.max(1.5, Math.round((cur.lineHeight - 0.06) * 100) / 100),
                                ),
                              )
                            }
                            className="rounded-md border border-slate-200 px-2 py-0.5 hover:bg-slate-50"
                          >
                            −
                          </button>
                          <span className="w-10 text-center tabular-nums text-slate-500">
                            {typographyPrefs.lineHeight.toFixed(2)}
                          </span>
                          <button
                            type="button"
                            data-typo-lh="inc"
                            onClick={() =>
                              setTypographyPrefs((cur) =>
                                updateTypographyPref(
                                  cur,
                                  'lineHeight',
                                  Math.min(2.3, Math.round((cur.lineHeight + 0.06) * 100) / 100),
                                ),
                              )
                            }
                            className="rounded-md border border-slate-200 px-2 py-0.5 hover:bg-slate-50"
                          >
                            +
                          </button>
                        </div>
                      </div>

                      <div className="flex items-center justify-between">
                        <span className="font-medium text-slate-600">段距</span>
                        <div className="flex rounded-lg bg-slate-100 p-0.5">
                          {(
                            [
                              ['compact', '紧凑'],
                              ['normal', '标准'],
                              ['relaxed', '宽松'],
                            ] as [ParagraphGap, string][]
                          ).map(([gap, lbl]) => (
                            <button
                              key={gap}
                              type="button"
                              data-typo-gap={gap}
                              onClick={() =>
                                setTypographyPrefs((cur) => updateTypographyPref(cur, 'paragraphGap', gap))
                              }
                              className={`rounded-md px-2 py-0.5 text-[11px] font-medium ${
                                typographyPrefs.paragraphGap === gap
                                  ? 'bg-white text-slate-900 shadow-xs'
                                  : 'text-slate-500'
                              }`}
                            >
                              {lbl}
                            </button>
                          ))}
                        </div>
                      </div>

                      <div className="flex items-center justify-between">
                        <span className="font-medium text-slate-600">正文对齐</span>
                        <div className="flex rounded-lg bg-slate-100 p-0.5">
                          {(
                            [
                              ['auto', '自动'],
                              ['justify', '两端'],
                              ['left', '左齐'],
                            ] as [TextAlignMode, string][]
                          ).map(([al, lbl]) => (
                            <button
                              key={al}
                              type="button"
                              data-typo-align={al}
                              onClick={() =>
                                setTypographyPrefs((cur) => updateTypographyPref(cur, 'textAlign', al))
                              }
                              className={`rounded-md px-2 py-0.5 text-[11px] font-medium ${
                                typographyPrefs.textAlign === al
                                  ? 'bg-white text-slate-900 shadow-xs'
                                  : 'text-slate-500'
                              }`}
                            >
                              {lbl}
                            </button>
                          ))}
                        </div>
                      </div>
                    </div>

                    <div className="border-t border-slate-100 pt-2.5 flex items-center justify-between">
                      <span className="font-medium text-slate-600">折叠未改段落</span>
                      <button
                        type="button"
                        onClick={() => setSmartFold((v) => !v)}
                        className={`relative h-5 w-9 rounded-full transition-colors ${
                          smartFold ? 'bg-blue-600' : 'bg-slate-300'
                        }`}
                      >
                        <span
                          className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${
                            smartFold ? 'left-[18px]' : 'left-0.5'
                          }`}
                        />
                      </button>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-slate-600">显示文档插图</span>
                      <button
                        type="button"
                        onClick={() => setShowFigures((v) => !v)}
                        className={`relative h-5 w-9 rounded-full transition-colors ${
                          showFigures ? 'bg-blue-600' : 'bg-slate-300'
                        }`}
                      >
                        <span
                          className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${
                            showFigures ? 'left-[18px]' : 'left-0.5'
                          }`}
                        />
                      </button>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-slate-600">阅读时标注 AI 表达</span>
                      <button
                        type="button"
                        onClick={() => setHighlightAiIsms((v) => !v)}
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
                    <div className="border-t border-slate-100 pt-2.5 space-y-1.5">
                      {!isQuickMode && activeProject && (
                        <button
                          type="button"
                          onClick={() => {
                            setSettingsMenuOpen(false);
                            setGlossaryProjectId(activeProject.id);
                          }}
                          className="flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-slate-700 hover:bg-slate-50"
                        >
                          <span className="inline-flex items-center gap-1.5 font-medium">
                            <ShieldCheck className="h-3.5 w-3.5 text-blue-600" />
                            受保护术语表
                          </span>
                          <span className="text-slate-400">{activeProject.protected_terms.length} 词</span>
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => {
                          setSettingsMenuOpen(false);
                          setLexiconOpen(true);
                        }}
                        className="flex w-full items-center gap-1.5 rounded-lg px-2 py-1.5 font-medium text-slate-700 hover:bg-slate-50"
                      >
                        <Sparkles className="h-3.5 w-3.5 text-emerald-600" />
                        AI 表达词典
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setSettingsMenuOpen(false);
                          setQuickOpen(true);
                        }}
                        className="flex w-full items-center gap-1.5 rounded-lg px-2 py-1.5 font-medium text-slate-700 hover:bg-slate-50"
                      >
                        <Zap className="h-3.5 w-3.5 text-blue-600" />
                        快速阅读 / 对比
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setSettingsMenuOpen(false);
                          setScreen('guide');
                        }}
                        className="flex w-full items-center gap-1.5 rounded-lg px-2 py-1.5 font-medium text-slate-700 hover:bg-slate-50"
                      >
                        <HelpCircle className="h-3.5 w-3.5 text-slate-500" />
                        使用指南
                      </button>
                    </div>
                  </div>
                )}
              </div>
              {runtimeControlNode}
            </div>
          </header>

          {/* Ultra-Slim Status & Filter Ribbon */}
          {isReadContext && singlePreview ? (
            <div className="z-10 flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-[#E6E8EE] bg-[#FAFBFC] px-5 py-1.5 text-xs">
              <div className="flex flex-wrap items-center gap-3 text-slate-500">
                <span>
                  篇幅 <strong className="text-slate-900 tabular-nums">{singlePreview.summary.word_count}</strong> 词
                </span>
                <span className="text-slate-200">|</span>
                <span className="tabular-nums">
                  {singlePreview.summary.paragraph_count} 段 · {singlePreview.summary.figure_count} 图 ·{' '}
                  {singlePreview.summary.table_count} 表 · {singlePreview.summary.math_count} 公式 ·{' '}
                  {singlePreview.summary.citation_count} 引文
                </span>
                <span className="text-slate-200">|</span>
                <button
                  type="button"
                  onClick={() => setAuditDrawerOpen(true)}
                  className="inline-flex items-center gap-1 hover:text-slate-900 transition-colors"
                >
                  <Sparkles className="h-3.5 w-3.5 text-violet-600" />
                  AI 词 <strong className="text-slate-800 tabular-nums">{singlePreview.summary.ai_ism_count}</strong>
                </button>
              </div>

              <div className="flex items-center gap-2">
                {viewMode !== 'source' && (
                  <div className="flex items-center rounded-lg border border-slate-200 bg-white p-0.5 text-[11px]">
                    <button
                      type="button"
                      onClick={() => setReadWidth('standard')}
                      title="弹性自适应 62% 屏宽（780–1140px，14寸笔记本与外接大屏自动伸缩）"
                      className={`rounded-md px-2 py-0.5 font-medium transition-colors ${
                        readWidth === 'standard'
                          ? 'bg-slate-900 text-white'
                          : 'text-slate-500 hover:text-slate-800'
                      }`}
                    >
                      标准弹性
                    </button>
                    <button
                      type="button"
                      onClick={() => setReadWidth('wide')}
                      title="宽屏展示 78% 屏宽（960–1520px，大屏全幅阅读）"
                      className={`rounded-md px-2 py-0.5 font-medium transition-colors ${
                        readWidth === 'wide'
                          ? 'bg-slate-900 text-white'
                          : 'text-slate-500 hover:text-slate-800'
                      }`}
                    >
                      宽屏
                    </button>
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => setHighlightAiIsms((v) => !v)}
                  className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-[11px] font-semibold transition-colors ${
                    highlightAiIsms
                      ? 'border-violet-300 bg-violet-50 text-violet-700'
                      : 'border-slate-200 bg-white text-slate-500 hover:text-slate-800'
                  }`}
                >
                  <Sparkles className="h-3 w-3" />
                  AI 腔标注{highlightAiIsms ? '：开' : '：关'}
                </button>
                <div className="relative">
                  <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
                  <input
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="筛选段落或词条..."
                    className="w-36 sm:w-44 rounded-lg border border-slate-200 bg-white pl-7 pr-2 py-1 text-[11.5px] focus:border-blue-400 focus:outline-none"
                  />
                </div>
              </div>
            </div>
          ) : (
            !isReadContext &&
            sum &&
            ev && (
              <div className="z-10 flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-[#E6E8EE] bg-[#FAFBFC] px-5 py-1.5 text-xs">
                <div className="flex flex-wrap items-center gap-3.5 text-slate-500">
                  <span>
                    整体相似 <strong className="text-slate-900 tabular-nums">{sum.overall_similarity}%</strong>
                    <span className="ml-1 text-[11px] text-slate-400">(改写 {sum.rewrite_ratio}%)</span>
                  </span>
                  <span className="text-slate-200">|</span>
                  <span>
                    篇幅{' '}
                    <span
                      className={`rounded px-1.5 py-0.5 font-semibold tabular-nums ${
                        sum.word_delta < 0
                          ? 'bg-[#E3EEFF] text-[#2563EB]'
                          : sum.word_delta > 0
                            ? 'bg-emerald-50 text-emerald-700'
                            : 'bg-slate-100 text-slate-600'
                      }`}
                    >
                      {sum.word_delta > 0 ? `+${sum.word_delta}` : sum.word_delta} 词
                    </span>
                    <span className="ml-1.5 text-[11px] text-slate-400 tabular-nums">
                      +{sum.added_words} / -{sum.deleted_words}
                    </span>
                  </span>
                  <span className="text-slate-200">|</span>
                  <button
                    type="button"
                    onClick={() => setAuditDrawerOpen(true)}
                    className="inline-flex items-center gap-1 hover:text-slate-900 transition-colors"
                  >
                    <Sparkles className="h-3.5 w-3.5 text-emerald-600" />
                    AI 词{' '}
                    <strong className="text-slate-800 tabular-nums">
                      {ev.ai_ism_diff.old_count} → {ev.ai_ism_diff.new_count}
                    </strong>
                  </button>
                </div>

                <div className="flex items-center gap-2">
                  <div className="flex items-center rounded-lg border border-slate-200 bg-white p-0.5 text-[11px]">
                    {(
                      [
                        ['all', '全部'],
                        ['changed', '仅改动'],
                        ['heavy', '大改<60%'],
                        ['alerts', '仅告警'],
                      ] as [FilterMode, string][]
                    ).map(([m, label]) => (
                      <button
                        key={m}
                        type="button"
                        onClick={() => setFilterMode(m)}
                        className={`rounded-md px-2 py-0.5 font-medium transition-colors ${
                          filterMode === m ? 'bg-slate-900 text-white' : 'text-slate-500 hover:text-slate-800'
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
                    <input
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="筛选段落..."
                      className="w-32 sm:w-40 rounded-lg border border-slate-200 bg-white pl-7 pr-2 py-1 text-[11.5px] focus:border-blue-400 focus:outline-none"
                    />
                  </div>
                </div>
              </div>
            )
          )}

          {/* Main Workspace Row: Optional Left Local File Tree + Paper Canvas */}
          <div className="relative flex flex-1 min-h-0 overflow-hidden">
            {isLocalProject && localSidebarOpen && activeProject && (
              <LocalFileTreeSidebar
                project={activeProject}
                tree={localTree}
                loading={localTreeLoading}
                error={localTreeError}
                includeAux={localIncludeAux}
                onToggleIncludeAux={(next) => {
                  setLocalIncludeAux(next);
                  if (activeProjectId) loadLocalTree(activeProjectId, next, false);
                }}
                activeRelPath={localActiveRelPath}
                selectedPair={localSelectedPair}
                pendingThirdRelPath={localPendingThird}
                onSelectFile={handleSelectLocalNode}
                onTogglePickForDiff={(relPath) => {
                  const res = togglePairSelection(localSelectedPair, relPath);
                  setLocalSelectedPair(res.nextPair);
                  setLocalPendingThird(res.pendingThirdRelPath);
                }}
                onReplacePairSlot={(slot, relPath) => {
                  setLocalSelectedPair((cur) => replacePairSlot(cur, slot, relPath));
                  setLocalPendingThird(null);
                }}
                onCancelPendingThird={() => setLocalPendingThird(null)}
                onClearPair={() => {
                  setLocalSelectedPair([]);
                  setLocalPendingThird(null);
                }}
                onStartPairCompare={() => {
                  if (activeProjectId && localSelectedPair.length === 2) {
                    runLocalPairCompare(activeProjectId, localSelectedPair[0], localSelectedPair[1]);
                  }
                }}
                onRefresh={() => syncLocalExternalChanges(true)}
                onOpenBindingSettings={() => setLocalBindingModalProj(activeProject)}
                onCloseSidebar={() => setLocalSidebarOpen(false)}
              />
            )}

            {/* Main Paper Canvas (Full-bleed White in Read Mode, Soft Gray in Compare Mode) */}
            <main
              ref={mainScrollRef}
              className={`relative flex-1 overflow-y-auto ${
                isReadContext && viewMode !== 'source' ? 'bg-white' : 'bg-[#F6F7F9]'
              }`}
            >
              {loading ? (
                <div className="flex h-64 items-center justify-center text-sm text-slate-400">
                  {isReadContext ? '正在解析学术排版与单稿体检...' : '正在执行学术解析与词级对比...'}
                </div>
              ) : isLocalProject && localAuxPreview && isReadContext ? (
                <div className="mx-auto max-w-4xl px-6 py-8 space-y-4">
                  <div className="flex items-center justify-between border-b border-slate-200 pb-3">
                    <span className="font-mono text-xs font-semibold text-slate-700">
                      辅助资源只读预览：{localAuxPreview.relPath}
                    </span>
                  </div>
                  {localAuxPreview.kind === 'image' && activeProjectId ? (
                    <div className="flex justify-center rounded-2xl border border-slate-200 bg-slate-50 p-6">
                      <img
                        src={`/api/projects/${activeProjectId}/local/raw?rel_path=${encodeURIComponent(localAuxPreview.relPath)}`}
                        alt={localAuxPreview.relPath}
                        className="max-h-[70vh] w-auto object-contain rounded-lg"
                      />
                    </div>
                  ) : (
                    <pre className="rounded-xl border border-slate-200 bg-slate-50 p-4 font-mono text-xs leading-relaxed text-slate-800 overflow-x-auto whitespace-pre-wrap">
                      {localAuxPreview.text}
                    </pre>
                  )}
                </div>
              ) : isLocalProject && localFileError && isReadContext ? (
                <div className="flex h-full flex-col items-center justify-center p-8 text-center">
                  <div
                    data-local-file-error="true"
                    className="max-w-md rounded-2xl border border-rose-200 bg-rose-50/60 p-6 space-y-3"
                  >
                    <h2 className="text-sm font-bold text-rose-800">无法打开该本地文件</h2>
                    <p className="text-xs text-rose-700 leading-relaxed">{localFileError}</p>
                    <p className="text-[11px] text-slate-500">
                      请在左侧文件树选择其他正常文稿，或点击刷新重试。
                    </p>
                  </div>
                </div>
              ) : isReadContext && singlePreview ? (
                <SingleDocWorkspace
                  preview={singlePreview}
                  showSource={viewMode === 'source'}
                  fontMode={fontMode}
                  fontSize={fontSize}
                  readWidth={readWidth}
                  typographyPrefs={typographyPrefs}
                  showFigures={showFigures}
                  highlightAiIsms={highlightAiIsms}
                  searchQuery={searchQuery}
                  paragraphEdits={singleEdits}
                  pendingPatches={singlePatches}
                  highlightedBlock={highlightedPara}
                  canSaveVersion={
                    isLocalProject
                      ? Boolean(activeProjectId && localActiveRelPath)
                      : !isQuickMode && Boolean(activeDocumentId)
                  }
                  localProjectId={isLocalProject ? activeProjectId : null}
                  externalUpdateNotice={isLocalProject && localExternalNotice}
                  onReloadExternal={() => {
                    if (activeProjectId && localActiveRelPath) {
                      openLocalFileForRead(activeProjectId, localActiveRelPath);
                    }
                  }}
                  onDismissExternalNotice={() => setLocalExternalNotice(false)}
                  onSplitTrackedDocx={
                    isLocalProject && activeProjectId && singlePreview.local_rel_path
                      ? () => runLocalTrackedSplit(activeProjectId, singlePreview.local_rel_path!)
                      : undefined
                  }
                  scrollContainerRef={mainScrollRef}
                  onSaveBlockEdit={handleSaveSingleEdit}
                  onAddPatch={(op) => setSinglePatches((prev) => [...prev, op])}
                  onRemovePatchAt={(idx) =>
                    setSinglePatches((prev) => prev.filter((_, i) => i !== idx))
                  }
                  onOpenSaveModal={() => {
                    if (isLocalProject) {
                      setSaveLocalModalOpen(true);
                    } else {
                      setSaveMergedOpen(true);
                    }
                  }}
                  onResetEdits={() => {
                    setSingleEdits({});
                    setSinglePatches([]);
                    showToast('已撤销全部阅读态修订');
                  }}
                  onCopySource={handleCopySingleSource}
                  onJumpToBlock={(idx) => handleJumpToParagraph(idx)}
                />
              ) : !isReadContext && comparison ? (
                <DiffWorkspace
                  comparison={comparison}
                  viewMode={viewMode}
                  filterMode={filterMode}
                  fontMode={fontMode}
                  fontSize={fontSize}
                  smartFold={smartFold}
                  showFigures={showFigures}
                  searchQuery={searchQuery}
                  decisions={decisions}
                  paragraphEdits={paragraphEdits}
                  expandedAlerts={expandedAlerts}
                  onToggleParaAlerts={(idx) =>
                    setExpandedAlerts((prev) => ({ ...prev, [idx]: !prev[idx] }))
                  }
                  onToggleAlertAck={handleToggleAlertAck}
                  onSetHunkDecision={handleSetHunkDecision}
                  onSetParagraphDecision={handleSetParagraphDecision}
                  onSaveParagraphEdit={handleSaveParagraphEdit}
                  highlightedPara={highlightedPara}
                  onJumpToParagraph={(idx) => handleJumpToParagraph(idx)}
                />
              ) : isLocalProject ? (
                <div className="flex h-full flex-col items-center justify-center p-8 text-center">
                  <div className="max-w-md rounded-2xl border border-dashed border-slate-300 bg-white p-8 space-y-3">
                    <h2 className="text-base font-bold text-slate-800">
                      {localTreeError ? '绑定的本地文件夹不可用' : '从左侧文件树选择文稿开始阅读或对比'}
                    </h2>
                    <p className="text-xs leading-relaxed text-slate-500">
                      {localTreeError
                        ? localTreeError.message
                        : '单击左侧目录树任意 .tex / .docx / .md / .zip 免上传直读；勾选其中任意 2 个文件即可一键两两对比。'}
                    </p>
                    <div className="flex justify-center gap-2 pt-2">
                      {localTreeError && activeProject && (
                        <button
                          type="button"
                          onClick={() => setLocalBindingModalProj(activeProject)}
                          className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700"
                        >
                          重新定位目录 / 解绑
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => setScreen('home')}
                        className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                      >
                        返回项目工作台
                      </button>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="flex h-full flex-col items-center justify-center p-8 text-center">
                  <div className="max-w-md rounded-2xl border border-dashed border-slate-300 bg-white p-8">
                    <h2 className="text-base font-bold text-slate-800">
                      向「{activeDocument?.name || '当前文档'}」导入文稿版本
                    </h2>
                    <p className="mt-2 text-xs leading-relaxed text-slate-500">
                      拖拽或上传 .tex、Overleaf .zip、Word .docx、Markdown：导入第 1 版即刻进入纯净阅读预览与单稿体检，导入第 2 版自动展开词级对比。
                    </p>
                    <div className="mt-5 flex justify-center gap-2">
                      {activeProjectId && activeDocumentId && (
                        <button
                          type="button"
                          onClick={() => openUploadForDoc(activeProjectId, activeDocumentId)}
                          className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700"
                        >
                          导入第一版文稿
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => setScreen('home')}
                        className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                      >
                        返回项目工作台
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </main>
          </div>

          {isReadContext && singlePreview ? (
            <FloatingOutline
              readSections={singlePreview.sections}
              hideOnXl={true}
              onJumpToParagraph={(idx) => handleJumpToParagraph(idx)}
            />
          ) : (
            !isReadContext &&
            comparison && (
              <FloatingOutline
                sections={comparison.sections}
                onJumpToParagraph={(idx) => handleJumpToParagraph(idx)}
              />
            )
          )}

          {!isReadContext && comparison && (
            <FloatingStepper
              changedCount={changedParaIndices.length}
              currentChangeIdx={changeCursor}
              alertParaCount={alertParaIndices.length}
              currentAlertIdx={alertCursor}
              revertedCount={revertedCount}
              editedParaCount={editedParaCount}
              canSaveVersion={!isQuickMode && Boolean(activeDocumentId)}
              onStepChange={stepChange}
              onStepAlert={stepAlert}
              onExportMerged={() => handleExport('merged')}
              onSaveAsNewVersion={() => setSaveMergedOpen(true)}
              onResetDecisions={() => {
                persistDecisions({});
                setParagraphEdits({});
                showToast('已重置全部回退与微调');
              }}
            />
          )}

          {/* Left 3-Level Hierarchy Drawer (⌘1) */}
          <ProjectDrawer
            open={projectDrawerOpen}
            onClose={() => setProjectDrawerOpen(false)}
            projects={projects}
            activeProjectId={activeProjectId}
            activeDocumentId={activeDocumentId}
            versions={versions}
            oldVersionId={oldVersionId}
            newVersionId={newVersionId}
            readVersionId={readVersionId}
            isReadMode={isReadContext}
            isQuickMode={isQuickMode}
            onGoHome={() => setScreen('home')}
            onSelectDocument={(pid, did) => openDocumentInStudio(pid, did)}
            onDeleteProject={async (id) => {
              if (!window.confirm('确定删除该项目及所有文档版本吗？')) return;
              await api.deleteProject(id);
              await loadProjects();
              showToast('已删除项目');
            }}
            onDeleteDocument={async (pid, did) => {
              if (!window.confirm('确定删除该文档及全部版本吗？')) return;
              await api.deleteDocument(did);
              await loadProjects(pid);
              showToast('已删除文档');
            }}
            onOpenNewProject={() => setNewProjOpen(true)}
            onOpenNewDocument={(pid) => setNewDocProjectId(pid)}
            onOpenUploadVersion={() => {
              if (activeProjectId && activeDocumentId) {
                openUploadForDoc(activeProjectId, activeDocumentId);
              }
            }}
            onOpenQuickCompare={() => setQuickOpen(true)}
            onOpenGuide={() => setScreen('guide')}
            onSelectVersionPair={(oid, nid) => {
              setIsQuickMode(false);
              setOldVersionId(oid);
              setNewVersionId(nid);
              setViewMode('split');
              setLastNonSourceMode('split');
            }}
            onReadVersion={(vid) => {
              setIsQuickMode(false);
              setReadVersionId(vid);
              setSingleEdits({});
              setSinglePatches([]);
              setViewMode('read');
              setLastNonSourceMode('read');
            }}
            onToggleMilestone={async (v) => {
              await api.updateVersion(v.id, { is_milestone: !v.is_milestone });
              if (activeDocumentId) {
                await loadProjects(activeProjectId || undefined, activeDocumentId);
                await loadVersionsForDocument(activeDocumentId);
              }
              showToast(v.is_milestone ? '已取消里程碑标记' : '已设为星标里程碑 ★');
            }}
            onEditVersion={(v) => setEditingVersion(v)}
            onDeleteVersion={async (vid) => {
              if (!window.confirm('确定删除该历史版本吗？')) return;
              await api.deleteVersion(vid);
              if (activeDocumentId) {
                await loadProjects(activeProjectId || undefined, activeDocumentId);
                await loadVersionsForDocument(activeDocumentId);
              }
              showToast('已删除版本');
            }}
          />

          {/* Right Audit Drawer (⌘2): Single-Doc Self-Audit in Read Mode / Compare Evaluation in Compare Mode */}
          {isReadContext && singlePreview ? (
            <SingleAuditDrawer
              open={auditDrawerOpen}
              onClose={() => setAuditDrawerOpen(false)}
              preview={singlePreview}
              highlightAiIsms={highlightAiIsms}
              onToggleHighlightAiIsms={() => setHighlightAiIsms((v) => !v)}
              onJumpToBlock={(idx) => handleJumpToParagraph(idx)}
              onFilterWord={(word) => setSearchQuery(word)}
              onOpenLexicon={() => setLexiconOpen(true)}
            />
          ) : (
            !isReadContext &&
            comparison && (
              <EvaluationDrawer
                open={auditDrawerOpen}
                onClose={() => setAuditDrawerOpen(false)}
                comparison={comparison}
                versions={isQuickMode ? [] : versions}
                onJumpToAlertParagraph={(idx) => handleJumpToParagraph(idx, true)}
                onToggleAlertAck={handleToggleAlertAck}
              />
            )
          )}

          {/* Global Drag-and-Drop Overlay */}
          {dragActive && (
            <div className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center bg-blue-600/10 backdrop-blur-[2px]">
              <div className="flex flex-col items-center rounded-3xl border-2 border-dashed border-blue-500 bg-white/95 px-12 py-10 shadow-2xl">
                <FileUp className="h-10 w-10 text-blue-600 mb-3" />
                <div className="text-base font-bold text-slate-900">
                  松开导入到「{activeDocument?.name || '当前文档'}」
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  支持 .tex / Overleaf .zip / Word .docx / .md，将自动与上一版对比
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Shared Modals (Accessible from BOTH Home & Studio!) */}
      <NewProjectModal
        open={newProjOpen}
        onClose={() => setNewProjOpen(false)}
        onOpenGuide={() => {
          setNewProjOpen(false);
          setScreen('guide');
        }}
        onCreated={async (pid, defaultDocId, mode) => {
          await loadProjects(pid, defaultDocId);
          if (mode === 'local_folder') {
            await openLocalProjectInStudio(pid);
            showToast('本地文件夹项目已绑定，可直接浏览和两两对比');
          } else {
            if (defaultDocId) {
              openDocumentInStudio(pid, defaultDocId);
            }
            showToast('科研项目已创建（已自动建立默认主文稿）');
          }
        }}
      />

      <LocalBindingModal
        project={localBindingModalProj}
        onClose={() => setLocalBindingModalProj(null)}
        onRelocated={async (updated) => {
          await loadProjects(updated.id);
          if (screen === 'studio' && activeProjectId === updated.id) {
            await loadLocalTree(updated.id, localIncludeAux, false);
          }
          showToast('已更新本地目录绑定路径（磁盘原文件未改动）');
        }}
        onUnbound={async (updated) => {
          await loadProjects(updated.id);
          if (screen === 'studio' && activeProjectId === updated.id) {
            setScreen('home');
          }
          showToast('已解除本地目录绑定（磁盘原文件完好无损）');
        }}
        onDeleted={async (deletedId) => {
          await loadProjects();
          if (screen === 'studio' && activeProjectId === deletedId) {
            setScreen('home');
          }
          showToast('已移除项目记录（磁盘原文件完好无损）');
        }}
      />

      {isLocalProject && activeProjectId && localActiveRelPath && (
        <SaveLocalEditsModal
          open={saveLocalModalOpen}
          projectId={activeProjectId}
          relPath={localActiveRelPath}
          expectedSha256={singlePreview?.file_sha256}
          patches={buildCombinedSinglePatches()}
          paragraphEdits={singleEdits}
          onClose={() => setSaveLocalModalOpen(false)}
          onSaved={async (res) => {
            setSingleEdits({});
            setSinglePatches([]);
            await loadLocalTree(activeProjectId, localIncludeAux, false);
            await openLocalFileForRead(activeProjectId, res.target_rel_path);
            showToast(
              res.backup_rel_path
                ? `已覆盖 ${res.target_rel_path}（原稿已备份至 ${res.backup_rel_path}）`
                : `已另存为 ${res.target_rel_path}（原文件未改动）`,
            );
          }}
        />
      )}

      {isLocalProject && activeProjectId && localActiveRelPath && (
        <ExternalConflictModal
          open={localConflictOpen}
          relPath={localActiveRelPath}
          pendingEditCount={Object.keys(singleEdits).length + singlePatches.length}
          onKeepDrafts={() => {
            setLocalConflictOpen(false);
            showToast('已保留您的暂存微调（保存时建议选择「另存为新文件」）');
          }}
          onDiscardAndReload={async () => {
            setLocalConflictOpen(false);
            await openLocalFileForRead(activeProjectId, localActiveRelPath);
            showToast('已重载磁盘最新版本');
          }}
        />
      )}

      {newDocProject && (
        <NewDocumentModal
          open={newDocProjectId !== null}
          projectId={newDocProject.id}
          projectName={newDocProject.name}
          onClose={() => setNewDocProjectId(null)}
          onCreated={async (docId) => {
            await loadProjects(newDocProject.id, docId);
            openDocumentInStudio(newDocProject.id, docId);
            showToast('文档已添加到项目中');
          }}
        />
      )}

      {uploadTarget && (
        <UploadVersionModal
          open={true}
          documentId={uploadTarget.docId}
          documentName={uploadTarget.docName}
          nextVersionNum={uploadTarget.nextVer}
          preloadedFile={droppedFile}
          onClose={() => {
            setUploadTarget(null);
            setDroppedFile(null);
          }}
          onUploaded={async (newVid) => {
            const targetDocId = uploadTarget.docId;
            setUploadTarget(null);
            setDroppedFile(null);
            setIsQuickMode(false);
            const list = await loadProjects(undefined, targetDocId);
            const ownerProj = list.find((p) => p.documents.some((d) => d.id === targetDocId));
            let count = 2;
            if (ownerProj) {
              setActiveProjectId(ownerProj.id);
              setActiveDocumentId(targetDocId);
              setScreen('studio');
              count = await loadVersionsForDocument(targetDocId, newVid);
            }
            showToast(count === 1 ? '第一版已入库，已进入阅读预览' : '新版本已入库并自动完成对比');
          }}
        />
      )}

      <SaveMergedVersionModal
        open={saveMergedOpen}
        mode={isReadContext ? 'read' : 'compare'}
        nextVersionNum={versions.length + 1}
        revertedCount={isReadContext ? 0 : revertedCount}
        editedParaCount={isReadContext ? singleEditedCount : editedParaCount}
        onClose={() => setSaveMergedOpen(false)}
        onConfirm={handleSaveMergedAsNewVersion}
      />

      <PdfExportModal
        open={pdfExportOpen}
        mode={isReadContext ? 'read' : 'compare'}
        onClose={() => setPdfExportOpen(false)}
        onExportPdf={handleExportPdf}
      />

      <EditVersionModal
        version={editingVersion}
        onClose={() => setEditingVersion(null)}
        onSaved={async () => {
          if (activeDocumentId) {
            await loadProjects(activeProjectId || undefined, activeDocumentId);
            await loadVersionsForDocument(activeDocumentId);
          }
          showToast('版本信息已更新');
        }}
      />

      <QuickCompareModal
        open={quickOpen}
        initialOld={quickRaw?.oldText || quickSingleRaw?.content}
        initialNew={quickRaw?.newText}
        initialOldLabel={quickRaw?.oldLabel || quickSingleRaw?.label}
        initialOldMeta={quickRaw?.oldMeta || quickSingleRaw?.meta}
        onClose={() => setQuickOpen(false)}
        onCompare={handleQuickCompare}
        onPreviewSingle={(content, label, meta) => handleQuickPreview(content, label, meta, false)}
      />

      {glossaryProject && (
        <GlossaryModal
          open={glossaryProjectId !== null}
          projectName={glossaryProject.name}
          terms={glossaryProject.protected_terms}
          onClose={() => setGlossaryProjectId(null)}
          onSave={async (terms) => {
            await api.updateProject(glossaryProject.id, { protected_terms: terms });
            await loadProjects(glossaryProject.id, activeDocumentId);
            if (screen === 'studio' && isReadContext && readVersionId) {
              await runSinglePreview(readVersionId);
            } else if (screen === 'studio' && activeDocumentId && oldVersionId && newVersionId) {
              await runDocumentCompare(activeDocumentId, oldVersionId, newVersionId);
            }
            showToast('项目受保护术语表已更新并重新审计');
          }}
        />
      )}

      <AiLexiconModal
        open={lexiconOpen}
        onClose={() => setLexiconOpen(false)}
        onSaved={async () => {
          if (screen === 'studio' && isReadContext && !isQuickMode && readVersionId) {
            await runSinglePreview(readVersionId);
          } else if (screen === 'studio' && isReadContext && isQuickMode && quickSingleRaw) {
            await handleQuickPreview(
              quickSingleRaw.content,
              quickSingleRaw.label,
              quickSingleRaw.meta,
              Boolean(quickRaw),
            );
          } else if (screen === 'studio' && activeDocumentId && oldVersionId && newVersionId) {
            await runDocumentCompare(activeDocumentId, oldVersionId, newVersionId);
          } else if (isQuickMode && quickRaw) {
            await handleQuickCompare(
              quickRaw.oldText,
              quickRaw.newText,
              quickRaw.oldLabel,
              quickRaw.newLabel,
              quickRaw.oldMeta,
              quickRaw.newMeta,
            );
          }
          showToast('AI 套话词典已更新并重新审计');
        }}
      />

      {toast && (
        <div className="fixed top-16 left-1/2 z-50 -translate-x-1/2 rounded-full bg-slate-900/95 px-4 py-1.5 text-xs font-medium text-white shadow-lg">
          {toast}
        </div>
      )}
    </>
  );
}
