"""FastAPI local backend service for 对稿 · PaperDiff Studio (v0.1.0).

This module exposes the 100% local-first REST API bound to `127.0.0.1` and serves
the compiled React SPA (`frontend/dist`) in both desktop (`pywebview`) and browser modes.

Route groups:
    - Health & Settings: `/api/health`, `/api/settings/ai-lexicon`
    - 3-Tier Workspace CRUD: `/api/projects`, `/api/documents`, `/api/versions`
    - Binary Archive & Media: `/api/assets/{asset_key}`, `/api/versions/{version_id}/source-blob`
    - Word Track Changes Split Import: `/inspect-docx`, `/import-tracked-docx`
    - Single-Doc Preview, Compare & Ack Persistence: `/preview`, `/compare`, `/decisions`, `/acks`
    - Round-Trip Typed Patching & Publication Export: `/apply-patches`, `/api/export`

Architectural invariants:
    - Zero external network calls or telemetry; all state resides in `DATA_DIR`.
    - Startup calls `init_db()` (idempotent Schema v1.1 migration) and seeds the demo project once.
"""
from __future__ import annotations

import hmac
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .assets import get_asset_path, get_blob_path, save_blob_bytes
from .analyzer import (
    DEFAULT_EN_AI_PHRASES,
    DEFAULT_EN_AI_WORDS,
    DEFAULT_ZH_AI_CLICHES,
    compare_documents,
    extract_ai_isms,
    preview_document,
)
from .database import (
    create_document,
    create_project,
    create_version,
    delete_document,
    delete_project,
    delete_version,
    get_ai_lexicon_settings,
    get_alert_acks,
    get_document,
    get_local_pair_state,
    get_merge_decisions,
    get_project,
    get_version,
    init_db,
    list_documents,
    list_projects,
    list_versions,
    list_versions_by_document,
    save_ai_lexicon_settings,
    save_alert_acks,
    save_local_pair_state,
    save_merge_decisions,
    update_document,
    update_project,
    update_version,
)
from .local_workspace import (
    LocalWorkspaceError,
    normalize_user_path,
    probe_root_summary,
    read_local_file_for_analysis,
    read_local_raw_file,
    resolve_open_path_target,
    save_local_file_edits,
    scan_local_tree,
    stat_local_files,
    validate_root_dir,
)
from .diff_engine import count_academic_words
from .export import (
    apply_single_document_edits,
    export_docx_merged_bytes,
    export_docx_tracked_bytes,
    export_html_report,
    export_latexdiff_tex,
    export_markdown_summary,
    export_merged_document,
    export_single_html_report,
    render_diff_print_html,
    render_html_to_pdf_bytes,
    render_single_print_html,
)
from .parsers import (
    detect_format,
    extract_docx_with_assets,
    extract_latex_zip_with_assets,
    inspect_docx_tracked_changes,
    parse_document,
)
from .patcher import apply_typed_patches
from .runtime_state import (
    APP_VERSION,
    get_runtime_context,
    trigger_shutdown_callback,
)
from .sample_data import seed_demo_data_if_empty

app = FastAPI(title="对稿 · PaperDiff API", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    seed_demo_data_if_empty()


@app.exception_handler(LocalWorkspaceError)
async def _handle_local_workspace_error(_request: Request, exc: LocalWorkspaceError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "detail": exc.detail})


class FolderValidatePayload(BaseModel):
    path: str


class FolderPickPayload(BaseModel):
    initial_dir: str | None = None


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    category: str = "paper"  # paper | grant | report | other
    status: str = "polishing"  # drafting | polishing | revising | done | archived
    primary_format: str = "latex"
    protected_terms: list[str] = Field(default_factory=list)
    default_doc_name: str | None = None
    project_mode: str = "managed"  # managed | local_folder
    local_root_path: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    status: str | None = None
    pinned: bool | None = None
    protected_terms: list[str] | None = None
    project_mode: str | None = None
    local_root_path: str | None = None


class DocumentCreate(BaseModel):
    name: str
    doc_type: str = "manuscript"  # manuscript | si | rebuttal | proposal | report | other
    primary_format: str = "latex"
    notes: str = ""


class DocumentUpdate(BaseModel):
    name: str | None = None
    doc_type: str | None = None
    primary_format: str | None = None
    notes: str | None = None


class VersionCreateJSON(BaseModel):
    label: str = ""
    source_tag: str = "AI润色"
    filename: str = "manuscript.tex"
    format: str = "auto"
    content: str
    notes: str = ""
    is_milestone: bool = False


class VersionUpdate(BaseModel):
    label: str | None = None
    source_tag: str | None = None
    notes: str | None = None
    is_milestone: bool | None = None


class QuickCompareRequest(BaseModel):
    old_content: str
    new_content: str
    old_format: str = "auto"
    new_format: str = "auto"
    old_label: str = "旧版本"
    new_label: str = "新版本"
    old_meta: dict[str, Any] = Field(default_factory=dict)
    new_meta: dict[str, Any] = Field(default_factory=dict)
    protected_terms: list[str] = Field(default_factory=list)


class MergeDecisionPayload(BaseModel):
    old_version_id: int
    new_version_id: int
    decisions: dict[str, str]


class SaveMergedVersionPayload(BaseModel):
    old_version_id: int
    new_version_id: int
    decisions: dict[str, str] = Field(default_factory=dict)
    paragraph_edits: dict[int, str] = Field(default_factory=dict)
    label: str = ""
    source_tag: str = "人工修复"
    notes: str = ""
    is_milestone: bool = False


class QuickPreviewRequest(BaseModel):
    content: str
    format: str = "auto"
    label: str = "快速预览文稿"
    filename: str = "manuscript.tex"
    meta: dict[str, Any] = Field(default_factory=dict)
    protected_terms: list[str] = Field(default_factory=list)


class SaveSingleVersionPayload(BaseModel):
    base_version_id: int
    paragraph_edits: dict[int, str] = Field(default_factory=dict)
    label: str = ""
    source_tag: str = "人工修复"
    notes: str = ""
    is_milestone: bool = False


class AiLexiconPayload(BaseModel):
    added_en: list[str] = Field(default_factory=list)
    added_zh: list[str] = Field(default_factory=list)
    muted: list[str] = Field(default_factory=list)


class AlertAckPayload(BaseModel):
    old_version_id: int
    new_version_id: int
    acked_ids: list[str] = Field(default_factory=list)


class ApplyPatchesPayload(BaseModel):
    base_version_id: int
    patches: list[dict[str, Any]] = Field(default_factory=list)
    label: str = ""
    source_tag: str = "人工修复"
    notes: str = ""
    is_milestone: bool = False
    docx_mode: str = "clean"  # clean | tracked


class ExportPayload(BaseModel):
    old_version_id: int | None = None
    new_version_id: int | None = None
    old_content: str | None = None
    new_content: str | None = None
    version_id: int | None = None
    single_content: str | None = None
    single_meta: dict[str, Any] = Field(default_factory=dict)
    single_label: str = "当前文稿"
    old_label: str = "旧版本"
    new_label: str = "新版本"
    project_name: str = "Quick Compare"
    export_type: str = "merged"  # merged | html | single_html | single_source | latexdiff | markdown | docx_tracked | docx_merged | pdf_diff_report | pdf_diff_compact | pdf_single | print_html_diff | print_html_diff_compact | print_html_single | docx_patched | docx_tracked_preserved | latex_zip_patched
    view_mode: str = "split"  # split | inline
    decisions: dict[str, str] = Field(default_factory=dict)
    paragraph_edits: dict[int, str] = Field(default_factory=dict)
    patches: list[dict[str, Any]] = Field(default_factory=list)
    protected_terms: list[str] = Field(default_factory=list)
    commentary_note: str = ""
    landscape: bool = False
    docx_mode: str = "clean"
    typography_prefs: dict[str, Any] | None = None
    local_project_id: int | None = None
    local_rel_path: str | None = None
    local_old_rel_path: str | None = None
    local_new_rel_path: str | None = None


class LocalPreviewPayload(BaseModel):
    rel_path: str


class LocalComparePayload(BaseModel):
    old_rel_path: str | None = None
    new_rel_path: str | None = None
    rel_path: str | None = None
    docx_tracked_split: bool = False


class LocalPairStatePayload(BaseModel):
    old_rel_path: str
    new_rel_path: str
    acked_ids: list[str] | None = None
    decisions: dict[str, str] | None = None


class LocalSaveEditsPayload(BaseModel):
    rel_path: str
    patches: list[dict[str, Any]] = Field(default_factory=list)
    paragraph_edits: dict[int, str] = Field(default_factory=dict)
    mode: str = "save_as"  # save_as | overwrite
    target_rel_path: str | None = None
    expected_sha256: str | None = None
    force: bool = False
    docx_mode: str = "clean"


def _decode_uploaded_file(filename: str, raw_bytes: bytes) -> tuple[str, str, str, dict[str, Any]]:
    low = filename.lower()
    if low.endswith(".docx"):
        text, meta = extract_docx_with_assets(raw_bytes)
        return filename, "docx", text, meta
    if low.endswith(".zip"):
        root_name, expanded, meta = extract_latex_zip_with_assets(raw_bytes)
        return f"{filename} ({root_name})", "latex", expanded, meta
    text = raw_bytes.decode("utf-8", errors="replace")
    fmt = detect_format(filename, text)
    return filename, fmt, text, {"assets": {}, "bib": {}}


def _compute_version_stats(content: str, fmt: str, filename: str) -> tuple[str, int, int, int]:
    det_fmt, blocks = parse_document(content, fmt, filename)
    clean_full = "\n\n".join(b.clean_text for b in blocks if b.block_type not in ("heading", "table"))
    wc = count_academic_words(clean_full)
    pc = sum(1 for b in blocks if b.block_type != "heading")
    ai_cnt = len(extract_ai_isms(clean_full, get_ai_lexicon_settings()))
    return det_fmt, wc, pc, ai_cnt


@app.get("/api/health")
def health() -> dict[str, Any]:
    ctx = get_runtime_context()
    return {
        "status": "ok",
        "app": "对稿 · PaperDiff",
        "version": APP_VERSION,
        "pid": int(ctx.get("pid") or os.getpid()),
        "port": int(ctx.get("port") or 0),
        "data_dir": str(ctx.get("data_dir") or ""),
        "log_path": str(ctx.get("log_path") or ""),
        "launch_mode": str(ctx.get("launch_mode") or "test"),
        "can_shutdown": bool(ctx.get("can_shutdown", False)),
    }


def _is_loopback_client(request: Request) -> bool:
    client_host = (request.client.host if request.client else "").strip().lower()
    return client_host in {"127.0.0.1", "::1", "localhost", "testclient"}


def _is_same_origin_loopback(request: Request) -> bool:
    host_header = (request.headers.get("host") or "").strip().lower()
    if not host_header:
        return False
    source = (request.headers.get("origin") or request.headers.get("referer") or "").strip()
    if not source:
        return False
    parsed = urlparse(source)
    if parsed.scheme != "http":
        return False
    if (parsed.hostname or "").lower() not in {"127.0.0.1", "localhost"}:
        return False
    return parsed.netloc.lower() == host_header


@app.post("/api/runtime/shutdown")
def api_runtime_shutdown(request: Request) -> dict[str, Any]:
    if not _is_loopback_client(request):
        raise HTTPException(status_code=403, detail="仅允许本机回环地址触发停止服务")

    ctx = get_runtime_context()
    expected_token = str(ctx.get("instance_token") or "")
    provided_token = (request.headers.get("x-paperdiff-token") or "").strip()
    client_marker = (request.headers.get("x-paperdiff-client") or "").strip().lower()

    token_ok = bool(expected_token and provided_token and hmac.compare_digest(expected_token, provided_token))
    web_ui_ok = client_marker == "web-ui" and _is_same_origin_loopback(request)

    if not (token_ok or web_ui_ok):
        raise HTTPException(status_code=403, detail="拒绝跨站或未授权的本地服务停止请求")

    if not ctx.get("can_shutdown", False):
        raise HTTPException(status_code=409, detail="当前运行模式不允许通过接口停止服务")

    def _delayed_exit() -> None:
        time.sleep(0.15)
        trigger_shutdown_callback()

    threading.Thread(target=_delayed_exit, daemon=True).start()
    return {
        "stopping": True,
        "pid": int(ctx.get("pid") or os.getpid()),
        "port": int(ctx.get("port") or 0),
    }


@app.get("/api/assets/{asset_key}")
def api_get_asset(asset_key: str) -> FileResponse:
    path = get_asset_path(asset_key)
    if not path:
        raise HTTPException(status_code=404, detail="图片资源不存在")
    return FileResponse(str(path), headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/api/versions/{version_id}/source-blob")
def api_get_version_source_blob(version_id: int) -> FileResponse:
    ver = get_version(version_id)
    if not ver:
        raise HTTPException(status_code=404, detail="版本不存在")
    blob_key = ver.get("source_blob_key") or (ver.get("meta") or {}).get("source_blob_key")
    if not blob_key:
        raise HTTPException(status_code=404, detail="该版本无原始二进制归档文件")
    path = get_blob_path(str(blob_key))
    if not path:
        raise HTTPException(status_code=404, detail="原始二进制归档文件不存在")
    media_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if path.suffix.lower() == ".docx"
        else "application/zip"
    )
    return FileResponse(
        str(path),
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@app.get("/api/settings/ai-lexicon")
def api_get_ai_lexicon() -> dict[str, Any]:
    custom = get_ai_lexicon_settings()
    return {
        "defaults": {
            "en_words": DEFAULT_EN_AI_WORDS,
            "en_phrases": DEFAULT_EN_AI_PHRASES,
            "zh_words": DEFAULT_ZH_AI_CLICHES,
        },
        **custom,
    }


@app.put("/api/settings/ai-lexicon")
def api_save_ai_lexicon(payload: AiLexiconPayload) -> dict[str, Any]:
    saved = save_ai_lexicon_settings(payload.added_en, payload.added_zh, payload.muted)
    return {
        "defaults": {
            "en_words": DEFAULT_EN_AI_WORDS,
            "en_phrases": DEFAULT_EN_AI_PHRASES,
            "zh_words": DEFAULT_ZH_AI_CLICHES,
        },
        **saved,
    }


# ---------------- Local Folder Picker & Validation (W2, D-08) ----------------

def _is_loopback_request(request: Request) -> bool:
    fwd = (request.headers.get("x-forwarded-for") or "").strip()
    if fwd:
        first_hop = fwd.split(",")[0].strip()
        if first_hop not in ("127.0.0.1", "::1", "localhost"):
            return False
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost", "testclient")


def _enrich_project(p: dict[str, Any]) -> dict[str, Any]:
    if p.get("project_mode") == "local_folder":
        p.update(probe_root_summary(p.get("local_root_path")))
    else:
        p.setdefault("local_status", None)
        p.setdefault("local_doc_count", 0)
    return p


@app.post("/api/local/validate-folder")
def api_validate_local_folder(payload: FolderValidatePayload) -> dict[str, Any]:
    return validate_root_dir(payload.path)


@app.post("/api/local/open-path")
def api_open_local_path(request: Request, payload: FolderValidatePayload) -> dict[str, Any]:
    if not _is_loopback_request(request):
        raise HTTPException(status_code=403, detail="仅允许本机回环请求打开本地路径")
    resolved = resolve_open_path_target(payload.path, list_projects())
    matched = resolved["matched_project"]
    root_path = str(resolved["root_path"])
    rel_path = resolved["rel_path"]
    if matched is not None:
        pid = int(matched["id"])
        pname = str(matched["name"])
        created = False
    else:
        created_proj = create_project(
            name=str(resolved["suggested_name"]),
            description=f"本地绑定目录：{root_path}",
            category="paper",
            project_mode="local_folder",
            local_root_path=root_path,
        )
        pid = int(created_proj["id"])
        pname = str(created_proj["name"])
        created = True

    handoff = f"/?project={pid}"
    if rel_path:
        handoff += f"&file={quote(str(rel_path), safe='')}"
    return {
        "project_id": pid,
        "project_name": pname,
        "created": created,
        "root_path": root_path,
        "rel_path": rel_path,
        "handoff_path": handoff,
    }


def _pick_native_folder(initial_dir: str | None = None) -> dict[str, Any]:
    """Open an OS-native folder selection dialog (macOS / Windows / Linux) cleanly out-of-process."""
    system = platform.system()
    safe_init_path = ""
    if initial_dir:
        try:
            cand = Path(normalize_user_path(initial_dir)).expanduser()
            if cand.is_dir():
                safe_init_path = str(cand.resolve())
        except OSError:
            safe_init_path = ""

    if system == "Darwin":
        script = 'POSIX path of (choose folder with prompt "选择论文所在本地文件夹")'
        if safe_init_path:
            escaped = safe_init_path.replace("\\", "\\\\").replace('"', '\\"')
            script = (
                f'POSIX path of (choose folder with prompt "选择论文所在本地文件夹" '
                f'default location POSIX file "{escaped}")'
            )
        try:
            proc = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except Exception as exc:
            return {"picked": False, "supported": False, "detail": str(exc)}
        if proc.returncode != 0:
            return {"picked": False, "cancelled": True, "supported": True}
        chosen = proc.stdout.strip().rstrip("/")
        return (
            {"picked": True, "supported": True, "path": chosen}
            if chosen
            else {"picked": False, "cancelled": True, "supported": True}
        )

    if system == "Windows":
        no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        # In PyInstaller frozen builds, `sys.executable` is PaperDiff.exe (not python.exe) and
        # tkinter is intentionally excluded; skip tkinter subprocess and go straight to PowerShell.
        if not getattr(sys, "frozen", False):
            tk_script = (
                "import sys, tkinter as tk\n"
                "from tkinter import filedialog\n"
                "root = tk.Tk()\n"
                "root.withdraw()\n"
                "try:\n"
                "    root.attributes('-topmost', True)\n"
                "except Exception:\n"
                "    pass\n"
                "root.update()\n"
                "init = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None\n"
                "chosen = filedialog.askdirectory(title='选择论文所在本地文件夹', initialdir=init, mustexist=True)\n"
                "root.destroy()\n"
                "if chosen:\n"
                "    sys.stdout.write(chosen)\n"
            )
            try:
                proc = subprocess.run(
                    [sys.executable, "-c", tk_script, safe_init_path],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=120,
                    check=False,
                    creationflags=no_window,
                )
                if proc.returncode == 0:
                    chosen = proc.stdout.strip()
                    if chosen:
                        return {"picked": True, "supported": True, "path": os.path.normpath(chosen)}
                    return {"picked": False, "cancelled": True, "supported": True}
            except Exception:
                pass

        # Fallback: Windows PowerShell modern FolderBrowserDialog (STA + UTF-8 + TopMost)
        ps_init = safe_init_path.replace("'", "''")
        ps_script = (
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$owner = New-Object System.Windows.Forms.Form; "
            "$owner.TopMost = $true; $owner.StartPosition = 'Manual'; $owner.Location = New-Object System.Drawing.Point(-32000, -32000); "
            "$dlg = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$dlg.Description = '选择论文所在本地文件夹'; "
            "$dlg.UseDescriptionForTitle = $true; "
            "$dlg.AutoUpgradeEnabled = $true; "
            + (f"$dlg.SelectedPath = '{ps_init}'; " if ps_init else "")
            + "$res = $dlg.ShowDialog($owner); $owner.Dispose(); "
            "if ($res -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Out.Write($dlg.SelectedPath) }"
        )
        try:
            proc = subprocess.run(
                ["powershell.exe", "-NoProfile", "-STA", "-Command", ps_script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
                creationflags=no_window,
            )
            if proc.returncode == 0:
                chosen = proc.stdout.strip()
                if chosen:
                    return {"picked": True, "supported": True, "path": os.path.normpath(chosen)}
                return {"picked": False, "cancelled": True, "supported": True}
        except Exception as exc:
            return {"picked": False, "supported": False, "detail": f"无法唤起 Windows 目录选择器：{exc}"}
        return {"picked": False, "supported": False, "detail": "无法唤起系统目录选择器，请直接粘贴本地文件夹路径"}

    if system == "Linux":
        zenity = shutil.which("zenity")
        if zenity:
            cmd = [zenity, "--file-selection", "--directory", "--title=选择论文所在本地文件夹"]
            if safe_init_path:
                cmd.append(f"--filename={safe_init_path.rstrip('/')}/")
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
                if proc.returncode == 0 and proc.stdout.strip():
                    return {"picked": True, "supported": True, "path": proc.stdout.strip().rstrip("/")}
                return {"picked": False, "cancelled": True, "supported": True}
            except Exception:
                pass
        kdialog = shutil.which("kdialog")
        if kdialog:
            try:
                proc = subprocess.run(
                    [kdialog, "--getexistingdirectory", safe_init_path or str(Path.home())],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    return {"picked": True, "supported": True, "path": proc.stdout.strip().rstrip("/")}
                return {"picked": False, "cancelled": True, "supported": True}
            except Exception:
                pass

    return {"picked": False, "supported": False, "detail": "当前平台请直接粘贴本地目录绝对路径"}


@app.post("/api/local/pick-folder")
def api_pick_local_folder(request: Request, payload: FolderPickPayload) -> dict[str, Any]:
    if not _is_loopback_request(request):
        raise HTTPException(status_code=403, detail="仅允许本机 127.0.0.1 调用系统文件夹选择器")
    picked = _pick_native_folder(payload.initial_dir)
    if not picked.get("picked") or not picked.get("path"):
        return picked
    chosen = str(picked["path"])
    val = validate_root_dir(chosen)
    return {
        "picked": True,
        "supported": True,
        "path": val.get("resolved_path") or chosen,
        "doc_count": val.get("doc_count", 0),
        "valid": bool(val.get("valid", False)),
    }


# ---------------- Projects ----------------

@app.get("/api/projects")
def api_list_projects() -> list[dict[str, Any]]:
    return [_enrich_project(p) for p in list_projects()]


@app.post("/api/projects")
def api_create_project(payload: ProjectCreate) -> dict[str, Any]:
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="项目名称不能为空")
    resolved_root: str | None = None
    if payload.project_mode == "local_folder":
        val = validate_root_dir(payload.local_root_path or "")
        if not val.get("valid"):
            code = str(val.get("error_code") or "INVALID_ROOT")
            status_code = 404 if code == "NOT_FOUND" else (403 if code == "ROOT_UNREADABLE" else 400)
            raise LocalWorkspaceError(status_code, code, str(val.get("detail") or "本地目录无效"))
        resolved_root = str(val["resolved_path"])

    created = create_project(
        name=payload.name,
        description=payload.description,
        category=payload.category,
        status=payload.status,
        primary_format=payload.primary_format,
        protected_terms=payload.protected_terms,
        default_doc_name=payload.default_doc_name,
        project_mode=payload.project_mode,
        local_root_path=resolved_root,
    )
    return _enrich_project(created)


@app.patch("/api/projects/{project_id}")
def api_update_project(project_id: int, payload: ProjectUpdate) -> dict[str, Any]:
    new_root: str | None = payload.local_root_path
    if new_root is not None and new_root.strip():
        val = validate_root_dir(new_root)
        if not val.get("valid"):
            code = str(val.get("error_code") or "INVALID_ROOT")
            status_code = 404 if code == "NOT_FOUND" else (403 if code == "ROOT_UNREADABLE" else 400)
            raise LocalWorkspaceError(status_code, code, str(val.get("detail") or "本地目录无效"))
        new_root = str(val["resolved_path"])

    updated = update_project(
        project_id,
        name=payload.name,
        description=payload.description,
        category=payload.category,
        status=payload.status,
        pinned=payload.pinned,
        protected_terms=payload.protected_terms,
        project_mode=payload.project_mode,
        local_root_path=new_root,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="项目不存在")
    return _enrich_project(updated)


@app.delete("/api/projects/{project_id}")
def api_delete_project(project_id: int) -> dict[str, bool]:
    # Strictly deletes SQLite project record only; NEVER touches user local disk files (AC-08 / I5).
    if not delete_project(project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"deleted": True}


# ---------------- Local Folder Workspace Routes (W2: Tree / Direct Read / Pairwise Diff) ----------------

def _require_local_project(project_id: int) -> tuple[dict[str, Any], str]:
    proj = get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    if proj.get("project_mode") != "local_folder" or not proj.get("local_root_path"):
        raise LocalWorkspaceError(400, "NOT_LOCAL_PROJECT", "该项目未绑定本地文件夹")
    return proj, str(proj["local_root_path"])


@app.get("/api/projects/{project_id}/local/tree")
def api_local_tree(
    project_id: int,
    include_aux: bool = Query(False),
) -> dict[str, Any]:
    _, root = _require_local_project(project_id)
    return scan_local_tree(root, include_aux=include_aux)


@app.get("/api/projects/{project_id}/local/raw")
def api_local_raw(
    project_id: int,
    rel_path: str = Query(...),
) -> Response:
    _, root = _require_local_project(project_id)
    data, mime, _fname = read_local_raw_file(root, rel_path)
    return Response(content=data, media_type=mime)


@app.post("/api/projects/{project_id}/local/preview")
def api_local_preview(project_id: int, payload: LocalPreviewPayload) -> dict[str, Any]:
    proj, root = _require_local_project(project_id)
    doc_data = read_local_file_for_analysis(root, payload.rel_path)
    result = preview_document(
        content=doc_data["content"],
        fmt=doc_data["format"],
        filename=doc_data["filename"],
        protected_terms=proj["protected_terms"],
        custom_lexicon=get_ai_lexicon_settings(),
        meta=doc_data["meta"],
    )
    result["mode"] = "local_folder"
    result["project"] = _enrich_project(proj)
    result["version"] = {
        "id": 0,
        "label": doc_data["rel_path"],
        "filename": doc_data["filename"],
        "format": doc_data["format"],
        "source_tag": "本地文件",
        "source_blob_key": "local_raw" if doc_data["format"] == "docx" else None,
    }
    result["local_rel_path"] = doc_data["rel_path"]
    result["file_sha256"] = doc_data["file_sha256"]
    result["mtime_ms"] = doc_data["mtime_ms"]
    result["tracked_changes_info"] = doc_data["tracked_changes_info"]
    result["encoding_warning"] = doc_data["encoding_warning"]
    return result


@app.post("/api/projects/{project_id}/local/compare")
def api_local_compare(project_id: int, payload: LocalComparePayload) -> dict[str, Any]:
    proj, root = _require_local_project(project_id)
    if payload.docx_tracked_split:
        if not payload.rel_path:
            raise HTTPException(status_code=400, detail="缺少需要拆版对比的 .docx 相对路径")
        old_data = read_local_file_for_analysis(root, payload.rel_path, track_mode="before")
        new_data = read_local_file_for_analysis(root, payload.rel_path, track_mode="after")
        old_rel = f"{old_data['rel_path']}::before"
        new_rel = f"{new_data['rel_path']}::after"
        old_label = f"{old_data['rel_path']}（修订前）"
        new_label = f"{new_data['rel_path']}（修订后）"
    else:
        if not payload.old_rel_path or not payload.new_rel_path:
            raise HTTPException(status_code=400, detail="请选择项目内的 2 个文件进行两两对比")
        old_data = read_local_file_for_analysis(root, payload.old_rel_path)
        new_data = read_local_file_for_analysis(root, payload.new_rel_path)
        old_rel = old_data["rel_path"]
        new_rel = new_data["rel_path"]
        old_label = old_rel
        new_label = new_rel

    result = compare_documents(
        old_data["content"],
        new_data["content"],
        old_data["format"],
        new_data["format"],
        old_data["filename"],
        new_data["filename"],
        proj["protected_terms"],
        custom_lexicon=get_ai_lexicon_settings(),
        old_meta=old_data["meta"],
        new_meta=new_data["meta"],
    )
    pair_state = get_local_pair_state(project_id, old_rel, new_rel)
    acked_set = set(pair_state["acked_ids"])
    for a in result["alerts"]:
        a["acked"] = a["alert_id"] in acked_set
    for p in result["paragraphs"]:
        for a in p["alerts"]:
            a["acked"] = a["alert_id"] in acked_set
    result["summary"]["alert_counts"]["acked"] = sum(1 for a in result["alerts"] if a.get("acked"))

    result["mode"] = "local_folder"
    result["project"] = _enrich_project(proj)
    result["old_version"] = {"id": 0, "label": old_label, "filename": old_data["filename"]}
    result["new_version"] = {"id": 0, "label": new_label, "filename": new_data["filename"]}
    result["local_old_rel_path"] = old_rel
    result["local_new_rel_path"] = new_rel
    result["old_sha256"] = old_data["file_sha256"]
    result["new_sha256"] = new_data["file_sha256"]
    result["decisions"] = pair_state["decisions"]
    result["acked_alert_ids"] = pair_state["acked_ids"]
    return result


@app.put("/api/projects/{project_id}/local/pair-state")
def api_save_local_pair_state(project_id: int, payload: LocalPairStatePayload) -> dict[str, Any]:
    _require_local_project(project_id)
    return save_local_pair_state(
        project_id,
        payload.old_rel_path,
        payload.new_rel_path,
        acked_ids=payload.acked_ids,
        decisions=payload.decisions,
    )


@app.get("/api/projects/{project_id}/local/stat")
def api_local_stat(
    project_id: int,
    rel_path: list[str] = Query(default=[]),
) -> dict[str, Any]:
    _, root = _require_local_project(project_id)
    return stat_local_files(root, rel_path)


@app.post("/api/projects/{project_id}/local/save-edits")
def api_local_save_edits(project_id: int, payload: LocalSaveEditsPayload) -> dict[str, Any]:
    proj, root = _require_local_project(project_id)
    return save_local_file_edits(
        root,
        payload.rel_path,
        patches=payload.patches,
        paragraph_edits=payload.paragraph_edits,
        mode=payload.mode,
        target_rel_path=payload.target_rel_path,
        expected_sha256=payload.expected_sha256,
        force=payload.force,
        docx_mode=payload.docx_mode,
        protected_terms=proj["protected_terms"],
        custom_lexicon=get_ai_lexicon_settings(),
    )


# ---------------- Documents ----------------

@app.get("/api/projects/{project_id}/documents")
def api_list_documents(project_id: int) -> list[dict[str, Any]]:
    if not get_project(project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    return list_documents(project_id)


@app.post("/api/projects/{project_id}/documents")
def api_create_document(project_id: int, payload: DocumentCreate) -> dict[str, Any]:
    if not get_project(project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="文档名称不能为空")
    return create_document(
        project_id=project_id,
        name=payload.name,
        doc_type=payload.doc_type,
        primary_format=payload.primary_format,
        notes=payload.notes,
    )


@app.patch("/api/documents/{document_id}")
def api_update_document(document_id: int, payload: DocumentUpdate) -> dict[str, Any]:
    updated = update_document(
        document_id,
        name=payload.name,
        doc_type=payload.doc_type,
        primary_format=payload.primary_format,
        notes=payload.notes,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="文档不存在")
    return updated


@app.delete("/api/documents/{document_id}")
def api_delete_document(document_id: int) -> dict[str, bool]:
    if not delete_document(document_id):
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"deleted": True}


# ---------------- Versions (Document-Scoped + Legacy Compatible) ----------------

@app.get("/api/documents/{document_id}/versions")
def api_list_doc_versions(document_id: int) -> list[dict[str, Any]]:
    if not get_document(document_id):
        raise HTTPException(status_code=404, detail="文档不存在")
    return list_versions_by_document(document_id)


@app.post("/api/documents/{document_id}/versions")
def api_create_doc_version_json(document_id: int, payload: VersionCreateJSON) -> dict[str, Any]:
    doc = get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if not payload.content.strip():
        raise HTTPException(status_code=400, detail="文稿内容不能为空")
    det_fmt, wc, pc, ai_cnt = _compute_version_stats(payload.content, payload.format, payload.filename)
    return create_version(
        project_id=int(doc["project_id"]),
        document_id=document_id,
        label=payload.label,
        source_tag=payload.source_tag,
        filename=payload.filename,
        fmt=det_fmt,
        content=payload.content,
        notes=payload.notes,
        word_count=wc,
        para_count=pc,
        ai_ism_count=ai_cnt,
        is_milestone=payload.is_milestone,
    )


@app.post("/api/documents/{document_id}/versions/upload")
async def api_upload_doc_version(
    document_id: int,
    file: UploadFile = File(...),
    label: str = Form(""),
    source_tag: str = Form("AI润色"),
    notes: str = Form(""),
    is_milestone: bool = Form(False),
) -> dict[str, Any]:
    doc = get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")
    try:
        eff_name, det_fmt, content, meta = _decode_uploaded_file(file.filename or "upload.tex", raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"文件解析失败: {exc}") from exc
    det_fmt, wc, pc, ai_cnt = _compute_version_stats(content, det_fmt, eff_name)
    return create_version(
        project_id=int(doc["project_id"]),
        document_id=document_id,
        label=label,
        source_tag=source_tag,
        filename=eff_name,
        fmt=det_fmt,
        content=content,
        notes=notes,
        word_count=wc,
        para_count=pc,
        ai_ism_count=ai_cnt,
        is_milestone=is_milestone,
        meta=meta,
        source_blob_key=meta.get("source_blob_key"),
    )


@app.post("/api/documents/{document_id}/versions/inspect-docx")
async def api_inspect_docx(document_id: int, file: UploadFile = File(...)) -> dict[str, Any]:
    if not get_document(document_id):
        raise HTTPException(status_code=404, detail="文档不存在")
    raw = await file.read()
    if not raw or not (file.filename or "").lower().endswith(".docx"):
        return {"has_tracked_changes": False, "ins_count": 0, "del_count": 0, "authors": [], "summary": ""}
    return inspect_docx_tracked_changes(raw)


@app.post("/api/documents/{document_id}/versions/import-tracked-docx")
async def api_import_tracked_docx(
    document_id: int,
    file: UploadFile = File(...),
    label_prefix: str = Form(""),
    notes: str = Form(""),
) -> dict[str, Any]:
    """One-click split import of a Word Track Changes .docx into vN (修订前) + vN+1 (修订后)."""
    doc = get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")
    fname = file.filename or "tracked.docx"
    try:
        tc_info = inspect_docx_tracked_changes(raw)
        before_txt, before_meta = extract_docx_with_assets(raw, track_mode="before")
        after_txt, after_meta = extract_docx_with_assets(raw, track_mode="after")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Word 修订拆分解析失败: {exc}") from exc

    prefix = label_prefix.strip() or Path(fname).stem
    _, wc_b, pc_b, ai_b = _compute_version_stats(before_txt, "docx", fname)
    before_v = create_version(
        project_id=int(doc["project_id"]),
        document_id=document_id,
        label=f"{prefix} · Word修订前",
        source_tag="Word原稿",
        filename=fname,
        fmt="docx",
        content=before_txt,
        notes=notes or f"由带修订 Word 拆分的基准原稿（{tc_info.get('summary', '')}）",
        word_count=wc_b,
        para_count=pc_b,
        ai_ism_count=ai_b,
        meta=before_meta,
        source_blob_key=before_meta.get("source_blob_key"),
    )
    _, wc_a, pc_a, ai_a = _compute_version_stats(after_txt, "docx", fname)
    after_v = create_version(
        project_id=int(doc["project_id"]),
        document_id=document_id,
        label=f"{prefix} · Word修订后",
        source_tag="导师批注",
        filename=fname,
        fmt="docx",
        content=after_txt,
        notes=notes or f"由带修订 Word 拆分的修订版（{tc_info.get('summary', '')}）",
        word_count=wc_a,
        para_count=pc_a,
        ai_ism_count=ai_a,
        parent_version_id=int(before_v["id"]),
        meta=after_meta,
        source_blob_key=after_meta.get("source_blob_key"),
    )
    return {
        "before_version": {k: v for k, v in before_v.items() if k != "content"},
        "after_version": {k: v for k, v in after_v.items() if k != "content"},
        "tracked_changes_info": tc_info,
    }


@app.get("/api/projects/{project_id}/versions")
def api_list_versions_legacy(project_id: int) -> list[dict[str, Any]]:
    if not get_project(project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    return list_versions(project_id)


@app.post("/api/projects/{project_id}/versions")
def api_create_version_legacy(project_id: int, payload: VersionCreateJSON) -> dict[str, Any]:
    proj = get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    doc_id = int(proj["documents"][0]["id"]) if proj["documents"] else None
    det_fmt, wc, pc, ai_cnt = _compute_version_stats(payload.content, payload.format, payload.filename)
    return create_version(
        project_id=project_id,
        document_id=doc_id,
        label=payload.label,
        source_tag=payload.source_tag,
        filename=payload.filename,
        fmt=det_fmt,
        content=payload.content,
        notes=payload.notes,
        word_count=wc,
        para_count=pc,
        ai_ism_count=ai_cnt,
        is_milestone=payload.is_milestone,
    )


@app.post("/api/parse-upload")
async def api_parse_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")
    try:
        eff_name, det_fmt, content, meta = _decode_uploaded_file(file.filename or "upload.tex", raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"文件解析失败: {exc}") from exc
    return {"filename": eff_name, "format": det_fmt, "content": content, "meta": meta}


@app.get("/api/versions/{version_id}")
def api_get_version(version_id: int) -> dict[str, Any]:
    ver = get_version(version_id)
    if not ver:
        raise HTTPException(status_code=404, detail="版本不存在")
    return ver


@app.patch("/api/versions/{version_id}")
def api_update_version(version_id: int, payload: VersionUpdate) -> dict[str, Any]:
    updated = update_version(
        version_id,
        label=payload.label,
        source_tag=payload.source_tag,
        notes=payload.notes,
        is_milestone=payload.is_milestone,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="版本不存在")
    return {k: v for k, v in updated.items() if k != "content"}


@app.delete("/api/versions/{version_id}")
def api_delete_version(version_id: int) -> dict[str, bool]:
    if not delete_version(version_id):
        raise HTTPException(status_code=404, detail="版本不存在")
    return {"deleted": True}


# ---------------- Single-Document Preview & Self-Audit (v1.4.5) ----------------

@app.get("/api/versions/{version_id}/preview")
def api_preview_version(version_id: int) -> dict[str, Any]:
    ver = get_version(version_id)
    if not ver:
        raise HTTPException(status_code=404, detail="版本不存在")
    doc = get_document(int(ver["document_id"])) if ver.get("document_id") else None
    proj = get_project(int(ver["project_id"])) if ver.get("project_id") else None
    terms = proj["protected_terms"] if proj else []
    prev = preview_document(
        content=ver["content"],
        fmt=ver["format"],
        filename=ver["filename"],
        protected_terms=terms,
        custom_lexicon=get_ai_lexicon_settings(),
        meta=ver.get("meta"),
    )
    return {
        "mode": "project",
        "project": proj,
        "document": doc,
        "version": {k: v for k, v in ver.items() if k != "content"},
        **prev,
    }


@app.post("/api/preview/quick")
def api_preview_quick(payload: QuickPreviewRequest) -> dict[str, Any]:
    prev = preview_document(
        content=payload.content,
        fmt=payload.format,
        filename=payload.filename,
        protected_terms=payload.protected_terms,
        custom_lexicon=get_ai_lexicon_settings(),
        meta=payload.meta,
    )
    return {
        "mode": "quick",
        "version": {
            "id": -1,
            "label": payload.label,
            "source_tag": "单稿预览",
            "filename": payload.filename,
            "format": prev["format"],
        },
        **prev,
    }


@app.post("/api/documents/{document_id}/save-single-version")
def api_save_single_as_new_version(document_id: int, payload: SaveSingleVersionPayload) -> dict[str, Any]:
    """Apply in-place Read-Mode paragraph micro-edits losslessly and save as v(N+1)."""
    doc = get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    proj = get_project(int(doc["project_id"]))
    assert proj is not None
    base_v = get_version(payload.base_version_id)
    if not base_v or int(base_v["document_id"]) != document_id:
        raise HTTPException(status_code=404, detail="源版本不存在或不属于当前文档")

    prev = preview_document(
        content=base_v["content"],
        fmt=base_v["format"],
        filename=base_v["filename"],
        protected_terms=proj["protected_terms"],
        custom_lexicon=get_ai_lexicon_settings(),
        meta=base_v.get("meta"),
    )
    patched_text = apply_single_document_edits(
        base_v["content"], prev["format"], prev, payload.paragraph_edits
    )
    fmt = prev["format"] or base_v["format"] or "markdown"
    ext = "tex" if fmt == "latex" else "md"
    filename = f"revised_from_v{base_v['version_number']}.{ext}"

    edited_cnt = len(payload.paragraph_edits)
    auto_note = f"基于 {base_v['label']} 阅读态原位修订（微调 {edited_cnt} 段）"
    notes = payload.notes.strip() or auto_note

    det_fmt, wc, pc, ai_cnt = _compute_version_stats(patched_text, fmt, filename)
    created = create_version(
        project_id=int(doc["project_id"]),
        document_id=document_id,
        label=payload.label,
        source_tag=payload.source_tag or "人工修复",
        filename=filename,
        fmt=det_fmt,
        content=patched_text,
        notes=notes,
        word_count=wc,
        para_count=pc,
        ai_ism_count=ai_cnt,
        is_milestone=payload.is_milestone,
        parent_version_id=int(base_v["id"]),
        meta=base_v.get("meta"),
    )
    return {k: v for k, v in created.items() if k != "content"}


@app.post("/api/documents/{document_id}/apply-patches")
def api_apply_typed_patches(document_id: int, payload: ApplyPatchesPayload) -> dict[str, Any]:
    """
    v1.1.0 Format-Preserving Round-Trip Patching Endpoint:
    Applies Typed Patch Ops (paragraph, heading, caption, math, table cell/row edits) directly onto
    the source format (.tex / Overleaf .zip / original archived .docx template / .md) and saves v(N+1).
    """
    doc = get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    proj = get_project(int(doc["project_id"]))
    assert proj is not None
    base_v = get_version(payload.base_version_id)
    if not base_v or int(base_v["document_id"]) != document_id:
        raise HTTPException(status_code=404, detail="源版本不存在或不属于当前文档")
    if not payload.patches:
        raise HTTPException(status_code=400, detail="没有需要保存的修订补丁")

    base_meta = dict(base_v.get("meta") or {})
    prev = preview_document(
        content=base_v["content"],
        fmt=base_v["format"],
        filename=base_v["filename"],
        protected_terms=proj["protected_terms"],
        custom_lexicon=get_ai_lexicon_settings(),
        meta=base_meta,
    )

    blob_key = base_v.get("source_blob_key") or base_meta.get("source_blob_key")
    orig_blob_bytes = None
    if blob_key:
        bp = get_blob_path(str(blob_key))
        if bp and bp.exists():
            orig_blob_bytes = bp.read_bytes()

    fmt = prev["format"] or base_v["format"] or "markdown"
    patch_res = apply_typed_patches(
        content=base_v["content"],
        fmt=fmt,
        blocks=prev["blocks"],
        ops=payload.patches,
        orig_blob_bytes=orig_blob_bytes,
        source_map=base_meta.get("source_map"),
        docx_mode=payload.docx_mode,
    )

    new_blob_key = blob_key
    if patch_res["patched_blob_bytes"] and patch_res["patched_blob_ext"]:
        saved_k = save_blob_bytes(patch_res["patched_blob_bytes"], patch_res["patched_blob_ext"])
        if saved_k:
            new_blob_key = saved_k
            base_meta["source_blob_key"] = saved_k

    # If .docx was patched in-place, re-extract clean Markdown from the patched .docx so XML anchors stay 100% synced!
    final_content = patch_res["patched_content"]
    if fmt == "docx" and patch_res["patched_blob_bytes"]:
        try:
            re_txt, re_meta = extract_docx_with_assets(patch_res["patched_blob_bytes"], track_mode="after")
            final_content = re_txt
            base_meta["assets"] = {**(base_meta.get("assets") or {}), **(re_meta.get("assets") or {})}
            base_meta["footnotes"] = re_meta.get("footnotes") or base_meta.get("footnotes") or {}
            if re_meta.get("source_blob_key"):
                new_blob_key = re_meta["source_blob_key"]
                base_meta["source_blob_key"] = new_blob_key
        except Exception:
            pass

    ext = "tex" if fmt == "latex" else ("docx" if fmt == "docx" else "md")
    filename = f"revised_from_v{base_v['version_number']}.{ext}"
    auto_note = f"基于 {base_v['label']} 原位结构化修订（应用 {patch_res['applied_count']} 项补丁）"
    notes = payload.notes.strip() or auto_note
    det_fmt, wc, pc, ai_cnt = _compute_version_stats(final_content, fmt, filename)

    created = create_version(
        project_id=int(doc["project_id"]),
        document_id=document_id,
        label=payload.label,
        source_tag=payload.source_tag or "人工修复",
        filename=filename,
        fmt=det_fmt,
        content=final_content,
        notes=notes,
        word_count=wc,
        para_count=pc,
        ai_ism_count=ai_cnt,
        is_milestone=payload.is_milestone,
        parent_version_id=int(base_v["id"]),
        meta=base_meta,
        source_blob_key=new_blob_key,
    )
    out_v = {k: v for k, v in created.items() if k != "content"}
    return {
        "version": out_v,
        "applied_count": patch_res["applied_count"],
        "warnings": patch_res["warnings"],
    }


# ---------------- Comparison & Fix-Save Loop ----------------

@app.get("/api/documents/{document_id}/compare")
def api_compare_document_versions(
    document_id: int,
    old_id: int = Query(...),
    new_id: int = Query(...),
) -> dict[str, Any]:
    doc = get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    proj = get_project(int(doc["project_id"]))
    assert proj is not None
    old_v = get_version(old_id)
    new_v = get_version(new_id)
    if not old_v or not new_v or int(old_v["document_id"]) != document_id or int(new_v["document_id"]) != document_id:
        raise HTTPException(status_code=404, detail="版本不存在或不属于当前文档")

    lexicon = get_ai_lexicon_settings()
    acked_ids = get_alert_acks(document_id, old_id, new_id)
    comp = compare_documents(
        old_content=old_v["content"],
        new_content=new_v["content"],
        old_fmt=old_v["format"],
        new_fmt=new_v["format"],
        old_filename=old_v["filename"],
        new_filename=new_v["filename"],
        protected_terms=proj["protected_terms"],
        custom_lexicon=lexicon,
        acked_alert_ids=acked_ids,
        old_meta=old_v.get("meta"),
        new_meta=new_v.get("meta"),
    )
    decisions = get_merge_decisions(int(proj["id"]), old_id, new_id)
    return {
        "mode": "project",
        "project": proj,
        "document": doc,
        "old_version": {k: v for k, v in old_v.items() if k != "content"},
        "new_version": {k: v for k, v in new_v.items() if k != "content"},
        "decisions": decisions,
        "acked_alert_ids": acked_ids,
        **comp,
    }


@app.get("/api/projects/{project_id}/compare")
def api_compare_project_legacy(
    project_id: int,
    old_id: int = Query(...),
    new_id: int = Query(...),
) -> dict[str, Any]:
    old_v = get_version(old_id)
    if not old_v or not old_v.get("document_id"):
        raise HTTPException(status_code=404, detail="版本不存在")
    return api_compare_document_versions(int(old_v["document_id"]), old_id, new_id)


@app.post("/api/compare/quick")
def api_compare_quick(payload: QuickCompareRequest) -> dict[str, Any]:
    comp = compare_documents(
        old_content=payload.old_content,
        new_content=payload.new_content,
        old_fmt=payload.old_format,
        new_fmt=payload.new_format,
        protected_terms=payload.protected_terms,
        custom_lexicon=get_ai_lexicon_settings(),
        old_meta=payload.old_meta,
        new_meta=payload.new_meta,
    )
    return {
        "mode": "quick",
        "old_version": {"id": -1, "label": payload.old_label, "source_tag": "旧版", "filename": "old"},
        "new_version": {"id": -2, "label": payload.new_label, "source_tag": "新版", "filename": "new"},
        "decisions": {},
        "acked_alert_ids": [],
        **comp,
    }


@app.put("/api/documents/{document_id}/ack-alerts")
def api_save_alert_acks(document_id: int, payload: AlertAckPayload) -> dict[str, Any]:
    if not get_document(document_id):
        raise HTTPException(status_code=404, detail="文档不存在")
    saved = save_alert_acks(document_id, payload.old_version_id, payload.new_version_id, payload.acked_ids)
    return {"acked_ids": saved}


@app.put("/api/documents/{document_id}/merge-decisions")
def api_save_doc_merge_decisions(document_id: int, payload: MergeDecisionPayload) -> dict[str, Any]:
    doc = get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    saved = save_merge_decisions(
        int(doc["project_id"]),
        payload.old_version_id,
        payload.new_version_id,
        payload.decisions,
        document_id=document_id,
    )
    return {"decisions": saved}


@app.post("/api/documents/{document_id}/save-merged-version")
def api_save_merged_as_new_version(document_id: int, payload: SaveMergedVersionPayload) -> dict[str, Any]:
    """Reconstruct merged draft (Cherry-Pick + inline paragraph edits) and persist as v(N+1)."""
    doc = get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    proj = get_project(int(doc["project_id"]))
    assert proj is not None
    old_v = get_version(payload.old_version_id)
    new_v = get_version(payload.new_version_id)
    if not old_v or not new_v:
        raise HTTPException(status_code=404, detail="源版本不存在")

    comp = compare_documents(
        old_v["content"],
        new_v["content"],
        old_v["format"],
        new_v["format"],
        old_v["filename"],
        new_v["filename"],
        proj["protected_terms"],
        custom_lexicon=get_ai_lexicon_settings(),
    )
    merged_text = export_merged_document(
        comp, payload.decisions, payload.paragraph_edits, new_full_content=new_v["content"]
    )
    is_latex = comp["formats"]["new"] == "latex" or comp["formats"]["old"] == "latex"
    fmt = "latex" if is_latex else (new_v["format"] or "markdown")
    ext = "tex" if is_latex else "md"
    filename = f"merged_from_v{new_v['version_number']}.{ext}"

    reverted_cnt = sum(1 for v in payload.decisions.values() if v == "keep_old")
    edited_cnt = len(payload.paragraph_edits)
    auto_note = f"基于 {new_v['label']} 修复合成（回退 {reverted_cnt} 处词块，微调 {edited_cnt} 段）"
    notes = payload.notes.strip() or auto_note

    det_fmt, wc, pc, ai_cnt = _compute_version_stats(merged_text, fmt, filename)
    created = create_version(
        project_id=int(doc["project_id"]),
        document_id=document_id,
        label=payload.label,
        source_tag=payload.source_tag or "人工修复",
        filename=filename,
        fmt=det_fmt,
        content=merged_text,
        notes=notes,
        word_count=wc,
        para_count=pc,
        ai_ism_count=ai_cnt,
        is_milestone=payload.is_milestone,
        parent_version_id=int(new_v["id"]),
        meta=new_v.get("meta"),
    )
    return {k: v for k, v in created.items() if k != "content"}


@app.post("/api/export")
def api_export(payload: ExportPayload) -> Response:
    et = payload.export_type

    # --- Single-document exports (HTML, Printable HTML, PDF, Patched Source/DOCX/ZIP) ---
    if et in (
        "single_html",
        "single_source",
        "print_html_single",
        "pdf_single",
        "docx_patched",
        "docx_tracked_preserved",
        "latex_zip_patched",
    ):
        ver = None
        local_raw_bytes: bytes | None = None
        if payload.local_project_id and payload.local_rel_path:
            proj, root = _require_local_project(payload.local_project_id)
            doc_data = read_local_file_for_analysis(root, payload.local_rel_path)
            title = f"{proj['name']} · {doc_data['rel_path']}"
            v_label = doc_data["rel_path"]
            raw_content = doc_data["content"]
            fmt = doc_data["format"]
            fname = doc_data["filename"]
            meta = doc_data["meta"]
            terms = proj["protected_terms"]
            local_raw_bytes = doc_data["raw_bytes"]
        elif payload.version_id:
            ver = get_version(payload.version_id)
            if not ver:
                raise HTTPException(status_code=404, detail="版本不存在")
            proj = get_project(int(ver["project_id"])) if ver.get("project_id") else None
            doc = get_document(int(ver["document_id"])) if ver.get("document_id") else None
            title = f"{proj['name']} · {doc['name']}" if (proj and doc) else (proj["name"] if proj else payload.project_name)
            v_label = ver["label"]
            raw_content = ver["content"]
            fmt = ver["format"]
            fname = ver["filename"]
            meta = ver.get("meta") or {}
            terms = proj["protected_terms"] if proj else payload.protected_terms
        else:
            if payload.single_content is None:
                raise HTTPException(status_code=400, detail="缺少单文档内容")
            title = payload.project_name
            v_label = payload.single_label
            raw_content = payload.single_content
            fmt = "auto"
            fname = "manuscript.tex"
            meta = payload.single_meta or {}
            terms = payload.protected_terms

        prev = preview_document(
            content=raw_content,
            fmt=fmt,
            filename=fname,
            protected_terms=terms,
            custom_lexicon=get_ai_lexicon_settings(),
            meta=meta,
        )

        # Apply either new Typed Patch Ops or legacy paragraph_edits
        orig_blob_bytes = local_raw_bytes if fmt in ("docx", "latex") and fname.lower().endswith((".docx", ".zip")) else None
        blob_key = (ver.get("source_blob_key") if ver else None) or meta.get("source_blob_key")
        if orig_blob_bytes is None and blob_key:
            bp = get_blob_path(str(blob_key))
            if bp and bp.exists():
                orig_blob_bytes = bp.read_bytes()

        patched_blob: bytes | None = orig_blob_bytes
        if payload.patches:
            d_mode = "tracked" if et == "docx_tracked_preserved" else payload.docx_mode
            pres = apply_typed_patches(
                content=raw_content,
                fmt=prev["format"],
                blocks=prev["blocks"],
                ops=payload.patches,
                orig_blob_bytes=orig_blob_bytes,
                source_map=meta.get("source_map"),
                docx_mode=d_mode,
            )
            patched_content = pres["patched_content"]
            if pres["patched_blob_bytes"]:
                patched_blob = pres["patched_blob_bytes"]
        else:
            patched_content = apply_single_document_edits(raw_content, prev["format"], prev, payload.paragraph_edits)

        if et == "single_source":
            return PlainTextResponse(content=patched_content, media_type="text/plain; charset=utf-8")
        if et in ("docx_patched", "docx_tracked_preserved"):
            if not patched_blob:
                raise HTTPException(status_code=400, detail="该版本缺少原始 .docx 模板归档，请重新导入 .docx 文件")
            return Response(
                content=patched_blob,
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        if et == "latex_zip_patched":
            if not patched_blob:
                raise HTTPException(status_code=400, detail="该版本缺少原始 Overleaf .zip 归档")
            return Response(content=patched_blob, media_type="application/zip")

        if payload.patches or payload.paragraph_edits:
            prev = preview_document(
                content=patched_content,
                fmt=prev["format"],
                filename=fname,
                protected_terms=terms,
                custom_lexicon=get_ai_lexicon_settings(),
                meta=meta,
            )

        if et == "print_html_single":
            phtml = render_single_print_html(
                prev,
                title,
                v_label,
                commentary_note=payload.commentary_note,
                landscape=payload.landscape,
                typography_prefs=payload.typography_prefs,
            )
            return Response(content=phtml, media_type="text/html; charset=utf-8")
        if et == "pdf_single":
            phtml = render_single_print_html(
                prev,
                title,
                v_label,
                commentary_note=payload.commentary_note,
                landscape=payload.landscape,
                typography_prefs=payload.typography_prefs,
            )
            try:
                pdf_bytes = render_html_to_pdf_bytes(phtml)
            except Exception as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            return Response(content=pdf_bytes, media_type="application/pdf")

        html_str = export_single_html_report(prev, title, v_label)
        return Response(content=html_str, media_type="text/html; charset=utf-8")

    # --- Comparison exports ---
    new_full_content = None
    if payload.local_project_id and payload.local_old_rel_path and payload.local_new_rel_path:
        proj, root = _require_local_project(payload.local_project_id)
        old_data = read_local_file_for_analysis(root, payload.local_old_rel_path)
        new_data = read_local_file_for_analysis(root, payload.local_new_rel_path)
        proj_name = proj["name"]
        terms = proj["protected_terms"]
        old_label = payload.old_label if payload.old_label != "旧版本" else old_data["rel_path"]
        new_label = payload.new_label if payload.new_label != "新版本" else new_data["rel_path"]
        new_full_content = new_data["content"]
        comp = compare_documents(
            old_data["content"],
            new_data["content"],
            old_data["format"],
            new_data["format"],
            old_data["filename"],
            new_data["filename"],
            terms,
            custom_lexicon=get_ai_lexicon_settings(),
            old_meta=old_data["meta"],
            new_meta=new_data["meta"],
        )
    elif payload.old_version_id and payload.new_version_id:
        old_v = get_version(payload.old_version_id)
        new_v = get_version(payload.new_version_id)
        if not old_v or not new_v:
            raise HTTPException(status_code=404, detail="版本不存在")
        proj = get_project(int(old_v["project_id"]))
        proj_name = proj["name"] if proj else payload.project_name
        terms = proj["protected_terms"] if proj else payload.protected_terms
        old_label = old_v["label"]
        new_label = new_v["label"]
        new_full_content = new_v["content"]
        comp = compare_documents(
            old_v["content"],
            new_v["content"],
            old_v["format"],
            new_v["format"],
            old_v["filename"],
            new_v["filename"],
            terms,
            custom_lexicon=get_ai_lexicon_settings(),
            old_meta=old_v.get("meta"),
            new_meta=new_v.get("meta"),
        )
    else:
        if payload.old_content is None or payload.new_content is None:
            raise HTTPException(status_code=400, detail="缺少对比文本")
        proj_name = payload.project_name
        old_label = payload.old_label
        new_label = payload.new_label
        new_full_content = payload.new_content
        comp = compare_documents(
            payload.old_content,
            payload.new_content,
            protected_terms=payload.protected_terms,
            custom_lexicon=get_ai_lexicon_settings(),
        )

    if et in ("print_html_diff", "print_html_diff_compact"):
        phtml = render_diff_print_html(
            comp,
            proj_name,
            old_label,
            new_label,
            compact=(et == "print_html_diff_compact"),
            commentary_note=payload.commentary_note,
            landscape=payload.landscape,
        )
        return Response(content=phtml, media_type="text/html; charset=utf-8")
    if et in ("pdf_diff_report", "pdf_diff_compact"):
        phtml = render_diff_print_html(
            comp,
            proj_name,
            old_label,
            new_label,
            compact=(et == "pdf_diff_compact"),
            commentary_note=payload.commentary_note,
            landscape=payload.landscape,
        )
        try:
            pdf_bytes = render_html_to_pdf_bytes(phtml)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return Response(content=pdf_bytes, media_type="application/pdf")
    if et == "html":
        html_str = export_html_report(comp, proj_name, old_label, new_label, payload.view_mode)
        return Response(content=html_str, media_type="text/html; charset=utf-8")
    if et == "latexdiff":
        tex_str = export_latexdiff_tex(comp, old_label, new_label)
        return PlainTextResponse(content=tex_str, media_type="text/plain; charset=utf-8")
    if et == "markdown":
        md_str = export_markdown_summary(comp, proj_name, old_label, new_label)
        return PlainTextResponse(content=md_str, media_type="text/markdown; charset=utf-8")
    if et == "docx_tracked":
        docx_bytes = export_docx_tracked_bytes(comp)
        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    if et == "docx_merged":
        docx_bytes = export_docx_merged_bytes(comp, payload.decisions, payload.paragraph_edits)
        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    merged = export_merged_document(
        comp, payload.decisions, payload.paragraph_edits, new_full_content=new_full_content
    )
    return PlainTextResponse(content=merged, media_type="text/plain; charset=utf-8")


def _resolve_frontend_dist() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        bundled = Path(sys._MEIPASS) / "frontend" / "dist"  # type: ignore[attr-defined]
        if bundled.exists():
            return bundled
    return Path(__file__).resolve().parent.parent / "frontend" / "dist"


# Serve compiled React frontend if available
FRONTEND_DIST = _resolve_frontend_dist()
if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    _NO_CACHE_HEADERS = {
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        dist_root = FRONTEND_DIST.resolve()
        target = (dist_root / full_path).resolve()
        if full_path and target.is_relative_to(dist_root) and target.exists() and target.is_file():
            if target.name in {"index.html", "manifest.webmanifest"}:
                return FileResponse(str(target), headers=_NO_CACHE_HEADERS)
            return FileResponse(str(target))
        return FileResponse(str(dist_root / "index.html"), headers=_NO_CACHE_HEADERS)
