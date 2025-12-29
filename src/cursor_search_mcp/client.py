"""Cursor API client for semantic search."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

from .auth import CursorCredentials, generate_checksum, get_cursor_version
from .encryption import build_path_encryption_scheme, decrypt_path, encrypt_glob
from .proto import (
    build_repository_info,
    decode_connect_envelope,
    encode_search_repository_request,
    encode_sem_search_request,
    parse_search_response,
    wrap_connect_envelope,
)

REPO_SERVICE_URL = "https://repo42.cursor.sh"


@dataclass
class CodeChunk:
    file_path: str
    content: str
    start_line: int
    end_line: int
    score: float


@dataclass
class SearchResult:
    chunks: list[CodeChunk]
    query: str
    metadata: Optional[dict] = None


class CursorSearchClient:
    def __init__(
        self,
        credentials: CursorCredentials,
        repo_name: str,
        repo_owner: str,
        workspace_path: str,
        remote_url: Optional[str] = None,
        is_tracked: bool = True,
        is_local: bool = False,
        num_files: Optional[int] = None,
        orthogonal_transform_seed: Optional[float] = None,
        preferred_embedding_model: Optional[int] = None,
        workspace_uri: Optional[str] = None,
        preferred_db_provider: Optional[int] = None,
        path_encryption_key: Optional[str] = None,
    ):
        self.credentials = credentials
        self.repo_name = repo_name
        self.repo_owner = repo_owner
        self.workspace_path = workspace_path
        self.remote_url: Optional[str]
        if remote_url is not None:
            self.remote_url = remote_url
        elif is_local:
            self.remote_url = None
        else:
            self.remote_url = f"https://github.com/{repo_owner}/{repo_name}"
        self.is_tracked = is_tracked
        self.is_local = is_local
        self.num_files = num_files
        self.orthogonal_transform_seed = orthogonal_transform_seed
        self.preferred_embedding_model = preferred_embedding_model
        self.workspace_uri = workspace_uri
        self.preferred_db_provider = preferred_db_provider
        self.path_encryption_key = path_encryption_key
        self._path_scheme = build_path_encryption_scheme(path_encryption_key)
        self._client = httpx.Client(timeout=60.0)

    def _get_headers(self) -> dict[str, str]:
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
        url = f"{base_url}/{service_path}"
        headers = self._get_headers()
        envelope = wrap_connect_envelope(proto_data)

        return self._client.post(
            url,
            headers=headers,
            content=envelope,
        )

    def search(
        self,
        query: str,
        top_k: int = 10,
        target_directory: Optional[str] = None,
        rerank: bool = True,
    ) -> SearchResult:
        glob_filter = f"{target_directory}/**" if target_directory else None
        if glob_filter and self.path_encryption_key:
            glob_filter = encrypt_glob(glob_filter, self._path_scheme)

        proto_data = encode_sem_search_request(
            query=query,
            repo_name=self.repo_name,
            repo_owner=self.repo_owner,
            top_k=top_k,
            rerank=rerank,
            glob_filter=glob_filter,
            remote_url=self.remote_url,
            is_tracked=self.is_tracked,
            is_local=self.is_local,
            num_files=self.num_files,
            orthogonal_transform_seed=self.orthogonal_transform_seed,
            preferred_embedding_model=self.preferred_embedding_model,
            workspace_uri=self.workspace_uri,
            preferred_db_provider=self.preferred_db_provider,
        )

        try:
            response = self._make_proto_request(
                REPO_SERVICE_URL,
                "aiserver.v1.RepositoryService/SemSearch",
                proto_data,
            )

            if response.status_code == 200:
                return self._parse_proto_response(response.content, query)

            proto_data = encode_search_repository_request(
                query=query,
                repo_name=self.repo_name,
                repo_owner=self.repo_owner,
                top_k=top_k,
                rerank=rerank,
                glob_filter=glob_filter,
                remote_url=self.remote_url,
                is_tracked=self.is_tracked,
                is_local=self.is_local,
                num_files=self.num_files,
                orthogonal_transform_seed=self.orthogonal_transform_seed,
                preferred_embedding_model=self.preferred_embedding_model,
                workspace_uri=self.workspace_uri,
                preferred_db_provider=self.preferred_db_provider,
            )

            response = self._make_proto_request(
                REPO_SERVICE_URL,
                "aiserver.v1.RepositoryService/SearchRepositoryV2",
                proto_data,
            )

            if response.status_code == 200:
                return self._parse_proto_response(response.content, query)

            raise RuntimeError(
                f"Search failed with status {response.status_code}: "
                f"{response.text[:200]}"
            )

        except httpx.RequestError as e:
            raise RuntimeError(f"Search request failed: {e}")

    def _parse_proto_response(self, data: bytes, query: str) -> SearchResult:
        chunks = []

        if data and data[0] == 0x02:  # Trailer frame flag
            try:
                import json

                json_start = data.find(b"{")
                if json_start != -1:
                    error_data = json.loads(data[json_start:])
                    error_msg = error_data.get("error", {}).get(
                        "message", "Unknown error"
                    )
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
            messages = decode_connect_envelope(data)

            for message in messages:
                code_results = parse_search_response(message)

                for result in code_results:
                    block = result.code_block
                    if not block:
                        continue

                    rng = block.range
                    start_line = rng.start_position.line if rng else 0
                    end_line = rng.end_position.line if rng else 0

                    file_path = block.relative_workspace_path
                    if file_path and self.path_encryption_key:
                        try:
                            file_path = decrypt_path(file_path, self._path_scheme)
                        except Exception:
                            pass

                    content = (
                        self._decode_text(block.contents)
                        or self._decode_text(block.override_contents)
                        or self._decode_text(block.file_contents)
                        or self._decode_text(getattr(block, "original_contents", b""))
                    )
                    if not content and file_path:
                        content = self._read_chunk_contents(
                            file_path=file_path,
                            start_line=start_line,
                            end_line=end_line,
                        )

                    chunk = CodeChunk(
                        file_path=file_path,
                        content=content,
                        start_line=start_line,
                        end_line=end_line,
                        score=result.score,
                    )

                    if chunk.file_path:
                        chunks.append(chunk)

        except Exception as e:
            return SearchResult(
                chunks=[],
                query=query,
                metadata={"parse_error": str(e), "raw_length": len(data)},
            )

        return SearchResult(
            chunks=chunks,
            query=query,
        )

    @staticmethod
    def _decode_text(value: Optional[object]) -> str:
        if not value:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    def _read_chunk_contents(
        self, file_path: str, start_line: int, end_line: int
    ) -> str:
        if not file_path:
            return ""

        try:
            base = Path(self.workspace_path)
            full_path = (base / file_path).resolve()
            if not full_path.exists():
                return ""

            start_line = max(start_line, 1)
            end_line = max(end_line, start_line)

            lines = []
            with full_path.open("r", encoding="utf-8", errors="replace") as handle:
                for i, line in enumerate(handle, start=1):
                    if i < start_line:
                        continue
                    if i > end_line:
                        break
                    lines.append(line.rstrip("\n"))
            return "\n".join(lines)
        except Exception:
            return ""

    def ensure_index_created(self) -> bool:
        from .messages import EnsureIndexCreatedRequest

        repo_info = build_repository_info(
            repo_name=self.repo_name,
            repo_owner=self.repo_owner,
            remote_url=self.remote_url,
            is_tracked=self.is_tracked,
            is_local=self.is_local,
            num_files=self.num_files,
            orthogonal_transform_seed=self.orthogonal_transform_seed,
            preferred_embedding_model=self.preferred_embedding_model,
            workspace_uri=self.workspace_uri,
            preferred_db_provider=self.preferred_db_provider,
        )

        request = EnsureIndexCreatedRequest(repository_info=repo_info)
        proto_data = bytes(request)

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
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
