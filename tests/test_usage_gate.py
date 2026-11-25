"""Offline tests for the usage gate. No network, no real Claude probes.

Run: python3 -m unittest discover -s tests
"""
import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

P2M = Path(__file__).resolve().parent.parent / "scripts" / "p2m.py"


def stream(five=0.10, week=0.30, reset_min=90.0, overage=False, omit=()):
    """A `claude --output-format stream-json` line with a rate_limit_event."""
    reset = int(time.time() + reset_min * 60)
    windows = {"five_hour": {"utilization": five, "resetsAt": int(time.time() + 3600)},
               "seven_day": {"utilization": week, "resetsAt": reset}}
    for k in omit:
        windows.pop(k)
    info = {"status": "allowed", "resetsAt": reset, "rateLimitType": "seven_day", "utilization": week,
            "isUsingOverage": overage, "unifiedWindows": windows}
    return '{"type":"system"}\n' + json.dumps({"type": "rate_limit_event", "rate_limit_info": info}) + "\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.state = self.tmp / "state"
        self.config = self.tmp / "autoprover.config.json"
        self.config.write_text(json.dumps({"minutes_per_claim": 40}))
        self.env = {**os.environ, "AUTOPROVER_STATE": str(self.state), "AUTOPROVER_CONFIG": str(self.config),
                    "AUTOPROVER_DATA": str(self.tmp), "PROVE2ME_CREDENTIALS_FILE": str(self.tmp / "none.json"),
                    "PROVE2ME_WORKSPACE": str(self.tmp / "ws")}
        for k in ("AUTOPROVER_IGNORE_WINDOW", "AUTOPROVER_USAGE_FIXTURE", "AUTOPROVER_DRY_RUN"):
            self.env.pop(k, None)

    def fixture(self, name="f.jsonl", **kw):
        f = self.tmp / name
        f.write_text(stream(**kw))
        return f

    def p2m(self, *args, env=None):
        p = subprocess.run([sys.executable, str(P2M), *args], env={**self.env, **(env or {})},
                           capture_output=True, text=True, timeout=60)
        return p.returncode, p.stdout, p.stderr

    def usage(self, mode="continue", env=None, **kw):
        rc, out, err = self.p2m("usage", "--for", mode, "--from-file", str(self.fixture(**kw)), env=env)
        return rc, json.loads(out)


class DecisionTests(Base):
    def test_five_hour_margin(self):
        rc, out = self.usage("start-claim", five=0.45)
        self.assertEqual((rc, out["decision"]["kind"]), (6, "limit"))
        rc, out = self.usage("continue", five=0.45)
        self.assertEqual((rc, out["decision"]["kind"]), (0, "ok"))
        for mode in ("start-claim", "continue"):
            self.assertEqual(self.usage(mode, five=0.51)[0], 6)
        self.assertEqual(self.usage("start-claim", five=0.40)[0], 0)  # exactly at cap - margin
        self.assertEqual(self.usage("continue", five=0.50)[0], 6)     # at the cap

    def test_weekly_margin(self):
        self.assertEqual(self.usage("start-claim", week=0.78)[0], 6)
        self.assertEqual(self.usage("continue", week=0.78)[0], 0)
        self.assertEqual(self.usage("start-claim", week=0.75)[0], 0)
        for mode in ("start-claim", "continue"):
            self.assertEqual(self.usage(mode, week=0.81)[0], 6)

    def test_budget_and_window(self):
        rc, out = self.usage(reset_min=90)
        self.assertEqual((rc, out["claim_budget_minutes"]), (0, 40))
        rc, out = self.usage(reset_min=20)
        self.assertEqual((rc, out["claim_budget_minutes"]), (0, 15))
        self.assertAlmostEqual(out["minutes_to_reset"], 20, delta=1)
        for reset_min in (3, 30 * 60):
            rc, out = self.usage(reset_min=reset_min)
            self.assertEqual((rc, out["decision"]["kind"], out["claim_budget_minutes"]), (6, "window", 0))

    def test_ignore_window(self):
        rc, out = self.usage(reset_min=30 * 60, env={"AUTOPROVER_IGNORE_WINDOW": "1"})
        self.assertEqual((rc, out["claim_budget_minutes"]), (0, 40))
        rc, out = self.usage(reset_min=30 * 60, five=0.6, env={"AUTOPROVER_IGNORE_WINDOW": "1"})
        self.assertEqual((rc, out["decision"]["kind"]), (6, "limit"))  # caps still apply

    def test_test_run_config(self):
        self.config.write_text(json.dumps({"minutes_per_claim": 40, "test_run": True,
                                           "dry_run": False, "max_claims_per_run": 3}))
        rc, out = self.usage(reset_min=30 * 60)
        self.assertEqual((rc, out["claim_budget_minutes"]), (0, 40))  # window ignored
        rc, out = self.usage(reset_min=30 * 60, week=0.85)
        self.assertEqual((rc, out["decision"]["kind"]), (6, "limit"))  # caps still apply
        code = ("import importlib.util,json,sys;s=importlib.util.spec_from_file_location('p',sys.argv[1]);"
                "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);c=m.load_config();"
                "print(json.dumps([c['dry_run'],c['max_claims_per_run']]))")
        p = subprocess.run([sys.executable, "-c", code, str(P2M)], capture_output=True, text=True,
                           env={**self.env, "AUTOPROVER_DRY_RUN": "false", "AUTOPROVER_MAX_CLAIMS_PER_RUN": "5"})
        self.assertEqual(json.loads(p.stdout), [True, 1])  # no env var can make a test run live

    def test_safety_allow_web(self):
        rc, out, _ = self.p2m("safety")
        out = json.loads(out)
        self.assertEqual((rc, out["allow_web"], out["allow_connectors"]), (0, False, False))
        self.assertIn("mcp__github__", out["builtin_mcp_prefixes"])
        self.assertIn("mcp__ccd_session__", out["builtin_mcp_prefixes"])
        for val, want in ((True, True), ("true", False), (1, False)):  # only a real JSON true
            self.config.write_text(json.dumps({"allow_web": val}))
            self.assertEqual(json.loads(self.p2m("safety")[1])["allow_web"], want)

    def test_overage_and_unknown(self):
        self.assertEqual(self.usage(overage=True)[1]["decision"]["kind"], "overage")
        rc, out = self.usage(omit=("five_hour",))
        self.assertEqual((rc, out["decision"]["kind"]), (7, "unknown"))
        bad = self.tmp / "bad.jsonl"
        bad.write_text('{"type":"result"}\n')
        rc, out, _ = self.p2m("usage", "--from-file", str(bad))
        self.assertEqual((rc, json.loads(out)["decision"]["kind"]), (7, "unknown"))

    def test_no_five_hour_window(self):
        """An account that reports no 5-hour window: a no-go by default, a go with
        require_five_hour_window false, and the weekly cap still applies then."""
        self.config.write_text(json.dumps({"minutes_per_claim": 40, "require_five_hour_window": False}))
        rc, out = self.usage(omit=("five_hour",))
        self.assertEqual((rc, out["decision"]["kind"]), (0, "ok"))
        rc, out = self.usage(omit=("five_hour",), week=0.85)
        self.assertEqual((rc, out["decision"]["kind"]), (6, "limit"))
        rc, out = self.usage(omit=("seven_day",))
        self.assertEqual((rc, out["decision"]["kind"]), (7, "unknown"))

    def test_legacy_stop_at_utilization(self):
        self.config.write_text(json.dumps({"stop_at_utilization": 0.97}))
        self.assertEqual(self.usage(five=0.55)[0], 6)  # never raised above the 0.50 default
        self.config.write_text(json.dumps({"stop_at_utilization": 0.30}))
        self.assertEqual(self.usage(five=0.35)[0], 6)  # can lower the caps
        self.config.write_text(json.dumps({"stop_at_utilization": 0.97, "max_five_hour_utilization": 0.6}))
        self.assertEqual(self.usage(five=0.55)[0], 0)  # explicit new key wins


class EnforcementTests(Base):
    def check(self, cmd="check", env=None):
        args = [cmd, "tid", str(self.tmp / "Sol.lean")]
        return self.p2m(*args, env=env)

    def test_check_and_submit_refuse(self):
        nogo = self.fixture("nogo.jsonl", five=0.6)
        for cmd in ("check", "submit"):
            rc, out, err = self.check(cmd, env={"AUTOPROVER_USAGE_FIXTURE": str(nogo)})
            self.assertEqual(rc, 6, err)
            self.assertIn("usage gate", err)
        rc, out, err = self.check("submit", env={"AUTOPROVER_USAGE_FIXTURE": str(nogo),
                                                 "AUTOPROVER_DRY_RUN": "true"})
        self.assertEqual(rc, 6)

    def test_check_uses_recent_cache_submit_does_not(self):
        go = self.fixture("go.jsonl")
        nogo = self.fixture("nogo.jsonl", week=0.85)
        # A fresh no-go probe is cached; check reuses it even if the next probe would say go.
        self.assertEqual(self.check(env={"AUTOPROVER_USAGE_FIXTURE": str(nogo)})[0], 6)
        self.assertEqual(self.check(env={"AUTOPROVER_USAGE_FIXTURE": str(go)})[0], 6)
        # An old cache is ignored: the go probe lets check through to the gates (which then
        # fail on the missing credentials, before any network access).
        cache = self.state / "usage_last.json"
        c = json.loads(cache.read_text())
        c["probed_at"] -= 400
        cache.write_text(json.dumps(c))
        rc, _, err = self.check(env={"AUTOPROVER_USAGE_FIXTURE": str(go)})
        self.assertNotEqual(rc, 6)
        self.assertIn("credentials", err)
        # The go probe is now cached; submit still probes fresh and refuses.
        self.assertEqual(self.check("submit", env={"AUTOPROVER_USAGE_FIXTURE": str(nogo)})[0], 6)


class ScheduleTests(Base):
    def load(self):
        spec = importlib.util.spec_from_file_location("p2m_t", P2M)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_schedule_cron(self):
        m = self.load()
        s = m.recommended_schedule("2026-10-13T08:00:00Z", {"lead_hours": 2})
        self.assertEqual(s["cron_utc"], "7 6 * * 2")  # a Tuesday
        reset = dt.datetime(2026, 10, 11, 1, 0, tzinfo=dt.timezone.utc)  # Sunday 01:00
        s = m.recommended_schedule(reset.strftime("%Y-%m-%dT%H:%M:%SZ"), {"lead_hours": 2})
        self.assertEqual(s["cron_utc"], "7 23 * * 6")  # Saturday 23:07
        rc, out, err = self.p2m("schedule", "--from-file", str(self.fixture(reset_min=600)))
        self.assertEqual(rc, 0, err)
        self.assertRegex(json.loads(out)["cron_utc"], r"^\d+ \d+ \* \* [0-6]$")

    def test_misaligned_notify(self):
        m = self.load()
        cfg = {**m.DEFAULT_CONFIG}
        ev = {"event": "usage", "seven_day": {"resets_at": "2026-10-13T08:00:00Z"},
              "decision": {"go": False, "kind": "window"}}
        text = m.notify_text([ev], cfg, "r1")
        self.assertIn("needs you: schedule is misaligned", text)
        self.assertIn("7 6 * * 2", text)
        self.assertIsNone(m.notify_text([ev], {**cfg, "expect_window_on_schedule": False}, "r1"))
        ok = {**ev, "decision": {"go": True, "kind": "ok"}}
        self.assertIsNone(m.notify_text([ok, ev], cfg, "r1"))  # mid-run reset buffer: no alarm


if __name__ == "__main__":
    unittest.main()
