import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import * as api from "../api/client";
import type {
  InvestmentReport,
  Portfolio,
  RiskMetrics,
  Scenario,
  ShockMode,
  StressTest,
} from "../api/types";
import { money, pct } from "../api/format";
import BacktestPanel from "../components/BacktestPanel";
import { Chip, Empty, ErrorBox, Panel, ProvenanceBanner } from "../components/Bits";
import ReportView from "../components/ReportView";
import RiskMetricsPanel from "../components/RiskMetricsPanel";
import StressTestView from "../components/StressTestView";
import VarPanel from "../components/VarPanel";

export default function PortfolioDetail() {
  const { portfolioId = "" } = useParams();
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [metrics, setMetrics] = useState<RiskMetrics | null>(null);
  const [stressTests, setStressTests] = useState<StressTest[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [report, setReport] = useState<InvestmentReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stressError, setStressError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const loaded = await api.getPortfolio(portfolioId);
      setPortfolio(loaded);
      const [m, s, r, sc] = await Promise.all([
        api.optional(api.getRiskMetrics(portfolioId)),
        api.listStressTests(portfolioId),
        api.optional(api.getReport(portfolioId)),
        api.getScenarios(loaded.universe),
      ]);
      setMetrics(m);
      setStressTests(s);
      setReport(r);
      setScenarios(sc.scenarios);
    } catch (e: any) {
      setError(e.message);
    }
  }, [portfolioId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function run(label: string, action: () => Promise<unknown>) {
    setBusy(label);
    setError(null);
    try {
      await action();
      await refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function runStress(
    payload:
      | { scenario_name: string; mode: ShockMode }
      | { custom_shock_pct: number; custom_label?: string; mode: ShockMode },
  ) {
    setBusy("stress");
    setStressError(null);
    try {
      await api.runStressTest(portfolioId, payload);
      await refresh();
    } catch (e: any) {
      setStressError(e.message);
    } finally {
      setBusy(null);
    }
  }

  if (!portfolio) {
    return error ? <ErrorBox message={error} /> : <Empty>Loading…</Empty>;
  }

  const provenance = metrics?.calculation_basis?.data_provenance;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">{portfolio.name}</h1>
          <p className="mt-1 text-xs text-muted">
            {portfolio.universe} · {money(portfolio.base_value, portfolio.currency)} notional
            · {portfolio.holdings.length} holdings
          </p>
        </div>
        <Link to="/" className="btn-ghost">
          All portfolios
        </Link>
      </div>

      <ProvenanceBanner provenance={provenance} />
      {error && <ErrorBox message={error} />}

      <Panel title="Composition">
        <div className="flex flex-wrap gap-2">
          {portfolio.holdings.map((holding) => (
            <span
              key={holding.ticker}
              className="rounded-md border border-edge bg-ink px-3 py-2 text-sm"
            >
              <span className="font-mono text-slate-100">{holding.ticker}</span>
              <span className="ml-2 stat text-accent">{pct(holding.weight, 1)}</span>
            </span>
          ))}
        </div>
      </Panel>

      <Panel
        title="Pipeline"
        subtitle="Each stage appends a result rather than overwriting one, so re-running after loading more history leaves the earlier figure in place."
      >
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-primary"
            disabled={busy !== null}
            onClick={() => run("metrics", () => api.computeRiskMetrics(portfolioId))}
          >
            {busy === "metrics" ? "Computing…" : "Compute risk metrics"}
          </button>
          <button
            type="button"
            className="btn-ghost"
            disabled={busy !== null || !metrics}
            onClick={() => run("report", () => api.generateReport(portfolioId))}
          >
            {busy === "report" ? "Generating…" : "Generate investment report"}
          </button>
          {metrics && <Chip tone="good">metrics computed</Chip>}
          {report && <Chip tone="good">report generated</Chip>}
        </div>
      </Panel>

      {metrics ? (
        <>
          <RiskMetricsPanel metrics={metrics} currency={portfolio.currency} />
          <VarPanel metrics={metrics} currency={portfolio.currency} />
          <BacktestPanel metrics={metrics} />
        </>
      ) : (
        <Panel title="Risk metrics">
          <Empty>
            Nothing computed yet. Load the universe&rsquo;s price data, then run the
            pipeline above.
          </Empty>
        </Panel>
      )}

      <StressTestView
        scenarios={scenarios}
        tests={stressTests}
        currency={portfolio.currency}
        busy={busy === "stress"}
        error={stressError}
        onRun={runStress}
      />

      {report && <ReportView report={report} />}
    </div>
  );
}
