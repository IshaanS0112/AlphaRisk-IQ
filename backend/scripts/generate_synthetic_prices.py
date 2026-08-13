#!/usr/bin/env python3
"""Generate the labelled synthetic price fixture.

**Read this before using any number this file produces.**

These are not market prices. They are draws from a single-factor model with
Student-t innovations, and they exist so that the test suite, CI, and a
first-clone demo can run with no network access and no data licence. Every file
written here lands under ``data/historical_prices/SYNTHETIC/``, every manifest
records ``provenance: SYNTHETIC``, and that flag is carried on every database row
and surfaced in every API response and every generated report. It is deliberately
difficult to look at output from this data and not know where it came from.

For real numbers run ``scripts/fetch_prices.py``, which downloads actual daily
adjusted closes and writes them under ``REAL_MARKET_DATA/``. The application
prefers real data whenever it is present.

**The generating process**, stated so nobody has to reverse-engineer it:

    s(t)    in {calm, stress}, a two-state Markov chain
    r_m(t)  = mu(s) + sigma_m * k(s) * T_nu(t)                the market factor
    r_i(t)  = alpha_i + beta_i * r_m(t) + sigma_i * T_nu(t)   each asset

with ``T_nu`` a Student-t variate standardised to unit variance and ``k(s)`` a
volatility multiplier normalised so the unconditional variance is still
``sigma_m^2``. Four properties are wanted and all four are deliberate:

* **A real factor structure.** Betas are inputs, so the stress engine's OLS
  estimates can be checked against a known truth. That turns the beta code from
  "it returns a number" into "it recovers the number it should".
* **Fat tails that survive aggregation.** Student-t innovations alone are not
  enough. A portfolio is a weighted sum of assets, and sums of independent
  heavy-tailed variates get *closer to normal* - the central limit theorem does
  not care that you wanted fat tails. What survives aggregation is a shock
  common to every holding, which is what the regime switch supplies: in the
  stress state every asset's volatility rises together, because they all load on
  the same market factor.
* **Volatility clustering.** The Markov chain is persistent (a stress spell lasts
  around ten days), so losses arrive in runs rather than independently. That is
  what real markets do, and it is what makes the VaR backtest's breach-clustering
  statistics show something - a fixture with i.i.d. returns would make
  Christoffersen's independence test look unnecessary, which would be a
  misleading thing for the demo to imply.
* **Negative skew.** The stress state carries a negative drift, so the left tail
  is heavier than the right. Equity returns are negatively skewed; a symmetric
  fixture would make the two Sortino conventions agree more closely than they
  should.

Nothing here is calibrated to any actual series. "Roughly the right magnitudes"
is the entire claim.
"""

from __future__ import annotations

import argparse
import json
import zlib
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
UNIVERSES_PATH = ROOT / "data" / "universes" / "universes.json"
OUT_ROOT = ROOT / "data" / "historical_prices" / "SYNTHETIC"

# Anchored so regeneration is byte-identical. Not "today" - a fixture whose
# contents depend on when it was generated is not a fixture.
ANCHOR_END = date(2026, 6, 30)
DEFAULT_YEARS = 5
DOF = 5.0

# Two-state volatility regime for the market factor. Transition probabilities are
# per trading day, so a stress spell lasts 1/0.10 = 10 days on average and the
# chain spends 0.02/(0.02+0.10) = 16.7% of its time in stress.
P_CALM_TO_STRESS = 0.02
P_STRESS_TO_CALM = 0.10
CALM_VOL_MULTIPLIER = 0.80
STRESS_VOL_MULTIPLIER = 2.20
STRESS_DAILY_DRIFT = -0.0020

# Per-sector factor loadings and idiosyncratic volatilities (daily). Set by hand
# to plausible magnitudes; see the module docstring on what that does and does
# not claim.
SECTOR_PROFILE = {
    "Financials": (1.25, 0.011, 0.00015),
    "Information Technology": (0.90, 0.010, 0.00025),
    "Energy": (1.05, 0.012, 0.00010),
    "Energy / Conglomerate": (1.05, 0.012, 0.00012),
    "Industrials / Infrastructure": (1.20, 0.012, 0.00018),
    "Consumer Staples": (0.65, 0.008, 0.00020),
    "Health Care": (0.70, 0.008, 0.00018),
}
DEFAULT_PROFILE = (1.0, 0.010, 0.00015)

# Market factor per universe: TARGET UNCONDITIONAL daily drift and volatility.
# Unconditional, not calm-state: the calm-state drift is solved for below so that
# the blend of calm and stress days lands on these numbers. Setting the calm
# drift directly would mean the realised return silently depended on how many
# stress days the chain happened to draw.
#   NSE_INDIA: 0.00048/day * 250 = 12.0% a year
#   US:        0.00042/day * 252 = 10.6% a year
MARKET_PROFILE = {
    "NSE_INDIA": (0.00048, 0.0105),
    "US": (0.00042, 0.0095),
}


def standardised_t(rng: np.random.Generator, size, dof: float = DOF) -> np.ndarray:
    """Student-t scaled to unit variance, so sigma parameters mean what they say."""
    return rng.standard_t(dof, size=size) / np.sqrt(dof / (dof - 2.0))


def regime_market_factor(
    rng: np.random.Generator, n: int, mu: float, sigma: float
) -> tuple[np.ndarray, np.ndarray]:
    """Market returns with a persistent two-state volatility regime.

    The multipliers are renormalised by the unconditional root-mean-square
    multiplier, so switching the regime on changes the *shape* of the return
    distribution without changing its overall volatility. Without that
    normalisation, turning on regimes would silently make every portfolio in the
    fixture more volatile and every VaR figure larger, which would look like a
    finding rather than a parameter change.
    """
    states = np.zeros(n, dtype=bool)
    in_stress = False
    for i in range(n):
        if in_stress:
            in_stress = rng.random() > P_STRESS_TO_CALM
        else:
            in_stress = rng.random() < P_CALM_TO_STRESS
        states[i] = in_stress

    pi_stress = P_CALM_TO_STRESS / (P_CALM_TO_STRESS + P_STRESS_TO_CALM)
    rms = np.sqrt(
        (1 - pi_stress) * CALM_VOL_MULTIPLIER**2 + pi_stress * STRESS_VOL_MULTIPLIER**2
    )
    multipliers = (
        np.where(states, STRESS_VOL_MULTIPLIER, CALM_VOL_MULTIPLIER) / rms
    )

    # ``mu`` is the target UNCONDITIONAL mean. Solve for the calm-state drift that
    # produces it once the negative stress-state drift is blended in:
    #   mu = (1 - pi) * calm + pi * stress
    # Setting the calm drift directly instead would leave the realised return
    # depending on how many stress days the chain happened to draw, which is a
    # fixture whose headline Sharpe ratio moves when you change the seed.
    calm_drift = (mu - pi_stress * STRESS_DAILY_DRIFT) / (1 - pi_stress)
    drift = np.where(states, STRESS_DAILY_DRIFT, calm_drift)
    return drift + sigma * multipliers * standardised_t(rng, n), states


def business_days(end: date, count: int) -> list[date]:
    """``count`` weekdays ending on or before ``end``.

    Weekends only. Exchange holidays are not modelled, which makes the series
    about 4% longer than a real one over the same span - immaterial for a
    fixture, and stated rather than left to be noticed.
    """
    days: list[date] = []
    cursor = end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return sorted(days)


def write_series(path: Path, dates: list[date], prices: np.ndarray) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["date,close"]
    lines += [f"{d.isoformat()},{p:.4f}" for d, p in zip(dates, prices)]
    path.write_text("\n".join(lines) + "\n")
    return len(dates)


def generate(universe_name: str, years: int, seed: int, out_root: Path) -> dict:
    universes = json.loads(UNIVERSES_PATH.read_text())["universes"]
    if universe_name not in universes:
        raise SystemExit(f"Unknown universe {universe_name}")
    universe = universes[universe_name]

    n = int(years * 252)
    dates = business_days(ANCHOR_END, n)

    # Seeded per universe as well as by --seed, so generating only NSE_INDIA
    # produces a byte-identical file to generating both universes.
    #
    # zlib.crc32 rather than the builtin hash(): Python randomises string hashing
    # per process unless PYTHONHASHSEED is pinned, so hash(("x", seed)) would give
    # a different fixture on every run. That is the exact class of bug that makes
    # a "reproducible" dataset quietly not be one, and it is invisible until
    # someone tries to reproduce a result.
    stream = zlib.crc32(f"{seed}:{universe_name}".encode()) & 0xFFFFFFFF
    rng = np.random.default_rng(stream)

    mu_m, sigma_m = MARKET_PROFILE.get(universe_name, (0.0004, 0.010))
    market_returns, regime_states = regime_market_factor(rng, n, mu_m, sigma_m)
    market_returns[0] = 0.0
    market_prices = 10_000.0 * np.cumprod(1.0 + market_returns)

    out_dir = out_root / universe_name
    manifest_assets = []
    rows = 0

    rows += write_series(
        out_dir / f"{universe['benchmark_symbol'].replace('^', '_')}.csv",
        dates,
        market_prices,
    )
    manifest_assets.append(
        {
            "symbol": universe["benchmark_symbol"],
            "file": f"{universe['benchmark_symbol'].replace('^', '_')}.csv",
            "kind": "BENCHMARK",
            "generating_beta": 1.0,
            "generating_daily_vol": sigma_m,
            "generating_daily_drift": mu_m,
            "stress_regime_days": int(regime_states.sum()),
        }
    )

    for entry in universe["tickers"]:
        beta, idio_vol, alpha = SECTOR_PROFILE.get(entry["sector"], DEFAULT_PROFILE)
        asset_returns = alpha + beta * market_returns + idio_vol * standardised_t(rng, n)
        asset_returns[0] = 0.0
        prices = 500.0 * np.cumprod(1.0 + asset_returns)
        filename = f"{entry['ticker']}.csv"
        rows += write_series(out_dir / filename, dates, prices)
        manifest_assets.append(
            {
                "symbol": entry["ticker"],
                "file": filename,
                "kind": "ASSET",
                "name": entry["name"],
                "sector": entry["sector"],
                "generating_beta": beta,
                "generating_idiosyncratic_daily_vol": idio_vol,
                "generating_daily_alpha": alpha,
            }
        )

    manifest = {
        "provenance": "SYNTHETIC",
        "WARNING": (
            "THESE ARE NOT MARKET PRICES. They are draws from a single-factor "
            "Student-t model, generated by backend/scripts/generate_synthetic_prices.py "
            "so that tests, CI and a first-clone demo run with no network access. Every "
            "risk figure computed from them is a demonstration of the arithmetic, not a "
            "statement about any real asset. Run scripts/fetch_prices.py for real data."
        ),
        "universe": universe_name,
        "source": (
            f"Synthetic single-factor Student-t(dof={DOF:.0f}) fixture, "
            f"seed={seed}, generated by generate_synthetic_prices.py"
        ),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "model": {
            "form": (
                "r_i = alpha_i + beta_i * r_m + sigma_i * T_nu ; "
                "r_m = mu(s) + sigma_m * k(s) * T_nu ; s = two-state Markov chain"
            ),
            "student_t_dof": DOF,
            "t_standardised_to_unit_variance": True,
            "market_daily_drift": mu_m,
            "market_daily_vol": sigma_m,
            "regime": {
                "p_calm_to_stress": P_CALM_TO_STRESS,
                "p_stress_to_calm": P_STRESS_TO_CALM,
                "calm_vol_multiplier": CALM_VOL_MULTIPLIER,
                "stress_vol_multiplier": STRESS_VOL_MULTIPLIER,
                "stress_daily_drift": STRESS_DAILY_DRIFT,
                "multipliers_renormalised_to_preserve_unconditional_variance": True,
                "stress_days_realised": int(regime_states.sum()),
            },
            "why_regime_switching": (
                "Student-t innovations alone do not survive portfolio aggregation - "
                "sums of independent heavy-tailed variates tend towards normal. A "
                "common volatility regime does survive, because every holding loads on "
                "the same market factor. It also produces volatility clustering, which "
                "is what makes the VaR backtest's breach-run statistics meaningful."
            ),
        },
        "observations_per_series": len(dates),
        "date_range": [dates[0].isoformat(), dates[-1].isoformat()],
        "calendar": "Weekdays only; exchange holidays are not modelled.",
        "assets": manifest_assets,
    }
    (out_dir / "_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return {"universe": universe_name, "files": len(manifest_assets), "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--universe",
        action="append",
        choices=["NSE_INDIA", "US"],
        help="Repeatable. Default: both.",
    )
    parser.add_argument("--years", type=int, default=DEFAULT_YEARS)
    parser.add_argument("--seed", type=int, default=20260730)
    parser.add_argument("--out", type=Path, default=OUT_ROOT)
    args = parser.parse_args()

    for universe in args.universe or ["NSE_INDIA", "US"]:
        result = generate(universe, args.years, args.seed, args.out)
        print(
            f"{result['universe']}: {result['files']} series, {result['rows']} rows "
            f"-> {args.out / result['universe']}"
        )
    print("\nProvenance: SYNTHETIC. Not market data. See the manifest in each folder.")


if __name__ == "__main__":
    main()
