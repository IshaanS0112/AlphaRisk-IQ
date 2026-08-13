import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import * as api from "../api/client";
import type { MarketDataLoad, Universe, UniverseName } from "../api/types";
import { pct } from "../api/format";
import { Chip, ErrorBox, Note, Panel } from "../components/Bits";

const PRESETS: Record<UniverseName, { ticker: string; weight: number }[]> = {
  NSE_INDIA: [
    { ticker: "RELIANCE.NS", weight: 25 },
    { ticker: "TCS.NS", weight: 20 },
    { ticker: "HDFCBANK.NS", weight: 20 },
    { ticker: "ITC.NS", weight: 20 },
    { ticker: "LT.NS", weight: 15 },
  ],
  US: [
    { ticker: "AAPL", weight: 30 },
    { ticker: "MSFT", weight: 25 },
    { ticker: "JPM", weight: 20 },
    { ticker: "JNJ", weight: 15 },
    { ticker: "XOM", weight: 10 },
  ],
};

export default function PortfolioBuilder() {
  const navigate = useNavigate();
  const [universes, setUniverses] = useState<Record<UniverseName, Universe> | null>(null);
  const [universe, setUniverse] = useState<UniverseName>("NSE_INDIA");
  const [name, setName] = useState("India Core 5");
  const [baseValue, setBaseValue] = useState("10000000");
  const [weights, setWeights] = useState<Record<string, string>>({});
  const [load, setLoad] = useState<MarketDataLoad | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.getUniverses().then(setUniverses).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    const preset = Object.fromEntries(
      PRESETS[universe].map((h) => [h.ticker, String(h.weight)]),
    );
    setWeights(preset);
    setName(universe === "NSE_INDIA" ? "India Core 5" : "US Core 5");
    setBaseValue(universe === "NSE_INDIA" ? "10000000" : "1000000");
    setLoad(null);
  }, [universe]);

  const current = universes?.[universe];
  const total = useMemo(
    () => Object.values(weights).reduce((sum, w) => sum + (Number(w) || 0), 0),
    [weights],
  );
  const holdings = useMemo(
    () =>
      Object.entries(weights)
        .filter(([, w]) => Number(w) > 0)
        .map(([ticker, w]) => ({ ticker, weight: Number(w) })),
    [weights],
  );

  async function handleLoad() {
    setBusy(true);
    setError(null);
    try {
      setLoad(await api.loadMarketData(universe));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleCreate() {
    setBusy(true);
    setError(null);
    try {
      const portfolio = await api.createPortfolio({
        name,
        universe,
        base_value: Number(baseValue),
        holdings,
      });
      navigate(`/portfolios/${portfolio.id}`);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <Panel
        title="1 · Load price history"
        subtitle="Nothing can be computed until a universe's price series are in the database. Provenance is read from the folder manifest and carried on every row."
      >
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[240px] flex-1">
            <label className="label" htmlFor="universe">
              Universe
            </label>
            <select
              id="universe"
              className="field"
              value={universe}
              onChange={(event) => setUniverse(event.target.value as UniverseName)}
            >
              {universes &&
                Object.values(universes).map((u) => (
                  <option key={u.name} value={u.name}>
                    {u.label}
                  </option>
                ))}
            </select>
          </div>
          <button type="button" className="btn-primary" disabled={busy} onClick={handleLoad}>
            {busy ? "Loading…" : "Load price data"}
          </button>
        </div>

        {current && (
          <Note>
            Benchmark {current.benchmark_label} ({current.benchmark_symbol}) ·{" "}
            {current.trading_days_per_year} trading days a year · risk-free{" "}
            {pct(current.risk_free_annual)} ({current.risk_free_basis}, as of{" "}
            {current.risk_free_as_of}). {current.trading_days_note}
          </Note>
        )}

        {load && (
          <div className="mt-4 rounded-md border border-edge bg-ink p-3 text-xs">
            <div className="mb-2 flex items-center gap-2">
              <Chip tone={load.provenance === "REAL_MARKET_DATA" ? "good" : "warn"}>
                {load.provenance}
              </Chip>
              <span className="text-muted">
                {load.tickers_loaded} tickers · {load.rows_loaded.toLocaleString()} rows ·{" "}
                {load.first_date} to {load.last_date}
              </span>
            </div>
            <p className="text-muted">{load.source}</p>
            {load.warnings.map((warning, index) => (
              <p key={index} className="mt-2 text-warn">
                {warning}
              </p>
            ))}
          </div>
        )}
      </Panel>

      <Panel
        title="2 · Build the portfolio"
        subtitle="Long only. Weights are normalised to sum to 1 and the submitted figures are recorded alongside, so 40/35/25 is visibly the same submission as 0.40/0.35/0.25."
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="name">
              Name
            </label>
            <input
              id="name"
              className="field"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div>
            <label className="label" htmlFor="notional">
              Notional ({current?.currency ?? "—"})
            </label>
            <input
              id="notional"
              className="field"
              value={baseValue}
              onChange={(event) => setBaseValue(event.target.value)}
            />
          </div>
        </div>

        <div className="mt-4 overflow-hidden rounded-md border border-edge">
          <table className="w-full">
            <thead className="bg-ink">
              <tr>
                <th className="th">Ticker</th>
                <th className="th">Name</th>
                <th className="th">Sector</th>
                <th className="th w-32">Weight</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-edge">
              {current?.tickers.map((ticker) => (
                <tr key={ticker.ticker}>
                  <td className="td font-mono text-slate-100">{ticker.ticker}</td>
                  <td className="td text-slate-300">{ticker.name}</td>
                  <td className="td text-muted">{ticker.sector}</td>
                  <td className="td">
                    <input
                      className="field"
                      inputMode="decimal"
                      value={weights[ticker.ticker] ?? ""}
                      placeholder="0"
                      onChange={(event) =>
                        setWeights((previous) => ({
                          ...previous,
                          [ticker.ticker]: event.target.value,
                        }))
                      }
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-muted">
            {holdings.length} holdings, weights summing to{" "}
            <span className="stat text-slate-300">{total.toFixed(2)}</span> — normalised on
            save.
          </p>
          <button
            type="button"
            className="btn-primary"
            disabled={busy || holdings.length === 0 || !name}
            onClick={handleCreate}
          >
            Create portfolio
          </button>
        </div>

        {error && (
          <div className="mt-4">
            <ErrorBox message={error} />
          </div>
        )}
      </Panel>
    </div>
  );
}
