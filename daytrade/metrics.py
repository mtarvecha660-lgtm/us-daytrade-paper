"""Performance numbers, shared by the backtest report and the dashboard."""
import math


def max_drawdown(values):
    peak, mdd = None, 0.0
    for v in values:
        peak = v if peak is None or v > peak else peak
        if peak:
            mdd = min(mdd, v / peak - 1)
    return mdd


def daily_returns(values):
    return [values[i] / values[i - 1] - 1 for i in range(1, len(values)) if values[i - 1]]


def sharpe(rets, periods=252):
    if len(rets) < 2:
        return None
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))
    return None if sd == 0 else m / sd * math.sqrt(periods)


def sortino(rets, periods=252):
    if len(rets) < 2:
        return None
    m = sum(rets) / len(rets)
    dd = math.sqrt(sum(min(r, 0) ** 2 for r in rets) / len(rets))
    return None if dd == 0 else m / dd * math.sqrt(periods)


def trade_stats(trades):
    n = len(trades)
    if not n:
        return {"trades": 0}
    pnl = [t["pnl"] for t in trades]
    rs = [t["r"] for t in trades if t.get("r") is not None]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p <= 0]
    gross_w, gross_l = sum(wins), -sum(losses)
    avg_r = sum(rs) / len(rs) if rs else None
    t_stat = None
    if len(rs) > 2:
        sd = math.sqrt(sum((r - avg_r) ** 2 for r in rs) / (len(rs) - 1))
        t_stat = avg_r / (sd / math.sqrt(len(rs))) if sd else None
    reasons = {}
    for t in trades:
        k = t["exit_reason"].split(" ")[0]
        k = {"stop": "stop", "gapped": "stop", "target": "target", "opened": "target", "flat": "flat-by"}.get(k, k)
        reasons[k] = reasons.get(k, 0) + 1
    return {"trades": n, "wins": len(wins), "win_rate": len(wins) / n, "avg_r": avg_r, "t_stat_r": t_stat,
            "net_pnl": round(sum(pnl), 2), "profit_factor": (gross_w / gross_l) if gross_l else None,
            "expectancy_usd": round(sum(pnl) / n, 2),
            "avg_win": round(gross_w / len(wins), 2) if wins else None,
            "avg_loss": round(-gross_l / len(losses), 2) if losses else None,
            "costs_usd": round(sum(t.get("cost_usd", 0) for t in trades), 2), "exits": reasons}


def curve_stats(values):
    if not values:
        return {}
    rets = daily_returns(values)
    return {"return": values[-1] / values[0] - 1, "max_drawdown": max_drawdown(values),
            "sharpe": sharpe(rets), "sortino": sortino(rets), "days": len(values)}
