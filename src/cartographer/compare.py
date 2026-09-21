"""Where the two maps disagree, which is the only part worth printing.

Where source and history agree there is nothing to say: these files import each other and
they change together, as you would expect. The map is interesting exactly where it is wrong.

**Hidden coupling** - changes together, nothing in the code connects them. Something links
these files that the source does not state: a wire format written in one and parsed in
another, a constant duplicated, a version string in two places. Nobody arriving at the
repository can see it, and nothing fails when only one side is changed. This is the finding.

**Ceremonial dependency** - imports, never changes together. Either a genuinely stable
interface, which is the system working, or an import that outlived whatever used it. The tool
cannot tell those apart and does not pretend to; it says which pairs to look at.

## Why hop distance had to be thrown away

The first version called a pair hidden when it was three or more import-hops apart. On click
that gave sensible answers; on flask and httpx it gave nothing but test files paired with the
modules they test.

The reason is `__init__.py`. A package root that re-exports its modules is imported by
everything and imports everything, so it is a hub - and through a hub, *every file in a
package is two hops from every other file in it*. Hop distance does not measure connection in
a Python package; it measures whether both files are in the same package, which was already
known.

So connectivity is computed on the graph with the re-export hubs **removed**, and a pair is
only hidden when nothing but a hub connects them. That turns a meaningless number into a
statement somebody can act on: *the only thing linking these two files is that they are in
the same package.*
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from cartographer.couple import Coupling
from cartographer.imports import ImportGraph

#: A pair must be this much more likely than chance before it counts as coupled at all.
#: At lift 1.0 the two files are independent; the count can still be large, because a file
#: that changes in half of all commits co-occurs with everything.
DEFAULT_MIN_LIFT = 2.0

#: How far a real (non-hub) import path may run before the connection stops counting. Two
#: hops is a shared module away, which most people would still call connected.
MAX_REAL_HOPS = 2


def looks_like_test(path: str) -> bool:
    parts = path.split("/")
    return any(p in ("tests", "test", "testing") for p in parts[:-1]) or parts[-1].startswith(
        ("test_", "conftest")
    )


def is_hub(path: str) -> bool:
    """A package root. Imports everything below it and is imported by everything above."""
    return path.endswith("__init__.py")


@dataclass
class Pair:
    a: str
    b: str
    commits: int
    confidence: float
    lift: float
    via_hub: bool
    """True when a package `__init__.py` is the only thing that connects them."""

    test_and_subject: bool = False
    """A test file paired with non-test code.

    Marked rather than dropped. That a test changes with what it tests is not a discovery -
    but the *reason* it lands here is: the test imports the package, not the module, so
    nothing in the code records which module it covers. Left unmarked it would pad the
    findings with the one pair every reader can predict.
    """

    def as_row(self) -> dict:
        return {
            "a": self.a,
            "b": self.b,
            "commits_together": self.commits,
            "confidence": round(self.confidence, 3),
            "lift": round(self.lift, 2),
            "connected_only_via_package_root": self.via_hub,
        }


@dataclass
class Comparison:
    hidden: list[Pair] = field(default_factory=list)
    ceremonial: list[tuple[str, str, int]] = field(default_factory=list)
    """(importer, imported, commits they ever shared) - always below min_support."""

    agreed: int = 0
    total_coupled: int = 0
    total_imports: int = 0
    gone: int = 0
    """Coupled pairs where at least one file no longer exists at HEAD.

    Reported, not silently dropped. A large number here says the history reaches back past a
    restructuring, which is worth knowing before reading anything else.
    """

    weak_lift: int = 0
    min_lift: float = DEFAULT_MIN_LIFT
    max_real_hops: int = MAX_REAL_HOPS

    def no_path(self, include_tests: bool = True) -> list[Pair]:
        return [
            p for p in self.hidden if not p.via_hub and (include_tests or not p.test_and_subject)
        ]

    def hub_only(self, include_tests: bool = True) -> list[Pair]:
        return [p for p in self.hidden if p.via_hub and (include_tests or not p.test_and_subject)]

    def test_pairs(self) -> list[Pair]:
        return [p for p in self.hidden if p.test_and_subject]


def _real_hops(adj: dict[str, set[str]], start: str, depth: int) -> dict[str, int]:
    """Breadth-first distance over an adjacency map, undirected.

    Undirected on purpose: if `cli.py` imports `core.py`, a change to `core.py` reaches
    `cli.py` just as surely as the other way round.
    """
    seen = {start: 0}
    q = deque([start])
    while q:
        cur = q.popleft()
        if seen[cur] >= depth:
            continue
        for nxt in adj.get(cur, ()):
            if nxt not in seen:
                seen[nxt] = seen[cur] + 1
                q.append(nxt)
    seen.pop(start, None)
    return seen


def hub_free_adjacency(g: ImportGraph) -> dict[str, set[str]]:
    """Adjacency with package roots dropped as intermediate nodes."""
    adj: dict[str, set[str]] = {}
    for a, b in g.edges:
        if is_hub(a) or is_hub(b):
            continue
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    return adj


def run(
    g: ImportGraph,
    cp: Coupling,
    min_lift: float = DEFAULT_MIN_LIFT,
    max_real_hops: int = MAX_REAL_HOPS,
    min_churn: int = 5,
) -> Comparison:
    out = Comparison(min_lift=min_lift, max_real_hops=max_real_hops, total_imports=len(g.edges))
    declared = {(a, b) if a < b else (b, a) for a, b in g.edges}

    # Only pairs that both still exist. The import graph is read at HEAD, so a file deleted
    # years ago has no edges at all - and "nothing connects them" is then a statement about
    # the repository's present, not about the pair. Without this the findings are dominated
    # by dead files: on click, every one of the top six was a pair of removed files, ranked
    # above everything real because nothing could possibly connect them.
    alive = set(g.files)

    adj = hub_free_adjacency(g)
    hop_cache: dict[str, dict[str, int]] = {}

    def real_distance(a: str, b: str) -> int:
        if a not in hop_cache:
            hop_cache[a] = _real_hops(adj, a, max_real_hops)
        return hop_cache[a].get(b, 99)

    for (a, b), n in cp.pairs.items():
        if a not in alive or b not in alive:
            out.gone += 1
            continue
        out.total_coupled += 1
        if (a, b) in declared:
            out.agreed += 1
            continue
        if real_distance(a, b) <= max_real_hops:
            out.agreed += 1
            continue

        # Direction matters for confidence, so report the stronger reading of the pair.
        conf = max(cp.confidence(a, b), cp.confidence(b, a))
        lift = max(cp.lift(a, b), cp.lift(b, a))
        if lift < min_lift:
            out.weak_lift += 1
            continue

        # Is there any path at all once hubs are allowed back in? If so, the two files are
        # connected, but only by a package root re-exporting both - which is a weaker
        # finding and is kept apart from the ones nothing connects.
        via = _hub_reachable(g, a, b)
        is_test_pair = looks_like_test(a) != looks_like_test(b)
        out.hidden.append(Pair(a, b, n, conf, lift, via, is_test_pair))

    # Nothing-connects-them sorts above connected-only-through-a-hub; the two are different
    # claims, and printing them in one list would let the weaker pass for the stronger.
    out.hidden.sort(key=lambda p: (p.test_and_subject, p.via_hub, -p.commits, -p.lift))

    for a, b in sorted(declared):
        if cp.churn.get(a, 0) < min_churn or cp.churn.get(b, 0) < min_churn:
            # Too little history to call anything about this pair stable.
            continue
        if cp.support(a, b) < cp.min_support:
            out.ceremonial.append((a, b, cp.support(a, b)))

    out.ceremonial.sort(key=lambda t: (t[2], t[0]))
    return out


def _hub_reachable(g: ImportGraph, a: str, b: str, depth: int = 4) -> bool:
    seen = {a}
    q = deque([(a, 0)])
    while q:
        cur, d = q.popleft()
        if d >= depth:
            continue
        for nxt in g.neighbours(cur):
            if nxt == b:
                return True
            if nxt not in seen:
                seen.add(nxt)
                q.append((nxt, d + 1))
    return False
