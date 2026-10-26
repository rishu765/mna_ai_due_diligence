"""Encrypted, integrity-checked backup and restore for the controlled pilot."""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import os
import shutil
import sqlite3
import zipfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Final, cast
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_MAGIC: Final = b"MADD-BACKUP-1\x00"
_NONCE_BYTES: Final = 12
_MANIFEST = "manifest.json"
_DATABASES = ("pilot.sqlite3", "checkpoints.sqlite3")


class BackupValidationError(ValueError):
    """Raised when a backup envelope or its content fails validation."""


@dataclass(frozen=True, slots=True)
class PilotBackupManifest:
    format_version: int
    created_at: datetime
    files: dict[str, dict[str, object]]

    def payload(self) -> dict[str, object]:
        return {
            "format_version": self.format_version,
            "created_at": self.created_at.isoformat(),
            "files": self.files,
        }


def backup_key_from_environment(variable: str = "MADD_BACKUP_KEY") -> bytes:
    encoded = os.environ.get(variable)
    if not encoded:
        raise RuntimeError(f"{variable} is required for encrypted pilot backups")
    try:
        key = base64.b64decode(encoded.encode("ascii"), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError, UnicodeEncodeError) as error:
        raise RuntimeError(f"{variable} is not valid URL-safe base64") from error
    if len(key) != 32:
        raise RuntimeError(f"{variable} must decode to exactly 32 bytes")
    return key


def create_pilot_backup(data_directory: Path, destination: Path, key: bytes) -> PilotBackupManifest:
    """Create one atomic encrypted backup without exposing filenames or metadata."""

    source = data_directory.resolve()
    target = destination.resolve()
    if len(key) != 32:
        raise ValueError("backup encryption key must contain 32 bytes")
    if not source.is_dir():
        raise FileNotFoundError(f"pilot data directory not found: {source}")
    if target.exists():
        raise FileExistsError(f"backup destination already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix="madd-backup-") as temporary_name:
        staging = Path(temporary_name)
        for database_name in _DATABASES:
            database_path = source / database_name
            if database_path.exists():
                _snapshot_sqlite(database_path, staging / database_name)
        documents = source / "documents"
        if documents.exists():
            for blob in sorted(documents.rglob("*.madd")):
                relative = blob.relative_to(source)
                staged = staging / relative
                staged.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(blob, staged)

        files = _file_manifest(staging)
        if "pilot.sqlite3" not in files:
            raise BackupValidationError("pilot.sqlite3 is required for a recoverable backup")
        manifest = PilotBackupManifest(1, datetime.now(UTC), files)
        archive = _build_archive(staging, manifest)
        nonce = os.urandom(_NONCE_BYTES)
        encrypted = AESGCM(key).encrypt(nonce, archive, _MAGIC)
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(_MAGIC + nonce + encrypted)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, target)
            with suppress(OSError):
                target.chmod(0o600)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
    return manifest


def verify_pilot_backup(archive_path: Path, key: bytes) -> PilotBackupManifest:
    """Authenticate the envelope and verify every manifest digest without restoring it."""

    archive, manifest = _open_backup(archive_path, key)
    _verify_archive(archive, manifest)
    return manifest


def restore_pilot_backup(
    archive_path: Path,
    destination: Path,
    key: bytes,
) -> PilotBackupManifest:
    """Restore into a new directory only after full authentication and digest validation."""

    target = destination.resolve()
    if target.exists():
        raise FileExistsError(f"restore destination must not exist: {target}")
    archive, manifest = _open_backup(archive_path, key)
    entries = _verify_archive(archive, manifest)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.restore-{uuid4().hex}"
    temporary.mkdir()
    try:
        with zipfile.ZipFile(io.BytesIO(archive), "r") as bundle:
            for name in sorted(entries):
                output = (temporary / Path(PurePosixPath(name))).resolve()
                if not output.is_relative_to(temporary.resolve()):
                    raise BackupValidationError("backup entry escapes the restore directory")
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(bundle.read(name))
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return manifest


def _snapshot_sqlite(source: Path, destination: Path) -> None:
    source_connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True, timeout=10)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
        result = destination_connection.execute("PRAGMA quick_check").fetchone()
        if result is None or str(result[0]) != "ok":
            raise BackupValidationError(f"SQLite snapshot failed integrity check: {source.name}")
    finally:
        destination_connection.close()
        source_connection.close()


def _file_manifest(root: Path) -> dict[str, dict[str, object]]:
    files: dict[str, dict[str, object]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        content = path.read_bytes()
        files[relative] = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
    return files


def _build_archive(staging: Path, manifest: PilotBackupManifest) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(
            _MANIFEST,
            json.dumps(manifest.payload(), sort_keys=True, separators=(",", ":")),
        )
        for name in sorted(manifest.files):
            bundle.write(staging / Path(PurePosixPath(name)), name)
    return output.getvalue()


def _open_backup(path: Path, key: bytes) -> tuple[bytes, PilotBackupManifest]:
    if len(key) != 32:
        raise ValueError("backup encryption key must contain 32 bytes")
    payload = path.resolve().read_bytes()
    minimum = len(_MAGIC) + _NONCE_BYTES + 16
    if len(payload) < minimum or not payload.startswith(_MAGIC):
        raise BackupValidationError("backup has an invalid encrypted envelope")
    nonce_start = len(_MAGIC)
    nonce = payload[nonce_start : nonce_start + _NONCE_BYTES]
    encrypted = payload[nonce_start + _NONCE_BYTES :]
    try:
        archive = AESGCM(key).decrypt(nonce, encrypted, _MAGIC)
    except Exception as error:
        raise BackupValidationError("backup authentication failed") from error
    try:
        with zipfile.ZipFile(io.BytesIO(archive), "r") as bundle:
            raw = json.loads(bundle.read(_MANIFEST))
        if not isinstance(raw, dict) or raw.get("format_version") != 1:
            raise BackupValidationError("unsupported backup manifest")
        files = raw.get("files")
        if not isinstance(files, dict):
            raise BackupValidationError("backup manifest files are invalid")
        manifest = PilotBackupManifest(
            format_version=1,
            created_at=datetime.fromisoformat(str(raw["created_at"])),
            files=cast(dict[str, dict[str, object]], files),
        )
    except (KeyError, ValueError, TypeError, zipfile.BadZipFile) as error:
        raise BackupValidationError("backup manifest is invalid") from error
    return archive, manifest


def _verify_archive(archive: bytes, manifest: PilotBackupManifest) -> set[str]:
    with zipfile.ZipFile(io.BytesIO(archive), "r") as bundle:
        names = set(bundle.namelist())
        expected = set(manifest.files)
        if names != expected | {_MANIFEST}:
            raise BackupValidationError("backup content does not match its manifest")
        for name, metadata in manifest.files.items():
            _validate_entry_name(name)
            content = bundle.read(name)
            if metadata.get("size_bytes") != len(content):
                raise BackupValidationError(f"backup size mismatch: {name}")
            digest = hashlib.sha256(content).hexdigest()
            if metadata.get("sha256") != digest:
                raise BackupValidationError(f"backup digest mismatch: {name}")
    if "pilot.sqlite3" not in manifest.files:
        raise BackupValidationError("backup is missing pilot.sqlite3")
    return expected


def _validate_entry_name(name: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise BackupValidationError("backup contains an unsafe path")
    if path.name in {"pilot.sqlite3", "checkpoints.sqlite3"} and len(path.parts) == 1:
        return
    if len(path.parts) >= 2 and path.parts[0] == "documents" and path.suffix == ".madd":
        return
    raise BackupValidationError(f"backup contains an unexpected file: {name}")
