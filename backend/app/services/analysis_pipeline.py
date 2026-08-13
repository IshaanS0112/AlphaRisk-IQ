"""Orchestration: portfolio row -> return series -> metrics -> stored result.

Every stage writes a ``calculation_basis`` alongside its numbers. That is not
bookkeeping. A Sharpe ratio of 1.4 is not a fact about a portfolio, it is a fact
about a portfolio *under a stated window, risk-free rate, trading-day count and
standard-deviation convention*, and dropping those four makes the number
unfalsifiable. Anything a reader would need to reproduce a figure is stored next
to the figure.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

import numpy as np
from sqlalchemy.orm import Session

from app.config import Settings
from app.enums import Provenance, Rebalancing, ShockMode, VarMethod
from app.models import Portfolio, RiskMetrics, StressTest
from app.services import (
    market_data,
    returns as returns_service,
    risk_calculator,
    stress_test_engine,
    var_backtest,
    var_engine,
)
from app.services.scenarios import Scenario
from app.services.universes import Universe


class InsufficientData(Exception):
    """Not enough usable observations to report a figure honestly."""


def _weights(portfolio: Portfolio) -> dict[str, float]:
    return {h["ticker"]: float(h["weight"]) for h in portfolio.holdings}


def build_series(
    portfolio: Portfolio,
    db: Session,
    settings: Settings,
    *,
    start: date | None = None,
    end: date | None = None,
) -> tuple[returns_service.AlignedReturns, np.ndarray, dict]:
    """Aligned asset returns, the portfolio series, and the alignment record."""
    weights = _weights(portfolio)
    series, provenances = market_data.fetch_series(
        db, list(weights), start=start, end=end
    )

    missing = sorted(set(weights) - set(series))
    if missing:
        raise InsufficientData(
            f"No return data loaded for: {', '.join(missing)}. Load the universe first "
            "(POST /market-data/load) - the portfolio's holdings must all have price "
            "history before any risk figure can be computed."
        )

    aligned = returns_service.align(series)
    if aligned.n < settings.min_observations:
        raise InsufficientData(
            f"Only {aligned.n} overlapping observations across the holdings, against a "
            f"floor of {settings.min_observations}. Below that, the confidence interval "
            "on an annualised volatility estimate is wide enough that the point "
            "estimate is not worth quoting."
        )

    portfolio_returns = returns_service.portfolio_series(aligned, weights)

    seen = {p for values in provenances.values() for p in values}
    if Provenance.SYNTHETIC.value in seen and len(seen) > 1:
        aggregate = "MIXED"
    elif Provenance.SYNTHETIC.value in seen:
        aggregate = Provenance.SYNTHETIC.value
    else:
        aggregate = Provenance.REAL_MARKET_DATA.value

    alignment = {
        "window_start": aligned.dates[0].isoformat(),
        "window_end": aligned.dates[-1].isoformat(),
        "observations": aligned.n,
        "raw_observations_per_ticker": aligned.raw_counts,
        "dates_dropped_in_alignment": len(aligned.dropped_dates),
        "alignment_policy": (
            "Intersection of trading dates across holdings. Missing closes are never "
            "forward-filled: a filled day enters the series as a 0% return and drags "
            "measured volatility down."
        ),
        "data_provenance": aggregate,
        "provenance_per_ticker": {t: sorted(v) for t, v in provenances.items()},
        "rebalancing": Rebalancing.DAILY_CONSTANT_WEIGHT.value,
    }
    return aligned, portfolio_returns, alignment


def compute_risk_metrics(
    portfolio: Portfolio,
    db: Session,
    settings: Settings,
    universe: Universe,
    *,
    start: date | None = None,
    end: date | None = None,
    risk_free_annual: float | None = None,
    confidence_levels: tuple[float, ...] = (0.95, 0.99),
    run_backtest: bool = True,
) -> tuple[RiskMetrics, dict]:
    aligned, portfolio_returns, alignment = build_series(
        portfolio, db, settings, start=start, end=end
    )
    rf = universe.risk_free_annual if risk_free_annual is None else risk_free_annual
    periods = universe.trading_days_per_year

    risk = risk_calculator.compute(
        portfolio_returns,
        periods_per_year=periods,
        risk_free_annual=rf,
        mar_annual=settings.sortino_mar_annual,
        ddof=settings.std_ddof,
        geometric_deannualisation=settings.risk_free_geometric_deannualisation,
        min_downside_observations=settings.sortino_min_downside_observations,
        degenerate_std_threshold=settings.degenerate_std_threshold,
    )

    var_results = {
        level: var_engine.compute(
            portfolio_returns,
            portfolio.base_value,
            confidence=level,
            ddof=settings.std_ddof,
            include_drift=settings.parametric_var_includes_drift,
            quantile_method=settings.historical_var_quantile_method,
            min_observations_per_tail_point=settings.min_observations_per_tail_point,
        )
        for level in confidence_levels
    }

    backtests = {}
    if run_backtest:
        for method in (VarMethod.HISTORICAL, VarMethod.PARAMETRIC):
            result = var_backtest.run(
                portfolio_returns,
                method=method,
                confidence=settings.default_confidence_level,
                window=settings.backtest_window,
                ddof=settings.std_ddof,
                include_drift=settings.parametric_var_includes_drift,
                quantile_method=settings.historical_var_quantile_method,
                critical_value=settings.kupiec_critical_value_95,
            )
            backtests[method.value] = asdict(result)

    basis = {
        **alignment,
        "risk_free_annual": rf,
        "risk_free_basis": universe.risk_free_basis,
        "risk_free_as_of": universe.risk_free_as_of,
        "risk_free_status": universe.risk_free_status,
        "risk_free_deannualisation": (
            "GEOMETRIC (1+rf)^(1/T)-1"
            if settings.risk_free_geometric_deannualisation
            else "SIMPLE rf/T"
        ),
        "sortino_mar_annual": settings.sortino_mar_annual,
        "trading_days_per_year": periods,
        "trading_days_note": universe.trading_days_note,
        "std_ddof": settings.std_ddof,
        "return_method": "SIMPLE",
        "annualisation": "mean * T for return, sigma * sqrt(T) for volatility",
        "confidence_levels": list(confidence_levels),
        "historical_var_quantile_method": settings.historical_var_quantile_method,
        "parametric_var_includes_drift": settings.parametric_var_includes_drift,
        "weights": _weights(portfolio),
        "base_value": portfolio.base_value,
        "currency": portfolio.currency,
        "universe": universe.name,
        "benchmark": universe.benchmark_symbol,
    }

    detail = {
        "risk": {
            "geometric_return_annualised": risk.geometric_return_annualised,
            "arithmetic_vs_geometric_note": (
                "Arithmetic annualised return (mean * T) exceeds the compound annual "
                "growth rate by roughly half the variance. The arithmetic figure is the "
                "one that belongs in a Sharpe ratio; the geometric figure is the one an "
                "investor actually earned."
            ),
            "downside_deviation_annualised": risk.downside_deviation_annualised,
            "n_downside_observations": risk.n_downside_observations,
            "max_drawdown_window": {
                "peak_date": aligned.dates[risk.max_drawdown_peak_index].isoformat(),
                "trough_date": aligned.dates[risk.max_drawdown_trough_index].isoformat(),
            },
            "sortino_conventions": {
                "STANDARD": risk.sortino_ratio,
                "NEGATIVE_ONLY_STDDEV": risk.sortino_ratio_negative_only,
                "note": (
                    "STANDARD is Sortino's own definition: RMS shortfall below the MAR "
                    "over all observations. NEGATIVE_ONLY_STDDEV is the widely "
                    "circulated shortcut, the sample standard deviation of the negative "
                    "returns only. Both are reported because they differ, and knowing "
                    "which one a quoted Sortino used is the difference between "
                    "comparing two portfolios and comparing two spreadsheets."
                ),
            },
        },
        "var": {
            f"{level:.2f}": {
                k: v for k, v in asdict(result).items() if k != "notes"
            }
            | {"notes": result.notes}
            for level, result in var_results.items()
        },
        "backtests": backtests,
        "per_holding": {
            ticker: {
                "weight": _weights(portfolio)[ticker],
                "mean_daily": float(np.mean(aligned.matrix[:, i])),
                "std_daily": float(np.std(aligned.matrix[:, i], ddof=settings.std_ddof)),
                "std_annualised": float(
                    np.std(aligned.matrix[:, i], ddof=settings.std_ddof)
                )
                * np.sqrt(periods),
            }
            for i, ticker in enumerate(aligned.tickers)
        },
        "diversification": _diversification(aligned, _weights(portfolio), periods, settings),
    }

    var95 = var_results.get(0.95)
    var99 = var_results.get(0.99)

    row = RiskMetrics(
        portfolio_id=portfolio.id,
        mean_return_daily=risk.mean_return_daily,
        mean_return_annualised=risk.mean_return_annualised,
        portfolio_std_dev_daily=risk.std_dev_daily,
        portfolio_std_dev_annualised=risk.std_dev_annualised,
        sharpe_ratio=risk.sharpe_ratio,
        sortino_ratio=risk.sortino_ratio,
        sortino_ratio_negative_only=risk.sortino_ratio_negative_only,
        downside_deviation=risk.downside_deviation_daily,
        downside_deviation_negative_only=risk.downside_deviation_negative_only_daily,
        max_drawdown=risk.max_drawdown,
        var_historical_95=var95.var_historical if var95 else None,
        var_parametric_95=var95.var_parametric if var95 else None,
        var_historical_99=var99.var_historical if var99 else None,
        var_parametric_99=var99.var_parametric if var99 else None,
        es_historical_95=var95.es_historical if var95 else None,
        es_parametric_95=var95.es_parametric if var95 else None,
        calculation_basis=basis,
        detail=detail,
        omitted_metrics=risk.omitted,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, detail


def _diversification(
    aligned: returns_service.AlignedReturns,
    weights: dict[str, float],
    periods: int,
    settings: Settings,
) -> dict:
    """Weighted-average holding volatility vs realised portfolio volatility.

    The ratio of the two is the diversification benefit, and expressing it this
    way avoids the trap of scoring diversification by counting holdings. Ten
    holdings that are all large-cap Indian banks is one position wearing ten
    hats; the covariance structure is what decides, and this is the cheapest
    honest read on it.
    """
    w = np.array([weights[t] for t in aligned.tickers])
    sigmas = np.std(aligned.matrix, axis=0, ddof=settings.std_ddof)
    undiversified = float(np.dot(w, sigmas))
    realised = float(np.std(aligned.matrix @ w, ddof=settings.std_ddof))
    corr = np.corrcoef(aligned.matrix, rowvar=False)
    off_diagonal = corr[np.triu_indices_from(corr, k=1)]
    return {
        "weighted_average_holding_vol_annualised": undiversified * float(np.sqrt(periods)),
        "portfolio_vol_annualised": realised * float(np.sqrt(periods)),
        "diversification_ratio": (undiversified / realised) if realised > 0 else None,
        "mean_pairwise_correlation": (
            float(np.mean(off_diagonal)) if off_diagonal.size else None
        ),
        "max_pairwise_correlation": (
            float(np.max(off_diagonal)) if off_diagonal.size else None
        ),
        "note": (
            "Diversification ratio is the weighted-average holding volatility divided "
            "by the realised portfolio volatility; 1.0 means no benefit at all. "
            "Correlations here are measured over a calm-or-not sample window and rise "
            "towards 1 in a crisis, which is exactly when the benefit is being counted "
            "on."
        ),
    }


def run_stress_test(
    portfolio: Portfolio,
    db: Session,
    settings: Settings,
    universe: Universe,
    *,
    scenario: Scenario | None = None,
    custom_shock_pct: float | None = None,
    custom_label: str | None = None,
    mode: ShockMode = ShockMode.UNIFORM,
    start: date | None = None,
    end: date | None = None,
) -> StressTest:
    if scenario is None and custom_shock_pct is None:
        raise ValueError("Supply either a named scenario or a custom shock.")
    if scenario is not None and scenario.universe != universe.name:
        raise ValueError(
            f"Scenario '{scenario.name}' is defined on the {scenario.index} "
            f"({scenario.universe}) and this portfolio is in {universe.name}. Applying "
            "one index's drawdown to another market's holdings is a category error, "
            "not a conservative assumption."
        )

    weights = _weights(portfolio)
    betas: dict[str, stress_test_engine.BetaEstimate] = {}
    basis: dict = {"beta_estimation": "not required in UNIFORM mode"}

    if mode is ShockMode.BETA_ADJUSTED:
        aligned, _, alignment = build_series(portfolio, db, settings, start=start, end=end)
        benchmark = market_data.fetch_benchmark(
            db, universe.benchmark_symbol, start=start, end=end
        )
        common = [d for d in aligned.dates if d in benchmark]
        if len(common) < settings.beta_min_observations:
            raise InsufficientData(
                f"Only {len(common)} dates overlap between the holdings and "
                f"{universe.benchmark_symbol}, against a floor of "
                f"{settings.beta_min_observations}. Load the benchmark series before "
                "requesting a beta-adjusted stress test, or use UNIFORM mode - which "
                "assumes beta=1 for every holding and says so."
            )
        index_of = {d: i for i, d in enumerate(aligned.dates)}
        rows = [index_of[d] for d in common]
        sub = returns_service.AlignedReturns(
            dates=common,
            tickers=aligned.tickers,
            matrix=aligned.matrix[rows, :],
            raw_counts=aligned.raw_counts,
            dropped_dates=aligned.dropped_dates,
        )
        benchmark_returns = np.array([benchmark[d] for d in common])
        betas = stress_test_engine.estimate_betas(
            sub, benchmark_returns, min_observations=settings.beta_min_observations
        )
        basis = {
            **alignment,
            "beta_estimation": (
                f"OLS of each holding's daily returns on {universe.benchmark_symbol} "
                f"over {len(common)} overlapping observations."
            ),
            "beta_window_start": common[0].isoformat(),
            "beta_window_end": common[-1].isoformat(),
            "betas": {t: asdict(b) for t, b in betas.items()},
        }

    shock = scenario.shock_pct if scenario else float(custom_shock_pct)
    result = stress_test_engine.apply_shock(
        weights=weights,
        portfolio_value=portfolio.base_value,
        index_shock=shock,
        mode=mode,
        betas=betas,
        max_shock_pct=settings.max_shock_pct,
    )

    shock_config = {
        "index_shock_pct": shock,
        "mode": mode.value,
        "portfolio_beta": result.portfolio_beta,
        "notes": result.notes,
    }
    if scenario:
        shock_config["scenario"] = scenario.as_dict()
    else:
        shock_config["scenario"] = {
            "name": "custom",
            "label": custom_label or f"Custom shock {shock:.2%}",
            "source": "User-specified shock; no historical episode is being claimed.",
            "verification_status": "USER_SUPPLIED",
        }

    row = StressTest(
        portfolio_id=portfolio.id,
        scenario_name=scenario.name if scenario else "custom",
        scenario_label=(
            scenario.label if scenario else (custom_label or f"Custom shock {shock:.2%}")
        ),
        shock_mode=mode.value,
        shock_config=shock_config,
        portfolio_value_before=result.portfolio_value_before,
        portfolio_value_after=result.portfolio_value_after,
        pct_loss=result.pct_loss,
        holding_impacts=[asdict(i) for i in result.holding_impacts],
        calculation_basis={
            **basis,
            "currency": portfolio.currency,
            "model": (
                "Single-period linear repricing: value_after = value_before * "
                "(1 + beta * index_shock), floored at zero. No path, no liquidity, no "
                "second-order effects."
            ),
        },
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
