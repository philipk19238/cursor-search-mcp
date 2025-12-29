"""Cursor API client for semantic search."""

from dataclasses import dataclass
from typing import Optional

import httpx

from .auth import CursorCredentials, generate_checksum, get_cursor_version
from .proto import (
    encode_search_repository_request,
    encode_sem_search_request,
    wrap_connect_envelope,
    decode_connect_envelope,
    parse_search_response,
    encode_repository_info,
    encode_message,
)


# API endpoints
REPO_SERVICE_URL = "https://repo42.cursor.sh"
AI_SERVICE_URL = "https://api2.cursor.sh"


@dataclass
class CodeChunk:
    """A code chunk returned from semantic search."""

    file_path: str
    content: str
    start_line: int
    end_line: int
    score: float
    language: Optional[str] = None


@dataclass
class SearchResult:
    """Result from a semantic search query."""

    chunks: list[CodeChunk]
    query: str
    metadata: Optional[dict] = None


class CursorSearchClient:
    """Client for Cursor's semantic search API."""

    def __init__(
        self,
        credentials: CursorCredentials,
        repo_name: str,
        repo_owner: str,
        workspace_path: str,
    ):
        self.credentials = credentials
        self.repo_name = repo_name
        self.repo_owner = repo_owner
        self.workspace_path = workspace_path
        self._client = httpx.Client(timeout=60.0)

    def _get_headers(self) -> dict[str, str]:
        """Get headers for Cursor API requests."""
        return {
            "authorization": f"Bearer {self.credentials.access_token}",
            "x-cursor-client-version": get_cursor_version(),
            "x-cursor-checksum": generate_checksum(),
            "content-type": "application/connect+proto",
            "connect-protocol-version": "1",
            "accept": "application/connect+proto",
        }

    def _make_proto_request(
        self,
        base_url: str,
        service_path: str,
        proto_data: bytes,
    ) -> httpx.Response:
        """Make a Connect protocol request with protobuf encoding."""
        url = f"{base_url}/{service_path}"
        headers = self._get_headers()

        # Wrap in Connect envelope
        envelope = wrap_connect_envelope(proto_data)

        response = self._client.post(
            url,
            headers=headers,
            content=envelope,
        )
        return response

    def search(
        self,
        query: str,
        top_k: int = 10,
        target_directory: Optional[str] = None,
        rerank: bool = True,
    ) -> SearchResult:
        """Perform semantic search on the codebase.

        Args:
            query: Natural language search query
            top_k: Maximum number of results to return
            target_directory: Optional directory to scope the search
            rerank: Whether to rerank results for relevance

        Returns:
            SearchResult with matching code chunks
        """
        glob_filter = f"{target_directory}/**" if target_directory else None

        # Try SemSearch first (streaming endpoint)
        proto_data = encode_sem_search_request(
            query=query,
            repo_name=self.repo_name,
            repo_owner=self.repo_owner,
            top_k=top_k,
            rerank=rerank,
            glob_filter=glob_filter,
        )

        try:
            response = self._make_proto_request(
                REPO_SERVICE_URL,
                "aiserver.v1.RepositoryService/SemSearch",
                proto_data,
            )

            if response.status_code == 200:
                return self._parse_proto_response(response.content, query)

            # Try SearchRepositoryV2 as fallback
            proto_data = encode_search_repository_request(
                query=query,
                repo_name=self.repo_name,
                repo_owner=self.repo_owner,
                top_k=top_k,
                rerank=rerank,
                glob_filter=glob_filter,
            )

            response = self._make_proto_request(
                REPO_SERVICE_URL,
                "aiserver.v1.RepositoryService/SearchRepositoryV2",
                proto_data,
            )

            if response.status_code == 200:
                return self._parse_proto_response(response.content, query)

            # If still failing, try with different content type
            raise RuntimeError(
                f"Search failed with status {response.status_code}: {response.text[:200]}"
            )

        except httpx.RequestError as e:
            raise RuntimeError(f"Search request failed: {e}")

    def _parse_proto_response(self, data: bytes, query: str) -> SearchResult:
        """Parse protobuf response into SearchResult."""
        chunks = []

        # Check for error response (trailer frame with JSON error)
        if data and data[0] == 0x02:  # Trailer frame flag
            try:
                import json
                # Skip the 5-byte envelope header
                json_start = data.find(b'{')
                if json_start != -1:
                    error_data = json.loads(data[json_start:])
                    error_msg = error_data.get("error", {}).get("message", "Unknown error")
                    details = error_data.get("error", {}).get("details", [])
                    if details:
                        detail_info = details[0].get("debug", {}).get("details", {})
                        error_msg = detail_info.get("detail", error_msg)

                    return SearchResult(
                        chunks=[],
                        query=query,
                        metadata={"error": error_msg},
                    )
            except Exception:
                pass

        try:
            # Decode Connect envelope(s)
            messages = decode_connect_envelope(data)

            for message in messages:
                # Parse the search response
                code_results = parse_search_response(message)

                for result in code_results:
                    code_block = result.get("codeBlock", {})
                    range_info = code_block.get("range", {})
                    start_pos = range_info.get("startPosition", {})
                    end_pos = range_info.get("endPosition", {})

                    chunk = CodeChunk(
                        file_path=code_block.get("relativeWorkspacePath", ""),
                        content=code_block.get("contents", ""),
                        start_line=start_pos.get("line", 0),
                        end_line=end_pos.get("line", 0),
                        score=result.get("score", 0.0),
                    )

                    if chunk.file_path:  # Only add if we have a valid path
                        chunks.append(chunk)

        except Exception as e:
            # If parsing fails, return empty result with error info
            return SearchResult(
                chunks=[],
                query=query,
                metadata={"parse_error": str(e), "raw_length": len(data)},
            )

        return SearchResult(
            chunks=chunks,
            query=query,
        )

    def ensure_index_created(self) -> bool:
        """Ensure the repository index exists."""
        repo_info = encode_repository_info(
            repo_name=self.repo_name,
            repo_owner=self.repo_owner,
        )

        # EnsureIndexCreatedRequest has repository at field 1
        proto_data = encode_message(1, repo_info)

        try:
            response = self._make_proto_request(
                REPO_SERVICE_URL,
                "aiserver.v1.RepositoryService/EnsureIndexCreated",
                proto_data,
            )
            return response.status_code == 200
        except httpx.RequestError:
            return False

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
