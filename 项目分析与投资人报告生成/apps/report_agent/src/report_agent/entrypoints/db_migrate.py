"""Explicit Report Agent metadata schema migration command."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pymysql

from report_agent.infrastructure.persistence import mysql_connection_factory
from report_agent.settings import load_settings

_MIGRATIONS_DIR = Path("apps/report_agent/migrations")
# MySQL: Duplicate column name. Re-running ADD COLUMN on an existing database.
_DUPLICATE_COLUMN = 1060


def _migration_files(selected: Path | None) -> list[Path]:
    if selected is not None:
        return [selected]
    files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        raise SystemExit(f"no SQL migrations in {_MIGRATIONS_DIR}")
    return files


def _statements(path: Path) -> list[str]:
    sql = path.read_text(encoding="utf-8")
    return [statement.strip() for statement in sql.split(";") if statement.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply Report Agent MySQL metadata schema")
    parser.add_argument("--apply", action="store_true", help="required acknowledgement for DDL")
    parser.add_argument("--checkpoints", action="store_true", help="migrate the dedicated one-pager checkpoint schema only")
    parser.add_argument(
        "--migration",
        type=Path,
        default=None,
        help="apply one SQL file; default applies every file in apps/report_agent/migrations",
    )
    args = parser.parse_args()
    if not args.apply:
        raise SystemExit("refusing DDL without --apply")
    raw_config = os.environ.get("REPORT_AGENT_CONFIG", "").strip()
    if not raw_config:
        raise SystemExit("REPORT_AGENT_CONFIG is required")
    settings = load_settings(Path(raw_config))
    if args.checkpoints:
        if args.migration:
            raise SystemExit("--checkpoints cannot be combined with --migration")
        from report_agent.infrastructure.persistence.checkpoints import build_one_pager_checkpointer
        adapter = build_one_pager_checkpointer(settings.persistence.mysql, os.environ,
                                               settings.service.one_pager_checkpoint_database_env)
        adapter.saver.setup()
        print("one-pager checkpoint schema migrated")
        return
    files = _migration_files(args.migration)
    connect = mysql_connection_factory(settings.persistence.mysql, os.environ)
    connection = connect()
    applied = 0
    skipped = 0
    try:
        with connection.cursor() as cursor:
            for path in files:
                for statement in _statements(path):
                    try:
                        cursor.execute(statement)
                    except pymysql.err.OperationalError as exc:
                        if exc.args and exc.args[0] == _DUPLICATE_COLUMN:
                            skipped += 1
                            continue
                        raise
                    applied += 1
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    print(
        f"applied {applied} Report Agent schema statements"
        + (f", skipped {skipped} existing columns" if skipped else "")
    )


if __name__ == "__main__":
    main()
