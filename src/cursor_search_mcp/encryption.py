"""Path encryption helpers compatible with Cursor's retrieval extension."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_PATH_SPLIT_RE = re.compile(r"([./\\\\])")
_GLOB_SPLIT_RE = re.compile(r"([{}\\\\/.,])")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _pad_to_multiple(value: str, multiple: int = 4) -> str:
    pad = (multiple - (len(value) % multiple)) % multiple
    if pad == 0:
        return value
    return value + ("\0" * pad)


@dataclass
class V1MasterKeyedEncryptionScheme:
    """AES-256-CTR + HMAC prefix scheme used by Cursor."""

    master_key_raw: str

    def __post_init__(self) -> None:
        master_key = _b64url_decode(self.master_key_raw)
        self._mac_key = hashlib.sha256(master_key + b"\x00").digest()
        self._enc_key = hashlib.sha256(master_key + b"\x01").digest()

    def encrypt(self, value: str) -> str:
        mac = hmac.new(self._mac_key, value.encode("utf-8"), hashlib.sha256).digest()
        prefix = mac[:6]
        iv = prefix + (b"\x00" * 10)
        padded = _pad_to_multiple(value)

        cipher = Cipher(algorithms.AES(self._enc_key), modes.CTR(iv))
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(padded.encode("utf-8")) + encryptor.finalize()

        return _b64url_encode(prefix + ciphertext)

    def decrypt(self, value: str) -> str:
        raw = _b64url_decode(value)
        prefix = raw[:6]
        iv = prefix + (b"\x00" * 10)
        ciphertext = raw[6:]

        cipher = Cipher(algorithms.AES(self._enc_key), modes.CTR(iv))
        decryptor = cipher.decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        return plaintext.rstrip(b"\x00").decode("utf-8")


@dataclass
class PlainTextEncryptionScheme:
    """No-op encryption scheme."""

    def encrypt(self, value: str) -> str:
        return value

    def decrypt(self, value: str) -> str:
        return value


def build_path_encryption_scheme(key: Optional[str]) -> PlainTextEncryptionScheme | V1MasterKeyedEncryptionScheme:
    if not key:
        return PlainTextEncryptionScheme()
    return V1MasterKeyedEncryptionScheme(key)


def encrypt_path(path: str, scheme: PlainTextEncryptionScheme | V1MasterKeyedEncryptionScheme) -> str:
    parts = _PATH_SPLIT_RE.split(path)
    out = []
    for part in parts:
        if _PATH_SPLIT_RE.match(part) or part == "":
            out.append(part)
        else:
            out.append(scheme.encrypt(part))
    return "".join(out)


def decrypt_path(path: str, scheme: PlainTextEncryptionScheme | V1MasterKeyedEncryptionScheme) -> str:
    parts = _PATH_SPLIT_RE.split(path)
    out = []
    for part in parts:
        if _PATH_SPLIT_RE.match(part) or part == "":
            out.append(part)
        else:
            out.append(scheme.decrypt(part))
    return "".join(out)


def encrypt_glob(pattern: str, scheme: PlainTextEncryptionScheme | V1MasterKeyedEncryptionScheme) -> str:
    parts = _GLOB_SPLIT_RE.split(pattern)
    out = []
    for part in parts:
        if _GLOB_SPLIT_RE.match(part) or part == "":
            out.append(part)
        elif part == "**":
            out.append(part)
        elif "*" in part:
            out.append("*")
        else:
            out.append(scheme.encrypt(part))
    return "".join(out)
