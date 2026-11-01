"""The bar-by-bar PAPER engine, shared by the backtest and the live tick.

Every decision uses only 5-minute bars that have CLOSED by the decision time. Orders fill on later,
closed bars:
  * entry:  a market order decided when a bar closes fills at the OPEN of the next bar, plus slippage;
  * stop:   a bar trading at or below the stop sells at the stop (or at the open if it gapped below), minus
            slippage. If one bar touches both stop and target, the stop is assumed to come first;
  * target: the take-profit limit sells at the target (or at the open if it gapped above) once a bar trades
            at least a cent through it; no slippage on a limit;
  * flat-by: still open when the bar ending 3:55 PM ET closes -> market sell at that close, minus slippage.

The skill's own tools make every trading decision (vendored unchanged in skill/):
  trader-entry  evaluate()        the opening-range breakout trigger (first 5-min close above the 15-min high)
  trader-exit   compute()         stop at the opening-range midpoint, target 1R; resolve_flat_by() -> 15:55
  trader-budget size_trade()      whole shares inside the four limits; refuses a bad reward:risk, etc.
                bracket_order()   the one bracket order
  trader-risk   check()           PASS/BLOCK against the day's limits (trades a day, daily loss, window, dupes)
Where the skill waits for a human "yes", this bot auto-approves on paper and logs the full reasoning.
"""
import datetime

from daytrade.skills import entry as E, exitp as X, size as S, risk as R

STEP = 300  # 5-minute bars


# ------------------------------------------------------------------ the skill's own clock

def et_of(ts):
    return E.to_eastern(E.utc_of(ts))


def ts_of_et(day, t):
    return E.ts_of(E.eastern_to_utc(datetime.datetime.combine(day, t)))


def session_bounds(day):
    """(open_ts, close_ts) in UTC epoch seconds, or None when the NYSE is closed that day."""
    ok, _ = E.trading_day(day)
    if not ok:
        return None
    o, c = E.session(day)
    return ts_of_et(day, o), ts_of_et(day, c)


def flat_by_ts(day, cfg):
    hhmm, _note = X.resolve_flat_by(day, None, cfg["skill"], None)
    return ts_of_et(day, datetime.datetime.strptime(hhmm, "%H:%M").time())


def clock(ts):
    return et_of(ts).strftime("%H:%M")


def entry_cfg(cfg):
    c = dict(E.DEFAULTS)
    for k in ("no_entries_before", "no_entries_after"):
        c[k] = cfg["skill"][k]
    return c


# ------------------------------------------------------------------ costs

def slip(price, cfg):
    return max(cfg["slippage_min_usd"], price * cfg["slippage_bps"] / 10000.0)


def buy_fill(price, cfg):
    return round(price + slip(price, cfg), 4)


def sell_fill(price, cfg):
    return round(price - slip(price, cfg), 4)


# ------------------------------------------------------------------ bars

def day_bars(bars, day):
    """Regular-session 5-minute bars of `day`, keyed by start ts (on the grid, 9:30 to the close)."""
    sb = session_bounds(day)
    if not sb:
        return {}
    ots, cts = sb
    return {b["t"]: b for b in bars if not b["t"] % STEP and ots <= b["t"] < cts}


def usable_through(bmap, day, end_ts):
    """trader-scanner's 'usable chart' rule: every 5-minute bar from 9:30 up to end_ts is there."""
    t = session_bounds(day)[0]
    while t + STEP <= end_ts:
        if t not in bmap:
            return False
        t += STEP
    return True


def chart_upto(sym, bmap, end_ts, prev_close=None):
    """A trader-entry chart holding ONLY bars that closed by end_ts (no look-ahead)."""
    return {"symbol": sym, "bars": [bmap[t] for t in sorted(bmap) if t + STEP <= end_ts],
            "prev_close": prev_close, "data_time": None}


def evaluate(sym, bmap, day, now_ts, cfg, prev_close=None):
    """trader-entry's verdict at now_ts, on the bars closed by then."""
    return E.evaluate(chart_upto(sym, bmap, now_ts, prev_close), E.utc_of(now_ts), setup="orb",
                      or_minutes=cfg["or_minutes"], interval="5m", cfg=entry_cfg(cfg))


def trigger_end_ts(res, day):
    """The close time (UTC ts) of the trigger bar in a trader-entry result, or None."""
    trig = res.get("trigger") if res.get("status") == "triggered" else None
    if not trig:
        return None
    return session_bounds(day)[0] + (int(trig["bar_index"]) + 1) * STEP


def dollar_volume(bmap, end_ts):
    """trader-scanner ranks hits most traded first: price x volume so far."""
    return sum(b["c"] * (b.get("v") or 0) for t, b in bmap.items() if t + STEP <= end_ts)


# ------------------------------------------------------------------ state

def new_account(cfg, start_ts=None):
    return {"cash": float(cfg["account_usd"]), "start_cash": float(cfg["account_usd"]), "started": start_ts,
            "day": None, "trades": [], "decisions": [], "equity": [], "day_state": None}


def new_day(day):
    return {"date": day.isoformat(), "last_bar_end": None, "position": None, "pending": None,
            "orders": [], "entries": 0, "skips": 0, "triggers_seen": 0, "missed": []}


def equity_now(acct, marks, cfg):
    """Cash plus any open position valued as if sold now at its last close, with slippage."""
    ds = acct.get("day_state") or {}
    pos = ds.get("position")
    eq = acct["cash"]
    if pos:
        eq += pos["qty"] * sell_fill(marks.get(pos["symbol"], pos["entry_fill"]), cfg)
    return round(eq, 2)


def log(acct, ts, kind, text, **kw):
    d = {"ts": ts, "et": et_of(ts).strftime("%Y-%m-%d %H:%M"), "kind": kind, "text": text}
    d.update(kw)
    acct["decisions"].append(d)
    return d


# ------------------------------------------------------------------ the decision chain (the skill, auto-approved)

def propose(sym, res, bmap, ds, acct, cfg, now_ts):
    """trader-exit -> trader-budget -> trader-risk for one trigger. Returns (order, reasoning, refusal)."""
    day = datetime.date.fromisoformat(ds["date"])
    trig, rng = res["trigger"], res["opening_range"]
    why = {"scanner": "%s: the %s bar closed at $%.2f, above the 15-min opening range high $%.2f (range %.2f-%.2f)" % (
        sym, trig["bar_start"], trig["close"], rng["high"], rng["low"], rng["high"])}
    try:
        plan = X.compute(X.D(str(trig["close"])), "or_mid", None, "r", X.D(str(cfg["target_r"])),
                         or_high=X.D(str(rng["high"])), or_low=X.D(str(rng["low"])))
    except X.PlanError as e:
        return None, why, "trader-exit: %s" % e
    entry_t = datetime.datetime.strptime(trig["close_time"], "%H:%M").time()
    try:
        flat_by, _ = X.resolve_flat_by(day, None, cfg["skill"], entry_t)
    except X.PlanError as e:
        return None, why, "trader-exit: %s" % e
    p = {"symbol": sym, "side": "buy", "setup": "orb", "date": ds["date"], "entry_time": trig["time"],
         "entry": float(plan["entry"]), "stop": float(plan["stop"]), "target": float(plan["target"]),
         "stop_label": plan["stop_label"], "target_label": plan["target_label"], "flat_by": flat_by}
    why["exit"] = "plan: entry $%.2f, stop $%.2f (%s), target $%.2f (%s), flat by %s ET" % (
        p["entry"], p["stop"], plan["stop_label"], p["target"], plan["target_label"], flat_by)
    try:
        # the paper account's cash is the budget (so trader-budget's position cap and trader-risk's agree)
        s = S.size_trade(p, cfg["skill"], budget=round(acct["cash"], 2), price=trig["close"], cash=acct["cash"],
                         today=ds["date"])
    except S.SizeError as e:
        return None, why, "trader-budget: %s" % e
    if s["refusal"]:
        return None, why, "trader-budget: %s" % s["refusal"]
    order = S.bracket_order(s)
    why["budget"] = order["why"] + " (limits: " + "; ".join(
        "%s %d" % (l["name"], l["shares"]) for l in s["limits"]) + ")"
    chk = R.check([order], cfg["skill"], portfolio={"cash": acct["cash"], "positions": []},
                  prices={sym: trig["close"]}, state={"orders": ds["orders"]}, today=ds["date"],
                  now=E.utc_of(now_ts))
    r0 = chk["results"][0]
    if r0["verdict"] != "PASS":
        return None, why, "trader-risk BLOCK: %s" % "; ".join(r0["reasons"])
    why["risk"] = "trader-risk PASS" + ((": " + "; ".join(r0["info"])) if r0.get("info") else "")
    why["approval"] = "auto-approved on paper (the skill waits for a human yes here; this bot says yes to every PASS)"
    return {"order": order, "sizing": {k: s[k] for k in ("qty", "bound_by", "risk_per_share", "max_loss", "cost")},
            "plan": p, "or_high": rng["high"], "or_low": rng["low"], "trigger_close": trig["close"],
            "trigger_time": trig["close_time"], "max_loss": r0["max_loss"]}, why, None


# ------------------------------------------------------------------ one bar close

def _close_position(acct, ds, ts, price, reason, cfg):
    pos = ds["position"]
    proceeds = pos["qty"] * price
    acct["cash"] = round(acct["cash"] + proceeds, 4)
    pnl = round((price - pos["entry_fill"]) * pos["qty"], 2)
    risk_usd = pos["qty"] * (pos["plan"]["entry"] - pos["plan"]["stop"])
    tr = {"date": ds["date"], "symbol": pos["symbol"], "qty": pos["qty"],
          "entry_et": clock(pos["entry_ts"]), "entry_fill": round(pos["entry_fill"], 4),
          "exit_et": clock(ts), "exit_fill": round(price, 4), "exit_reason": reason,
          "stop": pos["plan"]["stop"], "target": pos["plan"]["target"], "pnl": pnl,
          "r": round(pnl / risk_usd, 3) if risk_usd > 0 else None, "risk_usd": round(risk_usd, 2),
          "cost_usd": round(pos["qty"] * (pos["entry_fill"] - pos["plan"]["entry_ref"]) +
                            (pos["qty"] * (pos["exit_ref"] - price) if pos.get("exit_ref") else 0), 2),
          "why": pos["why"], "late": pos.get("late", False)}
    acct["trades"].append(tr)
    ds["orders"].append({"status": "filled", "date": ds["date"], "symbol": pos["symbol"], "side": "sell",
                         "kind": "exit", "qty": pos["qty"]})
    log(acct, ts, "exit", "SELL %d %s at $%.2f: %s. P&L $%+.2f (%+.2fR)" % (
        pos["qty"], pos["symbol"], price, reason, pnl, tr["r"] or 0), symbol=pos["symbol"])
    ds["position"] = None
    return tr


def process_bar(acct, ds, end_ts, maps, cfg, triggers, now_wall=None):
    """Process the bar that closed at end_ts. maps: {SYM: {start_ts: bar}} for today.
    triggers: {SYM: trader-entry result} whose trigger bar closed exactly at end_ts (fresh triggers)."""
    day = datetime.date.fromisoformat(ds["date"])
    start = end_ts - STEP
    fb = flat_by_ts(day, cfg)
    _, close_ts = session_bounds(day)

    # 1. a pending market order fills at the open of the first bar after the decision
    pend = ds.get("pending")
    if pend:
        b = maps.get(pend["symbol"], {}).get(start)
        if b is None:
            log(acct, end_ts, "cancel", "no %s bar after the signal (halt or missing data): order cancelled, no fill"
                % pend["symbol"], symbol=pend["symbol"])
            ds["pending"] = None
        else:
            q = pend["qty"]
            px = buy_fill(b["o"], cfg)
            cost = q * px
            if cost > acct["cash"]:
                q = int(acct["cash"] // px)
            acct["cash"] = round(acct["cash"] - q * px, 4)
            ds["position"] = {"symbol": pend["symbol"], "qty": q, "entry_fill": px, "entry_ts": start,
                              "plan": dict(pend["plan"], entry_ref=b["o"]), "why": pend["why"],
                              "late": pend.get("late", False)}
            ds["pending"] = None
            ds["orders"].append({"status": "filled", "date": ds["date"], "symbol": pend["symbol"], "side": "buy",
                                 "kind": "entry", "qty": q})
            log(acct, start, "fill", "BUY %d %s filled at $%.2f (next bar's open $%.2f + slippage). Stop $%.2f, "
                "target $%.2f" % (q, pend["symbol"], px, b["o"], pend["plan"]["stop"], pend["plan"]["target"]),
                symbol=pend["symbol"])

    # 2. exits on this closed bar
    pos = ds.get("position")
    if pos:
        b = maps.get(pos["symbol"], {}).get(start)
        stop, target = pos["plan"]["stop"], pos["plan"]["target"]
        if b is not None:
            if b["o"] <= stop:
                pos["exit_ref"] = b["o"]
                _close_position(acct, ds, end_ts, sell_fill(b["o"], cfg), "gapped through the stop $%.2f" % stop, cfg)
            elif b["l"] <= stop:
                pos["exit_ref"] = stop
                _close_position(acct, ds, end_ts, sell_fill(stop, cfg), "stop $%.2f hit" % stop, cfg)
            elif b["o"] >= target + 0.01:
                _close_position(acct, ds, end_ts, b["o"], "opened above the target $%.2f (limit filled at the open)"
                                % target, cfg)
            elif b["h"] >= target + 0.01:
                _close_position(acct, ds, end_ts, target, "target $%.2f hit (1R)" % target, cfg)
        pos = ds.get("position")
        if pos and (end_ts >= fb or end_ts >= close_ts):
            last = b if b is not None else _last_bar(maps.get(pos["symbol"], {}), end_ts)
            if last is not None:
                pos["exit_ref"] = last["c"]
                _close_position(acct, ds, end_ts, sell_fill(last["c"], cfg),
                                "flat by %s ET (the skill's flat-by rule)" % clock(fb), cfg)

    # 3. a new entry on a fresh trigger (one position at a time, the skill's one-plan flow)
    if triggers and not ds.get("position") and not ds.get("pending"):
        ds["triggers_seen"] += len(triggers)
        ranked = sorted(triggers, key=lambda s: -dollar_volume(maps.get(s, {}), end_ts))
        for sym in ranked:
            prop, why, refusal = propose(sym, triggers[sym], maps.get(sym, {}), ds, acct, cfg, end_ts)
            if refusal:
                ds["skips"] += 1
                log(acct, end_ts, "skip", "%s triggered but skipped. %s" % (sym, refusal), symbol=sym,
                    why=why)
                continue
            late = bool(now_wall and now_wall - end_ts > cfg["late_seconds"])
            ds["pending"] = {"symbol": sym, "qty": prop["sizing"]["qty"], "plan": prop["plan"], "why": why,
                             "decided_ts": end_ts, "late": late}
            ds["orders"].append({"status": "placed", "date": ds["date"], "symbol": sym, "side": "buy",
                                 "kind": "entry", "max_loss": prop["max_loss"], "at": et_of(end_ts).isoformat()})
            ds["entries"] += 1
            log(acct, end_ts, "order", "BUY %d %s at market (decided on the %s close). %s" % (
                prop["sizing"]["qty"], sym, clock(end_ts), why["budget"]), symbol=sym, why=why,
                others=[s for s in ranked if s != sym])
            break
    elif triggers:
        ds["triggers_seen"] += len(triggers)
        busy = (ds.get("position") or ds.get("pending") or {}).get("symbol")
        names = sorted(triggers)
        ds["missed"].extend(names)
        log(acct, end_ts, "busy", "%d more breakout%s (%s) not taken: already in %s (one trade at a time)" % (
            len(names), "" if len(names) == 1 else "s", ", ".join(names[:8]) + (" ..." if len(names) > 8 else ""),
            busy), symbols=names)
    ds["last_bar_end"] = end_ts


def _last_bar(bmap, end_ts):
    ks = [t for t in bmap if t + STEP <= end_ts]
    return bmap[max(ks)] if ks else None


def bar_ends(day, after_ts, upto_ts):
    """Bar close times of `day` in (after_ts, upto_ts]."""
    ots, cts = session_bounds(day)
    t = ots + STEP
    out = []
    while t <= cts and t <= upto_ts:
        if after_ts is None or t > after_ts:
            out.append(t)
        t += STEP
    return out


def eligible(sym, bmap, prev_close, cfg):
    return prev_close is not None and prev_close >= cfg["min_price"]


def run_day(acct, day, maps, prev_closes, cfg, upto_ts, now_wall=None, trigger_cache=None):
    """Process every bar of `day` that closed in (last processed, upto_ts]. Used identically by the backtest
    (upto = the close, in one go) and the live tick (upto = the newest closed bar, a few at a time)."""
    ds = acct.get("day_state")
    if not ds or ds["date"] != day.isoformat():
        ds = new_day(day)
        acct["day_state"] = ds
    for end_ts in bar_ends(day, ds["last_bar_end"], upto_ts):
        fresh = {}
        for sym, bmap in maps.items():
            if sym == cfg["benchmark"] or not eligible(sym, bmap, prev_closes.get(sym), cfg):
                continue
            if end_ts - STEP not in bmap or not usable_through(bmap, day, end_ts):
                continue
            res = trigger_cache.get(sym) if trigger_cache is not None else None
            if res is None:
                res = evaluate(sym, bmap, day, end_ts, cfg, prev_closes.get(sym))
            if trigger_end_ts(res, day) == end_ts:
                fresh[sym] = res
                ds.setdefault("triggered", []).append(sym)
                trig, rng = res["trigger"], res["opening_range"]
                ds.setdefault("hits", []).append({"symbol": sym, "at": clock(end_ts), "price": trig["price"],
                                                   "or_high": rng["high"], "or_low": rng["low"],
                                                   "pct_over": trig["pct_over"]})
        process_bar(acct, ds, end_ts, maps, cfg, fresh, now_wall=now_wall)
    return ds
