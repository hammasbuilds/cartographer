# Results

Five Python libraries, 7,873 commits between them. Reproduce with:

```bash
cartographer map    /path/to/repo --json map.json
cartographer bench  /path/to/repo --json bench.json
```

Raw output for every run is in this directory (`map_*.json`, `bench_*.json`, `real.log`).

Thresholds, identical for all five and printed with every report:
`min_support=3` (commits a pair must share), `min_lift=2.0` (how much more likely than
chance), `max_files=30` (commits larger than this are dropped), `fraction=0.8` (train share).

---

## 1. Which map predicts the next commit

Learn from the oldest 80% of commits, predict the newest 20%. For each held-out commit
touching two or more files: take one file as the query, hide the rest, rank **every other
file in the repository**, and see where the hidden ones land.

### Mean reciprocal rank

| repo | commits | queries | frequency | imports | co-change | both |
|---|---:|---:|---:|---:|---:|---:|
| click | 1,304 | 425 | 0.449 | 0.365 | **0.586** | 0.588 |
| requests | 2,814 | 463 | 0.577 | 0.599 | **0.634** | 0.630 |
| flask | 2,014 | 692 | 0.620 | 0.554 | **0.653** | 0.625 |
| httpx | 974 | 439 | 0.502 | 0.483 | 0.553 | **0.554** |
| packaging | 767 | 313 | 0.389 | 0.601 | 0.661 | **0.707** |

### recall@10

| repo | frequency | imports | co-change | both |
|---|---:|---:|---:|---:|
| click | 0.449 | 0.504 | 0.609 | **0.615** |
| requests | 0.702 | 0.700 | **0.748** | 0.737 |
| flask | 0.400 | 0.479 | 0.489 | **0.519** |
| httpx | 0.307 | 0.365 | 0.376 | **0.397** |
| packaging | 0.454 | 0.736 | 0.617 | **0.738** |

### What the four rankers are

| | |
|---|---|
| `frequency` | ignores the query; ranks by how often each file changes |
| `imports` | import-graph neighbours first, then theirs; churn breaks ties within a distance |
| `co-change` | confidence learned from the training period only |
| `both` | co-change where there is evidence, imports where there is none — a back-off, not a blend |

`frequency` is not a straw man. A handful of files absorb most of the churn in every
repository, so "guess the usual suspects" is genuinely strong — and on flask it beats the
import graph outright (0.620 vs 0.554). A structural map that cannot beat it has told you
nothing you could not get from `git log | sort | uniq -c`.

### Reading it

**Co-change beats the churn baseline on all five**, by 0.03 to 0.27 MRR.

**The import graph beats it on two of five** — requests and packaging — and loses on click,
flask and httpx. This is despite an advantage the benchmark hands it: the import graph is
read at **HEAD**, which is after the test period, while co-change may only learn from the
training window.

**`both` is best where structure is informative.** On packaging it is clearly ahead of either
alone (0.707 vs 0.661 and 0.601). On flask it is *worse* than co-change on MRR (0.625 vs
0.653) while better at recall@10 (0.519 vs 0.489) — it pushes more of the right files into
the top ten and fewer into the top one. There is no single winner, and an average over five
repositories would hide that.

---

## 2. How much of the coupling the imports explain

A pair is "explained" when one imports the other, or they are within two hops of each other
on the import graph **with package roots removed** as intermediates.

| repo | live coupled pairs | explained | share | pairs with a deleted file |
|---|---:|---:|---:|---:|
| requests | 178 | 136 | **76%** | 405 |
| click | 312 | 186 | 60% | 104 |
| flask | 468 | 280 | 60% | 150 |
| packaging | 203 | 115 | 57% | 63 |
| httpx | 610 | 202 | **33%** | 517 |

The last column is not a finding about the project, it is a fact about the history: httpx and
requests both restructured, so more than half of what ever changed together involves a file
that no longer exists. Those pairs are excluded from the share and reported separately, since
"nothing in the code connects them" is trivially true of a file that is gone.

---

## 3. The unexplained coupling, and what it actually is

| repo | nothing connects them | only via a package `__init__.py` | a test and its subject | imported, never co-changed |
|---|---:|---:|---:|---:|
| click | **0** | 57 | 28 | 18 |
| requests | 4 | 16 | 6 | 13 |
| flask | **0** | 100 | 37 | 45 |
| httpx | **0** | 147 | 119 | 11 |
| packaging | 13 | 26 | 6 | 22 |

**The premise was mostly wrong.** This was built to find hidden coupling — files that change
together with nothing in the source linking them. Three of the five libraries have exactly
zero, and requests has four, all of them `setup.py` against a metadata module:

```
  8 commits together   confidence 0.15   lift 2.4
      setup.py
      src/requests/__version__.py
```

packaging has thirteen, mostly documentation against the modules it documents:

```
  8 commits together   confidence 0.42   lift 7.2
      docs/conf.py
      src/packaging/__init__.py
```

Both are real and both are the same shape: **a version or a description duplicated outside
the package**, where nothing fails if only one copy is updated. That is a genuine finding and
a much narrower one than "hidden coupling in your architecture".

**What is actually large is the middle column.** On httpx, 147 coupled pairs are connected
only through a package `__init__.py` — neither file imports the other; both are re-exported
by the same root. The code records that they ship together and nothing more. That is not a
defect, but it is why the import graph explains only a third of httpx's coupling, and why it
loses to a churn baseline there.

**Test/subject pairs are listed apart** because "a test changes with what it tests" is not a
discovery. They appear at all because the test imports the *package*, not the module, so
nothing in the code records which module a test covers. On httpx that is 119 pairs — a
quarter of its coupling.

---

## 4. What these numbers do not say

- **Five repositories, all Python libraries, all well maintained.** No applications, no
  services, no monorepos, and nothing with a plugin registry or a template layer — which is
  exactly where unexplained coupling should be most common. The premise may hold there; this
  does not test it.
- **Co-change is correlation.** A shared cause, a causal link and one person tidying two
  files in an afternoon are indistinguishable here.
- **The thresholds move the answer.** At `min_lift=1.0` every busy file pairs with every
  other; at `min_support=1` a repository has tens of thousands of pairs at 100% confidence.
  The defaults are stated, printed and adjustable, and they are judgement calls.
- **MRR differences of 0.02 are not differences.** `both` vs `co-change` on httpx (0.554 vs
  0.553) is a tie. The gaps worth reading are click (+0.22 co-change over imports) and
  packaging (+0.21 imports over frequency).

## Bugs these runs caught

| what it reported | what was true |
|---|---|
| six top "hidden coupling" findings on click | six pairs of files that had been deleted, which is why nothing connected them |
| `requests`'s `utils.py ↔ certs.py` at 0.70 confidence | `utils.py` line 35 is `from . import certs` — my resolver sent it to `__init__.py` instead |
| flask and httpx had no findings except test/subject pairs | hop distance measures package membership, not connection, once a re-exporting `__init__.py` is in the graph |
| the benchmark took 200 seconds for 400 queries | `neighbours()` rescanned all edges per lookup, inside a BFS, inside a loop — 0.6s with one cached adjacency map |
