"""Protobuf encoding/decoding for Cursor API."""

import gzip
import struct
from typing import Optional

from .messages import (
    CodeBlock,
    CodeResult,
    CodeResultWithClassification,
    Position,
    Range,
    RepositoryInfo,
    SearchRepositoryRequest,
    SearchRepositoryResponse,
    SemSearchRequest,
    SemSearchResponse,
)


def build_repository_info(
    repo_name: str,
    repo_owner: str,
    relative_workspace_path: str = ".",
    remote_url: Optional[str] = None,
    is_tracked: bool = True,
    is_local: bool = False,
    num_files: Optional[int] = None,
    orthogonal_transform_seed: Optional[float] = None,
    preferred_embedding_model: Optional[int] = None,
    workspace_uri: Optional[str] = None,
    preferred_db_provider: Optional[int] = None,
) -> RepositoryInfo:
    """Build a RepositoryInfo message."""
    return RepositoryInfo(
        relative_workspace_path=relative_workspace_path,
        remote_url=remote_url or "",
        remote_name="origin" if remote_url else "",
        repo_name=repo_name,
        repo_owner=repo_owner,
        is_tracked=is_tracked,
        is_local=is_local,
        num_files=num_files or 0,
        orthogonal_transform_seed=orthogonal_transform_seed,
        preferred_embedding_model=preferred_embedding_model or 0,
        workspace_uri=workspace_uri or "",
        preferred_db_provider=preferred_db_provider or 0,
    )


def build_search_request(
    query: str,
    repo_name: str,
    repo_owner: str,
    top_k: int = 10,
    rerank: bool = True,
    glob_filter: Optional[str] = None,
    remote_url: Optional[str] = None,
    is_tracked: bool = True,
    is_local: bool = False,
    num_files: Optional[int] = None,
    orthogonal_transform_seed: Optional[float] = None,
    preferred_embedding_model: Optional[int] = None,
    workspace_uri: Optional[str] = None,
    preferred_db_provider: Optional[int] = None,
) -> SearchRepositoryRequest:
    """Build a SearchRepositoryRequest message."""
    repo_info = build_repository_info(
        repo_name=repo_name,
        repo_owner=repo_owner,
        remote_url=remote_url,
        is_tracked=is_tracked,
        is_local=is_local,
        num_files=num_files,
        orthogonal_transform_seed=orthogonal_transform_seed,
        preferred_embedding_model=preferred_embedding_model,
        workspace_uri=workspace_uri,
        preferred_db_provider=preferred_db_provider,
    )
    return SearchRepositoryRequest(
        query=query,
        repository_info=repo_info,
        top_k=top_k,
        rerank=rerank,
        glob_filter=glob_filter or "",
    )


def build_sem_search_request(
    query: str,
    repo_name: str,
    repo_owner: str,
    top_k: int = 10,
    rerank: bool = True,
    glob_filter: Optional[str] = None,
    remote_url: Optional[str] = None,
    is_tracked: bool = True,
    is_local: bool = False,
    num_files: Optional[int] = None,
    orthogonal_transform_seed: Optional[float] = None,
    preferred_embedding_model: Optional[int] = None,
    workspace_uri: Optional[str] = None,
    preferred_db_provider: Optional[int] = None,
) -> SemSearchRequest:
    """Build a SemSearchRequest message."""
    inner = build_search_request(
        query=query,
        repo_name=repo_name,
        repo_owner=repo_owner,
        top_k=top_k,
        rerank=rerank,
        glob_filter=glob_filter,
        remote_url=remote_url,
        is_tracked=is_tracked,
        is_local=is_local,
        num_files=num_files,
        orthogonal_transform_seed=orthogonal_transform_seed,
        preferred_embedding_model=preferred_embedding_model,
        workspace_uri=workspace_uri,
        preferred_db_provider=preferred_db_provider,
    )
    return SemSearchRequest(request=inner)


# Legacy encode functions for backward compatibility
def encode_search_repository_request(**kwargs) -> bytes:
    """Encode a SearchRepositoryRequest to bytes."""
    return bytes(build_search_request(**kwargs))


def encode_sem_search_request(**kwargs) -> bytes:
    """Encode a SemSearchRequest to bytes."""
    return bytes(build_sem_search_request(**kwargs))


def wrap_connect_envelope(data: bytes, compressed: bool = False) -> bytes:
    """Wrap data in a Connect protocol envelope."""
    flags = 1 if compressed else 0
    return struct.pack(">BI", flags, len(data)) + data


def decode_connect_envelope(data: bytes) -> list[bytes]:
    """Decode Connect protocol envelope(s) from data."""
    messages = []
    pos = 0

    while pos < len(data):
        if pos + 5 > len(data):
            break

        flags = data[pos]
        length = struct.unpack(">I", data[pos + 1 : pos + 5])[0]
        pos += 5

        if pos + length > len(data):
            break

        message = data[pos : pos + length]
        pos += length

        # Skip trailer frames (flag 0x02)
        if flags & 0x02:
            continue

        # Decompress if gzip flag set
        if flags & 0x01:
            try:
                message = gzip.decompress(message)
            except Exception:
                pass

        messages.append(message)

    return messages


def parse_search_response(data: bytes) -> list[CodeResult]:
    """Parse search response data into CodeResult objects."""
    results: list[CodeResult] = []

    # Try parsing as SemSearchResponse first
    try:
        sem_response = SemSearchResponse().parse(data)
        if sem_response.code_results:
            for item in sem_response.code_results:
                if item.code_result and item.code_result.code_block:
                    results.append(item.code_result)
            if results:
                return results
        if sem_response.response and sem_response.response.code_results:
            return list(sem_response.response.code_results)
    except Exception:
        pass

    # Try parsing as SearchRepositoryResponse
    try:
        response = SearchRepositoryResponse().parse(data)
        if response.code_results:
            return list(response.code_results)
    except Exception:
        pass

    # Try parsing as a single CodeResult
    try:
        result = CodeResult().parse(data)
        if result.code_block and result.code_block.relative_workspace_path:
            return [result]
    except Exception:
        pass

    return results


def code_result_to_dict(result: CodeResult) -> dict:
    """Convert a CodeResult to a dictionary (for backward compatibility)."""
    block = result.code_block or CodeBlock()
    rng = block.range or Range()
    start = rng.start_position or Position()
    end = rng.end_position or Position()

    # Resolve contents
    contents = block.contents
    if not contents:
        contents = block.override_contents or block.file_contents or ""

    return {
        "codeBlock": {
            "relativeWorkspacePath": block.relative_workspace_path,
            "contents": contents,
            "range": {
                "startPosition": {"line": start.line, "column": start.column},
                "endPosition": {"line": end.line, "column": end.column},
            },
        },
        "score": result.score,
    }


# Re-export message types for convenience
__all__ = [
    "Position",
    "Range",
    "CodeBlock",
    "CodeResult",
    "CodeResultWithClassification",
    "RepositoryInfo",
    "SearchRepositoryRequest",
    "SemSearchRequest",
    "SearchRepositoryResponse",
    "SemSearchResponse",
    "build_repository_info",
    "build_search_request",
    "build_sem_search_request",
    "encode_search_repository_request",
    "encode_sem_search_request",
    "wrap_connect_envelope",
    "decode_connect_envelope",
    "parse_search_response",
    "code_result_to_dict",
]
