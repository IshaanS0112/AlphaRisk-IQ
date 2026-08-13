# Price data

Two folders, two provenances, and the difference is enforced in code rather than
left to a naming convention.

```
historical_prices/
├── REAL_MARKET_DATA/<UNIVERSE>/     downloaded; gitignored
│   ├── _manifest.json
│   └── RELIANCE.NS.csv, ...
└── SYNTHETIC/<UNIVERSE>/            committed
    ├── _manifest.json
    └── RELIANCE.NS.csv, ...
```

Every folder must contain a `_manifest.json` declaring its `provenance`. The
loader refuses a folder without one, and refuses a manifest whose declared
provenance disagrees with the folder it sits in — a mislabelled provenance is
worse than no provenance, because everything downstream trusts it.

Provenance is then carried on **every database row**, aggregated into every risk
result's `calculation_basis`, surfaced as a banner in the UI, and written into
the context the report model is given. There is no code path that produces a risk
number without knowing where its prices came from.

`REAL_MARKET_DATA` is preferred whenever both are present.

## Getting real data

```bash
pip install -r backend/requirements-data.txt
python backend/scripts/fetch_prices.py --universe NSE_INDIA --years 5
python backend/scripts/fetch_prices.py --universe US --years 5
```

Daily **adjusted** closes from Yahoo Finance via `yfinance`. Adjusted, not raw:
raw closes put a fake −50% return in the series on the day of a 2:1 split, and a
single such day in a two-year window is enough to become the tail of a 95% VaR
estimate.

Yahoo Finance is free, unofficial, and occasionally wrong about corporate actions
on Indian tickers in particular. That is adequate for this project and it is not
what a desk would use — the honest framing is "Yahoo Finance daily adjusted
closes via yfinance, a free unofficial feed; a production system would use
exchange end-of-day files or a licensed vendor."

Real data is **gitignored**. It is someone else's data, it goes stale, and the
fetch script regenerates it in thirty seconds.

## The synthetic fixture

Committed, so that `pytest`, CI, and a first clone all work with no network
access and no data licence.

**It is not market data.** It is draws from a single-factor model with a
regime-switching market factor and Student-t innovations, described in full in
`backend/scripts/generate_synthetic_prices.py` and in each `_manifest.json`. Every
risk figure computed from it demonstrates the arithmetic and says nothing about
any real asset.

Three properties are deliberate, because the demo depends on them:

- **Fat tails that survive aggregation.** Student-t innovations alone are not
  enough — a portfolio is a weighted sum, and sums of independent heavy-tailed
  variates tend towards normal. What survives is a shock common to every holding,
  which is what the volatility regime supplies.
- **Volatility clustering.** The regime is persistent, so breaches arrive in runs.
  That is what makes the VaR backtest's clustering statistics say something.
- **Negative skew.** The stress regime carries a negative drift, so the left tail
  is heavier — which is what makes the two Sortino conventions visibly disagree.

Regenerate with:

```bash
python backend/scripts/generate_synthetic_prices.py
```

It is byte-identical every time, and CI fails if it is not.
