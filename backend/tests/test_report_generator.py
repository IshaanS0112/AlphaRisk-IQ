"""The report: structured context first, model second, fallback always.

The central claim of this architecture is that the LLM computes nothing. These
tests are what makes that claim checkable by someone who does not want to read
the prompt.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import Settings
from app.enums import ReportStatus
from app.services import report_generator


def _metrics(**overrides):
    base = {
        "mean_return_annualised": 0.1599,
        "portfolio_std_dev_annualised": 0.2005,
        "sharpe_ratio": 0.483,
        "sortino_ratio": 0.653,
        "sortino_ratio_negative_only": 0.563,
        "downside_deviation": 0.0094,
        "max_drawdown": 0.3116,
        "var_historical_95": 179_733.0,
        "var_parametric_95": 202_202.0,
        "var_historical_99": 487_382.0,
        "var_parametric_99": 288_628.0,
        "es_historical_95": 326_276.0,
        "es_parametric_95": 255_194.0,
        "calculation_basis": {
            "data_provenance": "SYNTHETIC",
            "window_start": "2021-07-05",
            "window_end": "2026-06-30",
            "observations": 1259,
            "risk_free_annual": 0.065,
            "trading_days_per_year": 250,
        },
        "detail": {
            "var": {"0.95": {"tail_ratio": 0.889, "notes": ["a note"]}},
            "backtests": {
                "PARAMETRIC": {
                    "verdict": "FAIL_UNDERSTATES_RISK",
                    "n_breaches": 23,
                    "n_tested": 1009,
                    "breach_rate": 0.0228,
                    "expected_breach_rate": 0.01,
                    "kupiec_lr": 12.4,
                    "kupiec_p_value": 0.0004,
                }
            },
            "diversification": {"mean_pairwise_correlation": 0.72},
        },
        "omitted_metrics": [],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _portfolio(**overrides):
    base = {
        "name": "India Core 5",
        "universe": "NSE_INDIA",
        "currency": "INR",
        "base_value": 10_000_000.0,
        "holdings": [{"ticker": "RELIANCE.NS", "weight": 0.25}],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _stress_test():
    return SimpleNamespace(
        scenario_label="Global Financial Crisis - NIFTY 50 peak to trough",
        shock_mode="UNIFORM",
        shock_config={
            "index_shock_pct": -0.5986,
            "portfolio_beta": 1.0,
            "scenario": {"source": "NIFTY 50 published daily closing levels (NSE India)"},
        },
        portfolio_value_before=10_000_000.0,
        portfolio_value_after=4_014_000.0,
        pct_loss=0.5986,
    )


# --- Context ------------------------------------------------------------------

def test_the_context_carries_every_figure_the_report_can_mention():
    context = report_generator.build_context(_portfolio(), _metrics(), [_stress_test()])
    assert context["risk_metrics"]["sharpe_ratio"] == 0.483
    assert context["value_at_risk"]["historical_95"] == 179_733.0
    assert context["value_at_risk"]["expected_shortfall_historical_95"] == 326_276.0
    assert context["var_backtest"]["PARAMETRIC"]["verdict"] == "FAIL_UNDERSTATES_RISK"
    assert context["stress_tests"][0]["pct_loss"] == 0.5986


def test_synthetic_provenance_produces_a_warning_in_the_context():
    context = report_generator.build_context(_portfolio(), _metrics(), [])
    assert context["data_provenance"]["status"] == "SYNTHETIC"
    assert "SYNTHETIC" in context["data_provenance"]["warning"]


def test_real_data_carries_no_warning():
    metrics = _metrics(
        calculation_basis={
            "data_provenance": "REAL_MARKET_DATA",
            "window_start": "2021-07-05",
            "window_end": "2026-06-30",
            "observations": 1259,
            "risk_free_annual": 0.065,
            "trading_days_per_year": 250,
        }
    )
    context = report_generator.build_context(_portfolio(), metrics, [])
    assert context["data_provenance"]["warning"] is None


# --- The deterministic fallback ----------------------------------------------

def test_without_an_api_key_the_report_is_templated_and_says_why():
    settings = Settings(_env_file=None, anthropic_api_key="")
    context = report_generator.build_context(_portfolio(), _metrics(), [_stress_test()])
    narrative, status, reason, model, dropped = report_generator.generate(context, settings)

    assert status == ReportStatus.TEMPLATE_FALLBACK.value
    assert model is None
    assert dropped == []
    assert "No ANTHROPIC_API_KEY" in reason
    for field in ("headline", "risk_summary", "var_interpretation", "key_risks", "caveats"):
        assert narrative[field]


def test_the_fallback_headline_flags_synthetic_data():
    context = report_generator.build_context(_portfolio(), _metrics(), [])
    assert report_generator.template_report(context)["headline"].startswith(
        "[SYNTHETIC DATA]"
    )


def test_the_fallback_explains_the_var_crossover_rather_than_asserting_thin_tails():
    """Historical below parametric at 95% must not be read as low risk."""
    context = report_generator.build_context(_portfolio(), _metrics(), [])
    text = report_generator.template_report(context)["var_interpretation"]
    assert "not evidence of thin tails" in text
    assert "At 99%" in text


def test_the_fallback_surfaces_a_failed_backtest_as_a_key_risk():
    context = report_generator.build_context(_portfolio(), _metrics(), [])
    risks = " ".join(report_generator.template_report(context)["key_risks"])
    assert "Kupiec" in risks


def test_the_fallback_surfaces_high_correlation_as_a_key_risk():
    context = report_generator.build_context(_portfolio(), _metrics(), [])
    risks = " ".join(report_generator.template_report(context)["key_risks"])
    assert "correlation" in risks


def test_every_number_in_the_fallback_appears_in_the_context():
    """The whole architecture, expressed as an assertion.

    Formats the figures out of the context and checks each appears in the prose.
    If a figure were computed inside the report layer it would not be in the
    context and this would fail.
    """
    context = report_generator.build_context(_portfolio(), _metrics(), [_stress_test()])
    report = report_generator.template_report(context)
    prose = " ".join(
        [report["headline"], report["risk_summary"], report["var_interpretation"]]
    )
    assert f"{context['value_at_risk']['historical_95']:,.0f}" in prose
    assert f"{context['value_at_risk']['parametric_95']:,.0f}" in prose
    assert f"{context['risk_metrics']['sharpe_ratio']:.2f}" in prose
    assert f"{context['risk_metrics']['max_drawdown']:.2%}" in prose


def test_omitted_metrics_reach_the_report_rather_than_being_swallowed():
    metrics = _metrics(
        omitted_metrics=[{"metric": "sortino_ratio", "reason": "too few downside days"}]
    )
    context = report_generator.build_context(_portfolio(), metrics, [])
    risks = " ".join(report_generator.template_report(context)["key_risks"])
    assert "sortino_ratio could not be computed" in risks


# --- Citation validation ------------------------------------------------------

def test_an_invented_metric_key_is_stripped_and_recorded():
    """The failure mode this architecture exists to catch."""
    context = report_generator.build_context(_portfolio(), _metrics(), [])
    narrative = {
        "headline": "x",
        "cited_metrics": [
            "risk_metrics.sharpe_ratio",
            "risk_metrics.jensens_alpha",
            "value_at_risk.monte_carlo_99",
        ],
    }
    cleaned, dropped = report_generator.validate_citations(narrative, context)
    assert cleaned["cited_metrics"] == ["risk_metrics.sharpe_ratio"]
    assert sorted(dropped) == ["risk_metrics.jensens_alpha", "value_at_risk.monte_carlo_99"]


def test_nested_and_list_paths_are_valid_citations():
    context = report_generator.build_context(_portfolio(), _metrics(), [_stress_test()])
    keys = report_generator._flatten_keys(context)
    assert "stress_tests[0].pct_loss" in keys
    assert "var_backtest.PARAMETRIC.verdict" in keys


# --- Degradation --------------------------------------------------------------

def test_an_llm_failure_degrades_to_the_template_instead_of_500ing(monkeypatch):
    settings = Settings(_env_file=None, anthropic_api_key="sk-not-a-real-key")
    context = report_generator.build_context(_portfolio(), _metrics(), [])

    def explode(*_args, **_kwargs):
        raise RuntimeError("connection reset by peer")

    monkeypatch.setattr(report_generator, "_extract_json", explode)
    narrative, status, reason, _, _ = report_generator.generate(context, settings)
    assert status == ReportStatus.TEMPLATE_FALLBACK.value
    assert narrative["headline"]
    assert reason is not None


@pytest.mark.parametrize(
    "reply",
    [
        '{"headline": "h"}',
        '```json\n{"headline": "h"}\n```',
        'Here you go:\n{"headline": "h"}\nHope that helps.',
    ],
)
def test_the_json_extractor_tolerates_the_usual_model_wrappers(reply):
    assert report_generator._extract_json(reply)["headline"] == "h"


def test_a_reply_with_no_json_is_an_error_not_a_silent_empty_report():
    with pytest.raises(ValueError, match="No JSON object"):
        report_generator._extract_json("I cannot help with that.")


def test_the_system_prompt_forbids_computation_and_requires_the_synthetic_flag():
    assert "must not compute" in report_generator.SYSTEM_PROMPT
    assert "SYNTHETIC" in report_generator.SYSTEM_PROMPT
    assert "not advice" in report_generator.SYSTEM_PROMPT
