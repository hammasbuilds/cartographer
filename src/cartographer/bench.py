"""Score the maps on commits they have never seen.

The split is by **time**, never at random. Sampling commits at random lets a pair that
changed together in 2024 be learned from and then predicted in 2019, and every real use of
this is a prediction about the future.

The task, for each held-out commit touching two or more files: take one file as the query,
hide the rest, rank every other file in the repository, and ask where the hidden ones landed.

    recall@k   share of the hidden files that made the top k
    MRR        1 / rank of the first hidden file found

Two decisions worth stating because they cut the other way from a flattering number:

**Candidates are every file, not a shortlist.** Ranking within a pre-filtered set would let
the filter do the work and hand the credit to the ranker.

**The import graph is read at HEAD**, which is *after* the test period. That is how the tool
is actually used - you have the code as it is now - but it is a real advantage, and it is the
import ranker that receives it. A finding that co-change beats imports is made stronger by
it, not weaker.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from cartographer import couple, history, imports, predict


@dataclass
class Score:
    ranker: str
    queries: int = 0
    hits_at: dict[int, float] = field(default_factory=dict)
    mrr: float = 0.0


KS = (1, 5, 10, 20)


def evaluate(
    g: imports.ImportGraph,
    cp: couple.Coupling,
    test: history.History,
    candidates: list[str],
    rankers: tuple[str, ...] = predict.RANKERS,
    max_queries: int = 2000,
) -> list[Score]:
    cand_set = set(candidates)
    tasks: list[tuple[str, set[str]]] = []
    for commit in test.commits:
        files = [f for f in dict.fromkeys(commit.files) if f in cand_set]
        if len(files) < 2:
            # A one-file commit has nothing to predict. Including them would let a ranker
            # score by not being asked.
            continue
        for q in files:
            rest = set(files) - {q}
            tasks.append((q, rest))
            if len(tasks) >= max_queries:
                break
        if len(tasks) >= max_queries:
            break

    out: list[Score] = []
    for name in rankers:
        s = Score(name, queries=len(tasks), hits_at=dict.fromkeys(KS, 0.0))
        for q, truth in tasks:
            pool = [f for f in candidates if f != q]
            ranked = predict.rank(name, g, cp, q, pool)
            positions = {f: i for i, f in enumerate(ranked)}
            for k in KS:
                top = set(ranked[:k])
                s.hits_at[k] += len(top & truth) / len(truth)
            first = min((positions[f] for f in truth if f in positions), default=None)
            if first is not None:
                s.mrr += 1.0 / (first + 1)
        if s.queries:
            s.hits_at = {k: v / s.queries for k, v in s.hits_at.items()}
            s.mrr /= s.queries
        out.append(s)
    return out


def run(
    repo: Path,
    fraction: float = 0.8,
    min_support: int = couple.DEFAULT_MIN_SUPPORT,
    max_files: int = history.DEFAULT_MAX_FILES,
    max_queries: int = 2000,
    progress=None,
) -> dict:
    say = progress or (lambda *_: None)
    started = time.time()

    say("reading history")
    hist = history.read(repo, max_files=max_files)
    train, test = history.split_by_time(hist, fraction)
    say(f"{len(hist.commits)} commits -> {len(train.commits)} train / {len(test.commits)} test")

    say("building import graph")
    g = imports.build(repo)

    say("building co-change graph from the training period only")
    cp = couple.build(train, min_support=min_support)

    # Candidates are the files that exist now. A file deleted before HEAD cannot be
    # recommended, and scoring against one would penalise every ranker equally but
    # make recall look worse than the task is.
    candidates = sorted(set(g.files))

    say("evaluating")
    scores = evaluate(g, cp, test, candidates, max_queries=max_queries)

    return {
        "repo": repo.name,
        "seconds": round(time.time() - started, 1),
        "commits": len(hist.commits),
        "skipped_large_commits": hist.skipped_large,
        "train_commits": len(train.commits),
        "test_commits": len(test.commits),
        "files_at_head": len(g.files),
        "import_edges": len(g.edges),
        "coupled_pairs": len(cp.pairs),
        "min_support": min_support,
        "max_files_per_commit": max_files,
        "queries": scores[0].queries if scores else 0,
        "scores": [
            {
                "ranker": s.ranker,
                "mrr": round(s.mrr, 4),
                **{f"recall@{k}": round(v, 4) for k, v in s.hits_at.items()},
            }
            for s in scores
        ],
    }


def text(res: dict) -> str:
    out = [
        "=" * 72,
        f"PREDICTING THE NEXT COMMIT - {res['repo']}",
        "=" * 72,
        f"{res['commits']} commits ({res['skipped_large_commits']} too large, dropped)",
        f"train {res['train_commits']}  ->  test {res['test_commits']}   (split by time, 80/20)",
        (
            f"{res['files_at_head']} files, {res['import_edges']} import edges, "
            f"{res['coupled_pairs']} coupled pairs"
        ),
        f"{res['queries']} held-out queries, {res['seconds']}s",
        "",
        f"{'ranker':<12}{'MRR':>8}{'r@1':>8}{'r@5':>8}{'r@10':>8}{'r@20':>8}",
        "-" * 72,
    ]
    for s in res["scores"]:
        out.append(
            f"{s['ranker']:<12}{s['mrr']:>8.3f}{s['recall@1']:>8.3f}"
            f"{s['recall@5']:>8.3f}{s['recall@10']:>8.3f}{s['recall@20']:>8.3f}"
        )
    return "\n".join(out)


def write_json(res: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, indent=2), encoding="utf-8")
