"""Authentication utilities for Cursor API."""

import base64
import json
import os
import platform
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CursorCredentials:
    """Cursor authentication credentials."""

    access_token: str
    refresh_token: str


def get_cursor_dir() -> Path:
    """Get the Cursor application data directory."""
    env_path = os.environ.get("CURSOR_CONFIG_PATH")
    if env_path:
        return Path(env_path)

    home = Path.home()

    system = platform.system()
    if system == "Darwin":
        return home / "Library" / "Application Support" / "Cursor"
    elif system == "Windows":
        return Path(os.environ.get("APPDATA", "")) / "Cursor"
    elif system == "Linux":
        return home / ".config" / "Cursor"
    else:
        raise RuntimeError(f"Unsupported platform: {system}")


def get_state_db_path() -> Path:
    """Get the path to Cursor's state database."""
    return get_cursor_dir() / "User" / "globalStorage" / "state.vscdb"


def _encrypt_bytes(data: bytes) -> bytes:
    """Apply rolling XOR encryption (matches Cursor's algorithm)."""
    result = bytearray(data)
    w = 165
    for i in range(len(result)):
        result[i] = ((result[i] ^ w) + (i % 256)) % 256
        w = result[i]
    return bytes(result)


def generate_checksum(machine_id: str = "cursor-search-mcp") -> str:
    """Generate a checksum for Cursor API requests."""
    timestamp = int(time.time() * 1000)

    # Convert timestamp to 6-byte array (big-endian)
    timestamp_bytes = timestamp.to_bytes(6, byteorder="big")

    # Apply encryption
    encrypted = _encrypt_bytes(timestamp_bytes)

    # Base64 encode and concatenate with machine ID
    encoded = base64.b64encode(encrypted).decode("ascii")
    return f"{encoded}{machine_id}"


def get_credentials_from_db() -> CursorCredentials:
    """Get Cursor credentials from the local SQLite database."""
    db_path = get_state_db_path()

    if not db_path.exists():
        raise FileNotFoundError(
            f"Cursor state database not found at {db_path}. "
            "Make sure Cursor is installed and you've logged in at least once."
        )

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute(
        "SELECT value FROM ItemTable WHERE key = 'cursorAuth/accessToken'"
    )
    access_token_row = cursor.fetchone()

    cursor.execute(
        "SELECT value FROM ItemTable WHERE key = 'cursorAuth/refreshToken'"
    )
    refresh_token_row = cursor.fetchone()

    conn.close()

    if not access_token_row:
        raise ValueError(
            "Access token not found in Cursor database. Please log in to Cursor."
        )

    return CursorCredentials(
        access_token=access_token_row[0],
        refresh_token=refresh_token_row[0] if refresh_token_row else "",
    )


def get_credentials() -> CursorCredentials:
    """Get Cursor credentials, with environment variable override support."""
    # Allow environment variable override
    env_token = os.environ.get("CURSOR_ACCESS_TOKEN")
    if env_token:
        return CursorCredentials(
            access_token=env_token,
            refresh_token=os.environ.get("CURSOR_REFRESH_TOKEN", ""),
        )

    return get_credentials_from_db()


# Cursor client version - should be updated when Cursor updates
CURSOR_VERSION = "2.3.10"


def get_cursor_version() -> str:
    """Get the Cursor client version to use in API requests."""
    return os.environ.get("CURSOR_VERSION", CURSOR_VERSION)


def get_auth_id_from_token(access_token: str) -> str:
    """Decode the Cursor auth token and return the auth ID (JWT sub)."""
    if not access_token or "." not in access_token:
        raise ValueError("Invalid access token format.")

    _, payload_b64, _ = access_token.split(".", 2)
    padding = "=" * (-len(payload_b64) % 4)
    payload_bytes = base64.urlsafe_b64decode(payload_b64 + padding)
    payload = json.loads(payload_bytes.decode("utf-8"))
    sub: str | None = payload.get("sub")
    if not sub:
        raise ValueError("Access token missing subject.")
    return sub
