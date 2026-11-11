"""Offline tests: python3 -m unittest discover tests"""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import coach  # noqa: E402
import sync_cf  # noqa: E402

DAY = date(2026, 11, 12)
NOON = datetime(2026, 11, 12, 12, 0).astimezone()


def sub(sid, cid, idx, verdict="OK", name=None, rating=800, ptype="PRACTICE", t=1_700_000_000):
    return {"id": sid, "contestId": cid, "creationTimeSeconds": t + sid, "verdict": verdict,
            "passedTestCount": 1, "author": {"participantType": ptype},
            "problem": {"contestId": cid, "index": idx, "name": name or f"P{cid}{idx}", "rating": rating,
                        "tags": ["math"]}}


class FakeClient:
    def __init__(self, subs=(), rating=(), problems=(), contests=()):
        self.subs, self.rating, self.problems, self.contests = list(subs), list(rating), list(problems), list(contests)
        self.calls = 0
        self.log = []

    def call(self, method, **params):
        self.calls += 1
        self.log.append((method, params))
        if method == "user.status":
            ordered = sorted(self.subs, key=lambda s: -s["id"])
            start = params["from"] - 1
            return ordered[start:start + params["count"]]
        if method == "user.rating":
            return self.rating
        if method == "problemset.problems":
            return {"problems": self.problems, "problemStatistics": []}
        if method == "contest.list":
            return self.contests
        raise AssertionError(method)


def prob(cid, idx, rating, name=None, tags=("math",)):
    return {"contestId": cid, "index": idx, "name": name or f"P{cid}{idx}", "rating": rating, "tags": list(tags)}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "coach").mkdir()
        for f in ("playbook.md", "template.cpp"):
            shutil.copy(REPO / "coach" / f, self.tmp / "coach" / f)
        self._saved = (coach.ROOT, coach.today, coach.now)
        coach.ROOT = self.tmp
        coach.today = lambda: DAY
        self.clock = NOON
        coach.now = lambda: self.clock
        self.run_cli("init", "--handle", "tester")

    def tearDown(self):
        coach.ROOT, coach.today, coach.now = self._saved
        shutil.rmtree(self.tmp)

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            coach.main(list(argv))
        return out.getvalue()

    def seed_data(self, problems, subs=(), contests=None):
        client = FakeClient(subs=subs, problems=problems,
                            contests=contests if contests is not None else
                            [{"id": c, "name": f"R{c}", "phase": "FINISHED"} for c in {p["contestId"] for p in problems}])
        sync_cf.sync(self.tmp, "tester", client=client, force=True)
        return client


class SyncTests(Base):
    def test_incremental_dedup_and_verdict_update(self):
        subs = [sub(1, 1500, "A"), sub(2, 1500, "B", verdict="WRONG_ANSWER"), sub(3, 1500, "C", verdict="TESTING")]
        client = FakeClient(subs=subs)
        self.assertEqual(sync_cf.sync_submissions(self.tmp, client, "tester"), (3, 0))
        subs[2]["verdict"] = "OK"
        subs.append(sub(4, 1501, "A"))
        client = FakeClient(subs=subs)
        self.assertEqual(sync_cf.sync_submissions(self.tmp, client, "tester"), (1, 1))
        store = json.loads((self.tmp / "coach/data/submissions.json").read_text())
        self.assertEqual(len(store), 4)
        self.assertEqual(store["3"]["verdict"], "OK")
        # nothing new: one page, no changes
        client = FakeClient(subs=subs)
        self.assertEqual(sync_cf.sync_submissions(self.tmp, client, "tester"), (0, 0))
        self.assertEqual(client.calls, 1)

    def test_paging_stops_at_known_data(self):
        subs = [sub(i, 1500 + i, "A") for i in range(1, 251)]
        sync_cf.sync_submissions(self.tmp, FakeClient(subs=subs), "tester")
        subs += [sub(i, 1500 + i, "A") for i in range(251, 261)]
        client = FakeClient(subs=subs)
        self.assertEqual(sync_cf.sync_submissions(self.tmp, client, "tester"), (10, 0))
        self.assertEqual(client.calls, 1)

    def test_gym_skipped_and_missing_rating_kept_blank(self):
        subs = [sub(1, 100500, "A"), sub(2, 1500, "A", rating=None)]
        sync_cf.sync_submissions(self.tmp, FakeClient(subs=subs), "tester")
        store = json.loads((self.tmp / "coach/data/submissions.json").read_text())
        self.assertEqual(list(store), ["2"])
        self.assertIsNone(store["2"]["rating"])
        self.assertIsNone(coach.problem_info("1500A")["rating"])
        self.assertIsNone(coach.problem_info("9999Z")["name"])

    def test_failed_step_keeps_previous_data(self):
        sync_cf.sync_submissions(self.tmp, FakeClient(subs=[sub(1, 1500, "A")]), "tester")

        class Broken(FakeClient):
            def call(self, method, **params):
                raise sync_cf.CFError(f"{method}: boom")
        s = sync_cf.sync(self.tmp, "tester", client=Broken(), force=True)
        self.assertEqual(len(s["errors"]), 4)
        self.assertEqual(len(json.loads((self.tmp / "coach/data/submissions.json").read_text())), 1)


class InitTests(Base):
    def test_init_never_overwrites(self):
        path = self.tmp / "coach" / "attempts.csv"
        path.write_text("custom content\n")
        cfg = (self.tmp / "coach" / "config.json").read_text()
        out = self.run_cli("init", "--handle", "someone_else")
        self.assertEqual(path.read_text(), "custom content\n")
        self.assertEqual((self.tmp / "coach" / "config.json").read_text(), cfg)
        self.assertIn("different handle", out)


class PickTests(Base):
    def test_exclusions(self):
        problems = [
            prob(1600, "A", 1100, name="Good One"),
            prob(1601, "B", 1100, name="Seen Problem"),
            prob(1602, "C", 1100, name="Seen Problem"),            # Div1/Div2 duplicate of a seen one
            prob(1603, "A", 1100, name="Running"),                # contest not finished
            prob(1604, "A", None, name="Unrated"),
            prob(1605, "A", 1100, name="Special", tags=["*special"]),
            prob(1606, "A", 1100, name="Interactive", tags=["interactive"]),
            prob(900, "A", 1100, name="Too Old"),
            prob(1607, "A", 1100, name="Logged"),
            prob(1608, "A", 2000, name="Too Hard"),
        ]
        contests = [{"id": c, "name": "x", "phase": "FINISHED"} for c in (1600, 1601, 1602, 1604, 1605, 1606, 900, 1607, 1608)]
        contests.append({"id": 1603, "name": "x", "phase": "CODING"})
        self.seed_data(problems, subs=[sub(1, 1601, "B", name="Seen Problem", rating=1100)], contests=contests)
        self.run_cli("log", "1607A", "--result", "clean", "--minutes", "10")
        got = coach.pick("frontier", n=10)
        self.assertEqual([p["pid"] for p in got], ["1600A"])

    def test_tags_filter_and_plan_has_no_duplicates(self):
        problems = [prob(1700 + i, "A", r, tags=["graphs"] if i % 2 else ["math"]) for i, r in
                    enumerate([800, 900] * 3 + [1000, 1100, 1200] * 4 + [1300] * 2)]
        self.seed_data(problems)
        self.assertTrue(all("graphs" in p["tags"] for p in coach.pick("frontier", n=5, tags=["graphs"])))
        items = coach.plan(240, seed=1)
        pids = [i["problem"] for i in items]
        self.assertEqual(len(pids), len(set(pids)))
        self.assertEqual(items[0]["slot"], "speed")
        self.assertIn("stretch", [i["slot"] for i in items])
        for it in items:
            lo, hi = coach.band(it["slot"])
            self.assertTrue(lo <= it["rating"] <= hi, it)


class ReviewTests(Base):
    def test_transfer_progression_mastery_and_reset(self):
        cfg = coach.config()
        rows = []
        r = coach.upsert_review(rows, "tr-1A", type="transfer", interval=3, due="2026-11-12", status="open")
        for expected in (7, 16):
            coach.apply_review_result(rows, r, True, "x", cfg)
            self.assertEqual(int(r["interval"]), expected)
        coach.apply_review_result(rows, r, True, "x", cfg)
        self.assertEqual(r["status"], "mastered")
        r2 = coach.upsert_review(rows, "tr-2A", type="transfer", interval=7, streak=1, due="2026-11-12", status="open")
        coach.apply_review_result(rows, r2, False, "x", cfg)
        self.assertEqual((r2["interval"], r2["streak"], r2["due"]), ("1", "0", "2026-11-13"))

    def test_upsolves_queued_after_contest(self):
        problems = [prob(1800, i, 800 + 200 * n) for n, i in enumerate("ABCDE")]
        t = int((NOON - timedelta(days=1)).timestamp())
        subs = [sub(1, 1800, "A", ptype="CONTESTANT", t=t), sub(2, 1800, "B", verdict="WRONG_ANSWER", ptype="CONTESTANT", t=t),
                sub(3, 1800, "C", ptype="CONTESTANT", t=t)]
        self.seed_data(problems, subs=subs)
        self.assertEqual(coach.queue_upsolves(), ["1800B", "1800D"])
        self.assertEqual(coach.queue_upsolves(), [])


class SessionFlowTests(Base):
    def setUp(self):
        super().setUp()
        problems = [prob(1900 + i, "A", r) for i, r in enumerate([800, 900, 1000, 1100, 1200, 1300] * 3)]
        self.seed_data(problems, subs=[sub(1, 1903, "A", verdict="WRONG_ANSWER", rating=1100)])

    def test_brief_start_log_end_journal(self):
        out = self.run_cli("brief", "--minutes", "180", "--no-sync")
        self.assertIn("WORKOUT", out)
        self.assertNotIn("math", out.split("WORKOUT")[1])  # tags hidden
        s = coach.session()
        first = s["items"][0]["problem"]
        self.run_cli("start", first, "--no-alarm")
        self.assertTrue(any(self.tmp.joinpath("practice").rglob(f"{first}_*.cpp")))
        self.clock = NOON + timedelta(minutes=17)
        self.run_cli("log", first, "--result", "after_editorial", "--failure", "knowledge",
                     "--technique", "prefix-sums", "--lesson", "range sums -> prefix sums")
        row = coach.attempts()[-1]
        self.assertEqual((row["minutes"], row["editorial"], row["slot"]), ("17", "1", "speed"))
        rids = {r["rid"]: r for r in coach.reviews()}
        self.assertEqual(rids[f"rc-{first}"]["due"], "2026-11-13")
        self.assertEqual(rids[f"tr-{first}"]["due"], "2026-11-15")
        md = (self.tmp / "coach/sessions/2026-11-12.md").read_text()
        self.assertIn("after_editorial", md)
        self.assertIn("range sums -> prefix sums", md)

        self.run_cli("end", "--no-sync", "--summary", "Solid day.", "--well", "Fast reads",
                     "--improve", "Overflow", "--next", "Check constraints first")
        journal = (self.tmp / "coach/journal.md").read_text()
        self.assertIn("2026-11-12 (Thu) · Practice day", journal)
        self.assertIn("Check constraints first", journal)
        self.run_cli("end", "--no-sync", "--summary", "Rewritten.", "--next", "Second tip")
        journal = (self.tmp / "coach/journal.md").read_text()
        self.assertEqual(journal.count("<!-- day:2026-11-12 -->"), 1)
        self.assertIn("Rewritten.", journal)

        coach.today = lambda: DAY + timedelta(days=1)
        self.assertIn("(from 2026-11-12) Second tip", coach.keep_in_mind())
        self.run_cli("end", "--no-sync", "--summary", "Next day.")
        journal = (self.tmp / "coach/journal.md").read_text()
        self.assertLess(journal.index("day:2026-11-13"), journal.index("day:2026-11-12"))  # newest first

    def test_park_then_log_sums_time(self):
        self.run_cli("brief", "--minutes", "120", "--no-sync")
        pid = coach.session()["items"][1]["problem"]
        self.run_cli("start", pid, "--no-alarm")
        self.clock = NOON + timedelta(minutes=50)
        self.run_cli("park", pid, "--notes", "tried greedy by max")
        coach.today = lambda: DAY + timedelta(days=1)
        self.assertEqual(coach.due_reviews()[0]["rid"], f"pk-{pid}")
        out = self.run_cli("start", pid, "--no-alarm")
        self.assertIn("tried greedy by max", out)
        self.clock = NOON + timedelta(minutes=80)
        self.run_cli("log", pid, "--result", "after_park")
        row = coach.attempts()[-1]
        self.assertEqual((row["minutes"], row["parked"], row["result"]), ("80", "1", "after_park"))
        self.assertEqual(next(r for r in coach.reviews() if r["rid"] == f"pk-{pid}")["status"], "done")

    def test_add_validates_and_drop_removes(self):
        self.run_cli("brief", "--minutes", "120", "--no-sync")
        n = len(coach.session()["items"])
        for bad in ("1903A", "9999Z"):  # submitted on CF / not in problemset
            with self.assertRaises(SystemExit):
                self.run_cli("add", bad)
        self.run_cli("add", "1903A", "--slot", "reconstruct")  # seen is expected for a re-solve
        planned = {i["problem"] for i in coach.session()["items"]}
        fresh = next(p["pid"] for p in coach.problemset() if p["pid"] not in planned and p["pid"] != "1903A")
        self.run_cli("add", fresh, "--at", "1")
        items = coach.session()["items"]
        self.assertEqual((len(items), items[0]["problem"]), (n + 2, fresh))
        with self.assertRaises(SystemExit):
            self.run_cli("add", fresh)  # already in today's plan
        self.run_cli("drop", "1")
        self.assertNotIn(fresh, [i["problem"] for i in coach.session()["items"]])

    def test_unlogged_activity_and_ack(self):
        self.assertTrue(any("1903A" in line for line in coach.unlogged()))
        self.run_cli("ack", "1903A")
        self.assertEqual(coach.unlogged(), [])

    def test_trigger_rule_goes_to_playbook(self):
        self.run_cli("log", "1902A", "--result", "unsolved", "--failure", "observation",
                     "--trigger", "when operations preserve parity, check parity first", "--minutes", "40")
        rules = coach.playbook_sections()[coach.TRIGGER_SECTION]
        self.assertTrue(rules[-1].startswith("[observation] when operations preserve parity"))
        self.assertIn("(your rule)", " ".join(coach.keep_in_mind()))


if __name__ == "__main__":
    unittest.main()
