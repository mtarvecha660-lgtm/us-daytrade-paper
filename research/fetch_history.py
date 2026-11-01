"""Download ~60 days of Yahoo 5-minute bars for the universe + SPY into data/cache (for the backtest)."""
import gzip, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from daytrade.skills import entry
from daytrade.universe import load_universe

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cache")

def main():
    os.makedirs(OUT, exist_ok=True)
    syms = load_universe() + ["SPY"]
    ok = fail = 0
    for s in syms:
        p = os.path.join(OUT, s + ".json.gz")
        if os.path.exists(p):
            ok += 1; continue
        try:
            txt = entry.yahoo_get(entry.chart_path(s, "60d", "5m"))
            ch = entry.parse_chart(txt, s)
            with gzip.open(p, "wt") as fh:
                json.dump({"symbol": ch["symbol"], "bars": ch["bars"], "prev_close": ch["prev_close"],
                           "data_time": ch["data_time"], "fetched": int(time.time())}, fh)
            ok += 1
        except Exception as e:
            fail += 1
            print("FAIL", s, e, flush=True)
        time.sleep(0.3)
    print("done ok=%d fail=%d" % (ok, fail), flush=True)

if __name__ == "__main__":
    main()
