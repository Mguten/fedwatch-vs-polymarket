# FedWatch replication vs. Polymarket

A from-scratch replication of CME's FedWatch methodology — converting Fed
funds futures (ZQ contract) prices into market-implied probabilities for
FOMC rate decisions — built to answer a question CME's own tool doesn't:
how does that probability compare to an independent market pricing the
same event? [Polymarket](https://polymarket.com) runs prediction markets
on FOMC decisions, so this project builds the FedWatch-style engine from
raw futures data, validates it against CME's own published methodology,
and compares its output to Polymarket's prices over time.

## Key findings

Measured over 21 settled FOMC meetings (2023–2026), within a 90-day
pre-meeting window (see [`docs/STRATEGY.md`](docs/STRATEGY.md) for why 90 days,
and the full methodology behind every number below):

- **Better calibrated.** Lower (better) Brier score than Polymarket in
  15/21 meetings — about 15% lower on average, 4% lower at the median
  (the mean is pulled up by one unusually surprising meeting).
- **Leads in time.** A small but statistically robust lead over
  Polymarket — a median of roughly 1–3 days depending on the probability
  threshold used, confirmed by two independent methods (threshold-crossing
  and cross-correlation, which peaks at a +2-day lag). This lead-time
  effect is statistically more robust than the calibration difference
  itself (p < 0.01 across three separate significance tests, vs. a
  borderline result for calibration) — an asymmetry the writeup explains
  rather than glosses over.
- **The likely mechanism:** because our model tends to flag its leading
  outcome before Polymarket's price fully catches up, it implies a
  cheaper average entry price for the equivalent position. A control
  experiment — rerunning the same trading rules using Polymarket's own
  price as the signal instead — performs almost as well, which is the
  honest reason a naive backtest of this idea looks "too good to be
  true": FOMC decisions in this period were unusually well-telegraphed,
  not necessarily because this model is exceptionally skilled.
- **A backtest with zero losing meetings is a red flag, not a selling
  point** — and it's explained, not hidden: it traces to one specific
  behavior (the position that survives to a meeting's resolution wins
  21/21 in this sample), while the noisier, real-loss-bearing part of the
  strategy (positions closed early when a different outcome takes the
  lead) is exactly where the visible variance is. Details, plus every
  other caveat (small n, single regime, no transaction costs, no
  out-of-sample validation) are in [`docs/STRATEGY.md` §7–9](docs/STRATEGY.md).

This is a research project, not investment advice.

## How it works

| Stage | What it does |
|---|---|
| **Data ingestion** | Reads raw ZQ (Fed funds futures) contract prices from local CSV files, one per contract month. |
| **FOMC calendar** | Scrapes meeting dates from federalreserve.gov (with a static CSV fallback); actual decisions are derived from FRED (`DFEDTARU`/`DFEDTARL`), not hand-maintained. |
| **Deconvolution engine** | The core: decomposes each contract's implied rate into an integer + mantissa step per CME's published methodology, and convolves that forward across the full meeting sequence to get a probability distribution per meeting. Validated against CME's own worked example ([regression-tested exactly](fedwatch/deconvolution/), independent of any external data file). |
| **CME validation** | Compares engine output against CME's own historical FedWatch probabilities where that data is available, at a pre-declared tolerance. |
| **Polymarket integration** | Pulls FOMC-related markets from Polymarket's public APIs, builds a candidate match table against FOMC meetings, which is manually reviewed before use (automated question-text matching alone isn't reliable enough to trust blindly). |
| **Comparison** | Produces a time series of both models' probabilities for every matched meeting/outcome, ready for analysis. |
| **Live notifications** | Optional: a daily check (local cron, not GitHub Actions — see below) that messages Telegram when a live signal qualifies under the entry rule in `docs/STRATEGY.md`. |

## Quickstart

```bash
pip install -r requirements.txt

# Run the full pipeline for a given date (defaults to today)
python scripts/run_pipeline.py [YYYY-MM-DD] [--skip-validation]

# Run the trading-strategy backtest (see docs/STRATEGY.md for the rules)
python scripts/run_backtest.py [threshold ...]   # defaults to 50/60/70%

# Run the test suite (66 tests, no network access required)
python -m pytest tests/ -v
```

The first pipeline run generates `config/polymarket_fomc_match_review.csv`
and stops there — review it by hand (fill in `TRUE`/`FALSE` in the
`confirmed` column), then run again to get the full comparison output in
`output/fedfunds_vs_polymarket.csv`.

**Note on data:** `Data/` (raw ZQ contract prices + CME's historical
export) is gitignored — its redistribution licensing hasn't been checked,
so it's kept out of this public repo. `tests/` ships with CSV fixtures
so the test suite runs without it; running the full pipeline yourself
requires sourcing that contract data separately.

## Live notifications (optional)

`scripts/run_notify.py` checks daily whether any FOMC meeting's leading
outcome qualifies for entry under `docs/STRATEGY.md` §4, and sends a Telegram message
if so. This reads live data from investing.com rather than the ZQ
pipeline (see `fedwatch/livesource/investing.py` for why — CME's own
tool is behind bot protection that isn't practical to get around without
techniques this project deliberately avoids).

Scheduling is done via **local cron, not GitHub Actions** — investing.com
returns 403 specifically to GitHub-hosted runners' IP ranges, confirmed by
actually running the workflow. Rather than working around that with
proxies or IP rotation, the notifier just runs locally:

```bash
cp .env.example .env   # fill in TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
crontab -e
# add:
0 8 * * * /path/to/FF_rates/scripts/run_notify_cron.sh
```

`scripts/run_notify_cron.sh` loads `.env` (cron doesn't inherit your
interactive shell environment) and logs to `output/notify.log`.

To get a bot token: talk to [@BotFather](https://t.me/BotFather) on
Telegram (`/newbot`), then send your new bot any message and visit
`https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` to find your
`chat_id` in the response.

## Trading strategy

The rules used for the backtest and live notifier — entry/exit
conditions, Kelly-based position sizing, and every known limitation — are
formalized in [`docs/STRATEGY.md`](docs/STRATEGY.md). Nothing in this codebase
executes the strategy automatically against real money; it's a
research/paper-trading rule set, not a broker integration.

## Environment

Standard Python + pandas. See `requirements.txt`.
