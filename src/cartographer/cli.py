"""Command line: `map` a repository, `bench` the two maps against held-out commits."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cartographer import bench as bench_mod
from cartographer import compare, couple, history, imports
from cartographer import report as report_mod


def _say(msg: str) -> None:
    print(f"  .. {msg}", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="cartographer",
        description="Compare what a repository's imports declare against what its history reveals.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("map", help="the two maps, and where they disagree")
    m.add_argument("repo", type=Path)
    m.add_argument(
        "--min-support",
        type=int,
        default=couple.DEFAULT_MIN_SUPPORT,
        help=f"commits a pair must share to count (default {couple.DEFAULT_MIN_SUPPORT}). "
        "At 1, a repository has tens of thousands of pairs at 100%% confidence.",
    )
    m.add_argument(
        "--min-lift",
        type=float,
        default=compare.DEFAULT_MIN_LIFT,
        help=f"how much more likely than chance a pair must be (default "
        f"{compare.DEFAULT_MIN_LIFT}). At 1.0 a pair is indistinguishable from coincidence.",
    )
    m.add_argument(
        "--max-files",
        type=int,
        default=history.DEFAULT_MAX_FILES,
        help=f"drop commits touching more than this many files (default "
        f"{history.DEFAULT_MAX_FILES}); a reformat couples everything to everything",
    )
    m.add_argument("--limit", type=int, default=10, help="pairs to print per section")
    m.add_argument("--json", type=Path)
    m.add_argument("--quiet", action="store_true")

    b = sub.add_parser("bench", help="score both maps on commits they have not seen")
    b.add_argument("repo", type=Path)
    b.add_argument("--fraction", type=float, default=0.8, help="train share, split by time")
    b.add_argument("--min-support", type=int, default=couple.DEFAULT_MIN_SUPPORT)
    b.add_argument("--max-files", type=int, default=history.DEFAULT_MAX_FILES)
    b.add_argument("--max-queries", type=int, default=100000)
    b.add_argument("--json", type=Path)
    b.add_argument("--quiet", action="store_true")

    a = p.parse_args(argv)
    say = None if a.quiet else _say

    if not a.repo.exists():
        print(f"no such path: {a.repo}", file=sys.stderr)
        return 2
    if not history.is_repo(a.repo):
        print(f"not a git repository: {a.repo}", file=sys.stderr)
        print("Half of this tool reads git history; there is nothing to compare without it.")
        return 2

    if a.cmd == "bench":
        res = bench_mod.run(
            a.repo,
            fraction=a.fraction,
            min_support=a.min_support,
            max_files=a.max_files,
            max_queries=a.max_queries,
            progress=say,
        )
        print(bench_mod.text(res))
        if a.json:
            bench_mod.write_json(res, a.json)
            print(f"\nwrote {a.json}")
        return 0

    if say:
        say("reading history")
    hist = history.read(a.repo, max_files=a.max_files)
    if not hist.commits:
        print(f"no commits touching .py files in {a.repo}", file=sys.stderr)
        return 1

    if say:
        say(f"{len(hist.commits)} commits; building import graph")
    g = imports.build(a.repo)

    if say:
        say("building co-change graph")
    cp = couple.build(hist, min_support=a.min_support)
    c = compare.run(g, cp, min_lift=a.min_lift)

    print(report_mod.text(hist, g, cp, c, limit=a.limit))
    if a.json:
        report_mod.write_json(report_mod.as_json(hist, g, cp, c), a.json)
        print(f"\nwrote {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
