"""Cursor API client for semantic search."""

import json
import struct
from dataclasses import dataclass
from typing import Optional

import httpx

from .auth import CursorCredentials, generate_checksum, get_cursor_version


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
        }

    def _encode_protobuf_message(self, data: dict) -> bytes:
        """Encode a message as protobuf-like format for Connect protocol.

        This is a simplified encoding - for full compatibility, use proper protobuf.
        """
        # For Connect protocol, we need to wrap in an envelope:
        # 1 byte flags (0 = no compression)
        # 4 bytes message length (big-endian)
        # message bytes

        # Since we don't have the full proto definitions compiled,
        # we'll use JSON encoding with application/json content type instead
        json_bytes = json.dumps(data).encode("utf-8")

        # Connect protocol envelope
        envelope = struct.pack(">BI", 0, len(json_bytes)) + json_bytes
        return envelope

    def _make_connect_request(
        self,
        base_url: str,
        service_path: str,
        request_data: dict,
    ) -> httpx.Response:
        """Make a Connect protocol request."""
        url = f"{base_url}/{service_path}"

        headers = self._get_headers()
        # Use JSON for simplicity (Connect supports both proto and JSON)
        headers["content-type"] = "application/json"

        response = self._client.post(
            url,
            headers=headers,
            json=request_data,
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
        # Build repository info
        repository_info = {
            "repoName": self.repo_name,
            "repoOwner": self.repo_owner,
            "relativeWorkspacePath": ".",
        }

        # Build search request
        request_data = {
            "query": query,
            "repository": repository_info,
            "topK": top_k,
            "rerank": rerank,
        }

        if target_directory:
            request_data["globFilter"] = f"{target_directory}/**"

        try:
            response = self._make_connect_request(
                REPO_SERVICE_URL,
                "aiserver.v1.RepositoryService/SearchRepositoryV2",
                request_data,
            )

            if response.status_code != 200:
                # Try alternative endpoint
                response = self._make_connect_request(
                    REPO_SERVICE_URL,
                    "aiserver.v1.RepositoryService/SemSearch",
                    {"request": request_data},
                )

            if response.status_code != 200:
                raise RuntimeError(
                    f"Search failed with status {response.status_code}: {response.text}"
                )

            result_data = response.json()
            return self._parse_search_response(result_data, query)

        except httpx.RequestError as e:
            raise RuntimeError(f"Search request failed: {e}")

    def _parse_search_response(self, data: dict, query: str) -> SearchResult:
        """Parse the search response into SearchResult."""
        chunks = []

        # Handle different response formats
        code_results = data.get("codeResults", [])
        if not code_results and "response" in data:
            code_results = data["response"].get("codeResults", [])

        for result in code_results:
            code_block = result.get("codeBlock", {})

            # Extract position info
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
            chunks.append(chunk)

        metadata = data.get("metadata", None)

        return SearchResult(
            chunks=chunks,
            query=query,
            metadata=metadata,
        )

    def ensure_index_created(self) -> bool:
        """Ensure the repository index exists."""
        repository_info = {
            "repoName": self.repo_name,
            "repoOwner": self.repo_owner,
            "relativeWorkspacePath": ".",
        }

        try:
            response = self._make_connect_request(
                REPO_SERVICE_URL,
                "aiserver.v1.RepositoryService/EnsureIndexCreated",
                {"repository": repository_info},
            )
            return response.status_code == 200
        except httpx.RequestError:
            return False

    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for a list of texts."""
        try:
            response = self._make_connect_request(
                REPO_SERVICE_URL,
                "aiserver.v1.RepositoryService/GetEmbeddings",
                {"texts": texts},
            )

            if response.status_code != 200:
                raise RuntimeError(f"GetEmbeddings failed: {response.text}")

            data = response.json()
            return [emb.get("embedding", []) for emb in data.get("embeddings", [])]
        except httpx.RequestError as e:
            raise RuntimeError(f"GetEmbeddings request failed: {e}")

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
