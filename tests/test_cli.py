"""End to end, on real repositories built for the occasion."""

from __future__ import annotations

import json

from cartographer.cli import main


def build_repo(repo):
    """A package where `a` and `b` change together while nothing in the code links them."""
    repo.commit(
        "start",
        pkg____init__="",
        pkg__a="A = 1\n",
        pkg__b="B = 1\n",
        pkg__c="from . import a\n",
        **{"README.md": "hi"},
    )
    for i in range(6):
        repo.commit(f"pair {i}", pkg__a=f"A = {i}\n", pkg__b=f"B = {i}\n")
    # Enough commits touching neither for `b` to have a base rate well under 1. A pair
    # appearing in half of all commits has a lift near 1 however reliably the two appear
    # together, and is correctly dropped as indistinguishable from "both files are busy".
    for i in range(14):
        repo.commit(f"solo {i}", pkg__c=f"from . import a  # {i}\n")
    return repo


def test_map_reports_the_unconnected_pair(repo, capsys):
    build_repo(repo)
    assert main(["map", str(repo.root), "--quiet", "--min-support", "3"]) == 0
    out = capsys.readouterr().out
    assert "pkg/a.py" in out and "pkg/b.py" in out
    assert "the import graph explains" in out


def test_map_writes_json(repo, capsys, tmp_path):
    build_repo(repo)
    dest = tmp_path / "out" / "map.json"
    main(["map", str(repo.root), "--quiet", "--min-support", "3", "--json", str(dest)])
    data = json.loads(dest.read_text())
    assert data["commits"] == 21
    assert data["files_at_head"] == 4
    assert 0.0 <= data["explained_share"] <= 1.0


def test_bench_runs_end_to_end(repo, capsys):
    build_repo(repo)
    assert main(["bench", str(repo.root), "--quiet", "--min-support", "1"]) == 0
    out = capsys.readouterr().out
    assert "PREDICTING THE NEXT COMMIT" in out
    for ranker in ("frequency", "imports", "cochange", "both"):
        assert ranker in out


def test_a_path_that_is_not_a_repo_is_refused(tmp_path, capsys):
    """Half the tool is git history; there is nothing to compare without it."""
    assert main(["map", str(tmp_path)]) == 2
    assert "not a git repository" in capsys.readouterr().err


def test_a_missing_path_is_refused(tmp_path, capsys):
    assert main(["map", str(tmp_path / "nope")]) == 2
    assert "no such path" in capsys.readouterr().err


def test_a_repo_with_no_python_commits_says_so(repo, capsys):
    repo.commit("docs only", **{"README.md": "hi"})
    assert main(["map", str(repo.root), "--quiet"]) == 1
    assert "no commits touching .py files" in capsys.readouterr().err


def test_a_short_history_says_so_rather_than_reporting_nothing(repo, capsys):
    """ "No pair met the threshold" and "this repository is well connected" look alike in a
    report that prints neither."""
    repo.commit("one", a="A=1\n", b="B=1\n")
    main(["map", str(repo.root), "--quiet", "--min-support", "5"])
    out = capsys.readouterr().out
    assert "No file pair changed together often enough" in out
    assert "min_support=5" in out
