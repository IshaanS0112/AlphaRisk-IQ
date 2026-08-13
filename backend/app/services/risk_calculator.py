"""Sharpe, Sortino, downside deviation, drawdown.

The formulas are three lines each. What is worth reading is the set of
conventions around them, because every one of these ratios is quoted constantly
without its convention attached, and two correct implementations will disagree.

**Annualisation.** Mean daily return is scaled by T and daily standard deviation
by sqrt(T), so the ratio scales by sqrt(T). The sqrt comes from variance being
additive over independent periods while the mean is additive linearly. That
independence assumption is the weak point: real returns are mildly
autocorrelated, and positive autocorrelation means sqrt(T) *understates* true
annual volatility. Worth saying out loud rather than hiding behind "standard
practice".

**Risk-free de-annualisation.** ``(1+rf)^(1/T) - 1``, not ``rf/T``. For rf=6.5%
and T=252 these differ by about a millionth of a percent per day, so this is not
about accuracy - it is that the geometric form is the one that compounds back to
the quoted annual rate, and "why did you divide?" is a question with no good
answer.

**Sortino's denominator, which is where almost everyone gets it wrong.** The
definition Frank Sortino published is

    downside_deviation = sqrt( (1/N) * sum over ALL i of min(r_i - MAR, 0)^2 )

Note two things. The deviations are measured from the **Minimum Acceptable
Return**, not from the sample mean. And the sum is divided by **N, the total
number of observations** - not by the count of observations that fell below the
MAR. A quarter with no losing days genuinely has zero downside risk, and that is
what the full-N denominator expresses.

The version that circulates widely - "the standard deviation of the negative
returns" - differs on both counts, and the two differences push in opposite
directions. Dividing by ``n_negative - 1`` instead of ``N`` inflates it;
measuring deviations from the mean of the negatives instead of from the MAR
deflates it. Which effect wins depends on the shape of the distribution, and it
is worth being able to state the closed form:

    For returns that are normal with mean 0, standard deviation sigma, and MAR 0
        Sortino's definition  ->  sqrt(1/2) * sigma          = 0.7071 * sigma
        negative-only std dev ->  sqrt(1 - 2/pi) * sigma     = 0.6028 * sigma

so on a symmetric sample the shortcut gives the *smaller* denominator and
therefore flatters the ratio by about 17%. Introduce left skew - which is what
real equity returns have - and the ordering reverses, because the shortcut's
mean-centring subtracts a larger number while Sortino's MAR-centring does not.
Both are verified against these closed forms in ``tests/test_risk_calculator.py``.

This module computes both, labels them with a
:class:`~app.enums.SortinoConvention`, and stores both, so the difference is a
number this project reports rather than a claim it makes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RiskResult:
    mean_return_daily: float
    mean_return_annualised: float
    geometric_return_annualised: float
    std_dev_daily: float
    std_dev_annualised: float
    sharpe_ratio: float | None
    sortino_ratio: float | None
    sortino_ratio_negative_only: float | None
    downside_deviation_daily: float | None
    downside_deviation_annualised: float | None
    downside_deviation_negative_only_daily: float | None
    max_drawdown: float
    max_drawdown_peak_index: int
    max_drawdown_trough_index: int
    n_observations: int
    n_downside_observations: int
    omitted: list[dict]


def deannualise(annual_rate: float, periods_per_year: int, geometric: bool = True) -> float:
    """Annual rate -> per-period rate."""
    if geometric:
        return (1.0 + annual_rate) ** (1.0 / periods_per_year) - 1.0
    return annual_rate / periods_per_year


def annualise_return(mean_periodic: float, periods_per_year: int) -> float:
    """Arithmetic annualisation: mean * T.

    Paired with sqrt(T) volatility scaling so the Sharpe ratio annualises
    cleanly. This is *not* the compound annual growth rate - see
    :func:`geometric_annual_return` - and the two differ by roughly half the
    variance, which for a 20% vol portfolio is about 2 percentage points a year.
    Both are reported, because quoting the arithmetic one as "the return" is
    misleading and quoting the geometric one inside a Sharpe ratio is wrong.
    """
    return mean_periodic * periods_per_year


def geometric_annual_return(returns: np.ndarray, periods_per_year: int) -> float:
    """Compound annual growth rate actually realised over the sample."""
    growth = float(np.prod(1.0 + returns))
    if growth <= 0:
        return -1.0
    years = len(returns) / periods_per_year
    return growth ** (1.0 / years) - 1.0 if years > 0 else 0.0


def std_dev(returns: np.ndarray, ddof: int = 1) -> float:
    return float(np.std(returns, ddof=ddof))


def downside_deviation(returns: np.ndarray, mar_periodic: float = 0.0) -> float:
    """Sortino's own definition. RMS shortfall below MAR over ALL observations."""
    shortfall = np.minimum(returns - mar_periodic, 0.0)
    return float(math.sqrt(float(np.mean(shortfall**2))))


def downside_deviation_negative_only(returns: np.ndarray, ddof: int = 1) -> float:
    """The widely circulated shortcut: sample std dev of the negative returns only.

    Kept so the gap against the standard definition is a number this project
    reports rather than a claim it makes. Returns NaN when fewer than two
    negative observations exist, since a sample standard deviation of one point
    is undefined.
    """
    negatives = returns[returns < 0.0]
    if len(negatives) < 2:
        return float("nan")
    return float(np.std(negatives, ddof=ddof))


def max_drawdown(returns: np.ndarray) -> tuple[float, int, int]:
    """Largest peak-to-trough decline of the cumulative return path.

    Returned as a positive fraction (0.34 = a 34% drawdown), with the indices of
    the peak and trough so the caller can date it. Drawdown is not in the master
    brief's metric list, and it is here because it is the one risk number a
    non-quant stakeholder actually feels: VaR is a statement about a distribution,
    a drawdown is a statement about what happened.
    """
    if len(returns) == 0:
        return 0.0, 0, 0
    equity = np.cumprod(1.0 + returns)
    running_peak = np.maximum.accumulate(equity)
    drawdowns = equity / running_peak - 1.0
    trough = int(np.argmin(drawdowns))
    peak = int(np.argmax(equity[: trough + 1])) if trough > 0 else 0
    return float(-drawdowns[trough]), peak, trough


def compute(
    returns: np.ndarray,
    *,
    periods_per_year: int,
    risk_free_annual: float,
    mar_annual: float = 0.0,
    ddof: int = 1,
    geometric_deannualisation: bool = True,
    min_downside_observations: int = 5,
    degenerate_std_threshold: float = 1e-12,
) -> RiskResult:
    """The full risk-adjusted-return block for one return series."""
    omitted: list[dict] = []
    n = len(returns)
    if n < 2:
        raise ValueError(
            "At least two return observations are needed for a standard deviation."
        )

    rf_periodic = deannualise(risk_free_annual, periods_per_year, geometric_deannualisation)
    mar_periodic = deannualise(mar_annual, periods_per_year, geometric_deannualisation)

    mean_daily = float(np.mean(returns))
    sigma_daily = std_dev(returns, ddof=ddof)
    sigma_annual = sigma_daily * math.sqrt(periods_per_year)

    excess_daily = mean_daily - rf_periodic

    if sigma_daily > degenerate_std_threshold:
        sharpe = (excess_daily / sigma_daily) * math.sqrt(periods_per_year)
    else:
        sharpe = None
        omitted.append(
            {
                "metric": "sharpe_ratio",
                "reason": (
                    "Portfolio standard deviation is numerically zero over the sample "
                    f"({sigma_daily:.2e}), so the ratio is undefined. Every observation "
                    "is identical, which is a data problem - a forward-filled series, or "
                    "one ticker loaded twice - rather than a riskless portfolio."
                ),
            }
        )

    n_downside = int(np.sum(returns < mar_periodic))
    dd = downside_deviation(returns, mar_periodic)
    dd_neg = downside_deviation_negative_only(returns, ddof=ddof)

    sortino: float | None
    if n_downside < min_downside_observations:
        sortino = None
        omitted.append(
            {
                "metric": "sortino_ratio",
                "reason": (
                    f"Only {n_downside} of {n} observations fell below the minimum "
                    f"acceptable return, against a floor of {min_downside_observations}. "
                    "A downside deviation estimated from a handful of points is noise, "
                    "and dividing by a near-zero denominator would produce a large "
                    "Sortino ratio that means nothing."
                ),
            }
        )
    elif dd <= degenerate_std_threshold:
        sortino = None
        omitted.append(
            {
                "metric": "sortino_ratio",
                "reason": "Downside deviation is zero: no observation fell below the MAR.",
            }
        )
    else:
        sortino = (excess_daily / dd) * math.sqrt(periods_per_year)

    if math.isnan(dd_neg) or dd_neg <= degenerate_std_threshold:
        sortino_neg = None
        dd_neg_value = None
        omitted.append(
            {
                "metric": "sortino_ratio_negative_only",
                "reason": (
                    "Fewer than two strictly negative returns in the sample, so the "
                    "sample standard deviation of the negative subset is undefined."
                ),
            }
        )
    else:
        sortino_neg = (excess_daily / dd_neg) * math.sqrt(periods_per_year)
        dd_neg_value = dd_neg

    mdd, peak_i, trough_i = max_drawdown(returns)

    return RiskResult(
        mean_return_daily=mean_daily,
        mean_return_annualised=annualise_return(mean_daily, periods_per_year),
        geometric_return_annualised=geometric_annual_return(returns, periods_per_year),
        std_dev_daily=sigma_daily,
        std_dev_annualised=sigma_annual,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        sortino_ratio_negative_only=sortino_neg,
        downside_deviation_daily=dd,
        downside_deviation_annualised=dd * math.sqrt(periods_per_year),
        downside_deviation_negative_only_daily=dd_neg_value,
        max_drawdown=mdd,
        max_drawdown_peak_index=peak_i,
        max_drawdown_trough_index=trough_i,
        n_observations=n,
        n_downside_observations=n_downside,
        omitted=omitted,
    )
