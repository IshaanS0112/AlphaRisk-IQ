"""VaR and Expected Shortfall, including the crossover the docstring claims."""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.services import var_engine


# --- z scores -----------------------------------------------------------------

@pytest.mark.parametrize(
    ("confidence", "published"),
    [(0.90, 1.281552), (0.95, 1.644854), (0.975, 1.959964), (0.99, 2.326348)],
)
def test_z_scores_match_published_tables(confidence, published):
    """Solved at import time rather than transcribed; this is the check."""
    assert var_engine.z_score(confidence) == pytest.approx(published, abs=1e-6)


def test_z_score_rejects_an_impossible_confidence():
    with pytest.raises(ValueError, match="strictly between 0 and 1"):
        var_engine.z_score(1.0)


# --- Sign convention ----------------------------------------------------------

def test_all_reported_figures_are_positive_losses(rng):
    result = var_engine.compute(rng.standard_normal(2000) * 0.01, 1_000_000)
    assert result.var_historical > 0
    assert result.var_parametric > 0
    assert result.es_historical > 0
    assert result.es_parametric > 0
    # ...and the underlying quantiles they came from are negative.
    assert result.historical_quantile < 0
    assert result.parametric_quantile < 0


def test_var_scales_linearly_with_portfolio_value(rng):
    returns = rng.standard_normal(2000) * 0.01
    small = var_engine.compute(returns, 1_000_000)
    large = var_engine.compute(returns, 5_000_000)
    assert large.var_historical == pytest.approx(5 * small.var_historical)
    assert large.var_historical_pct == pytest.approx(small.var_historical_pct)


# --- Agreement on normal data -------------------------------------------------

def test_on_normal_data_the_two_methods_agree(normal_returns):
    """They must: the parametric method's assumption is exactly satisfied here."""
    result = var_engine.compute(normal_returns, 1_000_000, confidence=0.95)
    assert result.tail_ratio == pytest.approx(1.0, rel=0.02)


def test_parametric_es_matches_its_closed_form(normal_returns):
    """ES = mu - sigma * phi(z) / (1 - confidence) for a normal."""
    result = var_engine.compute(normal_returns, 1_000_000, confidence=0.95)
    z = var_engine.z_score(0.95)
    phi = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    expected = -(result.mean_daily - result.std_daily * phi / 0.05) * 1_000_000
    assert result.es_parametric == pytest.approx(expected)


def test_historical_es_is_the_mean_of_the_tail(rng):
    returns = rng.standard_normal(5000) * 0.01
    result = var_engine.compute(returns, 1_000_000, confidence=0.95)
    tail = returns[returns <= result.historical_quantile]
    assert result.es_historical == pytest.approx(-float(np.mean(tail)) * 1_000_000)


def test_expected_shortfall_always_exceeds_var(rng):
    """By construction: an average over the tail cannot be milder than its edge."""
    for _ in range(5):
        returns = rng.standard_normal(3000) * 0.012
        result = var_engine.compute(returns, 1_000_000, confidence=0.95)
        assert result.es_historical > result.var_historical
        assert result.es_parametric > result.var_parametric


# --- The crossover ------------------------------------------------------------

# Published t(5) one-tailed quantiles divided by sqrt(5/3), the standardisation
# that puts the distribution on unit variance, over the matching normal quantile.
# These are the exact numbers in the var_engine docstring table, so this
# parametrisation checks the documentation as well as the code.
T5_OVER_NORMAL = {
    0.95: (2.015048 / math.sqrt(5 / 3)) / 1.644854,   # 0.9490 - normal is worse
    0.975: (2.570582 / math.sqrt(5 / 3)) / 1.959964,  # 1.0159 - just past the crossover
    0.99: (3.364930 / math.sqrt(5 / 3)) / 2.326348,   # 1.1204 - t is clearly worse
}


@pytest.mark.parametrize("confidence", [0.95, 0.975, 0.99])
def test_the_historical_parametric_ratio_matches_student_t_theory(
    fat_tailed_returns, confidence
):
    """The claim the master brief gets wrong, checked against the closed form.

    A standardised t(5) has a MORE PEAKED body as well as fatter extremes - the
    variance is fixed, so the two must trade off. At 95% the normal fit is the
    more extreme of the two and reading that as "thin tails" is backwards.
    """
    result = var_engine.compute(fat_tailed_returns, 1_000_000, confidence=confidence)
    assert result.tail_ratio == pytest.approx(T5_OVER_NORMAL[confidence], rel=0.03)


def test_the_crossover_sits_between_95_and_99_percent(fat_tailed_returns):
    ratios = {
        level: var_engine.compute(
            fat_tailed_returns, 1_000_000, confidence=level
        ).tail_ratio
        for level in (0.95, 0.975, 0.99)
    }
    assert ratios[0.95] < ratios[0.975] < ratios[0.99]
    assert ratios[0.95] < 1.0 < ratios[0.99]


def test_expected_shortfall_registers_fat_tails_even_at_95_percent(fat_tailed_returns):
    """The strongest argument for reporting ES: no crossover to worry about.

    At 95% the VaR comparison says the normal fit is conservative and the ES
    comparison says it is optimistic. Both are correct, and the disagreement is
    the point - VaR reads one point off the distribution, ES averages everything
    past it.
    """
    result = var_engine.compute(fat_tailed_returns, 1_000_000, confidence=0.95)
    assert result.tail_ratio < 1.0
    assert result.es_ratio > 1.0


@pytest.mark.parametrize("confidence", [0.95, 0.975, 0.99])
def test_es_is_always_more_tail_sensitive_than_var(fat_tailed_returns, confidence):
    result = var_engine.compute(fat_tailed_returns, 1_000_000, confidence=confidence)
    assert result.es_ratio > result.tail_ratio


def test_the_engine_says_so_rather_than_asserting_a_direction(fat_tailed_returns):
    result = var_engine.compute(fat_tailed_returns, 1_000_000, confidence=0.95)
    joined = " ".join(result.notes)
    assert "NOT evidence of thin tails" in joined
    assert "expected shortfall" in joined.lower()


# --- Drift and quantile method ------------------------------------------------

def test_dropping_the_drift_term_changes_the_parametric_figure(rng):
    returns = rng.standard_normal(2000) * 0.01 + 0.002
    with_drift = var_engine.compute(returns, 1_000_000, include_drift=True)
    without = var_engine.compute(returns, 1_000_000, include_drift=False)
    assert with_drift.var_parametric < without.var_parametric


@pytest.mark.parametrize("method", ["linear", "lower", "higher"])
def test_every_declared_quantile_method_runs(rng, method):
    result = var_engine.compute(
        rng.standard_normal(1000) * 0.01, 1_000_000, quantile_method=method
    )
    assert result.var_historical > 0


# --- Guards -------------------------------------------------------------------

def test_a_thin_tail_sample_is_flagged_rather_than_silently_reported(rng):
    result = var_engine.compute(rng.standard_normal(120) * 0.01, 1_000_000, confidence=0.99)
    assert any("resting on a handful" in note for note in result.notes)


def test_a_non_positive_portfolio_value_is_refused(rng):
    with pytest.raises(ValueError, match="must be positive"):
        var_engine.compute(rng.standard_normal(500) * 0.01, 0.0)
