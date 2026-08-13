"""Provenance, the loader's refusals, and the synthetic fixture's properties."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from app.enums import Provenance
from app.services import market_data

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
PRICES_ROOT = REPO_ROOT / "data" / "historical_prices"
SYNTHETIC_NSE = PRICES_ROOT / "SYNTHETIC" / "NSE_INDIA"


def _series(symbol: str) -> np.ndarray:
    import csv

    with (SYNTHETIC_NSE / f"{symbol}.csv").open() as handle:
        prices = np.array([float(row["close"]) for row in csv.DictReader(handle)])
    return prices[1:] / prices[:-1] - 1.0


# --- The manifest contract ----------------------------------------------------

def test_the_fixture_declares_itself_synthetic_in_terms_nobody_can_miss():
    manifest = json.loads((SYNTHETIC_NSE / "_manifest.json").read_text())
    assert manifest["provenance"] == Provenance.SYNTHETIC.value
    assert "NOT MARKET PRICES" in manifest["WARNING"]
    assert manifest["model"]["student_t_dof"] == 5.0
    assert manifest["model"]["regime"]["stress_vol_multiplier"] > 1


def test_a_price_folder_with_no_manifest_is_refused(tmp_path):
    folder = tmp_path / "SYNTHETIC" / "NSE_INDIA"
    folder.mkdir(parents=True)
    (folder / "TCS.NS.csv").write_text("date,close\n2026-01-01,100\n")
    with pytest.raises(FileNotFoundError, match="No price data found"):
        market_data.resolve_folder("NSE_INDIA", root=tmp_path)


def test_a_manifest_that_lies_about_its_folder_is_refused(tmp_path):
    """A mislabelled provenance is worse than none: everything downstream trusts it."""
    folder = tmp_path / "REAL_MARKET_DATA" / "NSE_INDIA"
    folder.mkdir(parents=True)
    (folder / "_manifest.json").write_text(
        json.dumps({"provenance": "SYNTHETIC", "source": "x", "assets": []})
    )
    from sqlalchemy.orm import Session

    from app.db.session import engine

    with Session(engine) as db, pytest.raises(ValueError, match="Refusing to load"):
        market_data.load_universe(db, "NSE_INDIA", "^NSEI", root=tmp_path)


def test_real_data_is_preferred_over_synthetic_when_both_exist(tmp_path):
    for provenance in ("SYNTHETIC", "REAL_MARKET_DATA"):
        folder = tmp_path / provenance / "US"
        folder.mkdir(parents=True)
        (folder / "_manifest.json").write_text(json.dumps({"provenance": provenance}))
    _, resolved = market_data.resolve_folder("US", root=tmp_path)
    assert resolved is Provenance.REAL_MARKET_DATA


def test_an_explicit_provenance_request_overrides_the_preference(tmp_path):
    for provenance in ("SYNTHETIC", "REAL_MARKET_DATA"):
        folder = tmp_path / provenance / "US"
        folder.mkdir(parents=True)
        (folder / "_manifest.json").write_text(json.dumps({"provenance": provenance}))
    _, resolved = market_data.resolve_folder("US", provenance="SYNTHETIC", root=tmp_path)
    assert resolved is Provenance.SYNTHETIC


def test_duplicate_dates_in_a_csv_are_refused(tmp_path):
    path = tmp_path / "X.csv"
    path.write_text("date,close\n2026-01-05,100\n2026-01-05,101\n")
    with pytest.raises(ValueError, match="duplicate dates"):
        market_data._read_csv(path)


# --- The fixture's statistical properties -------------------------------------

def test_the_fixture_is_byte_identical_when_regenerated(tmp_path):
    """A 'reproducible' dataset that is not reproducible is the classic silent bug.

    Python randomises string hashing per process, so a seed derived from
    ``hash(str)`` would give a different fixture on every run. The generator uses
    zlib.crc32 instead; this is the test that keeps it that way.
    """
    subprocess.run(
        [
            sys.executable,
            str(BACKEND_ROOT / "scripts" / "generate_synthetic_prices.py"),
            "--universe",
            "NSE_INDIA",
            "--out",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
    )
    regenerated = (tmp_path / "NSE_INDIA" / "TCS.NS.csv").read_bytes()
    committed = (SYNTHETIC_NSE / "TCS.NS.csv").read_bytes()
    assert regenerated == committed


def test_the_fixture_has_the_fat_tails_the_demo_depends_on():
    """Excess kurtosis well above the normal's 3.0, at the portfolio level."""
    weights = {
        "RELIANCE.NS": 0.25,
        "TCS.NS": 0.20,
        "HDFCBANK.NS": 0.20,
        "ITC.NS": 0.20,
        "LT.NS": 0.15,
    }
    portfolio = sum(w * _series(t) for t, w in weights.items())
    centred = portfolio - portfolio.mean()
    kurtosis = float((centred**4).mean() / portfolio.var() ** 2)
    assert kurtosis > 5.0


def test_the_fixture_is_negatively_skewed_like_real_equity_returns():
    portfolio = 0.5 * _series("RELIANCE.NS") + 0.5 * _series("ITC.NS")
    centred = portfolio - portfolio.mean()
    skew = float((centred**3).mean() / portfolio.std() ** 3)
    assert skew < -0.2


def test_the_generating_betas_are_recoverable_from_the_fixture():
    """Turns the beta estimator from 'it returns a number' into 'it returns the
    right number' - the generating beta is known, so this is a real check."""
    from app.services.stress_test_engine import estimate_beta

    manifest = json.loads((SYNTHETIC_NSE / "_manifest.json").read_text())
    market = _series("_NSEI")
    for asset in manifest["assets"]:
        if asset["kind"] != "ASSET":
            continue
        estimate = estimate_beta(_series(asset["symbol"]), market, ticker=asset["symbol"])
        assert estimate.beta == pytest.approx(asset["generating_beta"], rel=0.08)


def test_the_defensive_names_really_do_have_lower_betas_than_the_financials():
    from app.services.stress_test_engine import estimate_beta

    market = _series("_NSEI")
    staple = estimate_beta(_series("ITC.NS"), market).beta
    bank = estimate_beta(_series("HDFCBANK.NS"), market).beta
    assert staple < 0.8 < bank


def test_the_fixture_lands_in_a_plausible_volatility_range():
    """A demo whose portfolio shows 90% annualised volatility is not a demo."""
    portfolio = 0.5 * _series("RELIANCE.NS") + 0.5 * _series("TCS.NS")
    annualised = float(portfolio.std(ddof=1) * np.sqrt(250))
    assert 0.12 < annualised < 0.35
