"""Command-line interface.

python -m job_monitor                       # full monitoring run
python -m job_monitor --dry-run             # fetch + report, write nothing
python -m job_monitor --company Microsoft --company NVIDIA
python -m job_monitor validate-sources      # try every configured source
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .runner import Runner


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="job_monitor",
        description="Monitor company career sites for US new-grad software roles.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "validate-sources"],
        help="run (default) or validate-sources",
    )
    parser.add_argument(
        "--company",
        action="append",
        default=None,
        metavar="NAME",
        help="only process this company (repeatable)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and report changes without modifying tracked data",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    runner = Runner()
    if args.command == "validate-sources":
        rows = runner.validate_sources(only_companies=args.company)
        width = max(len(r["company"]) for r in rows) if rows else 10
        print(f"{'COMPANY':<{width}}  {'ADAPTER':<12} {'STATUS':<28} DETAIL")
        for row in rows:
            print(
                f"{row['company']:<{width}}  {row['source_type']:<12} "
                f"{row['status']:<28} {row.get('detail', '')}"
            )
        failed = sum(1 for r in rows if r["status"].startswith("FAILED"))
        print(f"\n{len(rows)} sources: {failed} failing")
        return 1 if failed else 0

    summary = runner.run(only_companies=args.company, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
