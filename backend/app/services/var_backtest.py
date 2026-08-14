"""Rolling VaR backtesting and Kupiec's proportion-of-failures test.

Anyone can compute a VaR. The question that separates a risk number from a risk
*model* is whether the number was right, and the standard answer is breach
counting: if your 95% VaR is calibrated, the realised loss should exceed it on
about 5% of days. More often and the model is understating risk; far less often
and it is over-reserving capital, which has a real cost.

**The test is run out of sample, and that matters.** On each day t the VaR is
re-estimated on the trailing ``window`` observations only, then compared against
the return on day t+1 - which the estimate has never seen. Estimating the
threshold on the whole sample and then counting breaches within that same sample
is circular: the quantile was fitted to those very observations, so it passes
essentially by construction. That mistake is common enough that "was it in
sample?" is a fair first question to ask of any backtest result.

**Kupiec's POF test** (Paul Kupiec, "Techniques for Verifying the Accuracy of
Risk Measurement Models", Journal of Derivatives, 1995) turns the breach count
into a hypothesis test. Under the null that the true breach probability equals
p = 1 - confidence, the likelihood ratio

    LR_POF = -2 * ln[ ((1-p)^(N-x) * p^x) / ((1-x/N)^(N-x) * (x/N)^x) ]

is asymptotically chi-square with one degree of freedom. Above 3.841 the null is
rejected at 95%.

**What this test does not do.** Kupiec tests only the *number* of breaches, not
their *timing*. A model that breaches five times in five consecutive days during
one crisis and never again passes it just as cleanly as one that breaches five
times spread evenly across the year - and the first is far more dangerous,
because clustered breaches are what wipes out a book. Testing independence of
breaches is Christoffersen's conditional-coverage test, documented as V2. The
clustering statistics here (longest breach run, count of consecutive-day
breaches) are reported so the gap is visible in the output.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from app.enums import VarMethod
from app.services.var_engine import historical_var, parametric_var


@dataclass(frozen=True)
class BacktestResult:
    method: str
    confidence: float
    window: int
    n_tested: int
    n_breaches: int
    breach_rate: float
    expected_breach_rate: float
    expected_breaches: float
    kupiec_lr: float | None
    kupiec_p_value: float | None
    kupiec_critical_value: float
    passes: bool | None
    verdict: str
    longest_breach_run: int
    consecutive_breach_days: int
    breach_dates_index: list[int]
    notes: list[str]


def chi2_1df_sf(x: float) -> float:
    """Survival function of chi-square with one degree of freedom.

    P(X > x) = erfc(sqrt(x/2)) for one degree of freedom. Closed form, so the
    p-value needs no scipy and no lookup table.
    """
    if x <= 0:
        return 1.0
    return math.erfc(math.sqrt(x / 2.0))


def kupiec_pof(n: int, breaches: int, p: float) -> tuple[float, float]:
    """Kupiec likelihood-ratio statistic and its chi-square(1) p-value.

    The boundary cases are handled explicitly rather than left to produce a
    ``log(0)``: zero breaches and all-breaches both have finite closed-form
    statistics under the null, and returning NaN there would silently drop the
    most extreme (and most informative) failures.
    """
    if n <= 0:
        raise ValueError("Cannot run a proportion-of-failures test on zero observations.")
    x = breaches
    if x == 0:
        lr = -2.0 * (n * math.log(1.0 - p))
    elif x == n:
        lr = -2.0 * (n * math.log(p))
    else:
        p_hat = x / n
        log_null = (n - x) * math.log(1.0 - p) + x * math.log(p)
        log_alt = (n - x) * math.log(1.0 - p_hat) + x * math.log(p_hat)
        lr = -2.0 * (log_null - log_alt)
    lr = max(0.0, lr)
    return lr, chi2_1df_sf(lr)


def _runs(flags: np.ndarray) -> tuple[int, int]:
    """Longest run of consecutive breaches, and how many breach days sit in a run.

    A day counts as clustered if it is adjacent to another breach. The second day
    of a run brings the first one with it, which is why the ``current == 2`` case
    adds two.
    """
    longest = current = clustered = 0
    for flag in flags:
        if flag:
            current += 1
            longest = max(longest, current)
            if current == 2:
                clustered += 2
            elif current > 2:
                clustered += 1
        else:
            current = 0
    return longest, clustered


def run(
    returns: np.ndarray,
    *,
    method: VarMethod = VarMethod.HISTORICAL,
    confidence: float = 0.95,
    window: int = 250,
    ddof: int = 1,
    include_drift: bool = True,
    quantile_method: str = "linear",
    critical_value: float = 3.841,
) -> BacktestResult:
    n_total = len(returns)
    notes: list[str] = []
    p = 1.0 - confidence

    if n_total <= window:
        return BacktestResult(
            method=method.value,
            confidence=confidence,
            window=window,
            n_tested=0,
            n_breaches=0,
            breach_rate=float("nan"),
            expected_breach_rate=p,
            expected_breaches=0.0,
            kupiec_lr=None,
            kupiec_p_value=None,
            kupiec_critical_value=critical_value,
            passes=None,
            verdict="NOT_ENOUGH_DATA",
            longest_breach_run=0,
            consecutive_breach_days=0,
            breach_dates_index=[],
            notes=[
                f"A rolling backtest needs more than {window} observations to produce a "
                f"single out-of-sample test; the sample has {n_total}. Load a longer "
                "price history or shorten the estimation window - but a window much "
                "below 250 days makes each VaR estimate itself unreliable, so the "
                "honest answer here is usually 'get more data'."
            ],
        )

    thresholds = np.empty(n_total - window, dtype=float)
    for i in range(window, n_total):
        train = returns[i - window : i]
        if method is VarMethod.HISTORICAL:
            q, _ = historical_var(train, confidence, method=quantile_method)
        else:
            q, _ = parametric_var(
                float(np.mean(train)),
                float(np.std(train, ddof=ddof)),
                confidence,
                include_drift=include_drift,
            )
        thresholds[i - window] = q

    realised = returns[window:]
    breach_flags = realised < thresholds
    n_tested = int(len(realised))
    n_breaches = int(np.sum(breach_flags))
    breach_rate = n_breaches / n_tested

    lr, p_value = kupiec_pof(n_tested, n_breaches, p)
    passes = lr <= critical_value
    longest, clustered = _runs(breach_flags)

    if passes:
        verdict = "PASS"
        notes.append(
            f"{n_breaches} breaches in {n_tested} out-of-sample days is a rate of "
            f"{breach_rate:.2%} against an expected {p:.2%}. Kupiec LR = {lr:.3f}, "
            f"below the {critical_value} chi-square(1) critical value, so the null "
            "that the model is correctly calibrated is not rejected at 95%."
        )
    else:
        direction = "understating" if breach_rate > p else "overstating"
        verdict = "FAIL_UNDERSTATES_RISK" if breach_rate > p else "FAIL_OVERSTATES_RISK"
        notes.append(
            f"{n_breaches} breaches in {n_tested} out-of-sample days is a rate of "
            f"{breach_rate:.2%} against an expected {p:.2%}. Kupiec LR = {lr:.3f} "
            f"exceeds {critical_value}, so the model is rejected at 95%: it is "
            f"{direction} risk over this window."
        )

    if longest >= 2:
        notes.append(
            f"The longest run of consecutive breaches is {longest} days. Kupiec does "
            "not test for this - clustered breaches pass its count test just as "
            "cleanly as evenly spaced ones, and they are considerably more dangerous. "
            "Christoffersen's conditional-coverage test is the right tool and is a "
            "documented V2."
        )

    return BacktestResult(
        method=method.value,
        confidence=confidence,
        window=window,
        n_tested=n_tested,
        n_breaches=n_breaches,
        breach_rate=breach_rate,
        expected_breach_rate=p,
        expected_breaches=n_tested * p,
        kupiec_lr=lr,
        kupiec_p_value=p_value,
        kupiec_critical_value=critical_value,
        passes=passes,
        verdict=verdict,
        longest_breach_run=longest,
        consecutive_breach_days=clustered,
        breach_dates_index=[int(i) for i in np.flatnonzero(breach_flags)],
        notes=notes,
    )
