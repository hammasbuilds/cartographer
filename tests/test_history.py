"""Reading git history: the three things that have to be right, and the edges around them."""

from __future__ import annotations

from cartographer import history


def test_commits_come_back_oldest_first(repo):
    """A time split needs an axis, and git hands them over newest first."""
    repo.commit("one", a="x=1\n")
    repo.commit("two", b="x=2\n")
    repo.commit("three", c="x=3\n")
    h = history.read(repo.root)
    assert [c.files for c in h.commits] == [["a.py"], ["b.py"], ["c.py"]]


def test_only_python_files(repo):
    repo.commit("mixed", a="x=1\n", **{"README.md": "hi"})
    h = history.read(repo.root)
    assert h.commits[0].files == ["a.py"]


def test_commits_touching_no_python_are_dropped_entirely(repo):
    repo.commit("code", a="x=1\n")
    repo.commit("docs", **{"README.md": "hi"})
    h = history.read(repo.root)
    assert len(h.commits) == 1


def test_a_rename_folds_onto_the_name_at_head(repo):
    """Otherwise one file's history is two files', and each half looks less coupled."""
    repo.commit("start", **{"old__core.py": "x = 1\n" * 40})
    repo.commit("edit", **{"old__core.py": "x = 1\n" * 40 + "y = 2\n"})
    repo.move("old/core.py", "new/core.py")
    repo.commit("edit again", **{"new__core.py": "x = 1\n" * 40 + "y = 3\n"})

    h = history.read(repo.root)
    touched = {f for c in h.commits for f in c.files}
    assert touched == {"new/core.py"}
    assert h.followed_renames


def test_a_chain_of_renames_folds_all_the_way(repo):
    body = "x = 1\n" * 40
    repo.commit("start", **{"a.py": body})
    repo.move("a.py", "b.py")
    repo.move("b.py", "c.py")
    h = history.read(repo.root)
    assert {f for c in h.commits for f in c.files} == {"c.py"}


def test_enormous_commits_are_dropped_and_counted(repo):
    """One reformat asserts thousands of pairings and would swamp everything real."""
    repo.commit("normal", a="x=1\n", b="x=1\n")
    repo.commit("sweep", **{f"f{i}": "x=1\n" for i in range(12)})
    h = history.read(repo.root, max_files=5)
    assert len(h.commits) == 1
    assert h.skipped_large == 1


def test_a_file_is_counted_once_per_commit(repo):
    repo.commit("one", a="x=1\n")
    h = history.read(repo.root)
    assert h.commits[0].files.count("a.py") == 1


def test_deleting_a_file_still_records_the_commit(repo):
    """A deletion is a change to that file, and it couples with whatever removed its callers."""
    repo.commit("start", a="x=1\n", b="x=1\n")
    repo.delete("a.py")
    h = history.read(repo.root)
    assert h.commits[-1].files == ["a.py"]


def test_split_by_time_is_contiguous_and_ordered(repo):
    for i in range(10):
        repo.commit(f"c{i}", **{f"f{i}": "x=1\n"})
    h = history.read(repo.root)
    train, test = history.split_by_time(h, 0.8)
    assert len(train.commits) == 8 and len(test.commits) == 2
    assert train.commits[-1].when <= test.commits[0].when
    assert not set(c.sha for c in train.commits) & set(c.sha for c in test.commits)


def test_split_carries_the_rename_flag_to_both_halves(repo):
    repo.commit("one", a="x=1\n")
    h = history.read(repo.root)
    h.followed_renames = False
    train, test = history.split_by_time(h)
    assert not train.followed_renames and not test.followed_renames


def test_a_directory_that_is_not_a_repo(tmp_path):
    assert not history.is_repo(tmp_path)


def test_a_repo_with_no_commits_reads_as_empty(tmp_path):
    from tests.conftest import Repo

    r = Repo(tmp_path)
    assert history.read(r.root).commits == []
