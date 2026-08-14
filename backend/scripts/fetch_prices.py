#!/usr/bin/env python3
"""Download real daily adjusted closes and write them where the loader expects.

    pip install -r backend/requirements-data.txt
    python backend/scripts/fetch_prices.py --universe NSE_INDIA --years 5

Writes ``data/historical_prices/REAL_MARKET_DATA/<UNIVERSE>/<TICKER>.csv`` plus a
``_manifest.json`` recording the source, the download timestamp, the requested
window and the row count per series. The loader reads provenance from that
manifest, so a folder without one is refused rather than assumed to be real.

**Adjusted closes, not raw closes.** ``auto_adjust=True`` gives prices adjusted
for splits and dividends. Using raw closes puts a fake -50% return in the series
on the day of a 2:1 split, and a single such day in a two-year window is enough
to move a 95% VaR estimate materially - it becomes the tail. Dividend adjustment
matters less for a risk number than for a return number, but the two come
together in yfinance and there is no reason to want the unadjusted series here.

**On the data source.** Yahoo Finance is free, unofficial and occasionally wrong
about corporate actions, particularly on Indian tickers. It is adequate for
analysis at this scale and it is not production-grade: a system running real
capital would use the exchange's own end-of-day files or a licensed vendor. The
manifest records the source on every load so the provenance travels with the
data.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UNIVERSES_PATH = ROOT / "data" / "universes" / "universes.json"
OUT_ROOT = ROOT / "data" / "historical_prices" / "REAL_MARKET_DATA"

SOURCE_LABEL = "Yahoo Finance daily adjusted closes (yfinance, auto_adjust=True)"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", action="append", choices=["NSE_INDIA", "US"])
    parser.add_argument(
        "--years",
        type=int,
        default=5,
        help=(
            "Window length. Five years is the sensible default: long enough that a "
            "99%% historical VaR rests on ~12 tail observations rather than 2, short "
            "enough that the sample is still describing the current portfolio's "
            "regime. Ten years buys tail resolution at the cost of averaging over "
            "market regimes that no longer exist."
        ),
    )
    parser.add_argument("--out", type=Path, default=OUT_ROOT)
    args = parser.parse_args()

    try:
        import yfinance as yf
    except ImportError:
        sys.exit(
            "yfinance is not installed. Run:\n"
            "    pip install -r backend/requirements-data.txt\n"
            "It is deliberately not in requirements.txt - the API image has no reason "
            "to carry pandas and a market data client."
        )

    universes = json.loads(UNIVERSES_PATH.read_text())["universes"]
    end = date.today()
    start = end - timedelta(days=int(args.years * 365.25) + 5)

    for universe_name in args.universe or ["NSE_INDIA", "US"]:
        universe = universes[universe_name]
        out_dir = args.out / universe_name
        out_dir.mkdir(parents=True, exist_ok=True)

        symbols = [universe["benchmark_symbol"]] + [
            t["ticker"] for t in universe["tickers"]
        ]
        assets, failures = [], []

        for symbol in symbols:
            frame = yf.download(
                symbol,
                start=start.isoformat(),
                end=end.isoformat(),
                auto_adjust=True,
                progress=False,
            )
            if frame is None or frame.empty:
                failures.append(symbol)
                print(f"  !! no data returned for {symbol}", file=sys.stderr)
                continue

            closes = frame["Close"]
            # yfinance returns a MultiIndex column frame for some symbol shapes;
            # squeeze to a Series either way rather than assuming one.
            if hasattr(closes, "columns"):
                closes = closes.iloc[:, 0]
            closes = closes.dropna()

            filename = f"{symbol.replace('^', '_')}.csv"
            lines = ["date,close"]
            lines += [
                f"{idx.date().isoformat()},{float(value):.4f}"
                for idx, value in closes.items()
            ]
            (out_dir / filename).write_text("\n".join(lines) + "\n")

            is_benchmark = symbol == universe["benchmark_symbol"]
            assets.append(
                {
                    "symbol": symbol,
                    "file": filename,
                    "kind": "BENCHMARK" if is_benchmark else "ASSET",
                    "rows": len(closes),
                    "first_date": closes.index[0].date().isoformat(),
                    "last_date": closes.index[-1].date().isoformat(),
                }
            )
            print(f"  {symbol:<16} {len(closes):>5} rows")

        manifest = {
            "provenance": "REAL_MARKET_DATA",
            "universe": universe_name,
            "source": SOURCE_LABEL,
            "source_caveat": (
                "Yahoo Finance is a free, unofficial feed and is occasionally wrong "
                "about corporate actions, particularly on Indian tickers. Adequate for "
                "this project; a desk would use exchange end-of-day files or a licensed "
                "vendor."
            ),
            "downloaded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "requested_window": {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "years": args.years,
            },
            "price_basis": "ADJUSTED_CLOSE",
            "assets": assets,
            "failed_symbols": failures,
        }
        (out_dir / "_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"{universe_name}: {len(assets)} series -> {out_dir}")
        if failures:
            print(f"  failed: {', '.join(failures)}", file=sys.stderr)


if __name__ == "__main__":
    main()
