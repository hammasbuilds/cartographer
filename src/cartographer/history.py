"""What the git history says changed together.

Three things have to be right or the co-change graph is noise wearing a number.

**Merges are excluded.** A merge commit's file list is the union of everything it brings in,
which would couple every file in a feature branch to every other. It is not a change; it is
an accounting entry.

**Renames are followed.** `src/click/core.py` was `click/core.py` for the first half of this
history. Treated as two files, each one's coupling evidence is cut in half and the pair
`(core.py, core.py)` appears as a strong coupling between a file and itself.

**Enormous commits are dropped.** A reformat, a vendoring, a license header sweep - one
commit touching 400 files asserts 79,800 pairwise couplings, all of them meaningless, and
they swamp everything real. The cap is a judgement call, so it is stated, and the number of
commits it excluded is reported rather than hidden.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

#: Commits touching more than this many files are excluded from the coupling graph.
#: A commit of 30 files already asserts 435 pairs; beyond that the ratio of mechanical to
#: meaningful edits goes the wrong way fast.
DEFAULT_MAX_FILES = 30


@dataclass
class Commit:
    sha: str
    when: int
    """Unix timestamp. Committer date, so the ordering matches the branch, not the author."""

    files: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.files)


@dataclass
class History:
    commits: list[Commit] = field(default_factory=list)
    """Oldest first."""

    renames: dict[str, str] = field(default_factory=dict)
    """Historical path -> the path it is known by at HEAD."""

    skipped_large: int = 0
    max_files: int = DEFAULT_MAX_FILES
    followed_renames: bool = True
    """False when rename detection was unavailable - see `read`."""

    def span(self) -> tuple[int, int]:
        return (self.commits[0].when, self.commits[-1].when) if self.commits else (0, 0)


def _git(repo: Path, *args: str, timeout: float = 600.0) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()[:200]}")
    return proc.stdout


def is_repo(path: Path) -> bool:
    try:
        return _git(path, "rev-parse", "--is-inside-work-tree").strip() == "true"
    except (RuntimeError, OSError, subprocess.SubprocessError):
        return False


def _has_commits(repo: Path) -> bool:
    try:
        return bool(_git(repo, "rev-parse", "--verify", "HEAD").strip())
    except (RuntimeError, OSError, subprocess.SubprocessError):
        return False


def read(
    repo: Path,
    suffix: str = ".py",
    max_files: int = DEFAULT_MAX_FILES,
    limit: int = 0,
) -> History:
    """Every non-merge commit, newest-first from git, returned oldest-first.

    `-M` turns copy/rename detection on: `--name-status` then emits `R100\\told\\tnew`, which
    is the only way to learn that two paths are one file.
    """
    base = ["log", "--no-merges", "--name-status", "--pretty=format:\x01%H\x02%ct"]
    if limit:
        base += [f"-n{limit}"]

    if not _has_commits(repo):
        # A freshly initialised repository. `git log` exits non-zero on it, and raising
        # would be wrong: there is no history, which is a perfectly good answer.
        return History(max_files=max_files)

    followed_renames = True
    try:
        out = _git(repo, *base[:1], "-M", *base[1:])
    except (RuntimeError, OSError, subprocess.SubprocessError):
        # `-M` compares file *contents* to find renames, so on a partial clone
        # (`--filter=blob:none`) it reaches for blobs that were never downloaded and the
        # whole log fails - on an offline machine, with a network error. Renames then go
        # unfollowed, which splits a file's history in two; that is a worse map, not a
        # broken one, so it is recorded and reported rather than raised.
        followed_renames = False
        out = _git(repo, *base, "--no-renames")

    hist = History(max_files=max_files, followed_renames=followed_renames)
    canon: dict[str, str] = {}

    # git walks newest first, so by the time an old path is seen the new one is already
    # known - which is exactly the direction needed to fold a chain of renames onto HEAD.
    raw: list[Commit] = []
    current: Commit | None = None

    for line in out.splitlines():
        if line.startswith("\x01"):
            if current is not None:
                raw.append(current)
            sha, _, ts = line[1:].partition("\x02")
            current = Commit(sha, int(ts or 0))
            continue
        if not line.strip() or current is None:
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R") and len(parts) >= 3:
            old, new = parts[1], parts[2]
            canon[old] = canon.get(new, new)
            path = canon[old]
        elif len(parts) >= 2:
            path = canon.get(parts[1], parts[1])
        else:
            continue
        if suffix and not path.endswith(suffix):
            continue
        if path not in current.files:
            current.files.append(path)

    if current is not None:
        raw.append(current)

    for c in raw:
        if not c.files:
            continue
        if len(c.files) > max_files:
            hist.skipped_large += 1
            continue
        hist.commits.append(c)

    hist.commits.reverse()  # oldest first: a time split needs an axis
    hist.renames = canon
    return hist


def split_by_time(hist: History, fraction: float = 0.8) -> tuple[History, History]:
    """Cut the history in two at a point in time, not at random.

    Sampling commits at random would let a pair that changed together in 2024 be learned
    from and then predicted in 2019. Every real use of this is a prediction about the
    future, so the evaluation has to be one too.
    """
    n = int(len(hist.commits) * fraction)
    a = History(
        hist.commits[:n],
        hist.renames,
        hist.skipped_large,
        hist.max_files,
        hist.followed_renames,
    )
    b = History(hist.commits[n:], hist.renames, 0, hist.max_files, hist.followed_renames)
    return a, b
