"""Risk metrics, stress tests and the narrated report.

Each POST runs one stage and appends a row; each GET returns the latest.
Appending rather than overwriting is deliberate - "the VaR moved when we extended
the window from one year to three" is the finding, not a detail to overwrite.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.enums import ReportStatus
from app.models import InvestmentReport
from app.routers.deps import AppSettings, CurrentPortfolio, CurrentUniverse, DbSession
from app.schemas import (
    InvestmentReportOut,
    RiskMetricsOut,
    RiskMetricsRequest,
    StressTestOut,
    StressTestRequest,
)
from app.services import analysis_pipeline as pipeline
from app.services import report_generator
from app.services.scenarios import load_scenarios

router = APIRouter(prefix="/portfolios", tags=["analysis"])


@router.post("/{portfolio_id}/compute-risk-metrics", response_model=RiskMetricsOut)
def compute_risk_metrics(
    portfolio: CurrentPortfolio,
    universe: CurrentUniverse,
    db: DbSession,
    settings: AppSettings,
    payload: RiskMetricsRequest | None = None,
):
    request = payload or RiskMetricsRequest()
    try:
        row, _ = pipeline.compute_risk_metrics(
            portfolio,
            db,
            settings,
            universe,
            start=request.window_start,
            end=request.window_end,
            risk_free_annual=request.risk_free_annual,
            run_backtest=request.run_backtest,
        )
    except pipeline.InsufficientData as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return row


@router.get("/{portfolio_id}/risk-metrics", response_model=RiskMetricsOut)
def get_risk_metrics(portfolio: CurrentPortfolio):
    if not portfolio.risk_metrics:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No risk metrics computed yet. POST /compute-risk-metrics first.",
        )
    return portfolio.risk_metrics[-1]


@router.post("/{portfolio_id}/stress-test", response_model=StressTestOut)
def stress_test(
    portfolio: CurrentPortfolio,
    universe: CurrentUniverse,
    db: DbSession,
    settings: AppSettings,
    payload: StressTestRequest,
):
    scenario = None
    if payload.scenario_name:
        scenarios = load_scenarios()
        if payload.scenario_name not in scenarios:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"Unknown scenario '{payload.scenario_name}'. "
                    f"Available: {', '.join(sorted(scenarios))}."
                ),
            )
        scenario = scenarios[payload.scenario_name]

    try:
        row = pipeline.run_stress_test(
            portfolio,
            db,
            settings,
            universe,
            scenario=scenario,
            custom_shock_pct=payload.custom_shock_pct,
            custom_label=payload.custom_label,
            mode=payload.mode,
            start=payload.window_start,
            end=payload.window_end,
        )
    except pipeline.InsufficientData as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return row


@router.get("/{portfolio_id}/stress-tests", response_model=list[StressTestOut])
def list_stress_tests(portfolio: CurrentPortfolio):
    return portfolio.stress_tests


@router.post("/{portfolio_id}/generate-report", response_model=InvestmentReportOut)
def generate_report(
    portfolio: CurrentPortfolio, db: DbSession, settings: AppSettings
):
    if not portfolio.risk_metrics:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No risk metrics computed yet. The report narrates over computed "
                "figures and has nothing to narrate until they exist - which is the "
                "point of the architecture, not a limitation of it."
            ),
        )

    context = report_generator.build_context(
        portfolio, portfolio.risk_metrics[-1], list(portfolio.stress_tests)
    )
    narrative, report_status, reason, model_used, dropped = report_generator.generate(
        context, settings
    )

    row = InvestmentReport(
        portfolio_id=portfolio.id,
        structured_context=context,
        ai_narrative=narrative,
        status=report_status,
        fallback_reason=reason,
        model_used=model_used,
        dropped_citations=dropped,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/{portfolio_id}/investment-report", response_model=InvestmentReportOut)
def get_report(portfolio: CurrentPortfolio):
    if not portfolio.investment_reports:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No report generated yet. POST /generate-report first.",
        )
    return portfolio.investment_reports[-1]


@router.get("/{portfolio_id}/report-status")
def report_status(portfolio: CurrentPortfolio, settings: AppSettings):
    """Whether a generated report would be narrated or templated, and why."""
    return {
        "llm_configured": bool(settings.anthropic_api_key),
        "model": settings.anthropic_model if settings.anthropic_api_key else None,
        "would_produce": (
            ReportStatus.LLM.value
            if settings.anthropic_api_key
            else ReportStatus.TEMPLATE_FALLBACK.value
        ),
        "note": (
            "Without an API key the report is generated deterministically from the same "
            "structured context. Every figure is identical; only the prose differs."
        ),
    }
