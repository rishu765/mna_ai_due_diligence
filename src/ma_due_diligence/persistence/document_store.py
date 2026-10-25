"""Encrypted, deal-scoped local document storage for a controlled pilot."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
import secrets
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_MAGIC: Final = b"MADD-AESGCM-1\x00"
_NONCE_SIZE: Final = 12
_SAFE_STORAGE_KEY = re.compile(r"[0-9a-f]{16}/[0-9a-f]{32}\.madd")


@dataclass(frozen=True, slots=True)
class StoredBlob:
    storage_key: str
    plaintext_sha256: str
    plaintext_size_bytes: int
    encrypted_size_bytes: int


def generate_document_key() -> str:
    """Return a URL-safe base64-encoded 256-bit key for external secret storage."""

    return base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256)).decode("ascii")


def document_key_from_environment(variable: str = "MADD_DOCUMENT_KEY") -> bytes:
    encoded = os.environ.get(variable)
    if not encoded:
        raise RuntimeError(f"{variable} is required for encrypted document storage")
    try:
        key = base64.b64decode(encoded.encode("ascii"), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError, UnicodeEncodeError) as error:
        raise RuntimeError(f"{variable} is not valid URL-safe base64") from error
    if len(key) != 32:
        raise RuntimeError(f"{variable} must decode to exactly 32 bytes")
    return key


class EncryptedLocalDocumentStore:
    """Stores encrypted blobs without exposing filenames in storage paths."""

    def __init__(self, root: Path, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("document encryption key must contain 32 bytes")
        self._root = root.resolve()
        self._cipher = AESGCM(key)
        self._root.mkdir(parents=True, exist_ok=True)
        _restrict_permissions(self._root, 0o700)

    def put(self, *, deal_id: str, document_id: str, content: bytes) -> StoredBlob:
        if not deal_id.strip() or not document_id.strip():
            raise ValueError("deal_id and document_id must not be blank")
        checksum = hashlib.sha256(content).hexdigest()
        deal_partition = hashlib.sha256(deal_id.encode("utf-8")).hexdigest()[:16]
        storage_key = f"{deal_partition}/{secrets.token_hex(16)}.madd"
        destination = self._safe_path(storage_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _restrict_permissions(destination.parent, 0o700)

        nonce = os.urandom(_NONCE_SIZE)
        associated_data = _associated_data(deal_id, document_id, checksum)
        encrypted = self._cipher.encrypt(nonce, content, associated_data)
        payload = _MAGIC + nonce + encrypted

        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="wb",
                dir=destination.parent,
                prefix=".upload-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            _restrict_permissions(temporary_path, 0o600)
            os.replace(temporary_path, destination)
            _restrict_permissions(destination, 0o600)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

        return StoredBlob(storage_key, checksum, len(content), len(payload))

    def read(
        self,
        *,
        deal_id: str,
        document_id: str,
        storage_key: str,
        expected_sha256: str,
    ) -> bytes:
        path = self._safe_path(storage_key)
        payload = path.read_bytes()
        minimum_size = len(_MAGIC) + _NONCE_SIZE + 16
        if len(payload) < minimum_size or not payload.startswith(_MAGIC):
            raise ValueError("stored document has an invalid encrypted envelope")
        nonce_start = len(_MAGIC)
        nonce = payload[nonce_start : nonce_start + _NONCE_SIZE]
        encrypted = payload[nonce_start + _NONCE_SIZE :]
        associated_data = _associated_data(deal_id, document_id, expected_sha256)
        content = self._cipher.decrypt(nonce, encrypted, associated_data)
        actual_sha256 = hashlib.sha256(content).hexdigest()
        if not secrets.compare_digest(actual_sha256, expected_sha256.casefold()):
            raise ValueError("stored document checksum verification failed")
        return content

    def delete(self, storage_key: str) -> None:
        path = self._safe_path(storage_key)
        path.unlink(missing_ok=True)

    def _safe_path(self, storage_key: str) -> Path:
        if not _SAFE_STORAGE_KEY.fullmatch(storage_key):
            raise ValueError("invalid storage key")
        candidate = (self._root / storage_key).resolve()
        if not candidate.is_relative_to(self._root):
            raise ValueError("storage key escapes the configured root")
        return candidate


def _associated_data(deal_id: str, document_id: str, checksum: str) -> bytes:
    return f"{deal_id}\x00{document_id}\x00{checksum.casefold()}".encode()


def _restrict_permissions(path: Path, mode: int) -> None:
    # The deployment boundary must additionally restrict the service account and volume ACL.
    with suppress(OSError):
        path.chmod(mode)
