"""Trusted process-local checkpoint serialization for the offline V1."""

from __future__ import annotations

import os
import pickle
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_ENCRYPTED_TYPE = "madd-aesgcm-checkpoint-v1"
_NONCE_SIZE = 12


class TrustedLocalSerializer:
    """Preserve immutable domain objects in a trusted in-process store only."""

    _TYPE = "madd-trusted-local-pickle-v1"

    def dumps_typed(self, obj: Any) -> tuple[str, bytes]:
        return self._TYPE, pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)

    def loads_typed(self, data: tuple[str, bytes]) -> Any:
        kind, payload = data
        if kind != self._TYPE:
            raise ValueError(f"unsupported local checkpoint payload type: {kind}")
        return pickle.loads(payload)  # noqa: S301 - trusted same-process data only


class EncryptedCheckpointSerializer:
    """Authenticate and encrypt trusted application-generated checkpoint payloads."""

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("checkpoint encryption key must contain 32 bytes")
        self._cipher = AESGCM(key)
        self._inner = TrustedLocalSerializer()

    def dumps_typed(self, obj: Any) -> tuple[str, bytes]:
        inner_kind, plaintext = self._inner.dumps_typed(obj)
        kind_bytes = inner_kind.encode("utf-8")
        if len(kind_bytes) > 255:
            raise ValueError("checkpoint payload type is too long")
        nonce = os.urandom(_NONCE_SIZE)
        associated_data = _ENCRYPTED_TYPE.encode("ascii") + b"\x00" + kind_bytes
        encrypted = self._cipher.encrypt(nonce, plaintext, associated_data)
        envelope = bytes((len(kind_bytes),)) + kind_bytes + nonce + encrypted
        return _ENCRYPTED_TYPE, envelope

    def loads_typed(self, data: tuple[str, bytes]) -> Any:
        outer_kind, envelope = data
        if outer_kind != _ENCRYPTED_TYPE:
            raise ValueError(f"unsupported encrypted checkpoint payload type: {outer_kind}")
        if not envelope:
            raise ValueError("encrypted checkpoint envelope is empty")
        kind_size = envelope[0]
        nonce_start = 1 + kind_size
        encrypted_start = nonce_start + _NONCE_SIZE
        if kind_size == 0 or len(envelope) < encrypted_start + 16:
            raise ValueError("encrypted checkpoint envelope is malformed")
        try:
            inner_kind = envelope[1:nonce_start].decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("encrypted checkpoint payload type is invalid") from error
        nonce = envelope[nonce_start:encrypted_start]
        encrypted = envelope[encrypted_start:]
        associated_data = _ENCRYPTED_TYPE.encode("ascii") + b"\x00" + inner_kind.encode("utf-8")
        plaintext = self._cipher.decrypt(nonce, encrypted, associated_data)
        return self._inner.loads_typed((inner_kind, plaintext))
