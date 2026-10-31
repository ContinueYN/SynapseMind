"""Explicit maintenance for the optional SQLite session store.

There is no background TTL job: deleting student snapshots is an operator
action. Dry-run is the default for every destructive command; add ``--apply``
only after reading the list.

Usage::

    python scripts/dev/session_store.py stats
    python scripts/dev/session_store.py migrate            # inspect legacy rows
    python scripts/dev/session_store.py migrate --apply    # rewrite them
    python scripts/dev/session_store.py cleanup --older-than-days 30
    python scripts/dev/session_store.py cleanup --older-than-days 30 --apply
    python scripts/dev/session_store.py purge --session-id S_... --apply

The database defaults to ``SYNAPSE_SESSION_DB``, then to
``var/synapse.sqlite3`` at the repository root.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows GBK consoles
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from synapse.infrastructure.session_maintenance import (  # noqa: E402
    CleanupReport,
    MigrationReport,
    PurgeReport,
    StoreStats,
    cleanup,
    migrate_store,
    purge,
    scan,
    vacuum_store,
)
from synapse.infrastructure.snapshots import SNAPSHOT_VERSION  # noqa: E402
from synapse.infrastructure.sqlite_state import (  # noqa: E402
    SCHEMA_VERSION,
    StateSchemaError,
)


def _resolve_db(raw: Path | None) -> Path:
    if raw is not None:
        return raw.expanduser().resolve()
    env = os.environ.get("SYNAPSE_SESSION_DB", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (ROOT / "var" / "synapse.sqlite3").resolve()


def _print_stats(stats: StoreStats) -> None:
    print(f"store:    {stats.path}")
    print(f"schema:   {stats.schema_version} (this build: {SCHEMA_VERSION})")
    print(f"file:     {stats.file_bytes} bytes")
    print(f"sessions: {stats.session_count}")
    print(f"problems: {stats.problem_count}")
    print(f"oldest:   {stats.oldest_session_at or '-'}")
    print(f"newest:   {stats.newest_session_at or '-'}")
    print("snapshots:")
    if not stats.versions:
        print("  (empty)")
        return
    for item in stats.versions:
        marker = "" if item.version == SNAPSHOT_VERSION else "  <- needs migrate"
        print(f"  {item.kind} {item.version}: {item.count}{marker}")


def _print_migration(report: MigrationReport) -> int:
    if report.errors:
        print("migration aborted; no snapshot was written:", file=sys.stderr)
        for error in report.errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    if not report.changes:
        print(f"nothing to migrate: every snapshot is already {SNAPSHOT_VERSION}")
        return 0
    for change in report.changes:
        print(
            f"  {change.kind} {change.from_version} -> {change.to_version}: {change.count} row(s)"
        )
    if report.apply:
        print(f"migrated {report.path}")
    else:
        print("dry run; pass --apply to rewrite the rows")
    return 0


def _print_cleanup(report: CleanupReport) -> int:
    print(f"cutoff:   {report.cutoff.isoformat(timespec='seconds')}")
    print(f"sessions: {len(report.session_ids)}")
    for session_id in report.session_ids:
        print(f"  {session_id}")
    if report.include_orphan_problems:
        print(f"problems: {len(report.problem_ids)}")
        for problem_id in report.problem_ids:
            print(f"  {problem_id}")
    if not report.session_ids and not report.problem_ids:
        print("nothing to clean")
        return 0
    if report.apply:
        print(f"deleted from {report.path}")
    else:
        print("dry run; pass --apply to delete these rows")
    return 0


def _print_purge(report: PurgeReport) -> int:
    print(f"sessions: {len(report.session_ids)}")
    for session_id in report.session_ids:
        print(f"  {session_id}")
    for session_id in report.missing_ids:
        print(f"  missing: {session_id}", file=sys.stderr)
    if report.problem_ids:
        print(f"problems: {len(report.problem_ids)}")
        for problem_id in report.problem_ids:
            print(f"  {problem_id}")
    if not report.session_ids and not report.problem_ids:
        return 1 if report.missing_ids else 0
    if report.apply:
        print(f"deleted from {report.path}")
    else:
        print("dry run; pass --apply to delete these rows")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite file (default: SYNAPSE_SESSION_DB, then var/synapse.sqlite3)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("stats", help="show schema, row counts and snapshot versions")

    migrate = commands.add_parser("migrate", help="rewrite legacy snapshot versions")
    migrate.add_argument("--apply", action="store_true", help="write the migration")

    clean = commands.add_parser("cleanup", help="delete sessions older than a TTL")
    clean.add_argument(
        "--older-than-days",
        type=float,
        required=True,
        help="delete sessions whose updated_at is older than this many days",
    )
    clean.add_argument("--apply", action="store_true", help="delete the selected rows")
    clean.add_argument(
        "--include-orphan-problems",
        action="store_true",
        help="also delete stale generated problems no surviving session references",
    )
    clean.add_argument(
        "--vacuum",
        action="store_true",
        help="reclaim free pages after deleting (drops residual row bytes)",
    )

    remove = commands.add_parser("purge", help="delete named sessions")
    remove.add_argument(
        "--session-id",
        dest="session_ids",
        action="append",
        required=True,
        help="session id to delete; repeat for more than one",
    )
    remove.add_argument("--apply", action="store_true", help="delete the selected rows")
    remove.add_argument(
        "--include-orphan-problems",
        action="store_true",
        help="also delete generated problems left without any session",
    )
    remove.add_argument(
        "--vacuum",
        action="store_true",
        help="reclaim free pages after deleting (drops residual row bytes)",
    )

    args = parser.parse_args()
    db = _resolve_db(args.db)
    try:
        if args.command == "stats":
            if not db.is_file():
                print(f"no store at {db} (nothing to inspect)")
                return 0
            _print_stats(scan(db))
            return 0
        if args.command == "migrate":
            return _print_migration(migrate_store(db, apply=args.apply))
        if args.command == "cleanup":
            report = cleanup(
                db,
                older_than_days=args.older_than_days,
                apply=args.apply,
                include_orphan_problems=args.include_orphan_problems,
            )
            code = _print_cleanup(report)
            if code == 0 and args.apply and args.vacuum:
                vacuum_store(db)
                print(f"vacuumed {db}")
            return code
        if args.command == "purge":
            report = purge(
                db,
                session_ids=args.session_ids,
                apply=args.apply,
                include_orphan_problems=args.include_orphan_problems,
            )
            code = _print_purge(report)
            if code == 0 and args.apply and args.vacuum:
                vacuum_store(db)
                print(f"vacuumed {db}")
            return code
    except (FileNotFoundError, StateSchemaError, ValueError, sqlite3.Error) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
