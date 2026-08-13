"""Rolling VaR backtesting and the Kupiec proportion-of-failures test."""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.enums import VarMethod
from app.services import var_backtest


# --- The chi-square tail ------------------------------------------------------

@pytest.mark.parametrize(
    ("statistic", "p_value"), [(3.841, 0.05), (6.635, 0.01), (2.706, 0.10)]
)
def test_chi_square_one_df_survival_matches_published_critical_values(statistic, p_value):
    """Closed form erfc(sqrt(x/2)); no scipy, no lookup table."""
    assert var_backtest.chi2_1df_sf(statistic) == pytest.approx(p_value, abs=5e-4)


# --- Kupiec ------------------------------------------------------------------

def test_a_perfectly_calibrated_model_scores_zero():
    lr, p_value = var_backtest.kupiec_pof(n=1000, breaches=50, p=0.05)
    assert lr == pytest.approx(0.0, abs=1e-9)
    assert p_value == pytest.approx(1.0)


def test_twice_the_expected_breaches_is_rejected():
    lr, p_value = var_backtest.kupiec_pof(n=1000, breaches=100, p=0.05)
    assert lr > 3.841
    assert p_value < 0.001


def test_zero_breaches_has_a_finite_statistic_rather_than_a_log_of_zero():
    """The boundary case a naive implementation returns NaN for."""
    lr, _ = var_backtest.kupiec_pof(n=250, breaches=0, p=0.05)
    assert math.isfinite(lr)
    assert lr == pytest.approx(-2 * 250 * math.log(0.95))


def test_all_breaches_also_has_a_finite_statistic():
    lr, _ = var_backtest.kupiec_pof(n=100, breaches=100, p=0.05)
    assert math.isfinite(lr)


def test_the_statistic_is_symmetric_in_neither_direction_but_always_non_negative():
    for breaches in range(0, 200, 7):
        lr, _ = var_backtest.kupiec_pof(n=1000, breaches=breaches, p=0.05)
        assert lr >= 0.0


def test_zero_observations_is_an_error_not_a_division_by_zero():
    with pytest.raises(ValueError, match="zero observations"):
        var_backtest.kupiec_pof(n=0, breaches=0, p=0.05)


# --- The rolling backtest -----------------------------------------------------

def test_a_correctly_specified_model_passes(rng):
    returns = rng.standard_normal(2500) * 0.011
    result = var_backtest.run(
        returns, method=VarMethod.PARAMETRIC, confidence=0.95, window=250
    )
    assert result.verdict == "PASS"
    assert result.breach_rate == pytest.approx(0.05, abs=0.015)


def test_a_normal_fit_on_fat_tailed_data_fails_at_99_percent(rng):
    """The headline result: parametric VaR under-reserves where it matters.

    At 99% the normal fit's quantile sits well inside the true one, so breaches
    arrive at roughly twice the rate the model claims.
    """
    dof = 3.0
    returns = rng.standard_t(dof, size=2500) / math.sqrt(dof / (dof - 2)) * 0.011
    result = var_backtest.run(
        returns, method=VarMethod.PARAMETRIC, confidence=0.99, window=250
    )
    assert result.verdict == "FAIL_UNDERSTATES_RISK"
    assert result.breach_rate > 0.01


def test_the_test_is_out_of_sample(rng):
    """Each threshold must be estimated on data strictly before the day it judges.

    Re-deriving the thresholds here from trailing windows only and confirming the
    breach count matches is the check that no lookahead crept in - the mistake
    that makes any backtest pass by construction.
    """
    returns = rng.standard_normal(600) * 0.01
    window = 250
    result = var_backtest.run(
        returns, method=VarMethod.PARAMETRIC, confidence=0.95, window=window
    )

    breaches = 0
    for i in range(window, len(returns)):
        train = returns[i - window : i]
        threshold = float(np.mean(train)) - 1.6448536269514722 * float(
            np.std(train, ddof=1)
        )
        if returns[i] < threshold:
            breaches += 1
    assert result.n_breaches == breaches
    assert result.n_tested == len(returns) - window


def test_too_short_a_sample_reports_why_rather_than_returning_a_number(rng):
    result = var_backtest.run(rng.standard_normal(200) * 0.01, window=250)
    assert result.verdict == "NOT_ENOUGH_DATA"
    assert result.passes is None
    assert result.kupiec_lr is None
    assert "get more data" in " ".join(result.notes)


def test_breach_clustering_is_reported_because_kupiec_cannot_see_it(rng):
    """Kupiec counts breaches; it says nothing about whether they arrive in runs.

    Clustered breaches are far more dangerous and pass the count test just as
    cleanly, so the run statistics are surfaced and the gap is named.
    """
    dof = 3.0
    returns = rng.standard_t(dof, size=1500) / math.sqrt(dof / (dof - 2)) * 0.012
    result = var_backtest.run(returns, confidence=0.95, window=250)
    assert result.longest_breach_run >= 1
    assert result.consecutive_breach_days >= 0
    if result.longest_breach_run >= 2:
        assert any("Christoffersen" in note for note in result.notes)


def test_both_methods_run_and_are_labelled(rng):
    returns = rng.standard_normal(1000) * 0.01
    for method in (VarMethod.HISTORICAL, VarMethod.PARAMETRIC):
        result = var_backtest.run(returns, method=method, window=250)
        assert result.method == method.value
        assert result.n_tested == 750


def test_run_counting_handles_adjacency_correctly():
    flags = np.array([True, True, False, True, False, True, True, True])
    longest, clustered = var_backtest._runs(flags)
    assert longest == 3
    # Two in the first run plus three in the last; the isolated breach does not count.
    assert clustered == 5
