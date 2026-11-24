"""SQLite Persistence Layer & Idempotent Schema v1.1 Migrations for PaperDiff Studio.

Data directory resolution order (`_resolve_data_dir`):
    1. Explicit `PAPERDIFF_DATA_DIR` environment variable (used by tests & custom setups).
    2. `~/Library/Application Support/PaperDiff` when running as a PyInstaller frozen `.app`
       so read-only mounted `.dmg` images remain 100% writable and sandbox-friendly.
    3. Local `paperdiff/data/` directory during source development (excluded via `.gitignore`).

Schema hierarchy:
    `projects` 1--N `documents` 1--N `versions` (with v1.1 `source_blob_key` column)
    plus `merge_decisions`, `alert_acks`, and `app_settings`.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator


def _resolve_data_dir() -> Path:
    from .runtime_state import resolve_data_dir

    return resolve_data_dir()


DATA_DIR = _resolve_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "paperdiff.db"


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(r["name"]) for r in rows}


def init_db() -> None:
    """Create schema and execute idempotent zero-data-loss migrations (v1.1 -> v1.2)."""
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'paper',
                status TEXT NOT NULL DEFAULT 'polishing',
                pinned INTEGER NOT NULL DEFAULT 0,
                primary_format TEXT NOT NULL DEFAULT 'latex',
                protected_terms TEXT NOT NULL DEFAULT '[]',
                project_mode TEXT NOT NULL DEFAULT 'managed',
                local_root_path TEXT DEFAULT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL DEFAULT '主文稿',
                doc_type TEXT NOT NULL DEFAULT 'manuscript',
                primary_format TEXT NOT NULL DEFAULT 'latex',
                notes TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                document_id INTEGER,
                version_number INTEGER NOT NULL,
                label TEXT NOT NULL,
                source_tag TEXT NOT NULL DEFAULT '手改',
                is_milestone INTEGER NOT NULL DEFAULT 0,
                parent_version_id INTEGER,
                filename TEXT NOT NULL DEFAULT 'manuscript.tex',
                format TEXT NOT NULL DEFAULT 'latex',
                content TEXT NOT NULL,
                meta_json TEXT NOT NULL DEFAULT '{}',
                notes TEXT NOT NULL DEFAULT '',
                word_count INTEGER NOT NULL DEFAULT 0,
                para_count INTEGER NOT NULL DEFAULT 0,
                ai_ism_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS merge_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                document_id INTEGER,
                old_version_id INTEGER NOT NULL,
                new_version_id INTEGER NOT NULL,
                decisions_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL,
                UNIQUE(project_id, old_version_id, new_version_id),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS alert_acks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                old_version_id INTEGER NOT NULL,
                new_version_id INTEGER NOT NULL,
                acked_json TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL,
                UNIQUE(document_id, old_version_id, new_version_id),
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS local_pair_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                old_rel_path TEXT NOT NULL,
                new_rel_path TEXT NOT NULL,
                acked_json TEXT NOT NULL DEFAULT '[]',
                decisions_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL,
                UNIQUE(project_id, old_rel_path, new_rel_path),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            """
        )

        # Idempotent v1.1 -> v1.3 migrations for existing databases
        p_cols = _table_columns(conn, "projects")
        if "category" not in p_cols:
            conn.execute("ALTER TABLE projects ADD COLUMN category TEXT NOT NULL DEFAULT 'paper'")
        if "status" not in p_cols:
            conn.execute("ALTER TABLE projects ADD COLUMN status TEXT NOT NULL DEFAULT 'polishing'")
        if "pinned" not in p_cols:
            conn.execute("ALTER TABLE projects ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
        if "project_mode" not in p_cols:
            conn.execute("ALTER TABLE projects ADD COLUMN project_mode TEXT NOT NULL DEFAULT 'managed'")
        if "local_root_path" not in p_cols:
            conn.execute("ALTER TABLE projects ADD COLUMN local_root_path TEXT DEFAULT NULL")

        v_cols = _table_columns(conn, "versions")
        if "document_id" not in v_cols:
            conn.execute("ALTER TABLE versions ADD COLUMN document_id INTEGER")
        if "is_milestone" not in v_cols:
            conn.execute("ALTER TABLE versions ADD COLUMN is_milestone INTEGER NOT NULL DEFAULT 0")
        if "parent_version_id" not in v_cols:
            conn.execute("ALTER TABLE versions ADD COLUMN parent_version_id INTEGER")
        if "meta_json" not in v_cols:
            conn.execute("ALTER TABLE versions ADD COLUMN meta_json TEXT NOT NULL DEFAULT '{}'")
        if "source_blob_key" not in v_cols:
            conn.execute("ALTER TABLE versions ADD COLUMN source_blob_key TEXT DEFAULT NULL")

        m_cols = _table_columns(conn, "merge_decisions")
        if "document_id" not in m_cols:
            conn.execute("ALTER TABLE merge_decisions ADD COLUMN document_id INTEGER")

        # Ensure every existing managed project has at least one document and attach orphan versions
        projs = conn.execute(
            "SELECT id, primary_format, created_at, updated_at FROM projects WHERE COALESCE(project_mode, 'managed') = 'managed'"
        ).fetchall()
        for p in projs:
            pid = int(p["id"])
            doc = conn.execute(
                "SELECT id FROM documents WHERE project_id = ? ORDER BY sort_order ASC, id ASC LIMIT 1",
                (pid,),
            ).fetchone()
            if not doc:
                cur = conn.execute(
                    """
                    INSERT INTO documents (project_id, name, doc_type, primary_format, notes, sort_order, created_at, updated_at)
                    VALUES (?, '主文稿', 'manuscript', ?, '', 0, ?, ?)
                    """,
                    (pid, p["primary_format"], p["created_at"], p["updated_at"]),
                )
                default_doc_id = int(cur.lastrowid)
            else:
                default_doc_id = int(doc["id"])

            conn.execute(
                "UPDATE versions SET document_id = ? WHERE project_id = ? AND document_id IS NULL",
                (default_doc_id, pid),
            )
            conn.execute(
                "UPDATE merge_decisions SET document_id = ? WHERE project_id = ? AND document_id IS NULL",
                (default_doc_id, pid),
            )


def _attach_documents_to_project(conn: sqlite3.Connection, project_dict: dict[str, Any]) -> dict[str, Any]:
    pid = int(project_dict["id"])
    doc_rows = conn.execute(
        """
        SELECT d.*,
               COUNT(v.id) AS version_count,
               SUM(CASE WHEN v.is_milestone = 1 THEN 1 ELSE 0 END) AS milestone_count,
               MAX(v.created_at) AS last_version_at
        FROM documents d
        LEFT JOIN versions v ON v.document_id = d.id
        WHERE d.project_id = ?
        GROUP BY d.id
        ORDER BY d.sort_order ASC, d.id ASC
        """,
        (pid,),
    ).fetchall()

    docs: list[dict[str, Any]] = []
    total_versions = 0
    for r in doc_rows:
        dd = dict(r)
        dd["version_count"] = int(dd["version_count"] or 0)
        dd["milestone_count"] = int(dd["milestone_count"] or 0)
        total_versions += dd["version_count"]
        latest = conn.execute(
            """
            SELECT id, version_number, label, source_tag, word_count, ai_ism_count, is_milestone, created_at
            FROM versions
            WHERE document_id = ?
            ORDER BY version_number DESC, id DESC
            LIMIT 1
            """,
            (dd["id"],),
        ).fetchone()
        dd["latest_version"] = dict(latest) if latest else None
        docs.append(dd)

    project_dict["documents"] = docs
    project_dict["document_count"] = len(docs)
    project_dict["version_count"] = total_versions
    project_dict["pinned"] = bool(project_dict.get("pinned", 0))
    project_dict["project_mode"] = project_dict.get("project_mode") or "managed"
    project_dict["local_root_path"] = project_dict.get("local_root_path") or None
    return project_dict


def list_projects() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT p.*,
                   MAX(v.created_at) AS last_version_at
            FROM projects p
            LEFT JOIN versions v ON v.project_id = p.id
            GROUP BY p.id
            ORDER BY p.pinned DESC, COALESCE(MAX(v.created_at), p.updated_at) DESC, p.id DESC
            """
        ).fetchall()
        result: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["protected_terms"] = json.loads(d["protected_terms"] or "[]")
            result.append(_attach_documents_to_project(conn, d))
        return result


def get_project(project_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["protected_terms"] = json.loads(d["protected_terms"] or "[]")
        return _attach_documents_to_project(conn, d)


def create_project(
    name: str,
    description: str = "",
    category: str = "paper",
    status: str = "polishing",
    primary_format: str = "latex",
    protected_terms: list[str] | None = None,
    default_doc_name: str | None = None,
    project_mode: str = "managed",
    local_root_path: str | None = None,
) -> dict[str, Any]:
    """Create either a managed upload project or a local-folder-bound project."""
    now = _now_iso()
    terms_json = json.dumps(protected_terms or [], ensure_ascii=False)
    norm_mode = "local_folder" if project_mode == "local_folder" else "managed"
    norm_root = local_root_path.strip() if isinstance(local_root_path, str) and local_root_path.strip() else None
    if norm_mode != "local_folder":
        norm_root = None

    default_doc_map = {
        "paper": ("主论文正文", "manuscript"),
        "grant": ("基金申请书正文", "proposal"),
        "report": ("结题总报告", "report"),
        "other": ("主文稿", "other"),
    }
    doc_name, doc_type = default_doc_map.get(category, ("主文稿", "manuscript"))
    if default_doc_name and default_doc_name.strip():
        doc_name = default_doc_name.strip()

    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO projects (
                name, description, category, status, pinned, primary_format,
                protected_terms, project_mode, local_root_path, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
            """,
            (
                name.strip(),
                description.strip(),
                category,
                status,
                primary_format,
                terms_json,
                norm_mode,
                norm_root,
                now,
                now,
            ),
        )
        pid = int(cur.lastrowid)
        if norm_mode == "managed":
            conn.execute(
                """
                INSERT INTO documents (project_id, name, doc_type, primary_format, notes, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, '', 0, ?, ?)
                """,
                (pid, doc_name, doc_type, primary_format, now, now),
            )
    proj = get_project(pid)
    assert proj is not None
    return proj


def update_project(
    project_id: int,
    name: str | None = None,
    description: str | None = None,
    category: str | None = None,
    status: str | None = None,
    pinned: bool | None = None,
    protected_terms: list[str] | None = None,
    project_mode: str | None = None,
    local_root_path: str | None = None,
) -> dict[str, Any] | None:
    """Update project metadata, relocate a bound folder, or unbind cleanly (never touches user disk files)."""
    existing = get_project(project_id)
    if not existing:
        return None
    new_name = name.strip() if (name is not None and name.strip()) else existing["name"]
    new_desc = description.strip() if description is not None else existing["description"]
    new_cat = category if category is not None else existing["category"]
    new_status = status if status is not None else existing["status"]
    new_pinned = (1 if pinned else 0) if pinned is not None else (1 if existing["pinned"] else 0)
    new_terms = protected_terms if protected_terms is not None else existing["protected_terms"]
    new_mode = (
        ("local_folder" if project_mode == "local_folder" else "managed")
        if project_mode is not None
        else (existing.get("project_mode") or "managed")
    )
    if local_root_path is not None:
        new_root = local_root_path.strip() or None
    else:
        new_root = existing.get("local_root_path")
    if new_mode == "managed" and local_root_path == "":
        new_root = None

    now = _now_iso()
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE projects
            SET name = ?, description = ?, category = ?, status = ?, pinned = ?,
                protected_terms = ?, project_mode = ?, local_root_path = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                new_name,
                new_desc,
                new_cat,
                new_status,
                new_pinned,
                json.dumps(new_terms, ensure_ascii=False),
                new_mode,
                new_root,
                now,
                project_id,
            ),
        )
    return get_project(project_id)


def delete_project(project_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        return cur.rowcount > 0


# ---------------- Documents CRUD ----------------

def list_documents(project_id: int) -> list[dict[str, Any]]:
    proj = get_project(project_id)
    return proj["documents"] if proj else []


def get_document(document_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        return dict(row) if row else None


def create_document(
    project_id: int,
    name: str,
    doc_type: str = "manuscript",
    primary_format: str = "latex",
    notes: str = "",
) -> dict[str, Any]:
    now = _now_iso()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) AS max_o FROM documents WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        next_order = int(row["max_o"]) + 1 if row else 0
        cur = conn.execute(
            """
            INSERT INTO documents (project_id, name, doc_type, primary_format, notes, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, name.strip(), doc_type, primary_format, notes.strip(), next_order, now, now),
        )
        did = int(cur.lastrowid)
        conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, project_id))
    doc = get_document(did)
    assert doc is not None
    return doc


def update_document(
    document_id: int,
    name: str | None = None,
    doc_type: str | None = None,
    primary_format: str | None = None,
    notes: str | None = None,
) -> dict[str, Any] | None:
    existing = get_document(document_id)
    if not existing:
        return None
    now = _now_iso()
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE documents
            SET name = ?, doc_type = ?, primary_format = ?, notes = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                name.strip() if name is not None else existing["name"],
                doc_type if doc_type is not None else existing["doc_type"],
                primary_format if primary_format is not None else existing["primary_format"],
                notes.strip() if notes is not None else existing["notes"],
                now,
                document_id,
            ),
        )
        conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, existing["project_id"]))
    return get_document(document_id)


def delete_document(document_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        return cur.rowcount > 0


# ---------------- Versions CRUD ----------------

def list_versions_by_document(document_id: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, project_id, document_id, version_number, label, source_tag, is_milestone,
                   parent_version_id, filename, format, source_blob_key, notes, word_count, para_count, ai_ism_count, created_at
            FROM versions
            WHERE document_id = ?
            ORDER BY version_number ASC, id ASC
            """,
            (document_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["is_milestone"] = bool(d.get("is_milestone", 0))
            out.append(d)
        return out


def list_versions(project_id: int) -> list[dict[str, Any]]:
    """Backward-compatible: list versions of the project's first document."""
    docs = list_documents(project_id)
    if not docs:
        return []
    return list_versions_by_document(int(docs[0]["id"]))


def get_version(version_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM versions WHERE id = ?", (version_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["is_milestone"] = bool(d.get("is_milestone", 0))
        try:
            d["meta"] = json.loads(d.get("meta_json") or "{}")
        except Exception:
            d["meta"] = {}
        return d


def create_version(
    project_id: int,
    label: str,
    source_tag: str,
    filename: str,
    fmt: str,
    content: str,
    notes: str,
    word_count: int,
    para_count: int,
    ai_ism_count: int,
    document_id: int | None = None,
    is_milestone: bool = False,
    parent_version_id: int | None = None,
    meta: dict[str, Any] | None = None,
    source_blob_key: str | None = None,
) -> dict[str, Any]:
    now = _now_iso()
    meta_str = json.dumps(meta or {}, ensure_ascii=False)
    with get_conn() as conn:
        eff_doc_id = document_id
        if eff_doc_id is None:
            row_doc = conn.execute(
                "SELECT id FROM documents WHERE project_id = ? ORDER BY sort_order ASC, id ASC LIMIT 1",
                (project_id,),
            ).fetchone()
            if row_doc:
                eff_doc_id = int(row_doc["id"])
            else:
                cur_d = conn.execute(
                    "INSERT INTO documents (project_id, name, doc_type, primary_format, notes, sort_order, created_at, updated_at) VALUES (?, '主文稿', 'manuscript', ?, '', 0, ?, ?)",
                    (project_id, fmt, now, now),
                )
                eff_doc_id = int(cur_d.lastrowid)

        row = conn.execute(
            "SELECT COALESCE(MAX(version_number), 0) AS max_v FROM versions WHERE document_id = ?",
            (eff_doc_id,),
        ).fetchone()
        next_v = int(row["max_v"]) + 1 if row else 1
        effective_label = label.strip() or f"v{next_v} · {source_tag or '修订'}"
        cur = conn.execute(
            """
            INSERT INTO versions (
                project_id, document_id, version_number, label, source_tag, is_milestone, parent_version_id,
                filename, format, content, meta_json, source_blob_key, notes, word_count, para_count, ai_ism_count, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                eff_doc_id,
                next_v,
                effective_label,
                source_tag.strip() or "手改",
                1 if is_milestone else 0,
                parent_version_id,
                filename,
                fmt,
                content,
                meta_str,
                source_blob_key,
                notes.strip(),
                word_count,
                para_count,
                ai_ism_count,
                now,
            ),
        )
        vid = int(cur.lastrowid)
        conn.execute("UPDATE documents SET updated_at = ? WHERE id = ?", (now, eff_doc_id))
        conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, project_id))
    ver = get_version(vid)
    assert ver is not None
    return ver


def update_version(
    version_id: int,
    label: str | None = None,
    source_tag: str | None = None,
    notes: str | None = None,
    is_milestone: bool | None = None,
) -> dict[str, Any] | None:
    existing = get_version(version_id)
    if not existing:
        return None
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE versions
            SET label = ?, source_tag = ?, notes = ?, is_milestone = ?
            WHERE id = ?
            """,
            (
                label.strip() if label is not None and label.strip() else existing["label"],
                source_tag.strip() if source_tag is not None and source_tag.strip() else existing["source_tag"],
                notes.strip() if notes is not None else existing["notes"],
                (1 if is_milestone else 0) if is_milestone is not None else (1 if existing["is_milestone"] else 0),
                version_id,
            ),
        )
    return get_version(version_id)


def delete_version(version_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM versions WHERE id = ?", (version_id,))
        return cur.rowcount > 0


# ---------------- Merge Decisions ----------------

def get_merge_decisions(project_id: int, old_version_id: int, new_version_id: int) -> dict[str, str]:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT decisions_json FROM merge_decisions
            WHERE project_id = ? AND old_version_id = ? AND new_version_id = ?
            """,
            (project_id, old_version_id, new_version_id),
        ).fetchone()
        if not row:
            return {}
        return json.loads(row["decisions_json"] or "{}")


def save_merge_decisions(
    project_id: int,
    old_version_id: int,
    new_version_id: int,
    decisions: dict[str, str],
    document_id: int | None = None,
) -> dict[str, str]:
    now = _now_iso()
    payload = json.dumps(decisions, ensure_ascii=False)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO merge_decisions (project_id, document_id, old_version_id, new_version_id, decisions_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, old_version_id, new_version_id)
            DO UPDATE SET decisions_json = excluded.decisions_json, document_id = COALESCE(excluded.document_id, merge_decisions.document_id), updated_at = excluded.updated_at
            """,
            (project_id, document_id, old_version_id, new_version_id, payload, now),
        )
    return decisions


# ---------------- App Settings & Alert Acknowledgements (v1.3) ----------------

def get_ai_lexicon_settings() -> dict[str, list[str]]:
    default = {"added_en": [], "added_zh": [], "muted": []}
    with get_conn() as conn:
        row = conn.execute("SELECT value_json FROM app_settings WHERE key = 'ai_lexicon'").fetchone()
        if not row:
            return default
        try:
            data = json.loads(row["value_json"] or "{}")
            return {
                "added_en": [str(x).strip() for x in data.get("added_en", []) if str(x).strip()],
                "added_zh": [str(x).strip() for x in data.get("added_zh", []) if str(x).strip()],
                "muted": [str(x).strip().lower() for x in data.get("muted", []) if str(x).strip()],
            }
        except Exception:
            return default


def save_ai_lexicon_settings(
    added_en: list[str], added_zh: list[str], muted: list[str]
) -> dict[str, list[str]]:
    cleaned = {
        "added_en": sorted({x.strip().lower() for x in added_en if x.strip()}),
        "added_zh": sorted({x.strip() for x in added_zh if x.strip()}),
        "muted": sorted({x.strip().lower() for x in muted if x.strip()}),
    }
    now = _now_iso()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value_json, updated_at)
            VALUES ('ai_lexicon', ?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
            """,
            (json.dumps(cleaned, ensure_ascii=False), now),
        )
    return cleaned


def get_alert_acks(document_id: int, old_version_id: int, new_version_id: int) -> list[str]:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT acked_json FROM alert_acks
            WHERE document_id = ? AND old_version_id = ? AND new_version_id = ?
            """,
            (document_id, old_version_id, new_version_id),
        ).fetchone()
        if not row:
            return []
        try:
            return [str(x) for x in json.loads(row["acked_json"] or "[]")]
        except Exception:
            return []


def save_alert_acks(
    document_id: int, old_version_id: int, new_version_id: int, acked_ids: list[str]
) -> list[str]:
    cleaned = sorted({str(x) for x in acked_ids if str(x)})
    now = _now_iso()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO alert_acks (document_id, old_version_id, new_version_id, acked_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(document_id, old_version_id, new_version_id)
            DO UPDATE SET acked_json = excluded.acked_json, updated_at = excluded.updated_at
            """,
            (document_id, old_version_id, new_version_id, json.dumps(cleaned, ensure_ascii=False), now),
        )
    return cleaned


def _norm_pair_rel_path(rel_path: str) -> str:
    return rel_path.replace("\\", "/").strip().lstrip("./")


def get_local_pair_state(
    project_id: int, old_rel_path: str, new_rel_path: str
) -> dict[str, Any]:
    """Load persisted alert acknowledgements and Cherry-Pick decisions for a local file pair."""
    old_k = _norm_pair_rel_path(old_rel_path)
    new_k = _norm_pair_rel_path(new_rel_path)
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT acked_json, decisions_json FROM local_pair_states
            WHERE project_id = ? AND old_rel_path = ? AND new_rel_path = ?
            """,
            (project_id, old_k, new_k),
        ).fetchone()
        if not row:
            return {"acked_ids": [], "decisions": {}}
        try:
            acked = [str(x) for x in json.loads(row["acked_json"] or "[]")]
        except Exception:
            acked = []
        try:
            decs = {str(k): str(v) for k, v in json.loads(row["decisions_json"] or "{}").items()}
        except Exception:
            decs = {}
        return {"acked_ids": acked, "decisions": decs}


def save_local_pair_state(
    project_id: int,
    old_rel_path: str,
    new_rel_path: str,
    *,
    acked_ids: list[str] | None = None,
    decisions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Persist relative-path-keyed alert acks and/or Cherry-Pick decisions (survives folder relocation)."""
    old_k = _norm_pair_rel_path(old_rel_path)
    new_k = _norm_pair_rel_path(new_rel_path)
    cur = get_local_pair_state(project_id, old_k, new_k)
    next_acked = (
        sorted({str(x) for x in acked_ids if str(x)})
        if acked_ids is not None
        else cur["acked_ids"]
    )
    next_decs = (
        {str(k): str(v) for k, v in decisions.items()}
        if decisions is not None
        else cur["decisions"]
    )
    now = _now_iso()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO local_pair_states (project_id, old_rel_path, new_rel_path, acked_json, decisions_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, old_rel_path, new_rel_path)
            DO UPDATE SET acked_json = excluded.acked_json, decisions_json = excluded.decisions_json, updated_at = excluded.updated_at
            """,
            (
                project_id,
                old_k,
                new_k,
                json.dumps(next_acked, ensure_ascii=False),
                json.dumps(next_decs, ensure_ascii=False),
                now,
            ),
        )
    return {"acked_ids": next_acked, "decisions": next_decs}


