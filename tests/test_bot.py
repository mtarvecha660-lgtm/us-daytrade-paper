import copy, datetime, hashlib, json, os, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "live"))
from daytrade import engine as G, metrics as M  # noqa: E402

with open(os.path.join(ROOT, "config.json")) as _fh:
    CFG = json.load(_fh)
DAY = datetime.date(2026, 10, 30)          # a normal Friday session
OTS, CTS = G.session_bounds(DAY)


def bar(k, o, h, l, c, v=100000):
    return {"t": OTS + 300 * k, "o": o, "h": h, "l": l, "c": c, "v": v}


def flat_bars(n_from, n_to, px=101.0):
    return [bar(k, px, px + 0.05, px - 0.05, px) for k in range(n_from, n_to)]


def base_day(after):
    """Opening range 9:30-9:45: high 101, low 99 (mid 100). The 9:45 bar closes 101.50 -> trigger at 9:50."""
    b = [bar(0, 100, 101, 99, 100.5), bar(1, 100.5, 100.9, 99.5, 100.2), bar(2, 100.2, 100.8, 99.8, 100.6),
         bar(3, 100.6, 101.6, 100.5, 101.5)]
    return b + after


def run(maps, cfg=CFG, upto=None, steps=None):
    acct = G.new_account(cfg)
    prev = {s: 100.0 for s in maps}
    m = {s: G.day_bars(bs, DAY) for s, bs in maps.items()}
    if steps:
        for u in steps:
            G.run_day(acct, DAY, m, prev, cfg, u)
    else:
        G.run_day(acct, DAY, m, prev, cfg, upto or CTS)
    return acct


class TestFills(unittest.TestCase):
    def test_target_fill_next_open_with_slippage(self):
        acct = run({"AAA": base_day([bar(4, 101.6, 103.5, 101.4, 103.2)] + flat_bars(5, 78, 103.2))})
        self.assertEqual(len(acct["trades"]), 1)
        t = acct["trades"][0]
        self.assertEqual(t["qty"], 66)                 # $100 max loss / $1.50 risk a share
        self.assertAlmostEqual(t["entry_fill"], round(101.6 + 101.6 * 2 / 10000, 4))   # next open + 2 bps
        self.assertEqual(t["stop"], 100.0)             # opening-range midpoint
        self.assertEqual(t["target"], 103.0)           # 1R
        self.assertEqual(t["exit_fill"], 103.0)
        self.assertEqual(t["entry_et"], "09:50")

    def test_stop_first_when_both_touched(self):
        acct = run({"AAA": base_day([bar(4, 101.6, 103.5, 99.5, 101)] + flat_bars(5, 78, 101))})
        t = acct["trades"][0]
        self.assertIn("stop", t["exit_reason"])
        self.assertAlmostEqual(t["exit_fill"], round(100.0 - 0.02, 4))
        self.assertLess(t["r"], -1.0)

    def test_gap_below_stop_fills_at_open(self):
        acct = run({"AAA": base_day([bar(4, 101.6, 101.7, 101.2, 101.3), bar(5, 98.0, 98.5, 97.5, 98.2)] + flat_bars(6, 78, 98))})
        t = acct["trades"][0]
        self.assertIn("gapped", t["exit_reason"])
        self.assertAlmostEqual(t["exit_fill"], round(98.0 - 0.02, 4), places=3)

    def test_flat_by_355(self):
        acct = run({"AAA": base_day(flat_bars(4, 78, 101.7))})
        t = acct["trades"][0]
        self.assertEqual(t["exit_et"], "15:55")
        self.assertIn("flat by", t["exit_reason"])
        self.assertIsNone(acct["day_state"]["position"])

    def test_early_close_moves_flat_by(self):
        self.assertEqual(G.clock(G.flat_by_ts(datetime.date(2026, 11, 27), CFG)), "12:55")


class TestNoLookahead(unittest.TestCase):
    def test_future_bars_do_not_change_decision(self):
        a = base_day(flat_bars(4, 78, 101.7))
        b = copy.deepcopy(a)
        for x in b[5:]:
            x.update(o=500, h=600, l=1, c=550)      # wild future
        ma, mb = G.day_bars(a, DAY), G.day_bars(b, DAY)
        ra = G.evaluate("AAA", ma, DAY, OTS + 4 * 300, CFG)
        rb = G.evaluate("AAA", mb, DAY, OTS + 4 * 300, CFG)
        self.assertEqual(ra["trigger"], rb["trigger"])
        self.assertEqual(ra["opening_range"], rb["opening_range"])

    def test_chart_holds_only_closed_bars(self):
        m = G.day_bars(base_day(flat_bars(4, 78)), DAY)
        ch = G.chart_upto("AAA", m, OTS + 4 * 300)
        self.assertTrue(all(b["t"] + 300 <= OTS + 4 * 300 for b in ch["bars"]))
        self.assertEqual(len(ch["bars"]), 4)

    def test_no_trigger_before_range_complete(self):
        m = G.day_bars(base_day(flat_bars(4, 78)), DAY)
        self.assertNotEqual(G.evaluate("AAA", m, DAY, OTS + 3 * 300, CFG).get("status"), "triggered")


class TestReplay(unittest.TestCase):
    def maps(self):
        out = {}
        for i, s in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE"]):
            k0 = 3 + 6 * i      # each breaks out later in the day
            bs = [bar(0, 100, 101, 99, 100.5), bar(1, 100.5, 100.9, 99.5, 100.2), bar(2, 100.2, 100.8, 99.8, 100.6)]
            bs += flat_bars(3, k0, 100.7)
            bs += [bar(k0, 100.7, 101.6, 100.6, 101.5), bar(k0 + 1, 101.5, 101.6, 99.0, 99.5)]   # breakout then stop
            bs += flat_bars(k0 + 2, 78, 99.5)
            out[s] = bs
        return out

    def test_incremental_equals_one_shot(self):
        one = run(self.maps())
        steps = list(range(OTS + 300, CTS + 1, 300 * 7)) + [CTS]
        inc = run(self.maps(), steps=steps)
        self.assertEqual(one["trades"], inc["trades"])

    def test_max_three_trades_a_day(self):
        acct = run(self.maps())
        self.assertEqual(len(acct["trades"]), 3)      # the skill's max_trades_per_day
        self.assertTrue(any("max" in d["text"] or "trades" in d["text"] for d in acct["decisions"] if d["kind"] == "skip"))

    def test_trigger_cache_equals_bar_by_bar(self):
        maps = {s: G.day_bars(b, DAY) for s, b in self.maps().items()}
        for s, m in maps.items():
            cached = G.trigger_end_ts(G.evaluate(s, m, DAY, CTS, CFG), DAY)
            fresh = [e for e in G.bar_ends(DAY, None, CTS) if G.trigger_end_ts(G.evaluate(s, m, DAY, e, CFG), DAY) == e]
            self.assertEqual([cached], fresh)

    def test_one_position_at_a_time(self):
        ms = self.maps()
        ms["ZZZ"] = [dict(b, v=10 ** 7) for b in base_day(flat_bars(4, 78, 101.7))]   # most traded, holds all day
        acct = run(ms)
        self.assertEqual([t["symbol"] for t in acct["trades"]], ["ZZZ"])


class TestSkillRules(unittest.TestCase):
    def test_stop_too_far_is_refused(self):
        bs = [bar(0, 100, 130, 70, 100), bar(1, 100, 101, 99, 100), bar(2, 100, 101, 99, 100),
              bar(3, 100, 131, 100, 130.5)] + flat_bars(4, 78, 130)
        cfg = copy.deepcopy(CFG)
        cfg["skill"]["max_loss_per_trade_usd"] = 20      # 1 share risks $30.50
        acct = run({"AAA": bs}, cfg=cfg)
        self.assertEqual(acct["trades"], [])
        self.assertTrue(any("trader-budget" in d["text"] for d in acct["decisions"]))

    def test_no_entries_after_cutoff(self):
        bs = [bar(0, 100, 101, 99, 100.5), bar(1, 100.5, 100.9, 99.5, 100.2), bar(2, 100.2, 100.8, 99.8, 100.6)]
        bs += flat_bars(3, 72, 100.7) + [bar(72, 100.7, 101.6, 100.6, 101.5)] + flat_bars(73, 78, 101.5)   # 15:30 bar
        self.assertEqual(run({"AAA": bs})["trades"], [])

    def test_vendored_skill_unchanged(self):
        src = json.load(open(os.path.join(ROOT, "skill", "SOURCE.json")))
        for f, h in src["sha256"].items():
            with open(os.path.join(ROOT, "skill", f), "rb") as fh:
                self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), h, f)

    def test_paper_only(self):
        self.assertTrue(CFG["paper"])
        self.assertTrue(CFG["skill"]["paper"])
        for d in ("daytrade", "live"):
            for f in os.listdir(os.path.join(ROOT, d)):
                if f.endswith(".py"):
                    txt = open(os.path.join(ROOT, d, f)).read()
                    self.assertNotIn("ticket", txt)        # trader-broker is not vendored or imported
                    self.assertNotIn("api_key", txt.lower())
        self.assertFalse(os.path.exists(os.path.join(ROOT, "skill", "ticket.py")))


class TestTick(unittest.TestCase):
    def test_closed_day_needs_no_network(self):
        import tick
        from daytrade.skills import scan, entry
        d = tempfile.mkdtemp()
        os.environ["TICK_NOW"] = str(G.ts_of_et(datetime.date(2026, 10, 31), datetime.time(12, 0)))  # Saturday
        old = (tick.STATE, tick.DATA, scan.yahoo_get, entry.yahoo_get)
        tick.STATE, tick.DATA = os.path.join(d, "s"), os.path.join(d, "d")

        def boom(*a):
            raise AssertionError("no network on a closed day")
        scan.yahoo_get = entry.yahoo_get = boom
        try:
            self.assertEqual(tick.main(), 0)
            with open(os.path.join(d, "d", "latest.json")) as fh:
                lat = json.load(fh)
            self.assertEqual(lat["phase"], "closed")
            self.assertIn("Mon Nov 2", lat["next_move"])
            self.assertTrue(lat["health"]["ok"])
        finally:
            tick.STATE, tick.DATA, scan.yahoo_get, entry.yahoo_get = old
            del os.environ["TICK_NOW"]

    def test_data_failure_is_a_red_run(self):
        import tick
        from daytrade.skills import scan
        d = tempfile.mkdtemp()
        os.environ["TICK_NOW"] = str(OTS + 3600)
        old = (tick.STATE, tick.DATA, scan.fetch_spark)
        tick.STATE, tick.DATA = os.path.join(d, "s"), os.path.join(d, "d")
        scan.fetch_spark = lambda syms, *a, **k: ({}, {s: "HTTP 429" for s in syms})
        try:
            self.assertEqual(tick.main(), 1)
            with open(os.path.join(d, "d", "latest.json")) as fh:
                lat = json.load(fh)
            self.assertFalse(lat["health"]["ok"])
        finally:
            tick.STATE, tick.DATA, scan.fetch_spark = old
            del os.environ["TICK_NOW"]


class TestMetrics(unittest.TestCase):
    def test_drawdown(self):
        self.assertAlmostEqual(M.max_drawdown([100, 120, 90, 130]), -0.25)

    def test_trade_stats(self):
        s = M.trade_stats([{"pnl": 10, "r": 1, "exit_reason": "target"}, {"pnl": -5, "r": -0.5, "exit_reason": "stop"}])
        self.assertEqual(s["win_rate"], 0.5)
        self.assertAlmostEqual(s["profit_factor"], 2.0)


if __name__ == "__main__":
    unittest.main()
