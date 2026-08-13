# Architecture

## Shape

```
React + TS + Tailwind  ──►  FastAPI  ──►  PostgreSQL
                                │
        ┌──────────┬────────────┼─────────────┬──────────────┐
        ▼          ▼            ▼             ▼              ▼
   returns.py  risk_calc.py  var_engine.py  var_backtest  stress_engine
   align &     Sharpe,       hist + param   rolling       OLS betas,
   weight      Sortino x2,   VaR + ES       Kupiec POF    scenario repricing
                drawdown
                                │
                                ▼
                        report_generator.py
                   structured context ──► Claude ──► citation validation
                            │                              │
                            └──────► template fallback ◄────┘
```

Every arrow into the report generator carries **already-computed numbers**. No
arrow runs the other way. That is the one architectural constraint the rest of the
design exists to enforce.

---

## What's real and what's simulated

### Real — all of it, in the sense that matters

Every calculation in this system is a real implementation of a published
definition, run on whatever data is loaded:

- **Sharpe, Sortino, downside deviation, drawdown, diversification ratio** —
  arithmetic, no approximations, both Sortino conventions verified against closed
  forms in the test suite.
- **Historical VaR** — empirical quantile of the realised return distribution.
- **Parametric VaR and ES** — normal quantile and its closed-form tail
  conditional mean. The z-score is *solved* at import time from `erf` by
  bisection, not transcribed, and asserted against published tables.
- **Kupiec proportion-of-failures test** — the published likelihood-ratio
  statistic, with the chi-square(1) p-value from the closed form
  `erfc(sqrt(x/2))`. The rolling backtest is genuinely out of sample and the test
  suite re-derives the thresholds to prove it.
- **OLS betas** — `Cov(r_i, r_m)/Var(r_m)` with R², checked against known
  generating betas.
- **Stress scenarios** — magnitudes recomputed from transcribed published index
  closing levels on every request. Nothing is a hard-coded percentage.

### Simulated — the default price series, and it says so everywhere

The price data committed to this repository is **synthetic**, and this is the one
thing in the project that is not real. It is worth being precise about why it is
here and what has been done to make it impossible to mistake for market data.

**Why:** `pytest`, CI and a first clone must work with no network access and no
data licence. A repo whose test suite requires a Yahoo Finance call is a repo
whose test suite does not run.

**What stops it passing as real:**

- It lives under `data/historical_prices/SYNTHETIC/`, never anywhere else.
- Every folder carries a `_manifest.json` with `provenance: SYNTHETIC` and a
  `WARNING` field beginning "THESE ARE NOT MARKET PRICES".
- The loader **refuses** a price folder with no manifest, and **refuses** a
  manifest whose declared provenance disagrees with the folder it sits in.
- Provenance is stored on **every single return row**, not on the ticker — a
  universe can be half loaded and the aggregate comes back as `MIXED`.
- It is aggregated into every `risk_metrics.calculation_basis`.
- It becomes a yellow banner in the UI on every portfolio page.
- It is injected into the structured context the report model receives, and the
  system prompt requires the headline to say so. The deterministic fallback
  prefixes its headline with `[SYNTHETIC DATA]`.

**How it is generated**, in full, so nobody has to reverse-engineer it:

```
s(t)    in {calm, stress}, a two-state Markov chain
r_m(t)  = mu(s) + sigma_m * k(s) * T_nu(t)                 market factor
r_i(t)  = alpha_i + beta_i * r_m(t) + sigma_i * T_nu(t)    each asset
```

`T_nu` is Student-t with 5 degrees of freedom standardised to unit variance;
`k(s)` is a volatility multiplier renormalised so the unconditional variance is
unchanged by the regime switch.

Four design decisions, each for a reason:

1. **A real factor structure**, so betas are known inputs and the OLS estimator
   can be checked against ground truth.
2. **Fat tails that survive aggregation.** This is the non-obvious one. Student-t
   innovations alone are not enough: a portfolio is a weighted sum, and sums of
   independent heavy-tailed variates get *closer* to normal — the central limit
   theorem does not care that you wanted fat tails. What survives is a shock
   common to every holding, which is exactly what the volatility regime supplies.
   I found this out by building it the naive way first and watching the portfolio
   kurtosis collapse.
3. **Volatility clustering**, because the regime is persistent (a stress spell
   lasts ~10 days). Without it, breaches arrive independently and the backtest's
   clustering statistics would imply Christoffersen's test is unnecessary — a
   misleading thing for the demo to say.
4. **Negative skew**, from a negative drift in the stress state. Real equity
   returns are negatively skewed, and a symmetric fixture would make the two
   Sortino conventions agree more closely than they should.

**Also approximate, and flagged as such:** the risk-free rates in
`data/universes/universes.json` carry
`risk_free_status: APPROXIMATE_PLACEHOLDER_VERIFY_BEFORE_QUOTING`. The value used
is recorded in every result's `calculation_basis`, so a corrected rate is a
one-line change and the affected results are identifiable.

**The scenario index levels are transcribed**, and transcription is a step where
errors happen. Each carries
`verification_status: TRANSCRIBED_FROM_PUBLISHED_INDEX_CLOSES`. They are stored as
levels rather than percentages precisely so that verifying them means checking two
published closing prices, and so a correction propagates everywhere from one edit.

---

## Design decisions worth defending

### Storing scenarios as levels, not percentages

A magnitude asserted as `-38%` is unfalsifiable. Stored as "1468.36 on 2007-12-31
→ 903.25 on 2008-12-31" it is checkable in thirty seconds, and the derivation
string is returned by the API next to the number. A test asserts the arithmetic;
CI runs it.

The side benefit is that it forces the calendar-year/peak-to-trough distinction
into the open. Both are real 2008 S&P 500 figures (−38.49% and −56.78%) and they
describe different things.

### Every result carries its own `calculation_basis`

Window bounds, observation count, risk-free rate and its basis and as-of date,
MAR, trading-day count, ddof, quantile interpolation method, drift inclusion,
per-ticker weights, rebalancing convention, alignment policy, and provenance.

The point is falsifiability. A Sharpe ratio without these is not a reproducible
number, and a system that produces unreproducible numbers is a system whose
outputs cannot be argued with — which sounds like a strength and is the opposite.

### `/methodology` as an endpoint

The claim "these figures are computed, not generated" is only checkable if the
formulas and conventions are visible without reading the source. So they are an
endpoint, and the frontend has a page that renders them.

### Metrics come back `null` with a reason, not as a number

Sortino on a sample with three losing days is a large number divided by noise. The
engine returns `null` and an `omitted_metrics` entry saying *"Only 3 of 500
observations fell below the minimum acceptable return, against a floor of 5. A
downside deviation estimated from a handful of points is noise, and dividing by a
near-zero denominator would produce a large Sortino ratio that means nothing."*

The same applies to VaR at a confidence level the sample cannot support: the
figure is returned with a note saying it is resting on a handful of tail
observations.

### Universes bind four things that must agree

Ticker list, benchmark index, trading-day count, risk-free rate. Letting those be
set independently is how an NSE portfolio ends up with a US T-bill rate in its
Sharpe ratio and an S&P 500 drawdown in its stress test — both of which produce
numbers that look completely normal and mean nothing. Cross-universe scenarios are
refused with a 422 and an explanation.

### Appending results, never updating

Re-running after loading more history leaves the earlier row in place. "The VaR
moved when we extended the window from one year to three" is the finding.

### JSONB and UUID as SQLAlchemy dialect *variants*

Postgres is the deployment target, but declaring the variants means the same
models load under SQLite — so the API integration tests run the real app on a
fresh clone with no container up. Without that, the HTTP layer is the one nobody
ever tests.

### `create_all` instead of Alembic

Adequate because the V1 schema is append-only. A migration tool is the correct
answer the moment a column needs to change shape, and this note is here so that
choice is visibly a choice.

---

## Lessons learned

**A number can be right and still be wrong.** The single most useful thing I did
here was check the claim I had been handed — "fat tails, therefore historical VaR
exceeds parametric VaR" — instead of implementing it. It is true at 99% and false
at 95%, because a leptokurtic distribution has a more peaked *body* as well as
fatter extremes and the variance is fixed, so the two must trade off. If I had
built the naive version, the demo portfolio would have shown parametric above
historical at 95% and I would have had no explanation for it in an interview. Now
that inversion is the most interesting thing in the output.

**Expected shortfall earned its place by accident.** I added it as a small bonus.
It turned out to be the thing that resolves the crossover: at 95% the VaR
comparison and the ES comparison point in *opposite directions* on the same data,
and understanding why that is not a contradiction is the clearest way I know to
explain what the two measures actually do.

**The central limit theorem does not care what you wanted.** My first fixture used
Student-t innovations per asset and the portfolio came out nearly normal, because
sums of independent heavy-tailed variates converge. Fat tails at the portfolio
level require a *common* shock. That is not a quirk of the fixture — it is why
diversification stops working in a crisis, and I would not have understood it
properly if the simulation had happened to work first time.

**Floating point ate a guard clause.** `np.std` of a constant array is about
1e-19, not 0.0, so `if sigma > 0` never fired and a degenerate portfolio returned
a Sharpe ratio of 7.28e16 instead of `null`. A number that large is obvious to a
human and completely invisible on a chart axis. Found by a test that asserted the
*omission* rather than the value — the guard clauses need tests as much as the
formulas do.

**`hash()` is not a seed.** Python randomises string hashing per process unless
`PYTHONHASHSEED` is pinned, so my "reproducible" fixture regenerated differently
every run. It is `zlib.crc32` now, and CI regenerates the fixture and fails on any
diff. This class of bug is invisible until someone tries to reproduce a published
number, which is the worst possible moment.

**Closed-form tests are worth the effort.** Asserting that downside deviation
converges to `sqrt(1/2)·sigma` on a large normal sample proves the code implements
Sortino's definition. Asserting it equals 0.00981 only proves nobody has touched
it. The second kind of test passes forever while the code is quietly wrong.

**Publishing the conventions changed the design.** Once `/methodology` had to
return every parameter, it became obvious that no parameter could live as a
literal inside a function. Everything moved into `config.py` with a validator, and
the code got better as a side effect of having to explain itself.

---

## V2, in priority order

1. **Christoffersen conditional-coverage test** — the independence half of VaR
   backtesting. The clustering statistics are already computed, so this is mostly
   the likelihood ratio.
2. **Monte Carlo VaR** — with an explicit, defensible return-generating process
   (bootstrapped historical, then a t-copula) rather than a silent normal.
3. **Mean-variance optimisation** — suggest weights rather than only analyse
   given ones, with the estimation-error caveat stated loudly.
4. **Multi-period stress with a path** — the 2020 drawdown took 23 trading days
   and 2008 took 17 months. A single-shock model treats them identically, and
   speed matters as much as depth for anything with a liquidity constraint.
5. **Buy-and-hold weight drift** as an alternative to daily-constant-weight
   rebalancing.
6. **Alembic**, the first time a column needs to change shape.
