"""Confidence, lift, and the floors that keep coincidence out."""

from __future__ import annotations

from cartographer import couple
from cartographer.history import Commit, History


def hist(*commits: list[str]) -> History:
    return History(commits=[Commit(f"s{i}", i, list(f)) for i, f in enumerate(commits)])


def test_a_pair_below_min_support_is_dropped():
    """Two files sharing one commit have 100% confidence, and a repo has thousands of them."""
    cp = couple.build(hist(["a", "b"]), min_support=3)
    assert cp.pairs == {}


def test_a_pair_at_min_support_is_kept():
    cp = couple.build(hist(["a", "b"], ["a", "b"], ["a", "b"]), min_support=3)
    assert cp.support("a", "b") == 3


def test_support_is_symmetric():
    cp = couple.build(hist(*[["a", "b"]] * 3), min_support=3)
    assert cp.support("a", "b") == cp.support("b", "a")


def test_confidence_is_not():
    """`a` never changes without `b`; `b` changes without `a` half the time."""
    cp = couple.build(hist(*[["a", "b"]] * 3, *[["b", "c"]] * 3), min_support=3)
    assert cp.confidence("a", "b") == 1.0
    assert cp.confidence("b", "a") == 0.5


def test_lift_is_one_for_a_file_that_changes_in_everything():
    """The trap confidence alone walks into.

    `noise` is in every commit, so its confidence with anything is 1.0 - which says nothing
    about a relationship and everything about `noise`. Lift divides that out.
    """
    commits = [["a", "noise"], ["b", "noise"], ["c", "noise"]] * 3
    cp = couple.build(hist(*commits), min_support=3)
    assert cp.confidence("a", "noise") == 1.0
    assert abs(cp.lift("a", "noise") - 1.0) < 1e-9


def test_lift_is_high_for_a_genuinely_exclusive_pair():
    commits = [["a", "b"]] * 3 + [["c"], ["d"], ["e"], ["f"]] * 3
    cp = couple.build(hist(*commits), min_support=3)
    assert cp.lift("a", "b") > 4


def test_churn_counts_commits_not_pairs():
    cp = couple.build(hist(["a", "b"], ["a", "c"], ["a"]), min_support=1)
    assert cp.churn["a"] == 3
    assert cp.churn["b"] == 1


def test_a_file_repeated_in_one_commit_is_counted_once():
    cp = couple.build(hist(["a", "a", "b"]), min_support=1)
    assert cp.churn["a"] == 1
    assert cp.support("a", "b") == 1


def test_confidence_of_an_unknown_file_is_zero_not_an_error():
    cp = couple.build(hist(["a", "b"]), min_support=1)
    assert cp.confidence("nope", "a") == 0.0
    assert cp.lift("nope", "a") == 0.0


def test_partners_are_sorted_by_support():
    commits = [["a", "b"]] * 5 + [["a", "c"]] * 2
    cp = couple.build(hist(*commits), min_support=1)
    assert [p for p, _ in cp.partners("a")] == ["b", "c"]


def test_an_empty_history_yields_an_empty_graph():
    cp = couple.build(History())
    assert cp.pairs == {} and cp.commits == 0
    assert cp.lift("a", "b") == 0.0
