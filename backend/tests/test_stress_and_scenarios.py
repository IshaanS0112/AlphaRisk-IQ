"""Stress testing, beta estimation, and the sourced scenario library."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.enums import ShockMode
from app.services import scenarios as scenario_service
from app.services import stress_test_engine as stress
from app.services.universes import get_universe, load_universes

REPO_ROOT = Path(__file__).resolve().parents[2]


# --- The scenario library -----------------------------------------------------

def test_every_scenario_magnitude_is_derived_from_its_stored_index_levels():
    """The design claim: no percentage is ever asserted, only computed.

    If a peak or trough level is corrected, this test is what guarantees the
    magnitude everywhere downstream moves with it.
    """
    for scenario in scenario_service.load_scenarios().values():
        expected = scenario.trough_level / scenario.peak_level - 1.0
        assert scenario.shock_pct == pytest.approx(expected)
        assert f"{expected:.4f}" in scenario.as_dict()["derivation"]


@pytest.mark.parametrize(
    ("name", "approximate_pct"),
    [
        ("gfc_2008_calendar_year", -0.3849),
        ("gfc_peak_to_trough", -0.5678),
        ("covid_crash_2020", -0.3392),
        ("gfc_2008_calendar_year_nifty", -0.5179),
        ("gfc_peak_to_trough_nifty", -0.5986),
        ("covid_crash_2020_nifty", -0.3844),
    ],
)
def test_the_documented_magnitudes_still_hold(name, approximate_pct):
    """A tripwire on the figures quoted in the README.

    Editing an index level fails this test, which is the intended behaviour: a
    documented magnitude has changed and every figure derived from it moves with
    it.
    """
    scenario = scenario_service.load_scenarios()[name]
    assert scenario.shock_pct == pytest.approx(approximate_pct, abs=5e-4)


def test_the_calendar_year_and_peak_to_trough_scenarios_are_not_the_same_number():
    """The distinction the master brief blurs. -38% and -57% are both real 2008
    figures describing different things."""
    library = scenario_service.load_scenarios()
    calendar = library["gfc_2008_calendar_year"].shock_pct
    drawdown = library["gfc_peak_to_trough"].shock_pct
    assert drawdown < calendar - 0.15
    assert library["gfc_2008_calendar_year"].basis == "CALENDAR_YEAR_PRICE_RETURN"
    assert library["gfc_peak_to_trough"].basis == "PEAK_TO_TROUGH_DRAWDOWN"


def test_every_scenario_states_its_source_and_verification_status():
    for scenario in scenario_service.load_scenarios().values():
        assert scenario.source
        assert scenario.verification_status
        assert scenario.peak_date < scenario.trough_date


def test_scenarios_are_partitioned_by_universe():
    for name in load_universes():
        for scenario in scenario_service.for_universe(name):
            assert scenario.universe == name


def test_a_scenario_whose_levels_are_the_wrong_way_round_is_refused(tmp_path):
    payload = {
        "scenarios": [
            {
                "name": "inverted",
                "universe": "US",
                "label": "Inverted",
                "index": "S&P 500",
                "peak_date": "2020-01-01",
                "peak_level": 100.0,
                "trough_date": "2020-06-01",
                "trough_level": 150.0,
                "basis": "PEAK_TO_TROUGH_DRAWDOWN",
                "source": "test",
                "verification_status": "TEST",
                "note": "",
            }
        ]
    }
    path = tmp_path / "scenarios.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="wrong way round"):
        scenario_service.load_scenarios(str(path))


# --- Universes ----------------------------------------------------------------

def test_every_universe_declares_what_the_risk_math_needs():
    for name, universe in load_universes().items():
        assert universe.benchmark_symbol
        assert universe.trading_days_per_year > 200
        assert universe.currency in {"INR", "USD"}
        assert universe.tickers
        # The risk-free rate is a placeholder and must say so, not pretend to be
        # a sourced figure.
        assert "VERIFY" in universe.risk_free_status
        assert scenario_service.for_universe(name), f"{name} has no scenarios"


def test_an_unknown_universe_is_a_clear_error():
    with pytest.raises(KeyError, match="Unknown universe"):
        get_universe("EUROSTOXX")


# --- Beta estimation ----------------------------------------------------------

def test_ols_beta_recovers_a_known_generating_beta(rng):
    market = rng.standard_normal(1000) * 0.01
    asset = 1.35 * market + rng.standard_normal(1000) * 0.004
    estimate = stress.estimate_beta(asset, market, ticker="X")
    assert estimate.beta == pytest.approx(1.35, rel=0.03)
    assert estimate.estimated is True
    assert 0.8 < estimate.r_squared < 1.0


def test_pure_noise_gives_a_beta_near_zero_and_a_near_zero_r_squared(rng):
    market = rng.standard_normal(2000) * 0.01
    asset = rng.standard_normal(2000) * 0.01
    estimate = stress.estimate_beta(asset, market, ticker="X")
    assert abs(estimate.beta) < 0.1
    assert estimate.r_squared < 0.05


def test_too_short_a_sample_defaults_to_one_and_says_so(rng):
    estimate = stress.estimate_beta(
        rng.standard_normal(30) * 0.01, rng.standard_normal(30) * 0.01, min_observations=60
    )
    assert estimate.beta == 1.0
    assert estimate.estimated is False
    assert "floor of 60" in estimate.note


# --- Applying a shock ---------------------------------------------------------

def test_uniform_mode_is_exactly_the_stated_arithmetic():
    result = stress.apply_shock(
        weights={"A": 0.5, "B": 0.5},
        portfolio_value=1_000_000,
        index_shock=-0.3844,
        mode=ShockMode.UNIFORM,
    )
    assert result.portfolio_value_after == pytest.approx(1_000_000 * (1 - 0.3844))
    assert result.pct_loss == pytest.approx(0.3844)
    assert result.portfolio_beta == pytest.approx(1.0)


def test_beta_adjusted_loss_equals_portfolio_beta_times_the_shock():
    betas = {
        "A": stress.BetaEstimate("A", 1.4, 0.7, 500, True, ""),
        "B": stress.BetaEstimate("B", 0.6, 0.5, 500, True, ""),
    }
    result = stress.apply_shock(
        weights={"A": 0.75, "B": 0.25},
        portfolio_value=1_000_000,
        index_shock=-0.20,
        mode=ShockMode.BETA_ADJUSTED,
        betas=betas,
    )
    expected_beta = 0.75 * 1.4 + 0.25 * 0.6
    assert result.portfolio_beta == pytest.approx(expected_beta)
    assert result.pct_loss == pytest.approx(expected_beta * 0.20)


def test_a_low_beta_portfolio_loses_less_than_the_index():
    betas = {"A": stress.BetaEstimate("A", 0.6, 0.5, 500, True, "")}
    result = stress.apply_shock(
        weights={"A": 1.0},
        portfolio_value=1_000_000,
        index_shock=-0.50,
        mode=ShockMode.BETA_ADJUSTED,
        betas=betas,
    )
    assert result.pct_loss == pytest.approx(0.30)


def test_holding_impacts_decompose_the_loss_exactly():
    result = stress.apply_shock(
        weights={"A": 0.3, "B": 0.5, "C": 0.2},
        portfolio_value=1_000_000,
        index_shock=-0.25,
    )
    assert sum(i.loss for i in result.holding_impacts) == pytest.approx(result.loss)
    assert sum(i.contribution_to_portfolio_loss_pct for i in result.holding_impacts) == (
        pytest.approx(1.0)
    )


def test_a_high_beta_holding_is_floored_at_a_total_loss_not_a_negative_value():
    betas = {"A": stress.BetaEstimate("A", 2.5, 0.7, 500, True, "")}
    result = stress.apply_shock(
        weights={"A": 1.0},
        portfolio_value=1_000_000,
        index_shock=-0.60,
        mode=ShockMode.BETA_ADJUSTED,
        betas=betas,
    )
    assert result.portfolio_value_after == pytest.approx(0.0)
    assert any("Floored at zero" in note for note in result.notes)


def test_beta_mode_always_states_the_crisis_convergence_caveat():
    result = stress.apply_shock(
        weights={"A": 1.0},
        portfolio_value=1_000_000,
        index_shock=-0.30,
        mode=ShockMode.BETA_ADJUSTED,
        betas={"A": stress.BetaEstimate("A", 0.7, 0.6, 500, True, "")},
    )
    assert any("converge towards 1" in note for note in result.notes)


def test_weak_betas_are_called_out():
    result = stress.apply_shock(
        weights={"A": 1.0},
        portfolio_value=1_000_000,
        index_shock=-0.30,
        mode=ShockMode.BETA_ADJUSTED,
        betas={"A": stress.BetaEstimate("A", 1.1, 0.05, 500, True, "")},
    )
    assert any("under 25%" in note for note in result.notes)


def test_a_positive_shock_is_refused():
    with pytest.raises(ValueError, match="must be negative"):
        stress.apply_shock(weights={"A": 1.0}, portfolio_value=1_000, index_shock=0.10)


def test_an_absurd_shock_is_refused_as_a_data_entry_error():
    with pytest.raises(ValueError, match="ceiling"):
        stress.apply_shock(
            weights={"A": 1.0}, portfolio_value=1_000, index_shock=-0.999
        )
