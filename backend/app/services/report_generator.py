"""The investment report: structured context first, model second, always.

The claim this project makes is that the LLM does not compute anything. The way
that claim is made checkable rather than asserted:

1. :func:`build_context` assembles every figure the report may mention from rows
   already in the database. This dict is written to ``investment_reports.
   structured_context`` **before** the API call is made, so it exists even if the
   call fails.
2. The prompt hands over that dict and forbids arithmetic. The model's job is
   interpretation - which risk is the binding one, what the Sharpe/Sortino gap
   implies about the shape of the return distribution, whether the stress loss is
   survivable - not calculation.
3. Every figure the model cites must name a key that exists in the context. Any
   key it invents is stripped and recorded in ``dropped_citations``. A model
   inventing a metric key is precisely the failure mode this architecture exists
   to catch, so it is logged as a finding rather than swallowed.
4. With no API key, or on any failure, :func:`template_report` produces the same
   report deterministically from the same context. Every number is identical;
   only the prose is missing.

The line to have ready: *"The model doesn't calculate VaR or Sharpe - my code
does, with the formulas in the methodology endpoint. The model writes the
narrative interpretation, and I can show you the exact structured payload it was
given, because it's stored on the report row."*
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import Settings
from app.enums import ReportStatus

logger = logging.getLogger("alphariskiq.report")

SYSTEM_PROMPT = """You are a risk analyst writing the narrative section of a \
portfolio risk report.

Every number you need has already been computed and is supplied to you as JSON. \
You must not compute, estimate, adjust, annualise, convert or infer any figure. \
If a quantity is not in the supplied context, it does not go in the report.

Write for a reader who understands finance but has not seen this portfolio. Be \
specific and cite figures. Do not hedge everything; say which risk is the \
binding one and why.

Return ONLY a JSON object, no prose outside it, matching exactly:

{
  "headline": "one sentence, under 140 characters, the single most important thing",
  "risk_summary": "2-4 sentences on return, volatility and what Sharpe vs Sortino imply about the shape of the return distribution",
  "var_interpretation": "2-4 sentences comparing the historical and parametric VaR figures and what the gap means about tail risk",
  "stress_interpretation": "2-3 sentences on the stress results; empty string if no stress test was supplied",
  "key_risks": ["3 to 5 short strings, each naming a specific concern"],
  "cited_metrics": ["the exact context keys you used, dotted paths like risk_metrics.sharpe_ratio"],
  "caveats": ["2 to 4 short strings on what these numbers do not tell the reader"]
}

Hard rules:
- Cite only keys that exist in the context. An invented key will be stripped and flagged.
- If the context says the data provenance is SYNTHETIC, your headline must say so explicitly.
- Do not recommend buying or selling anything. This is a risk report, not advice."""


def build_context(
    portfolio: Any,
    metrics: Any,
    stress_tests: list[Any],
) -> dict:
    """Assemble the frozen payload. Nothing is computed here that is not a lookup."""
    basis = dict(metrics.calculation_basis or {})
    detail = dict(metrics.detail or {})
    var_detail = detail.get("var", {})
    var95 = var_detail.get("0.95", {})
    backtests = detail.get("backtests", {})

    context: dict[str, Any] = {
        "portfolio": {
            "name": portfolio.name,
            "universe": portfolio.universe,
            "currency": portfolio.currency,
            "base_value": portfolio.base_value,
            "holdings": portfolio.holdings,
            "holding_count": len(portfolio.holdings),
        },
        "data_provenance": {
            "status": basis.get("data_provenance"),
            "window_start": basis.get("window_start"),
            "window_end": basis.get("window_end"),
            "observations": basis.get("observations"),
            "warning": (
                "This portfolio's risk figures were computed on SYNTHETIC price data. "
                "They demonstrate the calculations and say nothing about any real asset."
                if basis.get("data_provenance") != "REAL_MARKET_DATA"
                else None
            ),
        },
        "risk_metrics": {
            "mean_return_annualised": metrics.mean_return_annualised,
            "volatility_annualised": metrics.portfolio_std_dev_annualised,
            "sharpe_ratio": metrics.sharpe_ratio,
            "sortino_ratio": metrics.sortino_ratio,
            "sortino_ratio_negative_only": metrics.sortino_ratio_negative_only,
            "downside_deviation_daily": metrics.downside_deviation,
            "max_drawdown": metrics.max_drawdown,
            "risk_free_annual_used": basis.get("risk_free_annual"),
            "trading_days_per_year": basis.get("trading_days_per_year"),
        },
        "value_at_risk": {
            "confidence": 0.95,
            "historical_95": metrics.var_historical_95,
            "parametric_95": metrics.var_parametric_95,
            "historical_99": metrics.var_historical_99,
            "parametric_99": metrics.var_parametric_99,
            "expected_shortfall_historical_95": metrics.es_historical_95,
            "expected_shortfall_parametric_95": metrics.es_parametric_95,
            "historical_over_parametric_ratio": var95.get("tail_ratio"),
            "engine_notes": var95.get("notes", []),
        },
        "var_backtest": {
            method: {
                "verdict": result.get("verdict"),
                "breaches": result.get("n_breaches"),
                "days_tested": result.get("n_tested"),
                "breach_rate": result.get("breach_rate"),
                "expected_breach_rate": result.get("expected_breach_rate"),
                "kupiec_lr": result.get("kupiec_lr"),
                "kupiec_p_value": result.get("kupiec_p_value"),
            }
            for method, result in backtests.items()
        },
        "diversification": detail.get("diversification", {}),
        "stress_tests": [
            {
                "scenario": test.scenario_label,
                "mode": test.shock_mode,
                "index_shock_pct": (test.shock_config or {}).get("index_shock_pct"),
                "portfolio_beta": (test.shock_config or {}).get("portfolio_beta"),
                "value_before": test.portfolio_value_before,
                "value_after": test.portfolio_value_after,
                "pct_loss": test.pct_loss,
                "source": ((test.shock_config or {}).get("scenario") or {}).get("source"),
            }
            for test in stress_tests
        ],
        "omitted_metrics": metrics.omitted_metrics or [],
        "methodology_note": (
            "Every figure above was computed deterministically by the backend from the "
            "loaded price series. The narrative model is given this object and is "
            "forbidden from computing anything."
        ),
    }
    return context


def _flatten_keys(payload: Any, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else key
            keys.add(path)
            keys |= _flatten_keys(value, path)
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            keys |= _flatten_keys(value, f"{prefix}[{index}]")
    return keys


def validate_citations(narrative: dict, context: dict) -> tuple[dict, list[str]]:
    """Strip cited keys that are not in the context; return them for the record."""
    valid = _flatten_keys(context)
    cited = narrative.get("cited_metrics") or []
    kept = [c for c in cited if c in valid]
    dropped = [c for c in cited if c not in valid]
    return {**narrative, "cited_metrics": kept}, dropped


def template_report(context: dict) -> dict:
    """The deterministic report. Same numbers, no model, no network.

    This is not a degraded mode to apologise for. It is the reference the LLM
    output is checked against: if the narrative ever disagrees with this, the
    narrative is wrong.
    """
    metrics = context["risk_metrics"]
    var = context["value_at_risk"]
    portfolio = context["portfolio"]
    provenance = context["data_provenance"]
    currency = portfolio["currency"]

    def money(value: float | None) -> str:
        return "n/a" if value is None else f"{currency} {value:,.0f}"

    def ratio(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.2f}"

    def pct(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.2%}"

    synthetic = provenance.get("status") != "REAL_MARKET_DATA"
    prefix = "[SYNTHETIC DATA] " if synthetic else ""

    headline = (
        f"{prefix}{portfolio['name']}: {pct(metrics['volatility_annualised'])} "
        f"annualised volatility, Sharpe {ratio(metrics['sharpe_ratio'])}, "
        f"95% one-day VaR {money(var['historical_95'])} (historical)."
    )

    risk_lines = [
        f"Over {provenance.get('observations')} trading days from "
        f"{provenance.get('window_start')} to {provenance.get('window_end')}, the "
        f"portfolio returned {pct(metrics['mean_return_annualised'])} annualised with "
        f"{pct(metrics['volatility_annualised'])} annualised volatility.",
        f"Sharpe is {ratio(metrics['sharpe_ratio'])} against a risk-free rate of "
        f"{pct(metrics['risk_free_annual_used'])}; Sortino is "
        f"{ratio(metrics['sortino_ratio'])}.",
    ]
    if metrics["sharpe_ratio"] and metrics["sortino_ratio"]:
        if metrics["sortino_ratio"] > metrics["sharpe_ratio"]:
            risk_lines.append(
                "Sortino exceeds Sharpe, so the volatility being penalised by Sharpe is "
                "disproportionately upside volatility - which an investor is not "
                "usually trying to avoid."
            )
        else:
            risk_lines.append(
                "Sortino sits below Sharpe, so downside deviation is large relative to "
                "total volatility: the losses are concentrated rather than symmetric."
            )
    risk_lines.append(f"Maximum drawdown over the window was {pct(metrics['max_drawdown'])}.")

    var_lines = [
        f"95% one-day VaR is {money(var['historical_95'])} on the historical method and "
        f"{money(var['parametric_95'])} on the parametric method.",
    ]
    if var["historical_95"] and var["parametric_95"]:
        gap = var["historical_95"] / var["parametric_95"] - 1.0
        if gap > 0:
            var_lines.append(
                f"The historical figure is {gap:.1%} larger: the normal fit assigns too "
                "little probability to losses this size, so it understates the tail at "
                "this confidence level."
            )
        else:
            var_lines.append(
                f"The parametric figure is {-gap / (1 + gap):.1%} larger, which is not "
                "evidence of thin tails - a fat-tailed distribution has a more peaked "
                "body as well as fatter extremes, and its quantile only overtakes the "
                "normal's between 95% and 99% confidence."
            )
    if var["historical_99"] and var["parametric_99"]:
        gap99 = var["historical_99"] / var["parametric_99"] - 1.0
        var_lines.append(
            f"At 99% the ordering is "
            f"{money(var['historical_99'])} historical against "
            f"{money(var['parametric_99'])} parametric, a "
            f"{'gap of ' + format(gap99, '.1%') if gap99 > 0 else 'shortfall of ' + format(-gap99, '.1%')} "
            "- which is where the tail behaviour actually shows up."
        )
    es_h = var["expected_shortfall_historical_95"]
    es_p = var["expected_shortfall_parametric_95"]
    var_lines.append(
        f"Expected shortfall at 95% - the average loss on the days VaR is breached - is "
        f"{money(es_h)} historical against {money(es_p)} parametric."
    )
    if es_h and es_p and es_h > es_p and var["historical_95"] <= var["parametric_95"]:
        var_lines.append(
            "The two measures disagree, and both are right: the normal fit is "
            "conservative about the threshold and optimistic about what lies beyond it. "
            "VaR reads one point; ES averages the whole tail."
        )

    stress_lines = []
    for test in context["stress_tests"]:
        stress_lines.append(
            f"{test['scenario']} ({test['mode']}): "
            f"{money(test['value_before'])} -> {money(test['value_after'])}, a loss of "
            f"{pct(test['pct_loss'])}."
        )

    key_risks = []
    if (
        var["expected_shortfall_historical_95"]
        and var["expected_shortfall_parametric_95"]
        and var["expected_shortfall_historical_95"] > var["expected_shortfall_parametric_95"]
    ):
        key_risks.append(
            "Fat tails: realised losses beyond the 95% threshold average more than a "
            "normal distribution predicts."
        )
    for method, result in (context.get("var_backtest") or {}).items():
        if result.get("verdict", "").startswith("FAIL"):
            key_risks.append(
                f"{method} VaR fails Kupiec backtesting "
                f"({result.get('breaches')} breaches in {result.get('days_tested')} days "
                f"against {result.get('expected_breach_rate'):.1%} expected)."
            )
    diversification = context.get("diversification") or {}
    if (diversification.get("mean_pairwise_correlation") or 0) > 0.6:
        key_risks.append(
            f"Mean pairwise correlation of "
            f"{diversification['mean_pairwise_correlation']:.2f}: the holdings move "
            "largely together, so the diversification is thinner than the holding count "
            "suggests."
        )
    if context["stress_tests"]:
        worst = max(context["stress_tests"], key=lambda t: t["pct_loss"])
        key_risks.append(
            f"Worst modelled scenario ({worst['scenario']}) costs {pct(worst['pct_loss'])}."
        )
    for omission in context.get("omitted_metrics") or []:
        key_risks.append(f"{omission.get('metric')} could not be computed.")
    if not key_risks:
        key_risks.append("No threshold-based concern was triggered by these figures.")

    caveats = [
        "Every figure is an estimate from one finite historical window and is not a "
        "forecast.",
        "VaR is a threshold, not a worst case: it says nothing about how bad the "
        "breaches are. That is what the expected shortfall figure is for.",
        "Stress tests reprice in a single step with no path, liquidity or "
        "second-order effects.",
    ]
    if synthetic:
        caveats.insert(0, provenance["warning"])

    return {
        "headline": headline,
        "risk_summary": " ".join(risk_lines),
        "var_interpretation": " ".join(var_lines),
        "stress_interpretation": " ".join(stress_lines),
        "key_risks": key_risks[:5],
        "cited_metrics": [
            "risk_metrics.sharpe_ratio",
            "risk_metrics.sortino_ratio",
            "risk_metrics.volatility_annualised",
            "risk_metrics.max_drawdown",
            "value_at_risk.historical_95",
            "value_at_risk.parametric_95",
            "value_at_risk.expected_shortfall_historical_95",
        ],
        "caveats": caveats[:4],
    }


def _extract_json(text: str) -> dict:
    """Parse the model's reply, tolerating a fenced code block around the JSON."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        cleaned = cleaned.rsplit("```", 1)[0]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in the model reply.")
    return json.loads(cleaned[start : end + 1])


REQUIRED_FIELDS = (
    "headline",
    "risk_summary",
    "var_interpretation",
    "key_risks",
    "caveats",
)


def generate(context: dict, settings: Settings) -> tuple[dict, str, str | None, str | None, list[str]]:
    """Return ``(narrative, status, fallback_reason, model_used, dropped_citations)``."""
    if not settings.anthropic_api_key:
        return (
            template_report(context),
            ReportStatus.TEMPLATE_FALLBACK.value,
            "No ANTHROPIC_API_KEY configured. Every figure below is identical to what "
            "the narrated version would contain; only the prose differs.",
            None,
            [],
        )

    try:
        import anthropic

        client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_seconds
        )
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=settings.llm_max_tokens,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Portfolio risk context (the only figures you may use):\n\n"
                        + json.dumps(context, indent=2, default=str)
                    ),
                }
            ],
        )
        narrative = _extract_json(response.content[0].text)

        missing = [field for field in REQUIRED_FIELDS if not narrative.get(field)]
        if missing:
            raise ValueError(f"Model reply omitted required fields: {', '.join(missing)}")

        dropped: list[str] = []
        if settings.drop_uncited_metrics:
            narrative, dropped = validate_citations(narrative, context)

        return (
            narrative,
            ReportStatus.LLM.value,
            None,
            settings.anthropic_model,
            dropped,
        )
    except Exception as exc:  # noqa: BLE001 - any failure must degrade, not 500
        logger.warning("LLM narration failed, falling back to template: %s", exc)
        return (
            template_report(context),
            ReportStatus.TEMPLATE_FALLBACK.value,
            f"{type(exc).__name__}: {exc}",
            None,
            [],
        )
