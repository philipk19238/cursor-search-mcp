"""Protobuf encoding/decoding for Cursor API."""

import gzip
import struct
from typing import Optional

from .messages import (
    CodeResult,
    RepositoryInfo,
    SearchRepositoryRequest,
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


def encode_sem_search_request(**kwargs) -> bytes:
    return bytes(build_sem_search_request(**kwargs))


def wrap_connect_envelope(data: bytes, compressed: bool = False) -> bytes:
    flags = 1 if compressed else 0
    return struct.pack(">BI", flags, len(data)) + data


def decode_connect_envelope(data: bytes) -> list[bytes]:
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

        if flags & 0x02:
            continue

        if flags & 0x01:
            message = gzip.decompress(message)

        messages.append(message)

    return messages


def parse_search_response(data: bytes) -> list[CodeResult]:
    sem_response = SemSearchResponse().parse(data)
    if sem_response.code_results:
        return [
            item.code_result
            for item in sem_response.code_results
            if item.code_result and item.code_result.code_block
        ]
    if sem_response.response and sem_response.response.code_results:
        return list(sem_response.response.code_results)
    return []


__all__ = [
    "CodeResult",
    "RepositoryInfo",
    "SearchRepositoryRequest",
    "SemSearchRequest",
    "SemSearchResponse",
    "build_repository_info",
    "build_search_request",
    "build_sem_search_request",
    "encode_sem_search_request",
    "wrap_connect_envelope",
    "decode_connect_envelope",
    "parse_search_response",
]
