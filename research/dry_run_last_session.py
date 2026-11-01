"""Dry-run the live tick on the LAST SESSION's real Yahoo bars: call live/tick.py's main() at a series of
pretend clock times (every 5 minutes, 9:30 AM to 4:15 PM ET), with each Yahoo answer fetched once and reused.
Writes to a scratch state dir, then checks the trades equal a one-day backtest of the same day.

python research/dry_run_last_session.py [YYYY-MM-DD] [--every 5]
"""
import argparse, datetime, json, os, shutil, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "live"))
sys.path.insert(0, os.path.join(ROOT, "research"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("day", nargs="?")
    ap.add_argument("--every", type=int, default=5)
    a = ap.parse_args()
    scratch = tempfile.mkdtemp(prefix="dryrun-")
    os.environ["TICK_STATE_DIR"] = os.path.join(scratch, "state")
    os.environ["TICK_DATA_DIR"] = os.path.join(scratch, "data")
    import tick
    from daytrade import engine as G
    from daytrade.skills import entry as E, scan as SC
    memo = {}
    calls, per_tick = [], []
    real_e, real_s = E.yahoo_get, SC.yahoo_get

    def m_e(path):
        calls.append(path)
        if path not in memo:
            memo[path] = real_e(path)
        return memo[path]

    def m_s(path):
        calls.append(path)
        if path not in memo:
            memo[path] = real_s(path)
        return memo[path]
    E.yahoo_get, SC.yahoo_get = m_e, m_s
    tick.time.sleep = lambda s: None
    SC.SLEEP = lambda s: None
    spy = E.parse_chart(m_e(E.chart_path("SPY", "1d", "5m")), "SPY")
    day = datetime.date.fromisoformat(a.day) if a.day else G.et_of(spy["bars"][-1]["t"]).date()
    ots, cts = G.session_bounds(day)
    t = ots - 300
    codes = []
    while t <= cts + 15 * 60:
        os.environ["TICK_NOW"] = str(t + 70)
        n0 = len(calls)
        codes.append((G.clock(t + 70), tick.main()))
        per_tick.append(len(calls) - n0)
        t += a.every * 60
    st = json.load(open(os.path.join(scratch, "state", "account.json")))
    latest = json.load(open(os.path.join(scratch, "data", "latest.json")))
    # one-day backtest of the same day from the same charts (the replay must agree with the backtest engine)
    import backtest as BT
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    syms = [s for s in tick.load_universe()] + ["SPY"]
    charts = {}
    for s in syms:
        p = E.chart_path(s, "1d", "5m")
        if p in memo:
            try:
                charts[s] = E.parse_chart(memo[p], s)
            except Exception:
                pass
    # symbols the live tick never fetched (no stage-1 candidate) cannot trigger: fetch them too for the check
    for s in syms:
        if s not in charts:
            try:
                charts[s] = E.parse_chart(m_e(E.chart_path(s, "1d", "5m")), s)
            except Exception:
                pass
    acct, labels, curve, spyc = BT.run(cfg, charts, days=[day])
    bt = [(x["symbol"], x["entry_et"], x["exit_et"], x["qty"], round(x["pnl"], 2)) for x in acct["trades"]]
    lv = [(x["symbol"], x["entry_et"], x["exit_et"], x["qty"], round(x["pnl"], 2)) for x in st["trades"]]
    out = {"day": day.isoformat(), "ticks": len(codes), "exit_codes": sorted(set(c for _, c in codes)),
           "live_trades": lv, "backtest_trades": bt, "match": lv == bt,
           "live_hits": len(st["day_state"].get("hits", [])),
           "backtest_hits": len((acct.get("day_state") or {}).get("hits", [])), "equity": latest["account"],
           "spy": latest["spy"], "next_move": latest["next_move"], "hits_today": latest["today"]["n_hits"],
           "requests": len(memo), "yahoo_requests_per_tick_max": max(per_tick), "yahoo_requests_per_tick_avg": round(sum(per_tick) / len(per_tick), 1), "scratch": scratch}
    print(json.dumps(out, indent=1, default=str))
    return 0 if out["match"] and out["live_hits"] == out["backtest_hits"] and out["exit_codes"] == [0] else 1


if __name__ == "__main__":
    sys.exit(main())
