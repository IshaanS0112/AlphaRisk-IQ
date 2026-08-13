import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base, JsonBlob, utc_now

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.portfolio import Portfolio


class RiskMetrics(Base):
    """One computation of the full metric set over one sample window.

    Rows are appended, never updated. Re-running after loading more history
    should leave the earlier result in place: "the VaR moved when we extended the
    window from one year to three" is the finding, not a detail to overwrite.
    """

    __tablename__ = "risk_metrics"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # --- Return / volatility ------------------------------------------------
    mean_return_daily: Mapped[float] = mapped_column(Float, nullable=False)
    mean_return_annualised: Mapped[float] = mapped_column(Float, nullable=False)
    portfolio_std_dev_daily: Mapped[float] = mapped_column(Float, nullable=False)
    portfolio_std_dev_annualised: Mapped[float] = mapped_column(Float, nullable=False)

    # --- Risk-adjusted return ----------------------------------------------
    sharpe_ratio: Mapped[float | None] = mapped_column(Float)
    # Sortino under the STANDARD definition (RMS of shortfall below MAR over all
    # observations). This is the headline figure.
    sortino_ratio: Mapped[float | None] = mapped_column(Float)
    # Sortino under the widely circulated NEGATIVE_ONLY_STDDEV shortcut, kept so
    # the difference between the two is visible rather than argued about.
    sortino_ratio_negative_only: Mapped[float | None] = mapped_column(Float)
    downside_deviation: Mapped[float | None] = mapped_column(Float)
    downside_deviation_negative_only: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)

    # --- Value at Risk (positive loss magnitudes, in portfolio currency) -----
    var_historical_95: Mapped[float | None] = mapped_column(Float)
    var_parametric_95: Mapped[float | None] = mapped_column(Float)
    var_historical_99: Mapped[float | None] = mapped_column(Float)
    var_parametric_99: Mapped[float | None] = mapped_column(Float)
    es_historical_95: Mapped[float | None] = mapped_column(Float)
    es_parametric_95: Mapped[float | None] = mapped_column(Float)

    # Everything needed to reproduce the numbers above: window bounds and
    # length, risk-free rate and MAR used, confidence levels, trading-day count,
    # ddof, quantile method, per-ticker weights, and the aggregate provenance.
    calculation_basis: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    # Full per-VaR-method detail plus the backtest, kept out of the flat columns
    # because it is nested and nobody filters on it.
    detail: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    # Metrics that could not be computed and precisely why. Stored rather than
    # logged: "Sortino is undefined because only 3 days fell below the MAR" is an
    # analytical finding about the sample, not a debug message.
    omitted_metrics: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)

    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    portfolio: Mapped["Portfolio"] = relationship(back_populates="risk_metrics")


class StressTest(Base):
    __tablename__ = "stress_tests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True
    )

    scenario_name: Mapped[str] = mapped_column(String(100), nullable=False)
    scenario_label: Mapped[str] = mapped_column(String(200), nullable=False)
    shock_mode: Mapped[str] = mapped_column(String(30), nullable=False)

    # The scenario as applied: index shock, per-holding betas and effective
    # shocks, and the citation the magnitude came from.
    shock_config: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    portfolio_value_before: Mapped[float] = mapped_column(Float, nullable=False)
    portfolio_value_after: Mapped[float] = mapped_column(Float, nullable=False)
    pct_loss: Mapped[float] = mapped_column(Float, nullable=False)

    # Per-holding contribution to the loss, so the answer is decomposable
    # rather than a single number.
    holding_impacts: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)
    calculation_basis: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    tested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    portfolio: Mapped["Portfolio"] = relationship(back_populates="stress_tests")


class InvestmentReport(Base):
    __tablename__ = "investment_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # The exact payload handed to the model, stored before the call is made.
    # This is the artefact that makes the central claim checkable: every figure
    # in the narrative exists here first, and a reader can diff the two.
    structured_context: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    ai_narrative: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    # LLM or TEMPLATE_FALLBACK, plus the reason if it fell back.
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    fallback_reason: Mapped[str | None] = mapped_column(String(400))
    model_used: Mapped[str | None] = mapped_column(String(80))
    # Metric keys the model cited that were not in the context it was given.
    # Dropped from the narrative and recorded here, because a model inventing a
    # metric key is the exact failure this architecture exists to catch.
    dropped_citations: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    portfolio: Mapped["Portfolio"] = relationship(back_populates="investment_reports")
