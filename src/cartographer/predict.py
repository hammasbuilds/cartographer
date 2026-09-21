"""The question that makes the two maps comparable.

*You are about to change this file. What else will you have to change?*

Both maps answer it. The import graph says "whatever this file imports, and whatever imports
it". The co-change graph says "whatever changed with it before". Held-out commits say which
one was right, and that is the only way to compare a map drawn from source against a map
drawn from history: not by which looks better, but by which predicts.

Four rankers, and the first one is the one that matters:

    frequency   ignore the query entirely; rank by how often each file changes
    imports     import-graph neighbours first, then their neighbours
    cochange    confidence learned from the training period
    both        co-change where there is evidence, imports where there is not

**`frequency` is not a straw man.** A handful of files absorb most of the churn in every
repository, so "guess the usual suspects" is a genuinely strong strategy, and a map that
cannot beat it has told you nothing you did not already know from `git log | sort | uniq -c`.
"""

from __future__ import annotations

from collections import deque

from cartographer.couple import Coupling
from cartographer.imports import ImportGraph


def by_frequency(cp: Coupling, query: str, candidates: list[str]) -> list[str]:
    return sorted(candidates, key=lambda f: (-cp.churn.get(f, 0), f))


def _hops(g: ImportGraph, query: str, depth: int = 3) -> dict[str, int]:
    """Breadth-first distance in the import graph, treating edges as undirected.

    Undirected on purpose: if `cli.py` imports `core.py`, a change to `core.py` reaches
    `cli.py` just as surely as the other way round. Direction tells you who depends on whom;
    it does not tell you which way a change propagates.
    """
    seen = {query: 0}
    q = deque([query])
    while q:
        cur = q.popleft()
        if seen[cur] >= depth:
            continue
        for nxt in g.neighbours(cur):
            if nxt not in seen:
                seen[nxt] = seen[cur] + 1
                q.append(nxt)
    seen.pop(query, None)
    return seen


def by_imports(
    g: ImportGraph, cp: Coupling, query: str, candidates: list[str], depth: int = 3
) -> list[str]:
    hops = _hops(g, query, depth)
    # Churn breaks ties *within* a hop distance. Without it, everything two hops away is
    # ordered alphabetically, which would make the import ranker lose for a silly reason.
    return sorted(candidates, key=lambda f: (hops.get(f, 99), -cp.churn.get(f, 0), f))


def by_cochange(cp: Coupling, query: str, candidates: list[str]) -> list[str]:
    return sorted(candidates, key=lambda f: (-cp.confidence(query, f), -cp.churn.get(f, 0), f))


def by_both(
    g: ImportGraph, cp: Coupling, query: str, candidates: list[str], depth: int = 3
) -> list[str]:
    """Co-change where there is evidence; the import graph where there is none.

    Not a weighted blend of the two scores - they are not on a shared scale, and inventing
    one would bury the comparison the benchmark exists to make. This is a back-off: a pair
    the history has never seen falls through to structure, which is precisely the case where
    history has nothing to say.
    """
    hops = _hops(g, query, depth)
    return sorted(
        candidates,
        key=lambda f: (
            -cp.confidence(query, f),
            hops.get(f, 99),
            -cp.churn.get(f, 0),
            f,
        ),
    )


RANKERS = ("frequency", "imports", "cochange", "both")


def rank(name: str, g: ImportGraph, cp: Coupling, query: str, candidates: list[str]) -> list[str]:
    if name == "frequency":
        return by_frequency(cp, query, candidates)
    if name == "imports":
        return by_imports(g, cp, query, candidates)
    if name == "cochange":
        return by_cochange(cp, query, candidates)
    if name == "both":
        return by_both(g, cp, query, candidates)
    raise ValueError(f"unknown ranker: {name}")
