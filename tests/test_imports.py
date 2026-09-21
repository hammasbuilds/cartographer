"""Resolving imports to files, which is where the real bug was."""

from __future__ import annotations

from pathlib import Path

import pytest

from cartographer import imports


def build(tmp_path: Path, **files: str) -> imports.ImportGraph:
    for key, body in files.items():
        rel = key.replace("__", "/")
        if "." not in rel.rsplit("/", 1)[-1]:
            rel += ".py"
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return imports.build(tmp_path)


def test_from_dot_import_submodule_points_at_the_submodule(tmp_path):
    """The bug that made the whole map a star.

    `from . import certs` names the *package* in its text and the *submodule* in its intent.
    Resolving the spelling first sent the edge to `__init__.py` - and since this is the most
    common import form inside a package, most of a project's internal edges ended up at its
    package root. On requests it hid the `utils.py -> certs.py` edge entirely, which then
    showed up as a top "hidden coupling" finding: a bug reported as a discovery.
    """
    g = build(
        tmp_path,
        pkg____init__="from . import certs\n",
        pkg__certs="X = 1\n",
        pkg__utils="from . import certs\n",
    )
    assert ("pkg/utils.py", "pkg/certs.py") in g.edges
    assert ("pkg/utils.py", "pkg/__init__.py") not in g.edges


def test_absolute_submodule_import(tmp_path):
    g = build(
        tmp_path,
        src__pkg____init__="",
        src__pkg__core="X = 1\n",
        src__pkg__cli="from pkg.core import X\n",
    )
    assert ("src/pkg/cli.py", "src/pkg/core.py") in g.edges


def test_importing_a_class_resolves_to_its_module(tmp_path):
    """`from pkg.core import Context` names a class, which is not a file."""
    g = build(
        tmp_path,
        pkg____init__="",
        pkg__core="class Context: pass\n",
        pkg__cli="from pkg.core import Context\n",
    )
    assert ("pkg/cli.py", "pkg/core.py") in g.edges


def test_two_names_in_one_statement_are_two_edges(tmp_path):
    g = build(
        tmp_path,
        pkg____init__="",
        pkg__a="X=1\n",
        pkg__b="Y=1\n",
        pkg__c="from . import a, b\n",
    )
    assert ("pkg/c.py", "pkg/a.py") in g.edges
    assert ("pkg/c.py", "pkg/b.py") in g.edges


def test_a_parent_relative_import(tmp_path):
    g = build(
        tmp_path,
        pkg____init__="",
        pkg__shared="X=1\n",
        pkg__sub____init__="",
        pkg__sub__thing="from ..shared import X\n",
    )
    assert ("pkg/sub/thing.py", "pkg/shared.py") in g.edges


def test_the_standard_library_is_not_an_edge(tmp_path):
    g = build(tmp_path, a="import os\nimport json.decoder\n")
    assert g.edges == set()
    assert g.unresolved == 2


def test_a_file_importing_itself_is_not_an_edge(tmp_path):
    g = build(tmp_path, pkg____init__="", pkg__a="from pkg import a\n")
    assert not any(x == y for x, y in g.edges)


def test_an_unparseable_file_is_recorded_not_raised(tmp_path):
    """A repository with a Python 2 file or a broken fixture is normal. One that silently
    yields no edges is not."""
    g = build(tmp_path, ok="import os\n", bad="def (:\n")
    assert "bad.py" in g.unparseable
    assert "ok.py" not in g.unparseable


def test_virtualenvs_and_caches_are_skipped(tmp_path):
    # Written directly rather than through `build`'s `__` -> `/` convention: a name that
    # *starts* with `__`, like `__pycache__`, translates to a leading slash, and the test
    # then tries to create `/pycache`. On Windows that lands somewhere harmless and the
    # test passes; on Linux it is a permission error at the filesystem root.
    for rel in (".venv/lib/thing.py", "__pycache__/junk.py", "node_modules/x.py"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("X = 1\n", encoding="utf-8")
    g = build(tmp_path, a="X=1\n")
    assert g.files == ["a.py"]


def test_neighbours_is_undirected(tmp_path):
    g = build(tmp_path, pkg____init__="", pkg__a="X=1\n", pkg__b="from . import a\n")
    assert "pkg/b.py" in g.neighbours("pkg/a.py")
    assert "pkg/a.py" in g.neighbours("pkg/b.py")


@pytest.mark.parametrize("name", ["nothing", "pkg/missing.py"])
def test_neighbours_of_an_unknown_file_is_empty(tmp_path, name):
    g = build(tmp_path, a="X=1\n")
    assert g.neighbours(name) == set()
