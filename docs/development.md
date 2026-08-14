# Development

## Requirements

- **Python 3.10–3.13.** `numpy`, `pydantic-core` and `psycopg2-binary` publish
  wheels up to 3.13; on 3.14 pip falls back to building them from source. CI runs
  3.12.
- **Node 18+** for the frontend.
- Docker is optional and only needed for the PostgreSQL path.

## Setup

```bash
./dev.sh
```

Selects a supported interpreter, creates `backend/.venv`, installs
`requirements-dev.txt`, writes `backend/.env` from the example, runs the test
suite, and starts the API on port 8000. It exits with a diagnostic rather than
proceeding if no supported Python is on `PATH`.

Equivalent by hand:

```bash
cd backend
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python -m pytest -q
uvicorn app.main:app --reload
```

Frontend, in a second shell:

```bash
cd frontend
npm install
npm run dev
```

- API: `http://localhost:8000` — OpenAPI UI at `/docs`
- Dashboard: `http://localhost:5173`

The Vite dev server proxies `/api` to port 8000, so the browser only ever talks
to a single origin. The Docker image does the same through nginx.

## Configuration

`backend/.env.example` documents every setting. The defaults are chosen so a
fresh clone runs with no infrastructure:

| Setting | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./alphariskiq.db` | Created on first startup. Uncomment the PostgreSQL line, or use Docker, for the deployment target. |
| `ANTHROPIC_API_KEY` | empty | Without it, investment reports use the deterministic template. Every computed figure is identical; only the prose differs. |
| `DATA_ROOT` | empty | Resolves to the repository's `data/`. Docker sets `/data`. |

Every risk-calculation convention (trading-day count, `ddof`, quantile method,
drift inclusion, backtest window) is also overridable and is republished by
`GET /methodology`.

## Tests

```bash
cd backend
python -m pytest -q
```

156 tests. No network, no database container, no API key. The models declare
JSONB and UUID as SQLAlchemy dialect variants, so the API integration tests run
the real application against a temporary SQLite file.

Several tests assert against closed forms rather than recorded values — the
Student-t/normal quantile crossover, the two downside-deviation definitions, the
chi-square(1) survival function, and the OLS beta estimator against the betas the
price fixture was generated with.

## Market data

The repository ships a **synthetic** price fixture under
`data/historical_prices/SYNTHETIC/` so that tests, CI and a first clone work
offline. It is labelled as synthetic in its manifest, on every database row it
produces, in every API response and in the UI.

To load real prices:

```bash
pip install -r backend/requirements-data.txt
python backend/scripts/fetch_prices.py --universe NSE_INDIA --years 5
python backend/scripts/fetch_prices.py --universe US --years 5
```

Writes to `data/historical_prices/REAL_MARKET_DATA/`, which is gitignored. The
loader prefers real data whenever it is present. Regenerate the synthetic fixture
with `python backend/scripts/generate_synthetic_prices.py`; it is byte-identical
each time and CI fails if it drifts.

**Before quoting a Sharpe ratio from real data**, set the risk-free rates in
`data/universes/universes.json`. They ship as placeholders marked
`APPROXIMATE_PLACEHOLDER_VERIFY_BEFORE_QUOTING`, and the value used is recorded
in every result's `calculation_basis`.

## Docker

```bash
docker compose up --build
```

PostgreSQL 16, the API, and the built frontend behind nginx. Same ports. The
`data/` directory is mounted read-only — a container that can rewrite its own
scenario magnitudes is a container whose stress results are not reproducible.

## Continuous integration

`.github/workflows/ci.yml` runs four jobs on every push and pull request:

| Job | Checks |
|---|---|
| Backend tests | The full pytest suite on Python 3.12 |
| Synthetic fixture is reproducible | Regenerates the fixture and fails on any diff |
| Scenario magnitudes | Re-derives every crisis magnitude from its stored index levels |
| Frontend | `tsc --noEmit` and a production build |

## Troubleshooting

| Symptom | Cause |
|---|---|
| `ModuleNotFoundError: No module named 'fastapi'` | Virtualenv not active. |
| pip fails compiling numpy or pydantic-core | Virtualenv built with Python 3.14. `rm -rf backend/.venv` and re-run `./dev.sh`. |
| `Cannot reach the API` in the dashboard | Backend not running, or not on port 8000. Check `/health`. |
| `409 No return data loaded for: <ticker>` | Price data not loaded. `POST /market-data/load`. |
| `422 Scenario ... is defined on the S&P 500` | A US scenario applied to an NSE portfolio. Intended behaviour. |
| `EADDRINUSE` on 8000 or 5173 | `lsof -ti:8000 \| xargs kill -9` |
| Vite errors under `node_modules/.vite` | Stale dependency cache. `rm -rf frontend/node_modules/.vite`. |
