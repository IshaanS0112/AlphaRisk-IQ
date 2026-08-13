import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base, utc_now


class AssetReturn(Base):
    """One asset, one date, one close and the return that led to it.

    ``return_pct`` is stored as a decimal fraction (0.0123 = +1.23%), not as a
    percentage number. Mixing the two is the single most common unit bug in risk
    code and it produces results that are wrong by 10,000x in variance terms
    while still looking like plausible floats.

    The first observation of every series has ``return_pct = NULL``, because
    there is no prior close to difference against. It is stored rather than
    dropped so the price series stays complete.
    """

    __tablename__ = "asset_returns"
    __table_args__ = (
        # Every query in this system is "give me the series for these tickers
        # over this window", which is exactly this index.
        Index("ix_asset_returns_ticker_date", "ticker", "date", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(30), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    return_pct: Mapped[float | None] = mapped_column(Float)

    # Free text: "Yahoo Finance daily adjusted close, RELIANCE.NS, downloaded
    # 2026-07-30". Coarser than a per-row citation, but it means no number in
    # this system exists without a stated origin.
    source: Mapped[str] = mapped_column(String(300), nullable=False)

    # Provenance.REAL_MARKET_DATA or Provenance.SYNTHETIC. Carried on every row
    # rather than on the ticker, because a universe can be half loaded.
    provenance: Mapped[str] = mapped_column(String(30), nullable=False)

    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )


class Benchmark(Base):
    """Index level series used for beta estimation and scenario framing.

    Structurally identical to AssetReturn and deliberately a separate table: the
    benchmark is not a holding, and letting it into ``asset_returns`` invites a
    portfolio that accidentally contains its own index.
    """

    __tablename__ = "benchmark_returns"
    __table_args__ = (
        Index("ix_benchmark_returns_symbol_date", "symbol", "date", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    return_pct: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(300), nullable=False)
    provenance: Mapped[str] = mapped_column(String(30), nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )


class DataLoad(Base):
    """One row per load operation, so provenance survives a re-import.

    Without this, "where did the RELIANCE series come from" is answerable only
    by reading a source string on 500 rows and hoping they agree.
    """

    __tablename__ = "data_loads"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    universe: Mapped[str] = mapped_column(String(20), nullable=False)
    provenance: Mapped[str] = mapped_column(String(30), nullable=False)
    source: Mapped[str] = mapped_column(String(300), nullable=False)
    tickers_loaded: Mapped[int] = mapped_column(nullable=False, default=0)
    rows_loaded: Mapped[int] = mapped_column(nullable=False, default=0)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )
