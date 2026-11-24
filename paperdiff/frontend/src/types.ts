/**
 * @file types.ts
 * @description Canonical TypeScript data contracts mirroring the FastAPI v1.1.0 backend responses,
 * unified Academic IR (`SingleDocBlock`, `DisplayItem`), `TypedPatchOp` round-trip patch protocol,
 * comparison/audit payloads, and `ThemePreference` state.
 */

export type ProjectCategory = 'paper' | 'grant' | 'report' | 'other';
export type ProjectStatus = 'drafting' | 'polishing' | 'revising' | 'done' | 'archived';
export type ProjectMode = 'managed' | 'local_folder';
export type DocType = 'manuscript' | 'si' | 'rebuttal' | 'proposal' | 'report' | 'other';

export interface LatestVersionBrief {
  id: number;
  version_number: number;
  label: string;
  source_tag: string;
  word_count: number;
  ai_ism_count: number;
  is_milestone: number | boolean;
  created_at: string;
}

export interface DocumentSummary {
  id: number;
  project_id: number;
  name: string;
  doc_type: DocType;
  primary_format: string;
  notes: string;
  sort_order: number;
  version_count: number;
  milestone_count: number;
  last_version_at: string | null;
  latest_version: LatestVersionBrief | null;
  created_at: string;
  updated_at: string;
}

export interface Project {
  id: number;
  name: string;
  description: string;
  category: ProjectCategory;
  status: ProjectStatus;
  pinned: boolean;
  primary_format: string;
  protected_terms: string[];
  project_mode?: ProjectMode;
  local_root_path?: string | null;
  local_status?: 'ok' | 'missing' | 'unreadable' | 'unbound' | null;
  local_doc_count?: number;
  local_truncated?: boolean;
  local_error?: string;
  documents: DocumentSummary[];
  document_count: number;
  version_count: number;
  last_version_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface VersionSummary {
  id: number;
  project_id: number;
  document_id: number;
  version_number: number;
  label: string;
  source_tag: string;
  is_milestone: boolean;
  parent_version_id: number | null;
  filename: string;
  format: string;
  source_blob_key?: string | null;
  notes: string;
  word_count: number;
  para_count: number;
  ai_ism_count: number;
  created_at: string;
}

export type DocumentZone = 'frontmatter' | 'body' | 'backmatter';
export type BlockType =
  | 'title'
  | 'heading'
  | 'paragraph'
  | 'caption'
  | 'figure'
  | 'math'
  | 'table'
  | 'list'
  | 'blockquote'
  | 'code'
  | 'hr'
  | 'reference_item'
  | 'theorem'
  | 'algorithm';

export interface DisplayItem {
  kind: 'text' | 'ref' | 'cite' | 'math' | 'code' | 'link' | 'fn' | 'br' | 'sp';
  text: string;
  value?: string;
  bold?: boolean;
  italic?: boolean;
  strike?: boolean;
}

export interface BlockStyle {
  first_line_indent_em?: number;
  hanging_indent_em?: number;
  left_indent_em?: number;
  right_indent_em?: number;
  align?: 'left' | 'center' | 'right' | 'justify';
  explicit_indent?: 'indent' | 'none';
  quote_depth?: number;
  parent_list_depth?: number;
  list_depth?: number;
  semantic_role?: 'abstract' | 'footnote';
}

export type DocLanguage = 'zh' | 'en' | 'mixed';

export interface WordCommentItem {
  id: string;
  author: string;
  date: string;
  text: string;
}

export interface TheoremMeta {
  theorem_env: string;
  theorem_title: string;
  theorem_num?: number | null;
  optional_title?: string;
  label?: string;
  is_proof?: boolean;
}

export interface AlgorithmLine {
  indent: number;
  text: string;
  items?: DisplayItem[];
}

export interface AlgorithmMeta {
  alg_num?: number | null;
  caption?: string;
  label?: string;
  lines: AlgorithmLine[];
}

export interface SubfigureItem {
  image_path: string;
  asset_key: string | null;
  subcaption?: string;
  label?: string;
}

export type TypedPatchOp =
  | {
      op: 'replace_block';
      block_index: number;
      new_raw: string;
      summary?: string;
    }
  | {
      op: 'replace_math';
      block_index: number;
      new_raw: string;
      summary?: string;
    }
  | {
      op: 'edit_table_cell';
      block_index: number;
      row: number;
      col: number;
      old_value?: string;
      new_value: string;
      bold?: boolean;
      summary?: string;
    }
  | {
      op: 'insert_table_row';
      block_index: number;
      after_row: number;
      cells: string[];
      summary?: string;
    }
  | {
      op: 'delete_table_row';
      block_index: number;
      row: number;
      summary?: string;
    };

export type CitationStyle = 'gbt7714' | 'nature' | 'ieee' | 'apa';

export interface TrackedChangesInfo {
  has_tracked_changes: boolean;
  ins_count: number;
  del_count: number;
  authors: string[];
  summary: string;
}

export interface DiffSegment {
  type: 'equal' | 'replace' | 'delete' | 'insert';
  hunk_id?: string;
  items?: DisplayItem[];
  old_items?: DisplayItem[];
  new_items?: DisplayItem[];
  raw?: string;
  old_raw?: string;
  new_raw?: string;
  lead_space_old?: boolean;
  lead_space_new?: boolean;
}

export interface AuditAlert {
  alert_id: string;
  acked?: boolean;
  para_index: number;
  section: string;
  category: 'citation' | 'reference' | 'number' | 'math' | 'terminology' | 'claim_drift';
  severity: 'high' | 'medium' | 'info';
  title: string;
  detail: string;
  items: string[];
}

export interface NumericDelta {
  old_num: number;
  new_num: number;
  delta: number;
  pct: number | null;
}

export interface TableDiffCell {
  status: 'unchanged' | 'modified' | 'added' | 'deleted';
  old: string;
  new: string;
  items?: DisplayItem[];
  colspan?: number;
  rowspan?: number;
  old_bold?: boolean;
  new_bold?: boolean;
  bold_changed?: boolean;
  numeric_delta?: NumericDelta | null;
  segments: DiffSegment[];
}

export interface TablePlainCell {
  text: string;
  items?: DisplayItem[];
  colspan: number;
  rowspan: number;
  bold: boolean;
}

export interface TableDiffRow {
  status: 'unchanged' | 'modified' | 'added' | 'deleted';
  cells: TableDiffCell[];
}

export interface TableDiffData {
  rows: TableDiffRow[];
  old_rows?: TablePlainCell[][];
  new_rows?: TablePlainCell[][];
  changed_cells: number;
  bold_changed_cells?: number;
  total_cells: number;
}

export interface FigureInfo {
  old_asset: string | null;
  new_asset: string | null;
  old_path: string;
  new_path: string;
  label: string;
  image_status: 'unchanged' | 'updated' | 'added' | 'deleted' | 'no_preview';
}

export interface BibEntry {
  type?: string;
  title?: string;
  author?: string;
  year?: string;
  venue?: string;
}

export interface ListMeta {
  ordered: boolean;
  item_num: number;
  depth?: number;
  checked?: boolean | null;
}

export interface RefMeta {
  ref_num?: number | null;
  bib_key?: string;
  bib_entry?: BibEntry;
}

export interface AiLexiconConfig {
  defaults: {
    en_words: string[];
    en_phrases: string[];
    zh_words: string[];
  };
  added_en: string[];
  added_zh: string[];
  muted: string[];
}

export interface MathDiffPart {
  type: 'equal' | 'delete' | 'insert';
  text: string;
}

export interface ParagraphDiff {
  index: number;
  block_type: BlockType;
  zone?: DocumentZone;
  section_title: string;
  section_level: number;
  status: 'unchanged' | 'modified' | 'added' | 'deleted' | 'moved_from' | 'moved_to';
  old_raw: string;
  new_raw: string;
  old_clean: string;
  new_clean: string;
  heading_items?: DisplayItem[] | null;
  ai_isms_old: string[];
  ai_isms_new: string[];
  alerts: AuditAlert[];
  moved_peer_index?: number | null;
  moved_peer_section?: string | null;
  math_diff?: MathDiffPart[];
  table_diff?: TableDiffData | null;
  table_role?: 'data_table' | 'metadata_form' | null;
  table_alignments?: string[] | null;
  table_notes?: string[] | null;
  code_lang?: string | null;
  is_diagram?: boolean;
  callout_type?: 'note' | 'tip' | 'important' | 'warning' | 'caution' | null;
  theorem_meta?: TheoremMeta | null;
  algorithm_meta?: AlgorithmMeta | null;
  comments?: WordCommentItem[];
  ref_meta?: RefMeta | null;
  figure_info?: FigureInfo | null;
  list_meta?: ListMeta | null;
  quote_depth?: number | null;
  eq_number?: number | null;
  source_anchor?: Record<string, unknown> | null;
  segments: DiffSegment[];
  hunk_count: number;
  old_word_count: number;
  new_word_count: number;
  word_delta: number;
  added_words: number;
  deleted_words: number;
  similarity: number;
  similarity_int: number;
  jaccard_similarity: number;
  bigram_similarity: number;
}

export interface SectionSummary {
  title: string;
  level: number;
  first_para_index: number;
  para_count: number;
  changed_para_count: number;
  old_words: number;
  new_words: number;
  word_delta: number;
  similarity: number;
  change_intensity: number;
  alert_count: number;
}

export interface StyleMetrics {
  word_count: number;
  sentence_count: number;
  avg_sentence_len: number;
  long_sentence_ratio: number;
  flesch_kincaid_grade: number | null;
  flesch_reading_ease: number | null;
  lexical_diversity: number;
  passive_voice_ratio: number;
  ai_ism_count: number;
  ai_ism_density: number;
  ai_isms: string[];
  hedge_count: number;
  booster_count: number;
}

export interface ComparisonResult {
  mode: 'project' | 'quick' | 'local_folder';
  project?: Project;
  document?: DocumentSummary;
  old_version: Partial<VersionSummary> & { id: number; label: string };
  new_version: Partial<VersionSummary> & { id: number; label: string };
  local_old_rel_path?: string;
  local_new_rel_path?: string;
  old_sha256?: string;
  new_sha256?: string;
  decisions: Record<string, 'accept_new' | 'keep_old'>;
  acked_alert_ids?: string[];
  formats: { old: string; new: string };
  summary: {
    overall_similarity: number;
    rewrite_ratio: number;
    old_words: number;
    new_words: number;
    word_delta: number;
    added_words: number;
    deleted_words: number;
    total_paragraphs: number;
    modified_paragraphs: number;
    added_paragraphs: number;
    deleted_paragraphs: number;
    unchanged_paragraphs: number;
    alert_counts: {
      high: number;
      medium: number;
      info: number;
      total: number;
      acked?: number;
    };
  };
  evaluation: {
    overall_health: number;
    scores: {
      fact_safety: number;
      ai_naturalness: number;
      readability: number;
    };
    old_style: StyleMetrics;
    new_style: StyleMetrics;
    ai_ism_diff: {
      old_count: number;
      new_count: number;
      delta: number;
      removed: { word: string; count: number }[];
      added: { word: string; count: number }[];
    };
  };
  sections: SectionSummary[];
  alerts: AuditAlert[];
  bib_entries?: Record<string, BibEntry>;
  latex_macros?: Record<string, string>;
  footnotes?: Record<string, string>;
  paragraphs: ParagraphDiff[];
}

export interface SingleDocIssue {
  issue_id: string;
  block_index: number;
  section: string;
  category: 'citation' | 'reference' | 'ai_ism';
  severity: 'high' | 'medium' | 'info';
  title: string;
  detail: string;
  items: string[];
}

export interface SingleDocBlock {
  index: number;
  block_type: BlockType;
  zone?: DocumentZone;
  section_title: string;
  section_level: number;
  raw_text: string;
  clean_text: string;
  raw_start?: number | null;
  raw_end?: number | null;
  source_anchor?: Record<string, unknown> | null;
  label?: string;
  items: DisplayItem[];
  word_count: number;
  ai_isms: string[];
  table_rows?: TablePlainCell[][] | null;
  table_role?: 'data_table' | 'metadata_form' | null;
  table_alignments?: string[] | null;
  table_notes?: string[] | null;
  code_lang?: string | null;
  is_diagram?: boolean;
  callout_type?: 'note' | 'tip' | 'important' | 'warning' | 'caution' | null;
  theorem_meta?: TheoremMeta | null;
  algorithm_meta?: AlgorithmMeta | null;
  comments?: WordCommentItem[];
  ref_meta?: RefMeta | null;
  figure_info?: {
    asset_key: string | null;
    image_path: string;
    label: string;
    images?: SubfigureItem[];
  } | null;
  list_meta?: ListMeta | null;
  eq_number?: number | null;
  style?: BlockStyle | null;
  issues: SingleDocIssue[];
}

export interface SingleDocSection {
  title: string;
  level: number;
  first_block_index: number;
  block_count: number;
  word_count: number;
  ai_ism_count: number;
  issue_count: number;
}

export interface SingleDocPreview {
  mode: 'project' | 'quick' | 'local_folder';
  project?: Project;
  document?: DocumentSummary;
  version: Partial<VersionSummary> & { id: number; label: string };
  format: string;
  doc_language?: DocLanguage;
  cjk_ratio?: number;
  local_rel_path?: string;
  file_sha256?: string;
  mtime_ms?: number;
  tracked_changes_info?: TrackedChangesInfo | null;
  encoding_warning?: string | null;
  raw_content: string;
  health_score: number;
  summary: {
    word_count: number;
    paragraph_count: number;
    heading_count: number;
    figure_count: number;
    table_count: number;
    math_count: number;
    list_count: number;
    citation_count: number;
    citation_total: number;
    reference_count: number;
    ai_ism_count: number;
    issue_counts: {
      high: number;
      medium: number;
      info: number;
      total: number;
    };
  };
  style: StyleMetrics;
  ai_ism_breakdown: { word: string; count: number }[];
  term_coverage: { term: string; count: number }[];
  sections: SingleDocSection[];
  issues: SingleDocIssue[];
  bib_entries?: Record<string, BibEntry>;
  latex_macros?: Record<string, string>;
  footnotes?: Record<string, string>;
  footnote_items?: Record<string, DisplayItem[]>;
  label_map?: Record<string, string>;
  blocks: SingleDocBlock[];
}

export type AppScreen = 'home' | 'studio' | 'guide';
export type ViewMode = 'read' | 'split' | 'inline' | 'source';
export type ReadWidthMode = 'standard' | 'wide';
export type ThemePreference = 'light' | 'sepia' | 'dark' | 'auto';
export type FilterMode = 'all' | 'changed' | 'heavy' | 'alerts';
export type FontMode = 'serif' | 'sans';
export type TypographyPreset = 'auto' | 'source' | 'zh_thesis' | 'en_journal' | 'modern_note' | 'custom';
export type IndentMode = 'auto' | 'source' | '2em' | 'none';
export type ParagraphGap = 'compact' | 'normal' | 'relaxed';
export type TextAlignMode = 'auto' | 'justify' | 'left';

export interface TypographyPrefs {
  typographyPreset: TypographyPreset;
  indentMode: IndentMode;
  lineHeight: number;
  paragraphGap: ParagraphGap;
  textAlign: TextAlignMode;
}

export type LocalFormatFilter = 'all' | 'latex' | 'docx' | 'markdown';

export interface LocalTreeNode {
  name: string;
  rel_path: string;
  node_type: 'dir' | 'file';
  kind?: 'doc' | 'aux';
  format?: string;
  ext?: string;
  size_bytes?: number;
  mtime_ms?: number;
  children?: LocalTreeNode[];
}

export interface LocalTreeResponse {
  root_path: string;
  nodes: LocalTreeNode[];
  doc_count: number;
  aux_count: number;
  scanned_entries: number;
  truncated: boolean;
  truncated_reason: string | null;
  max_depth: number;
  max_entries: number;
}

export interface LocalFolderValidation {
  valid: boolean;
  resolved_path?: string;
  doc_count?: number;
  truncated?: boolean;
  truncated_reason?: string | null;
  error_code?: string;
  detail?: string;
}

export interface LocalStatItem {
  exists: boolean;
  mtime_ms: number | null;
  size_bytes: number | null;
  sha256: string | null;
}

export interface LocalStatResponse {
  root_status: string;
  root_path: string;
  files: Record<string, LocalStatItem>;
}

export interface LocalSaveEditsResult {
  saved: boolean;
  mode: 'save_as' | 'overwrite';
  target_rel_path: string;
  backup_rel_path: string | null;
  new_sha256: string;
  new_mtime_ms: number;
  warnings: string[];
}
