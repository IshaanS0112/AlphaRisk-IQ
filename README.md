# AlphaRisk IQ

[![CI](https://github.com/IshaanS0112/AlphaRisk-IQ/actions/workflows/ci.yml/badge.svg)](https://github.com/IshaanS0112/AlphaRisk-IQ/actions/workflows/ci.yml)
[![Python 3.10-3.13](https://img.shields.io/badge/python-3.10--3.13-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Portfolio risk and decision intelligence. Sharpe and Sortino under both downside
conventions, historical and parametric Value at Risk with expected shortfall,
Kupiec-tested VaR backtesting, and beta-adjusted scenario stress testing against
index drawdowns derived from cited closing levels.

FastAPI · PostgreSQL · React + TypeScript + Tailwind · Docker · Claude

---

## Why I built it

I got interested in risk management from the wrong end: I wanted to know why two
people can compute "the Sharpe ratio" of the same portfolio and get different
numbers, and neither of them is wrong. The answer turned out to be that a Sharpe
ratio is not a fact about a portfolio. It is a fact about a portfolio *under a
stated window, risk-free rate, trading-day count and standard-deviation
convention*, and almost nobody states any of them.

That is the idea the whole project is built around. Every figure it produces
carries the conventions it was computed under, `GET /methodology` republishes all
of them, and every stored result has a `calculation_basis` you can reproduce the
number from. Where a metric can't be computed honestly, it comes back as `null`
with a reason instead of as a number that looks like an answer.

Along the way I found that one of the things I had been told about VaR is only
true half the time. That is written up below, because working it out was the most
useful thing I did here.

---

## What it computes

| | |
|---|---|
| **Return & volatility** | Arithmetic and geometric annualised return, daily and annualised volatility, maximum drawdown with its dates |
| **Risk-adjusted** | Sharpe; Sortino under **both** the standard and the negative-only downside-deviation conventions, side by side |
| **Value at Risk** | Historical and parametric, at 95% and 99%, as positive loss magnitudes |
| **Expected Shortfall** | Historical and parametric, at 95% |
| **Model validation** | Rolling out-of-sample VaR backtest with Kupiec's proportion-of-failures test and breach-clustering statistics |
| **Stress testing** | Uniform and beta-adjusted repricing under six crisis scenarios plus custom shocks, decomposed per holding |
| **Diversification** | Diversification ratio and pairwise correlation structure |
| **Narrative** | An LLM report that narrates over the computed figures and computes nothing |

---

## Quick start

Needs **Python 3.10-3.13** (not 3.14 - the pinned wheels don't reach it yet) and
Node 18+. No database, no Docker, no API key.

Terminal 1 - sets up the venv, installs, runs the tests, starts the API on
http://localhost:8000:

```bash
git clone https://github.com/IshaanS0112/AlphaRisk-IQ && cd AlphaRisk-IQ
./dev.sh
```

Terminal 2 - the dashboard on http://localhost:5173:

```bash
cd frontend && npm install && npm run dev
```

`dev.sh` selects a supported interpreter, creates the virtualenv, installs, runs
the test suite and starts the API. Manual setup, configuration and troubleshooting
are in **[`docs/development.md`](docs/development.md)**.

The whole stack on PostgreSQL: `docker compose up --build`.

The synthetic price fixture ships with the repository, so everything above works
on a fresh clone with no network access. For real numbers:

```bash
pip install -r backend/requirements-data.txt
python backend/scripts/fetch_prices.py --universe NSE_INDIA --years 5
```

Then POST `/market-data/load` again — real data is preferred automatically, and
the synthetic-data banner disappears from the UI.

---

## The thing I got wrong, and then got right

The standard framing, repeated in most textbooks and every tutorial I read while
building this, is:

> Parametric VaR assumes returns are normally distributed, which underestimates
> tail risk — real financial returns have fatter tails than a normal
> distribution — so historical VaR comes out larger.

The first clause is right. The conclusion is only right at high confidence
levels, and the level where it flips sits inside the range people routinely
quote.

A fat-tailed distribution with the same variance as a normal does not have more
mass everywhere in the tail. Variance is fixed, so fatter extremes have to be paid
for somewhere — and they are paid for with a **more peaked body**. For a Student-t
with 5 degrees of freedom standardised to unit variance:

| confidence | standardised t(5) | normal | which is worse |
|---|---|---|---|
| 95.0% | −1.561 | −1.645 | **normal** |
| 97.5% | −1.991 | −1.960 | t |
| 99.0% | −2.606 | −2.326 | t |

So on genuinely fat-tailed data, a 95% VaR comparison can show parametric *above*
historical — and reading that as "this portfolio has thin tails" is exactly
backwards. The demo portfolio does precisely this:

```
             VaR historical   VaR parametric   ratio       ES historical   ES parametric   ratio
95%             1,79,733         2,02,202      0.89×          3,26,276        2,55,194      1.28×
99%             4,87,382         2,88,628      1.69×          5,98,081        3,31,603      1.80×
```

Read the 95% row across. VaR says the normal fit is **conservative by 11%**.
Expected shortfall, on the same data at the same confidence level, says it is
**optimistic by 28%**. Both are correct, and the disagreement is the whole point:
VaR reads a single point off the distribution and ES averages everything beyond
it, so the normal fit can be conservative about *where* the threshold sits and
badly wrong about *what happens past it*.

That is also the cleanest argument for why Basel III moved market-risk capital
from VaR at 99% to Expected Shortfall at 97.5%.

The engine reports the ratio at every confidence level, never asserts a direction,
and says so in the output. The closed-form quantiles in that table are asserted in
`tests/test_var_engine.py`, so the documentation is tested too.

---

## The other places the conventions actually matter

**Sortino's denominator.** The definition Frank Sortino published is

```
downside_deviation = sqrt( (1/N) * sum over ALL i of min(r_i - MAR, 0)^2 )
```

Deviations from the **minimum acceptable return**, not from the sample mean, and
divided by **N**, not by the count of losing days. The version that circulates
widely — "the standard deviation of the negative returns" — differs on both
counts, and the two differences push in opposite directions:

```
For N(0, sigma) with MAR 0:
  Sortino's definition   ->  sqrt(1/2)     * sigma  =  0.7071 * sigma
  negative-only std dev  ->  sqrt(1 - 2/pi) * sigma  =  0.6028 * sigma
```

On a symmetric sample the shortcut gives the smaller denominator and flatters the
ratio by about 17%. Add left skew — which real equity returns have — and the
ordering reverses. Both closed forms are asserted in the test suite. The app
reports both figures side by side rather than picking one and hoping.

**Simple returns, not log returns.** A portfolio's simple return is the weighted
sum of its holdings' simple returns. Log returns are additive across *time*, not
across *assets*, so `sum(w_i * log_r_i)` is a number with no interpretation.

**Dates are intersected, never forward-filled.** A filled close enters the series
as a 0% return and drags measured volatility down, which makes the portfolio look
safer than it was.

**Geometric de-annualisation of the risk-free rate**, `(1+rf)^(1/T) - 1`, not
`rf/T`. The difference is a millionth of a percent a day, so this is not about
accuracy — it is that "why did you divide?" is a question with no good answer.

---

## VaR backtesting, which is the part most projects skip

Anyone can compute a VaR. The question that turns a number into a *model* is
whether it was right, and the standard answer is breach counting: a calibrated
95% VaR should be exceeded on about 5% of days.

The test here is **out of sample**. On each day the threshold is re-estimated on
the trailing 250 observations only, then compared against the next day's realised
return, which the estimate has never seen. Estimating the threshold on the whole
sample and counting breaches within it is circular and passes by construction —
"was it in sample?" is the first thing to ask of any backtest result. The test
suite re-derives the thresholds independently and asserts the breach count
matches, which is the check that no lookahead crept in.

Kupiec's proportion-of-failures statistic turns the count into a hypothesis test:

```
LR_POF = -2 * ln[ ((1-p)^(N-x) * p^x) / ((1-x/N)^(N-x) * (x/N)^x ) ]   ~ chi-square(1)
```

Rejected above 3.841 at 95%. The p-value comes from `erfc(sqrt(x/2))`, the closed
form of the chi-square(1) survival function, so there is no scipy dependency and
no lookup table.

**What Kupiec does not test, said before anyone asks:** the *timing* of breaches.
A model that breaches five times in five consecutive days during one crisis passes
it exactly as cleanly as one that breaches five times spread across a year — and
the first is far more dangerous, because clustered breaches are what wipe out a
book. Christoffersen's conditional-coverage test is the right tool and is a
documented V2; the clustering statistics (longest run, adjacent breaches) are
reported so the gap is visible in the output rather than hidden.

---

## Stress testing, with betas estimated rather than assumed

Scenarios are stored as **the two index closing levels the magnitude is derived
from**, never as a percentage. The percentage is recomputed at load time and a
test asserts the arithmetic.

That is deliberate. A scenario asserted as `-38%` cannot be checked by anyone,
including its author six months later. A scenario stored as "the S&P 500 closed at
1468.36 on 2007-12-31 and 903.25 on 2008-12-31" can be checked in thirty seconds
against any data provider, and correcting one level corrects every figure
downstream of it.

It also forces a distinction that gets blurred constantly:

| scenario | index | basis | magnitude |
|---|---|---|---|
| `gfc_2008_calendar_year` | S&P 500 | calendar-year price return | **−38.49%** |
| `gfc_peak_to_trough` | S&P 500 | peak-to-trough drawdown | **−56.78%** |
| `covid_crash_2020` | S&P 500 | peak-to-trough drawdown | −33.92% |
| `gfc_2008_calendar_year_nifty` | NIFTY 50 | calendar-year price return | −51.79% |
| `gfc_peak_to_trough_nifty` | NIFTY 50 | peak-to-trough drawdown | **−59.86%** |
| `covid_crash_2020_nifty` | NIFTY 50 | peak-to-trough drawdown | −38.44% |

The first two are both real 2008 S&P 500 figures. They describe different things,
and quoting one while describing the other is the most common piece of sloppiness
in this area. All six levels are transcribed from published index closes and
labelled `TRANSCRIBED_FROM_PUBLISHED_INDEX_CLOSES` — verify them against your own
data provider before quoting any of them, and if one is wrong, fix it in
`data/scenarios/scenarios.json` and everything downstream moves with it.

**Two shock modes.** `UNIFORM` applies the index shock to every holding, which
implicitly assumes every beta is exactly 1. `BETA_ADJUSTED` estimates each
holding's beta by OLS against the universe benchmark and shocks it by
`beta_i × index_shock`. On the demo portfolio:

```
GFC peak-to-trough (NIFTY 50, -59.86%), 1,00,00,000 notional

  UNIFORM          -> 40,14,409   (-59.86%)
  BETA_ADJUSTED    -> 39,31,316   (-60.69%),  portfolio beta 1.014

  estimated betas:  HDFCBANK 1.30 | LT 1.21 | RELIANCE 1.05 | TCS 0.90 | ITC 0.65
```

**The limitation, stated before anyone else states it:** beta is estimated on a
calm sample and applied to a crisis, and in a crisis betas and correlations both
converge towards 1. Precisely when diversification is supposed to help, it stops
helping. So a beta-adjusted stress test fitted on recent data will *understate*
the loss on a low-beta portfolio in a 2008-style event. That is not a reason to
skip the beta estimate — it is a reason to report both modes and treat the uniform
number as the pessimistic bound, which is what the app does.

---

## The AI report computes nothing

1. Every figure the report may mention is assembled from rows already in the
   database and written to `investment_reports.structured_context` **before** the
   API call is made — so it exists even if the call fails.
2. The prompt hands over that dict and forbids arithmetic.
3. Every metric key the model cites must exist in the context. Invented keys are
   stripped and recorded in `dropped_citations`, because a model inventing a
   metric key is exactly the failure this architecture exists to catch.
4. With no API key, or on any failure, the same report is produced
   deterministically from the same context. Every number is identical; only the
   prose is missing.

The UI has a button that dumps the exact payload the model was given, so the
narrative can be diffed against it.

> *"The model doesn't calculate VaR or Sharpe — my code does, with the formulas at
> `/methodology`. The model writes the narrative interpretation, and I can show
> you the exact structured payload it was given, because it's stored on the report
> row."*

---

## Data

Two universes, because the universe is what decides the benchmark for beta
estimation, the risk-free rate, the trading-day count, and which crisis magnitudes
are meaningful. Applying an S&P 500 drawdown to an NSE portfolio is refused with a
422.

- **NSE_INDIA** — 8 NIFTY 50 constituents, benchmark `^NSEI`, 250 trading days,
  INR
- **US** — 6 S&P 500 constituents, benchmark `^GSPC`, 252 trading days, USD

Price series carry a `provenance` of `REAL_MARKET_DATA` or `SYNTHETIC` on **every
row**, aggregated into every result and surfaced as a banner in the UI and a
warning in the report. The loader refuses a price folder with no manifest, and
refuses a manifest whose declared provenance disagrees with the folder it sits in.

The committed fixture is synthetic and says so everywhere. It exists so that
`pytest`, CI and a first clone work offline. See
[`data/historical_prices/README.md`](data/historical_prices/README.md) for the
generating process and why it uses a regime-switching market factor rather than
plain Student-t innovations.

**Risk-free rates in `data/universes/universes.json` are approximate placeholders
marked `APPROXIMATE_PLACEHOLDER_VERIFY_BEFORE_QUOTING`.** Update them before you
quote a Sharpe ratio anywhere that matters; the value used is recorded in every
result's `calculation_basis`.

---

## API

```
GET    /health
GET    /methodology                             every formula, convention and parameter in force
GET    /universes                               tickers, benchmark, risk-free, what data is on disk
GET    /scenarios?universe=NSE_INDIA            magnitudes recomputed from index levels

POST   /market-data/load                        load a universe's price series
GET    /market-data/status                      what is loaded, with provenance

POST   /portfolios                              create (weights normalised, tickers validated)
GET    /portfolios  ·  GET /portfolios/{id}  ·  DELETE /portfolios/{id}

POST   /portfolios/{id}/compute-risk-metrics    Sharpe, Sortino, VaR, ES, backtests
GET    /portfolios/{id}/risk-metrics

POST   /portfolios/{id}/stress-test             named scenario or custom shock
GET    /portfolios/{id}/stress-tests

POST   /portfolios/{id}/generate-report
GET    /portfolios/{id}/investment-report
GET    /portfolios/{id}/report-status           whether a report would be narrated or templated
```

Each POST appends a row; each GET returns the latest. Appending is deliberate —
"the VaR moved when we extended the window from one year to three" is the finding,
not a detail to overwrite.

---

## Tests

```
156 passed
```

No network, no database container, no API key. Several assert against **closed
forms rather than golden numbers**: a test that says "downside deviation is
0.00981" only proves the code has not changed, while a test that says "for a large
normal sample it must converge to `sqrt(1/2)·sigma`, and the negative-only variant
to `sqrt(1-2/pi)·sigma`" proves the code implements the definition it claims to.

Worth knowing about a few of them:

- **`test_the_test_is_out_of_sample`** re-derives every rolling VaR threshold
  independently and asserts the breach count matches — the check that no lookahead
  crept into the backtest.
- **`test_the_generating_betas_are_recoverable_from_the_fixture`** checks the OLS
  estimator against the betas the fixture was *generated* with, turning "it
  returns a number" into "it returns the right number".
- **`test_the_fixture_is_byte_identical_when_regenerated`** exists because Python
  randomises string hashing per process, so a seed derived from `hash(str)` gives
  a different dataset on every run. CI fails if the fixture drifts.
- **`test_the_documented_magnitudes_still_hold`** is a tripwire on this README:
  edit an index level and it fails, because a documented magnitude has moved.
- **`test_every_number_in_the_fallback_appears_in_the_context`** is the report
  architecture expressed as an assertion.

CI runs four jobs: backend tests, fixture reproducibility, scenario validation,
and frontend typecheck + build.

---

## Deliberately not built

Published at `/methodology` rather than left to be discovered.

| | why not |
|---|---|
| **Monte Carlo VaR** | Historical and parametric cover the standard tradeoff. Monte Carlo needs a defensible return-generating process, and picking one badly is worse than not having it. |
| **Portfolio optimisation** | This analyses the weights it is given. Suggesting weights is a different product. |
| **Christoffersen independence test** | Kupiec tests breach *count*, not *timing*. The clustering statistics are reported; the formal test is V2. |
| **Options and Greeks** | Equity-only. Non-linear payoffs need a different engine, not a bigger one. |
| **Real-time market data** | Static historical files, loaded explicitly and versioned. |
| **Multi-period / liquidity-aware stress** | A one-shot repricing says nothing about path or liquidity. The 2020 drawdown took 23 trading days and 2008 took 17 months; this model treats them identically. |

---

## Repository

```
backend/app/services/
  returns.py             price -> aligned return matrix -> portfolio series
  risk_calculator.py     Sharpe, Sortino (both conventions), drawdown
  var_engine.py          historical + parametric VaR and ES
  var_backtest.py        rolling backtest, Kupiec POF
  stress_test_engine.py  OLS betas, scenario repricing
  scenarios.py           scenario library, magnitudes derived from levels
  universes.py           NSE / US definitions
  market_data.py         CSV loading with enforced provenance
  report_generator.py    structured context -> LLM -> validation -> fallback
backend/scripts/
  fetch_prices.py                 real data (yfinance)
  generate_synthetic_prices.py    the labelled fixture
frontend/src/                     PortfolioBuilder, RiskMetricsPanel, VarPanel,
                                  BacktestPanel, StressTestView, ReportView
data/                             universes, scenarios, price series
docs/development.md               setup, configuration, tests, CI
docs/architecture.md              design decisions, what's real vs simulated
docs/schema.sql                   the PostgreSQL reference schema
```

MIT licensed.
