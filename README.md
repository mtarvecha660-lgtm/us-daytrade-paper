# US Day-Trade Paper Bot

**PAPER ONLY.** Virtual money, no broker account, no API keys, no real orders. There is no order code in this repo.

A fully automatic paper day trader for US stocks, built on the
[day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) (MIT). Every trading decision is made by
the skill's own Python tools, vendored unchanged in `skill/` (upstream commit `3d0f4ef6986f`, checked by a
test). Where the skill waits for a human "yes", this bot auto-approves on paper and logs the full reasoning.

- **Dashboard:** https://mtarvecha660-lgtm.github.io/us-daytrade-paper/
- **Scorecard (locked before the first trade):** [EVALUATION.md](EVALUATION.md)
- **Backtest (60 days, small sample):** [RESULTS.md](RESULTS.md): -4.21% vs SPY -2.02%, 133 trades, no edge.

## What it does each session
| Time (ET) | IST (winter) | Step | Skill tool |
|---|---|---|---|
| 9:30-9:45 | 8:00-8:15 PM | Each of the 234 stocks builds its 15-minute opening range (high/low of the first three 5-min bars) | trader-entry |
| from 9:50 | 8:20 PM | **Scanner:** a hit is the first 5-minute bar that CLOSES above the range high (stage 1 on closes, stage 2 on real highs/lows) | trader-scanner, trader-entry |
| on a fresh hit | | **Exit plan:** stop at the range midpoint, target 1R | trader-exit |
| | | **Budget:** whole shares inside four limits ($100 max loss, 75% position cap, $8,000 max order, cash after a 10% buffer) | trader-budget |
| | | **Risk check:** max 3 trades/day, $300 daily loss, entry window 9:45-3:30, no duplicates | trader-risk |
| | | **Approval:** auto-yes on paper; buys at the next bar's open + slippage | (this bot) |
| until 3:55 | 2:25 AM | Exits on the stop or the target, or market-sells at 3:55 PM ET at the latest | trader-exit's flat-by |

If several stocks break out on the same bar it takes the most traded one first (the scanner's order). It holds one
trade at a time; breakouts that happen while it is in a trade are listed on the dashboard but not taken.

Settings are the skill's `config.example.json` limits scaled x2 for a $10,000 account (1% risk a trade, 3% a day).
Costs: no commission (like zero-commission US brokers), slippage of 2 bps (min 1 cent) a share on every market
fill. All settings: [`config.json`](config.json), frozen by EVALUATION.md.

## Honest notes
- **Data delay.** Yahoo's free chart data is unofficial and can lag. The bot only uses bars that closed at least a
  minute ago, so it acts 1-6 minutes behind the market plus however late GitHub starts the run. If a run is late it
  replays the missed bars in order (exactly like the backtest) and marks trades decided more than 10 minutes late.
- **No look-ahead.** Decisions only see closed bars; fills happen on the next closed bar. Tests check this.
- **The live tick and the backtest share one engine.** A dry run of the live tick over Fri 2026-10-30's real bars
  (83 ticks, 5 minutes apart) produced the same trade and the same 65 scan hits as the backtest of that day:
  `python research/dry_run_last_session.py`.
- **Benchmark:** $10,000 of SPY bought at the open of the first bar the bot trades, held, valued as if sold now.
- **Not modelled:** the PDT rule (3 day trades in 5 days under $25k on margin), SEC/FINRA sell fees, partial fills.

## How it runs (free, on GitHub Actions)
`.github/workflows/tick.yml` runs `live/tick.py` every ~5 minutes on weekdays during US hours, commits the state in
`live/state/` and `docs/data/latest.json`, and republishes `docs/` to GitHub Pages.
- **The chain (never depends on cron).** GitHub's cron is unreliable: it never fired on the sister BTC repo, and there
  a single stray cron run once switched the backup off for 2.5 hours. So every run starts the next one itself with
  `workflow_dispatch`: ~5 minutes after it began during market hours. Outside market hours (nights, weekends, NYSE
  holidays from the skill's calendar) a run sleeps up to 5.5 hours (GitHub's job limit is 6) toward 5 minutes before
  the next open, then starts the next run, which sleeps again if the open is still far; that is how it wakes up every
  morning with no cron. Right before dispatching, a run checks whether a NEWER run of this workflow is already queued
  or running (for example a cron run waiting behind it); if so, that run carries the chain, so there is only ever
  one chain. A finished or cancelled cron run never switches it off. The cron line stays as a free extra.
- **Health:** a failed tick (crash, Yahoo data missing for most stocks or for the held stock) exits 1 and turns the
  run red. `latest.json` has a `health` block; the dashboard shows a red banner if the last run failed or if there was
  no update for 20 minutes while the market is open, and an amber dot when Yahoo's data runs over 15 minutes behind.
- GitHub disables scheduled workflows in public repos after 60 days with no repository activity. The bot's own
  commits are activity, but if it is ever disabled: Actions tab -> tick -> Enable workflow.

**Stop it:** Actions tab -> tick -> "..." -> Disable workflow.

## Files
- `skill/`: the skill's tools, unchanged (scan, entry, exit, size, check, timemachine) + LICENSE + SOURCE.json
- `daytrade/engine.py`: the bar-by-bar engine (fills, exits, the decision chain); `daytrade/universe.txt`: the 234 stocks
- `live/tick.py`: one live tick; `live/schedule.py`: the backup ticker's clock
- `research/`: `fetch_history.py`, `backtest.py`, `dry_run_last_session.py`
- `tests/`: `python -m unittest discover -s tests`

Run locally (Python 3.11, no packages needed): `python live/tick.py`, `python research/fetch_history.py && python research/backtest.py`.

Not financial advice. Paper results don't predict real results, and most day traders lose money.
