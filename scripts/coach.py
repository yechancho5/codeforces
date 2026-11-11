#!/usr/bin/env python3
"""cf-coach: deterministic training utilities. See README.md for the workflow.

Facts from Codeforces live in coach/data/ (written by sync_cf.py). Everything
the user reports (time, editorial use, what blocked them) is entered via `log`
and never inferred from submissions.
"""
import argparse
import csv
import os
import random
import re
import shutil
import signal
import statistics
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync_cf  # noqa: E402
from sync_cf import load_json, save_json  # noqa: E402

ROOT = Path(os.environ.get("COACH_ROOT") or Path(__file__).resolve().parent.parent)

ATTEMPT_FIELDS = ["date", "problem", "name", "rating", "tags", "slot", "minutes", "limit", "result",
                  "editorial", "parked", "wrong_subs", "failure", "technique", "lesson"]
REVIEW_FIELDS = ["rid", "type", "target", "technique", "tags", "source", "due", "interval", "streak",
                 "status", "spent", "notes"]
REVIEW_LOG_FIELDS = ["date", "rid", "type", "problem", "result", "interval"]
RESULTS = ["clean", "after_park", "after_editorial", "unsolved"]
FAILURES = ["none", "knowledge", "observation", "math", "implementation", "time"]
PASSING = {"clean", "after_park"}

DEFAULT_CONFIG = {
    "handle": "",
    "level": 900,
    "bands": {"speed": [-100, 0], "frontier": [100, 300], "stretch": [400, 400]},
    # minutes: check-in, stop (and for frontier an absolute cap while ideas still flow)
    "limits": {
        "speed": {"checkin": 15, "stop": 20},
        "frontier": {"checkin": 45, "stop": 60, "cap": 90},
        "stretch": {"checkin": 60, "stop": 90},
        "transfer": {"checkin": 45, "stop": 60, "cap": 90},
        "park": {"checkin": 20, "stop": 30},
        "reconstruct": {"checkin": 20, "stop": 30},
        "upsolve": {"checkin": 30, "stop": 45},
        "remedial": {"checkin": 30, "stop": 45},
        "contest": {"checkin": 0, "stop": 0},
    },
    "stuck_window": 20,
    "plan": {"postmortem_buffer": 5, "queue_share": 0.4, "stretch_every_days": 7, "stretch_min_session": 150},
    "pick": {"min_contest_id": 1000, "interactive_min_level": 1400, "min_rating": 800},
    "review_intervals": [1, 3, 7, 16, 35],
    "upsolve_lookback_days": 14,
}

PURPOSE = {
    "speed": "warm-up / speed: read, code, first-try AC",
    "frontier": "frontier: core growth",
    "stretch": "stretch: push the ceiling, park if stuck",
    "transfer": "retention: same technique, new problem (topic hidden)",
    "reconstruct": "retention: rebuild from a blank file, no notes",
    "park": "parked: fresh 30 min with yesterday's notes, then editorial",
    "upsolve": "upsolve: finish the contest",
    "remedial": "topic drill (topic known)",
}

PLAYBOOK_FOR_FAILURE = {
    "implementation": "Implementation pitfalls",
    "observation": "Invariants & observations",
    "math": "Invariants & observations",
    "time": "Contest & timing",
    "knowledge": "Editorial protocol",
}
PLAYBOOK_TIP_SECTIONS = ["Invariants & observations", "Implementation pitfalls", "Contest & timing",
                         "Editorial protocol"]
TRIGGER_SECTION = "My trigger rules"
JOURNAL_HEADER = ("# Training journal\n\nOne entry per training day, newest first. "
                  "Written by `coach.py end` from logged data plus the coach's assessment.\n\n")

CF_PID = re.compile(r"^(\d+)([A-Za-z]\d*)$")


# ---------------------------------------------------------------- basics

def P(*parts):
    return ROOT.joinpath(*parts)


def today():
    return date.today()


def now():
    return datetime.now().astimezone()


def iso(d):
    return d.isoformat()


def config():
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_CONFIG.items()}
    for k, v in load_json(P("coach", "config.json"), {}).items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


def read_csv(path):
    try:
        with open(path, newline="") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def write_csv(path, rows, fields):
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def append_csv(path, row, fields):
    new = not Path(path).exists()
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)


def attempts():
    return read_csv(P("coach", "attempts.csv"))


def reviews():
    return read_csv(P("coach", "reviews.csv"))


def save_reviews(rows):
    write_csv(P("coach", "reviews.csv"), rows, REVIEW_FIELDS)


def submissions():
    return list(load_json(P("coach", "data", "submissions.json"), {}).values())


def problemset():
    return load_json(P("coach", "data", "cache", "problemset.json"), [])


def contests():
    return load_json(P("coach", "data", "cache", "contests.json"), [])


def session():
    return load_json(P("coach", "data", "session.json"), None)


def save_session(s):
    save_json(P("coach", "data", "session.json"), s)


# ---------------------------------------------------------------- problems

def norm_pid(pid):
    m = CF_PID.match(pid.strip())
    return f"{m.group(1)}{m.group(2).upper()}" if m else pid.strip()


def link(pid):
    m = CF_PID.match(pid)
    if m:
        return f"https://codeforces.com/problemset/problem/{m.group(1)}/{m.group(2)}"
    if pid.upper().startswith("CSES-"):
        return f"https://cses.fi/problemset/task/{pid.split('-', 1)[1]}"
    return ""


def problem_info(pid):
    """Name/rating/tags from CF data; fields stay blank when CF doesn't provide them."""
    for p in problemset():
        if p["pid"] == pid:
            return p
    for s in submissions():
        if s["pid"] == pid:
            return {"pid": pid, "name": s.get("name"), "rating": s.get("rating"), "tags": s.get("tags", [])}
    return {"pid": pid, "name": None, "rating": None, "tags": []}


def label(p):
    rating = p.get("rating") or "unrated"
    return f"{p['pid']} {p.get('name') or ''} ({rating})".replace("  ", " ")


def band(slot, cfg=None):
    cfg = cfg or config()
    lo, hi = cfg["bands"][slot]
    floor = cfg["pick"]["min_rating"]
    lo = max(floor, cfg["level"] + lo)
    return lo, max(lo, cfg["level"] + hi)


def band_str(slot, cfg=None):
    lo, hi = band(slot, cfg)
    return str(lo) if lo == hi else f"{lo}-{hi}"


def seen_sets():
    pids = {s["pid"] for s in submissions()}
    pids |= {a["problem"] for a in attempts()}
    pids |= {r["target"] for r in reviews() if r["target"]}
    s = session()
    if s:
        pids |= {i["problem"] for i in s.get("items", []) if i.get("problem")}
    names = {p["name"] for p in submissions() if p.get("name")}
    names |= {a["name"] for a in attempts() if a["name"]}
    by_pid = {p["pid"]: p for p in problemset()}
    names |= {by_pid[x]["name"] for x in pids if x in by_pid}
    return pids, names


def finished_contest_ids():
    cs = contests()
    return {c["id"] for c in cs if c["phase"] == "FINISHED"} if cs else None


def pick(slot, n=1, tags=None, rng=None, exclude=None, cfg=None, rating=None):
    cfg = cfg or config()
    rng = rng or random.Random()
    lo, hi = (rating, rating) if rating else band("frontier" if slot == "transfer" else slot, cfg)
    if slot == "transfer":
        hi = max(lo, hi - 100)  # transfer tests recognition, not raw difficulty
    seen, seen_names = seen_sets()
    seen |= exclude or set()
    finished = finished_contest_ids()
    want = set(tags or [])
    out, used_names = [], set()
    cands = []
    for p in problemset():
        t = set(p.get("tags", []))
        if (not p.get("rating") or not lo <= p["rating"] <= hi or p["pid"] in seen
                or p.get("name") in seen_names or (p.get("contestId") or 0) < cfg["pick"]["min_contest_id"]
                or "*special" in t or (finished is not None and p["contestId"] not in finished)
                or ("interactive" in t and cfg["level"] < cfg["pick"]["interactive_min_level"])
                or not want <= t):
            continue
        cands.append(p)
    cands.sort(key=lambda p: p["pid"])
    rng.shuffle(cands)
    for p in cands:
        if p["name"] in used_names:
            continue
        used_names.add(p["name"])
        out.append(p)
        if len(out) == n:
            break
    return out


# ---------------------------------------------------------------- reviews

def next_interval(cur, cfg):
    for v in cfg["review_intervals"]:
        if v > cur:
            return v
    return cur * 2


def upsert_review(rows, rid, **fields):
    for r in rows:
        if r["rid"] == rid:
            r.update({k: str(v) for k, v in fields.items()})
            return r
    r = {f: "" for f in REVIEW_FIELDS}
    r.update({"rid": rid, "streak": "0", "spent": "", "status": "open"})
    r.update({k: str(v) for k, v in fields.items()})
    rows.append(r)
    return r


def due_reviews(on=None):
    on = iso(on or today())
    return sorted((r for r in reviews() if r["status"] == "open" and r["due"] <= on),
                  key=lambda r: (["upsolve", "park", "reconstruct", "transfer"].index(r["type"])
                                 if r["type"] in ("upsolve", "park", "reconstruct", "transfer") else 9, r["due"]))


def apply_review_result(rows, r, passed, problem, cfg):
    """Spaced-repetition update for reconstruct/transfer reviews."""
    t = today()
    interval = int(r["interval"] or 1)
    if r["type"] == "transfer":
        if passed:
            streak = int(r["streak"] or 0) + 1
            if interval >= 16:
                r.update(status="mastered", streak=str(streak), target="")
            else:
                new = next_interval(interval, cfg)
                r.update(streak=str(streak), interval=str(new), due=iso(t + timedelta(days=new)), target="")
        else:
            r.update(streak="0", interval="1", due=iso(t + timedelta(days=1)), target="")
    elif r["type"] == "reconstruct":
        if passed:
            r.update(status="done")
        else:
            r.update(interval="1", due=iso(t + timedelta(days=1)))
    else:
        r.update(status="done")
    append_csv(P("coach", "data", "review_log.csv"),
               {"date": iso(t), "rid": r["rid"], "type": r["type"], "problem": problem,
                "result": "pass" if passed else "fail", "interval": interval}, REVIEW_LOG_FIELDS)


def schedule_after_failure(rows, pid, technique, tags):
    t = today()
    upsert_review(rows, f"rc-{pid}", type="reconstruct", target=pid, technique=technique, source=pid,
                  due=iso(t + timedelta(days=1)), interval=1, status="open")
    upsert_review(rows, f"tr-{pid}", type="transfer", target="", technique=technique, tags=";".join(tags),
                  source=pid, due=iso(t + timedelta(days=3)), interval=3, streak=0, status="open")


def queue_upsolves(cfg=None):
    """Queue unsolved contest problems up to one past the last in-contest solve."""
    cfg = cfg or config()
    cutoff = (now() - timedelta(days=cfg["upsolve_lookback_days"])).timestamp()
    by_contest = {}
    for s in submissions():
        if s.get("participant") == "CONTESTANT" and (s.get("time") or 0) >= cutoff:
            by_contest.setdefault(s["contestId"], []).append(s)
    if not by_contest:
        return []
    rows, added = reviews(), []
    existing = {r["rid"] for r in rows}
    all_subs = submissions()
    for cid, subs in by_contest.items():
        indexes = sorted(p["index"] for p in problemset() if p.get("contestId") == cid)
        if not indexes:
            continue
        solved_in_contest = {s["index"] for s in subs if s["verdict"] == "OK"}
        last = max((indexes.index(i) for i in solved_in_contest if i in indexes), default=-1)
        solved_ever = {s["index"] for s in all_subs if s["contestId"] == cid and s["verdict"] == "OK"}
        day = datetime.fromtimestamp(min(s["time"] for s in subs)).date()
        for idx in indexes[:last + 2]:
            pid, rid = f"{cid}{idx}", f"up-{cid}{idx}"
            if idx in solved_ever or rid in existing:
                continue
            upsert_review(rows, rid, type="upsolve", target=pid, source=f"contest {cid}",
                          due=iso(day + timedelta(days=1)), interval=0, status="open")
            added.append(pid)
    if added:
        save_reviews(rows)
    return added


# ---------------------------------------------------------------- playbook & sessions

def playbook_sections():
    sections, cur = {}, None
    try:
        lines = P("coach", "playbook.md").read_text().splitlines()
    except FileNotFoundError:
        return {}
    for line in lines:
        if line.startswith("## "):
            cur = line[3:].strip()
            sections[cur] = []
        elif cur and line.startswith("- "):
            sections[cur].append(line[2:].strip())
    return sections


def add_trigger_rule(category, rule, pid):
    path = P("coach", "playbook.md")
    text = path.read_text() if path.exists() else f"# Playbook\n\n## {TRIGGER_SECTION}\n"
    entry = f"- [{category}] {rule} _({pid}, {iso(today())})_"
    if f"## {TRIGGER_SECTION}" not in text:
        text = text.rstrip() + f"\n\n## {TRIGGER_SECTION}\n"
    head, _, tail = text.partition(f"## {TRIGGER_SECTION}\n")
    nxt = tail.find("\n## ")
    body, rest = (tail, "") if nxt < 0 else (tail[:nxt + 1], tail[nxt + 1:])
    body = body.rstrip("\n") + "\n" + entry + "\n"
    path.write_text(head + f"## {TRIGGER_SECTION}\n" + body + ("\n" + rest if rest else ""))


def journal_entries():
    """{date: entry text} from coach/journal.md."""
    try:
        text = P("coach", "journal.md").read_text()
    except FileNotFoundError:
        return {}
    return dict(re.findall(r"<!-- day:(\S+) -->\n(.*?)<!-- /day:\1 -->", text, flags=re.S))


def journal_bullets(entry, label):
    out, inside = [], False
    for line in entry.splitlines():
        if line.startswith("**"):
            inside = line.startswith(f"**{label}")
        elif inside and line.startswith("- "):
            out.append(line[2:].strip())
    return out


def write_journal_entry(day, text):
    path = P("coach", "journal.md")
    content = path.read_text() if path.exists() else JOURNAL_HEADER
    block = f"<!-- day:{day} -->\n{text.rstrip()}\n<!-- /day:{day} -->\n"
    pattern = re.compile(rf"<!-- day:{re.escape(day)} -->.*?<!-- /day:{re.escape(day)} -->\n?", re.S)
    if pattern.search(content):
        content = pattern.sub(lambda m: block, content)
    else:
        later = [m for m in re.finditer(r"<!-- day:(\S+) -->", content) if m.group(1) < day]
        i = later[0].start() if later else len(content)
        sep = "" if content[:i].endswith("\n\n") else "\n"
        content = content[:i] + sep + block + "\n" + content[i:]
    path.write_text(re.sub(r"\n{3,}", "\n\n", content))
    return path


def keep_in_mind():
    tips = []
    prev = sorted(d for d in journal_entries() if d < iso(today()))
    if prev:
        tips += [f"(from {prev[-1]}) {b}" for b in journal_bullets(journal_entries()[prev[-1]], "Next time")]
    sections = playbook_sections()
    recent = [a["failure"] for a in attempts()[-10:] if a["failure"] not in ("", "none")]
    triggers = sections.get(TRIGGER_SECTION, [])
    if recent:
        top = Counter(recent).most_common(1)[0][0]
        mine = [t for t in triggers if t.startswith(f"[{top}]")]
        tips += [f"(your rule) {t}" for t in mine[-2:]]
        pool = sections.get(PLAYBOOK_FOR_FAILURE.get(top, ""), [])
        if len(tips) < 4 and pool:
            tips.append(f"(playbook: {PLAYBOOK_FOR_FAILURE[top]}) {pool[today().toordinal() % len(pool)]}")
    else:
        pool = [(s, b) for s in PLAYBOOK_TIP_SECTIONS for b in sections.get(s, [])]
        if pool:
            s, b = pool[today().toordinal() % len(pool)]
            tips.append(f"(playbook: {s}) {b}")
    return tips


def item_result_cells(item, att):
    if att:
        return att["result"], f"{att['minutes']}m" if att["minutes"] else "?", att["failure"] or "-"
    return item.get("status", "todo"), "", ""


def render_session_md():
    s = session()
    if not s:
        return None
    path = P("coach", "sessions", f"{s['date']}.md")
    todays = [a for a in attempts() if a["date"] == s["date"]]
    by_pid = {}
    for a in todays:
        by_pid[a["problem"]] = a
    rows, listed = [], set()
    for i, it in enumerate(s["items"], 1):
        pid = it.get("problem") or ""
        listed.add(pid)
        name = f"[{pid} {it.get('name') or ''}]({link(pid)})" if pid else f"_{it.get('note', 'coach picks')}_"
        res, tm, fail = item_result_cells(it, by_pid.get(pid))
        rows.append(f"| {i} | {it['slot']} | {name.strip()} | {it.get('rating') or ''} | {it['limit']}m | {res} | {tm} | {fail} |")
    for a in todays:
        if a["problem"] not in listed:
            rows.append(f"| + | {a['slot']} | [{a['problem']} {a['name']}]({link(a['problem'])}) | {a['rating']} "
                        f"| {a['limit']}m | {a['result']} | {a['minutes']}m | {a['failure'] or '-'} |")
    block = "\n".join(["<!-- workout:start -->",
                       "| # | Slot | Problem | Rating | Limit | Result | Time | Failure |",
                       "|---|---|---|---|---|---|---|---|", *rows])
    done = [a for a in todays if a["minutes"]]
    total = sum(int(a["minutes"]) for a in done)
    block += f"\n\n_{len(todays)} logged · {sum(a['result'] == 'clean' for a in todays)} clean · {total} min solving_\n"
    lessons = [f"- **{a['problem']}** ({a['failure'] or '-'}): {a['lesson']}" for a in todays if a["lesson"]]
    if lessons:
        block += "\n**Lessons**\n" + "\n".join(lessons) + "\n"
    block += "<!-- workout:end -->"
    if path.exists():
        text = path.read_text()
        text = re.sub(r"<!-- workout:start -->.*?<!-- workout:end -->", lambda m: block, text, flags=re.S)
    else:
        d = date.fromisoformat(s["date"])
        tips = "\n".join(f"- {t}" for t in s.get("keep_in_mind", [])) or "- (nothing carried forward yet)"
        text = (f"# Training: {s['date']} ({d.strftime('%a')}) · {s['minutes']} min planned · level {s['level']}\n\n"
                f"## Keep in mind today\n{tips}\n\n"
                "## Coach's read\n_(what the data shows → today's adjustments; written by the coach)_\n\n"
                f"## Workout\n{block}\n\n"
                "## Notes\n_(coach notes during the session; the day summary goes in coach/journal.md)_\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# ---------------------------------------------------------------- planning

def make_item(slot, p, limit, **extra):
    item = {"slot": slot, "problem": p["pid"] if p else "", "name": p.get("name") if p else "",
            "rating": p.get("rating") if p else "", "limit": limit, "status": "todo"}
    item.update(extra)
    return item


def plan(minutes, cfg=None, seed=None):
    cfg = cfg or config()
    rng = random.Random(seed if seed is not None else iso(today()))
    buf = cfg["plan"]["postmortem_buffer"]
    lim = cfg["limits"]
    items, used, remaining = [], set(), minutes

    def take(slot, **kw):
        got = pick(slot, 1, rng=rng, exclude=used, cfg=cfg, **kw)
        if got:
            used.add(got[0]["pid"])
        return got[0] if got else None

    # warm-up
    if remaining >= lim["speed"]["stop"] + buf:
        p = take("speed")
        items.append(make_item("speed", p, lim["speed"]["stop"], **({} if p else {"note": "no problem data"})))
        remaining -= lim["speed"]["stop"] + buf

    # due queue, capped
    cap, spent = minutes * cfg["plan"]["queue_share"], 0
    revs = reviews()
    for r in due_reviews():
        cost = lim[r["type"]]["stop"] + buf
        if spent + cost > cap or cost > remaining:
            continue
        if r["type"] == "transfer":
            p = problem_info(r["target"]) if r["target"] else take(
                "transfer", tags=[t for t in r["tags"].split(";") if t])
            if p and not r["target"]:
                upsert_review(revs, r["rid"], target=p["pid"])
            items.append(make_item("transfer", p, lim["transfer"]["stop"], rid=r["rid"],
                                   **({} if p else {"note": f"transfer: {r['technique']} (coach picks)"})))
        else:
            p = problem_info(r["target"])
            items.append(make_item(r["type"], p, lim[r["type"]]["stop"], rid=r["rid"]))
        used.add(r["target"] or (items[-1]["problem"]))
        spent += cost
        remaining -= cost
    save_reviews(revs)

    # stretch (reserved before frontier fill, placed last)
    stretch = None
    recent = iso(today() - timedelta(days=cfg["plan"]["stretch_every_days"]))
    had_stretch = any(a["slot"] == "stretch" and a["date"] > recent for a in attempts())
    if minutes >= cfg["plan"]["stretch_min_session"] and not had_stretch and remaining >= lim["stretch"]["stop"] + buf:
        stretch = take("stretch")
        if stretch:
            remaining -= lim["stretch"]["stop"] + buf

    while remaining >= lim["frontier"]["checkin"] + buf:
        p = take("frontier")
        if not p:
            break
        limit = min(lim["frontier"]["stop"], remaining - buf)
        items.append(make_item("frontier", p, limit))
        remaining -= limit + buf
    if stretch:
        items.append(make_item("stretch", stretch, lim["stretch"]["stop"]))
    return items


def format_item(i, it):
    pid = it.get("problem")
    what = f"{label(it | {'pid': pid})}  {link(pid)}" if pid else f"({it.get('note', 'coach picks')})"
    status = "" if it.get("status", "todo") == "todo" else f"  [{it['status']}]"
    return f"{i}. {it['slot']:<11} [{it['limit']}m] {what}{status}\n   purpose: {PURPOSE.get(it['slot'], '')}"


# ---------------------------------------------------------------- timer / alarms

def schedule_alarms(pid, checkpoints):
    if sys.platform != "darwin" or not shutil.which("osascript"):
        return []
    pids = []
    for mins, msg in checkpoints:
        if mins <= 0:
            continue
        script = f'display notification "{msg}" with title "CF Coach: {pid}" sound name "Glass"'
        proc = subprocess.Popen(["sh", "-c", f"sleep {mins * 60}; osascript -e '{script}'"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        pids.append(proc.pid)
    return pids


def cancel_alarms(active):
    for pid in active.get("alarm_pids", []):
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def elapsed_minutes(active):
    return int((now() - datetime.fromisoformat(active["started"])).total_seconds() // 60)


def slot_rule(slot, cfg):
    lim = cfg["limits"].get(slot, cfg["limits"]["frontier"])
    w = cfg["stuck_window"]
    if slot == "speed":
        return f"Hard cap {lim['stop']} min, then read the editorial."
    if slot in ("frontier", "transfer"):
        return (f"Check-in at {lim['checkin']} min. {w} min with no new idea = stuck -> park it. "
                f"Past {lim['stop']} only while ideas are flowing; absolute cap {lim['cap']}.")
    if slot == "stretch":
        return f"{lim['checkin']}-{lim['stop']} min, park once overnight, then editorial."
    if slot == "park":
        return f"{lim['stop']} fresh minutes with your notes, then editorial (read only until it clicks)."
    if slot == "reconstruct":
        return f"Blank file, no notes, {lim['stop']} min. Reading your old code = fail."
    if slot == "upsolve":
        return f"{lim['checkin']}-{lim['stop']} min, then editorial."
    return f"{lim['stop']} min."


def policy_now(active, cfg):
    slot, e = active["slot"], elapsed_minutes(active)
    lim = cfg["limits"].get(slot, cfg["limits"]["frontier"])
    at = lambda m: (datetime.fromisoformat(active["started"]) + timedelta(minutes=m)).strftime("%H:%M")
    if e < lim["checkin"]:
        return f"Keep going. Check-in at {at(lim['checkin'])}."
    if e < lim["stop"]:
        return (f"Check-in window: any NEW idea in the last {cfg['stuck_window']} min? If not, stop now "
                f"({'park it' if slot in ('frontier', 'stretch', 'transfer') else 'editorial'}). Stop at {at(lim['stop'])}.")
    if "cap" in lim and e < lim["cap"]:
        return f"Past the {lim['stop']}-min mark. Continue ONLY if ideas are actively flowing; absolute cap {at(lim['cap'])}. Otherwise park."
    if slot in ("frontier", "stretch", "transfer"):
        return "Time. Stop and park it (coach.py park ID --notes ...)."
    return "Time. Stop and read the editorial (only until the idea clicks), then write the code yourself."


# ---------------------------------------------------------------- commands

def cmd_init(a):
    created = []
    for d in [P("coach", "sessions"), P("coach", "data", "cache")]:
        if not d.exists():
            d.mkdir(parents=True)
            created.append(str(d.relative_to(ROOT)))
    cfg_path = P("coach", "config.json")
    if not cfg_path.exists():
        handle = a.handle or input("Codeforces handle: ").strip()
        save_json(cfg_path, dict(DEFAULT_CONFIG, handle=handle))
        created.append("coach/config.json")
    elif a.handle and load_json(cfg_path, {}).get("handle") != a.handle:
        print(f"config.json exists with a different handle; edit it by hand if you meant to change it.")
    for name, fields in [("attempts.csv", ATTEMPT_FIELDS), ("reviews.csv", REVIEW_FIELDS)]:
        path = P("coach", name)
        if not path.exists():
            write_csv(path, [], fields)
            created.append(f"coach/{name}")
    journal = P("coach", "journal.md")
    if not journal.exists():
        journal.write_text(JOURNAL_HEADER)
        created.append("coach/journal.md")
    print("Created: " + ", ".join(created) if created else "Nothing to do: everything already exists.")


def run_sync(cfg, quiet=False):
    if not cfg.get("handle"):
        print("No handle configured (coach.py init --handle H). Skipping sync.")
        return None
    s = sync_cf.sync(ROOT, cfg["handle"])
    if not quiet:
        print(sync_cf.format_summary(s))
    return s


def unlogged():
    logged = {a["problem"] for a in attempts()}
    acked = set(load_json(P("coach", "data", "ack.json"), []))
    groups = {}
    for s in submissions():
        if s["pid"] in logged or s["pid"] in acked:
            continue
        groups.setdefault(s["pid"], []).append(s)
    out = []
    for pid, subs in sorted(groups.items(), key=lambda kv: max(x["time"] for x in kv[1])):
        ac = any(x["verdict"] == "OK" for x in subs)
        wrong = sum(x["verdict"] not in ("OK", "COMPILATION_ERROR", "SKIPPED", None, "TESTING") for x in subs)
        kinds = sorted({x["participant"] or "?" for x in subs})
        last = datetime.fromtimestamp(max(x["time"] for x in subs)).strftime("%Y-%m-%d")
        out.append(f"{label(subs[0])} · {len(subs)} subs · {'AC' if ac else 'no AC'} · {wrong} wrong · "
                   f"{'/'.join(kinds).lower()} · last {last}")
    return out


def upcoming_contests(days=7):
    t = now().timestamp()
    return sorted((c for c in contests() if c["phase"] == "BEFORE" and c.get("start")
                   and c["start"] - t < days * 86400), key=lambda c: c["start"])


def contest_line(c, cfg):
    st = datetime.fromtimestamp(c["start"])
    good = ("Div. 3", "Div. 4", "Educational") if cfg["level"] < 1400 else ("Div. 2", "Div. 3", "Educational")
    rec = "  <- recommended" if any(g in c["name"] for g in good) else ""
    return f"{st.strftime('%a %m-%d %H:%M')} · {c['name']} · {c['duration'] // 3600}h{c['duration'] % 3600 // 60:02d}{rec}"


def rating_line():
    rows = load_json(P("coach", "data", "rating.json"), [])
    if not rows:
        return "CF rating: unrated so far (no rated contests yet)"
    r = rows[-1]
    d = datetime.fromtimestamp(r["time"]).strftime("%Y-%m-%d")
    return f"CF rating: {r['newRating']} (last: {r['contestName']} {d}, rank {r['rank']}, delta {r['newRating'] - r['oldRating']:+d})"


def cmd_brief(a):
    cfg = config()
    t = today()
    bands = " · ".join(f"{x} {band_str(x, cfg)}" for x in ("speed", "frontier", "stretch"))
    print(f"=== CF COACH BRIEF · {t.strftime('%a')} {iso(t)} · {a.minutes} min · level {cfg['level']} ({bands}) ===")
    if not a.no_sync:
        run_sync(cfg)
    print(rating_line())
    up = queue_upsolves(cfg)
    if up:
        print("Queued upsolves: " + ", ".join(up))

    s = session()
    if s and s["date"] == iso(t) and not s.get("ended") and not a.replan:
        print("\nRESUME: today's session is already in progress.")
        if s.get("active"):
            act = s["active"]
            print(f"ACTIVE: {act['problem']} ({act['slot']}) · {elapsed_minutes(act)} min elapsed · {policy_now(act, cfg)}")
        print("\nKEEP IN MIND")
        for tip in s.get("keep_in_mind", []):
            print(f"- {tip}")
        print("\nWORKOUT")
        for i, it in enumerate(s["items"], 1):
            print(format_item(i, it))
        print(f"\nSession log: coach/sessions/{s['date']}.md")
        return

    tips = keep_in_mind()
    print("\nKEEP IN MIND")
    for tip in tips or ["(no carried-forward tips yet)"]:
        print(f"- {tip}")
    ul = unlogged()
    if ul:
        print("\nUNLOGGED CF ACTIVITY (ask the user; never infer time/hints/editorial)")
        for line in ul:
            print(f"- {line}")
    due = due_reviews()
    if due:
        print("\nDUE")
        for r in due:
            print(f"- {r['rid']}: {r['type']} {r['target'] or r['technique'] or ''} (due {r['due']})")
    cs = upcoming_contests()
    print("\nCONTESTS (next 7 days)")
    for c in cs:
        print(f"- {contest_line(c, cfg)}")
    if not cs:
        print("- none found in cache")
    if any(datetime.fromtimestamp(c["start"]).date() == t for c in cs):
        print("!! A contest is TODAY. If the user is entering it, the contest is today's workout.")

    items = plan(a.minutes, cfg)
    if s and s["date"] == iso(t):
        kept = [i for i in s["items"] if i.get("status", "todo") != "todo"]
        items = kept + items
    started = s["started"] if s and s["date"] == iso(t) and s.get("started") else now().isoformat(timespec="seconds")
    s = {"date": iso(t), "minutes": a.minutes, "level": cfg["level"], "items": items, "started": started,
         "keep_in_mind": tips, "active": None, "ended": False}
    save_session(s)
    print("\nWORKOUT (tags hidden)")
    for i, it in enumerate(items, 1):
        print(format_item(i, it))
    planned = sum(int(i["limit"]) + cfg["plan"]["postmortem_buffer"] for i in items if i.get("status", "todo") == "todo")
    print(f"\nPlanned: ~{planned} of {a.minutes} min (incl. {cfg['plan']['postmortem_buffer']}m postmortem each)")
    print(f"Session log: {render_session_md().relative_to(ROOT)}")


def cmd_plan(a):
    for i, it in enumerate(plan(a.minutes, seed=a.seed), 1):
        print(format_item(i, it))


def cmd_pick(a):
    tags = [t.strip() for t in a.tags.split(",")] if a.tags else None
    got = pick(a.slot, a.n, tags=tags, rating=a.rating, rng=random.Random(a.seed))
    if not got:
        print("No unseen problems match (is the problemset cached? run sync_cf.py).")
    for p in got:
        extra = f"  tags: {', '.join(p['tags'])}" if a.show_tags else ""
        print(f"{label(p)}  {link(p['pid'])}{extra}")


def new_session(cfg, minutes=0):
    return {"date": iso(today()), "minutes": minutes, "level": cfg["level"], "items": [],
            "started": now().isoformat(timespec="seconds"), "keep_in_mind": keep_in_mind(),
            "active": None, "ended": False}


def find_item(s, pid):
    for it in (s or {}).get("items", []):
        if it.get("problem") == pid:
            return it
    return None


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_") or "problem"


def cmd_start(a):
    cfg, pid = config(), norm_pid(a.problem)
    s = session()
    if not s or s["date"] != iso(today()):
        s = new_session(cfg)
    if s.get("active") and s["active"]["problem"] != pid and not a.force:
        sys.exit(f"{s['active']['problem']} is still active. Log or park it first (or --force).")
    if s.get("active"):
        cancel_alarms(s["active"])
    item = find_item(s, pid)
    slot = a.slot or (item["slot"] if item else "frontier")
    info = problem_info(pid)
    if not item:
        item = make_item(slot, info, cfg["limits"].get(slot, cfg["limits"]["frontier"])["stop"])
        s["items"].append(item)
    item["status"] = "in progress"
    lim = cfg["limits"].get(slot, cfg["limits"]["frontier"])

    folder = P("practice", str(info.get("rating") or "unrated"))
    suffix = "_reconstruct" if slot == "reconstruct" else ""
    path = folder / f"{pid}_{slugify(info.get('name'))}{suffix}.cpp"
    if not path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        tpl = P("coach", "template.cpp")
        body = tpl.read_text() if tpl.exists() else ""
        path.write_text(f"// {pid} {info.get('name') or ''} - {link(pid)}\n" + body)

    started = now()
    checkpoints = [(lim["checkin"], f"Check-in ({lim['checkin']} min): new ideas in the last {cfg['stuck_window']} min?"),
                   (lim["stop"], f"{lim['stop']} min: stop rule ({slot})")]
    if "cap" in lim:
        checkpoints.append((lim["cap"], f"{lim['cap']} min: absolute cap. Park it."))
    alarm_pids = [] if a.no_alarm else schedule_alarms(pid, checkpoints)
    s["active"] = {"problem": pid, "slot": slot, "started": started.isoformat(timespec="seconds"),
                   "alarm_pids": alarm_pids}
    save_session(s)
    render_session_md()

    print(f"STARTED {label(info)} · slot {slot} · {started.strftime('%H:%M')}")
    print(f"Link: {link(pid)}")
    print(f"File: {path.relative_to(ROOT)}   (run: scripts/run.sh {path.relative_to(ROOT)})")
    print("Checkpoints: " + " · ".join(f"{(started + timedelta(minutes=m)).strftime('%H:%M')} ({m}m)"
                                       for m, _ in checkpoints if m > 0))
    print(f"Rule: {slot_rule(slot, cfg)}")
    print("Alarms: macOS notifications scheduled." if alarm_pids else "Alarms: none. Set a timer.")
    park = next((r for r in reviews() if r["rid"] == f"pk-{pid}" and r["status"] == "open"), None)
    if park:
        print(f"Your parked notes: {park['notes']}  (already spent {park['spent'] or '?'} min)")


def cmd_status(a):
    cfg, s = config(), session()
    if not s:
        print("No session. Start one with: coach.py brief --minutes N")
        return
    act = s.get("active")
    if act:
        print(f"ACTIVE {act['problem']} ({act['slot']}) · {elapsed_minutes(act)} min elapsed")
        print(f"Policy now: {policy_now(act, cfg)}")
    else:
        nxt = next((i for i in s["items"] if i.get("status", "todo") == "todo"), None)
        print("No active problem." + (f" Next up: {nxt['problem'] or nxt.get('note')} ({nxt['slot']}, {nxt['limit']}m)" if nxt else " Workout complete."))
    print(f"Session {s['date']}{' (ended)' if s.get('ended') else ''}:")
    for i, it in enumerate(s["items"], 1):
        print(f"  {i}. {it['slot']:<11} {it.get('problem') or '-':<8} {it.get('status', 'todo')}")


def cmd_park(a):
    s, pid = session(), norm_pid(a.problem)
    act = (s or {}).get("active")
    if a.minutes is not None:
        spent = a.minutes
    else:
        spent = elapsed_minutes(act) if act and act["problem"] == pid else 0
    rows = reviews()
    prev = next((r for r in rows if r["rid"] == f"pk-{pid}"), None)
    if prev and prev["spent"]:
        spent += int(prev["spent"])
    upsert_review(rows, f"pk-{pid}", type="park", target=pid, source=pid, due=iso(today() + timedelta(days=1)),
                  interval=1, status="open", spent=spent, notes=a.notes)
    save_reviews(rows)
    if act and act["problem"] == pid:
        cancel_alarms(act)
        s["active"] = None
    item = find_item(s, pid)
    if item:
        item["status"] = "parked"
    if s:
        save_session(s)
        render_session_md()
    print(f"PARKED {pid} · {spent} min so far · due tomorrow ({iso(today() + timedelta(days=1))}) with your notes.")


def wrong_subs(pid):
    return sum(1 for s in submissions() if s["pid"] == pid
               and s["verdict"] not in ("OK", "COMPILATION_ERROR", "SKIPPED", None, "TESTING"))


def cmd_log(a):
    cfg, pid = config(), norm_pid(a.problem)
    s = session()
    act = (s or {}).get("active")
    rows = reviews()
    park = next((r for r in rows if r["rid"] == f"pk-{pid}" and r["status"] == "open"), None)
    item = find_item(s, pid)
    slot = a.slot or (act["slot"] if act and act["problem"] == pid else (item["slot"] if item else "frontier"))

    minutes = a.minutes
    if minutes is None and act and act["problem"] == pid:
        minutes = elapsed_minutes(act) + (int(park["spent"]) if park and park["spent"] else 0)
    info = problem_info(pid)
    name = a.name or info.get("name") or ""
    tags = info.get("tags") or []
    failure = a.failure or ("none" if a.result == "clean" else "")
    row = {
        "date": iso(today()), "problem": pid, "name": name, "rating": info.get("rating") or "",
        "tags": ";".join(tags), "slot": slot, "minutes": "" if minutes is None else minutes,
        "limit": item["limit"] if item else cfg["limits"].get(slot, cfg["limits"]["frontier"])["stop"],
        "result": a.result, "editorial": int(a.result == "after_editorial"), "parked": int(bool(park)),
        "wrong_subs": wrong_subs(pid), "failure": failure, "technique": a.technique or "", "lesson": a.lesson or "",
    }
    append_csv(P("coach", "attempts.csv"), row, ATTEMPT_FIELDS)

    passed = a.result in PASSING
    scheduled = []
    linked = None
    if item and item.get("rid"):
        linked = next((r for r in rows if r["rid"] == item["rid"]), None)
    if not linked:
        linked = next((r for r in rows if r["status"] == "open" and r["target"] == pid
                       and r["type"] in ("reconstruct", "transfer")), None)
    if park:
        park["status"] = "done"
    up = next((r for r in rows if r["rid"] == f"up-{pid}" and r["status"] == "open"), None)
    if up:
        up["status"] = "done"
    if linked and linked["type"] in ("reconstruct", "transfer"):
        apply_review_result(rows, linked, passed, pid, cfg)
        scheduled.append(f"{linked['rid']} -> {linked['status']}" + (f", next due {linked['due']}" if linked["status"] == "open" else ""))
        if linked["type"] == "transfer" and not passed:
            schedule_after_failure(rows, pid, a.technique or linked["technique"], [])
            rows[:] = [r for r in rows if r["rid"] != f"tr-{pid}"]  # the source's transfer already covers it
            scheduled.append(f"rc-{pid} tomorrow")
    elif not passed:
        schedule_after_failure(rows, pid, a.technique or "", tags)
        scheduled += [f"rc-{pid} reconstruct tomorrow", f"tr-{pid} transfer in 3 days"]
    save_reviews(rows)

    if a.trigger:
        add_trigger_rule(failure or "general", a.trigger, pid)
    if act and act["problem"] == pid:
        cancel_alarms(act)
        s["active"] = None
    if item:
        item["status"] = a.result
    if s:
        save_session(s)
        render_session_md()
    print(f"LOGGED {pid} · {a.result} · {row['minutes'] or '?'} min · failure {failure or '-'} · wrong subs (CF) {row['wrong_subs']}")
    for x in scheduled:
        print(f"  scheduled: {x}")
    if a.trigger:
        print("  playbook: trigger rule added")


def cmd_ack(a):
    path = P("coach", "data", "ack.json")
    acked = set(load_json(path, []))
    acked |= {norm_pid(x) for x in a.problems}
    save_json(path, sorted(acked))
    print(f"Acknowledged {len(a.problems)} problem(s); they won't show as unlogged.")


RESOLVE_SLOTS = {"reconstruct", "park", "upsolve"}  # slots where a seen problem is expected


def problem_issues(pid, slot):
    """Reasons a problem shouldn't go into today's plan (empty list = fine)."""
    issues = []
    m = CF_PID.match(pid)
    if m:
        known = {p["pid"]: p for p in problemset()}
        if pid not in known and not any(x["pid"] == pid for x in submissions()):
            issues.append(f"{pid} is not in the cached Codeforces problemset (wrong ID?)")
        finished = finished_contest_ids()
        if finished is not None and int(m.group(1)) not in finished and int(m.group(1)) < 100000:
            issues.append(f"contest {m.group(1)} is not finished (live or upcoming)")
    if slot not in RESOLVE_SLOTS:
        pids, names = seen_sets()
        name = problem_info(pid).get("name")
        if any(x["pid"] == pid for x in submissions()):
            issues.append(f"{pid} already has your submissions on Codeforces")
        elif any(x["problem"] == pid for x in attempts()):
            issues.append(f"{pid} is already logged in attempts.csv")
        elif pid in pids:
            issues.append(f"{pid} is already in today's plan or the review queue")
        elif name and name in names:
            issues.append(f"'{name}' matches a problem you've already seen (Div1/Div2 copy)")
    return issues


def cmd_add(a):
    cfg, pid = config(), norm_pid(a.problem)
    s = session()
    if not s or s["date"] != iso(today()):
        sys.exit("No session today. Run brief first.")
    issues = problem_issues(pid, a.slot)
    if issues and not a.force:
        sys.exit("Not added: " + "; ".join(issues) + ". Use --force only if this is intentional.")
    info = problem_info(pid)
    if a.name:
        info = dict(info, name=a.name)
    item = make_item(a.slot, info, a.limit or cfg["limits"].get(a.slot, cfg["limits"]["frontier"])["stop"])
    pos = len(s["items"]) if a.at is None else max(0, min(len(s["items"]), a.at - 1))
    s["items"].insert(pos, item)
    save_session(s)
    render_session_md()
    print(format_item(pos + 1, item))


def cmd_drop(a):
    s = session()
    if not s or not 1 <= a.n <= len(s["items"]):
        sys.exit("No such workout item.")
    it = s["items"][a.n - 1]
    if it.get("status", "todo") != "todo":
        sys.exit("Only untouched items can be dropped.")
    if it.get("rid"):
        rows = reviews()
        upsert_review(rows, it["rid"], target="")  # review stays due; it just loses this problem
        save_reviews(rows)
    s["items"].pop(a.n - 1)
    save_session(s)
    render_session_md()
    print(f"Dropped item {a.n}: {it.get('problem') or it.get('note')} ({it['slot']}).")


def cmd_swap(a):
    s = session()
    if not s or not 1 <= a.n <= len(s["items"]):
        sys.exit("No such workout item.")
    it = s["items"][a.n - 1]
    if it.get("status", "todo") != "todo":
        sys.exit("Only untouched items can be swapped.")
    old = it.get("problem")
    tags = None
    if it.get("rid"):
        r = next((r for r in reviews() if r["rid"] == it["rid"]), None)
        tags = [t for t in r["tags"].split(";") if t] if r else None
    got = pick(it["slot"] if it["slot"] in ("speed", "frontier", "stretch", "transfer") else "frontier", 1,
               tags=tags, exclude={old} if old else set())
    if not got:
        sys.exit("No replacement found.")
    p = got[0]
    it.update(problem=p["pid"], name=p["name"], rating=p["rating"])
    if it.get("rid"):
        rows = reviews()
        upsert_review(rows, it["rid"], target=p["pid"])
        save_reviews(rows)
    save_session(s)
    render_session_md()
    print(format_item(a.n, it))


def cmd_queue(a):
    cfg = config()
    if a.action == "done":
        rows = reviews()
        r = next((r for r in rows if r["rid"] == a.rid), None)
        if not r:
            sys.exit(f"No review {a.rid}")
        apply_review_result(rows, r, a.result == "pass", r["target"], cfg)
        save_reviews(rows)
        print(f"{r['rid']}: {r['status']}" + (f", next due {r['due']}" if r["status"] == "open" else ""))
        return
    t = today()
    soon = iso(t + timedelta(days=7))
    rows = [r for r in reviews() if r["status"] == "open" and r["due"] <= soon]
    if not rows:
        print("Queue empty.")
    for r in sorted(rows, key=lambda r: r["due"]):
        flag = "DUE " if r["due"] <= iso(t) else "    "
        what = r["target"] or f"technique: {r['technique'] or r['tags'] or '?'}"
        print(f"{flag}{r['due']}  {r['rid']:<16} {r['type']:<11} {what}  (interval {r['interval']}, streak {r['streak']})")
    mastered = [r for r in reviews() if r["status"] == "mastered"]
    if mastered:
        print(f"Mastered techniques: {', '.join(r['technique'] or r['source'] for r in mastered)}")


def hm(minutes):
    return f"{minutes // 60}h{minutes % 60:02d}"


def day_type(todays, contest_minutes):
    slots = {r["slot"] for r in todays}
    if contest_minutes or "contest" in slots:
        return "Contest day" + (" + practice" if slots - {"contest", "upsolve"} else "")
    if "remedial" in slots:
        return "Topic block"
    if slots and slots <= {"reconstruct", "transfer", "park", "upsolve"}:
        return "Review / upsolve day"
    return "Practice day"


def journal_text(s, todays, a, ended_at):
    d = date.fromisoformat(s["date"])
    solving = sum(int(r["minutes"]) for r in todays if r["minutes"] and r["slot"] != "contest")
    contest = a.contest_minutes or sum(int(r["minutes"]) for r in todays if r["minutes"] and r["slot"] == "contest")
    started = datetime.fromisoformat(s["started"]) if s.get("started") else None
    span = (f"{started.strftime('%H:%M')}-{ended_at.strftime('%H:%M')} "
            f"({hm(int((ended_at - started).total_seconds() // 60))} session)") if started else "session time not recorded"
    count = Counter(r["result"] for r in todays)
    parked = [it for it in s["items"] if it.get("status") == "parked"]
    pk_spent = {r["target"]: r["spent"] for r in reviews() if r["type"] == "park"}
    solving += sum(int(pk_spent.get(it["problem"]) or 0) for it in parked)
    lines = [f"## {s['date']} ({d.strftime('%a')}) · {a.type or day_type(todays, contest)}",
             f"**Time:** {span} · practice {hm(solving)} · contest {hm(contest)}",
             f"**Level:** {s['level']} · **Problems:** {len(todays) + len(parked)} attempted · "
             f"{count['clean'] + count['after_park']} solved independently · {count['after_editorial']} with editorial · "
             f"{count['unsolved']} unsolved · {len(parked)} parked", ""]
    for r in todays:
        lines.append(f"- [{r['problem']} {r['name']}]({link(r['problem'])}) ({r['rating'] or 'unrated'}, {r['slot']}): "
                     f"**{r['result']}** in {r['minutes'] or '?'}m" + (f": {r['lesson']}" if r["lesson"] else ""))
    for it in parked:
        lines.append(f"- [{it['problem']} {it.get('name') or ''}]({link(it['problem'])}) ({it.get('rating') or 'unrated'}, "
                     f"{it['slot']}): **parked** after {pk_spent.get(it['problem']) or '?'}m, continues tomorrow")
    if not todays and not parked:
        lines.append("- (no problems logged)")
    lines += ["", f"**Summary:** {a.summary or '_(not written)_'}", ""]
    for label_, items in (("Went well", a.well), ("To improve", a.improve), ("Next time", a.next)):
        lines.append(f"**{label_}:**")
        lines += [f"- {x}" for x in items] or ["- _(none recorded)_"]
        lines.append("")
    return "\n".join(lines)


def cmd_end(a):
    cfg, s = config(), session()
    if not s or s["date"] != iso(today()):
        s = new_session(cfg)  # e.g. a contest-only day with no brief
    if s.get("active"):
        print(f"Note: {s['active']['problem']} is still active. Log or park it.")
    if not a.no_sync:
        run_sync(cfg)
    rows = attempts()
    for r in rows:
        if r["date"] == s["date"] and r["problem"]:
            r["wrong_subs"] = wrong_subs(r["problem"])
    write_csv(P("coach", "attempts.csv"), rows, ATTEMPT_FIELDS)
    for it in s["items"]:
        if it.get("status", "todo") == "todo":
            it["status"] = "skipped"
    s["ended"] = True
    save_session(s)
    path = render_session_md()
    todays = [r for r in rows if r["date"] == s["date"]]
    jpath = write_journal_entry(s["date"], journal_text(s, todays, a, now()))
    print(f"SESSION {s['date']} ENDED · {len(todays)} logged · {sum(r['result'] == 'clean' for r in todays)} clean · "
          f"{sum(int(r['minutes']) for r in todays if r['minutes'])} min solving")
    for r in todays:
        print(f"- {r['problem']} {r['name']} ({r['rating'] or 'unrated'}) {r['slot']}: {r['result']}, "
              f"{r['minutes'] or '?'}m, failure {r['failure'] or '-'}. {r['lesson']}")
    print(f"Journal: {jpath.relative_to(ROOT)} · Session log: {path.relative_to(ROOT)}")
    if not (a.summary and a.well and a.improve and a.next):
        print("Missing summary/well/improve/next: rerun `end` with them (it replaces today's journal entry).")
    print("Then update coach/state.md and propose a commit.")


def cmd_contests(a):
    cfg = config()
    if not a.no_sync:
        try:
            sync_cf.sync_contests(ROOT, sync_cf.Client())
        except sync_cf.CFError as e:
            print(f"(contest refresh failed: {e}; using cache)")
    cs = upcoming_contests(a.days)
    for c in cs:
        print(contest_line(c, cfg))
    if not cs:
        print("No upcoming contests in cache.")


def cmd_guard(a):
    pid = norm_pid(a.problem)
    m = CF_PID.match(pid)
    if not m:
        print("Not a Codeforces problem id; guard does not apply.")
        return
    cid = int(m.group(1))
    try:
        sync_cf.sync_contests(ROOT, sync_cf.Client(), force=True)
    except sync_cf.CFError as e:
        print(f"(could not refresh contest list: {e})")
    c = next((c for c in contests() if c["id"] == cid), None)
    if c is None:
        print(f"UNKNOWN: contest {cid} not found. Treat it as live: no problem-specific help.")
        sys.exit(3)
    if c["phase"] != "FINISHED":
        print(f"LIVE: {c['name']} is {c['phase']}. No help on this problem until it is FINISHED.")
        sys.exit(2)
    print(f"OK: {c['name']} is finished.")


def median(xs):
    return statistics.median(xs) if xs else None


def cmd_report(a):
    since = iso(today() - timedelta(days=a.days - 1))
    rows = [r for r in attempts() if r["date"] >= since]
    print(f"=== REPORT {since} .. {iso(today())} ({a.days} days) ===")
    if not rows:
        print("No attempts logged in this window.")
    else:
        res = Counter(r["result"] for r in rows)
        print(f"Attempts: {len(rows)} · clean {res['clean']} · after_park {res['after_park']} · "
              f"after_editorial {res['after_editorial']} · unsolved {res['unsolved']}")
        print(f"Sessions: {len({r['date'] for r in rows})} days · "
              f"{sum(int(r['minutes']) for r in rows if r['minutes'])} min logged")
        for slot in ("speed", "frontier", "stretch", "transfer", "reconstruct", "upsolve", "contest", "remedial"):
            sr = [r for r in rows if r["slot"] == slot]
            if not sr:
                continue
            clean = [int(r["minutes"]) for r in sr if r["result"] == "clean" and r["minutes"]]
            med = median(clean)
            print(f"  {slot:<11} {len(sr):>3} tried · {sum(r['result'] == 'clean' for r in sr)} clean"
                  + (f" · median clean time {med:g}m" if med is not None else ""))
        ratings = Counter(r["rating"] or "unrated" for r in rows)
        print("By rating: " + ", ".join(f"{k}: {sum(r['result'] == 'clean' for r in rows if (r['rating'] or 'unrated') == k)}/{v} clean"
                                         for k, v in sorted(ratings.items())))
        fails = Counter(r["failure"] for r in rows if r["failure"] not in ("", "none"))
        if fails:
            print("Failure types: " + ", ".join(f"{k} {v}" for k, v in fails.most_common()))
        lessons = [f"{r['problem']}: {r['lesson']}" for r in rows if r["lesson"]]
        if lessons:
            print("Lessons:")
            for l in lessons:
                print(f"  - {l}")
    rl = [r for r in read_csv(P("coach", "data", "review_log.csv")) if r["date"] >= since]
    if rl:
        print("Reviews: " + ", ".join(f"{t} {sum(r['result'] == 'pass' for r in rl if r['type'] == t)}/{sum(r['type'] == t for r in rl)} pass"
                                      for t in sorted({r['type'] for r in rl})))
    cutoff = datetime.fromisoformat(since).timestamp()
    rated = [r for r in load_json(P("coach", "data", "rating.json"), []) if r["time"] >= cutoff]
    for r in rated:
        print(f"Contest: {r['contestName']} · rank {r['rank']} · {r['oldRating']} -> {r['newRating']} ({r['newRating'] - r['oldRating']:+d})")
    if not rated:
        print("Contests: none rated in this window.")
    print("(Small samples: treat rates as noisy until there are 20+ attempts per band.)")


def cmd_set(a):
    path = P("coach", "config.json")
    cfg = load_json(path, {})
    old = cfg.get("level")
    cfg["level"] = a.value
    save_json(path, cfg)
    with open(P("coach", "state.md"), "a") as f:
        f.write(f"\n- {iso(today())}: level {old} -> {a.value}. Reason: {a.reason}\n")
    print(f"level {old} -> {a.value}; bands: " + ", ".join(f"{s} {band_str(s)}" for s in ("speed", "frontier", "stretch")))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="coach.py", description="cf-coach training utilities")
    sub = ap.add_subparsers(dest="cmd", required=True)

    x = sub.add_parser("init", help="create missing coach files (never overwrites)")
    x.add_argument("--handle")
    x.set_defaults(fn=cmd_init)

    x = sub.add_parser("brief", help="sync + today's briefing and workout")
    x.add_argument("--minutes", type=int, default=120)
    x.add_argument("--replan", action="store_true", help="re-plan today's untouched items")
    x.add_argument("--no-sync", action="store_true")
    x.set_defaults(fn=cmd_brief)

    x = sub.add_parser("plan", help="print a workout without saving it")
    x.add_argument("--minutes", type=int, default=120)
    x.add_argument("--seed")
    x.set_defaults(fn=cmd_plan)

    x = sub.add_parser("pick", help="unseen problems for a slot")
    x.add_argument("--slot", choices=["speed", "frontier", "stretch", "transfer"], default="frontier")
    x.add_argument("--n", type=int, default=3)
    x.add_argument("--tags", help="comma-separated CF tags that must all be present")
    x.add_argument("--rating", type=int)
    x.add_argument("--show-tags", action="store_true")
    x.add_argument("--seed")
    x.set_defaults(fn=cmd_pick)

    x = sub.add_parser("start", help="start the timer on a problem")
    x.add_argument("problem")
    x.add_argument("--slot", choices=list(DEFAULT_CONFIG["limits"]))
    x.add_argument("--no-alarm", action="store_true")
    x.add_argument("--force", action="store_true")
    x.set_defaults(fn=cmd_start)

    x = sub.add_parser("status", help="active problem, elapsed time, what the stop policy says")
    x.set_defaults(fn=cmd_status)

    x = sub.add_parser("park", help="park a problem overnight with notes")
    x.add_argument("problem")
    x.add_argument("--notes", required=True)
    x.add_argument("--minutes", type=int, help="minutes spent, if no timer was running")
    x.set_defaults(fn=cmd_park)

    x = sub.add_parser("log", help="record an attempt (postmortem)")
    x.add_argument("problem")
    x.add_argument("--result", required=True, choices=RESULTS)
    x.add_argument("--minutes", type=int, help="defaults to timer (+ parked time); blank if unknown")
    x.add_argument("--failure", choices=FAILURES)
    x.add_argument("--technique", help="short slug, e.g. prefix-sums")
    x.add_argument("--lesson")
    x.add_argument("--trigger", help="'when you see X, try Y' rule for the playbook")
    x.add_argument("--slot", choices=list(DEFAULT_CONFIG["limits"]))
    x.add_argument("--name", help="problem name for non-Codeforces problems")
    x.set_defaults(fn=cmd_log)

    x = sub.add_parser("ack", help="mark CF problems as known so they stop showing as unlogged")
    x.add_argument("problems", nargs="+")
    x.set_defaults(fn=cmd_ack)

    x = sub.add_parser("add", help="add a specific problem to today's workout")
    x.add_argument("problem")
    x.add_argument("--slot", default="frontier", choices=list(DEFAULT_CONFIG["limits"]))
    x.add_argument("--limit", type=int)
    x.add_argument("--name")
    x.add_argument("--at", type=int, help="position in the workout (1 = first)")
    x.add_argument("--force", action="store_true", help="add even if already seen / not found")
    x.set_defaults(fn=cmd_add)

    x = sub.add_parser("drop", help="remove untouched workout item N")
    x.add_argument("n", type=int)
    x.set_defaults(fn=cmd_drop)

    x = sub.add_parser("swap", help="replace workout item N with another unseen problem")
    x.add_argument("n", type=int)
    x.set_defaults(fn=cmd_swap)

    x = sub.add_parser("queue", help="review queue")
    x.add_argument("action", nargs="?", choices=["done"])
    x.add_argument("rid", nargs="?")
    x.add_argument("result", nargs="?", choices=["pass", "fail"])
    x.set_defaults(fn=cmd_queue)

    x = sub.add_parser("end", help="finalize today's session and write the journal entry")
    x.add_argument("--summary", help="2-3 sentence summary of the day")
    x.add_argument("--well", action="append", default=[], help="what went well (repeatable)")
    x.add_argument("--improve", action="append", default=[], help="what to improve (repeatable)")
    x.add_argument("--next", action="append", default=[], help="carry-forward tip for next session (repeatable)")
    x.add_argument("--type", help="override day type, e.g. 'Contest day'")
    x.add_argument("--contest-minutes", type=int, default=0)
    x.add_argument("--no-sync", action="store_true")
    x.set_defaults(fn=cmd_end)

    x = sub.add_parser("contests", help="upcoming contests")
    x.add_argument("--days", type=int, default=7)
    x.add_argument("--no-sync", action="store_true")
    x.set_defaults(fn=cmd_contests)

    x = sub.add_parser("guard", help="exit 2 if the problem's contest is not finished")
    x.add_argument("problem")
    x.set_defaults(fn=cmd_guard)

    x = sub.add_parser("report", help="summary of recent training")
    x.add_argument("--days", type=int, default=7)
    x.set_defaults(fn=cmd_report)

    x = sub.add_parser("set", help="change training level")
    x.add_argument("what", choices=["level"])
    x.add_argument("value", type=int)
    x.add_argument("--reason", required=True)
    x.set_defaults(fn=cmd_set)

    args = ap.parse_args(argv)
    if args.cmd == "queue" and args.action == "done" and not (args.rid and args.result):
        ap.error("usage: queue done RID pass|fail")
    args.fn(args)


if __name__ == "__main__":
    main()
