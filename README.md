# Codeforces training

My Codeforces solutions, plus a terminal-first coaching system aimed at a genuine **1900** rating.
The coach is an AI agent (Claude Code) running in this repo. It follows `AGENTS.md` and keeps all
state on disk, so every session picks up where the last one ended.

## Setup
Requirements: `python3` (3.9+, standard library only, nothing to `pip install`) and `g++`/clang.
```sh
python3 scripts/coach.py init --handle <codeforces-handle>   # creates missing files only; never overwrites
python3 scripts/sync_cf.py                                     # first sync with Codeforces
python3 -m unittest discover tests                             # offline tests
```

## Daily use
Open a terminal in the repo, start `claude`, and say **"let's train, I have 3 hours"**. The coach:
1. syncs Codeforces and reads the training state
2. gives a warm-up, then frontier/stretch problems with links and time limits (tags hidden)
3. reminds you of tips carried over from last session
4. keeps time while you solve (macOS notifications at the checkpoints), calls stops, and parks problems overnight
5. runs a short postmortem after each problem and logs it
6. at the end, writes your journal entry and proposes a commit

Things to say: `let's train` · `starting 1850B` · `status` · `stuck` · `park` · `done` · `review` · `analyze` · `done for today`.

**No hints.** The coach doesn't give hints unless you explicitly ask. Its job mid-problem is to tell you when to stop:

| Slot | Rule |
|---|---|
| warm-up (speed) | 20-min hard cap, then editorial |
| frontier | 45-60 min, up to 90 while ideas are flowing; 20 min with no new idea → park overnight, 30 fresh min tomorrow, then editorial |
| stretch | 60-90 min, park once, then editorial |

## What to read
| File | What it is |
|---|---|
| `coach/journal.md` | **Your journal.** One entry per day: time spent, problems, what went well, what to improve, next time |
| `coach/sessions/YYYY-MM-DD.md` | Detailed log of one day: workout table, results, lessons |
| `coach/playbook.md` | Tricks (constraints, invariants, pitfalls, STL syntax) + your own trigger rules |
| `coach/curriculum.md` | Topic ladder 900→1900 and when each topic gets taught |
| `coach/state.md` | The coach's current assessment of you and the active priorities |
| `coach/profile.md` | Goal, baseline, preferences |

## Commands (the coach runs these; you can too)
```
python3 scripts/coach.py brief --minutes 180     # sync + today's briefing and workout (resumes if in progress)
python3 scripts/coach.py start 1850B             # timer + creates practice/<rating>/<ID>_<name>.cpp from coach/template.cpp
python3 scripts/coach.py status                  # elapsed time + what the stop rule says now
python3 scripts/coach.py park 1850B --notes ".." # park overnight with your notes
python3 scripts/coach.py log 1850B --result clean|after_park|after_editorial|unsolved \
        [--failure knowledge|observation|math|implementation|time] [--lesson ".."] [--trigger "when X, try Y"]
python3 scripts/coach.py end --summary ".." --well ".." --improve ".." --next ".."   # journal entry
python3 scripts/coach.py queue                   # spaced-repetition reviews (reconstruct / transfer)
python3 scripts/coach.py report --days 7         # weekly numbers
python3 scripts/coach.py pick --slot frontier --n 3 [--tags "dp"]   # unseen problems
python3 scripts/coach.py contests                # upcoming rounds
python3 scripts/coach.py guard 1850B             # refuses (exit 2) if the contest is still live
python3 scripts/coach.py swap N | add ID | ack ID | set level R --reason ".."
scripts/run.sh practice/900/1807D_odd_queries.cpp   # compile with sanitizers, run against input.txt
```

## Data
- **From Codeforces** (via the official API, ≤1 request per 2 s, retries with backoff): submissions,
  verdicts, timestamps, contest participation, rating history, problem ratings and tags, contest phases.
  Stored in `coach/data/`. Large regenerable caches live in `coach/data/cache/` (gitignored).
  Sync is incremental: it stops at the first page of already-known submissions.
- **From you** (via `log`): time spent, whether you used the editorial, what blocked you, the lesson.
  These are never inferred from submission data. Unknown values stay blank.
- `coach/attempts.csv`: one row per attempt.
- `coach/reviews.csv`: review queue (park → tomorrow; after an editorial: reconstruct in 1 day and
  transfer in 3 days; on a pass, intervals grow 1→3→7→16→35 days).

## Layout
```
practice/<rating>/   my solutions (ID_name.cpp)
contests/            live-contest solutions
coach/               training state (see above)
scripts/             coach.py, sync_cf.py, cfapi.py, run.sh
tests/               offline unit tests
AGENTS.md            coach instructions (CLAUDE.md imports it)
```
