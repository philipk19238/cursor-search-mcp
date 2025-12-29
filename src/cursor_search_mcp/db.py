"""Utilities for Cursor's local SQLite databases."""

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

from .auth import get_cursor_dir


@dataclass
class IndexedRepo:
    """Information about an indexed repository."""

    owner: str
    name: str
    local_path: str
    last_accessed: int
    full_key: str  # e.g., "github.com/owner/repo"


@dataclass
class CursorRepoKeys:
    """Cursor internal repository keys for a workspace."""

    repo_name: str
    orthogonal_transform_seed: Optional[float]
    path_encryption_key: Optional[str]
    legacy_repo_name: str


def _get_cursor_db_path() -> Path:
    return get_cursor_dir() / "User" / "globalStorage" / "state.vscdb"


def _get_workspace_storage_base() -> Path:
    return get_cursor_dir() / "User" / "workspaceStorage"


def _parse_workspace_folder_uri(uri: str) -> Optional[str]:
    if not uri or not uri.startswith("file://"):
        return None

    parsed = urlparse(uri)
    path = unquote(parsed.path)

    # Windows file URIs look like /C:/path; trim leading slash.
    if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]

    return path


def find_workspace_storage_dir(workspace_path: Optional[str] = None) -> Optional[Path]:
    base = _get_workspace_storage_base()
    if not base.exists():
        return None

    if workspace_path is None:
        workspace_path = os.getcwd()

    workspace_path = os.path.abspath(workspace_path)

    candidates: list[tuple[int, int, Path]] = []

    for entry in base.iterdir():
        if not entry.is_dir():
            continue

        workspace_json = entry / "workspace.json"
        if not workspace_json.exists():
            continue

        data = json.loads(workspace_json.read_text())

        folder_uri = data.get("folder")
        folder_path = _parse_workspace_folder_uri(folder_uri) if folder_uri else None
        if not folder_path:
            continue

        folder_path = os.path.abspath(folder_path)

        if folder_path == workspace_path:
            # Exact match, highest priority.
            candidates.append((0, 0, entry))
            continue

        if workspace_path.startswith(folder_path + os.sep):
            # Workspace is inside this folder; prefer the closest ancestor.
            candidates.append((1, -len(folder_path), entry))
            continue

        if folder_path.startswith(workspace_path + os.sep):
            # Folder is inside workspace; prefer the closest child.
            candidates.append((2, len(folder_path), entry))
            continue

    if candidates:
        candidates.sort()
        return candidates[0][2]

    return None


def _query_db_at_path(db_path: Path, query: str, params: tuple = ()) -> list:
    if not db_path.exists():
        raise FileNotFoundError(f"Cursor database not found at {db_path}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".vscdb") as tmp:
        tmp_path = tmp.name

    try:
        shutil.copy2(db_path, tmp_path)
        conn = sqlite3.connect(tmp_path)
        cursor = conn.cursor()
        cursor.execute(query, params)
        results = cursor.fetchall()
        conn.close()
        return results
    finally:
        os.unlink(tmp_path)


def _load_workspace_retrieval_state(
    workspace_path: Optional[str] = None,
) -> Optional[dict]:
    storage_dir = find_workspace_storage_dir(workspace_path)
    if storage_dir is None:
        return None

    db_path = storage_dir / "state.vscdb"
    results = _query_db_at_path(
        db_path,
        "SELECT value FROM ItemTable WHERE key = 'anysphere.cursor-retrieval'",
    )

    if not results or not results[0][0]:
        return None

    return json.loads(results[0][0])


def compute_legacy_repo_name(workspace_paths: list[str]) -> str:
    normalized = [os.path.abspath(p).rstrip(os.sep) for p in workspace_paths]
    normalized.sort()

    joined_paths = "-".join(normalized)
    repo_names = "-".join(os.path.basename(p) for p in normalized)

    digest = hashlib.sha256(joined_paths.encode("utf-8")).hexdigest()
    return f"{digest}-{repo_names}"


def get_repo_keys_for_workspace(
    workspace_path: Optional[str] = None,
) -> Optional[CursorRepoKeys]:
    if workspace_path is None:
        workspace_path = os.getcwd()

    state = _load_workspace_retrieval_state(workspace_path)
    if not state:
        return None

    legacy_repo_name = compute_legacy_repo_name([workspace_path])
    repo_key = f"map/{legacy_repo_name}/repoKeys"
    repo_keys = state.get(repo_key)
    if not repo_keys:
        return None

    return CursorRepoKeys(
        repo_name=repo_keys.get("repoName", ""),
        orthogonal_transform_seed=repo_keys.get("orthogonalTransformationSeed"),
        path_encryption_key=repo_keys.get("pathEncryptionKey"),
        legacy_repo_name=legacy_repo_name,
    )


def _query_db(query: str, params: tuple = ()) -> list:
    db_path = _get_cursor_db_path()
    if not db_path.exists():
        raise FileNotFoundError(f"Cursor database not found at {db_path}")
    return _query_db_at_path(db_path, query, params)


def get_indexed_repos() -> list[IndexedRepo]:
    results = _query_db(
        "SELECT value FROM ItemTable WHERE key = 'repositoryTracker.paths'"
    )

    if not results or not results[0][0]:
        return []

    data = json.loads(results[0][0])

    repos = []
    for key, info in data.items():
        # Parse the key format: "github.com/owner/repo"
        parts = key.split("/")
        if len(parts) >= 3:
            owner = parts[1]
            name = parts[2]

            # Parse the local path from file:// URL
            local_path = info.get("localPath", "")
            if local_path.startswith("file://"):
                local_path = unquote(local_path[7:])

            repos.append(
                IndexedRepo(
                    owner=owner,
                    name=name,
                    local_path=local_path,
                    last_accessed=info.get("lastAccessed", 0),
                    full_key=key,
                )
            )

    return repos


def find_repo_for_workspace(
    workspace_path: Optional[str] = None,
) -> Optional[IndexedRepo]:
    if workspace_path is None:
        workspace_path = os.getcwd()

    workspace_path = os.path.abspath(workspace_path)

    repos = get_indexed_repos()

    # Find exact match first
    for repo in repos:
        if os.path.abspath(repo.local_path) == workspace_path:
            return repo

    # Find if workspace is a subdirectory of a repo
    for repo in repos:
        repo_path = os.path.abspath(repo.local_path)
        if workspace_path.startswith(repo_path + os.sep):
            return repo

    # Find if a repo is a subdirectory of workspace
    for repo in repos:
        repo_path = os.path.abspath(repo.local_path)
        if repo_path.startswith(workspace_path + os.sep):
            return repo

    return None


def list_indexed_repos_formatted() -> str:
    repos = get_indexed_repos()

    if not repos:
        return "No indexed repositories found in Cursor database."

    lines = ["Indexed repositories:"]
    repos.sort(key=lambda r: r.last_accessed, reverse=True)

    for repo in repos:
        lines.append(f"- {repo.owner}/{repo.name} ({repo.local_path})")

    return "\n".join(lines)
