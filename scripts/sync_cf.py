#!/usr/bin/env python3
"""Incremental sync of Codeforces data into coach/data/.

Stores only facts Codeforces provides (submissions, verdicts, timestamps,
participation type, rating changes, problem ratings/tags, contest phases).
It never writes attempt records: solve time, hints and editorial use are
manual input (see coach.py log).

Usage: python3 scripts/sync_cf.py [--force]
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cfapi import CFError, Client  # noqa: E402

PROBLEMSET_TTL = 24 * 3600
CONTESTS_TTL = 3600
GYM_MIN_CONTEST_ID = 100000
PENDING = {None, "", "TESTING"}


def data_dir(root):
    return Path(root) / "coach" / "data"


def cache_dir(root):
    return data_dir(root) / "cache"


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def slim_submission(s):
    p = s.get("problem", {})
    return {
        "id": s["id"],
        "pid": f"{p.get('contestId', s.get('contestId'))}{p.get('index', '')}",
        "contestId": p.get("contestId", s.get("contestId")),
        "index": p.get("index"),
        "name": p.get("name"),
        "rating": p.get("rating"),  # may be missing for new problems: kept as None
        "tags": p.get("tags", []),
        "verdict": s.get("verdict"),
        "time": s.get("creationTimeSeconds"),
        "participant": s.get("author", {}).get("participantType"),
        "passed": s.get("passedTestCount"),
    }


def sync_submissions(root, client, handle):
    """Fetch newest-first pages until a page overlaps already-stored data.

    Upserts by submission id, so verdicts still TESTING last time get updated.
    Returns (added, updated)."""
    path = data_dir(root) / "submissions.json"
    store = load_json(path, {})
    page = 100 if store else 1000
    start, added, updated = 1, 0, 0
    pending_ids = {k for k, v in store.items() if v.get("verdict") in PENDING}
    while True:
        batch = client.call("user.status", handle=handle, **{"from": start, "count": page})
        overlap = False
        for s in batch:
            cid = s.get("contestId") or s.get("problem", {}).get("contestId")
            if cid is None or cid >= GYM_MIN_CONTEST_ID:
                continue
            rec = slim_submission(s)
            key = str(rec["id"])
            old = store.get(key)
            if old is None:
                added += 1
            else:
                if old.get("verdict") not in PENDING:
                    overlap = True
                if old != rec:
                    updated += 1
            if rec["verdict"] not in PENDING:
                pending_ids.discard(key)
            store[key] = rec
        if (overlap and not pending_ids) or len(batch) < page:
            break
        start += page
    save_json(path, store)
    return added, updated


def sync_rating(root, client, handle):
    changes = client.call("user.rating", handle=handle)
    rows = [{
        "contestId": c["contestId"], "contestName": c["contestName"], "rank": c["rank"],
        "oldRating": c["oldRating"], "newRating": c["newRating"], "time": c["ratingUpdateTimeSeconds"],
    } for c in changes]
    save_json(data_dir(root) / "rating.json", rows)
    return len(rows)


def _fresh(path, ttl):
    try:
        return time.time() - path.stat().st_mtime < ttl
    except FileNotFoundError:
        return False


def sync_problemset(root, client, force=False):
    path = cache_dir(root) / "problemset.json"
    if not force and _fresh(path, PROBLEMSET_TTL):
        return None
    res = client.call("problemset.problems")
    solved = {f"{s['contestId']}{s['index']}": s.get("solvedCount", 0) for s in res.get("problemStatistics", [])}
    problems = []
    for p in res.get("problems", []):
        pid = f"{p.get('contestId')}{p.get('index')}"
        problems.append({
            "pid": pid, "contestId": p.get("contestId"), "index": p.get("index"), "name": p.get("name"),
            "rating": p.get("rating"), "tags": p.get("tags", []), "solvedCount": solved.get(pid, 0),
        })
    save_json(path, problems)
    return len(problems)


def sync_contests(root, client, force=False):
    path = cache_dir(root) / "contests.json"
    if not force and _fresh(path, CONTESTS_TTL):
        return None
    res = client.call("contest.list", gym="false")
    contests = [{
        "id": c["id"], "name": c["name"], "phase": c["phase"],
        "start": c.get("startTimeSeconds"), "duration": c.get("durationSeconds"),
    } for c in res]
    save_json(path, contests)
    return len(contests)


def sync(root, handle, client=None, force=False):
    """Run every sync step; a failing step keeps its previous data.

    Returns a summary dict with an 'errors' list."""
    client = client or Client()
    summary = {"errors": []}
    steps = [
        ("submissions", lambda: sync_submissions(root, client, handle)),
        ("rating", lambda: sync_rating(root, client, handle)),
        ("problemset", lambda: sync_problemset(root, client, force)),
        ("contests", lambda: sync_contests(root, client, force)),
    ]
    for name, step in steps:
        try:
            summary[name] = step()
        except CFError as e:
            summary["errors"].append(f"{name}: {e}")
    summary["calls"] = client.calls
    state_path = data_dir(root) / "sync_state.json"
    state = load_json(state_path, {})
    state["last_attempt"] = int(time.time())
    if not summary["errors"]:
        state["last_success"] = state["last_attempt"]
    save_json(state_path, state)
    return summary


def format_summary(s):
    parts = []
    if "submissions" in s:
        parts.append(f"submissions +{s['submissions'][0]} new, {s['submissions'][1]} updated")
    if "rating" in s:
        parts.append(f"{s['rating']} rated contests")
    for cache in ("problemset", "contests"):
        if cache in s:
            parts.append(f"{cache} {'refreshed' if s[cache] else 'cached'}")
    line = "Sync: " + ", ".join(p for p in parts if p) + f" ({s['calls']} API calls)"
    for e in s["errors"]:
        line += f"\nSYNC ERROR {e} -- using previously stored data"
    return line


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="refresh problemset/contest caches now")
    args = ap.parse_args()
    root = Path(os.environ.get("COACH_ROOT") or Path(__file__).resolve().parent.parent)
    handle = load_json(root / "coach" / "config.json", {}).get("handle")
    if not handle:
        sys.exit("No Codeforces handle in coach/config.json -- run: python3 scripts/coach.py init --handle <handle>")
    s = sync(root, handle, force=args.force)
    print(format_summary(s))
    sys.exit(1 if s["errors"] else 0)


if __name__ == "__main__":
    main()
