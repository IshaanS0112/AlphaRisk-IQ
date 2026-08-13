"""Value at Risk and Expected Shortfall, historical and parametric.

Both methods answer the same question - "how bad is a bad day?" - and they
disagree, reliably and in a direction you can predict. Computing one is
arithmetic. Computing both and being able to explain the gap is the actual
skill.

**Historical VaR** reads the loss straight off the empirical distribution: sort
the observed returns, take the 5th percentile, multiply by the portfolio value.
It assumes nothing about the shape of the distribution, which is its whole
appeal. What it does assume is that the window you have is representative of the
risk you face - so a VaR estimated on 2016-2019 data had never seen a pandemic,
and a 250-day window at 99% confidence is resting on about two and a half
observations.

**Parametric (variance-covariance) VaR** fits a normal distribution to the mean
and standard deviation and reads the quantile off that. It is stable and it
extends to horizons and confidence levels the sample does not cover. It is also
wrong, because real equity returns are leptokurtic: a daily move of five standard
deviations is a roughly one-in-3.5-million event under a normal, and equity
indices deliver them every few years.

**The part that is usually stated wrongly, including in this project's own brief.**
"Fat tails, therefore historical VaR exceeds parametric VaR" is not true in
general - it is true *at high confidence levels only*, and the confidence level
where it flips is inside the range people actually quote.

A leptokurtic distribution with the same variance as a normal does not have more
mass everywhere in the tail. It has a **more peaked body** and **fatter extreme
tails**, and the two must trade off because the variance is fixed. So its 5%
quantile is typically *less* extreme than the normal's and its 1% quantile is
considerably *more* extreme. For a Student-t with 5 degrees of freedom
standardised to unit variance:

    confidence   standardised t(5) quantile   normal quantile   which is worse
      95.0%              -1.561                   -1.645          normal
      97.5%              -1.991                   -1.960          t
      99.0%              -2.606                   -2.326          t

The crossover sits between 95% and 97.5%. So a 95% VaR comparison on fat-tailed
data can perfectly well show parametric *above* historical, and reading that as
"this portfolio has thin tails" is exactly backwards. The engine reports the
ratio at every confidence level requested and says which side of the crossover
the portfolio is on, rather than asserting a direction.

**Expected Shortfall** is here because VaR's central weakness is not its
estimation method, it is its definition. VaR is a *threshold*: "we lose no more
than X on 95% of days". It says nothing whatsoever about the 5% of days when the
loss is worse, so two portfolios with identical VaR can have wildly different
catastrophic exposure. ES answers the follow-up question - given that we are in
the tail, how bad is it on average - and unlike VaR it is subadditive, meaning
combining two portfolios can never make it worse than the sum of its parts. That
property is why Basel III moved market risk capital from VaR at 99% to Expected
Shortfall at 97.5%.

It also does not have the crossover problem above, which is the sharpest argument
for reporting it. Because ES averages the entire tail rather than reading one
point off it, it registers fat tails at *every* confidence level - including 95%,
where VaR is still saying the opposite. Seeing historical VaR sit *below*
parametric while historical ES sits well *above* parametric ES, on the same data
at the same confidence level, is the clearest demonstration available of what the
two measures actually do. The shipped demo portfolio does exactly this.

**Sign convention.** Every VaR and ES figure this module returns is a **positive
loss magnitude** in portfolio currency. The underlying quantile is negative and
is also returned, labelled, because the number of production risk systems that
have shipped a sign error here is not small.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# Inverse standard normal CDF at common confidence levels, so a reader can check
# the multiplier against a table without running the code. Computed at import
# time from the exact closed form rather than transcribed, because a typo'd
# z-score is invisible and changes every reported number.
def _z(confidence: float) -> float:
    """One-tailed standard normal quantile, i.e. Phi^-1(confidence).

    Uses Phi^-1(p) = sqrt(2) * erfinv(2p - 1), inverting ``math.erf`` by
    bisection on [-6, 6] (erf saturates to +-1 in double precision well inside
    that bracket). 80 halvings take the interval below 1e-22, so the result is
    exact to double precision.

    Solved rather than transcribed on purpose. A hard-coded 1.645 is a number
    nobody ever re-checks, it silently caps you at the confidence levels someone
    thought to type, and a digit typo'd into it moves every VaR figure in the
    system with no visible symptom. The test suite asserts these against
    published z-table values.
    """
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be strictly between 0 and 1")
    target = 2.0 * confidence - 1.0
    lo, hi = -6.0, 6.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if math.erf(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0 * math.sqrt(2.0)


Z_SCORES = {0.90: _z(0.90), 0.95: _z(0.95), 0.975: _z(0.975), 0.99: _z(0.99)}


@dataclass(frozen=True)
class VarResult:
    confidence: float
    portfolio_value: float
    # Positive loss magnitudes in portfolio currency.
    var_historical: float
    var_parametric: float
    es_historical: float
    es_parametric: float
    # The same figures as fractions of portfolio value.
    var_historical_pct: float
    var_parametric_pct: float
    es_historical_pct: float
    es_parametric_pct: float
    # The raw (negative) return quantiles the losses were derived from.
    historical_quantile: float
    parametric_quantile: float
    z_score: float
    mean_daily: float
    std_daily: float
    n_observations: int
    n_tail_observations: int
    # historical / parametric. Above 1 means the empirical tail is worse than the
    # normal fit at this confidence level; below 1 does NOT mean thin tails - see
    # the module docstring on where the crossover sits.
    tail_ratio: float
    es_ratio: float
    notes: list[str]


def z_score(confidence: float) -> float:
    return Z_SCORES.get(confidence) or _z(confidence)


def historical_var(
    returns: np.ndarray, confidence: float, method: str = "linear"
) -> tuple[float, float]:
    """Return ``(quantile, es_quantile)`` - both negative fractions.

    The quantile is the (1-confidence) percentile of the return distribution.
    ``method`` is numpy's interpolation rule between order statistics: "linear"
    interpolates between the two bracketing observations, "lower" always returns
    an observation that actually happened. On a 250-day window at 99% those two
    can differ meaningfully, which is why the choice is recorded rather than
    inherited from a default.
    """
    alpha = 1.0 - confidence
    q = float(np.quantile(returns, alpha, method=method))
    tail = returns[returns <= q]
    # A tail that is empty can only happen when the quantile is interpolated
    # below every observation, which "linear" does not do - but the guard is
    # cheap and an empty-slice mean is a silent NaN.
    es_q = float(np.mean(tail)) if tail.size else q
    return q, es_q


def parametric_var(
    mean: float, std: float, confidence: float, include_drift: bool = True
) -> tuple[float, float]:
    """Normal-fit VaR and ES quantiles - both negative fractions.

    VaR quantile = mu - z*sigma. Dropping mu gives the zero-drift form most
    textbooks quote; over a one-day horizon mu is around 1e-4 against z*sigma
    around 2e-2, so it moves the answer by well under a percent. Over a ten-day
    regulatory horizon it does not, which is why it is a flag rather than a
    hard-coded simplification.

    ES quantile = mu - sigma * phi(z)/(1-confidence), the closed form for the
    conditional mean of a normal beyond its quantile.
    """
    z = z_score(confidence)
    mu = mean if include_drift else 0.0
    var_q = mu - z * std
    phi_z = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    es_q = mu - std * phi_z / (1.0 - confidence)
    return var_q, es_q


def compute(
    returns: np.ndarray,
    portfolio_value: float,
    *,
    confidence: float = 0.95,
    ddof: int = 1,
    include_drift: bool = True,
    quantile_method: str = "linear",
    min_observations_per_tail_point: int = 3,
) -> VarResult:
    n = len(returns)
    if n < 2:
        raise ValueError("At least two observations are needed to estimate VaR.")
    if portfolio_value <= 0:
        raise ValueError("Portfolio value must be positive; VaR is a currency amount.")

    notes: list[str] = []
    expected_tail = n * (1.0 - confidence)
    if expected_tail < min_observations_per_tail_point:
        notes.append(
            f"At {confidence:.0%} confidence a sample of {n} observations puts only "
            f"{expected_tail:.1f} points in the tail. The historical estimate is "
            "resting on a handful of observations and should be read as indicative; "
            "the parametric estimate is more stable here precisely because it is "
            "extrapolating from the whole distribution rather than reading the edge."
        )

    mean = float(np.mean(returns))
    std = float(np.std(returns, ddof=ddof))

    hist_q, hist_es_q = historical_var(returns, confidence, method=quantile_method)
    par_q, par_es_q = parametric_var(mean, std, confidence, include_drift=include_drift)

    var_hist = max(0.0, -hist_q) * portfolio_value
    var_par = max(0.0, -par_q) * portfolio_value
    es_hist = max(0.0, -hist_es_q) * portfolio_value
    es_par = max(0.0, -par_es_q) * portfolio_value

    ratio = (var_hist / var_par) if var_par > 0 else float("nan")
    es_ratio = (es_hist / es_par) if es_par > 0 else float("nan")

    if var_par > 0 and var_hist > var_par:
        notes.append(
            f"Historical VaR exceeds parametric VaR by {(ratio - 1) * 100:.1f}%. The "
            "observed distribution has more mass this far into the loss tail than a "
            "normal fitted to the same mean and standard deviation allows for, so the "
            "parametric figure understates the risk at this confidence level."
        )
    elif var_par > 0:
        notes.append(
            f"Parametric VaR exceeds historical VaR by {(1 / ratio - 1) * 100:.1f}%. "
            "This is NOT evidence of thin tails. A leptokurtic distribution has a more "
            "peaked body as well as fatter extremes - the variance is fixed, so the two "
            "must trade off - and its quantile only becomes more extreme than the "
            "normal's somewhere between 95% and 99% confidence. Check the same "
            "comparison at 99% and check the expected shortfall, which registers fat "
            "tails at every confidence level."
        )

    if es_par > 0 and var_par > 0:
        if es_hist > es_par and var_hist <= var_par:
            notes.append(
                f"Note the disagreement: parametric VaR looks conservative here, yet "
                f"historical expected shortfall exceeds parametric ES by "
                f"{(es_ratio - 1) * 100:.1f}%. Both are correct. VaR reads a single "
                "point on the distribution and ES averages everything beyond it, so on "
                "fat-tailed data the normal fit can be conservative about the threshold "
                "and badly optimistic about what happens past it. This is the clearest "
                "single argument for reporting ES alongside VaR."
            )
        elif es_hist > es_par:
            notes.append(
                f"Historical expected shortfall exceeds parametric ES by "
                f"{(es_ratio - 1) * 100:.1f}%: beyond the threshold, realised losses are "
                "worse than a normal distribution predicts."
            )

    tail_count = int(np.sum(returns <= hist_q))

    return VarResult(
        confidence=confidence,
        portfolio_value=portfolio_value,
        var_historical=var_hist,
        var_parametric=var_par,
        es_historical=es_hist,
        es_parametric=es_par,
        var_historical_pct=var_hist / portfolio_value,
        var_parametric_pct=var_par / portfolio_value,
        es_historical_pct=es_hist / portfolio_value,
        es_parametric_pct=es_par / portfolio_value,
        historical_quantile=hist_q,
        parametric_quantile=par_q,
        z_score=z_score(confidence),
        mean_daily=mean,
        std_daily=std,
        n_observations=n,
        n_tail_observations=tail_count,
        tail_ratio=ratio,
        es_ratio=es_ratio,
        notes=notes,
    )
