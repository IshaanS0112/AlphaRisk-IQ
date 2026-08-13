"""Sharpe, Sortino and the conventions around them.

Most of these assert against **closed forms**, not against recorded outputs. A
golden-number test proves the code has not changed; a closed-form test proves the
code implements the definition it claims to.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.services import risk_calculator as rc


# --- De-annualisation ---------------------------------------------------------

def test_geometric_deannualisation_compounds_back_to_the_quoted_annual_rate():
    daily = rc.deannualise(0.065, 252, geometric=True)
    assert (1 + daily) ** 252 == pytest.approx(1.065)


def test_simple_deannualisation_does_not_compound_back():
    """Why the geometric form is the default: rf/T overshoots when compounded."""
    daily = rc.deannualise(0.065, 252, geometric=False)
    assert (1 + daily) ** 252 == pytest.approx(1.0671, abs=1e-4)


# --- Sharpe -------------------------------------------------------------------

def test_sharpe_matches_a_hand_computation():
    returns = np.array([0.01, -0.005, 0.012, 0.003, -0.002, 0.008])
    result = rc.compute(
        returns, periods_per_year=252, risk_free_annual=0.0, min_downside_observations=2
    )
    expected = (
        np.mean(returns) / np.std(returns, ddof=1) * math.sqrt(252)
    )
    assert result.sharpe_ratio == pytest.approx(expected)


def test_sharpe_is_none_when_volatility_is_zero_rather_than_infinite():
    result = rc.compute(
        np.full(100, 0.001), periods_per_year=252, risk_free_annual=0.0
    )
    assert result.sharpe_ratio is None
    assert any(o["metric"] == "sharpe_ratio" for o in result.omitted)


def test_raising_the_risk_free_rate_lowers_sharpe():
    returns = np.random.default_rng(1).standard_normal(500) * 0.01 + 0.0005
    low = rc.compute(returns, periods_per_year=252, risk_free_annual=0.0).sharpe_ratio
    high = rc.compute(returns, periods_per_year=252, risk_free_annual=0.08).sharpe_ratio
    assert high < low


# --- Downside deviation: the two conventions ----------------------------------

def test_standard_downside_deviation_converges_to_the_closed_form(normal_returns):
    """For N(0, sigma) with MAR 0, Sortino's definition gives sqrt(1/2) * sigma.

    Because exactly half the mass is below zero and the mean square of the
    shortfall over ALL observations is half the mean square of the whole sample.
    """
    sigma = float(np.std(normal_returns, ddof=1))
    assert rc.downside_deviation(normal_returns, 0.0) == pytest.approx(
        math.sqrt(0.5) * sigma, rel=0.01
    )


def test_negative_only_downside_deviation_converges_to_its_own_closed_form(
    normal_returns,
):
    """The shortcut gives sqrt(1 - 2/pi) * sigma = 0.6028 * sigma, not sqrt(1/2).

    E[r | r<0] = -sigma*sqrt(2/pi) and E[r^2 | r<0] = sigma^2, so the variance of
    the negative subset is sigma^2 * (1 - 2/pi). These are different numbers and
    that is the whole point of reporting both.
    """
    sigma = float(np.std(normal_returns, ddof=1))
    assert rc.downside_deviation_negative_only(normal_returns) == pytest.approx(
        math.sqrt(1 - 2 / math.pi) * sigma, rel=0.01
    )


def test_on_symmetric_data_the_shortcut_flatters_sortino(normal_returns):
    standard = rc.downside_deviation(normal_returns, 0.0)
    shortcut = rc.downside_deviation_negative_only(normal_returns)
    assert shortcut < standard
    # ...by the ratio of the two closed forms, about 15%.
    assert shortcut / standard == pytest.approx(
        math.sqrt(1 - 2 / math.pi) / math.sqrt(0.5), rel=0.02
    )


def test_left_skew_reverses_the_ordering(rng):
    """The direction of the gap is not fixed - it depends on the shape.

    This is why the project reports both rather than asserting which is larger.
    """
    skewed = -rng.standard_gamma(2.0, size=200_000)
    skewed = (skewed - skewed.mean()) / skewed.std()
    assert rc.downside_deviation_negative_only(skewed) > rc.downside_deviation(skewed, 0.0)


def test_the_two_sortino_conventions_both_appear_and_differ(rng):
    returns = rng.standard_normal(2000) * 0.01 + 0.0004
    result = rc.compute(returns, periods_per_year=252, risk_free_annual=0.02)
    assert result.sortino_ratio is not None
    assert result.sortino_ratio_negative_only is not None
    assert result.sortino_ratio != pytest.approx(result.sortino_ratio_negative_only)


def test_downside_deviation_is_zero_when_nothing_falls_below_the_mar():
    assert rc.downside_deviation(np.array([0.01, 0.02, 0.03]), 0.0) == 0.0


def test_sortino_is_omitted_with_a_reason_rather_than_returned_as_a_huge_number():
    returns = np.array([0.01] * 99 + [-0.001])
    result = rc.compute(
        returns,
        periods_per_year=252,
        risk_free_annual=0.0,
        min_downside_observations=5,
    )
    assert result.sortino_ratio is None
    reason = next(o for o in result.omitted if o["metric"] == "sortino_ratio")["reason"]
    assert "1 of 100" in reason


def test_the_mar_is_what_counts_as_downside_not_the_sample_mean():
    """Raising the MAR must pull more observations into the downside set."""
    returns = np.array([0.001, 0.002, 0.003, -0.001])
    at_zero = rc.downside_deviation(returns, 0.0)
    at_two_bp = rc.downside_deviation(returns, 0.002)
    assert at_two_bp > at_zero


# --- Return annualisation -----------------------------------------------------

def test_arithmetic_annualisation_exceeds_the_compound_growth_rate(rng):
    """Roughly by half the variance. Both are reported for exactly this reason."""
    returns = rng.standard_normal(5000) * 0.015 + 0.0005
    result = rc.compute(returns, periods_per_year=252, risk_free_annual=0.0)
    assert result.mean_return_annualised > result.geometric_return_annualised


def test_geometric_return_reproduces_the_realised_growth():
    returns = np.array([0.10, -0.10, 0.10, -0.10] * 63)
    result = rc.compute(returns, periods_per_year=252, risk_free_annual=0.0)
    growth = float(np.prod(1 + returns))
    assert (1 + result.geometric_return_annualised) ** (len(returns) / 252) == pytest.approx(
        growth
    )


# --- Drawdown -----------------------------------------------------------------

def test_max_drawdown_on_a_hand_checkable_path():
    # +10%, -30%, +5%: peak at index 0 (1.10), trough at index 1 (0.77).
    returns = np.array([0.10, -0.30, 0.05])
    depth, peak, trough = rc.max_drawdown(returns)
    assert depth == pytest.approx(0.30)
    assert (peak, trough) == (0, 1)


def test_a_monotonically_rising_path_has_no_drawdown():
    depth, _, _ = rc.max_drawdown(np.array([0.01, 0.02, 0.01]))
    assert depth == pytest.approx(0.0)


def test_drawdown_indices_bracket_the_decline():
    returns = np.array([0.05, 0.05, -0.10, -0.10, 0.20])
    _, peak, trough = rc.max_drawdown(returns)
    assert peak < trough


# --- Guards -------------------------------------------------------------------

def test_a_single_observation_is_refused():
    with pytest.raises(ValueError, match="At least two return observations"):
        rc.compute(np.array([0.01]), periods_per_year=252, risk_free_annual=0.0)


def test_annualisation_scales_the_ratio_by_sqrt_of_the_period_count(rng):
    returns = rng.standard_normal(3000) * 0.01 + 0.0003
    at_252 = rc.compute(returns, periods_per_year=252, risk_free_annual=0.0).sharpe_ratio
    at_63 = rc.compute(returns, periods_per_year=63, risk_free_annual=0.0).sharpe_ratio
    assert at_252 / at_63 == pytest.approx(math.sqrt(252 / 63), rel=1e-6)
