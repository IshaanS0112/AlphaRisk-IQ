"""The HTTP contract, exercised against the real app on SQLite."""

from __future__ import annotations

import pytest

from tests.conftest import NSE_HOLDINGS


# --- Meta ---------------------------------------------------------------------

def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_methodology_publishes_every_formula_and_convention(client):
    body = client.get("/methodology").json()
    assert "sharpe_ratio" in body["formulas"]
    assert "sortino_ratio_STANDARD" in body["formulas"]
    assert "sortino_ratio_NEGATIVE_ONLY_STDDEV" in body["formulas"]
    assert "kupiec_pof" in body["formulas"]
    assert body["conventions"]["var_sign"].startswith("All VaR and ES figures")
    assert body["conventions"]["return_method"] == "SIMPLE"
    # The V1 boundary is published rather than left to be discovered.
    assert "monte_carlo_var" in body["not_implemented_in_v1"]
    assert "christoffersen_independence_test" in body["not_implemented_in_v1"]


def test_methodology_recomputes_scenario_magnitudes_from_levels(client):
    scenarios = client.get("/methodology").json()["scenarios"]
    covid = scenarios["covid_crash_2020_nifty"]
    assert covid["shock_pct"] == pytest.approx(
        covid["trough_level"] / covid["peak_level"] - 1
    )


def test_universes_report_what_price_data_is_on_disk(client):
    body = client.get("/universes").json()
    assert set(body) == {"NSE_INDIA", "US"}
    assert "SYNTHETIC" in body["NSE_INDIA"]["price_data_available"]


# --- Market data --------------------------------------------------------------

def test_loading_market_data_reports_provenance_and_warns_about_synthetic(client):
    body = client.post("/market-data/load", json={"universe": "NSE_INDIA"}).json()
    assert body["provenance"] == "SYNTHETIC"
    assert body["tickers_loaded"] == 8
    assert body["benchmark_symbol"] == "^NSEI"
    assert any("SYNTHETIC" in warning for warning in body["warnings"])


def test_market_data_status_lists_every_loaded_series(loaded_client):
    body = loaded_client.get("/market-data/status").json()
    assert len(body["series"]) == 8
    assert all(row["provenance"] == "SYNTHETIC" for row in body["series"])
    assert body["recent_loads"][0]["universe"] == "NSE_INDIA"


def test_an_unknown_universe_is_rejected(client):
    response = client.post("/market-data/load", json={"universe": "MOON"})
    assert response.status_code == 422


# --- Portfolios ---------------------------------------------------------------

def test_weights_are_normalised_and_the_submitted_sum_recorded(loaded_client):
    body = loaded_client.post(
        "/portfolios",
        json={"name": "P", "universe": "NSE_INDIA", "holdings": NSE_HOLDINGS},
    ).json()
    assert sum(h["weight"] for h in body["holdings"]) == pytest.approx(1.0)
    assert body["holdings"][0]["submitted_weight"] == 25
    assert body["currency"] == "INR"


def test_a_ticker_outside_the_universe_is_refused_with_the_available_list(loaded_client):
    response = loaded_client.post(
        "/portfolios",
        json={
            "name": "P",
            "universe": "NSE_INDIA",
            "holdings": [{"ticker": "AAPL", "weight": 1}],
        },
    )
    assert response.status_code == 422
    assert "RELIANCE.NS" in response.json()["detail"]


def test_duplicate_holdings_are_refused(loaded_client):
    response = loaded_client.post(
        "/portfolios",
        json={
            "name": "P",
            "universe": "NSE_INDIA",
            "holdings": [
                {"ticker": "TCS.NS", "weight": 50},
                {"ticker": "TCS.NS", "weight": 50},
            ],
        },
    )
    assert response.status_code == 422


def test_a_negative_weight_is_refused_because_this_is_long_only(loaded_client):
    response = loaded_client.post(
        "/portfolios",
        json={
            "name": "P",
            "universe": "NSE_INDIA",
            "holdings": [{"ticker": "TCS.NS", "weight": -10}],
        },
    )
    assert response.status_code == 422


def test_a_missing_portfolio_is_a_404(client):
    response = client.get("/portfolios/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


# --- Risk metrics -------------------------------------------------------------

def test_metrics_are_404_until_they_are_computed(loaded_client, portfolio_id):
    assert loaded_client.get(f"/portfolios/{portfolio_id}/risk-metrics").status_code == 404


def test_computing_metrics_returns_the_whole_block_with_its_basis(
    loaded_client, portfolio_id
):
    body = loaded_client.post(
        f"/portfolios/{portfolio_id}/compute-risk-metrics", json={}
    ).json()

    assert body["sharpe_ratio"] is not None
    assert body["sortino_ratio"] is not None
    assert body["sortino_ratio_negative_only"] is not None
    assert body["var_historical_95"] > 0
    assert body["var_parametric_95"] > 0
    assert body["es_historical_95"] > body["var_historical_95"]

    basis = body["calculation_basis"]
    assert basis["data_provenance"] == "SYNTHETIC"
    assert basis["trading_days_per_year"] == 250
    assert basis["risk_free_annual"] == 0.065
    assert basis["rebalancing"] == "DAILY_CONSTANT_WEIGHT"
    assert basis["return_method"] == "SIMPLE"
    assert "forward-filled" in basis["alignment_policy"]


def test_a_risk_free_override_is_honoured_and_recorded(loaded_client, portfolio_id):
    default = loaded_client.post(
        f"/portfolios/{portfolio_id}/compute-risk-metrics", json={}
    ).json()
    overridden = loaded_client.post(
        f"/portfolios/{portfolio_id}/compute-risk-metrics",
        json={"risk_free_annual": 0.20},
    ).json()
    assert overridden["calculation_basis"]["risk_free_annual"] == 0.20
    assert overridden["sharpe_ratio"] < default["sharpe_ratio"]


def test_results_are_appended_so_the_history_survives(loaded_client, portfolio_id):
    loaded_client.post(f"/portfolios/{portfolio_id}/compute-risk-metrics", json={})
    second = loaded_client.post(
        f"/portfolios/{portfolio_id}/compute-risk-metrics", json={"risk_free_annual": 0.0}
    ).json()
    latest = loaded_client.get(f"/portfolios/{portfolio_id}/risk-metrics").json()
    assert latest["id"] == second["id"]


def test_both_var_backtests_run_and_are_reported(loaded_client, portfolio_id):
    body = loaded_client.post(
        f"/portfolios/{portfolio_id}/compute-risk-metrics", json={}
    ).json()
    backtests = body["detail"]["backtests"]
    assert set(backtests) == {"HISTORICAL", "PARAMETRIC"}
    for result in backtests.values():
        assert result["n_tested"] > 0
        assert result["kupiec_lr"] is not None
        assert result["verdict"] in {
            "PASS",
            "FAIL_UNDERSTATES_RISK",
            "FAIL_OVERSTATES_RISK",
        }


def test_computing_metrics_without_price_data_explains_what_to_do(client):
    portfolio_id = client.post(
        "/portfolios",
        json={"name": "P", "universe": "US", "holdings": [{"ticker": "AAPL", "weight": 1}]},
    ).json()["id"]
    response = client.post(f"/portfolios/{portfolio_id}/compute-risk-metrics", json={})
    assert response.status_code == 409
    assert "market-data/load" in response.json()["detail"]


# --- Stress tests -------------------------------------------------------------

def test_a_named_scenario_reprices_the_portfolio(loaded_client, portfolio_id):
    body = loaded_client.post(
        f"/portfolios/{portfolio_id}/stress-test",
        json={"scenario_name": "gfc_peak_to_trough_nifty", "mode": "UNIFORM"},
    ).json()
    assert body["pct_loss"] == pytest.approx(0.5986, abs=5e-4)
    assert body["shock_config"]["scenario"]["peak_level"] == 6287.85
    assert body["portfolio_value_after"] < body["portfolio_value_before"]


def test_beta_adjusted_mode_estimates_betas_and_records_them(
    loaded_client, portfolio_id
):
    body = loaded_client.post(
        f"/portfolios/{portfolio_id}/stress-test",
        json={"scenario_name": "covid_crash_2020_nifty", "mode": "BETA_ADJUSTED"},
    ).json()
    betas = body["calculation_basis"]["betas"]
    assert len(betas) == 5
    assert all(b["estimated"] for b in betas.values())
    # The consumer staple must come out below the financials.
    assert betas["ITC.NS"]["beta"] < betas["HDFCBANK.NS"]["beta"]


def test_a_custom_shock_is_labelled_as_user_supplied(loaded_client, portfolio_id):
    body = loaded_client.post(
        f"/portfolios/{portfolio_id}/stress-test",
        json={"custom_shock_pct": -0.20, "custom_label": "Board scenario"},
    ).json()
    assert body["pct_loss"] == pytest.approx(0.20)
    assert body["shock_config"]["scenario"]["verification_status"] == "USER_SUPPLIED"


def test_applying_another_markets_drawdown_is_refused(loaded_client, portfolio_id):
    response = loaded_client.post(
        f"/portfolios/{portfolio_id}/stress-test",
        json={"scenario_name": "covid_crash_2020"},
    )
    assert response.status_code == 422
    assert "category error" in response.json()["detail"]


def test_supplying_both_a_scenario_and_a_custom_shock_is_refused(
    loaded_client, portfolio_id
):
    response = loaded_client.post(
        f"/portfolios/{portfolio_id}/stress-test",
        json={"scenario_name": "covid_crash_2020_nifty", "custom_shock_pct": -0.2},
    )
    assert response.status_code == 422


def test_an_unknown_scenario_lists_the_available_ones(loaded_client, portfolio_id):
    response = loaded_client.post(
        f"/portfolios/{portfolio_id}/stress-test", json={"scenario_name": "y2k"}
    )
    assert response.status_code == 404
    assert "gfc_peak_to_trough_nifty" in response.json()["detail"]


def test_a_positive_custom_shock_is_refused(loaded_client, portfolio_id):
    response = loaded_client.post(
        f"/portfolios/{portfolio_id}/stress-test", json={"custom_shock_pct": 0.1}
    )
    assert response.status_code == 422


# --- Report -------------------------------------------------------------------

def test_a_report_cannot_be_generated_before_the_metrics_exist(
    loaded_client, portfolio_id
):
    response = loaded_client.post(f"/portfolios/{portfolio_id}/generate-report")
    assert response.status_code == 409
    assert "nothing to narrate" in response.json()["detail"]


def test_the_report_stores_the_context_it_was_built_from(loaded_client, portfolio_id):
    loaded_client.post(f"/portfolios/{portfolio_id}/compute-risk-metrics", json={})
    loaded_client.post(
        f"/portfolios/{portfolio_id}/stress-test",
        json={"scenario_name": "gfc_peak_to_trough_nifty"},
    )
    body = loaded_client.post(f"/portfolios/{portfolio_id}/generate-report").json()

    assert body["status"] == "TEMPLATE_FALLBACK"
    assert body["structured_context"]["risk_metrics"]["sharpe_ratio"] is not None
    assert body["structured_context"]["stress_tests"][0]["pct_loss"] > 0
    assert body["ai_narrative"]["headline"].startswith("[SYNTHETIC DATA]")
    assert body["dropped_citations"] == []


def test_report_status_says_what_would_happen_before_you_run_it(
    loaded_client, portfolio_id
):
    body = loaded_client.get(f"/portfolios/{portfolio_id}/report-status").json()
    assert body["llm_configured"] is False
    assert body["would_produce"] == "TEMPLATE_FALLBACK"


# --- Deletion -----------------------------------------------------------------

def test_deleting_a_portfolio_cascades(loaded_client, portfolio_id):
    loaded_client.post(f"/portfolios/{portfolio_id}/compute-risk-metrics", json={})
    assert loaded_client.delete(f"/portfolios/{portfolio_id}").status_code == 204
    assert loaded_client.get(f"/portfolios/{portfolio_id}").status_code == 404
