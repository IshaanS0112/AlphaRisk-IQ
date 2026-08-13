"""Scenario stress testing, with betas estimated rather than assumed.

The simplest possible stress test applies the index shock to the whole portfolio:

    value_after = value_before * (1 + shock)

which implicitly assumes every holding has a beta of exactly 1 to the index. That
is the ``UNIFORM`` mode here, and it is worth keeping because it is transparent
and it is what a lot of published stress numbers actually are.

``BETA_ADJUSTED`` mode does the thing the assumption is standing in for. Each
holding's beta is estimated by ordinary least squares of its returns on the
benchmark's over the sample window,

    beta_i = Cov(r_i, r_m) / Var(r_m)

and the holding is shocked by ``beta_i * index_shock``. A defensive staple with a
beta of 0.6 then loses less than the index, a high-beta financial loses more, and
the portfolio-level loss is ``sum(w_i * beta_i) * index_shock`` - the portfolio
beta, which is reported.

**The limitation to state before anyone else does.** Beta is estimated on a calm
sample and applied to a crisis, and in a crisis betas converge towards 1 and
correlations converge towards 1 with them. Precisely when diversification is
supposed to help, it stops helping. So a beta-adjusted stress test fitted on
2023-2025 data will *understate* the loss of a low-beta portfolio in a 2008-style
event. That is not a reason to skip the beta estimate - it is a reason to report
both modes side by side, which is what this engine does, and to treat the uniform
number as the pessimistic bound.

**What this is not.** A one-shot repricing says nothing about path, liquidity, or
the order in which things fail. The 2020 drawdown took 23 trading days and the
2008 drawdown took 17 months; the single-shock model treats them identically.
Multi-period and liquidity-aware stress is real work and is documented as V2
rather than gestured at.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.enums import ShockMode
from app.services.returns import AlignedReturns


@dataclass(frozen=True)
class BetaEstimate:
    ticker: str
    beta: float
    r_squared: float
    n_observations: int
    estimated: bool
    note: str


@dataclass(frozen=True)
class HoldingImpact:
    ticker: str
    weight: float
    beta: float
    effective_shock: float
    value_before: float
    value_after: float
    loss: float
    contribution_to_portfolio_loss_pct: float


@dataclass(frozen=True)
class StressResult:
    shock_mode: str
    index_shock: float
    portfolio_beta: float
    portfolio_value_before: float
    portfolio_value_after: float
    loss: float
    pct_loss: float
    holding_impacts: list[HoldingImpact]
    betas: list[BetaEstimate]
    notes: list[str]


def estimate_beta(
    asset_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    *,
    ticker: str = "",
    min_observations: int = 60,
) -> BetaEstimate:
    """OLS beta of an asset against the benchmark, with its R-squared.

    R-squared is returned alongside because a beta without one is half an answer:
    a beta of 1.2 explaining 70% of variance and a beta of 1.2 explaining 8% are
    completely different statements about how the holding will behave in an
    index-driven event, and only the first justifies using the beta in a stress
    test at all.
    """
    n = min(len(asset_returns), len(benchmark_returns))
    if n < min_observations:
        return BetaEstimate(
            ticker=ticker,
            beta=1.0,
            r_squared=float("nan"),
            n_observations=n,
            estimated=False,
            note=(
                f"Only {n} overlapping observations against a floor of "
                f"{min_observations}; beta defaulted to 1.0 rather than estimated from "
                "a sample too short to mean anything."
            ),
        )

    a = asset_returns[-n:]
    m = benchmark_returns[-n:]
    var_m = float(np.var(m, ddof=1))
    if var_m <= 0:
        return BetaEstimate(
            ticker=ticker,
            beta=1.0,
            r_squared=float("nan"),
            n_observations=n,
            estimated=False,
            note="Benchmark variance is zero over the window; beta is undefined.",
        )

    cov = float(np.cov(a, m, ddof=1)[0, 1])
    beta = cov / var_m
    corr = float(np.corrcoef(a, m)[0, 1])
    return BetaEstimate(
        ticker=ticker,
        beta=beta,
        r_squared=corr * corr,
        n_observations=n,
        estimated=True,
        note="OLS of asset returns on benchmark returns over the aligned window.",
    )


def estimate_betas(
    aligned: AlignedReturns,
    benchmark_returns: np.ndarray,
    *,
    min_observations: int = 60,
) -> dict[str, BetaEstimate]:
    return {
        ticker: estimate_beta(
            aligned.matrix[:, i],
            benchmark_returns,
            ticker=ticker,
            min_observations=min_observations,
        )
        for i, ticker in enumerate(aligned.tickers)
    }


def apply_shock(
    *,
    weights: dict[str, float],
    portfolio_value: float,
    index_shock: float,
    mode: ShockMode = ShockMode.UNIFORM,
    betas: dict[str, BetaEstimate] | None = None,
    max_shock_pct: float = 99.0,
) -> StressResult:
    """Reprice the portfolio under a single index-level shock."""
    if portfolio_value <= 0:
        raise ValueError("Portfolio value must be positive.")
    if index_shock >= 0:
        raise ValueError(
            f"Stress shock must be negative; got {index_shock:+.4f}. A scenario in "
            "which the index rises is not a stress test - if you want upside "
            "sensitivity, that is a different (and useful) analysis with a different "
            "name."
        )
    if abs(index_shock) * 100 > max_shock_pct:
        raise ValueError(
            f"Shock of {index_shock:.2%} exceeds the {max_shock_pct}% ceiling. A shock "
            "approaching -100% prices the portfolio to nearly zero, which is a "
            "data-entry error far more often than it is a scenario."
        )

    notes: list[str] = []
    betas = betas or {}
    impacts: list[HoldingImpact] = []
    used_betas: list[BetaEstimate] = []

    total_loss = 0.0
    portfolio_beta = 0.0

    for ticker, weight in sorted(weights.items()):
        if mode is ShockMode.BETA_ADJUSTED:
            estimate = betas.get(ticker)
            if estimate is None:
                estimate = BetaEstimate(
                    ticker=ticker,
                    beta=1.0,
                    r_squared=float("nan"),
                    n_observations=0,
                    estimated=False,
                    note="No return series available; beta defaulted to 1.0.",
                )
            beta = estimate.beta
        else:
            beta = 1.0
            estimate = BetaEstimate(
                ticker=ticker,
                beta=1.0,
                r_squared=float("nan"),
                n_observations=0,
                estimated=False,
                note="UNIFORM mode: every holding takes the full index shock.",
            )

        used_betas.append(estimate)
        effective = beta * index_shock
        value_before = portfolio_value * weight
        # Floored at zero: a beta above 1 combined with a severe shock can imply a
        # move below -100%, which is not possible for a long equity position.
        value_after = max(0.0, value_before * (1.0 + effective))
        loss = value_before - value_after
        total_loss += loss
        portfolio_beta += weight * beta

        impacts.append(
            HoldingImpact(
                ticker=ticker,
                weight=weight,
                beta=beta,
                effective_shock=effective,
                value_before=value_before,
                value_after=value_after,
                loss=loss,
                contribution_to_portfolio_loss_pct=0.0,
            )
        )

    if total_loss > 0:
        impacts = [
            HoldingImpact(
                **{
                    **impact.__dict__,
                    "contribution_to_portfolio_loss_pct": impact.loss / total_loss,
                }
            )
            for impact in impacts
        ]

    floored = [i.ticker for i in impacts if i.value_after == 0.0 and i.value_before > 0]
    if floored:
        notes.append(
            "Floored at zero (beta x shock implied a move below -100%): "
            + ", ".join(floored)
            + ". A linear beta model extrapolated past a total loss is outside its "
            "range of validity; treat these holdings as 'wiped out' rather than as a "
            "precise figure."
        )

    if mode is ShockMode.BETA_ADJUSTED:
        weak = [
            b.ticker
            for b in used_betas
            if b.estimated and not np.isnan(b.r_squared) and b.r_squared < 0.25
        ]
        if weak:
            notes.append(
                "Benchmark explains under 25% of return variance for: "
                + ", ".join(sorted(weak))
                + ". Their betas are statistically weak, so the beta-adjusted shock for "
                "these holdings is not much better than a guess."
            )
        notes.append(
            "Betas are estimated on the sample window and applied to a crisis. In a "
            "crisis betas and correlations both converge towards 1, so this mode will "
            "understate the loss on a low-beta portfolio. Read the UNIFORM result as "
            "the pessimistic bound."
        )

    value_after_total = portfolio_value - total_loss
    return StressResult(
        shock_mode=mode.value,
        index_shock=index_shock,
        portfolio_beta=portfolio_beta,
        portfolio_value_before=portfolio_value,
        portfolio_value_after=value_after_total,
        loss=total_loss,
        pct_loss=total_loss / portfolio_value,
        holding_impacts=impacts,
        betas=used_betas,
        notes=notes,
    )
