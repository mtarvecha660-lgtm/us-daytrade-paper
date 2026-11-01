# Backtest results (small sample: read with care)

**Run:** `python research/fetch_history.py && python research/backtest.py` on 2026-11-01, raw output in
`research/backtest_result.json`. The backtest uses the SAME engine and the same frozen `config.json` as the live bot.

**Data:** Yahoo's free 5-minute bars, which only go back about 60 days: **2026-08-07 to 2026-10-30,
60 sessions**, regular hours only. 233 of the skill's 234 example stocks had data (SQ returned no data;
Block now trades as XYZ). Start: $10,000 virtual.

## Headline (1R target, the frozen setting)
| | Bot | Just hold SPY |
|---|---|---|
| Return after costs | **-4.21%** | -2.02% |
| Max drawdown (end of day) | -8.67% | -3.05% |
| Sharpe (daily, annualised) | -1.14 | -0.81 |
| Sortino | -1.67 | -1.11 |

| Trades | |
|---|---|
| Closed trades | 133 (on 60 of 60 days) |
| Win rate | 46.6% |
| Average R per trade | -0.078R (t = -1.02: not different from zero) |
| Profit factor | 0.89 |
| Net P&L | $-421.01 |
| Average win / loss | $55.68 / $-54.55 |
| Slippage paid | $305.75 (no commission) |
| Exits | 47 target, 46 stop, 40 flat at 3:55 PM |

By month:

| Month | Trades | Win rate | Net P&L |
|---|---|---|---|
| 2026-08 | 35 | 43% | $+122.62 |
| 2026-09 | 47 | 43% | $-492.31 |
| 2026-10 | 51 | 53% | $-51.32 |

## Checks on the same data (not the frozen setting)
| Variant | Return | Trades | Avg R |
|---|---|---|---|
| Frozen: 1R target, 2 bps slippage | -4.21% | 133 | -0.078R |
| Same, zero slippage | -1.37% | 133 | -0.036R |
| 2R target (the skill's default in trader-exit) | -4.58% | 102 | -0.093R |

These variants were run AFTER the 1R setting was chosen (the brief and the skill's reel example use 1R) and do not
change it. They show the result is not an artefact of one cost or target assumption: none of them makes money.

## What this does and doesn't say
- **No edge showed up.** About half the trades won, wins and losses were the same size, and slippage turned a
  roughly break-even rule into a loss. SPY also fell over these weeks, and the bot fell more.
- **It is a small, single-regime sample.** 60 sessions, about 133 trades, one market phase (Aug to Oct 2026). One
  month (Sep) did most of the damage. A different 60 days could look quite different.
- **It is fragile.** While building it, a draft with a sizing mismatch (position cap measured against $10,000
  instead of the current cash) traded a slightly different set of stocks and ended at +1.7% instead of -4.2%.
  Small rule details move the result by several percent, which is what noise looks like.
- **Selection bias in the stock list.** The 234 stocks are the skill's own example list, saved on 2026-10-19, inside
  this window. Popular, heavily traded names; it was not picked for this test, but it was picked with hindsight.
- **Fills are modelled, not real**: next 5-minute bar's open plus slippage; stop first when a bar touches both stop
  and target; no partial fills.
- **The time-machine replay (trader-timemachine) was skipped.** It is a per-trade odds estimate for a human, needs
  60 days of history before each trade (so it can't be run fairly inside a 60-day backtest), and doesn't change the
  skill's rules. Leaving it out keeps the live bot and the backtest identical.

**Bottom line:** the backtest gives no reason to expect profits. The forward paper test (EVALUATION.md) is the
real experiment.
