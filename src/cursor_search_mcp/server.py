from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

from .auth import get_auth_id_from_token, get_credentials
from .client import CursorSearchClient, SearchResult
from .db import (
    find_repo_for_workspace,
    get_repo_keys_for_workspace,
    list_indexed_repos_formatted,
)
from .encryption import build_path_encryption_scheme, encrypt_path
from .git_utils import RepoInfo, get_repo_info

mcp = FastMCP(
    "Cursor Codebase Search",
    instructions="Semantic code search via Cursor's index.",
)

_cached_repo_info: Optional[RepoInfo] = None


def _get_repo_info(refresh: bool = False) -> RepoInfo:
    global _cached_repo_info

    if _cached_repo_info is None or refresh:
        indexed_repo = None
        try:
            indexed_repo = find_repo_for_workspace()
        except Exception:
            indexed_repo = None

        if indexed_repo:
            _cached_repo_info = RepoInfo(
                name=indexed_repo.name,
                owner=indexed_repo.owner,
                workspace_path=indexed_repo.local_path,
                remote_url=f"https://github.com/{indexed_repo.owner}/{indexed_repo.name}",
            )
        else:
            _cached_repo_info = get_repo_info()

    return _cached_repo_info


def _get_search_client() -> CursorSearchClient:
    credentials = get_credentials()
    repo_info = _get_repo_info()
    auth_id = get_auth_id_from_token(credentials.access_token)
    cursor_keys = get_repo_keys_for_workspace(repo_info.workspace_path)

    if cursor_keys and auth_id:
        repo_name = cursor_keys.repo_name
        repo_owner = auth_id
        orthogonal_transform_seed = cursor_keys.orthogonal_transform_seed
        is_local = True
        is_tracked = False
        remote_url = None
        path_encryption_key = cursor_keys.path_encryption_key
        if path_encryption_key:
            scheme = build_path_encryption_scheme(path_encryption_key)
            workspace_uri = encrypt_path(
                Path(repo_info.workspace_path).resolve().as_uri(),
                scheme,
            )
        else:
            workspace_uri = None
    else:
        repo_name = repo_info.name
        repo_owner = repo_info.owner
        orthogonal_transform_seed = None
        is_local = False
        is_tracked = True
        remote_url = repo_info.remote_url
        path_encryption_key = None
        workspace_uri = None

    return CursorSearchClient(
        credentials=credentials,
        repo_name=repo_name,
        repo_owner=repo_owner,
        workspace_path=repo_info.workspace_path,
        remote_url=remote_url,
        is_tracked=is_tracked,
        is_local=is_local,
        orthogonal_transform_seed=orthogonal_transform_seed,
        path_encryption_key=path_encryption_key,
        workspace_uri=workspace_uri,
    )


def _format_search_results(result: SearchResult, explanation: str) -> str:
    if not result.chunks:
        return f"No results for: {result.query}"

    output_parts = [f"## {result.query}", f"{len(result.chunks)} results"]
    if explanation:
        output_parts.append(f"Note: {explanation}")
    output_parts.append("")

    for i, chunk in enumerate(result.chunks, 1):
        output_parts.extend(
            [
                f"### {i}. {chunk.file_path}",
                f"Lines {chunk.start_line}-{chunk.end_line} (score: {chunk.score:.3f})",
                "",
                "```",
                chunk.content.strip(),
                "```",
                "",
            ]
        )

    return "\n".join(output_parts)


@mcp.tool
def codebase_search(
    query: str,
    explanation: str = "",
    target_directories: Optional[list[str]] = None,
    repo_owner: Optional[str] = None,
    repo_name: Optional[str] = None,
) -> str:
    """Semantic search that finds code by meaning, not exact text.

    ### When to Use This Tool

    Use `codebase_search` when you need to:
    - Explore unfamiliar codebases
    - Ask "how / where / what" questions to understand behavior
    - Find code by meaning rather than exact text

    ### When NOT to Use

    Skip `codebase_search` for:
    1. Exact text matches (use `grep`)
    2. Reading known files (use `read_file`)
    3. Simple symbol lookups (use `grep`)
    4. Find file by name (use `file_search`)

    ### Examples

    Good queries:
    - "Where is interface MyInterface implemented in the frontend?"
    - "Where do we encrypt user passwords before saving?"
    - "How does user authentication work?"

    Bad queries:
    - "MyInterface frontend" - Too vague, use a specific question
    - "AuthService" - Single word, use grep instead
    - "What is AuthService? How does it work?" - Split into separate searches

    ### Target Directories

    Provide ONE directory or file path; [] searches the whole repo. No globs.

    Good:
    - ["backend/api/"] - focus directory
    - ["src/components/Button.tsx"] - single file
    - [] - search everywhere when unsure

    Bad:
    - ["frontend/", "backend/"] - multiple paths
    - ["src/**/utils/**"] - globs
    - ["*.ts"] - wildcards

    ### Search Strategy

    1. Start broad with [] if unsure where relevant code is
    2. Review results; if a directory stands out, rerun with that as target
    3. Break large questions into smaller ones
    4. For big files (>1K lines), use codebase_search scoped to that file

    ### Usage Notes

    - When full chunk contents are provided, avoid re-reading the same chunks
    - Sometimes only chunk signatures are shown; use read_file or grep to explore
    - When reading chunks, consider expanding ranges to include imports

    Args:
        query: A complete question about what you want to understand.
               Ask as if talking to a colleague: 'How does X work?',
               'What happens when Y?', 'Where is Z handled?'
        explanation: Why this tool is being used, how it contributes to goal.
        target_directories: Directory paths to limit scope (single dir only).
        repo_owner: Optional GitHub repo owner override.
        repo_name: Optional GitHub repo name override.

    Returns:
        Formatted search results with file paths, line numbers, and snippets.
    """
    query = (query or "").strip()
    if not query:
        return "Error: query is required."

    target_dir = None
    if target_directories:
        for candidate in target_directories:
            if candidate:
                target_dir = candidate
                break

    try:
        if repo_owner and repo_name:
            credentials = get_credentials()
            remote_url = f"https://github.com/{repo_owner}/{repo_name}"
            client = CursorSearchClient(
                credentials=credentials,
                repo_name=repo_name,
                repo_owner=repo_owner,
                workspace_path=".",
                remote_url=remote_url,
            )
            used_repo_owner = repo_owner
            used_repo_name = repo_name
        else:
            client = _get_search_client()
            repo_info = _get_repo_info()
            used_repo_owner = repo_info.owner
            used_repo_name = repo_info.name

        with client:
            result = client.search(
                query=query,
                top_k=10,
                target_directory=target_dir,
                rerank=True,
            )

            if result.metadata and "error" in result.metadata:
                error_msg = result.metadata["error"]
                if (
                    "not found" in error_msg.lower()
                    or "not indexed" in error_msg.lower()
                ):
                    return f"Codebase not indexed: {used_repo_owner}/{used_repo_name}"
                return f"API error: {error_msg}"

            return _format_search_results(result, explanation)

    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def ensure_codebase_indexed() -> str:
    """Ensure the current codebase index exists."""
    try:
        with _get_search_client() as client:
            return (
                "Codebase index is ready."
                if client.ensure_index_created()
                else "Codebase index not ready."
            )
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def refresh_repo_info() -> str:
    """Refresh cached repository info."""
    try:
        repo_info = _get_repo_info(refresh=True)
        indexed_repo = find_repo_for_workspace(repo_info.workspace_path)
        index_status = "indexed" if indexed_repo else "not indexed"
        return (
            f"{repo_info.owner}/{repo_info.name} ({index_status})\n"
            f"{repo_info.workspace_path}"
        )
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def list_indexed_repos() -> str:
    try:
        return list_indexed_repos_formatted()
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {e}"


@mcp.resource("cursor://status")
def get_status() -> str:
    try:
        credentials = get_credentials()
        auth_id = get_auth_id_from_token(credentials.access_token)
        auth_status = "configured" if credentials.access_token else "missing"

        try:
            repo_info = _get_repo_info()
            repo_str = f"{repo_info.owner}/{repo_info.name}"
            workspace_str = repo_info.workspace_path
            cursor_keys = get_repo_keys_for_workspace(repo_info.workspace_path)
            if cursor_keys and auth_id:
                internal_str = f"{auth_id}/{cursor_keys.repo_name}"
            else:
                internal_str = "unavailable"
        except Exception as e:
            repo_str = f"Error: {e}"
            workspace_str = str(Path.cwd())
            internal_str = "unavailable"

        return (
            "Cursor Search MCP\n"
            f"- Auth: {auth_status}\n"
            f"- Repo: {repo_str}\n"
            f"- Workspace: {workspace_str}\n"
            f"- Internal Repo: {internal_str}\n"
        )
    except Exception as e:
        return f"Status error: {e}"


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
