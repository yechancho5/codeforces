# Training state

_Last updated: 2026-11-11 (system setup)._

## Current level
- **Level 900.** Bands: speed 800-900 · frontier 1000-1200 · stretch 1300 (computed from `config.json`).
- Promotion rule of thumb: most frontier problems solved clean within 60 min across ~8+ attempts → `coach.py set level +100`.
  Most unsolved → drop 100. Every change gets a written reason.

## Active priorities
1. **Volume at the frontier** (1000-1200, tags hidden). This is the main engine.
2. **First rated Div 3/4 round this week**, then upsolve the next day.
3. **Prefix-sum awareness.** 1807D was never accepted (3 WA + 1 TLE). The loop was O(n·q). Reconstruct it once prefix sums are taught.
4. **Heaps quick block**: `priority_queue`, min-heap syntax, 2-3 drills. Short, because it's STL.
5. Graphs (BFS/DFS): not yet. They start mattering around 1200; scheduled for Phase 2 of `curriculum.md`.

## Skills

### Observed (with evidence)
- CF history (synced 2026-11-11): 5 accepted 800s (2276A, 2269A, 1829B, 1791C, 1901A), no rated contests.
- 1807D Odd Queries (900): 3 WA + 1 TLE, never accepted. Code sums each query range in a loop, which is O(n·q).
- 1792C Min Max Sort (1500): 1 WA, not accepted.
- Solve times, editorial use and independence for these: unknown (not inferred from timestamps).

### Inferred (confidence)
- Reaches for direct simulation on range queries instead of prefix sums (medium: 1807D code + TLE verdict).
- The 3 WAs on 1807D before the TLE suggest a correctness issue too, maybe parity/overflow (low: not yet discussed).

### Unknown
- Cold solve rate at 1000-1200, speed at 800, contest performance, retention.

## Next steps
- **2026-11-12 (Thu) 09:35: Codeforces Round 1134 (Div. 4), contest 2290, 135 min.** First rated contest. No coach help
  during it. Afterwards: log each problem attempted (`--slot contest`), `end --contest-minutes <actual>`.
  Upsolves get queued automatically for 11-13.
- First regular session: intake questions, backfill or acknowledge the 7 unlogged CF problems, first workout.

## Level history
