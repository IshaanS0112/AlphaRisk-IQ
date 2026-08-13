"""Price series -> aligned return matrix -> a single portfolio return series.

Nothing in this module is clever, and all of it is where the bugs are. Three
decisions are made here that every downstream number inherits:

1. **Simple returns, not log returns.** A portfolio's simple return is the
   weighted sum of its holdings' simple returns. Log returns are *not* additive
   across assets, so ``sum(w_i * log_r_i)`` is not the portfolio's log return -
   it is a number with no interpretation. Log returns are additive across *time*,
   which is a different and genuinely useful property, and it is why they are
   offered for single-asset diagnostics.

2. **Dates are intersected, not forward-filled.** Two NSE tickers can disagree on
   trading days (a stock halted for a corporate action, a listing that starts
   mid-window). Forward-filling a missing close invents a 0% return day, which
   drags measured volatility down and makes the portfolio look safer than it was.
   The intersection is taken and the dropped dates are reported.

3. **Constant weights, rebalanced daily.** The portfolio return on day t is
   ``sum(w_i * r_it)`` with the *stated* weights every day. This is the standard
   convention for risk-reporting on a given weight vector. Buy-and-hold drift is
   a different portfolio by the end of a two-year window, and it is a documented
   V2 rather than something silently approximated here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from app.enums import ReturnMethod


@dataclass(frozen=True)
class AlignedReturns:
    """A rectangular return matrix and everything that was thrown away to get it."""

    dates: list[date]
    tickers: list[str]
    # shape (n_dates, n_tickers), decimal fractions
    matrix: np.ndarray
    # Per ticker: observations available before the intersection was taken.
    raw_counts: dict[str, int] = field(default_factory=dict)
    # Dates present for at least one ticker but not all of them.
    dropped_dates: list[date] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.dates)


def prices_to_returns(
    prices: list[float], method: ReturnMethod = ReturnMethod.SIMPLE
) -> list[float | None]:
    """Period returns from a price series, ``None`` for the first observation.

    The leading ``None`` is returned rather than dropped so the caller keeps a
    1:1 correspondence with the dates it passed in. Silently returning a shorter
    list is how off-by-one date misalignment gets into risk code.
    """
    out: list[float | None] = [None]
    for prev, cur in zip(prices, prices[1:]):
        if prev <= 0:
            raise ValueError(
                f"Non-positive price {prev} in series. A return cannot be computed "
                "against it, and a zero close is a data error rather than a market "
                "event - prices are adjusted closes, which are strictly positive."
            )
        out.append(math.log(cur / prev) if method is ReturnMethod.LOG else cur / prev - 1.0)
    return out


def align(series: dict[str, dict[date, float]]) -> AlignedReturns:
    """Intersect per-ticker return series onto a common date index.

    ``series`` maps ticker -> {date: return}. Dates missing for any ticker are
    dropped from all of them; see the module docstring for why forward-filling is
    not an option.
    """
    if not series:
        raise ValueError("No return series supplied.")

    tickers = sorted(series)
    date_sets = [set(series[t]) for t in tickers]
    common = sorted(set.intersection(*date_sets))
    union = set.union(*date_sets)
    dropped = sorted(union - set(common))

    if not common:
        raise ValueError(
            "The supplied tickers share no common trading dates. This usually "
            "means one series was loaded over a different window, or a ticker was "
            "listed after the others."
        )

    matrix = np.array(
        [[series[t][d] for t in tickers] for d in common], dtype=float
    )
    return AlignedReturns(
        dates=common,
        tickers=tickers,
        matrix=matrix,
        raw_counts={t: len(series[t]) for t in tickers},
        dropped_dates=dropped,
    )


def portfolio_series(aligned: AlignedReturns, weights: dict[str, float]) -> np.ndarray:
    """Daily portfolio returns under daily-rebalanced constant weights.

    Weights are looked up by ticker rather than by position, so a caller cannot
    accidentally pair the RELIANCE weight with the TCS return column - which is a
    silent error that produces perfectly plausible output.
    """
    missing = set(aligned.tickers) - set(weights)
    if missing:
        raise ValueError(f"No weight supplied for: {', '.join(sorted(missing))}")

    w = np.array([weights[t] for t in aligned.tickers], dtype=float)
    total = w.sum()
    if not math.isclose(total, 1.0, abs_tol=1e-6):
        raise ValueError(
            f"Weights over the aligned tickers sum to {total:.6f}, not 1.0. "
            "Portfolio weights are normalised at write time, so this means a "
            "holding was dropped during alignment."
        )
    return aligned.matrix @ w


def normalise_weights(holdings: list[dict]) -> tuple[list[dict], float]:
    """Scale weights to sum to 1, returning the pre-normalisation sum.

    A portfolio entered as ``[40, 35, 25]`` is obviously percentages and a
    portfolio entered as ``[0.4, 0.35, 0.25]`` is obviously fractions; both
    normalise to the same thing. The original sum is returned so the API can
    record what was actually submitted rather than pretending the user typed
    fractions.
    """
    total = sum(float(h["weight"]) for h in holdings)
    if total <= 0:
        raise ValueError("Portfolio weights must sum to a positive number.")
    return (
        [{**h, "weight": float(h["weight"]) / total} for h in holdings],
        total,
    )
