"""AlphaRisk IQ API entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db.session import Base, engine
from app.enums import Rebalancing, ShockMode, SortinoConvention
from app.routers import analysis, market, portfolios
from app.services import market_data
from app.services.scenarios import load_scenarios
from app.services.universes import load_universes

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("alphariskiq")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # create_all is adequate here because the schema is append-only for V1. A
    # migration tool (Alembic) is the correct answer the moment a column needs to
    # change shape - noted in docs/architecture.md.
    Base.metadata.create_all(bind=engine)

    settings = get_settings()
    for name in load_universes():
        available = market_data.available_provenances(name)
        if not available:
            logger.warning(
                "No price data on disk for %s. Run "
                "`python backend/scripts/generate_synthetic_prices.py` for the labelled "
                "fixture or `python backend/scripts/fetch_prices.py` for real data.",
                name,
            )
        else:
            logger.info("%s price data available: %s", name, ", ".join(available))

    if not settings.anthropic_api_key:
        logger.info(
            "No ANTHROPIC_API_KEY configured. Investment reports will use the "
            "deterministic template fallback - every risk figure is identical, only "
            "the prose is missing."
        )
    yield


settings = get_settings()

app = FastAPI(
    title="AlphaRisk IQ API",
    version="1.0.0",
    description=(
        "Portfolio risk and decision intelligence. Sharpe and Sortino under both "
        "downside-deviation conventions, historical and parametric Value at Risk with "
        "expected shortfall, Kupiec-tested VaR backtesting, and beta-adjusted scenario "
        "stress testing against index drawdowns derived from cited closing levels. "
        "Every figure is computed deterministically; the LLM only narrates."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (portfolios, analysis, market):
    app.include_router(module.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/methodology", tags=["meta"])
def methodology() -> dict[str, object]:
    """Every formula, convention and parameter currently in force.

    Exposed as an endpoint because the claim this project makes - that the risk
    figures are computed, not generated - is only checkable if the conventions
    behind them are visible without reading the source. Two correct
    implementations of "the Sharpe ratio" routinely disagree; this is what makes
    the disagreement diagnosable.
    """
    return {
        "formulas": {
            "sharpe_ratio": (
                "((mean(r) - rf_periodic) / stdev(r)) * sqrt(T), with rf_periodic = "
                "(1+rf_annual)^(1/T) - 1"
            ),
            "sortino_ratio_STANDARD": (
                "((mean(r) - rf_periodic) / downside_deviation) * sqrt(T), with "
                "downside_deviation = sqrt(mean(min(r - MAR, 0)^2)) over ALL "
                "observations - Sortino's own definition"
            ),
            "sortino_ratio_NEGATIVE_ONLY_STDDEV": (
                "same numerator, denominator = stdev(r where r < 0). The widely "
                "circulated shortcut. Reported alongside the standard form because they "
                "differ, and knowing which one a quoted Sortino used is the difference "
                "between comparing two portfolios and comparing two spreadsheets."
            ),
            "var_historical": (
                "-(quantile(r, 1 - confidence)) * portfolio_value, reported as a "
                "positive loss"
            ),
            "var_parametric": (
                "-(mu - z * sigma) * portfolio_value, z = Phi^-1(confidence). Set "
                "PARAMETRIC_VAR_INCLUDES_DRIFT=false for the zero-drift textbook form."
            ),
            "expected_shortfall_historical": "-mean(r | r <= VaR quantile) * portfolio_value",
            "expected_shortfall_parametric": (
                "-(mu - sigma * phi(z) / (1 - confidence)) * portfolio_value"
            ),
            "beta": "Cov(r_asset, r_benchmark) / Var(r_benchmark), OLS over the window",
            "stress_test": (
                "value_after = value_before * (1 + beta * index_shock), floored at zero"
            ),
            "kupiec_pof": (
                "LR = -2 * ln[ ((1-p)^(N-x) p^x) / ((1-x/N)^(N-x) (x/N)^x ) ], "
                "chi-square(1); reject above 3.841 at 95%"
            ),
            "max_drawdown": "max peak-to-trough decline of cumprod(1 + r)",
            "diversification_ratio": (
                "weighted-average holding volatility / realised portfolio volatility; "
                "1.0 means no benefit"
            ),
        },
        "conventions": {
            "return_method": "SIMPLE",
            "why_simple": (
                "A portfolio's simple return is the weighted sum of its holdings' simple "
                "returns. Log returns are additive across TIME, not across ASSETS, so "
                "weighting log returns produces a number with no interpretation."
            ),
            "rebalancing": Rebalancing.DAILY_CONSTANT_WEIGHT.value,
            "date_alignment": (
                "Intersection across holdings. Missing closes are never forward-filled: "
                "a filled day enters as a 0% return and drags measured volatility down."
            ),
            "std_ddof": settings.std_ddof,
            "trading_days_per_year": "per universe; see GET /universes",
            "risk_free_deannualisation": (
                "GEOMETRIC"
                if settings.risk_free_geometric_deannualisation
                else "SIMPLE"
            ),
            "annualisation": "mean * T for return, sigma * sqrt(T) for volatility",
            "annualisation_caveat": (
                "sqrt(T) scaling assumes independent returns. Real returns are mildly "
                "autocorrelated, and positive autocorrelation means sqrt(T) UNDERSTATES "
                "true annual volatility."
            ),
            "sortino_conventions": [c.value for c in SortinoConvention],
            "sortino_mar_annual": settings.sortino_mar_annual,
            "var_sign": "All VaR and ES figures are POSITIVE loss magnitudes.",
            "historical_var_quantile_method": settings.historical_var_quantile_method,
            "parametric_var_includes_drift": settings.parametric_var_includes_drift,
            "shock_modes": [m.value for m in ShockMode],
        },
        "sample_requirements": {
            "min_observations": settings.min_observations,
            "min_observations_per_tail_point": settings.min_observations_per_tail_point,
            "sortino_min_downside_observations": settings.sortino_min_downside_observations,
            "beta_min_observations": settings.beta_min_observations,
            "backtest_window": settings.backtest_window,
            "why": (
                "Below these counts the estimates are too noisy to report, so the metric "
                "is returned as null with a stated reason rather than as a number that "
                "looks like an answer."
            ),
        },
        "scenarios": {
            name: scenario.as_dict() for name, scenario in load_scenarios().items()
        },
        "not_implemented_in_v1": {
            "monte_carlo_var": (
                "Historical and parametric cover the standard tradeoff. Monte Carlo "
                "needs a defensible return-generating process, and picking one badly is "
                "worse than not having it."
            ),
            "portfolio_optimisation": (
                "This analyses the weights it is given. Mean-variance optimisation "
                "suggests weights, which is a different product and a documented V2."
            ),
            "christoffersen_independence_test": (
                "Kupiec tests the NUMBER of VaR breaches, not their TIMING. Clustered "
                "breaches pass it as cleanly as evenly spaced ones and are far more "
                "dangerous. Clustering statistics are reported; the formal test is V2."
            ),
            "options_and_greeks": "Equity-only. Non-linear payoffs need a different engine.",
            "real_time_data": "Static historical files, loaded explicitly and versioned.",
        },
        "llm_role": (
            "Narration only. Every figure in a report exists in structured_context "
            "before the model is called, that payload is stored on the report row, and "
            "any metric key the model cites that is not in the context is dropped and "
            "recorded in dropped_citations."
        ),
    }
