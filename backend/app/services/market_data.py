"""Load price CSVs into the database, carrying provenance the whole way.

The loader reads ``_manifest.json`` from each price folder and refuses a folder
that does not have one. That is the single rule that makes the provenance
guarantee hold: there is no code path that inserts a return row without knowing,
from a file on disk, whether the price it came from was a real market close or a
draw from a model. A missing manifest is an error, never an assumption.

``REAL_MARKET_DATA`` is preferred over ``SYNTHETIC`` when both are present for a
universe, and which one was used is reported everywhere downstream.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.enums import Provenance, ReturnMethod
from app.models import AssetReturn, Benchmark, DataLoad
from app.services.returns import prices_to_returns

PRICES_ROOT = get_settings().data_path / "historical_prices"
# Preference order. Real data wins whenever it is present.
PROVENANCE_ORDER = [Provenance.REAL_MARKET_DATA, Provenance.SYNTHETIC]


@dataclass(frozen=True)
class LoadSummary:
    universe: str
    provenance: str
    source: str
    tickers_loaded: int
    benchmark_symbol: str | None
    rows_loaded: int
    first_date: str | None
    last_date: str | None
    warnings: list[str]


def _read_manifest(folder: Path) -> dict:
    manifest_path = folder / "_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"No _manifest.json in {folder}. Price folders must declare their "
            "provenance in a manifest; a folder of bare CSVs could be anything, and "
            "'anything' is not a provenance. Generate the fixture with "
            "backend/scripts/generate_synthetic_prices.py or download real data with "
            "backend/scripts/fetch_prices.py."
        )
    return json.loads(manifest_path.read_text())


def _read_csv(path: Path) -> tuple[list[date], list[float]]:
    dates: list[date] = []
    prices: list[float] = []
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            dates.append(date.fromisoformat(row["date"]))
            prices.append(float(row["close"]))
    if len(dates) != len(set(dates)):
        raise ValueError(
            f"{path.name} contains duplicate dates. Two closes for one session means "
            "the file was appended to rather than replaced, and the duplicate would "
            "enter the return series as a spurious 0% day."
        )
    order = sorted(range(len(dates)), key=dates.__getitem__)
    return [dates[i] for i in order], [prices[i] for i in order]


def available_provenances(universe: str, root: Path | None = None) -> list[str]:
    base = root or PRICES_ROOT
    return [
        p.value
        for p in PROVENANCE_ORDER
        if (base / p.value / universe / "_manifest.json").is_file()
    ]


def resolve_folder(
    universe: str, provenance: str | None = None, root: Path | None = None
) -> tuple[Path, Provenance]:
    base = root or PRICES_ROOT
    candidates = (
        [Provenance(provenance)] if provenance else PROVENANCE_ORDER
    )
    for candidate in candidates:
        folder = base / candidate.value / universe
        if (folder / "_manifest.json").is_file():
            return folder, candidate
    raise FileNotFoundError(
        f"No price data found for universe {universe} under {base}. Generate the "
        "synthetic fixture with `python backend/scripts/generate_synthetic_prices.py` "
        "or download real prices with `python backend/scripts/fetch_prices.py`."
    )


def load_universe(
    db: Session,
    universe: str,
    benchmark_symbol: str,
    *,
    provenance: str | None = None,
    root: Path | None = None,
    replace: bool = True,
) -> LoadSummary:
    """Load every series in a universe folder into the database."""
    folder, resolved = resolve_folder(universe, provenance, root)
    manifest = _read_manifest(folder)

    declared = manifest.get("provenance")
    if declared != resolved.value:
        raise ValueError(
            f"{folder}/_manifest.json declares provenance {declared!r} but sits in the "
            f"{resolved.value} folder. Refusing to load: a mislabelled provenance is "
            "worse than no provenance, because everything downstream will trust it."
        )

    source = manifest.get("source", f"{resolved.value} (source not stated in manifest)")
    warnings: list[str] = []
    if resolved is Provenance.SYNTHETIC:
        warnings.append(
            "Loaded SYNTHETIC price data. Every risk figure computed from it "
            "demonstrates the arithmetic and says nothing about any real asset."
        )

    rows = 0
    tickers = 0
    all_dates: list[date] = []
    benchmark_loaded: str | None = None

    for entry in manifest["assets"]:
        path = folder / entry["file"]
        if not path.is_file():
            warnings.append(f"Manifest lists {entry['file']} but the file is missing.")
            continue

        dates, prices = _read_csv(path)
        if len(dates) < 2:
            warnings.append(f"{entry['symbol']}: fewer than two closes, skipped.")
            continue

        returns = prices_to_returns(prices, ReturnMethod.SIMPLE)
        all_dates.extend(dates)
        symbol = entry["symbol"]
        is_benchmark = entry.get("kind") == "BENCHMARK" or symbol == benchmark_symbol

        if is_benchmark:
            benchmark_loaded = symbol
            if replace:
                db.execute(delete(Benchmark).where(Benchmark.symbol == symbol))
            db.add_all(
                [
                    Benchmark(
                        symbol=symbol,
                        date=d,
                        price=p,
                        return_pct=r,
                        source=source,
                        provenance=resolved.value,
                    )
                    for d, p, r in zip(dates, prices, returns)
                ]
            )
        else:
            tickers += 1
            if replace:
                db.execute(delete(AssetReturn).where(AssetReturn.ticker == symbol))
            db.add_all(
                [
                    AssetReturn(
                        ticker=symbol,
                        date=d,
                        price=p,
                        return_pct=r,
                        source=source,
                        provenance=resolved.value,
                    )
                    for d, p, r in zip(dates, prices, returns)
                ]
            )
        rows += len(dates)

    db.add(
        DataLoad(
            universe=universe,
            provenance=resolved.value,
            source=source,
            tickers_loaded=tickers,
            rows_loaded=rows,
        )
    )
    db.commit()

    return LoadSummary(
        universe=universe,
        provenance=resolved.value,
        source=source,
        tickers_loaded=tickers,
        benchmark_symbol=benchmark_loaded,
        rows_loaded=rows,
        first_date=min(all_dates).isoformat() if all_dates else None,
        last_date=max(all_dates).isoformat() if all_dates else None,
        warnings=warnings,
    )


def fetch_series(
    db: Session,
    tickers: list[str],
    *,
    start: date | None = None,
    end: date | None = None,
) -> tuple[dict[str, dict[date, float]], dict[str, set[str]]]:
    """Return {ticker: {date: return}} plus the provenance values seen per ticker.

    The first observation of every series has a NULL return and is excluded here;
    it is stored so the price series stays complete, not so it can be averaged
    into a mean.
    """
    stmt = select(AssetReturn).where(
        AssetReturn.ticker.in_(tickers), AssetReturn.return_pct.is_not(None)
    )
    if start:
        stmt = stmt.where(AssetReturn.date >= start)
    if end:
        stmt = stmt.where(AssetReturn.date <= end)

    series: dict[str, dict[date, float]] = {}
    provenances: dict[str, set[str]] = {}
    for row in db.execute(stmt).scalars():
        series.setdefault(row.ticker, {})[row.date] = float(row.return_pct)
        provenances.setdefault(row.ticker, set()).add(row.provenance)
    return series, provenances


def fetch_benchmark(
    db: Session,
    symbol: str,
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict[date, float]:
    stmt = select(Benchmark).where(
        Benchmark.symbol == symbol, Benchmark.return_pct.is_not(None)
    )
    if start:
        stmt = stmt.where(Benchmark.date >= start)
    if end:
        stmt = stmt.where(Benchmark.date <= end)
    return {row.date: float(row.return_pct) for row in db.execute(stmt).scalars()}
