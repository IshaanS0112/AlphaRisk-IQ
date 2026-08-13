"""Request and response models.

Validation lives here rather than in the routers so that a bad portfolio is
rejected at the edge with a message that says what to do about it. Two rules are
enforced that are easy to omit and expensive to omit: weights must be positive
(this is a long-only V1 and a negative weight would silently produce a short
position the risk math is not set up for), and a ticker may appear only once.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.enums import ShockMode


class Holding(BaseModel):
    ticker: str = Field(min_length=1, max_length=30)
    weight: float = Field(gt=0)

    @field_validator("ticker")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.strip().upper()


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    universe: str = Field(description="NSE_INDIA or US")
    holdings: list[Holding] = Field(min_length=1)
    base_value: float = Field(
        default=1_000_000.0,
        gt=0,
        description=(
            "Notional the VaR and stress figures are expressed against. VaR is a "
            "currency amount, so it is meaningless without one."
        ),
    )

    @model_validator(mode="after")
    def _unique_tickers(self) -> "PortfolioCreate":
        seen = [h.ticker for h in self.holdings]
        duplicates = {t for t in seen if seen.count(t) > 1}
        if duplicates:
            raise ValueError(
                f"Duplicate holdings: {', '.join(sorted(duplicates))}. Combine them into "
                "one line with the summed weight - two rows for the same ticker would be "
                "treated as two assets with a correlation of exactly 1, which inflates "
                "the apparent holding count without changing the risk."
            )
        return self


class PortfolioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    universe: str
    holdings: list[dict]
    base_value: float
    currency: str
    created_at: datetime


class RiskMetricsRequest(BaseModel):
    window_start: date | None = None
    window_end: date | None = None
    risk_free_annual: float | None = Field(
        default=None,
        ge=-0.05,
        le=0.5,
        description=(
            "Overrides the universe default. Recorded in calculation_basis, because a "
            "Sharpe ratio without its risk-free rate is not a reproducible number."
        ),
    )
    run_backtest: bool = True


class RiskMetricsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    portfolio_id: uuid.UUID
    mean_return_daily: float
    mean_return_annualised: float
    portfolio_std_dev_daily: float
    portfolio_std_dev_annualised: float
    sharpe_ratio: float | None
    sortino_ratio: float | None
    sortino_ratio_negative_only: float | None
    downside_deviation: float | None
    downside_deviation_negative_only: float | None
    max_drawdown: float | None
    var_historical_95: float | None
    var_parametric_95: float | None
    var_historical_99: float | None
    var_parametric_99: float | None
    es_historical_95: float | None
    es_parametric_95: float | None
    calculation_basis: dict
    detail: dict
    omitted_metrics: list
    calculated_at: datetime


class StressTestRequest(BaseModel):
    scenario_name: str | None = None
    custom_shock_pct: float | None = Field(
        default=None,
        lt=0,
        gt=-1,
        description="Decimal fraction, negative. -0.25 is a 25% index decline.",
    )
    custom_label: str | None = Field(default=None, max_length=200)
    mode: ShockMode = ShockMode.UNIFORM
    window_start: date | None = None
    window_end: date | None = None

    @model_validator(mode="after")
    def _one_of(self) -> "StressTestRequest":
        if bool(self.scenario_name) == (self.custom_shock_pct is not None):
            raise ValueError(
                "Supply exactly one of scenario_name or custom_shock_pct. Supplying "
                "both leaves it ambiguous which magnitude the stored result refers to."
            )
        return self


class StressTestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    portfolio_id: uuid.UUID
    scenario_name: str
    scenario_label: str
    shock_mode: str
    shock_config: dict
    portfolio_value_before: float
    portfolio_value_after: float
    pct_loss: float
    holding_impacts: list
    calculation_basis: dict
    tested_at: datetime


class InvestmentReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    portfolio_id: uuid.UUID
    structured_context: dict
    ai_narrative: dict
    status: str
    fallback_reason: str | None
    model_used: str | None
    dropped_citations: list
    generated_at: datetime


class MarketDataLoadRequest(BaseModel):
    universe: str
    provenance: str | None = Field(
        default=None,
        description=(
            "REAL_MARKET_DATA or SYNTHETIC. Omit to prefer real data when it is present."
        ),
    )


class MarketDataLoadOut(BaseModel):
    universe: str
    provenance: str
    source: str
    tickers_loaded: int
    benchmark_symbol: str | None
    rows_loaded: int
    first_date: str | None
    last_date: str | None
    warnings: list[str]
