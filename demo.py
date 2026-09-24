"""Show what cartographer does, in one command, with nothing to set up.

    python demo.py

Cartographer compares the map a codebase *declares* - its import graph - against
the map its history *reveals*: which files actually change together. The claim
is that the second predicts what you will have to touch better than the first,
because coupling shows up in commits long before anyone writes an import.

Demonstrating that needs a repository with real history, and this one has three
commits. Running the benchmark here produces a table of zeros: truthful, and
useless as a demo.

So the demo builds a small repository whose coupling is known by construction.
Two files are edited together in almost every commit and never import each
other; two others import each other and never change together. A ranker that
only reads imports gets the second pair right and the first pair wrong, and
that gap is the whole thesis - visible here because the answer was planted
rather than inferred.

Takes about twenty seconds. Every commit below is a real commit.
"""

from __future__ import annotations

import os
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

ENV = {
    "GIT_AUTHOR_NAME": "demo",
    "GIT_AUTHOR_EMAIL": "demo@example.invalid",
    "GIT_COMMITTER_NAME": "demo",
    "GIT_COMMITTER_EMAIL": "demo@example.invalid",
}

# Files that move together but never import each other: a serialiser and the
# schema it writes, the classic pair that no static tool connects.
COUPLED = ("writer.py", "schema.py")

# Files that import each other but change independently: a stable utility and
# its caller.
IMPORTING = ("app.py", "helpers.py")


def git(args: list[str], cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={**os.environ, **ENV},
    )


def build(repo: Path, commits: int = 60) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    git(["init", "-q", "-b", "main"], repo)

    (repo / "helpers.py").write_text("def helper(x):\n    return x\n", encoding="utf-8")
    (repo / "app.py").write_text(
        "from helpers import helper\n\n\ndef run(x):\n    return helper(x)\n", encoding="utf-8"
    )
    (repo / "writer.py").write_text("def write(record):\n    return record\n", encoding="utf-8")
    (repo / "schema.py").write_text("FIELDS = ['id']\n", encoding="utf-8")
    git(["add", "-A"], repo)
    git(["commit", "-q", "-m", "initial"], repo)

    rng = random.Random(7)
    for n in range(commits):
        # The coupled pair moves in a MINORITY of commits, and that matters.
        #
        # Cartographer scores a pair by lift, not raw co-occurrence: two files
        # that both change in most commits move together about as often as any
        # two busy files would, so their lift sits near 1 and the pair carries
        # no information. An earlier version of this fixture edited the pair in
        # two commits out of three, which gave lift 1.52 - under the 2.0 floor -
        # and the pair was correctly dropped. The demo then asserted a finding
        # that was not in the output.
        if n % 3 == 0:
            # writer.py and schema.py, together, with no import between them.
            for name in COUPLED:
                path = repo / name
                path.write_text(
                    path.read_text(encoding="utf-8") + f"# field {n}\n", encoding="utf-8"
                )
            message = f"add field {n} to the record format"
        else:
            # One of the importing pair, alone.
            name = IMPORTING[rng.randrange(2)]
            path = repo / name
            path.write_text(path.read_text(encoding="utf-8") + f"# tweak {n}\n", encoding="utf-8")
            message = f"tidy {name}"
        git(["add", "-A"], repo)
        git(["commit", "-q", "-m", message], repo)


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="cartographer-demo-"))
    repo = work / "sample"
    try:
        print("Building a repository whose coupling is known in advance:", flush=True)
        print(
            f"  {COUPLED[0]} + {COUPLED[1]}   change together, never import each other", flush=True
        )
        print(
            f"  {IMPORTING[0]} + {IMPORTING[1]}   import each other, change independently",
            flush=True,
        )
        print(flush=True)
        build(repo)
        print(f"  built 61 real commits in {repo}", flush=True)
        print(flush=True)

        env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [sys.executable, "-m", "cartographer.cli", "map", str(repo), "--min-support", "3"],
            cwd=ROOT,
            env=env,
            check=False,
        )
        if result.returncode != 0:
            return result.returncode

        print(flush=True)
        print("The coupled pair is invisible to the import graph and obvious in the", flush=True)
        print("history. That gap is what the tool is for.", flush=True)
        print(flush=True)
        print("Point it at your own repository with:", flush=True)
        print("    cartographer map <repo>", flush=True)
        print("    cartographer bench <repo>   # split by time, and score the rankers", flush=True)
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
