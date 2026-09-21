"""The prediction task, and the things that would quietly inflate its numbers."""

from __future__ import annotations

from cartographer import bench, couple, predict
from cartographer.history import Commit, History
from cartographer.imports import ImportGraph

FILES = ["a.py", "b.py", "c.py", "d.py"]


def graph(*edges: tuple[str, str]) -> ImportGraph:
    return ImportGraph(edges=set(edges), files=list(FILES))


def hist(*commits: list[str]) -> History:
    return History(commits=[Commit(f"s{i}", i, list(f)) for i, f in enumerate(commits)])


def test_single_file_commits_are_not_scored():
    """They have nothing to predict, and a ranker would score by not being asked."""
    g = graph()
    cp = couple.build(hist(["a.py", "b.py"]), min_support=1)
    scores = bench.evaluate(g, cp, hist(["a.py"], ["b.py"]), FILES)
    assert all(s.queries == 0 for s in scores)


def test_each_file_of_a_commit_becomes_its_own_query():
    g = graph()
    cp = couple.build(hist(["a.py", "b.py"]), min_support=1)
    scores = bench.evaluate(g, cp, hist(["a.py", "b.py", "c.py"]), FILES)
    assert scores[0].queries == 3


def test_a_file_not_at_head_is_not_a_query():
    g = graph()
    cp = couple.build(hist(["a.py", "b.py"]), min_support=1)
    scores = bench.evaluate(g, cp, hist(["a.py", "gone.py"]), FILES)
    # Only one of the two survives, so the commit drops below two files and is not scored.
    assert scores[0].queries == 0


def test_the_query_is_never_its_own_answer():
    g = graph()
    cp = couple.build(hist(*[["a.py", "b.py"]] * 3), min_support=1)
    ranked = predict.rank("cochange", g, cp, "a.py", [f for f in FILES if f != "a.py"])
    assert "a.py" not in ranked


def test_a_perfect_ranker_scores_one():
    """`a` and `b` always change together and nothing else does."""
    train = hist(*[["a.py", "b.py"]] * 5, ["c.py", "d.py"], ["c.py"], ["d.py"])
    cp = couple.build(train, min_support=1)
    scores = bench.evaluate(graph(), cp, hist(["a.py", "b.py"]), FILES, rankers=("cochange",))
    assert scores[0].mrr == 1.0
    assert scores[0].hits_at[1] == 1.0


def test_recall_at_k_is_a_share_of_the_hidden_files_not_a_hit_or_miss():
    """A commit of four files with three found in the top 5 is 0.75, not 1.0."""
    train = hist(*[["a.py", "b.py", "c.py"]] * 4)
    cp = couple.build(train, min_support=1)
    scores = bench.evaluate(
        graph(), cp, hist(["a.py", "b.py", "c.py"]), FILES, rankers=("cochange",)
    )
    assert 0.0 < scores[0].hits_at[1] < 1.0


def test_frequency_ignores_the_query_entirely():
    cp = couple.build(hist(["a.py"], ["a.py"], ["b.py"], ["c.py", "d.py"]), min_support=1)
    g = graph()
    from_b = predict.rank("frequency", g, cp, "b.py", [f for f in FILES if f != "b.py"])
    from_c = predict.rank("frequency", g, cp, "c.py", [f for f in FILES if f != "c.py"])
    assert from_b[0] == "a.py" and from_c[0] == "a.py"


def test_imports_ranks_a_neighbour_above_a_stranger():
    g = graph(("a.py", "d.py"))
    cp = couple.build(hist(["b.py"], ["b.py"], ["b.py"]), min_support=1)
    ranked = predict.rank("imports", g, cp, "a.py", ["b.py", "c.py", "d.py"])
    # `b` is the most-churned file; the import edge still puts `d` first.
    assert ranked[0] == "d.py"


def test_both_backs_off_to_imports_where_history_is_silent():
    g = graph(("a.py", "d.py"))
    cp = couple.build(hist(["b.py"], ["b.py"]), min_support=1)
    ranked = predict.rank("both", g, cp, "a.py", ["b.py", "c.py", "d.py"])
    assert ranked[0] == "d.py"


def test_both_prefers_history_where_there_is_any():
    g = graph(("a.py", "d.py"))
    cp = couple.build(hist(*[["a.py", "c.py"]] * 4, ["b.py"]), min_support=1)
    ranked = predict.rank("both", g, cp, "a.py", ["b.py", "c.py", "d.py"])
    assert ranked[0] == "c.py"


def test_an_unknown_ranker_is_an_error_not_a_silent_default():
    import pytest

    with pytest.raises(ValueError):
        predict.rank("astrology", graph(), couple.build(hist()), "a.py", FILES)


def test_max_queries_caps_the_work():
    g = graph()
    cp = couple.build(hist(["a.py", "b.py"]), min_support=1)
    test = hist(*[["a.py", "b.py", "c.py"]] * 50)
    scores = bench.evaluate(g, cp, test, FILES, rankers=("frequency",), max_queries=10)
    assert scores[0].queries == 10
