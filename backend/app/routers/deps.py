"""Shared router dependencies."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import get_db
from app.models import Portfolio
from app.services.universes import Universe, get_universe

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def current_portfolio(
    portfolio_id: Annotated[uuid.UUID, Path()], db: DbSession
) -> Portfolio:
    portfolio = db.get(Portfolio, portfolio_id)
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found."
        )
    return portfolio


CurrentPortfolio = Annotated[Portfolio, Depends(current_portfolio)]


def portfolio_universe(portfolio: CurrentPortfolio) -> Universe:
    try:
        return get_universe(portfolio.universe)
    except KeyError as exc:  # pragma: no cover - unreachable via the API
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


CurrentUniverse = Annotated[Universe, Depends(portfolio_universe)]
