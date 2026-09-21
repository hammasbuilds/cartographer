"""What the source says depends on what: the declared architecture.

Read with `ast`, never imported. Importing a repository to inspect it runs its module-level
code, which for anything real means side effects, missing dependencies, or both.

The hard part is not finding `import` statements. It is deciding which of them point at a
file *in this repository* - `from .core import Context` and `from click.core import Context`
and `import os` all look alike to a parser, and only the first two are edges on this map.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".tox",
    ".nox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "site-packages",
}


@dataclass
class ImportGraph:
    edges: set[tuple[str, str]] = field(default_factory=set)
    """(importer path, imported path), both repo-relative, both real files."""

    files: list[str] = field(default_factory=list)
    unresolved: int = 0
    """Imports that named nothing in this repo - the standard library and dependencies.

    Counted rather than discarded, because a resolution rate near zero means the module
    mapping is wrong, not that the project has no internal structure.
    """

    resolved: int = 0
    unparseable: list[str] = field(default_factory=list)

    _adj: dict[str, set[str]] | None = field(default=None, repr=False, compare=False)

    def neighbours(self, path: str) -> set[str]:
        """Both directions. Coupling is not a one-way relation even when import is."""
        if self._adj is None:
            adj: dict[str, set[str]] = {}
            for a, b in self.edges:
                adj.setdefault(a, set()).add(b)
                adj.setdefault(b, set()).add(a)
            self._adj = adj
        return self._adj.get(path, set())


def python_files(root: Path) -> list[str]:
    out = []
    for p in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        out.append(p.relative_to(root).as_posix())
    return sorted(out)


def _module_index(files: list[str]) -> dict[str, str]:
    """Every dotted name a file can be imported as -> the file.

    A repo with `src/click/core.py` is imported as `click.core`, not `src.click.core`, so
    every suffix of the path is registered. That over-generates - two files can claim the
    same short name - and first-wins on the longest, most specific spelling, which is the
    one an import is most likely to have meant.
    """
    index: dict[str, str] = {}
    for f in files:
        parts = f[:-3].split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
            if not parts:
                continue
        for i in range(len(parts)):
            name = ".".join(parts[i:])
            index.setdefault(name, f)
    return index


def _package_of(path: str) -> list[str]:
    """The dotted package a file lives in, for resolving `from . import x`."""
    parts = path[:-3].split("/")
    return parts[:-1]


def build(root: Path) -> ImportGraph:
    files = python_files(root)
    index = _module_index(files)
    g = ImportGraph(files=files)

    for f in files:
        try:
            tree = ast.parse((root / f).read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, ValueError, OSError):
            # Python 2 files, templates, deliberately broken test fixtures. A repo that
            # will not parse is normal; one that silently yields no edges is not.
            g.unparseable.append(f)
            continue

        for node in ast.walk(tree):
            for name in _targets(node, f):
                hit = _resolve(name, index)
                if hit is None:
                    g.unresolved += 1
                    continue
                g.resolved += 1
                if hit != f:
                    g.edges.add((f, hit))

    return g


def _targets(node: ast.AST, f: str) -> list[str]:
    """The dotted names one import statement is asking for, most specific first.

    `from . import certs` asks for the *submodule* `certs`, not for the package it lives in -
    but the package is what the statement spells, and resolving the spelling first sends the
    edge to `__init__.py` every time. `from . import x` is the most common import form in a
    Python package, so getting this backwards quietly redirects most of a project's internal
    edges to its package root, and leaves the map a star with a hub in the middle.

    One entry per alias, because `from . import a, b` is two dependencies, not one.
    """
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    if not isinstance(node, ast.ImportFrom):
        return []

    if node.level:
        # Relative: walk up `level - 1` packages from this file's own package.
        pkg = _package_of(f)
        up = node.level - 1
        base = pkg[: len(pkg) - up] if up else pkg
        head = ".".join([*base, node.module] if node.module else base)
    else:
        head = node.module or ""

    if not head:
        return []
    return [f"{head}.{a.name}" for a in node.names] or [head]


def _resolve(name: str, index: dict[str, str]) -> str | None:
    """Longest prefix of a dotted name that is a file in this repo.

    `from click.core import Context` yields `click.core.Context`, which is a class and not a
    module; trimming from the right finds `click.core`. `import os.path` trims to `os` and
    finds nothing, which is correct - it is not in this repository.
    """
    while name:
        if name in index:
            return index[name]
        if "." not in name:
            return None
        name = name.rpartition(".")[0]
    return None
