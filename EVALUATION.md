# Forward-test evaluation criteria (locked before results)

Written and committed on **2026-11-02 (about 00:55 IST)**, before the bot's first live session.
The forward test starts with the first regular US session it trades: **Monday 2026-11-02, 9:30 AM ET (8:00 PM IST)**.
This file is the scorecard. Any later change goes in a new dated section with its reason; the original stays as written.

## What is being tested
The day-trader skill's opening-range-breakout day trade, run automatically on paper:
the skill's 234-stock example list, 15-minute opening range, entry on the first 5-minute close above the range high
(9:50 AM-3:30 PM ET), stop at the range midpoint, target 1R, flat by 3:55 PM ET, one trade at a time, max 3 a day,
max $100 loss a trade and $300 a day on a $10,000 virtual account, 2 bps (min 1 cent) slippage per market fill,
no commission. Full settings: `config.json` (version `orb-v1`).

## Ground rules
1. **Frozen settings.** `config.json` (sha256 `914b4dcc61dc24ca…`), the engine `daytrade/engine.py`
   (sha256 `f7472af0a1eef8dc…`) and the vendored skill files (`skill/SOURCE.json`, upstream commit
   `3d0f4ef6986f`) are frozen as of this commit. Changing a setting or a rule creates a NEW account
   (a new `version`, a fresh start date and a fresh trade count). The old account's record stays as it was.
2. **Forward results only.** The backtest (RESULTS.md) is never mixed into this scorecard.
3. **Same valuation for both.** The bot and the SPY benchmark are valued the same way: an open position as if
   sold now at the last close minus slippage. SPY is bought with the whole $10,000 at the open of the first bar the
   bot trades and is never sold.
4. **Paper only.** Passing this scorecard does NOT mean real money. At most it earns more paper testing.

## When the verdict is due
- **Health checks (no pass/fail):** after 20 sessions (about 1 Dec 2026) and at 2 months.
- **Verdict:** on the first trading day on which BOTH hold: at least **3 months** have passed (2 Feb 2027) and at
  least **100 closed trades** exist. If 100 trades are not reached by **3 May 2027** (6 months), the verdict is
  **NOT ENOUGH EVIDENCE** and the test ends there.

## The bot PASSES only if ALL of these hold at the verdict date
| # | Test | Rule |
|---|------|------|
| 1 | Net return | Return after all costs is above 0%. |
| 2 | Beats SPY risk-adjusted | Sharpe AND Sortino of daily returns are higher than SPY buy-and-hold's over the same dates. |
| 3 | Drawdown | Max drawdown (marked at every tick) is no worse than -10%. |
| 4 | Trade count | At least 100 closed trades (see the verdict date above). |
| 5 | Edge per trade | Average R per trade above 0, with a t-statistic of at least 1.65 (about 95% one-sided). Average R above 0 but t below 1.65 means **NOT ENOUGH EVIDENCE**, not a pass. |
| 6 | Survives double costs | Still above 0% net if every trade's slippage is doubled (recomputed from the trade log). |
| 7 | Consistency | In calendar months (a first or last month with fewer than 10 sessions is merged into its neighbour), the bot's net return is strictly lower than SPY's in no more than half of them. |
| 8 | Matches its backtest | Behaviour is plausible against the backtest: trades per session between 1.1 and 3 (backtest 2.2), win rate within 15 points of 47%, average losing trade no bigger than $110 (2x the backtest's $55). A miss here means a bug is suspected and must be checked before any verdict. |

Raw return vs SPY is **reported, not required** on its own: test 2 asks for better risk-adjusted return. The dashboard
always shows both side by side.

## Early stop (any time)
The account is marked **FAILED early** if:
- its drawdown from peak equity reaches **-15%**, or
- it shows a **bug**: a trade the rules should not allow, a fill on a bar that had not closed, a wrong valuation, or a
  missed flat-by. The bug is fixed in a new account (new version) and the clock restarts at zero.
Red runs from data outages are not a failure by themselves; they are counted and shown on the dashboard.

## What each outcome means
- **PASS:** a pass only earns **more paper testing**: another 6 months with the same frozen rules. Still no real money.
- **NOT ENOUGH EVIDENCE:** keep running unchanged until the 6-month limit; do not change the strategy to "help" it.
- **FAIL:** stop treating it as a candidate, and write down why.

## Known limits of this test (stated up front so they can't be used as excuses later)
- Fills are simulated from Yahoo's free 5-minute bars (open/high/low/close). Real fills can be worse: queue position,
  partial fills, wider spreads at 9:50 AM, and stop orders filling below the stop in fast markets.
- Yahoo's free data is unofficial and can lag. The bot waits a minute after each bar closes, and GitHub can start
  runs late; when a run is late the bot replays the missed bars in order, exactly as the backtest does, and marks
  any trade decided more than 10 minutes late.
- No PDT rule: a real US margin account under $25,000 is limited to 3 day trades in 5 business days. This paper
  account ignores that (the skill's `pdt_guard` is off by default).
- Regulatory sell fees (SEC/FINRA, a few cents a trade) are not charged.
