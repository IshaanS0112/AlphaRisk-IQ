"""Portfolio CRUD."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.models import Portfolio
from app.routers.deps import CurrentPortfolio, DbSession
from app.schemas import PortfolioCreate, PortfolioOut
from app.services.returns import normalise_weights
from app.services.universes import get_universe

router = APIRouter(prefix="/portfolios", tags=["portfolios"])


@router.post("", response_model=PortfolioOut, status_code=status.HTTP_201_CREATED)
def create_portfolio(payload: PortfolioCreate, db: DbSession):
    try:
        universe = get_universe(payload.universe)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    known = set(universe.ticker_symbols)
    unknown = [h.ticker for h in payload.holdings if h.ticker not in known]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Not in the {universe.label} universe: {', '.join(unknown)}. "
                f"Available: {', '.join(sorted(known))}. Tickers are constrained to the "
                "universe because the universe is what determines the benchmark, the "
                "risk-free rate and which crisis magnitudes are meaningful."
            ),
        )

    holdings, raw_sum = normalise_weights([h.model_dump() for h in payload.holdings])
    portfolio = Portfolio(
        name=payload.name,
        universe=payload.universe,
        holdings=holdings,
        base_value=payload.base_value,
        currency=universe.currency,
    )
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)

    # Recorded on the row so "I entered 40/35/25" and "the system stored
    # 0.40/0.35/0.25" are visibly the same submission rather than a silent
    # reinterpretation.
    portfolio.holdings = [
        {**h, "submitted_weight": raw * raw_sum}
        for h, raw in zip(portfolio.holdings, [h["weight"] for h in holdings])
    ]
    db.commit()
    db.refresh(portfolio)
    return portfolio


@router.get("", response_model=list[PortfolioOut])
def list_portfolios(db: DbSession):
    return list(db.execute(select(Portfolio).order_by(Portfolio.created_at.desc())).scalars())


@router.get("/{portfolio_id}", response_model=PortfolioOut)
def get_portfolio(portfolio: CurrentPortfolio):
    return portfolio


@router.delete(
    "/{portfolio_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_portfolio(portfolio: CurrentPortfolio, db: DbSession) -> Response:
    db.delete(portfolio)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
