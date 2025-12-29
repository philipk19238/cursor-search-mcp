"""Protobuf message definitions for Cursor API."""

from dataclasses import dataclass
from typing import Optional

import betterproto


@dataclass
class Position(betterproto.Message):
    """Position in a file."""

    line: int = betterproto.uint32_field(1)
    column: int = betterproto.uint32_field(2)


@dataclass
class Range(betterproto.Message):
    """Range in a file."""

    start_position: Position = betterproto.message_field(1)
    end_position: Position = betterproto.message_field(2)


@dataclass
class CodeBlock(betterproto.Message):
    """A block of code from a file."""

    relative_workspace_path: str = betterproto.string_field(1)
    file_contents: bytes = betterproto.bytes_field(2)
    range: Range = betterproto.message_field(3)
    contents: bytes = betterproto.bytes_field(4)
    override_contents: bytes = betterproto.bytes_field(6)
    original_contents: bytes = betterproto.bytes_field(7)


@dataclass
class CodeResult(betterproto.Message):
    """Search result with code block and score."""

    code_block: CodeBlock = betterproto.message_field(1)
    score: float = betterproto.float_field(2)


@dataclass
class CodeResultWithClassification(betterproto.Message):
    """Wrapper for code result with classification."""

    code_result: CodeResult = betterproto.message_field(1)


@dataclass
class RepositoryInfo(betterproto.Message):
    """Repository information for search requests."""

    relative_workspace_path: str = betterproto.string_field(1)
    remote_url: str = betterproto.string_field(2)
    remote_name: str = betterproto.string_field(3)
    repo_name: str = betterproto.string_field(4)
    repo_owner: str = betterproto.string_field(5)
    is_tracked: bool = betterproto.bool_field(6)
    is_local: bool = betterproto.bool_field(7)
    num_files: int = betterproto.uint32_field(8)
    orthogonal_transform_seed: Optional[float] = betterproto.double_field(9)
    preferred_embedding_model: int = betterproto.uint32_field(10)
    workspace_uri: str = betterproto.string_field(11)
    preferred_db_provider: int = betterproto.uint32_field(12)


@dataclass
class SearchRepositoryRequest(betterproto.Message):
    """Request to search a repository."""

    query: str = betterproto.string_field(1)
    repository_info: RepositoryInfo = betterproto.message_field(2)
    top_k: int = betterproto.uint32_field(3)
    rerank: bool = betterproto.bool_field(5)
    glob_filter: str = betterproto.string_field(7)


@dataclass
class SemSearchRequest(betterproto.Message):
    """Semantic search request wrapper."""

    request: SearchRepositoryRequest = betterproto.message_field(1)


@dataclass
class SearchRepositoryResponse(betterproto.Message):
    """Response from SearchRepositoryV2."""

    code_results: list[CodeResult] = betterproto.message_field(1)


@dataclass
class SemSearchResponse(betterproto.Message):
    """Response from SemSearch."""

    response: SearchRepositoryResponse = betterproto.message_field(1)
    code_results: list[CodeResultWithClassification] = betterproto.message_field(3)


@dataclass
class EnsureIndexCreatedRequest(betterproto.Message):
    """Request to ensure an index is created."""

    repository_info: RepositoryInfo = betterproto.message_field(1)
