"""Throwaway git repositories, built commit by commit.

The tests need real `git log` output, not a mock of it - the parsing of `--name-status`,
rename records and merge exclusion is most of what `history.py` does, and a fake would only
ever confirm what the fake was written to say. So each test builds an actual repository,
which costs a few hundred milliseconds and needs no network.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


class Repo:
    def __init__(self, root: Path):
        self.root = root
        self._git("init", "-q", "-b", "main")
        self._git("config", "user.email", "t@example.invalid")
        self._git("config", "user.name", "t")
        # Rename detection compares content, so it must not be disabled by a stray global.
        self._git("config", "diff.renames", "true")

    def _git(self, *args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout

    @staticmethod
    def _name(key: str) -> str:
        """`pkg__core` -> `pkg/core.py`. A key that already has a suffix is left alone."""
        path = key.replace("__", "/")
        return path if "." in path.rsplit("/", 1)[-1] else path + ".py"

    def write(self, path: str, body: str = "x = 1\n") -> None:
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")

    def commit(self, message: str, **files: str) -> None:
        for key, body in files.items():
            self.write(self._name(key), body)
        self._git("add", "-A")
        self._git("commit", "-q", "-m", message)

    def move(self, old: str, new: str) -> None:
        (self.root / new).parent.mkdir(parents=True, exist_ok=True)
        self._git("mv", old, new)
        self._git("commit", "-q", "-m", f"move {old} -> {new}")

    def delete(self, path: str) -> None:
        self._git("rm", "-q", path)
        self._git("commit", "-q", "-m", f"delete {path}")


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path)
