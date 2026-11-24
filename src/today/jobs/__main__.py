"""python -m today.jobs collect [--dry-run]: run every source once with the network and print the report.
python -m today.jobs analyze --one [--job-id N] [--profile FILE]: analyze one stored job, print the JSON.

Without --dry-run the postings go to DB_PATH (default data/today.db). --dry-run uses an in-memory database.
`analyze` uses ANALYST (default claude_cli) and ANALYST_MODEL (default sonnet) and writes nothing."""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from today.db import connect, migrate
from today.jobs.analyze import analyze_one
from today.jobs.collect import collect
from today.jobs.loop import select_sources
from today.jobs.sources import make_client
from today.llm.analyst import AnthropicApiAnalyst, ClaudeCliAnalyst


def analyze(args: argparse.Namespace) -> None:
    if not args.one:
        sys.exit("only `analyze --one` exists: slots analyze in batches inside the app")
    conn = connect(Path(os.environ.get("DB_PATH", "data/today.db")))
    migrate(conn)
    if os.environ.get("ANALYST") == "anthropic_api":
        import anthropic

        analyst = AnthropicApiAnalyst(anthropic.Anthropic())
    else:
        analyst = ClaudeCliAnalyst()
    profile = Path(args.profile).read_text() if args.profile else None
    model = os.environ.get("ANALYST_MODEL") or "sonnet"
    try:
        job, result = analyze_one(conn, analyst, model, args.job_id, profile)
    except ValueError as exc:
        sys.exit(str(exc))
    print(f"# {job.id} · {job.company} · {job.title}\n# {job.url}", file=sys.stderr)
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m today.jobs")
    parser.add_argument("command", choices=["collect", "analyze"])
    parser.add_argument("--dry-run", action="store_true", help="in-memory database, writes nothing")
    parser.add_argument("--sources", help="comma list, e.g. gupy,remotar (default: all)")
    parser.add_argument("--one", action="store_true", help="analyze: one job, print the JSON")
    parser.add_argument("--job-id", type=int, help="analyze: this job (default: next pending)")
    parser.add_argument("--profile", help="analyze: markdown file instead of the stored profile")
    args = parser.parse_args()
    if args.command == "analyze":
        return analyze(args)

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
