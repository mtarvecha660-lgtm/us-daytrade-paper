"""One live PAPER tick (GitHub Actions runs this every ~5 minutes during US market hours).

Reads only bars that have closed, replays every bar since the last tick through the same engine the
backtest uses, writes the state, and docs/data/latest.json for the dashboard.
Exit code 1 (red run) when the tick failed: an exception, or Yahoo data missing for most of the list or for
the stock the bot holds. Paper only: there is no order code anywhere in this repo.
"""
import datetime, json, os, sys, time, traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from daytrade import engine as G, metrics as M  # noqa: E402
from daytrade.skills import entry as E, scan as SC  # noqa: E402
from daytrade.universe import load_universe  # noqa: E402

STATE = os.environ.get("TICK_STATE_DIR") or os.path.join(ROOT, "live", "state")
DATA = os.environ.get("TICK_DATA_DIR") or os.path.join(ROOT, "docs", "data")
SETTLE = 60          # a bar counts as closed one minute after its end (Yahoo catches up)
DONE_AFTER = 10 * 60  # the day is finalised 10 minutes after the close


def jload(p, default):
    try:
        with open(p) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def jsave(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=1, default=str)
    os.replace(tmp, p)


def append_line(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a") as fh:
        fh.write(json.dumps(obj, default=str) + "\n")


def tail_lines(p, n):
    try:
        with open(p) as fh:
            lines = fh.readlines()
    except OSError:
        return []
    out = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass
    return out


def next_session(day):
    d = day
    for _ in range(15):
        d = d + datetime.timedelta(days=1)
        if G.session_bounds(d):
            return d
    return None


def fetch_chart(sym, rng="1d"):
    return E.parse_chart(E.yahoo_get(E.chart_path(sym, rng, "5m")), sym)


def stage1_candidates(series, day, after_ts, upto_ts, cfg, done):
    """trader-scanner's stage 1 on spark closes, applied to the bars that closed since the last tick: a stock can
    only break out at bar T if its close at T is at or above the highest close of its opening range (the range high
    is at least every range close). A bar missing from spark counts as "maybe", so a data gap never hides a
    breakout. Stocks whose first breakout the bot already processed today (`done`) are skipped."""
    n_range = cfg["or_minutes"] // 5
    ots, _ = G.session_bounds(day)
    cutoff = G.et_of(upto_ts).replace(tzinfo=None)
    first = max(n_range, 0 if after_ts is None else (after_ts - ots) // 300)
    last = (upto_ts - ots) // 300          # bars 0 .. last-1 have closed
    cands = set()
    for sym, s in series.items():
        if sym in done:
            continue
        bars = SC.session_bars(s, day, cutoff)
        by_k = {(int((G.ts_of_et(day, b["start"].time()) - ots) // 300)): b for b in bars}
        rng = [by_k[k]["c"] for k in range(n_range) if k in by_k]
        if not rng:
            cands.add(sym)
            continue
        top = max(rng)
        for k in range(first, last):
            b = by_k.get(k)
            if b is None or b["c"] >= top:
                cands.add(sym)
                break
    return cands


def plain_next(acct, cfg, day, now, phase, n_universe):
    ds = acct.get("day_state") or {}
    pos, pend = ds.get("position"), ds.get("pending")
    nxt = None
    if phase in ("closed", "after-close", "pre-open"):
        d = day if phase == "pre-open" else next_session(day)
        if d:
            ots, _ = G.session_bounds(d)
            ist = datetime.datetime.utcfromtimestamp(ots) + datetime.timedelta(hours=5, minutes=30)
            nxt = "%s, 9:30 AM ET (%s IST)" % (d.strftime("%a %b %-d"), ist.strftime("%-I:%M %p"))
        return ("Market closed. Next open: %s. At 9:45 AM ET each of the %d stocks has its 15-minute opening range; "
                "from 9:50 the bot buys the first one whose 5-minute bar CLOSES above its range high (most traded "
                "first), stop at the range middle, target 1R, sold by 3:55 PM ET at the latest." % (nxt, n_universe))
    if pend:
        return ("Buying %d %s at the next bar's open (signal at %s ET). Then: stop $%.2f, target $%.2f."
                % (pend["qty"], pend["symbol"], G.clock(pend["decided_ts"]), pend["plan"]["stop"], pend["plan"]["target"]))
    if pos:
        return ("Holding %d %s bought at $%.2f. It sells at the stop $%.2f, the target $%.2f, or at %s ET, "
                "whichever comes first." % (pos["qty"], pos["symbol"], pos["entry_fill"], pos["plan"]["stop"],
                                            pos["plan"]["target"], cfg["skill"]["flat_by"]))
    used = ds.get("entries", 0)
    cap = cfg["skill"]["max_trades_per_day"]
    if used >= cap:
        return "Done for today: %d of %d trades used (the skill's daily limit). Flat until tomorrow." % (used, cap)
    et = G.et_of(now)
    if et.strftime("%H:%M") < "09:45":
        return "The opening range is still forming (9:30-9:45 AM ET). Watching from the 9:50 bar close."
    if et.strftime("%H:%M") >= cfg["skill"]["no_entries_after"]:
        return "No new entries after %s ET (the skill's rule). Flat, waiting for tomorrow." % cfg["skill"]["no_entries_after"]
    return ("Flat and watching %d stocks for a 5-minute close above the opening-range high. %d of %d trades used today."
            % (n_universe, used, cap))


def main():
    t0 = time.time()
    now = int(t0 if not os.environ.get("TICK_NOW") else float(os.environ["TICK_NOW"]))
    with open(os.path.join(ROOT, "config.json")) as fh:
        cfg = json.load(fh)
    if not cfg.get("paper", True):
        raise SystemExit("paper must be true: this bot never trades real money")
    universe = load_universe()
    acct = jload(os.path.join(STATE, "account.json"), None) or G.new_account(cfg, now)
    spy = acct.setdefault("spy", {"shares": None, "start_ts": None, "start_price": None, "last": None})
    day = G.et_of(now).date()
    sb = G.session_bounds(day)
    errors, health = [], {"tick_at": now, "data_ok": None, "data_failed": 0, "yahoo_time": None}
    phase = "closed"
    bars_done = 0
    marks = {}
    if sb:
        ots, cts = sb
        ds = acct.get("day_state") or {}
        finished = ds.get("date") == day.isoformat() and ds.get("finalised")
        if now < ots:
            phase = "pre-open"
        elif now >= cts + DONE_AFTER and finished:
            phase = "after-close"
        else:
            phase = "open" if now < cts else "after-close"
            upto = min(now - SETTLE, cts)
            upto -= (upto - ots) % 300
            after = ds.get("last_bar_end") if ds.get("date") == day.isoformat() else None
            # stage 1: spark closes for the whole list (20 a request, the scanner's own fetcher)
            series, failed = SC.fetch_spark(universe, "1d", "5m", 0.3)
            health["data_ok"], health["data_failed"] = len(series), len(failed)
            if len(series) < 0.5 * len(universe):
                errors.append("Yahoo sent 5-minute data for only %d of %d stocks" % (len(series), len(universe)))
            done = set(ds.get("triggered") or []) if ds.get("date") == day.isoformat() else set()
            cands = stage1_candidates(series, day, after, upto, cfg, done) if upto > ots else set()
            need = set(cands) | {cfg["benchmark"]}
            for k in ("position", "pending"):
                if ds.get(k) and ds.get("date") == day.isoformat():
                    need.add(ds[k]["symbol"])
            charts, chart_fail = {}, []
            for sym in sorted(need):
                try:
                    charts[sym] = fetch_chart(sym)
                except Exception as e:  # noqa: BLE001
                    chart_fail.append("%s: %s" % (sym, e))
                time.sleep(0.15)
            for k in ("position", "pending"):
                if ds.get(k) and ds.get("date") == day.isoformat() and ds[k]["symbol"] not in charts:
                    errors.append("no data for the held stock %s" % ds[k]["symbol"])
            if chart_fail and len(chart_fail) > max(3, 0.3 * len(need)):
                errors.append("Yahoo charts failed for %d of %d: %s" % (len(chart_fail), len(need), "; ".join(chart_fail[:3])))
            maps = {s: G.day_bars(c["bars"], day) for s, c in charts.items()}
            prev = {s: c.get("prev_close") for s, c in charts.items()}
            dts = [c.get("data_time") for c in charts.values() if c.get("data_time")]
            health["yahoo_time"] = max(dts) if dts else None
            health["candidates"] = len(cands)
            health["charts_fetched"] = len(charts)
            before = (acct.get("day_state") or {}).get("last_bar_end")
            if not errors or upto <= ots:
                G.run_day(acct, day, maps, prev, cfg, upto, now_wall=now)
            ds = acct["day_state"]
            bars_done = 0 if errors or upto <= ots else len(
                G.bar_ends(day, before if before and ds["date"] == day.isoformat() else None, upto))
            for s, m in maps.items():
                closed = [t for t in m if t + 300 <= upto]
                if closed:
                    marks[s] = m[max(closed)]["c"]   # valued at the last CLOSED bar
            # SPY benchmark: bought with the whole $10,000 at the first bar the bot saw, held, valued as if sold now
            sm = maps.get(cfg["benchmark"]) or {}
            if spy["shares"] is None and sm and min(sm) + 300 <= upto:
                t_first = min(sm)
                spy.update(start_ts=t_first, start_price=sm[t_first]["o"],
                           shares=cfg["account_usd"] / G.buy_fill(sm[t_first]["o"], cfg))
            sm_closed = [t for t in sm if t + 300 <= upto]
            if sm_closed:
                spy["last"] = sm[max(sm_closed)]["c"]
                spy["last_ts"] = max(sm_closed) + 300
            if now >= cts + DONE_AFTER and ds.get("last_bar_end") == cts and not errors:
                ds["finalised"] = True
                acct.setdefault("daily", []).append({"date": ds["date"], "equity": round(acct["cash"], 2),
                                                     "spy": round(spy["shares"] * G.sell_fill(spy["last"], cfg), 2)
                                                     if spy.get("shares") else None,
                                                     "trades": ds.get("entries", 0)})
    # equity point
    eq = G.equity_now(acct, marks, cfg)
    spy_val = round(spy["shares"] * G.sell_fill(spy["last"], cfg), 2) if spy.get("shares") and spy.get("last") else None
    if phase == "open" or (phase == "after-close" and bars_done):
        append_line(os.path.join(STATE, "equity.jsonl"), {"ts": now, "equity": eq, "spy": spy_val})
    new_dec = acct["decisions"]
    for d in new_dec:
        append_line(os.path.join(STATE, "decisions.jsonl"), d)
    acct["decisions"] = []
    acct.setdefault("seen_trades", 0)
    acct["started"] = acct.get("started") or now
    status = "error" if errors else "ok"
    run = {"ts": now, "phase": phase, "status": status, "bars": bars_done, "secs": round(time.time() - t0, 1),
           "errors": errors, "run_id": os.environ.get("GITHUB_RUN_ID"), "event": os.environ.get("GITHUB_EVENT_NAME")}
    append_line(os.path.join(STATE, "runs.jsonl"), run)
    jsave(os.path.join(STATE, "account.json"), acct)
    write_latest(acct, cfg, now, phase, day, eq, spy_val, health, errors, len(universe))
    print(json.dumps(run))
    for d in new_dec:
        print(d["et"], d["kind"], d["text"])
    return 1 if errors else 0


def write_latest(acct, cfg, now, phase, day, eq, spy_val, health, errors, n_universe):
    ds = acct.get("day_state") or {}
    today = ds if ds.get("date") == day.isoformat() else {}
    trades = acct["trades"]
    eqs = tail_lines(os.path.join(STATE, "equity.jsonl"), 5000)
    daily = acct.get("daily", [])
    curve = [cfg["account_usd"]] + [d["equity"] for d in daily]
    spy_curve = [cfg["account_usd"]] + [d["spy"] for d in daily if d.get("spy")]
    yt = health.get("yahoo_time")
    lag = round((now - yt) / 60.0, 1) if (yt and phase == "open") else None
    stale = bool(phase == "open" and (lag is None or lag > 15))
    health.update(ok=not errors, errors=errors, stale_data=stale, yahoo_lag_min=lag,
                  note="Yahoo's free 5-minute bars; the bot only uses bars that closed at least a minute ago, so "
                       "decisions run 1-6 minutes behind the market, plus however late GitHub starts the run.")
    pos = today.get("position")
    latest = {
        "updated": now, "updated_et": G.et_of(now).strftime("%Y-%m-%d %H:%M ET"), "phase": phase,
        "paper": True, "version": cfg["version"],
        "account": {"start": cfg["account_usd"], "cash": round(acct["cash"], 2), "equity": eq,
                    "return": eq / cfg["account_usd"] - 1, "started": acct.get("started")},
        "spy": {"value": spy_val, "return": (spy_val / cfg["account_usd"] - 1) if spy_val else None,
                "start_price": (acct.get("spy") or {}).get("start_price"), "last": (acct.get("spy") or {}).get("last")},
        "position": None if not pos else {"symbol": pos["symbol"], "qty": pos["qty"], "entry": pos["entry_fill"],
                                          "entry_et": G.clock(pos["entry_ts"]), "stop": pos["plan"]["stop"],
                                          "target": pos["plan"]["target"], "last": None, "why": pos.get("why")},
        "pending": today.get("pending"),
        "today": {"date": today.get("date"), "hits": (today.get("hits") or [])[-60:],
                  "n_hits": len(today.get("hits") or []), "entries": today.get("entries", 0),
                  "max_trades": cfg["skill"]["max_trades_per_day"]},
        "next_move": plain_next(acct, cfg, day, now, phase, n_universe),
        "stats": M.trade_stats(trades), "curve": M.curve_stats(curve), "spy_curve": M.curve_stats(spy_curve),
        "intraday_max_drawdown": M.max_drawdown([cfg["account_usd"]] + [e["equity"] for e in eqs]),
        "trades": trades[-200:][::-1],
        "decisions": tail_lines(os.path.join(STATE, "decisions.jsonl"), 80)[::-1],
        "equity": eqs[-3000:], "daily": daily,
        "runs": tail_lines(os.path.join(STATE, "runs.jsonl"), 40)[::-1],
        "health": health, "config": {k: cfg[k] for k in ("target_r", "slippage_bps", "slippage_min_usd", "or_minutes")},
        "skill_limits": cfg["skill"],
    }
    if pos:
        latest["position"]["last"] = None
    jsave(os.path.join(DATA, "latest.json"), latest)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:  # a crash is a red run, and the dashboard says so
        tb = traceback.format_exc()
        print(tb)
        try:
            append_line(os.path.join(STATE, "runs.jsonl"), {"ts": int(time.time()), "status": "crash",
                                                            "errors": [tb.strip().splitlines()[-1]],
                                                            "run_id": os.environ.get("GITHUB_RUN_ID")})
            lp = os.path.join(DATA, "latest.json")
            lat = jload(lp, {})
            lat.setdefault("health", {}).update(ok=False, errors=[tb.strip().splitlines()[-1]], crash_at=int(time.time()))
            jsave(lp, lat)
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1)
