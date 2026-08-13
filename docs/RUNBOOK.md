# How to run AlphaRisk IQ

Written for a Mac, from a cold start. Every command has an expected output so you
can tell at each step whether it worked.

**Time:** about 10 minutes the first time, 30 seconds after that.

---

## Two things that will bite you, read these first

**1. Never paste a command with a `# comment` on the end.**

macOS zsh ships with `interactive_comments` **off**, so `#` is not a comment on the
command line — it becomes an argument. This:

```
source .venv/bin/activate          # prompt must now show (.venv)
```

fails with `zsh: unknown file attribute: v`, because zsh parses the `(.venv)` in
the *comment* as a glob qualifier. The venv silently never activates and every
command after it dies with `command not found: pip`.

No code block in this document has inline comments, for exactly that reason. If
you want them to work anyway, run this once:

```bash
echo 'setopt interactive_comments' >> ~/.zshrc
```

**2. Python must be 3.10–3.13, not 3.14.**

`numpy`, `pydantic-core` and `psycopg2-binary` publish wheels up to 3.13. On 3.14
pip tries to compile them from source and fails after several screens of C and
Rust errors. Check what you have:

```bash
python3 --version
ls /opt/homebrew/bin/python3.1*
```

If `python3` is 3.14 but you have a `python3.13` in that list, use it explicitly:
`python3.13 -m venv .venv`. If you have neither, `brew install python@3.13`.

---

## What you need first

Open **Terminal** (Cmd+Space, type `Terminal`, Enter) and check three things:

```bash
python3 --version
node --version
git --version
```

Python must be 3.10–3.13 (see above). Node must be 18 or newer — if it's missing,
install the LTS build from [nodejs.org](https://nodejs.org/).

You do **not** need Docker, Postgres, or an API key to run this. All three are
optional and covered at the end.

---

## The one-command version

If you would rather not do the next four steps by hand:

```bash
cd ~/BASE/02-projects/AlphaRiskIQ
./dev.sh
```

`dev.sh` finds a supported Python, creates the venv, installs, creates `.env`,
runs the tests, and starts the API. It refuses with a clear message if your Python
is out of range instead of failing halfway through a compile. Then skip to
**Step 5** for the frontend.

---

## Step 1 — Go to the project folder

The project lives at `~/BASE/02-projects/AlphaRiskIQ`. In Terminal:

```bash
cd ~/BASE/02-projects/AlphaRiskIQ
```

Check you are in the right place:

```bash
ls
```

**Expected:**

```
LICENSE            README.md          data               frontend
PUSH_TO_GITHUB.sh  backend            docker-compose.yml docs
```

If you see `No such file or directory`, you are in the wrong folder. Run `cd ~`
and try again.

---

## Step 2 — Set up the backend

You will run two Terminal windows for the rest of this: one for the backend, one
for the frontend. This is **window 1**.

Paste these **one line at a time**, not as a block:

```bash
cd ~/BASE/02-projects/AlphaRiskIQ/backend
python3.13 -m venv .venv
source .venv/bin/activate
```

If `python3.13` is not found but `python3 --version` says 3.10, 3.11, 3.12 or
3.13, use `python3 -m venv .venv` instead.

Your prompt should now start with `(.venv)`. That means the virtual environment is
active — a sandbox for this project's Python packages so they don't collide with
anything else on your machine.

Install the dependencies:

```bash
pip install -r requirements-dev.txt
```

Takes 1–2 minutes. **Expected** on the last line:

```
Successfully installed anthropic-0.42.0 fastapi-0.115.6 ... numpy-2.2.1 ...
```

Create your local config file:

```bash
cp .env.example .env
```

That is it. The default config uses SQLite, so there is no database to install or
start — the file is created automatically on first run.

---

## Step 3 — Run the tests (this is the real "is it working" check)

```bash
python -m pytest -q
```

**Expected:**

```
................................................................
................................................................
............
156 passed in 9.07s
```

**If you see `156 passed`, the entire risk engine is verified.** No network, no
database, no API key. These are not smoke tests — they check Sharpe, both Sortino
conventions, the VaR crossover, the Kupiec statistic and the beta estimator
against closed-form mathematical results.

Want to see what they actually test? Run it verbose:

```bash
python -m pytest -v
```

You will see names like
`test_standard_downside_deviation_converges_to_the_closed_form` and
`test_the_test_is_out_of_sample`.

<details>
<summary>If tests fail</summary>

| Error | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'fastapi'` | The venv isn't active. Run `source .venv/bin/activate` — your prompt must show `(.venv)`. |
| `zsh: unknown file attribute: v` | You pasted a command with a trailing `# comment`. Re-run just the command, no comment. |
| `zsh: command not found: pip` / `python` / `uvicorn` | The venv never activated — almost always the line above. |
| `No such file or directory: '.../data/universes/universes.json'` | You're in the wrong directory. `cd ~/BASE/02-projects/AlphaRiskIQ/backend`. |
| `command not found: pytest` | Use `python -m pytest`, not bare `pytest`. |

</details>

---

## Step 4 — Start the backend server

Still in **window 1**, still with `(.venv)` showing:

```bash
uvicorn app.main:app --reload
```

**Expected:**

```
INFO:     Will watch for changes in these directories: ['.../backend']
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     alphariskiq: NSE_INDIA price data available: SYNTHETIC
INFO:     alphariskiq: US price data available: SYNTHETIC
INFO:     alphariskiq: No ANTHROPIC_API_KEY configured. Investment reports will use
          the deterministic template fallback ...
INFO:     Application startup complete.
```

Those last three lines are the app telling you exactly what state it is in. Both
are expected and neither is an error.

**Leave this window running.** Closing it or pressing Ctrl+C stops the backend.

### Check it works

Open **http://localhost:8000/docs** in your browser. You should get an interactive
API page listing every endpoint. That page is generated from the code, so if it
loads, the backend is healthy.

Two more worth opening now:

- **http://localhost:8000/health** → `{"status":"ok"}`
- **http://localhost:8000/methodology** → a wall of JSON with every formula and
  convention the app uses. This is the page to show someone who asks whether the
  numbers are real.

---

## Step 5 — Start the frontend

Open a **second Terminal window** (Cmd+N).

```bash
cd ~/BASE/02-projects/AlphaRiskIQ/frontend
npm install
```

Takes 1–2 minutes the first time. Warnings about deprecated packages are normal
and safe to ignore.

```bash
npm run dev
```

**Expected:**

```
  VITE v6.4.3  ready in 412 ms

  ➜  Local:   http://localhost:5173/
```

Open **http://localhost:5173**. You should see a dark dashboard headed
**AlphaRisk IQ** with "No portfolios yet."

**Leave this window running too.** You now have two servers up: backend on 8000,
frontend on 5173.

---

## Step 6 — Drive the app end to end

This is the demo flow. Six clicks.

**1. Load price data.** Click **New portfolio**. The universe dropdown is on
`NSE India (NIFTY 50 constituents)`. Click **Load price data**.

> Expected: a yellow `SYNTHETIC` chip appears with "8 tickers · 11,340 rows ·
> 2021-09-01 to 2026-06-30", and a warning that these are not real prices. That
> warning is the app working correctly — see Step 8 to replace it with real data.

**2. Create the portfolio.** The weight boxes are pre-filled with a sensible
5-stock portfolio (Reliance 25, TCS 20, HDFC Bank 20, ITC 20, L&T 15). Change them
if you like. Click **Create portfolio**.

> Expected: you land on the portfolio page. A yellow synthetic-data banner sits at
> the top.

**3. Compute risk metrics.** Click **Compute risk metrics**.

> Expected, on the synthetic data:
>
> | | |
> |---|---|
> | Annualised return | 15.99% |
> | Annualised volatility | 20.05% |
> | Sharpe | 0.48 |
> | Sortino — STANDARD | 0.65 |
> | Sortino — NEGATIVE_ONLY_STDDEV | 0.56 |
> | Max drawdown | 31.16% |
>
> Two Sortino rows, not one. That is the point of that panel.

**4. Read the VaR table.** Scroll to **Value at Risk and Expected Shortfall**:

```
            VaR historical   VaR parametric   ratio     ES historical   ES parametric   ratio
95%           1,79,733         2,02,202       0.89×       3,26,276        2,55,194      1.28×
99%           4,87,382         2,88,628       1.69×       5,98,081        3,31,603      1.80×
```

Read the 95% row across. VaR says the normal fit is conservative; ES says it is
optimistic. Both are correct, and the note underneath explains why. **This is the
single most interesting thing in the project** — the explanation is in the README
under "The thing I got wrong, and then got right."

**5. Backtest.** Scroll to **VaR backtesting — Kupiec proportion-of-failures**.
Both methods should show `PASS` on this portfolio, with ~50 breaches in 1,009
out-of-sample days against 50.5 expected.

> Try the **US** universe later — its parametric VaR comes back
> `FAIL_OVERSTATES_RISK`, which is a much better story to have on screen.

**6. Stress test and report.** In the stress panel, pick
`Global Financial Crisis - NIFTY 50 peak to trough`, leave the mode on
**Beta-adjusted**, click **Run scenario**.

> Expected: −60.69%, ₹1,00,00,000 → ₹39,31,316, portfolio beta 1.014, and a
> per-holding table showing ITC shocked at β 0.65 while HDFC Bank takes β 1.30.
> Underneath, the derivation: `2524.2 / 6287.85 - 1 = -0.5986`.

Then scroll up and click **Generate investment report**. Inside the report, click
**Show the exact payload the model was given** — that JSON is what proves the AI
computed nothing.

---

## Step 7 — Stopping and restarting

**To stop:** press `Ctrl+C` in each Terminal window.

**To start again later** — two windows.

Window 1:

```bash
cd ~/BASE/02-projects/AlphaRiskIQ/backend && source .venv/bin/activate && uvicorn app.main:app --reload
```

Window 2:

```bash
cd ~/BASE/02-projects/AlphaRiskIQ/frontend && npm run dev
```

No reinstalling. Your portfolios persist in `backend/alphariskiq.db`.

**To wipe everything and start clean:** `rm backend/alphariskiq.db` — it is
recreated on next startup.

---

## Step 8 — Load real market data (do this before showing anyone)

Everything above runs on synthetic prices, and the app says so on every screen.
To replace them with real ones:

```bash
cd ~/BASE/02-projects/AlphaRiskIQ
source backend/.venv/bin/activate
pip install -r backend/requirements-data.txt
python backend/scripts/fetch_prices.py --universe NSE_INDIA --years 5
python backend/scripts/fetch_prices.py --universe US --years 5
```

**Expected:**

```
  ^NSEI              1234 rows
  RELIANCE.NS        1231 rows
  ...
NSE_INDIA: 9 series -> .../data/historical_prices/REAL_MARKET_DATA/NSE_INDIA
```

Then in the app: **New portfolio → Load price data** again. The chip turns green
and reads `REAL_MARKET_DATA`, and the yellow banner disappears everywhere. Rebuild
the portfolio and recompute — every number is now about real assets.

> Needs an internet connection. If a ticker fails, the script says which one and
> carries on; the manifest records the failures.

**Before you quote any Sharpe ratio from this**, fix the risk-free rates in
`data/universes/universes.json`. They are marked
`APPROXIMATE_PLACEHOLDER_VERIFY_BEFORE_QUOTING` for a reason, and the value used
is recorded in every result.

---

## Optional — the AI-narrated report

Without a key you get the deterministic template. Every number is identical; only
the prose differs. To turn on narration, edit `backend/.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Restart the backend. `GET /portfolios/{id}/report-status` will now say
`"would_produce": "LLM"`.

Never commit that file — `.env` is gitignored, and the test suite runs with the
key blank on purpose.

---

## Optional — run the whole thing in Docker

If you have Docker Desktop installed and running:

```bash
cd ~/BASE/02-projects/AlphaRiskIQ
docker compose up --build
```

Gives you real PostgreSQL instead of SQLite, at the same URLs (frontend 5173,
backend 8000). First build takes a few minutes. Stop with `Ctrl+C`; wipe the
database with `docker compose down -v`.

Use this when you want to say "it runs on Postgres in containers" — the local
setup above is faster for day-to-day work.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `zsh: command not found: uvicorn` | The venv isn't active. `source .venv/bin/activate` — the prompt must show `(.venv)`. |
| `[Errno 48] Address already in use` | Something is already on that port. `lsof -ti:8000 \| xargs kill -9` (or `:5173`). |
| Frontend loads but every panel errors | The backend isn't running, or isn't on port 8000. Check window 1 and confirm http://localhost:8000/health responds. |
| `Cannot reach the API...` in the UI | The backend isn't running, or isn't on port 8000. Check window 1 and that http://localhost:8000/health responds. |
| `409: No return data loaded for: RELIANCE.NS` | You skipped **Load price data**. Go to **New portfolio** and click it. |
| Vite errors on `node_modules/.vite/deps/...` | Stale dependency cache. `rm -rf node_modules/.vite` and `npm run dev` again. |
| `422: Scenario 'covid_crash_2020' is defined on the S&P 500` | You applied a US scenario to an Indian portfolio. Correct behaviour — pick the `_nifty` version. |
| `409: No risk metrics computed yet` | Compute the metrics before generating the report. The report narrates over computed figures. |
| `npm ERR! code EACCES` | Permissions. Do **not** use `sudo npm`. Delete `node_modules` and re-run `npm install`. |
| `The project root contains the "#" character` | You pasted `npm run dev  # leave running`. Harmless — Vite still starts — but re-run it without the comment. |
| Browser shows a blank white page | You went to `localhost` (port 80). The app is on **`localhost:5173`**. |
| pip fails compiling numpy / pydantic-core | Your venv is Python 3.14. `rm -rf backend/.venv`, then rebuild with `python3.13 -m venv .venv`. |
| Numbers differ from this document | You loaded real data instead of synthetic — expected, and the point. The figures above are from the synthetic fixture only. |

---

## The 30-second version, once it is all installed

Window 1:

```bash
cd ~/BASE/02-projects/AlphaRiskIQ/backend && source .venv/bin/activate && uvicorn app.main:app --reload
```

Window 2:

```bash
cd ~/BASE/02-projects/AlphaRiskIQ/frontend && npm run dev
```

Browser: **http://localhost:5173** — with the port. Plain `localhost` is port 80
and shows a blank page.

Verify at any time with: `cd backend && source .venv/bin/activate && python -m pytest -q` → `156 passed`.
