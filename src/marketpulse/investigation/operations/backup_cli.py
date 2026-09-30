"""Offline operational CLI. Database credentials are read from named environment variables."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from marketpulse.investigation.operations.backup import BackupError, backup, drill, restore, verify


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Paired database + immutable Blob backup and drill"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("backup")
    create.add_argument("--database-url-env", default="MARKETPULSE_DATABASE_URL")
    create.add_argument("--blob-root", required=True, type=Path)
    create.add_argument("--destination", required=True, type=Path)
    create.add_argument("--timeout", default=600, type=int)
    check = commands.add_parser("verify")
    check.add_argument("--archive", required=True, type=Path)
    for operation in ("restore", "drill"):
        command = commands.add_parser(operation)
        command.add_argument("--archive", required=True, type=Path)
        command.add_argument("--destination", required=True, type=Path)
        command.add_argument("--postgres-admin-url-env")
        command.add_argument("--timeout", default=600, type=int)
    args = parser.parse_args()
    try:
        if args.command == "backup":
            database_url = os.environ.get(args.database_url_env)
            if not database_url:
                raise BackupError("Database URL environment variable is unset")
            manifest = backup(
                database_url,
                args.blob_root,
                args.destination,
                timeout=args.timeout,
            )
            result = {
                "operation": "backup",
                "dialect": manifest.dialect,
                "blob_count": len(manifest.blob_hashes),
                "verified": True,
            }
        elif args.command == "verify":
            manifest = verify(args.archive)
            result = {
                "operation": "verify",
                "dialect": manifest.dialect,
                "verified": True,
                "database_references_checked": manifest.dialect == "sqlite",
                "postgresql_requires_restore_drill": manifest.dialect == "postgresql",
            }
        else:
            admin_url = None
            if args.postgres_admin_url_env:
                admin_url = os.environ.get(args.postgres_admin_url_env)
                if not admin_url:
                    raise BackupError("PostgreSQL admin URL environment variable is unset")
            action = drill if args.command == "drill" else restore
            result = action(
                args.archive,
                args.destination,
                postgres_admin_url=admin_url,
                timeout=args.timeout,
            )
            result["operation"] = args.command
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except BackupError as error:
        parser.exit(1, f"Backup operation failed: {error}\n")
    except Exception:
        # SQL/driver/filesystem exception messages may contain credentials or archived content.
        parser.exit(
            1, "Backup operation failed; inspect access, database tools and archive inputs.\n"
        )


if __name__ == "__main__":
    main()
