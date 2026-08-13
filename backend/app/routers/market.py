"""Market data loading and the universe / scenario catalogues."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.routers.deps import DbSession
from app.schemas import MarketDataLoadOut, MarketDataLoadRequest
from app.services import market_data
from app.services.scenarios import for_universe, load_scenarios
from app.services.universes import get_universe, load_universes

router = APIRouter(tags=["market-data"])


@router.get("/universes")
def list_universes():
    return {
        name: {
            **universe.as_dict(),
            "price_data_available": market_data.available_provenances(name),
        }
        for name, universe in load_universes().items()
    }


@router.get("/scenarios")
def list_scenarios(universe: str | None = None):
    scenarios = for_universe(universe) if universe else list(load_scenarios().values())
    return {
        "scenarios": [s.as_dict() for s in scenarios],
        "note": (
            "Magnitudes are recomputed from the stored index peak and trough closing "
            "levels every time this endpoint is called. Nothing here is a hard-coded "
            "percentage, which is what makes it checkable."
        ),
    }


@router.post("/market-data/load", response_model=MarketDataLoadOut)
def load_market_data(payload: MarketDataLoadRequest, db: DbSession):
    try:
        universe = get_universe(payload.universe)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    try:
        summary = market_data.load_universe(
            db,
            payload.universe,
            universe.benchmark_symbol,
            provenance=payload.provenance,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return summary


@router.get("/market-data/status")
def market_data_status(db: DbSession):
    from sqlalchemy import func, select

    from app.models import AssetReturn, DataLoad

    rows = db.execute(
        select(
            AssetReturn.ticker,
            AssetReturn.provenance,
            func.count(AssetReturn.id),
            func.min(AssetReturn.date),
            func.max(AssetReturn.date),
        ).group_by(AssetReturn.ticker, AssetReturn.provenance)
    ).all()

    loads = db.execute(select(DataLoad).order_by(DataLoad.loaded_at.desc()).limit(10)).scalars()

    return {
        "series": [
            {
                "ticker": ticker,
                "provenance": provenance,
                "observations": count,
                "first_date": str(first),
                "last_date": str(last),
            }
            for ticker, provenance, count, first, last in rows
        ],
        "recent_loads": [
            {
                "universe": load.universe,
                "provenance": load.provenance,
                "source": load.source,
                "tickers_loaded": load.tickers_loaded,
                "rows_loaded": load.rows_loaded,
                "loaded_at": load.loaded_at.isoformat() if load.loaded_at else None,
            }
            for load in loads
        ],
    }
