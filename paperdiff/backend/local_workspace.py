"""Local Folder Workspace Service, Root Path Sandbox (I5) & Bounded Tree Scanner.

Enforces Invariant I5 across all local-folder project operations:
- Read-only by default: scanning, statting, previewing, raw-streaming, and pairwise
  diffing never mutate any file inside the bound root directory.
- Strict root sandbox (`resolve_safe_path`): rejects `../` traversal, absolute paths,
  and symlinks resolving outside the canonical `root_real` directory with HTTP 403
  (`PATH_OUTSIDE_ROOT`).
- Bounded traversal (`D-07`): caps recursion at `MAX_SCAN_DEPTH=10` and
  `MAX_SCAN_ENTRIES=5000`, breaks symlink directory loops by `(st_dev, st_ino)`, and
  filters compile/OS/backup noise by default.
"""
from __future__ import annotations

import datetime
import hashlib
import mimetypes
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .assets import ALLOWED_IMAGE_EXTS, parse_bibtex_entries, save_asset_bytes
from .parsers import (
    detect_format,
    extract_docx_with_assets,
    extract_latex_zip_with_assets,
    inspect_docx_tracked_changes,
)

MAX_SCAN_DEPTH = 10
MAX_SCAN_ENTRIES = 5000

DOC_EXT_TO_FORMAT: dict[str, str] = {
    ".tex": "latex",
    ".ltx": "latex",
    ".docx": "docx",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "markdown",
    ".zip": "latex",
}

AUX_EXT_TO_KIND: dict[str, str] = {
    ".bib": "bib",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".svg": "image",
    ".webp": "image",
    ".gif": "image",
    ".pdf": "pdf",
    ".sty": "tex_aux",
    ".cls": "tex_aux",
}

IGNORED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".idea",
        ".vscode",
        "build",
        "dist",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
)

IGNORED_FILE_NAMES: frozenset[str] = frozenset({".ds_store", "thumbs.db", "desktop.ini"})

IGNORED_FILE_EXTS: frozenset[str] = frozenset(
    {
        ".aux",
        ".log",
        ".out",
        ".toc",
        ".lof",
        ".lot",
        ".fls",
        ".fdb_latexmk",
        ".bbl",
        ".blg",
        ".nav",
        ".snm",
        ".vrb",
        ".dvi",
        ".idx",
        ".ilg",
        ".ind",
        ".bak",
    }
)

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_NATURAL_KEY_RE = re.compile(r"(\d+)")


class LocalWorkspaceError(Exception):
    """Structured local-workspace error carrying HTTP status & machine error code."""

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


def _natural_sort_key(name: str) -> list[Any]:
    return [int(tok) if tok.isdigit() else tok.lower() for tok in _NATURAL_KEY_RE.split(name)]


def _is_ignored_dir(name: str) -> bool:
    low = name.lower()
    return low in IGNORED_DIR_NAMES or low.startswith("_minted-")


def _is_ignored_file(name: str) -> bool:
    low = name.lower()
    if low in IGNORED_FILE_NAMES:
        return True
    if low.startswith("~$"):
        return True
    if low.endswith(".synctex.gz") or ".paperdiff.bak." in low:
        return True
    suffix = Path(low).suffix
    return suffix in IGNORED_FILE_EXTS


def _ensure_root_dir(root_dir: str | Path) -> Path:
    """Validate that `root_dir` exists, is a directory, and is readable."""
    if not root_dir or not str(root_dir).strip():
        raise LocalWorkspaceError(400, "ROOT_UNBOUND", "当前项目未绑定有效的本地目录路径")
    raw = Path(str(root_dir).strip()).expanduser()
    if not raw.exists():
        raise LocalWorkspaceError(404, "ROOT_MISSING", f"绑定的本地目录不存在或已被移动：{raw}")
    if not raw.is_dir():
        raise LocalWorkspaceError(400, "NOT_A_DIR", f"指定路径不是文件夹：{raw}")
    try:
        resolved = raw.resolve(strict=True)
        # Actually probe directory listing to verify real OS read/execute permission
        with os.scandir(resolved) as it:
            next(it, None)
    except PermissionError as exc:
        raise LocalWorkspaceError(403, "ROOT_UNREADABLE", f"无权限读取本地目录：{raw}") from exc
    except OSError as exc:
        raise LocalWorkspaceError(403, "ROOT_UNREADABLE", f"无法访问本地目录：{exc}") from exc
    return resolved


def resolve_safe_path(
    root_dir: str | Path,
    rel_path: str,
    *,
    must_exist: bool = False,
    allow_dir: bool = False,
) -> Path:
    """Resolve `rel_path` strictly inside canonical `root_dir`, rejecting escapes & outside symlinks."""
    root_real = _ensure_root_dir(root_dir)
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise LocalWorkspaceError(403, "PATH_OUTSIDE_ROOT", "文件路径为空或非法")

    cleaned = rel_path.replace("\\", "/").strip()
    if "\x00" in cleaned or cleaned.startswith("/") or _WINDOWS_DRIVE_RE.match(cleaned):
        raise LocalWorkspaceError(403, "PATH_OUTSIDE_ROOT", f"禁止访问绑定目录之外的路径：{rel_path}")

    parts = [p for p in cleaned.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise LocalWorkspaceError(403, "PATH_OUTSIDE_ROOT", f"禁止路径穿越访问：{rel_path}")

    candidate = root_real.joinpath(*parts)
    try:
        target_real = candidate.resolve(strict=False)
    except OSError as exc:
        raise LocalWorkspaceError(403, "PATH_OUTSIDE_ROOT", f"无法规范化路径：{exc}") from exc

    if not target_real.is_relative_to(root_real):
        raise LocalWorkspaceError(
            403,
            "PATH_OUTSIDE_ROOT",
            f"安全拦截：路径或符号链接指向绑定根目录之外（{rel_path}）",
        )
    if target_real == root_real and not allow_dir:
        raise LocalWorkspaceError(403, "PATH_OUTSIDE_ROOT", "目标路径指向根目录而非文件")

    if must_exist:
        if not target_real.exists():
            raise LocalWorkspaceError(404, "FILE_MISSING", f"本地文件不存在或已被移除：{rel_path}")
        if not allow_dir and not target_real.is_file():
            raise LocalWorkspaceError(400, "NOT_A_FILE", f"目标路径不是普通文件：{rel_path}")
        if not allow_dir:
            try:
                with target_real.open("rb"):
                    pass
            except PermissionError as exc:
                raise LocalWorkspaceError(403, "FILE_UNREADABLE", f"无权限读取文件：{rel_path}") from exc
            except OSError as exc:
                raise LocalWorkspaceError(403, "FILE_UNREADABLE", f"无法打开文件：{exc}") from exc

    return target_real


def resolve_open_path_target(
    raw_path: str,
    existing_projects: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate and resolve a local directory or supported file for CLI/open-path binding (D-05 Option A)."""
    cleaned = (raw_path or "").strip()
    if not cleaned:
        raise LocalWorkspaceError(400, "INVALID_PATH", "路径不能为空")

    try:
        expanded = Path(cleaned).expanduser()
        target = expanded.resolve(strict=False)
    except OSError as exc:
        raise LocalWorkspaceError(400, "INVALID_PATH", f"路径格式无效：{exc}") from exc

    if not target.exists():
        raise LocalWorkspaceError(404, "PATH_NOT_FOUND", f"目标路径不存在：{cleaned}")

    if target.is_dir():
        try:
            os.listdir(target)
        except PermissionError as exc:
            raise LocalWorkspaceError(403, "PATH_UNREADABLE", f"无权读取目录：{target}") from exc
        except OSError as exc:
            raise LocalWorkspaceError(403, "PATH_UNREADABLE", f"无法访问目录：{exc}") from exc

        for proj in existing_projects:
            if proj.get("project_mode") != "local_folder" or not proj.get("local_root_path"):
                continue
            try:
                if Path(str(proj["local_root_path"])).expanduser().resolve() == target:
                    return {
                        "matched_project": proj,
                        "root_path": str(target),
                        "rel_path": None,
                        "suggested_name": str(proj.get("name") or target.name or str(target)),
                    }
            except OSError:
                continue

        return {
            "matched_project": None,
            "root_path": str(target),
            "rel_path": None,
            "suggested_name": target.name or str(target),
        }

    if not target.is_file():
        raise LocalWorkspaceError(400, "INVALID_PATH", f"目标既不是目录也不是普通文件：{target}")

    if target.suffix.lower() not in DOC_EXT_TO_FORMAT:
        raise LocalWorkspaceError(
            422,
            "UNSUPPORTED_FILE_TYPE",
            f"暂不支持直接打开该格式（{target.suffix or '无后缀'}）；支持 .tex/.ltx/.docx/.md/.txt/.zip",
        )

    try:
        with target.open("rb"):
            pass
    except PermissionError as exc:
        raise LocalWorkspaceError(403, "PATH_UNREADABLE", f"无权读取文件：{target}") from exc
    except OSError as exc:
        raise LocalWorkspaceError(403, "PATH_UNREADABLE", f"无法打开文件：{exc}") from exc

    # Prefer deepest already-bound ancestor local_folder project
    best_proj: dict[str, Any] | None = None
    best_root: Path | None = None
    best_depth = -1
    for proj in existing_projects:
        if proj.get("project_mode") != "local_folder" or not proj.get("local_root_path"):
            continue
        try:
            root = Path(str(proj["local_root_path"])).expanduser().resolve()
            if target.is_relative_to(root) and target != root:
                depth = len(root.parts)
                if depth > best_depth:
                    best_depth = depth
                    best_proj = proj
                    best_root = root
        except OSError:
            continue

    if best_proj is not None and best_root is not None:
        return {
            "matched_project": best_proj,
            "root_path": str(best_root),
            "rel_path": target.relative_to(best_root).as_posix(),
            "suggested_name": str(best_proj.get("name") or best_root.name),
        }

    parent = target.parent
    return {
        "matched_project": None,
        "root_path": str(parent),
        "rel_path": target.name,
        "suggested_name": parent.name or str(parent),
    }


def validate_root_dir(raw_path: str) -> dict[str, Any]:
    """Validate a candidate local folder path and return its canonical path & primary doc count."""
    if not raw_path or not raw_path.strip():
        return {"valid": False, "error_code": "EMPTY_PATH", "detail": "请输入或选择一个本地文件夹路径"}
    p = Path(raw_path.strip()).expanduser()
    if not p.exists():
        return {"valid": False, "error_code": "NOT_FOUND", "detail": f"目录不存在：{p}"}
    if not p.is_dir():
        return {"valid": False, "error_code": "NOT_A_DIR", "detail": f"该路径不是文件夹：{p}"}
    try:
        tree = scan_local_tree(p, include_aux=False, max_depth=MAX_SCAN_DEPTH, max_entries=MAX_SCAN_ENTRIES)
    except LocalWorkspaceError as exc:
        return {"valid": False, "error_code": exc.code, "detail": exc.detail}
    return {
        "valid": True,
        "resolved_path": tree["root_path"],
        "doc_count": tree["doc_count"],
        "truncated": tree["truncated"],
        "truncated_reason": tree["truncated_reason"],
    }


def probe_root_summary(local_root_path: str | None) -> dict[str, Any]:
    """Lightweight non-throwing status probe attached to project summaries (`AC-07`, `AC-18`)."""
    if not local_root_path:
        return {"local_status": "unbound", "local_doc_count": 0}
    try:
        tree = scan_local_tree(
            local_root_path,
            include_aux=False,
            max_depth=MAX_SCAN_DEPTH,
            max_entries=MAX_SCAN_ENTRIES,
        )
        return {
            "local_status": "ok",
            "local_doc_count": int(tree["doc_count"]),
            "local_truncated": bool(tree["truncated"]),
        }
    except LocalWorkspaceError as exc:
        status = "missing" if exc.code == "ROOT_MISSING" else "unreadable"
        return {"local_status": status, "local_doc_count": 0, "local_error": exc.detail}
    except Exception as exc:
        return {"local_status": "unreadable", "local_doc_count": 0, "local_error": str(exc)}


def scan_local_tree(
    root_dir: str | Path,
    *,
    include_aux: bool = False,
    max_depth: int = MAX_SCAN_DEPTH,
    max_entries: int = MAX_SCAN_ENTRIES,
) -> dict[str, Any]:
    """Recursively scan a bound local folder within strict depth, entry, noise, and sandbox bounds."""
    root_real = _ensure_root_dir(root_dir)
    root_stat = root_real.stat()
    visited_dirs: set[tuple[int, int]] = {(root_stat.st_dev, root_stat.st_ino)}

    scanned_entries = 0
    doc_count = 0
    aux_count = 0
    truncated = False
    truncated_reason: str | None = None

    def _walk(cur_dir: Path, rel_prefix: str, depth: int) -> list[dict[str, Any]]:
        nonlocal scanned_entries, doc_count, aux_count, truncated, truncated_reason

        try:
            entries = list(os.scandir(cur_dir))
        except OSError:
            return []

        dir_items: list[os.DirEntry[str]] = []
        file_items: list[os.DirEntry[str]] = []
        for ent in entries:
            name = ent.name
            try:
                is_sym = ent.is_symlink()
                # Sandbox guard: reject any symlink whose resolved target escapes root_real
                if is_sym:
                    resolved_ent = Path(ent.path).resolve(strict=False)
                    if not resolved_ent.is_relative_to(root_real):
                        continue
                if ent.is_dir(follow_symlinks=True):
                    if not _is_ignored_dir(name):
                        dir_items.append(ent)
                elif ent.is_file(follow_symlinks=True):
                    if not _is_ignored_file(name):
                        file_items.append(ent)
            except OSError:
                continue

        dir_items.sort(key=lambda e: _natural_sort_key(e.name))
        file_items.sort(key=lambda e: _natural_sort_key(e.name))

        nodes: list[dict[str, Any]] = []

        for ent in dir_items:
            if scanned_entries >= max_entries:
                truncated = True
                truncated_reason = f"目录扫描条目超过安全上限（{max_entries} 项），其余内容已截断"
                break
            try:
                resolved_d = Path(ent.path).resolve(strict=True)
                if not resolved_d.is_relative_to(root_real):
                    continue
                st = resolved_d.stat()
            except OSError:
                continue
            dir_key = (st.st_dev, st.st_ino)
            if dir_key in visited_dirs:
                continue

            if depth >= max_depth:
                truncated = True
                truncated_reason = f"目录嵌套层级超过安全上限（{max_depth} 层），更深目录已截断"
                continue

            visited_dirs.add(dir_key)
            scanned_entries += 1
            child_rel = f"{rel_prefix}/{ent.name}" if rel_prefix else ent.name
            children = _walk(resolved_d, child_rel, depth + 1)
            if children:
                nodes.append(
                    {
                        "name": ent.name,
                        "rel_path": child_rel,
                        "node_type": "dir",
                        "children": children,
                    }
                )

        for ent in file_items:
            if scanned_entries >= max_entries:
                truncated = True
                truncated_reason = f"目录扫描条目超过安全上限（{max_entries} 项），其余内容已截断"
                break
            suffix = Path(ent.name).suffix.lower()
            if suffix in DOC_EXT_TO_FORMAT:
                kind = "doc"
                fmt = DOC_EXT_TO_FORMAT[suffix]
            elif include_aux and suffix in AUX_EXT_TO_KIND:
                kind = "aux"
                fmt = AUX_EXT_TO_KIND[suffix]
            else:
                continue

            try:
                resolved_f = Path(ent.path).resolve(strict=True)
                if not resolved_f.is_relative_to(root_real):
                    continue
                st = resolved_f.stat()
            except OSError:
                continue

            scanned_entries += 1
            if kind == "doc":
                doc_count += 1
            else:
                aux_count += 1
            file_rel = f"{rel_prefix}/{ent.name}" if rel_prefix else ent.name
            nodes.append(
                {
                    "name": ent.name,
                    "rel_path": file_rel,
                    "node_type": "file",
                    "kind": kind,
                    "format": fmt,
                    "ext": suffix,
                    "size_bytes": int(st.st_size),
                    "mtime_ms": int(st.st_mtime * 1000),
                }
            )

        return nodes

    nodes = _walk(root_real, "", 0)
    return {
        "root_path": str(root_real),
        "nodes": nodes,
        "doc_count": doc_count,
        "aux_count": aux_count,
        "scanned_entries": scanned_entries,
        "truncated": truncated,
        "truncated_reason": truncated_reason,
        "max_depth": max_depth,
        "max_entries": max_entries,
    }


# ============================================================================
# Zero-Upload Direct File Reading & Context Resource Resolution (W2-T05 / T06)
# ============================================================================

_TEX_INPUT_RE = re.compile(r"(?<!\\)\\(?:input|include)\s*\{([^}\n]+)\}")
_TEX_GRAPHIC_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\s*\{([^}\n]+)\}")
_TEX_BIB_RE = re.compile(r"\\(?:bibliography|addbibresource)\s*\{([^}\n]+)\}")
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)")
_HTML_IMG_RE = re.compile(r'<img\b[^>]*\bsrc=["\']([^"\']+)["\']', re.IGNORECASE)
_IMAGE_SEARCH_EXTS = ("", ".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".pdf")


def _decode_text_bytes(raw_bytes: bytes) -> tuple[str, str | None]:
    """Decode text bytes gracefully: UTF-8 -> GB18030 -> UTF-8 replacement with warning."""
    try:
        return raw_bytes.decode("utf-8-sig"), None
    except UnicodeDecodeError:
        pass
    try:
        return raw_bytes.decode("gb18030"), "检测到非 UTF-8 编码（已按 GB18030 解码展示）"
    except UnicodeDecodeError:
        return raw_bytes.decode("utf-8", errors="replace"), "检测到损坏或非 UTF-8 字节，已按容错模式解码展示"


def _resolve_in_root_candidate(root_real: Path, base_dir: Path, raw_ref: str) -> Path | None:
    """Resolve a relative reference (`\\input`, image, `.bib`) strictly inside `root_real`."""
    cleaned = raw_ref.strip().strip('"').strip("'").replace("\\", "/")
    if not cleaned or "\x00" in cleaned or cleaned.startswith(("http://", "https://", "data:", "asset://")):
        return None
    if cleaned.startswith("/") or _WINDOWS_DRIVE_RE.match(cleaned):
        return None

    for anchor in (base_dir, root_real):
        cand = (anchor / cleaned).resolve(strict=False)
        if cand.is_relative_to(root_real) and cand.exists() and cand.is_file():
            return cand
    return None


def _expand_local_tex_inputs(
    root_real: Path,
    cur_file: Path,
    text: str,
    visited: set[Path],
    blocked: list[str],
    depth: int = 0,
) -> str:
    """Recursively expand safe in-root `\\input` / `\\include` directives (blocks escapes)."""
    if depth >= 8 or len(visited) >= 32:
        return text

    def _repl(match: re.Match[str]) -> str:
        ref = match.group(1).strip()
        if not ref:
            return match.group(0)
        candidates = [ref] if ref.lower().endswith(".tex") else [ref + ".tex", ref]
        resolved: Path | None = None
        for cand_ref in candidates:
            resolved = _resolve_in_root_candidate(root_real, cur_file.parent, cand_ref)
            if resolved is not None:
                break
        if resolved is None:
            if ".." in ref or ref.startswith("/"):
                blocked.append(ref)
                return ""
            return match.group(0)
        if resolved in visited or len(visited) >= 32:
            return ""
        visited.add(resolved)
        try:
            sub_text, _ = _decode_text_bytes(resolved.read_bytes())
        except OSError:
            return ""
        return _expand_local_tex_inputs(root_real, resolved, sub_text, visited, blocked, depth + 1)

    return _TEX_INPUT_RE.sub(_repl, text)


def _register_local_image(
    root_real: Path,
    base_dir: Path,
    raw_ref: str,
    asset_map: dict[str, str],
) -> None:
    """Register an in-root relative image into the deduplicated asset cache without mutating original."""
    cleaned = raw_ref.strip().strip('"').strip("'").replace("\\", "/")
    if not cleaned or cleaned.startswith(("http://", "https://", "data:", "asset://")):
        return
    resolved: Path | None = None
    for ext in _IMAGE_SEARCH_EXTS:
        cand_ref = cleaned if (ext == "" or Path(cleaned).suffix) else cleaned + ext
        resolved = _resolve_in_root_candidate(root_real, base_dir, cand_ref)
        if resolved is not None:
            break
    if resolved is None:
        return
    suffix = resolved.suffix.lower()
    if suffix not in ALLOWED_IMAGE_EXTS and suffix != ".pdf":
        return
    try:
        key = save_asset_bytes(resolved.read_bytes(), suffix)
    except OSError:
        return
    if not key:
        return

    rel_from_root = resolved.relative_to(root_real).as_posix()
    keys = {
        cleaned,
        cleaned.lower(),
        rel_from_root,
        rel_from_root.lower(),
        resolved.name,
        resolved.name.lower(),
        resolved.stem,
        resolved.stem.lower(),
        str(Path(rel_from_root).with_suffix("")),
        str(Path(rel_from_root).with_suffix("")).lower(),
    }
    try:
        rel_from_base = resolved.relative_to(base_dir).as_posix()
        keys.update(
            {
                rel_from_base,
                rel_from_base.lower(),
                str(Path(rel_from_base).with_suffix("")),
                str(Path(rel_from_base).with_suffix("")).lower(),
            }
        )
    except ValueError:
        pass
    for k in keys:
        asset_map[k] = key


def _load_context_bibs(root_real: Path, base_dir: Path, explicit_refs: list[str]) -> dict[str, dict[str, str]]:
    """Load referenced and sibling `.bib` files strictly inside `root_real`."""
    bib_files: list[Path] = []
    seen: set[Path] = set()

    for raw_ref in explicit_refs:
        for item in raw_ref.split(","):
            item = item.strip()
            if not item:
                continue
            cands = [item] if item.lower().endswith(".bib") else [item + ".bib", item]
            for c in cands:
                resolved = _resolve_in_root_candidate(root_real, base_dir, c)
                if resolved and resolved not in seen:
                    seen.add(resolved)
                    bib_files.append(resolved)
                    break

    for search_dir in (base_dir, root_real):
        try:
            for ent in sorted(os.scandir(search_dir), key=lambda e: e.name.lower()):
                if len(bib_files) >= 10:
                    break
                if ent.name.lower().endswith(".bib") and ent.is_file():
                    p = Path(ent.path).resolve(strict=False)
                    if p.is_relative_to(root_real) and p not in seen:
                        seen.add(p)
                        bib_files.append(p)
        except OSError:
            continue

    merged: dict[str, dict[str, str]] = {}
    for bf in bib_files:
        try:
            txt, _ = _decode_text_bytes(bf.read_bytes())
            merged.update(parse_bibtex_entries(txt))
        except OSError:
            continue
    return merged


def read_local_file_for_analysis(
    root_dir: str | Path,
    rel_path: str,
    *,
    track_mode: str = "after",
) -> dict[str, Any]:
    """Read and decode a bound local file strictly read-only with in-root context assets & `.bib`."""
    root_real = _ensure_root_dir(root_dir)
    target = resolve_safe_path(root_real, rel_path, must_exist=True)
    norm_rel = target.relative_to(root_real).as_posix()

    try:
        raw_bytes = target.read_bytes()
        st = target.stat()
    except PermissionError as exc:
        raise LocalWorkspaceError(403, "FILE_UNREADABLE", f"无权限读取文件：{rel_path}") from exc
    except OSError as exc:
        raise LocalWorkspaceError(403, "FILE_UNREADABLE", f"读取文件失败：{exc}") from exc

    file_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    mtime_ms = int(st.st_mtime * 1000)
    size_bytes = len(raw_bytes)
    suffix = target.suffix.lower()

    tracked_changes_info: dict[str, Any] | None = None
    encoding_warning: str | None = None
    blocked_inputs: list[str] = []

    if suffix == ".docx":
        try:
            content, meta = extract_docx_with_assets(raw_bytes, track_mode=track_mode)
            tracked_changes_info = inspect_docx_tracked_changes(raw_bytes)
        except Exception as exc:
            raise LocalWorkspaceError(
                422,
                "FILE_CORRUPTED",
                f"无法解析 Word 文档（文件可能已损坏或正在被其他软件写入）：{norm_rel}",
            ) from exc
        fmt = "docx"
    elif suffix == ".zip":
        try:
            _root_name, content, meta = extract_latex_zip_with_assets(raw_bytes)
        except Exception as exc:
            raise LocalWorkspaceError(
                422,
                "FILE_CORRUPTED",
                f"无法解析 LaTeX 压缩包（ZIP 可能已损坏）：{norm_rel}",
            ) from exc
        fmt = "latex"
    elif suffix == ".tex":
        raw_text, encoding_warning = _decode_text_bytes(raw_bytes)
        expanded = _expand_local_tex_inputs(
            root_real, target, raw_text, {target}, blocked_inputs, depth=0
        )
        asset_map: dict[str, str] = {}
        for gm in _TEX_GRAPHIC_RE.finditer(expanded):
            _register_local_image(root_real, target.parent, gm.group(1), asset_map)
        bib_refs = [bm.group(1) for bm in _TEX_BIB_RE.finditer(expanded)]
        bib_entries = _load_context_bibs(root_real, target.parent, bib_refs)
        content = expanded
        meta = {"assets": asset_map, "bib": bib_entries, "blocked_inputs": blocked_inputs}
        fmt = "latex"
    elif suffix in (".md", ".markdown", ".txt"):
        raw_text, encoding_warning = _decode_text_bytes(raw_bytes)
        asset_map = {}
        for im in _MD_IMAGE_RE.finditer(raw_text):
            _register_local_image(root_real, target.parent, im.group(1), asset_map)
        for im in _HTML_IMG_RE.finditer(raw_text):
            _register_local_image(root_real, target.parent, im.group(1), asset_map)
        bib_entries = _load_context_bibs(root_real, target.parent, [])
        content = raw_text
        meta = {"assets": asset_map, "bib": bib_entries}
        fmt = detect_format(target.name, raw_text)
    else:
        raise LocalWorkspaceError(
            415,
            "UNSUPPORTED_FORMAT",
            f"当前文件格式不支持作为学术文稿直读：{norm_rel}",
        )

    return {
        "rel_path": norm_rel,
        "filename": target.name,
        "format": fmt,
        "content": content,
        "meta": meta,
        "raw_bytes": raw_bytes,
        "file_sha256": file_sha256,
        "mtime_ms": mtime_ms,
        "size_bytes": size_bytes,
        "tracked_changes_info": tracked_changes_info,
        "encoding_warning": encoding_warning,
        "blocked_inputs": blocked_inputs,
    }


def read_local_raw_file(root_dir: str | Path, rel_path: str) -> tuple[bytes, str, str]:
    """Read raw binary bytes of a sandboxed file (for local `.docx` Word Original view or aux images)."""
    target = resolve_safe_path(root_dir, rel_path, must_exist=True)
    try:
        data = target.read_bytes()
    except PermissionError as exc:
        raise LocalWorkspaceError(403, "FILE_UNREADABLE", f"无权限读取文件：{rel_path}") from exc
    except OSError as exc:
        raise LocalWorkspaceError(403, "FILE_UNREADABLE", f"读取文件失败：{exc}") from exc
    mime, _ = mimetypes.guess_type(target.name)
    if target.suffix.lower() == ".docx":
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return data, mime or "application/octet-stream", target.name


# ============================================================================
# External Change Stat Probe & Safe Lossless Disk Write-Back (W2-T08 / T09)
# ============================================================================

def stat_local_files(root_dir: str | Path, rel_paths: list[str]) -> dict[str, Any]:
    """Compute lightweight exists/mtime/size/sha256 status for one or more in-root files (D-06)."""
    root_real = _ensure_root_dir(root_dir)
    files_out: dict[str, dict[str, Any]] = {}
    for rp in rel_paths:
        target = resolve_safe_path(root_real, rp, must_exist=False)
        norm_rel = target.relative_to(root_real).as_posix()
        if not target.exists() or not target.is_file():
            files_out[norm_rel] = {
                "exists": False,
                "mtime_ms": None,
                "size_bytes": None,
                "sha256": None,
            }
            continue
        try:
            raw = target.read_bytes()
            st = target.stat()
        except PermissionError as exc:
            raise LocalWorkspaceError(403, "FILE_UNREADABLE", f"无权限读取文件：{norm_rel}") from exc
        except OSError as exc:
            raise LocalWorkspaceError(403, "FILE_UNREADABLE", f"读取文件状态失败：{exc}") from exc
        files_out[norm_rel] = {
            "exists": True,
            "mtime_ms": int(st.st_mtime * 1000),
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    return {"root_status": "ok", "root_path": str(root_real), "files": files_out}


def _next_available_revised_path(source: Path) -> Path:
    stem = source.stem
    suffix = source.suffix
    cand = source.parent / f"{stem}_revised{suffix}"
    if not cand.exists():
        return cand
    idx = 2
    while True:
        cand = source.parent / f"{stem}_revised_{idx}{suffix}"
        if not cand.exists():
            return cand
        idx += 1


def _next_backup_path(source: Path) -> Path:
    stem = source.stem
    suffix = source.suffix
    cand = source.parent / f"{stem}.paperdiff.bak{suffix}"
    if not cand.exists():
        return cand
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    cand = source.parent / f"{stem}.paperdiff.bak.{ts}{suffix}"
    idx = 2
    while cand.exists():
        cand = source.parent / f"{stem}.paperdiff.bak.{ts}_{idx}{suffix}"
        idx += 1
    return cand


def _atomic_write_bytes(dest: Path, data: bytes) -> None:
    """Write bytes to `dest` atomically via same-directory temp file + `os.replace`."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=str(dest.parent),
            prefix=".paperdiff_tmp_",
            delete=False,
        ) as tf:
            tmp_path = Path(tf.name)
            tf.write(data)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(tmp_path, dest)
    except PermissionError as exc:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise LocalWorkspaceError(403, "FILE_UNWRITABLE", f"无权限写入目标文件：{dest.name}") from exc
    except OSError as exc:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise LocalWorkspaceError(500, "WRITE_FAILED", f"写入本地文件失败：{exc}") from exc


def save_local_file_edits(
    root_dir: str | Path,
    rel_path: str,
    *,
    patches: list[dict[str, Any]] | None = None,
    paragraph_edits: dict[int, str] | None = None,
    mode: str = "save_as",
    target_rel_path: str | None = None,
    expected_sha256: str | None = None,
    force: bool = False,
    docx_mode: str = "clean",
    protected_terms: list[str] | None = None,
    custom_lexicon: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply lossless edits and persist safely inside bound root (`D-05` Choice C).

    - `mode == "save_as"` (default): writes to `<stem>_revised.<ext>` (or validated `target_rel_path`),
      leaving original disk file byte-for-byte untouched.
    - `mode == "overwrite"`: verifies `expected_sha256` optimistic lock (409 `EXTERNAL_MODIFIED` on
      conflict unless `force=True`), creates `.paperdiff.bak` backup of original bytes, then atomically
      replaces the target file.
    """
    from .analyzer import preview_document
    from .export import apply_single_document_edits
    from .patcher import apply_typed_patches

    root_real = _ensure_root_dir(root_dir)
    source = resolve_safe_path(root_real, rel_path, must_exist=True)
    doc_data = read_local_file_for_analysis(root_real, rel_path)

    if expected_sha256 and doc_data["file_sha256"] != expected_sha256 and not force:
        raise LocalWorkspaceError(
            409,
            "EXTERNAL_MODIFIED",
            "磁盘文件已在外部被修改，请先确认是否覆盖或改为另存为新文件",
        )

    prev = preview_document(
        content=doc_data["content"],
        fmt=doc_data["format"],
        filename=doc_data["filename"],
        protected_terms=protected_terms or [],
        custom_lexicon=custom_lexicon,
        meta=doc_data["meta"],
    )

    warnings: list[str] = []
    suffix = source.suffix.lower()
    is_binary = suffix in (".docx", ".zip")
    orig_blob = doc_data["raw_bytes"] if is_binary else None

    if patches:
        pres = apply_typed_patches(
            content=doc_data["content"],
            fmt=prev["format"],
            blocks=prev["blocks"],
            ops=patches,
            orig_blob_bytes=orig_blob,
            source_map=doc_data["meta"].get("source_map"),
            docx_mode=docx_mode,
        )
        warnings = list(pres.get("warnings") or [])
        if is_binary:
            if not pres.get("patched_blob_bytes"):
                raise LocalWorkspaceError(422, "PATCH_FAILED", "原格式二进制补丁生成失败，未写入磁盘")
            out_bytes = bytes(pres["patched_blob_bytes"])
        else:
            out_bytes = str(pres["patched_content"]).encode("utf-8")
    elif paragraph_edits:
        if is_binary:
            # Convert paragraph_edits into replace_block ops so binary .docx/.zip preserves template XML
            conv_ops = [
                {"op": "replace_block", "block_index": int(k), "new_raw": str(v)}
                for k, v in paragraph_edits.items()
            ]
            pres = apply_typed_patches(
                content=doc_data["content"],
                fmt=prev["format"],
                blocks=prev["blocks"],
                ops=conv_ops,
                orig_blob_bytes=orig_blob,
                source_map=doc_data["meta"].get("source_map"),
                docx_mode=docx_mode,
            )
            warnings = list(pres.get("warnings") or [])
            out_bytes = bytes(pres["patched_blob_bytes"] or doc_data["raw_bytes"])
        else:
            patched_txt = apply_single_document_edits(
                doc_data["content"], prev["format"], prev, {int(k): str(v) for k, v in paragraph_edits.items()}
            )
            out_bytes = patched_txt.encode("utf-8")
    else:
        out_bytes = doc_data["raw_bytes"]

    norm_mode = "overwrite" if mode == "overwrite" else "save_as"
    backup_rel: str | None = None

    if norm_mode == "overwrite":
        dest = source
        backup_path = _next_backup_path(source)
        _atomic_write_bytes(backup_path, doc_data["raw_bytes"])
        backup_rel = backup_path.relative_to(root_real).as_posix()
        _atomic_write_bytes(dest, out_bytes)
    else:
        if target_rel_path and target_rel_path.strip():
            dest = resolve_safe_path(root_real, target_rel_path.strip(), must_exist=False)
            if dest == source:
                dest = _next_available_revised_path(source)
        else:
            dest = _next_available_revised_path(source)
        _atomic_write_bytes(dest, out_bytes)

    new_st = dest.stat()
    return {
        "saved": True,
        "mode": norm_mode,
        "target_rel_path": dest.relative_to(root_real).as_posix(),
        "backup_rel_path": backup_rel,
        "new_sha256": hashlib.sha256(out_bytes).hexdigest(),
        "new_mtime_ms": int(new_st.st_mtime * 1000),
        "warnings": warnings,
    }
