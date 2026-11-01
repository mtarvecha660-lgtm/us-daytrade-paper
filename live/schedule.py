"""How long the chain step should wait before starting the next run (used by the workflow).

Prints JSON: {"mode": "market"|"off-hours", "wait": seconds, "next_open_utc": ...}
  market:    during 9:20 AM-4:15 PM ET on a trading day -> next run ~5 minutes after this one began
  off-hours: nights, weekends, NYSE holidays -> sleep until 5 minutes before the next open, in pieces of at most
             MAX_SLEEP (a GitHub job may run 6 hours), then start the next run (which sleeps again if needed)
"""
import datetime, json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from daytrade import engine as G  # noqa: E402

CADENCE = 300
MAX_SLEEP = 330 * 60


def plan(now, started):
    day = G.et_of(now).date()
    sb = G.session_bounds(day)
    if sb and sb[0] - 10 * 60 <= now <= sb[1] + 15 * 60:
        return {"mode": "market", "wait": max(0, started + CADENCE - now)}
    d = day
    nxt = None
    for _ in range(15):
        b = G.session_bounds(d)
        if b and b[0] - 5 * 60 > now:
            nxt = b[0]
            break
        d += datetime.timedelta(days=1)
    target = (nxt or now + MAX_SLEEP) - 5 * 60
    budget = MAX_SLEEP - max(0, now - started)
    return {"mode": "off-hours", "wait": int(max(0, min(target - now, budget))), "next_open_utc": nxt}


if __name__ == "__main__":
    now = int(time.time())
    started = int(os.environ.get("TICK_START") or now)
    print(json.dumps(plan(now, started)))
