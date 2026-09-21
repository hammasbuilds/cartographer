"""What the history says changes together: the revealed architecture.

Two files that always change in the same commit are coupled, whether or not either imports
the other. That is the whole idea, and the only difficulty is that raw co-occurrence counts
are dominated by whichever files change most - a changelog or a version file co-occurs with
everything, and ranking by count puts it at the top of every list.

So two numbers, and they answer different questions:

    confidence(a -> b)   of the commits touching a, the share that also touched b
    lift(a, b)           how much more often than chance, given how often b changes at all

Confidence is what you want when *predicting*: you have touched `a`, what else will you
touch? It is deliberately asymmetric, because the answer is.

Lift is what you want when *reporting*: a pair with 90% confidence and a lift of 1.1 is
telling you that `b` changes in 90% of all commits, which is a fact about `b` and not a
relationship. Anything at lift ~1 is coincidence with a large count.

A minimum support is not optional. Two files sharing exactly one commit have a confidence of
100%, and a repository has tens of thousands of such pairs.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations

from cartographer.history import History

#: Pairs seen in fewer commits than this are dropped. Below 3 the graph is mostly pairs of
#: files that were touched together once, which is not evidence of anything.
DEFAULT_MIN_SUPPORT = 3


@dataclass
class Coupling:
    pairs: dict[tuple[str, str], int] = field(default_factory=dict)
    """Sorted (a, b) -> commits containing both."""

    churn: Counter = field(default_factory=Counter)
    """file -> commits touching it."""

    commits: int = 0
    min_support: int = DEFAULT_MIN_SUPPORT

    def support(self, a: str, b: str) -> int:
        return self.pairs.get((a, b) if a < b else (b, a), 0)

    def confidence(self, a: str, b: str) -> float:
        """Of the commits touching `a`, the share that also touched `b`."""
        n = self.churn.get(a, 0)
        return self.support(a, b) / n if n else 0.0

    def lift(self, a: str, b: str) -> float:
        """Confidence over the base rate of `b`. 1.0 means indistinguishable from chance."""
        base = self.churn.get(b, 0) / self.commits if self.commits else 0.0
        return self.confidence(a, b) / base if base else 0.0

    def partners(self, a: str) -> list[tuple[str, int]]:
        out = [(b if x == a else x, n) for (x, b), n in self.pairs.items() if x == a or b == a]
        return sorted(out, key=lambda t: -t[1])


def build(hist: History, min_support: int = DEFAULT_MIN_SUPPORT) -> Coupling:
    c = Coupling(min_support=min_support, commits=len(hist.commits))
    counts: Counter = Counter()
    for commit in hist.commits:
        files = sorted(set(commit.files))
        c.churn.update(files)
        # Pairs, not the commit itself: a commit of n files is n*(n-1)/2 assertions, which
        # is why history.read caps n.
        counts.update(combinations(files, 2))
    c.pairs = {k: v for k, v in counts.items() if v >= min_support}
    return c
