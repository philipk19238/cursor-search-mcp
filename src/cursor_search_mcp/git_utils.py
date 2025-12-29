"""Git utilities for auto-detecting repository information."""

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class RepoInfo:
    """Repository information extracted from git."""

    name: str
    owner: str
    workspace_path: str
    remote_url: Optional[str] = None


def _parse_git_remote_url(url: str) -> tuple[str, str]:
    """Parse owner and repo name from a git remote URL.

    Supports:
    - git@github.com:owner/repo.git
    - https://github.com/owner/repo.git
    - https://github.com/owner/repo
    - git@gitlab.com:owner/repo.git
    - etc.
    """
    # SSH format: git@github.com:owner/repo.git
    ssh_match = re.match(r"git@[\w.-]+:(.+?)/(.+?)(?:\.git)?$", url)
    if ssh_match:
        return ssh_match.group(1), ssh_match.group(2)

    # HTTPS format: https://github.com/owner/repo.git
    https_match = re.match(r"https?://[\w.-]+/(.+?)/(.+?)(?:\.git)?$", url)
    if https_match:
        return https_match.group(1), https_match.group(2)

    raise ValueError(f"Could not parse git remote URL: {url}")


def _find_git_root(start_path: Path) -> Optional[Path]:
    """Find the git root directory starting from the given path."""
    current = start_path.resolve()

    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent

    # Check root as well
    if (current / ".git").exists():
        return current

    return None


def _get_git_remote_url(git_root: Path, remote: str = "origin") -> Optional[str]:
    """Get the URL for a git remote."""
    try:
        result = subprocess.run(
            ["git", "-C", str(git_root), "remote", "get-url", remote],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def detect_repo_info(workspace_path: Optional[str] = None) -> RepoInfo:
    """Auto-detect repository information from the current directory.

    Args:
        workspace_path: Optional path to start searching from.
                       Defaults to current working directory.

    Returns:
        RepoInfo with detected repository information.

    Raises:
        ValueError: If not in a git repository or can't parse remote URL.
    """
    # Determine starting path
    if workspace_path:
        start_path = Path(workspace_path)
    else:
        start_path = Path.cwd()

    # Find git root
    git_root = _find_git_root(start_path)
    if not git_root:
        raise ValueError(
            f"Not in a git repository: {start_path}\n"
            "Please run from within a git repository or set CURSOR_REPO_NAME and CURSOR_REPO_OWNER."
        )

    # Get remote URL
    remote_url = _get_git_remote_url(git_root)
    if not remote_url:
        raise ValueError(
            f"No 'origin' remote found in {git_root}\n"
            "Please set up a git remote or set CURSOR_REPO_NAME and CURSOR_REPO_OWNER."
        )

    # Parse owner and repo
    try:
        owner, name = _parse_git_remote_url(remote_url)
    except ValueError as e:
        raise ValueError(
            f"{e}\n"
            "Please set CURSOR_REPO_NAME and CURSOR_REPO_OWNER manually."
        )

    return RepoInfo(
        name=name,
        owner=owner,
        workspace_path=str(git_root),
        remote_url=remote_url,
    )


def get_repo_info() -> RepoInfo:
    """Get repository info, with environment variable override support.

    Priority:
    1. Environment variables (CURSOR_REPO_NAME, CURSOR_REPO_OWNER)
    2. Auto-detect from git remote

    Returns:
        RepoInfo with repository information.
    """
    env_name = os.environ.get("CURSOR_REPO_NAME")
    env_owner = os.environ.get("CURSOR_REPO_OWNER")
    env_workspace = os.environ.get("CURSOR_WORKSPACE_PATH")

    # If both env vars are set, use them
    if env_name and env_owner:
        return RepoInfo(
            name=env_name,
            owner=env_owner,
            workspace_path=env_workspace or os.getcwd(),
        )

    # Auto-detect from git
    try:
        detected = detect_repo_info(env_workspace)

        # Allow partial override
        return RepoInfo(
            name=env_name or detected.name,
            owner=env_owner or detected.owner,
            workspace_path=env_workspace or detected.workspace_path,
            remote_url=detected.remote_url,
        )
    except ValueError as e:
        if env_name or env_owner:
            # Partial config - need both
            raise ValueError(
                "Partial configuration detected. Please set both "
                "CURSOR_REPO_NAME and CURSOR_REPO_OWNER, or run from a git repository."
            )
        raise
