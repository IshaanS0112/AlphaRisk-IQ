import { useState } from "react";

import type { Scenario, ShockMode, StressTest } from "../api/types";
import { money, pct, ratio } from "../api/format";
import { Chip, Empty, ErrorBox, Note, Panel } from "./Bits";

export default function StressTestView({
  scenarios,
  tests,
  currency,
  busy,
  error,
  onRun,
}: {
  scenarios: Scenario[];
  tests: StressTest[];
  currency: string;
  busy: boolean;
  error: string | null;
  onRun: (
    payload:
      | { scenario_name: string; mode: ShockMode }
      | { custom_shock_pct: number; custom_label?: string; mode: ShockMode },
  ) => void;
}) {
  const [scenarioName, setScenarioName] = useState(scenarios[0]?.name ?? "");
  const [mode, setMode] = useState<ShockMode>("BETA_ADJUSTED");
  const [customPct, setCustomPct] = useState("20");

  const selected = scenarios.find((s) => s.name === scenarioName);

  return (
    <Panel
      title="Stress testing"
      subtitle="Single-period repricing under an index-level shock. Scenario magnitudes are recomputed from published index closing levels every time, never stored as a percentage."
    >
      <div className="grid gap-4 lg:grid-cols-[1fr_auto]">
        <div className="space-y-3">
          <div>
            <label className="label" htmlFor="scenario">
              Scenario
            </label>
            <select
              id="scenario"
              className="field"
              value={scenarioName}
              onChange={(event) => setScenarioName(event.target.value)}
            >
              {scenarios.map((scenario) => (
                <option key={scenario.name} value={scenario.name}>
                  {scenario.label} ({pct(scenario.shock_pct)})
                </option>
              ))}
            </select>
          </div>

          <div>
            <span className="label">Shock mode</span>
            <div className="flex gap-2">
              {(["UNIFORM", "BETA_ADJUSTED"] as const).map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setMode(option)}
                  className={
                    mode === option
                      ? "btn bg-accent/20 text-accent ring-1 ring-accent/40"
                      : "btn-ghost"
                  }
                >
                  {option === "UNIFORM" ? "Uniform (β = 1)" : "Beta-adjusted (OLS)"}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="flex flex-col justify-end gap-2">
          <button
            type="button"
            className="btn-primary"
            disabled={busy || !scenarioName}
            onClick={() => onRun({ scenario_name: scenarioName, mode })}
          >
            {busy ? "Running…" : "Run scenario"}
          </button>
          <div className="flex gap-2">
            <input
              className="field w-24"
              value={customPct}
              onChange={(event) => setCustomPct(event.target.value)}
              aria-label="Custom shock percentage"
            />
            <button
              type="button"
              className="btn-ghost whitespace-nowrap"
              disabled={busy}
              onClick={() =>
                onRun({
                  custom_shock_pct: -Math.abs(Number(customPct)) / 100,
                  custom_label: `Custom −${Math.abs(Number(customPct))}%`,
                  mode,
                })
              }
            >
              Custom −%
            </button>
          </div>
        </div>
      </div>

      {selected && (
        <Note>
          <strong className="text-slate-300">{selected.index}</strong> closed at{" "}
          {selected.peak_level.toLocaleString()} on {selected.peak_date} and{" "}
          {selected.trough_level.toLocaleString()} on {selected.trough_date}.{" "}
          <span className="font-mono text-accent">{selected.derivation}</span>. Basis:{" "}
          {selected.basis}. Source: {selected.source} ({selected.verification_status}).{" "}
          {selected.note}
        </Note>
      )}

      {error && (
        <div className="mt-4">
          <ErrorBox message={error} />
        </div>
      )}

      <div className="mt-6 space-y-5">
        {tests.length === 0 && <Empty>No scenario has been run yet.</Empty>}
        {[...tests].reverse().map((test) => (
          <article key={test.id} className="rounded-md border border-edge bg-ink p-4">
            <header className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="text-sm font-medium text-slate-100">
                  {test.scenario_label}
                </h3>
                <p className="text-[11px] text-muted">
                  Index shock {pct(test.shock_config.index_shock_pct)} · portfolio beta{" "}
                  {ratio(test.shock_config.portfolio_beta)}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Chip tone="accent">{test.shock_mode}</Chip>
                <Chip tone={test.pct_loss > 0.4 ? "bad" : "warn"}>
                  −{pct(test.pct_loss)}
                </Chip>
              </div>
            </header>

            <p className="stat mb-3 text-lg">
              {money(test.portfolio_value_before, currency)}{" "}
              <span className="text-muted">→</span>{" "}
              <span className="text-bad">
                {money(test.portfolio_value_after, currency)}
              </span>
            </p>

            <div className="overflow-x-auto rounded border border-edge">
              <table className="w-full min-w-[560px]">
                <thead className="bg-panel">
                  <tr>
                    <th className="th">Holding</th>
                    <th className="th">Weight</th>
                    <th className="th">Beta</th>
                    <th className="th">Effective shock</th>
                    <th className="th">Loss</th>
                    <th className="th">Share of loss</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-edge">
                  {test.holding_impacts.map((impact) => (
                    <tr key={impact.ticker}>
                      <td className="td text-slate-100">{impact.ticker}</td>
                      <td className="td stat">{pct(impact.weight, 1)}</td>
                      <td className="td stat">{ratio(impact.beta)}</td>
                      <td className="td stat">{pct(impact.effective_shock)}</td>
                      <td className="td stat">{money(impact.loss, currency)}</td>
                      <td className="td stat">
                        {pct(impact.contribution_to_portfolio_loss_pct, 1)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {test.shock_config.notes?.map((note, index) => (
              <p
                key={index}
                className="mt-3 border-l-2 border-edge pl-3 text-xs leading-relaxed text-muted"
              >
                {note}
              </p>
            ))}
          </article>
        ))}
      </div>
    </Panel>
  );
}
