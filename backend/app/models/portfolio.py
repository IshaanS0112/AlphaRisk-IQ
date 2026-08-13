import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base, JsonBlob, utc_now

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.analysis import InvestmentReport, RiskMetrics, StressTest


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Which universe the tickers belong to. Not decoration: it selects the
    # benchmark index used for beta estimation and the crisis magnitudes that
    # are meaningful for these holdings. Applying an S&P 500 drawdown to an NSE
    # portfolio is a category error, and the universe is what prevents it.
    universe: Mapped[str] = mapped_column(String(20), nullable=False)

    # [{ticker, weight}] - weights normalised to sum to 1 at write time, with
    # the pre-normalisation sum recorded so a portfolio entered as percentages
    # is not silently reinterpreted.
    holdings: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)

    # Notional value the VaR and stress figures are expressed against. VaR is a
    # currency amount, so it is meaningless without one.
    base_value: Mapped[float] = mapped_column(nullable=False, default=1_000_000.0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    risk_metrics: Mapped[list["RiskMetrics"]] = relationship(
        back_populates="portfolio",
        cascade="all, delete-orphan",
        order_by="RiskMetrics.calculated_at",
    )
    stress_tests: Mapped[list["StressTest"]] = relationship(
        back_populates="portfolio",
        cascade="all, delete-orphan",
        order_by="StressTest.tested_at",
    )
    investment_reports: Mapped[list["InvestmentReport"]] = relationship(
        back_populates="portfolio",
        cascade="all, delete-orphan",
        order_by="InvestmentReport.generated_at",
    )
