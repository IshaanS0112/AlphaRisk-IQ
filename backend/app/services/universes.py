"""Asset universe definitions.

A universe bundles four things that must agree with each other: the ticker list,
the benchmark index beta is estimated against, the trading-day count used for
annualisation, and the risk-free rate subtracted in the Sharpe numerator. Letting
those be set independently is how an NSE portfolio ends up with a US T-bill rate
in its Sharpe ratio and an S&P 500 drawdown in its stress test - both of which
produce numbers that look completely normal and mean nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

_DEFAULT_PATH = get_settings().data_path / "universes" / "universes.json"


@dataclass(frozen=True)
class Universe:
    name: str
    label: str
    currency: str
    benchmark_symbol: str
    benchmark_label: str
    trading_days_per_year: int
    trading_days_note: str
    risk_free_annual: float
    risk_free_basis: str
    risk_free_as_of: str
    risk_free_status: str
    yahoo_suffix: str
    tickers: list[dict]

    @property
    def ticker_symbols(self) -> list[str]:
        return [t["ticker"] for t in self.tickers]

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "currency": self.currency,
            "benchmark_symbol": self.benchmark_symbol,
            "benchmark_label": self.benchmark_label,
            "trading_days_per_year": self.trading_days_per_year,
            "trading_days_note": self.trading_days_note,
            "risk_free_annual": self.risk_free_annual,
            "risk_free_basis": self.risk_free_basis,
            "risk_free_as_of": self.risk_free_as_of,
            "risk_free_status": self.risk_free_status,
            "tickers": self.tickers,
        }


@lru_cache
def load_universes(path: str | None = None) -> dict[str, Universe]:
    source = Path(path) if path else _DEFAULT_PATH
    if not source.is_file():
        raise FileNotFoundError(f"Universe definitions not found at {source}.")
    payload = json.loads(source.read_text())
    return {
        name: Universe(name=name, **entry)
        for name, entry in payload["universes"].items()
    }


def get_universe(name: str, path: str | None = None) -> Universe:
    universes = load_universes(path)
    if name not in universes:
        raise KeyError(
            f"Unknown universe '{name}'. Available: {', '.join(sorted(universes))}."
        )
    return universes[name]
