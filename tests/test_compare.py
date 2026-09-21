"""Sorting coupled pairs into what the code explains and what it does not."""

from __future__ import annotations

from cartographer import compare, couple
from cartographer.history import Commit, History
from cartographer.imports import ImportGraph


def graph(files: list[str], *edges: tuple[str, str]) -> ImportGraph:
    return ImportGraph(edges=set(edges), files=files)


def hist(*commits: list[str]) -> History:
    return History(commits=[Commit(f"s{i}", i, list(f)) for i, f in enumerate(commits)])


#: Commits touching nothing else under test. Without them a pair that appears in *every*
#: commit has a lift of exactly 1.0 - correctly indistinguishable from "both files always
#: change" - and is dropped before any of these rules is reached.
FILLER = [["filler.py"]] * 8


def test_a_direct_import_explains_the_coupling():
    g = graph(["a.py", "b.py"], ("a.py", "b.py"))
    cp = couple.build(hist(*[["a.py", "b.py"]] * 4, *FILLER), min_support=3)
    c = compare.run(g, cp)
    assert c.agreed == 1
    assert c.hidden == []


def test_a_shared_dependency_explains_it_too():
    """`a` and `b` both import `shared`, so the code does connect them."""
    g = graph(["a.py", "b.py", "shared.py"], ("a.py", "shared.py"), ("b.py", "shared.py"))
    cp = couple.build(hist(*[["a.py", "b.py"]] * 4, *FILLER), min_support=3)
    c = compare.run(g, cp)
    assert c.agreed == 1


def test_nothing_connecting_them_is_the_finding():
    g = graph(["a.py", "b.py"])
    cp = couple.build(hist(*[["a.py", "b.py"]] * 4, *FILLER), min_support=3)
    c = compare.run(g, cp)
    assert len(c.no_path()) == 1
    assert c.no_path()[0].via_hub is False


def test_a_package_root_does_not_count_as_a_connection():
    """The reason hop distance was thrown away.

    `__init__.py` imports every module in its package and is imported by everything outside
    it, so through it *every* file in a package is two hops from every other. Counting that
    as a connection makes the tool report nothing on a well-packaged library; the code has
    recorded that two files share a package, which was never in doubt.
    """
    g = graph(
        ["pkg/__init__.py", "pkg/a.py", "pkg/b.py"],
        ("pkg/__init__.py", "pkg/a.py"),
        ("pkg/__init__.py", "pkg/b.py"),
    )
    cp = couple.build(hist(*[["pkg/a.py", "pkg/b.py"]] * 4, *FILLER), min_support=3)
    c = compare.run(g, cp)
    assert c.agreed == 0
    assert len(c.hub_only()) == 1


def test_a_deleted_file_is_not_a_finding():
    """It has no import edges because it is gone, not because nothing connected it.

    On click every one of the top six findings was a pair of removed files, ranked above
    everything real precisely because nothing could possibly connect them.
    """
    g = graph(["a.py"])
    cp = couple.build(hist(*[["a.py", "deleted.py"]] * 4, *FILLER), min_support=3)
    c = compare.run(g, cp)
    assert c.hidden == []
    assert c.gone == 1
    assert c.total_coupled == 0


def test_a_low_lift_pair_is_dropped_and_counted():
    """`b` is in every commit, so it co-occurs with everything at lift 1."""
    commits = [["a.py", "b.py"]] * 3 + [["c.py", "b.py"]] * 3 + [["d.py", "b.py"]] * 3
    g = graph(["a.py", "b.py", "c.py", "d.py"])
    cp = couple.build(hist(*commits), min_support=3)
    c = compare.run(g, cp, min_lift=2.0)
    assert c.hidden == []
    assert c.weak_lift > 0


def test_a_test_and_its_subject_is_marked_not_counted_as_a_discovery():
    g = graph(["pkg/a.py", "tests/test_a.py"])
    cp = couple.build(hist(*[["pkg/a.py", "tests/test_a.py"]] * 4, *FILLER), min_support=3)
    c = compare.run(g, cp)
    assert len(c.test_pairs()) == 1
    assert c.no_path(include_tests=False) == []


def test_two_test_files_are_not_a_test_and_subject_pair():
    g = graph(["tests/test_a.py", "tests/test_b.py"])
    cp = couple.build(hist(*[["tests/test_a.py", "tests/test_b.py"]] * 4, *FILLER), min_support=3)
    c = compare.run(g, cp)
    assert c.test_pairs() == []
    assert len(c.no_path()) == 1


def test_an_import_that_never_co_changes_is_ceremonial():
    commits = [["a.py"]] * 6 + [["b.py"]] * 6
    g = graph(["a.py", "b.py"], ("a.py", "b.py"))
    cp = couple.build(hist(*commits), min_support=3)
    c = compare.run(g, cp, min_churn=5)
    assert c.ceremonial == [("a.py", "b.py", 0)]


def test_a_barely_touched_pair_is_not_called_ceremonial():
    """Two commits is not enough history to call anything stable."""
    g = graph(["a.py", "b.py"], ("a.py", "b.py"))
    cp = couple.build(hist(["a.py"], ["b.py"]), min_support=3)
    c = compare.run(g, cp, min_churn=5)
    assert c.ceremonial == []


def test_nothing_connects_them_sorts_above_connected_through_a_hub():
    g = graph(
        ["pkg/__init__.py", "pkg/a.py", "pkg/b.py", "x.py", "y.py"],
        ("pkg/__init__.py", "pkg/a.py"),
        ("pkg/__init__.py", "pkg/b.py"),
    )
    commits = [["pkg/a.py", "pkg/b.py"]] * 9 + [["x.py", "y.py"]] * 3 + FILLER
    cp = couple.build(hist(*commits), min_support=3)
    c = compare.run(g, cp)
    # The hub pair has three times the commits and still sorts second: a weaker claim
    # printed above a stronger one reads as the stronger one.
    assert c.hidden[0].via_hub is False


def test_looks_like_test_recognises_the_usual_spellings():
    for p in ("tests/test_a.py", "pkg/tests/x.py", "test_thing.py", "conftest.py"):
        assert compare.looks_like_test(p), p
    for p in ("pkg/core.py", "src/latest.py", "contest.py"):
        assert not compare.looks_like_test(p), p
