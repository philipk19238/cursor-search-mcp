"""MCP Server for Cursor's semantic codebase search."""

import os
from typing import Optional

from fastmcp import FastMCP

from .auth import get_credentials
from .client import CursorSearchClient, SearchResult
from .git_utils import get_repo_info, RepoInfo


# Initialize the MCP server
mcp = FastMCP(
    "Cursor Codebase Search",
    instructions="Semantic codebase search powered by Cursor's vector database. Use codebase_search for finding code by meaning.",
)

# Cache for repo info (can be refreshed)
_cached_repo_info: Optional[RepoInfo] = None


def _get_repo_info(refresh: bool = False) -> RepoInfo:
    """Get repository info, with caching."""
    global _cached_repo_info

    if _cached_repo_info is None or refresh:
        _cached_repo_info = get_repo_info()

    return _cached_repo_info


def _get_search_client() -> CursorSearchClient:
    """Get a configured search client."""
    credentials = get_credentials()
    repo_info = _get_repo_info()

    return CursorSearchClient(
        credentials=credentials,
        repo_name=repo_info.name,
        repo_owner=repo_info.owner,
        workspace_path=repo_info.workspace_path,
    )


def _format_search_results(result: SearchResult, explanation: str) -> str:
    """Format search results for display."""
    if not result.chunks:
        return f"No results found for query: {result.query}"

    output_parts = [
        f"## Search Results for: {result.query}",
        f"**Explanation:** {explanation}",
        f"**Found {len(result.chunks)} relevant chunks:**",
        "",
    ]

    for i, chunk in enumerate(result.chunks, 1):
        output_parts.extend([
            f"### Result {i}: {chunk.file_path}",
            f"**Lines {chunk.start_line}-{chunk.end_line}** (score: {chunk.score:.3f})",
            "",
            "```",
            chunk.content.strip(),
            "```",
            "",
        ])

    return "\n".join(output_parts)


@mcp.tool
def codebase_search(
    query: str,
    explanation: str,
    target_directories: Optional[list[str]] = None,
) -> str:
    """Semantic search that finds code by meaning, not exact text.

    Use this tool when you need to:
    - Explore unfamiliar codebases
    - Ask "how / where / what" questions to understand behavior
    - Find code by meaning rather than exact text

    Do NOT use for:
    - Exact text matches (use grep instead)
    - Reading known files (use read_file instead)
    - Simple symbol lookups (use grep instead)
    - Finding files by name (use file_search instead)

    Args:
        query: A complete question about what you want to understand.
               Ask as if talking to a colleague: 'How does X work?',
               'What happens when Y?', 'Where is Z handled?'
               BAD: Single words like "AuthService"
               BAD: Multiple questions in one query
               GOOD: "Where is interface MyInterface implemented in the frontend?"
               GOOD: "Where do we encrypt user passwords before saving?"

        explanation: One sentence explaining why this tool is being used
                    and how it contributes to the goal.

        target_directories: Prefix directory paths to limit search scope.
                           Provide ONE directory or file path, or empty list
                           to search the whole repo.
                           GOOD: ["backend/api/"] - focus directory
                           GOOD: ["src/components/Button.tsx"] - single file
                           GOOD: [] - search everywhere when unsure
                           BAD: ["frontend/", "backend/"] - multiple paths
                           BAD: ["src/**/utils/**"] - globs
                           BAD: ["*.ts"] - wildcards

    Returns:
        Formatted search results with file paths, line numbers, and code chunks.
        When full chunk contents are provided, avoid re-reading the exact same
        chunk contents using the read_file tool.

    Examples:
        # Good: Complete question with context
        codebase_search(
            query="Where is interface MyInterface implemented in the frontend?",
            explanation="Find implementation location with specific context",
            target_directories=["frontend/"]
        )

        # Good: Start broad, then narrow down
        codebase_search(
            query="How does user authentication work?",
            explanation="Find auth flow in the codebase",
            target_directories=[]
        )

        # Good: Scope to large file instead of reading entirely
        codebase_search(
            query="How are websocket connections handled?",
            explanation="File is too large to read entirely",
            target_directories=["backend/services/realtime.ts"]
        )
    """
    # Validate inputs
    if not query or len(query.strip()) < 10:
        return (
            "Error: Query too short. Please provide a complete question like "
            "'How does X work?' or 'Where is Y handled?'"
        )

    # Check for common bad patterns
    if query.count("?") > 1:
        return (
            "Error: Query contains multiple questions. Please split into separate "
            "parallel searches for better results. For example, instead of "
            "'What is AuthService? How does AuthService work?' use two separate calls."
        )

    # Handle target directories
    target_dir = None
    if target_directories:
        if len(target_directories) > 1:
            return (
                "Error: Multiple target directories provided. Please provide only ONE "
                "directory path, or use [] to search everywhere."
            )
        if target_directories[0]:
            target_dir = target_directories[0]
            # Check for glob patterns
            if "*" in target_dir or "?" in target_dir:
                return (
                    "Error: Glob patterns are not supported. Please provide a specific "
                    "directory path like 'src/components/' without wildcards."
                )

    try:
        with _get_search_client() as client:
            result = client.search(
                query=query,
                top_k=10,
                target_directory=target_dir,
                rerank=True,
            )

            # Check for API errors
            if result.metadata and "error" in result.metadata:
                error_msg = result.metadata["error"]
                if "not found" in error_msg.lower() or "not indexed" in error_msg.lower():
                    repo_info = _get_repo_info()
                    return f"""Error: Codebase not indexed.

The repository **{repo_info.owner}/{repo_info.name}** has not been indexed by Cursor yet.

**To fix this:**
1. Open this repository in Cursor IDE
2. Wait for Cursor to index the codebase (check the status bar)
3. Once indexing is complete, try the search again

Alternatively, you can try the `ensure_codebase_indexed` tool to trigger indexing.
"""
                return f"API Error: {error_msg}"

            return _format_search_results(result, explanation)

    except FileNotFoundError as e:
        return f"Error: {e}\n\nPlease ensure Cursor is installed and you're logged in."
    except Exception as e:
        return f"Error performing search: {e}"


@mcp.tool
def ensure_codebase_indexed() -> str:
    """Ensure the current codebase is indexed for semantic search.

    Call this before searching if you're not sure whether the codebase
    has been indexed. This is typically only needed once per repository.

    Returns:
        Status message indicating whether indexing was successful.
    """
    try:
        with _get_search_client() as client:
            success = client.ensure_index_created()
            if success:
                return "Codebase index is ready for semantic search."
            else:
                return "Failed to ensure index. The repository may not be configured."
    except FileNotFoundError as e:
        return f"Error: {e}\n\nPlease ensure Cursor is installed and you're logged in."
    except Exception as e:
        return f"Error ensuring index: {e}"


@mcp.tool
def refresh_repo_info() -> str:
    """Refresh the repository information by re-detecting from git.

    Use this after switching branches, changing directories, or if the
    repository info seems stale. The server will re-read the git remote
    URL and update the cached repo name and owner.

    Returns:
        Updated repository information.
    """
    try:
        repo_info = _get_repo_info(refresh=True)
        return f"""Repository info refreshed successfully!

- Repository: {repo_info.owner}/{repo_info.name}
- Workspace: {repo_info.workspace_path}
- Remote URL: {repo_info.remote_url or 'N/A'}
"""
    except Exception as e:
        return f"Error refreshing repo info: {e}"


@mcp.resource("cursor://status")
def get_status() -> str:
    """Get the current status of the Cursor search integration."""
    try:
        credentials = get_credentials()
        token_preview = credentials.access_token[:20] + "..." if credentials.access_token else "None"

        # Try to get repo info
        try:
            repo_info = _get_repo_info()
            repo_str = f"{repo_info.owner}/{repo_info.name}"
            workspace_str = repo_info.workspace_path
            remote_str = repo_info.remote_url or "N/A"
            source_str = "auto-detected from git" if repo_info.remote_url else "environment variables"
        except Exception as e:
            repo_str = f"Error: {e}"
            workspace_str = os.getcwd()
            remote_str = "N/A"
            source_str = "not configured"

        return f"""Cursor Search MCP Status:
- Authentication: Configured (token: {token_preview})
- Repository: {repo_str}
- Workspace: {workspace_str}
- Remote URL: {remote_str}
- Config Source: {source_str}

Tip: Use the refresh_repo_info tool to update after switching repos.
"""
    except Exception as e:
        return f"Status check failed: {e}"


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
