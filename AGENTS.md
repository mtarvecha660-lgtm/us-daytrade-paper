# AGENTS.md

US day-trade PAPER bot. Paper only: never add broker keys, order code, or the skill's trader-broker.

- The skill's tools in `skill/` are vendored UNCHANGED (a test checks their hashes). Don't edit them.
- Settings in `config.json` are frozen by EVALUATION.md. A change means a new `version` (a new account, fresh clock):
  move `live/state/` aside, don't edit files under `live/state/` by hand.
- Run `python -m unittest discover -s tests` after any change, and `python research/dry_run_last_session.py`
  after touching `daytrade/engine.py` or `live/tick.py` (live replay must match the backtest).
- Pull before you push: the bot commits every ~5 minutes in market hours.
