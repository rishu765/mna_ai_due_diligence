"""Operator CLI for encrypted pilot backup, verification, and restore."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from ma_due_diligence.persistence import (
    backup_key_from_environment,
    create_pilot_backup,
    create_rotating_pilot_backup,
    restore_pilot_backup,
    verify_pilot_backup,
)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Manage encrypted DealLens pilot backups.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Create a new encrypted backup archive.")
    create.add_argument("data_directory", type=Path)
    create.add_argument("archive", type=Path)

    verify = subparsers.add_parser("verify", help="Authenticate and verify a backup archive.")
    verify.add_argument("archive", type=Path)

    restore = subparsers.add_parser("restore", help="Restore into a new, absent directory.")
    restore.add_argument("archive", type=Path)
    restore.add_argument("destination", type=Path)

    scheduled = subparsers.add_parser(
        "scheduled", help="Create, verify, and rotate timestamped backup archives."
    )
    scheduled.add_argument("data_directory", type=Path)
    scheduled.add_argument("backup_directory", type=Path)
    scheduled.add_argument("--retain", type=int, default=14)

    arguments = parser.parse_args(argv)
    key = backup_key_from_environment()
    if arguments.command == "create":
        manifest = create_pilot_backup(arguments.data_directory, arguments.archive, key)
    elif arguments.command == "verify":
        manifest = verify_pilot_backup(arguments.archive, key)
    elif arguments.command == "restore":
        manifest = restore_pilot_backup(arguments.archive, arguments.destination, key)
    else:
        archive, manifest = create_rotating_pilot_backup(
            arguments.data_directory,
            arguments.backup_directory,
            key,
            retain=arguments.retain,
        )
        print(json.dumps({"archive": str(archive), "manifest": manifest.payload()}, sort_keys=True))
        return
    print(json.dumps(manifest.payload(), sort_keys=True))


if __name__ == "__main__":
    main()
