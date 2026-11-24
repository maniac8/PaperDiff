"""W2 TDD Verification Suite: Local Folder Binding, Sandbox, Direct Read & Pairwise Diff (W2-T01..W2-T15)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from backend import database


def test_w2_t01_sqlite_dual_mode_migration_and_pair_states(tmp_path: Path, monkeypatch) -> None:
    """W2-T01: Idempotent v1.2 -> v1.3 SQLite migration preserves managed projects and persists relative-path pair states."""
    db_file = tmp_path / "legacy_v12.db"
    conn = sqlite3.connect(str(db_file))
    conn.executescript(
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT 'paper',
            status TEXT NOT NULL DEFAULT 'polishing',
            pinned INTEGER NOT NULL DEFAULT 0,
            primary_format TEXT NOT NULL DEFAULT 'latex',
            protected_terms TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            doc_type TEXT NOT NULL DEFAULT 'manuscript',
            primary_format TEXT NOT NULL DEFAULT 'latex',
            notes TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE versions (
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
            source_blob_key TEXT DEFAULT NULL,
            notes TEXT NOT NULL DEFAULT '',
            word_count INTEGER NOT NULL DEFAULT 0,
            para_count INTEGER NOT NULL DEFAULT 0,
            ai_ism_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        INSERT INTO projects (id, name, primary_format, created_at, updated_at)
        VALUES (1, 'Legacy Managed Paper', 'latex', '2026-01-01 00:00:00', '2026-01-01 00:00:00');
        INSERT INTO documents (id, project_id, name, primary_format, created_at, updated_at)
        VALUES (10, 1, '主论文', 'latex', '2026-01-01 00:00:00', '2026-01-01 00:00:00');
        INSERT INTO versions (id, project_id, document_id, version_number, label, content, created_at)
        VALUES (100, 1, 10, 1, 'v1', 'Legacy content intact.', '2026-01-01 00:00:00');
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(database, "DB_PATH", db_file)

    # Run init_db twice to verify idempotency
    database.init_db()
    database.init_db()

    legacy = database.get_project(1)
    assert legacy is not None
    assert legacy["name"] == "Legacy Managed Paper"
    assert legacy.get("project_mode") == "managed"
    assert legacy.get("local_root_path") is None
    assert legacy["document_count"] == 1 and legacy["version_count"] == 1

    # Create a local_folder project & persist relative-path-keyed pair state
    folder_a = tmp_path / "paper_a"
    folder_a.mkdir()
    local_proj = database.create_project(
        name="Local Bound Paper",
        project_mode="local_folder",
        local_root_path=str(folder_a),
    )
    assert local_proj["project_mode"] == "local_folder"
    assert local_proj["local_root_path"] == str(folder_a)

    # Save pair state by relative paths, relocate root path, and verify state survives
    saved = database.save_local_pair_state(
        local_proj["id"],
        "drafts/v1.tex",
        "drafts/v2.tex",
        acked_ids=["alert-1", "alert-2"],
        decisions={"hunk-0": "keep_old"},
    )
    assert saved["acked_ids"] == ["alert-1", "alert-2"]
    assert saved["decisions"] == {"hunk-0": "keep_old"}

    folder_b = tmp_path / "paper_b_moved"
    folder_b.mkdir()
    relocated = database.update_project(local_proj["id"], local_root_path=str(folder_b))
    assert relocated is not None and relocated["local_root_path"] == str(folder_b)

    reloaded = database.get_local_pair_state(local_proj["id"], "drafts/v1.tex", "drafts/v2.tex")
    assert reloaded["acked_ids"] == ["alert-1", "alert-2"]
    assert reloaded["decisions"] == {"hunk-0": "keep_old"}

    # Unbind clears local_root_path and resets mode to managed without touching disk
    unbound = database.update_project(local_proj["id"], project_mode="managed", local_root_path="")
    assert unbound is not None
    assert unbound["project_mode"] == "managed"
    assert unbound["local_root_path"] is None


def test_w2_t02_path_sandbox_blocks_escapes_and_symlinks(tmp_path: Path) -> None:
    """W2-T02: Path sandbox blocks ../ traversal, absolute paths, and outside symlinks with 403 PATH_OUTSIDE_ROOT."""
    import os
    import pytest

    from backend.local_workspace import LocalWorkspaceError, resolve_safe_path, scan_local_tree

    root = tmp_path / "bound_paper"
    root.mkdir()
    (root / "main.tex").write_text("Hello", encoding="utf-8")

    outside_secret = tmp_path / "secret.txt"
    outside_secret.write_text("TOP_SECRET_DATA", encoding="utf-8")

    # Symlink inside bound root pointing outside root
    evil_link = root / "evil_link.md"
    os.symlink(outside_secret, evil_link)

    # 1. Valid in-root path passes
    ok = resolve_safe_path(root, "main.tex", must_exist=True)
    assert ok == (root / "main.tex").resolve()

    # 2. ../ traversal rejected with 403 PATH_OUTSIDE_ROOT
    with pytest.raises(LocalWorkspaceError) as exc1:
        resolve_safe_path(root, "../secret.txt")
    assert exc1.value.status_code == 403 and exc1.value.code == "PATH_OUTSIDE_ROOT"

    # 3. Absolute path outside root rejected
    with pytest.raises(LocalWorkspaceError) as exc2:
        resolve_safe_path(root, str(outside_secret))
    assert exc2.value.status_code == 403 and exc2.value.code == "PATH_OUTSIDE_ROOT"

    # 4. Symlink escaping root rejected
    with pytest.raises(LocalWorkspaceError) as exc3:
        resolve_safe_path(root, "evil_link.md", must_exist=True)
    assert exc3.value.status_code == 403 and exc3.value.code == "PATH_OUTSIDE_ROOT"

    # 5. Directory scan silently skips outside symlink (never leaks it into tree)
    tree = scan_local_tree(root, include_aux=True)
    flat_names = [n["name"] for n in tree["nodes"]]
    assert "main.tex" in flat_names
    assert "evil_link.md" not in flat_names


def test_w2_t03_bounded_tree_scan_noise_filter_aux_and_truncation(tmp_path: Path) -> None:
    """W2-T03: Tree scanner filters compile/OS noise, honors include_aux toggle, guards symlink loops, and truncates safely."""
    import os

    from backend.local_workspace import scan_local_tree

    root = tmp_path / "thesis_dir"
    root.mkdir()
    (root / "draft_v1.tex").write_text("v1", encoding="utf-8")
    (root / "draft_v2.md").write_text("# v2", encoding="utf-8")
    (root / "notes.txt").write_text("notes", encoding="utf-8")
    (root / "refs.bib").write_text("@article{a, title={T}}", encoding="utf-8")
    # Noise files that must NEVER appear
    (root / ".DS_Store").write_bytes(b"\x00")
    (root / "draft_v1.aux").write_text("aux", encoding="utf-8")
    (root / "draft_v1.log").write_text("log", encoding="utf-8")
    (root / "draft_v1.synctex.gz").write_bytes(b"gz")
    (root / "~$locked.docx").write_bytes(b"lock")
    (root / "draft_v1.paperdiff.bak.tex").write_text("bak", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("git", encoding="utf-8")

    figs = root / "figures"
    figs.mkdir()
    (figs / "fig1.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    sub = root / "sections"
    sub.mkdir()
    (sub / "method.tex").write_text("method", encoding="utf-8")
    # Self-referential symlink loop inside root must not cause infinite recursion
    os.symlink(root, sub / "loop_back")

    def _collect_rel_paths(nodes: list[dict]) -> list[str]:
        out: list[str] = []
        for n in nodes:
            if n["node_type"] == "file":
                out.append(n["rel_path"])
            else:
                out.extend(_collect_rel_paths(n.get("children") or []))
        return out

    # Default include_aux=False: only primary docs, zero noise, zero aux
    t_docs = scan_local_tree(root, include_aux=False)
    rels_docs = _collect_rel_paths(t_docs["nodes"])
    assert sorted(rels_docs) == ["draft_v1.tex", "draft_v2.md", "notes.txt", "sections/method.tex"]
    assert t_docs["doc_count"] == 4
    assert t_docs["truncated"] is False

    # include_aux=True: exposes refs.bib & figures/fig1.png while still excluding compile/OS noise
    t_aux = scan_local_tree(root, include_aux=True)
    rels_aux = _collect_rel_paths(t_aux["nodes"])
    assert "refs.bib" in rels_aux and "figures/fig1.png" in rels_aux
    for noise in (".DS_Store", "draft_v1.aux", "draft_v1.log", "draft_v1.synctex.gz", "~$locked.docx", ".git/config"):
        assert noise not in rels_aux

    # Depth limit & entry cap truncation (D-07)
    deep = tmp_path / "deep_dir"
    cur = deep
    for i in range(13):
        cur = cur / f"lvl{i}"
        cur.mkdir(parents=True)
        (cur / f"doc_{i}.md").write_text("hi", encoding="utf-8")
    t_deep = scan_local_tree(deep, max_depth=10)
    assert t_deep["truncated"] is True and t_deep["truncated_reason"]

    many = tmp_path / "many_dir"
    many.mkdir()
    for i in range(40):
        (many / f"f_{i:03d}.md").write_text("x", encoding="utf-8")
    t_many = scan_local_tree(many, max_entries=20)
    assert t_many["truncated"] is True and t_many["doc_count"] <= 20


def test_w2_t04_local_project_lifecycle_validate_pick_and_disk_invariance(tmp_path: Path, monkeypatch) -> None:
    """W2-T04: Folder validation, local project create/relocate/unbind/delete leave disk SHA-256 100% intact, and pick-folder blocks non-loopback."""
    import hashlib
    from fastapi.testclient import TestClient

    from backend.main import app

    db_file = tmp_path / "w2_t04.db"
    monkeypatch.setattr(database, "DB_PATH", db_file)
    database.init_db()

    dir1 = tmp_path / "paper_dir_1"
    dir1.mkdir()
    f1 = dir1 / "v1.tex"
    f2 = dir1 / "v2.md"
    f1.write_text(r"\section{Intro} Flux is 14.2\%.", encoding="utf-8")
    f2.write_text("# Notes\n\nLocal markdown.", encoding="utf-8")

    dir2 = tmp_path / "paper_dir_2"
    dir2.mkdir()
    f3 = dir2 / "v3.md"
    f3.write_text("# Relocated\n\nStill intact.", encoding="utf-8")

    def _snapshot(folder: Path) -> dict[str, str]:
        return {
            p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*"))
            if p.is_file()
        }

    snap1_before = _snapshot(dir1)
    snap2_before = _snapshot(dir2)

    with TestClient(app) as client:
        # 1. Validate folder
        r_ok = client.post("/api/local/validate-folder", json={"path": str(dir1)})
        assert r_ok.status_code == 200
        j_ok = r_ok.json()
        assert j_ok["valid"] is True and j_ok["doc_count"] == 2
        assert j_ok["resolved_path"] == str(dir1.resolve())

        r_bad = client.post("/api/local/validate-folder", json={"path": str(tmp_path / "nope")})
        assert r_bad.status_code == 200 and r_bad.json()["valid"] is False
        assert r_bad.json()["error_code"] == "NOT_FOUND"

        # 2. Create local_folder project
        r_create = client.post(
            "/api/projects",
            json={
                "name": "W2 Local Test",
                "project_mode": "local_folder",
                "local_root_path": str(dir1),
            },
        )
        assert r_create.status_code == 200
        proj = r_create.json()
        pid = proj["id"]
        assert proj["project_mode"] == "local_folder"
        assert proj["local_status"] == "ok"
        assert proj["local_doc_count"] == 2

        # 3. Relocate -> Unbind -> Delete never touches disk files
        r_reloc = client.patch(f"/api/projects/{pid}", json={"local_root_path": str(dir2)})
        assert r_reloc.status_code == 200
        assert r_reloc.json()["local_doc_count"] == 1
        assert r_reloc.json()["local_root_path"] == str(dir2.resolve())

        r_unbind = client.patch(
            f"/api/projects/{pid}",
            json={"project_mode": "managed", "local_root_path": ""},
        )
        assert r_unbind.status_code == 200
        assert r_unbind.json()["project_mode"] == "managed"
        assert r_unbind.json()["local_root_path"] is None

        r_del = client.delete(f"/api/projects/{pid}")
        assert r_del.status_code == 200 and r_del.json()["deleted"] is True

    assert _snapshot(dir1) == snap1_before
    assert _snapshot(dir2) == snap2_before

    # 4. Non-loopback caller cannot invoke native pick-folder dialog
    with TestClient(app, client=("198.51.100.42", 55555)) as remote_client:
        r_remote = remote_client.post("/api/local/pick-folder", json={})
        assert r_remote.status_code == 403


def _tiny_png_bytes() -> bytes:
    """Return minimal valid 1x1 PNG bytes."""
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )


def _make_docx_bytes(paragraphs: list[str], *, tracked: bool = False) -> bytes:
    """Build a real .docx in memory (optionally with native OOXML <w:ins>/<w:del> Track Changes)."""
    import io
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    if tracked:
        para = doc.add_paragraph("Flux reached ")
        d_el = OxmlElement("w:del")
        d_el.set(qn("w:id"), "1")
        d_el.set(qn("w:author"), "Reviewer")
        dr = OxmlElement("w:r")
        dt = OxmlElement("w:delText")
        dt.text = "14.2%"
        dr.append(dt)
        d_el.append(dr)
        para._p.append(d_el)

        i_el = OxmlElement("w:ins")
        i_el.set(qn("w:id"), "2")
        i_el.set(qn("w:author"), "Author")
        ir = OxmlElement("w:r")
        it = OxmlElement("w:t")
        it.text = "18.6%"
        ir.append(it)
        i_el.append(ir)
        para._p.append(i_el)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_w2_t05_local_direct_preview_context_assets_bib_and_safe_input(tmp_path: Path, monkeypatch) -> None:
    """W2-T05: Zero-upload direct read resolves relative figures, sibling .bib, safe \\input, and blocks outside \\input."""
    import hashlib
    from fastapi.testclient import TestClient

    from backend.main import app

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "w2_t05.db")
    database.init_db()

    (tmp_path / "outside.tex").write_text("LEAKED_OUTSIDE_SECRET", encoding="utf-8")
    root = tmp_path / "paper_ctx"
    (root / "sections").mkdir(parents=True)
    (root / "figures").mkdir(parents=True)
    png_path = root / "figures" / "fig1.png"
    png_path.write_bytes(_tiny_png_bytes())
    (root / "refs.bib").write_text(
        "@inproceedings{vaswani2017,\n  author={Vaswani, A.},\n  title={Attention Is All You Need},\n  year={2017},\n  booktitle={NeurIPS}\n}\n",
        encoding="utf-8",
    )
    (root / "sections" / "method.tex").write_text(
        "Sparse routing measured AdaptRouteBudget at 128K context.\n",
        encoding="utf-8",
    )
    tex_path = root / "main.tex"
    tex_path.write_text(
        r"""\documentclass{article}
\begin{document}
\section{Methods}
\input{sections/method}
\input{../outside}
As shown in \cite{vaswani2017}, results match observations.
\begin{figure}
\includegraphics{figures/fig1.png}
\caption{Attention latency profile.}
\end{figure}
\bibliography{refs}
\end{document}
""",
        encoding="utf-8",
    )
    md_path = root / "notes.md"
    md_path.write_text("# Notes\n\n![Latency plot](figures/fig1.png)\n\nReference AdaptRouteBudget [@vaswani2017].\n", encoding="utf-8")

    tex_sha = hashlib.sha256(tex_path.read_bytes()).hexdigest()
    png_sha = hashlib.sha256(png_path.read_bytes()).hexdigest()

    with TestClient(app) as client:
        pid = client.post(
            "/api/projects",
            json={
                "name": "Ctx Paper",
                "project_mode": "local_folder",
                "local_root_path": str(root),
                "protected_terms": ["AdaptRouteBudget"],
            },
        ).json()["id"]

        r_tex = client.post(f"/api/projects/{pid}/local/preview", json={"rel_path": "main.tex"})
        assert r_tex.status_code == 200, r_tex.text
        p_tex = r_tex.json()
        all_text = "\n".join(b["clean_text"] for b in p_tex["blocks"])
        assert "Sparse routing measured AdaptRouteBudget" in all_text
        assert "LEAKED_OUTSIDE_SECRET" not in all_text
        assert "vaswani2017" in (p_tex.get("bib_entries") or {})
        assert p_tex["file_sha256"] == tex_sha
        fig_blocks = [b for b in p_tex["blocks"] if b["block_type"] == "figure"]
        assert fig_blocks and fig_blocks[0]["figure_info"]["asset_key"]
        r_asset = client.get(f"/api/assets/{fig_blocks[0]['figure_info']['asset_key']}")
        assert r_asset.status_code == 200 and r_asset.content.startswith(b"\x89PNG")
        assert any(tc["term"] == "AdaptRouteBudget" and tc["count"] >= 1 for tc in p_tex["term_coverage"])

        r_md = client.post(f"/api/projects/{pid}/local/preview", json={"rel_path": "notes.md"})
        assert r_md.status_code == 200
        p_md = r_md.json()
        md_figs = [b for b in p_md["blocks"] if b["block_type"] == "figure"]
        assert md_figs and md_figs[0]["figure_info"]["asset_key"]
        assert "vaswani2017" in (p_md.get("bib_entries") or {})

    assert hashlib.sha256(tex_path.read_bytes()).hexdigest() == tex_sha
    assert hashlib.sha256(png_path.read_bytes()).hexdigest() == png_sha


def test_w2_t06_local_docx_raw_stream_and_tracked_changes_split(tmp_path: Path, monkeypatch) -> None:
    """W2-T06: Local .docx serves raw bytes for Word Original view and splits Track Changes without touching disk."""
    import hashlib
    from fastapi.testclient import TestClient

    from backend.main import app

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "w2_t06.db")
    database.init_db()

    root = tmp_path / "word_proj"
    root.mkdir()
    plain_bytes = _make_docx_bytes(["Introduction", "Plain Word paragraph content."])
    tracked_bytes = _make_docx_bytes(["Methods"], tracked=True)
    plain_p = root / "plain.docx"
    tracked_p = root / "tracked.docx"
    plain_p.write_bytes(plain_bytes)
    tracked_p.write_bytes(tracked_bytes)
    tracked_sha = hashlib.sha256(tracked_bytes).hexdigest()

    with TestClient(app) as client:
        pid = client.post(
            "/api/projects",
            json={"name": "Word Local", "project_mode": "local_folder", "local_root_path": str(root)},
        ).json()["id"]

        r_raw = client.get(f"/api/projects/{pid}/local/raw", params={"rel_path": "plain.docx"})
        assert r_raw.status_code == 200
        assert r_raw.content == plain_bytes

        r_prev = client.post(f"/api/projects/{pid}/local/preview", json={"rel_path": "tracked.docx"})
        assert r_prev.status_code == 200
        tc = r_prev.json().get("tracked_changes_info") or {}
        assert tc.get("has_tracked_changes") is True and tc.get("ins_count", 0) >= 1 and tc.get("del_count", 0) >= 1

        r_split = client.post(
            f"/api/projects/{pid}/local/compare",
            json={"rel_path": "tracked.docx", "docx_tracked_split": True},
        )
        assert r_split.status_code == 200
        cmp_data = r_split.json()
        assert cmp_data["summary"]["modified_paragraphs"] >= 1
        joined_old = " ".join(p["old_clean"] for p in cmp_data["paragraphs"])
        joined_new = " ".join(p["new_clean"] for p in cmp_data["paragraphs"])
        assert "14.2%" in joined_old and "18.6%" in joined_new

    assert hashlib.sha256(tracked_p.read_bytes()).hexdigest() == tracked_sha


def test_w2_t07_local_pairwise_diff_relocated_acks_and_offline_pdf(tmp_path: Path, monkeypatch) -> None:
    """W2-T07: Pairwise Diff (same dir / cross dir / cross format), ack persistence across relocation, and offline PDF."""
    import shutil
    from fastapi.testclient import TestClient

    from backend.export import find_local_chrome
    from backend.main import app

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "w2_t07.db")
    database.init_db()

    root = tmp_path / "diff_proj"
    (root / "sub").mkdir(parents=True)
    (root / "v1.tex").write_text(
        r"\section{Results}" + "\n\n" + r"Measured decode latency was 14.2 ms/tok ($p < 0.01$)." + "\n",
        encoding="utf-8",
    )
    (root / "v2.tex").write_text(
        r"\section{Results}" + "\n\n" + r"Measured decode latency was 22.8 ms/tok ($p < 0.05$)." + "\n",
        encoding="utf-8",
    )
    (root / "notes.md").write_text("# Results\n\nObserved latency was 14.2 ms/tok.\n", encoding="utf-8")
    (root / "sub" / "notes_v2.md").write_text("# Results\n\nObserved latency increased to 19.5 ms/tok.\n", encoding="utf-8")
    (root / "word_v2.docx").write_bytes(_make_docx_bytes(["Results", "Measured decode latency was 25.0 ms/tok."]))

    with TestClient(app) as client:
        pid = client.post(
            "/api/projects",
            json={"name": "Diff Local", "project_mode": "local_folder", "local_root_path": str(root)},
        ).json()["id"]

        # 1. Same-dir .tex pair -> generates numeric alert -> persist ack & decision
        r_tex_cmp = client.post(
            f"/api/projects/{pid}/local/compare",
            json={"old_rel_path": "v1.tex", "new_rel_path": "v2.tex"},
        )
        assert r_tex_cmp.status_code == 200
        tex_cmp = r_tex_cmp.json()
        assert tex_cmp["summary"]["modified_paragraphs"] >= 1
        assert len(tex_cmp["alerts"]) >= 1
        first_alert_id = tex_cmp["alerts"][0]["alert_id"]

        r_save_state = client.put(
            f"/api/projects/{pid}/local/pair-state",
            json={
                "old_rel_path": "v1.tex",
                "new_rel_path": "v2.tex",
                "acked_ids": [first_alert_id],
                "decisions": {"h0": "keep_old"},
            },
        )
        assert r_save_state.status_code == 200

        # 2. Cross-subdir & Cross-format (.tex vs .docx)
        r_cross_dir = client.post(
            f"/api/projects/{pid}/local/compare",
            json={"old_rel_path": "notes.md", "new_rel_path": "sub/notes_v2.md"},
        )
        assert r_cross_dir.status_code == 200 and r_cross_dir.json()["summary"]["modified_paragraphs"] >= 1

        r_cross_fmt = client.post(
            f"/api/projects/{pid}/local/compare",
            json={"old_rel_path": "v1.tex", "new_rel_path": "word_v2.docx"},
        )
        assert r_cross_fmt.status_code == 200 and r_cross_fmt.json()["formats"] == {"old": "latex", "new": "docx"}

        # 3. Physically move folder on disk & relocate project -> relative-path acks survive!
        moved_root = tmp_path / "diff_proj_relocated"
        shutil.move(str(root), str(moved_root))
        r_reloc = client.patch(f"/api/projects/{pid}", json={"local_root_path": str(moved_root)})
        assert r_reloc.status_code == 200

        r_reopen = client.post(
            f"/api/projects/{pid}/local/compare",
            json={"old_rel_path": "v1.tex", "new_rel_path": "v2.tex"},
        )
        assert r_reopen.status_code == 200
        reopened = r_reopen.json()
        assert first_alert_id in (reopened.get("acked_alert_ids") or [])
        assert reopened.get("decisions", {}).get("h0") == "keep_old"

        # 4. Offline single & diff print HTML / PDF export for local project files
        r_html_single = client.post(
            "/api/export",
            json={
                "local_project_id": pid,
                "local_rel_path": "v2.tex",
                "project_name": "Diff Local",
                "export_type": "print_html_single",
            },
        )
        assert r_html_single.status_code == 200
        assert "cdn.jsdelivr.net" not in r_html_single.text and "22.8" in r_html_single.text

        r_html_diff = client.post(
            "/api/export",
            json={
                "local_project_id": pid,
                "local_old_rel_path": "v1.tex",
                "local_new_rel_path": "v2.tex",
                "project_name": "Diff Local",
                "export_type": "print_html_diff",
            },
        )
        assert r_html_diff.status_code == 200
        assert "cdn.jsdelivr.net" not in r_html_diff.text and "14.2" in r_html_diff.text and "22.8" in r_html_diff.text

        if find_local_chrome():
            r_pdf_diff = client.post(
                "/api/export",
                json={
                    "local_project_id": pid,
                    "local_old_rel_path": "v1.tex",
                    "local_new_rel_path": "v2.tex",
                    "project_name": "Diff Local",
                    "export_type": "pdf_diff_report",
                },
            )
            assert r_pdf_diff.status_code == 200
            assert r_pdf_diff.content.startswith(b"%PDF-") and len(r_pdf_diff.content) > 10_000


def test_w2_t08_external_change_stat_and_optimistic_lock_409(tmp_path: Path, monkeypatch) -> None:
    """W2-T08: /local/stat detects external disk edits & /local/save-edits returns 409 EXTERNAL_MODIFIED on stale sha256."""
    from fastapi.testclient import TestClient

    from backend.main import app

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "w2_t08.db")
    database.init_db()

    root = tmp_path / "ext_watch"
    root.mkdir()
    doc_p = root / "paper.md"
    doc_p.write_text("# Title\n\nOriginal paragraph text.\n", encoding="utf-8")

    with TestClient(app) as client:
        pid = client.post(
            "/api/projects",
            json={"name": "Watch Proj", "project_mode": "local_folder", "local_root_path": str(root)},
        ).json()["id"]

        r_s1 = client.get(f"/api/projects/{pid}/local/stat", params={"rel_path": "paper.md"})
        assert r_s1.status_code == 200
        sha1 = r_s1.json()["files"]["paper.md"]["sha256"]

        # Simulate external AI tool creating a new file and modifying paper.md on disk
        (root / "ai_draft.md").write_text("# AI Draft\n\nNew file.\n", encoding="utf-8")
        doc_p.write_text("# Title\n\nExternally updated by AI tool.\n", encoding="utf-8")

        r_tree = client.get(f"/api/projects/{pid}/local/tree")
        assert r_tree.status_code == 200
        names = [n["name"] for n in r_tree.json()["nodes"]]
        assert "ai_draft.md" in names

        r_s2 = client.get(f"/api/projects/{pid}/local/stat", params={"rel_path": "paper.md"})
        assert r_s2.status_code == 200
        sha2 = r_s2.json()["files"]["paper.md"]["sha256"]
        assert sha2 != sha1

        # Saving overwrite with stale expected_sha256 -> 409 EXTERNAL_MODIFIED; disk remains externally updated!
        r_conflict = client.post(
            f"/api/projects/{pid}/local/save-edits",
            json={
                "rel_path": "paper.md",
                "mode": "overwrite",
                "expected_sha256": sha1,
                "paragraph_edits": {"1": "Stale local edit"},
            },
        )
        assert r_conflict.status_code == 409
        assert r_conflict.json().get("code") == "EXTERNAL_MODIFIED"
        assert "Externally updated by AI tool." in doc_p.read_text(encoding="utf-8")


def test_w2_t09_readonly_browse_and_two_mode_lossless_writeback(tmp_path: Path, monkeypatch) -> None:
    """W2-T09: Read/refresh/compare leave disk SHA-256 unchanged; save_as keeps original untouched; overwrite writes .bak backup."""
    import hashlib
    from fastapi.testclient import TestClient

    from backend.main import app

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "w2_t09.db")
    database.init_db()

    root = tmp_path / "save_proj"
    root.mkdir()
    md_p = root / "draft.md"
    tex_p = root / "paper.tex"
    docx_p = root / "report.docx"
    md_p.write_text("# Intro\n\nInitial markdown sentence.\n", encoding="utf-8")
    tex_p.write_text(r"\section{Intro}" + "\n\nInitial LaTeX sentence.\n", encoding="utf-8")
    docx_p.write_bytes(_make_docx_bytes(["Intro", "Initial Word sentence."]))

    orig_md_sha = hashlib.sha256(md_p.read_bytes()).hexdigest()
    orig_tex_bytes = tex_p.read_bytes()
    orig_tex_sha = hashlib.sha256(orig_tex_bytes).hexdigest()
    orig_docx_sha = hashlib.sha256(docx_p.read_bytes()).hexdigest()

    with TestClient(app) as client:
        pid = client.post(
            "/api/projects",
            json={"name": "Save Proj", "project_mode": "local_folder", "local_root_path": str(root)},
        ).json()["id"]

        # Read-only browse/compare/stat must never alter disk hashes
        p_md = client.post(f"/api/projects/{pid}/local/preview", json={"rel_path": "draft.md"}).json()
        p_tex = client.post(f"/api/projects/{pid}/local/preview", json={"rel_path": "paper.tex"}).json()
        p_docx = client.post(f"/api/projects/{pid}/local/preview", json={"rel_path": "report.docx"}).json()
        client.post(f"/api/projects/{pid}/local/compare", json={"old_rel_path": "draft.md", "new_rel_path": "paper.tex"})

        assert hashlib.sha256(md_p.read_bytes()).hexdigest() == orig_md_sha
        assert hashlib.sha256(tex_p.read_bytes()).hexdigest() == orig_tex_sha
        assert hashlib.sha256(docx_p.read_bytes()).hexdigest() == orig_docx_sha

        # 1. Default mode="save_as" on Markdown -> creates draft_revised.md & keeps draft.md untouched!
        md_para = [b for b in p_md["blocks"] if b["block_type"] == "paragraph"][0]
        r_save_as = client.post(
            f"/api/projects/{pid}/local/save-edits",
            json={
                "rel_path": "draft.md",
                "mode": "save_as",
                "patches": [{"op": "replace_block", "block_index": md_para["index"], "new_raw": "Revised markdown sentence."}],
            },
        )
        assert r_save_as.status_code == 200, r_save_as.text
        j_sa = r_save_as.json()
        assert j_sa["saved"] is True and j_sa["target_rel_path"] == "draft_revised.md"
        assert hashlib.sha256(md_p.read_bytes()).hexdigest() == orig_md_sha
        assert "Revised markdown sentence." in (root / "draft_revised.md").read_text(encoding="utf-8")

        # Second save_as auto-increments to draft_revised_2.md without clobbering
        r_save_as2 = client.post(
            f"/api/projects/{pid}/local/save-edits",
            json={
                "rel_path": "draft.md",
                "mode": "save_as",
                "patches": [{"op": "replace_block", "block_index": md_para["index"], "new_raw": "Revised markdown v2."}],
            },
        )
        assert r_save_as2.status_code == 200 and r_save_as2.json()["target_rel_path"] == "draft_revised_2.md"

        # 2. Explicit mode="overwrite" on LaTeX -> creates .paperdiff.bak backup matching original + atomically replaces paper.tex
        tex_para = [b for b in p_tex["blocks"] if b["block_type"] == "paragraph"][0]
        r_over = client.post(
            f"/api/projects/{pid}/local/save-edits",
            json={
                "rel_path": "paper.tex",
                "mode": "overwrite",
                "expected_sha256": orig_tex_sha,
                "patches": [{"op": "replace_block", "block_index": tex_para["index"], "new_raw": "Overwritten LaTeX sentence."}],
            },
        )
        assert r_over.status_code == 200, r_over.text
        j_ov = r_over.json()
        assert j_ov["saved"] is True and j_ov["target_rel_path"] == "paper.tex"
        assert j_ov["backup_rel_path"] and (root / j_ov["backup_rel_path"]).read_bytes() == orig_tex_bytes
        assert "Overwritten LaTeX sentence." in tex_p.read_text(encoding="utf-8")
        assert r"\section{Intro}" in tex_p.read_text(encoding="utf-8")

        # 3. save_as on .docx preserves valid Word XML via docx_patcher and leaves report.docx untouched
        docx_para = [b for b in p_docx["blocks"] if "Initial Word sentence" in b["clean_text"]][0]
        r_docx_sa = client.post(
            f"/api/projects/{pid}/local/save-edits",
            json={
                "rel_path": "report.docx",
                "mode": "save_as",
                "patches": [{"op": "replace_block", "block_index": docx_para["index"], "new_raw": "Revised Word sentence."}],
            },
        )
        assert r_docx_sa.status_code == 200, r_docx_sa.text
        assert r_docx_sa.json()["target_rel_path"] == "report_revised.docx"
        assert hashlib.sha256(docx_p.read_bytes()).hexdigest() == orig_docx_sha
        p_docx_rev = client.post(f"/api/projects/{pid}/local/preview", json={"rel_path": "report_revised.docx"}).json()
        assert any("Revised Word sentence." in b["clean_text"] for b in p_docx_rev["blocks"])

        # 4. Sandbox guard on target_rel_path prevents writing outside root
        r_escape = client.post(
            f"/api/projects/{pid}/local/save-edits",
            json={"rel_path": "draft.md", "mode": "save_as", "target_rel_path": "../escape.md", "paragraph_edits": {}},
        )
        assert r_escape.status_code == 403 and r_escape.json()["code"] == "PATH_OUTSIDE_ROOT"


def test_w2_t10_fault_isolation_missing_unreadable_corrupted_and_bad_encoding(tmp_path: Path, monkeypatch) -> None:
    """W2-T10: Missing root, unreadable permission, corrupted .docx, and non-UTF8 .tex isolate cleanly without affecting sibling projects."""
    import os
    import shutil
    from fastapi.testclient import TestClient

    from backend.main import app

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "w2_t10.db")
    database.init_db()

    good_dir = tmp_path / "good_proj"
    good_dir.mkdir()
    (good_dir / "ok.md").write_text("# Healthy\n\nAll good.\n", encoding="utf-8")

    fault_dir = tmp_path / "fault_proj"
    fault_dir.mkdir()
    corrupt_docx = fault_dir / "broken.docx"
    corrupt_docx.write_bytes(b"NOT_A_VALID_ZIP_FILE_AT_ALL")
    bad_enc_tex = fault_dir / "gbk_bad.tex"
    bad_enc_tex.write_bytes(b"\\section{Test}\n\nValid prefix " + b"\xff\xfe\x80\x81" + b" suffix.\n")
    no_perm = fault_dir / "secret_noperm.md"
    no_perm.write_text("# Locked\n", encoding="utf-8")

    missing_dir = tmp_path / "will_vanish"
    missing_dir.mkdir()
    (missing_dir / "a.md").write_text("# Gone\n", encoding="utf-8")

    try:
        with TestClient(app) as client:
            pid_good = client.post(
                "/api/projects",
                json={"name": "Healthy Proj", "project_mode": "local_folder", "local_root_path": str(good_dir)},
            ).json()["id"]
            pid_fault = client.post(
                "/api/projects",
                json={"name": "Fault Proj", "project_mode": "local_folder", "local_root_path": str(fault_dir)},
            ).json()["id"]
            pid_miss = client.post(
                "/api/projects",
                json={"name": "Missing Proj", "project_mode": "local_folder", "local_root_path": str(missing_dir)},
            ).json()["id"]

            # 1. Remove missing_dir -> GET /api/projects still returns 200, missing proj flagged 'missing', good proj unaffected
            shutil.rmtree(missing_dir)
            projs = client.get("/api/projects").json()
            by_id = {p["id"]: p for p in projs}
            assert by_id[pid_good]["local_status"] == "ok"
            assert by_id[pid_miss]["local_status"] == "missing"

            r_miss_tree = client.get(f"/api/projects/{pid_miss}/local/tree")
            assert r_miss_tree.status_code == 404 and r_miss_tree.json()["code"] == "ROOT_MISSING"

            # 2. Corrupted .docx returns 422 FILE_CORRUPTED
            r_corrupt = client.post(f"/api/projects/{pid_fault}/local/preview", json={"rel_path": "broken.docx"})
            assert r_corrupt.status_code == 422 and r_corrupt.json()["code"] == "FILE_CORRUPTED"

            # 3. Non-UTF-8 bad bytes decode gracefully with encoding_warning (never crashes!)
            r_bad_enc = client.post(f"/api/projects/{pid_fault}/local/preview", json={"rel_path": "gbk_bad.tex"})
            assert r_bad_enc.status_code == 200
            assert r_bad_enc.json().get("encoding_warning")

            # 4. Unreadable file permission returns 403 FILE_UNREADABLE (skipped only if running as root)
            if os.geteuid() != 0:
                os.chmod(no_perm, 0o000)
                r_noperm = client.post(f"/api/projects/{pid_fault}/local/preview", json={"rel_path": "secret_noperm.md"})
                assert r_noperm.status_code == 403 and r_noperm.json()["code"] == "FILE_UNREADABLE"

            # Sibling healthy project remains 100% readable
            r_good = client.post(f"/api/projects/{pid_good}/local/preview", json={"rel_path": "ok.md"})
            assert r_good.status_code == 200
    finally:
        if no_perm.exists():
            os.chmod(no_perm, 0o644)


def test_w2_t12_t13_t14_t15_browser_local_workspace_e2e(tmp_path: Path) -> None:
    """W2-T12/T13/T14/T15: Real Headless Chrome CDP E2E for local folder binding, file tree, D-04 3rd-file cap, D-06 conflict guard, D-05 save modal, 3-theme contrast & missing-dir recovery."""
    import hashlib
    import json
    import shutil
    import subprocess
    import tempfile
    import threading
    import time
    import urllib.request
    import uvicorn

    from backend.export import find_local_chrome
    from backend.main import app
    from tests.test_performance_benchmark import _MiniCDP, _find_free_port

    chrome = find_local_chrome()
    assert chrome, "Local Chrome/Chromium required for real browser W2 E2E verification"

    root = tmp_path / "w2_e2e_paper"
    (root / "figures").mkdir(parents=True)
    (root / "figures" / "fig1.png").write_bytes(_tiny_png_bytes())
    (root / "refs.bib").write_text(
        "@inproceedings{dao2022, author={Dao, T.}, title={FlashAttention}, year={2022}}\n",
        encoding="utf-8",
    )
    (root / "noise.aux").write_text("aux noise", encoding="utf-8")
    (root / ".DS_Store").write_bytes(b"\x00")
    (root / "v1.tex").write_text(
        r"""\documentclass{article}
\begin{document}
\section{引言}
长上下文稀疏路由在基准测试中的相对误差约为 14.2\%，具体机制参见 \cite{dao2022}。
\begin{figure}
\includegraphics{figures/fig1.png}
\caption{推理延迟分布图}
\end{figure}
\end{document}
""",
        encoding="utf-8",
    )
    (root / "v2.tex").write_text(
        r"""\documentclass{article}
\begin{document}
\section{引言}
长上下文稀疏路由在基准测试中的相对误差变为 21.6\%，具体机制参见 \cite{dao2022}。
\end{document}
""",
        encoding="utf-8",
    )
    notes_p = root / "notes.md"
    notes_p.write_text("# 研究笔记\n\n初始本地 Markdown 正文内容。\n", encoding="utf-8")
    tracked_p = root / "tracked.docx"
    tracked_p.write_bytes(_make_docx_bytes(["Methods"], tracked=True))
    tracked_sha = hashlib.sha256(tracked_p.read_bytes()).hexdigest()

    port = _find_free_port()
    cdp_port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    srv_thread = threading.Thread(target=server.run, daemon=True)
    srv_thread.start()
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"{base_url}/api/health", timeout=1.0) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(0.15)

    created_proj_id: int | None = None
    chrome_proc = None
    cdp = None
    user_dir = tempfile.mkdtemp(prefix="pd_w2_cdp_")

    try:
        chrome_proc = subprocess.Popen(
            [
                chrome,
                "--headless=new",
                f"--remote-debugging-port={cdp_port}",
                f"--user-data-dir={user_dir}",
                "--window-size=1440,900",
                "--no-first-run",
                "--disable-default-apps",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ws_url = None
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json", timeout=1.0) as r:
                    tabs = json.loads(r.read().decode("utf-8"))
                    if tabs and tabs[0].get("webSocketDebuggerUrl"):
                        ws_url = tabs[0]["webSocketDebuggerUrl"]
                        break
            except Exception:
                time.sleep(0.15)
        assert ws_url, "Chrome CDP failed to start"

        cdp = _MiniCDP(ws_url)
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")
        cdp.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1440, "height": 900, "deviceScaleFactor": 2, "mobile": False},
        )
        cdp.send("Page.navigate", {"url": base_url})
        time.sleep(1.3)

        # W2-T12: Create a local_folder bound project directly through the NewProjectModal UI
        created_res = cdp.eval_js(
            f"""
            (async () => {{
              const wait = (ms) => new Promise(r => setTimeout(r, ms));
              const setInput = (el, val) => {{
                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                setter.call(el, val);
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
              }};
              const newBtn = Array.from(document.querySelectorAll('button')).find(
                b => b.textContent && b.textContent.includes('新建项目')
              );
              if (!newBtn) return {{ ok: false, err: 'no newBtn' }};
              newBtn.click();
              await wait(200);
              document.querySelector('[data-new-proj-mode="local_folder"]')?.click();
              await wait(150);
              const pathInput = document.querySelector('[data-local-folder-input="true"]');
              if (!pathInput) return {{ ok: false, err: 'no pathInput' }};
              setInput(pathInput, {json.dumps(str(root))});
              await wait(100);
              document.querySelector('[data-local-validate-btn="true"]')?.click();
              for (let i = 0; i < 30; i++) {{
                if (document.querySelector('[data-local-folder-validation="valid"]')) break;
                await wait(100);
              }}
              const valText = document.querySelector('[data-local-folder-validation="valid"]')?.textContent || '';
              const nameInput = document.querySelector('[data-new-proj-name="true"]');
              setInput(nameInput, '__W2_CHROME_LOCAL__');
              await wait(100);
              const submitBtn = Array.from(document.querySelectorAll('button[type="submit"]')).find(
                b => b.textContent && b.textContent.includes('创建项目')
              );
              submitBtn?.click();
              for (let i = 0; i < 50; i++) {{
                if (document.querySelector('[data-local-sidebar="true"]') && document.querySelectorAll('[data-local-file]').length >= 4) break;
                await wait(100);
              }}
              await wait(250);
              return {{
                ok: Boolean(document.querySelector('[data-local-sidebar="true"]')),
                valText,
                fileCount: document.querySelectorAll('[data-local-file]').length,
              }};
            }})()
            """
        )
        assert created_res["ok"] and "4" in created_res["valText"] and created_res["fileCount"] == 4, created_res

        # Record project ID for cleanup safety
        with urllib.request.urlopen(f"{base_url}/api/projects", timeout=5.0) as r:
            projs_now = json.loads(r.read().decode("utf-8"))
            hit = [p for p in projs_now if p["name"] == "__W2_CHROME_LOCAL__"]
            assert hit, "Created local project not found in /api/projects"
            created_proj_id = int(hit[0]["id"])

        # W2-T13: Tree filtering, aux toggle, direct read .tex (figure + W1 2em indent), .docx Word Original & tracked split
        t13 = cdp.eval_js(
            """
            (async () => {
              const wait = (ms) => new Promise(r => setTimeout(r, ms));
              const setInput = (el, val) => {
                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                setter.call(el, val);
                el.dispatchEvent(new Event('input', { bubbles: true }));
              };

              const initialFiles = Array.from(document.querySelectorAll('[data-local-file]')).map(
                el => el.getAttribute('data-local-file')
              );

              // Toggle aux files ON -> refs.bib & figures/fig1.png appear
              const auxBox = document.querySelector('[data-local-tree-aux="true"]');
              auxBox?.click();
              for (let i = 0; i < 30; i++) {
                if (document.querySelector('[data-local-file="refs.bib"]')) break;
                await wait(100);
              }
              const withAux = Array.from(document.querySelectorAll('[data-local-file]')).map(
                el => el.getAttribute('data-local-file')
              );
              // Toggle aux OFF
              auxBox?.click();
              await wait(250);

              // Search filter test
              const searchInput = document.querySelector('[data-local-tree-search="true"]');
              setInput(searchInput, 'tracked');
              await wait(150);
              const searchMatches = Array.from(document.querySelectorAll('[data-local-file]')).map(
                el => el.getAttribute('data-local-file')
              );
              setInput(searchInput, '');
              await wait(150);

              // Click v1.tex -> check relative figure img + W1 Chinese 2em indent
              document.querySelector('[data-local-file="v1.tex"] button')?.click();
              for (let i = 0; i < 40; i++) {
                if (document.body.innerText.includes('相对误差约为')) break;
                await wait(100);
              }
              await wait(200);
              const hasAssetImg = Boolean(document.querySelector('img[src^="/api/assets/"]'));
              const texP = Array.from(document.querySelectorAll('p')).find(
                el => el.textContent && el.textContent.includes('相对误差约为')
              );
              const texIndentPx = texP ? parseFloat(getComputedStyle(texP).textIndent) : -1;

              // Click tracked.docx -> verify Word Original button + tracked changes banner -> click split
              document.querySelector('[data-local-file="tracked.docx"] button')?.click();
              for (let i = 0; i < 40; i++) {
                if (document.querySelector('[data-local-split-tracked="true"]')) break;
                await wait(100);
              }
              const hasWordOrigBtn = Array.from(document.querySelectorAll('button')).some(
                b => b.textContent && b.textContent.trim() === 'Word 原版'
              );
              document.querySelector('[data-local-split-tracked="true"]')?.click();
              for (let i = 0; i < 40; i++) {
                if (document.querySelector('[data-diff-pane="left"]') && document.body.innerText.includes('18.6%')) break;
                await wait(100);
              }
              const splitHasBoth = document.body.innerText.includes('14.2%') && document.body.innerText.includes('18.6%');

              return {
                initialFiles,
                withAux,
                searchMatches,
                hasAssetImg,
                texIndentPx,
                hasWordOrigBtn,
                splitHasBoth,
              };
            })()
            """
        )
        assert "noise.aux" not in t13["initialFiles"] and "refs.bib" not in t13["initialFiles"], t13
        assert "refs.bib" in t13["withAux"] and "figures/fig1.png" in t13["withAux"], t13
        assert t13["searchMatches"] == ["tracked.docx"], t13
        assert t13["hasAssetImg"] and t13["texIndentPx"] >= 28.0, t13
        assert t13["hasWordOrigBtn"] and t13["splitHasBoth"], t13
        assert hashlib.sha256(tracked_p.read_bytes()).hexdigest() == tracked_sha

        # W2-T14 part 1: Strict D-04 2-file cap (3rd file intercepted!) + Pairwise Diff + A<->B swap
        t14_pair = cdp.eval_js(
            """
            (async () => {
              const wait = (ms) => new Promise(r => setTimeout(r, ms));
              document.querySelector('[data-local-pick="v1.tex"]')?.click();
              await wait(80);
              document.querySelector('[data-local-pick="v2.tex"]')?.click();
              await wait(80);
              // Click 3rd file -> MUST trigger limit banner & keep count at 2/2!
              document.querySelector('[data-local-pick="notes.md"]')?.click();
              await wait(120);
              const bannerText = document.querySelector('[data-pair-limit-banner="true"]')?.textContent || '';
              const btnTextBefore = document.querySelector('[data-local-compare-btn="true"]')?.textContent || '';

              // Test replace B then restore v2.tex
              document.querySelector('[data-pair-replace="1"]')?.click();
              await wait(100);
              document.querySelector('[data-local-pick="v2.tex"]')?.click();
              await wait(100);
              document.querySelector('[data-pair-replace="1"]')?.click();
              await wait(100);

              document.querySelector('[data-local-compare-btn="true"]')?.click();
              for (let i = 0; i < 50; i++) {
                if (document.querySelector('[data-local-diff-swap="true"]') && document.body.innerText.includes('21.6%')) break;
                await wait(100);
              }
              const oldBefore = document.querySelector('[data-local-diff-old-select="true"]')?.value;
              const newBefore = document.querySelector('[data-local-diff-new-select="true"]')?.value;
              document.querySelector('[data-local-diff-swap="true"]')?.click();
              for (let i = 0; i < 40; i++) {
                if (document.querySelector('[data-local-diff-old-select="true"]')?.value === 'v2.tex') break;
                await wait(100);
              }
              const oldAfter = document.querySelector('[data-local-diff-old-select="true"]')?.value;
              const newAfter = document.querySelector('[data-local-diff-new-select="true"]')?.value;
              return { bannerText, btnTextBefore, oldBefore, newBefore, oldAfter, newAfter };
            })()
            """
        )
        assert "当前仅支持选择 2 个文件两两对比" in t14_pair["bannerText"], t14_pair
        assert "2/2" in t14_pair["btnTextBefore"], t14_pair
        assert (t14_pair["oldBefore"], t14_pair["newBefore"]) == ("v1.tex", "v2.tex"), t14_pair
        assert (t14_pair["oldAfter"], t14_pair["newAfter"]) == ("v2.tex", "v1.tex"), t14_pair

        # W2-T14 part 2: Open notes.md -> external edit + focus refresh banner -> Draft Dock edit + external edit conflict modal -> D-05 save_as modal
        cdp.eval_js(
            """
            (async () => {
              const wait = (ms) => new Promise(r => setTimeout(r, ms));
              document.querySelector('[data-local-file="notes.md"] button')?.click();
              for (let i = 0; i < 40; i++) {
                if (document.body.innerText.includes('初始本地 Markdown 正文内容')) break;
                await wait(100);
              }
            })()
            """
        )
        # External edit #1 (no unsaved drafts) -> window focus triggers top reload banner
        notes_p.write_text("# 研究笔记\n\n外部 AI 第一次更新后的正文内容。\n", encoding="utf-8")
        time.sleep(1.6)
        ext1 = cdp.eval_js(
            """
            (async () => {
              const wait = (ms) => new Promise(r => setTimeout(r, ms));
              window.dispatchEvent(new Event('focus'));
              for (let i = 0; i < 40; i++) {
                if (document.querySelector('[data-external-update-banner="true"]')) break;
                await wait(100);
              }
              const sawBanner = Boolean(document.querySelector('[data-external-update-banner="true"]'));
              document.querySelector('[data-reload-external="true"]')?.click();
              for (let i = 0; i < 40; i++) {
                if (document.body.innerText.includes('外部 AI 第一次更新后的正文内容')) break;
                await wait(100);
              }
              return { sawBanner, reloaded: document.body.innerText.includes('外部 AI 第一次更新后的正文内容') };
            })()
            """
        )
        assert ext1["sawBanner"] and ext1["reloaded"], ext1

        # Create an unsaved Draft Dock edit via double-click on the paragraph
        staged = cdp.eval_js(
            """
            (async () => {
              const wait = (ms) => new Promise(r => setTimeout(r, ms));
              const setTa = (el, val) => {
                const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                setter.call(el, val);
                el.dispatchEvent(new Event('input', { bubbles: true }));
              };
              const p = Array.from(document.querySelectorAll('p')).find(
                el => el.textContent && el.textContent.includes('外部 AI 第一次更新后的正文内容')
              );
              p?.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
              await wait(150);
              const ta = document.querySelector('textarea');
              if (!ta) return { ok: false };
              setTa(ta, '用户在阅读器内原位微调后的新内容。');
              await wait(80);
              const stageBtn = Array.from(document.querySelectorAll('button')).find(
                b => b.textContent && b.textContent.includes('暂存微调')
              );
              stageBtn?.click();
              await wait(150);
              return { ok: Boolean(document.querySelector('[data-draft-save-btn="true"]')) };
            })()
            """
        )
        assert staged["ok"], staged

        # External edit #2 while Draft Dock has unsaved edits -> manual refresh MUST open conflict modal!
        notes_p.write_text("# 研究笔记\n\n外部 AI 第二次并发写入内容。\n", encoding="utf-8")
        notes_sha_before_save = hashlib.sha256(notes_p.read_bytes()).hexdigest()
        conflict_and_save = cdp.eval_js(
            """
            (async () => {
              const wait = (ms) => new Promise(r => setTimeout(r, ms));
              document.querySelector('[data-local-refresh="true"]')?.click();
              for (let i = 0; i < 40; i++) {
                if (document.querySelector('[data-external-conflict-modal="true"]')) break;
                await wait(100);
              }
              const sawConflict = Boolean(document.querySelector('[data-external-conflict-modal="true"]'));
              document.querySelector('[data-conflict-keep="true"]')?.click();
              await wait(150);
              const keptDraft = Boolean(document.querySelector('[data-draft-save-btn="true"]'));

              // Open D-05 Save Local Edits modal -> default save_as checked -> save
              document.querySelector('[data-draft-save-btn="true"]')?.click();
              await wait(150);
              const defaultSaveAsChecked = Boolean(document.querySelector('[data-save-mode="save_as"]')?.checked);
              document.querySelector('[data-save-local-confirm="true"]')?.click();
              for (let i = 0; i < 50; i++) {
                if (document.querySelector('[data-local-file="notes_revised.md"]')) break;
                await wait(100);
              }
              return {
                sawConflict,
                keptDraft,
                defaultSaveAsChecked,
                revisedInTree: Boolean(document.querySelector('[data-local-file="notes_revised.md"]')),
              };
            })()
            """
        )
        assert conflict_and_save["sawConflict"] and conflict_and_save["keptDraft"], conflict_and_save
        assert conflict_and_save["defaultSaveAsChecked"] and conflict_and_save["revisedInTree"], conflict_and_save
        assert hashlib.sha256(notes_p.read_bytes()).hexdigest() == notes_sha_before_save
        assert "用户在阅读器内原位微调后的新内容" in (root / "notes_revised.md").read_text(encoding="utf-8")

        # W2-T15: Light / Sepia / Dark three-theme WCAG contrast check on LocalFileTreeSidebar
        theme_check = cdp.eval_js(
            """
            (() => {
              const parseRgb = (s) => {
                const m = s.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
                return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : [255, 255, 255];
              };
              const lum = ([r, g, b]) => {
                const f = (c) => {
                  const x = c / 255;
                  return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
                };
                return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
              };
              const contrast = (c1, c2) => {
                const l1 = lum(c1), l2 = lum(c2);
                return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
              };
              const sb = document.querySelector('.pd-local-sidebar');
              const orig = document.documentElement.getAttribute('data-theme') || 'light';
              const res = {};
              for (const t of ['light', 'sepia', 'dark']) {
                document.documentElement.setAttribute('data-theme', t);
                const bg = parseRgb(getComputedStyle(sb).backgroundColor);
                const fg = parseRgb(getComputedStyle(sb).color);
                res[t] = Math.round(contrast(bg, fg) * 100) / 100;
              }
              document.documentElement.setAttribute('data-theme', orig);
              return res;
            })()
            """
        )
        for t, ratio in theme_check.items():
            assert ratio >= 4.5, f"Sidebar WCAG contrast < 4.5 in {t}: {theme_check}"

        # W2-T14 part 3: Missing folder recovery card + non-destructive project removal (AC-08 / AC-18)
        moved_root = tmp_path / "w2_e2e_moved_away"
        shutil.move(str(root), str(moved_root))
        recovery = cdp.eval_js(
            """
            (async () => {
              const wait = (ms) => new Promise(r => setTimeout(r, ms));
              document.querySelector('[data-local-refresh="true"]')?.click();
              for (let i = 0; i < 40; i++) {
                if (document.querySelector('[data-local-recovery-card="true"]')) break;
                await wait(100);
              }
              const sawRecovery = Boolean(document.querySelector('[data-local-recovery-card="true"]'));
              document.querySelector('[data-local-settings="true"]')?.click();
              await wait(150);
              const modalText = document.querySelector('[data-local-binding-modal="true"]')?.textContent || '';
              document.querySelector('[data-delete-local-project-btn="true"]')?.click();
              await wait(300);
              return { sawRecovery, modalText };
            })()
            """
        )
        assert recovery["sawRecovery"], recovery
        assert "绝不删除或修改您磁盘上的任何原文件" in recovery["modalText"], recovery
        # Project record removed from SQLite while moved folder on disk stays 100% intact
        created_proj_id = None
        assert (moved_root / "v1.tex").exists() and (moved_root / "notes_revised.md").exists()

    finally:
        if cdp:
            cdp.close()
        if chrome_proc:
            chrome_proc.terminate()
            try:
                chrome_proc.wait(timeout=3)
            except Exception:
                chrome_proc.kill()
        if created_proj_id:
            try:
                req = urllib.request.Request(f"{base_url}/api/projects/{created_proj_id}", method="DELETE")
                urllib.request.urlopen(req, timeout=5.0)
            except Exception:
                pass
        shutil.rmtree(user_dir, ignore_errors=True)
        server.should_exit = True
        srv_thread.join(timeout=3)





