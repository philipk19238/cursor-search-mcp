"""Protobuf encoding/decoding for Cursor API."""

import gzip
import struct
from typing import Optional

from .messages import (
    CodeBlock,
    CodeResult,
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


def _decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        byte = data[pos]
        result |= (byte & 0x7F) << shift
        pos += 1
        if not (byte & 0x80):
            break
        shift += 7
    return result, pos


def _skip_field(data: bytes, pos: int, wire_type: int) -> int:
    if wire_type == 0:  # varint
        while data[pos] & 0x80:
            pos += 1
        pos += 1
    elif wire_type == 1:  # 64-bit
        pos += 8
    elif wire_type == 2:  # length-delimited
        length, pos = _decode_varint(data, pos)
        pos += length
    elif wire_type == 5:  # 32-bit
        pos += 4
    return pos


def _decode_bytes(data: bytes, pos: int) -> tuple[bytes, int]:
    length, pos = _decode_varint(data, pos)
    return data[pos:pos + length], pos + length


def _parse_position(data: bytes, pos: int, end: int) -> Position:
    line = 0
    column = 0
    while pos < end:
        tag, pos = _decode_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x7
        if field_number == 1 and wire_type == 0:
            line, pos = _decode_varint(data, pos)
        elif field_number == 2 and wire_type == 0:
            column, pos = _decode_varint(data, pos)
        else:
            pos = _skip_field(data, pos, wire_type)
    return Position(line=line, column=column)


def _parse_range(data: bytes, pos: int, end: int) -> Range:
    start = Position()
    end_pos = Position()
    while pos < end:
        tag, pos = _decode_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x7
        if field_number == 1 and wire_type == 2:
            length, pos = _decode_varint(data, pos)
            pos_end = pos + length
            start = _parse_position(data, pos, pos_end)
            pos = pos_end
        elif field_number == 2 and wire_type == 2:
            length, pos = _decode_varint(data, pos)
            pos_end = pos + length
            end_pos = _parse_position(data, pos, pos_end)
            pos = pos_end
        else:
            pos = _skip_field(data, pos, wire_type)
    return Range(start_position=start, end_position=end_pos)


def _parse_code_block(data: bytes, pos: int, end: int) -> CodeBlock:
    block = CodeBlock()
    while pos < end:
        tag, pos = _decode_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x7
        if field_number == 1 and wire_type == 2:
            raw, pos = _decode_bytes(data, pos)
            block.relative_workspace_path = raw.decode("utf-8", errors="replace")
        elif field_number == 2 and wire_type == 2:
            block.file_contents, pos = _decode_bytes(data, pos)
        elif field_number == 3 and wire_type == 2:
            length, pos = _decode_varint(data, pos)
            range_end = pos + length
            block.range = _parse_range(data, pos, range_end)
            pos = range_end
        elif field_number == 4 and wire_type == 2:
            block.contents, pos = _decode_bytes(data, pos)
        elif field_number == 6 and wire_type == 2:
            block.override_contents, pos = _decode_bytes(data, pos)
        elif field_number == 7 and wire_type == 2:
            block.original_contents, pos = _decode_bytes(data, pos)
        else:
            pos = _skip_field(data, pos, wire_type)
    return block


def _parse_code_result(data: bytes, pos: int, end: int) -> CodeResult:
    code_block = CodeBlock()
    score = 0.0
    while pos < end:
        tag, pos = _decode_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x7
        if field_number == 1 and wire_type == 2:
            length, pos = _decode_varint(data, pos)
            block_end = pos + length
            code_block = _parse_code_block(data, pos, block_end)
            pos = block_end
        elif field_number == 2 and wire_type == 5:
            score = struct.unpack("<f", data[pos:pos + 4])[0]
            pos += 4
        elif field_number == 2 and wire_type == 1:
            score = struct.unpack("<d", data[pos:pos + 8])[0]
            pos += 8
        else:
            pos = _skip_field(data, pos, wire_type)
    return CodeResult(code_block=code_block, score=float(score))


def _parse_code_result_with_classification(data: bytes, pos: int, end: int) -> Optional[CodeResult]:
    while pos < end:
        tag, pos = _decode_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x7
        if field_number == 1 and wire_type == 2:
            length, pos = _decode_varint(data, pos)
            item_end = pos + length
            return _parse_code_result(data, pos, item_end)
        pos = _skip_field(data, pos, wire_type)
    return None


def _parse_search_response_manual(data: bytes) -> list[CodeResult]:
    results: list[CodeResult] = []
    pos = 0
    end = len(data)

    def looks_like_path(value: str) -> bool:
        if not value:
            return False
        if any(ord(ch) < 32 for ch in value):
            return False
        return value.startswith(("./", "/")) or "/" in value

    while pos < end:
        tag, pos = _decode_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x7
        if field_number == 1 and wire_type == 2:
            length, pos = _decode_varint(data, pos)
            item_end = pos + length
            payload = data[pos:item_end]
            result = _parse_code_result(payload, 0, len(payload))
            path = result.code_block.relative_workspace_path if result.code_block else ""
            if path and looks_like_path(path):
                results.append(result)
            else:
                results.extend(_parse_search_response_manual(payload))
            pos = item_end
        elif field_number == 3 and wire_type == 2:
            length, pos = _decode_varint(data, pos)
            item_end = pos + length
            result = _parse_code_result_with_classification(data, pos, item_end)
            if result and result.code_block:
                path = result.code_block.relative_workspace_path
                if path and looks_like_path(path):
                    results.append(result)
            pos = item_end
        else:
            pos = _skip_field(data, pos, wire_type)
    return results


def parse_search_response(data: bytes) -> list[CodeResult]:
    """Parse search response data into CodeResult objects."""
    try:
        sem_response = SemSearchResponse().parse(data)
        if sem_response.code_results:
            return [
                item.code_result
                for item in sem_response.code_results
                if item.code_result and item.code_result.code_block
            ]
        if sem_response.response and sem_response.response.code_results:
            return list(sem_response.response.code_results)
    except Exception:
        pass

    try:
        response = SearchRepositoryResponse().parse(data)
        if response.code_results:
            return list(response.code_results)
    except Exception:
        pass

    return _parse_search_response_manual(data)


# Re-export message types for convenience
__all__ = [
    "CodeBlock",
    "CodeResult",
    "Position",
    "Range",
    "RepositoryInfo",
    "SearchRepositoryRequest",
    "SearchRepositoryResponse",
    "SemSearchRequest",
    "SemSearchResponse",
    "build_repository_info",
    "build_search_request",
    "build_sem_search_request",
    "encode_search_repository_request",
    "encode_sem_search_request",
    "wrap_connect_envelope",
    "decode_connect_envelope",
    "parse_search_response",
]
