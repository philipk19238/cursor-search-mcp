"""Git utilities for repo detection."""

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class RepoInfo:
    name: str
    owner: str
    workspace_path: str
    remote_url: Optional[str] = None


def _parse_git_remote_url(url: str) -> tuple[str, str]:
    """Parse owner and repo name from a git remote URL."""
    ssh_match = re.match(r"git@[\w.-]+:(.+?)/(.+?)(?:\.git)?$", url)
    if ssh_match:
        return ssh_match.group(1), ssh_match.group(2)

    https_match = re.match(r"https?://[\w.-]+/(.+?)/(.+?)(?:\.git)?$", url)
    if https_match:
        return https_match.group(1), https_match.group(2)

    raise ValueError(f"Could not parse git remote URL: {url}")


def _find_git_root(start_path: Path) -> Optional[Path]:
    current = start_path.resolve()

    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent

    if (current / ".git").exists():
        return current

    return None


def _get_git_remote_url(git_root: Path, remote: str = "origin") -> Optional[str]:
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
    if workspace_path:
        start_path = Path(workspace_path)
    else:
        start_path = Path.cwd()

    git_root = _find_git_root(start_path)
    if not git_root:
        raise ValueError(f"Not in a git repository: {start_path}")

    remote_url = _get_git_remote_url(git_root)
    if not remote_url:
        raise ValueError(f"No 'origin' remote found in {git_root}")

    try:
        owner, name = _parse_git_remote_url(remote_url)
    except ValueError as e:
        raise ValueError(
            f"{e}. Set CURSOR_REPO_NAME and CURSOR_REPO_OWNER to override."
        )

    return RepoInfo(
        name=name,
        owner=owner,
        workspace_path=str(git_root),
        remote_url=remote_url,
    )


def get_repo_info() -> RepoInfo:
    env_name = os.environ.get("CURSOR_REPO_NAME")
    env_owner = os.environ.get("CURSOR_REPO_OWNER")
    env_workspace = os.environ.get("CURSOR_WORKSPACE_PATH")

    if env_name and env_owner:
        return RepoInfo(
            name=env_name,
            owner=env_owner,
            workspace_path=env_workspace or os.getcwd(),
        )

    try:
        detected = detect_repo_info(env_workspace)

        return RepoInfo(
            name=env_name or detected.name,
            owner=env_owner or detected.owner,
            workspace_path=env_workspace or detected.workspace_path,
            remote_url=detected.remote_url,
        )
    except ValueError:
        if env_name or env_owner:
            raise ValueError("Set both CURSOR_REPO_NAME and CURSOR_REPO_OWNER.")
        raise
