"""Backtest the bot on Yahoo's free ~60 days of 5-minute bars, with the SAME engine the live tick uses.

python research/backtest.py            -> research/backtest_result.json + prints a summary
python research/backtest.py --target-r 2   (sensitivity only; the frozen setting is 1R)
"""
import argparse, datetime, gzip, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from daytrade import engine as G, metrics as M
from daytrade.universe import load_universe

CACHE = os.path.join(ROOT, "data", "cache")


def load_cache(syms):
    out = {}
    for s in syms:
        p = os.path.join(CACHE, s + ".json.gz")
        if os.path.exists(p):
            out[s] = json.load(gzip.open(p, "rt"))
    return out


def sessions(charts, bench):
    days = sorted({G.et_of(b["t"]).date() for b in charts[bench]["bars"]})
    return [d for d in days if G.session_bounds(d)]


def run(cfg, charts, days=None):
    bench = cfg["benchmark"]
    days = days or sessions(charts, bench)
    acct = G.new_account(cfg)
    prev = {s: c.get("prev_close") for s, c in charts.items()}
    spy_sh = None
    curve, spy_curve, labels = [], [], []
    for day in days:
        maps = {s: G.day_bars(c["bars"], day) for s, c in charts.items()}
        maps = {s: m for s, m in maps.items() if m}
        ots, cts = G.session_bounds(day)
        # one trader-entry evaluation per chart per day at the close gives the day's first trigger;
        # the engine only acts on it at the bar where it is fresh (tested equal to bar-by-bar evaluation).
        cache = {s: G.evaluate(s, m, day, cts, cfg, prev.get(s)) for s, m in maps.items() if s != bench}
        G.run_day(acct, day, maps, prev, cfg, cts, trigger_cache=cache)
        sb = maps.get(bench)
        if sb:
            first = sb[min(sb)]
            last = sb[max(sb)]
            if spy_sh is None:
                spy_sh = cfg["account_usd"] / G.buy_fill(first["o"], cfg)
            spy_curve.append(round(spy_sh * G.sell_fill(last["c"], cfg), 2))
        curve.append(round(acct["cash"], 2))
        labels.append(day.isoformat())
        for s, m in maps.items():
            prev[s] = m[max(m)]["c"]
    return acct, labels, curve, spy_curve


def summary(acct, labels, curve, spy_curve, cfg):
    eq = [cfg["account_usd"]] + curve
    sp = [cfg["account_usd"]] + spy_curve
    return {"period": [labels[0], labels[-1]], "sessions": len(labels), "bot": M.curve_stats(eq),
            "spy": M.curve_stats(sp), "trades": M.trade_stats(acct["trades"]),
            "skips": sum(1 for d in acct["decisions"] if d["kind"] == "skip"),
            "days_with_trade": len({t["date"] for t in acct["trades"]})}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-r", type=float)
    ap.add_argument("--out", default=os.path.join(ROOT, "research", "backtest_result.json"))
    a = ap.parse_args()
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    if a.target_r:
        cfg["target_r"] = a.target_r
    syms = load_universe() + [cfg["benchmark"]]
    charts = load_cache(syms)
    acct, labels, curve, spy = run(cfg, charts)
    s = summary(acct, labels, curve, spy, cfg)
    s["universe"] = {"listed": len(syms) - 1, "with_data": len(charts) - 1,
                     "missing": sorted(set(syms) - set(charts))}
    s["config"] = {k: cfg[k] for k in ("version", "target_r", "slippage_bps", "slippage_min_usd")}
    out = {"summary": s, "trades": acct["trades"], "equity": list(zip(labels, curve, spy)),
           "decisions_sample": acct["decisions"][:400]}
    json.dump(out, open(a.out, "w"), indent=1, default=str)
    print(json.dumps(s, indent=1, default=str))


if __name__ == "__main__":
    main()
