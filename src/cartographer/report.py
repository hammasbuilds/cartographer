"""Print the two maps side by side, and lead with how much of the second the first explains.

The share of co-change the import graph accounts for is the first line, because it sets how
much the rest is worth. At 76% the source is a good map of the repository and the exceptions
are worth chasing one by one. At 33% the source is not the map anybody is actually navigating
by, and the exceptions are the shape of the thing.
"""

from __future__ import annotations

import json
from pathlib import Path

from cartographer.compare import Comparison
from cartographer.couple import Coupling
from cartographer.history import History
from cartographer.imports import ImportGraph


def _pair_lines(pairs, limit: int) -> list[str]:
    out = []
    for p in pairs[:limit]:
        out.append(
            f"  {p.commits:>3} commits together   confidence {p.confidence:.2f}   lift {p.lift:.1f}"
        )
        out.append(f"      {p.a}")
        out.append(f"      {p.b}")
    if len(pairs) > limit:
        out.append(f"  ... and {len(pairs) - limit} more")
    return out


def text(
    hist: History,
    g: ImportGraph,
    cp: Coupling,
    c: Comparison,
    limit: int = 10,
) -> str:
    w = "=" * 76
    out = [w, "CARTOGRAPHER - the declared map against the revealed one", w]

    out.append(
        f"{len(hist.commits)} commits, {len(g.files)} files at HEAD, {len(g.edges)} import edges"
    )
    if hist.skipped_large:
        out.append(
            f"{hist.skipped_large} commits dropped for touching more than {hist.max_files} files"
        )
    if not hist.followed_renames:
        out.append(
            "renames could NOT be followed (partial clone) - a renamed file's history is "
            "split in two, which understates its coupling"
        )
    if g.unparseable:
        out.append(f"{len(g.unparseable)} files could not be parsed and hold no edges")
    out.append("")

    if not c.total_coupled:
        out.append("No file pair changed together often enough to count.")
        out.append(
            f"Either the history is short ({len(hist.commits)} commits) or "
            f"min_support={cp.min_support} is too high for it."
        )
        return "\n".join(out)

    share = c.agreed / c.total_coupled
    out.append(
        f"Of {c.total_coupled} coupled file pairs, the import graph explains "
        f"{c.agreed} - {share:.0%}."
    )
    out.append(
        f"  (a direct import, or a path of at most {c.max_real_hops} hops "
        f"that does not run through a package root)"
    )
    if c.gone:
        out.append(
            f"  {c.gone} further pairs involve a file that no longer exists and are not "
            f"counted either way."
        )
    out.append("")

    no_path = c.no_path(include_tests=False)
    hub = c.hub_only(include_tests=False)
    tests = c.test_pairs()

    out.append(f"{len(no_path):>4}  change together, nothing in the code connects them")
    out.append(f"{len(hub):>4}  connected only through a package __init__.py")
    out.append(f"{len(tests):>4}  a test and the module it covers (not a finding, see below)")
    out.append(f"{len(c.ceremonial):>4}  imported but never changed together")
    out.append("")

    if no_path:
        out.append("-" * 76)
        out.append("NOTHING IN THE CODE CONNECTS THESE")
        out.append("Something links them that the source does not state.")
        out.append("-" * 76)
        out += _pair_lines(no_path, limit)
        out.append("")

    if hub:
        out.append("-" * 76)
        out.append("CONNECTED ONLY THROUGH A PACKAGE ROOT")
        out.append("Neither imports the other; both are re-exported by the same __init__.py,")
        out.append("so the code records that they are in one package and nothing more.")
        out.append("-" * 76)
        out += _pair_lines(hub, limit)
        out.append("")

    if tests:
        out.append("-" * 76)
        out.append(f"A TEST AND ITS SUBJECT ({len(tests)} pairs)")
        out.append("Listed apart because it is not a discovery. It appears here at all")
        out.append("because the test imports the package rather than the module, so nothing")
        out.append("in the code says which module the test covers.")
        out.append("-" * 76)
        out += _pair_lines(tests, min(limit, 3))
        out.append("")

    if c.ceremonial:
        out.append("-" * 76)
        out.append("IMPORTED, NEVER CHANGED TOGETHER")
        out.append("A stable interface, or an import that outlived its use. Both look alike")
        out.append("from here, so this is a list to read, not a verdict.")
        out.append("-" * 76)
        for a, b, n in c.ceremonial[:limit]:
            out.append(f"  {n} shared commits   {a}  ->  {b}")
        if len(c.ceremonial) > limit:
            out.append(f"  ... and {len(c.ceremonial) - limit} more")

    return "\n".join(out)


def as_json(hist: History, g: ImportGraph, cp: Coupling, c: Comparison) -> dict:
    return {
        "commits": len(hist.commits),
        "skipped_large_commits": hist.skipped_large,
        "followed_renames": hist.followed_renames,
        "files_at_head": len(g.files),
        "import_edges": len(g.edges),
        "unparseable_files": len(g.unparseable),
        "coupled_pairs": c.total_coupled,
        "pairs_with_a_deleted_file": c.gone,
        "explained_by_imports": c.agreed,
        "explained_share": round(c.agreed / c.total_coupled, 4) if c.total_coupled else 0.0,
        "min_support": cp.min_support,
        "min_lift": c.min_lift,
        "unconnected": [p.as_row() for p in c.no_path(include_tests=False)],
        "via_package_root": [p.as_row() for p in c.hub_only(include_tests=False)],
        "test_and_subject": [p.as_row() for p in c.test_pairs()],
        "imported_never_co_changed": [
            {"importer": a, "imported": b, "shared_commits": n} for a, b, n in c.ceremonial
        ],
    }


def write_json(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
