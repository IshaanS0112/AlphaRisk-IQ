"""Shared fixtures.

Two kinds of test live here.

The **engine tests** exercise the pure computation functions directly - no
database, no network, no ORM. That is deliberate: every claim this project makes
(the two Sortino conventions genuinely differ and in a direction that depends on
skew, the VaR crossover is where the docstring says it is, the beta estimator
recovers a known beta, the report degrades identically without an API key) is a
claim about those functions. Anyone who clones the repo can check all of it with
``pytest`` and nothing running.

Several of them assert against **closed forms rather than golden numbers**. A
test that says "downside deviation of this array is 0.00981" only proves the code
has not changed. A test that says "for a large standard normal sample it must
converge to sqrt(1/2) * sigma, and the negative-only variant to
sqrt(1 - 2/pi) * sigma" proves the code implements the definition it claims to.

The **API tests** run the real FastAPI app against a temporary SQLite file. The
models declare JSONB and UUID as dialect *variants*, so the same schema loads on
SQLite - which means the HTTP contract is tested on a fresh clone with no
Postgres container up, rather than being the one layer nobody ever runs.

The price fixture is the committed synthetic dataset, loaded through the real
loader. Using the real files rather than inline arrays means a test failure after
regenerating the fixture is a real signal.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

# Must happen before app.config is imported anywhere: get_settings is cached, so
# the first read of DATABASE_URL is the one that sticks.
_TMP_DB = Path(tempfile.mkdtemp(prefix="alphariskiq-tests-")) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ.setdefault("ANTHROPIC_API_KEY", "")

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
REPO_ROOT = BACKEND_ROOT.parent
PRICES_ROOT = REPO_ROOT / "data" / "historical_prices"

from app.config import Settings  # noqa: E402

NSE_HOLDINGS = [
    {"ticker": "RELIANCE.NS", "weight": 25},
    {"ticker": "TCS.NS", "weight": 20},
    {"ticker": "HDFCBANK.NS", "weight": 20},
    {"ticker": "ITC.NS", "weight": 20},
    {"ticker": "LT.NS", "weight": 15},
]


@pytest.fixture
def settings() -> Settings:
    """Default parameter set, isolated from any .env on the developer's machine."""
    return Settings(_env_file=None)


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(20260730)


@pytest.fixture
def normal_returns(rng: np.random.Generator) -> np.ndarray:
    """A large symmetric sample, for asserting against closed forms."""
    return rng.standard_normal(400_000) * 0.01


@pytest.fixture
def fat_tailed_returns(rng: np.random.Generator) -> np.ndarray:
    """Standardised Student-t(5): unit variance, excess kurtosis."""
    dof = 5.0
    return rng.standard_t(dof, size=400_000) / np.sqrt(dof / (dof - 2.0)) * 0.01


@pytest.fixture
def client():
    """FastAPI TestClient over a fresh SQLite schema."""
    from fastapi.testclient import TestClient

    from app.db.session import Base, engine
    from app.main import app

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def loaded_client(client):
    """A client with the NSE synthetic price fixture loaded."""
    response = client.post("/market-data/load", json={"universe": "NSE_INDIA"})
    assert response.status_code == 200, response.text
    return client


@pytest.fixture
def portfolio_id(loaded_client) -> str:
    response = loaded_client.post(
        "/portfolios",
        json={
            "name": "India Core 5",
            "universe": "NSE_INDIA",
            "base_value": 10_000_000,
            "holdings": NSE_HOLDINGS,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]
