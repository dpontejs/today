"""python -m today.jobs collect [--dry-run]: run every source once with the network and print the report.

Without --dry-run the postings go to DB_PATH (default data/today.db). --dry-run uses an in-memory database."""

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path

from today.db import connect, migrate
from today.jobs.collect import collect
from today.jobs.loop import select_sources
from today.jobs.sources import make_client


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m today.jobs")
    parser.add_argument("command", choices=["collect"])
    parser.add_argument("--dry-run", action="store_true", help="in-memory database, writes nothing")
    parser.add_argument("--sources", help="comma list, e.g. gupy,remotar (default: all)")
    args = parser.parse_args()

    names = frozenset(s.strip() for s in args.sources.split(",") if s.strip()) if args.sources else None
    sources = select_sources(names)
    conn = (
        connect(Path(":memory:"))
        if args.dry_run
        else connect(Path(os.environ.get("DB_PATH", "data/today.db")))
    )
    migrate(conn)
    with make_client() as client:
        report = collect(conn, client, sources, datetime.now(UTC))

    print(f"{'source':<28} {'fetched':>7} {'kept':>5} {'new':>4}  error")
    for name, r in report.items():
        print(f"{name:<28} {r.fetched:>7} {r.kept:>5} {r.new:>4}  {r.error or ''}")
    print(
        f"{'total':<28} {sum(r.fetched for r in report.values()):>7} "
        f"{sum(r.kept for r in report.values()):>5} {sum(r.new for r in report.values()):>4}"
    )


if __name__ == "__main__":
    main()
