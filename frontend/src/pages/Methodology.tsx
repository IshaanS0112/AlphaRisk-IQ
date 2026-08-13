import { useEffect, useState } from "react";

import * as api from "../api/client";
import { Empty, ErrorBox, Note, Panel } from "../components/Bits";

export default function Methodology() {
  const [methodology, setMethodology] = useState<Record<string, any> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getMethodology()
      .then(setMethodology)
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorBox message={error} />;
  if (!methodology) return <Empty>Loading…</Empty>;

  return (
    <div className="space-y-6">
      <Panel
        title="Formulas"
        subtitle="Published as an endpoint, because a claim that the figures are computed rather than generated is only checkable if the formulas behind them are visible without reading the source."
      >
        <dl className="space-y-3">
          {Object.entries(methodology.formulas as Record<string, string>).map(
            ([key, formula]) => (
              <div key={key} className="rounded-md border border-edge bg-ink p-3">
                <dt className="font-mono text-xs text-accent">{key}</dt>
                <dd className="mt-1 font-mono text-xs leading-relaxed text-slate-300">
                  {formula}
                </dd>
              </div>
            ),
          )}
        </dl>
      </Panel>

      <Panel
        title="Conventions"
        subtitle="Two correct implementations of 'the Sharpe ratio' routinely disagree. This is what makes the disagreement diagnosable."
      >
        <dl className="space-y-2">
          {Object.entries(methodology.conventions as Record<string, unknown>).map(
            ([key, value]) => (
              <div
                key={key}
                className="flex flex-col gap-1 border-b border-edge py-2 last:border-0 sm:flex-row sm:gap-4"
              >
                <dt className="font-mono text-xs text-muted sm:w-64 sm:shrink-0">{key}</dt>
                <dd className="text-xs leading-relaxed text-slate-300">
                  {Array.isArray(value) ? value.join(", ") : String(value)}
                </dd>
              </div>
            ),
          )}
        </dl>
      </Panel>

      <Panel
        title="Sample requirements"
        subtitle="Below these counts a metric is returned as null with a stated reason rather than as a number that looks like an answer."
      >
        <dl className="space-y-2">
          {Object.entries(methodology.sample_requirements as Record<string, unknown>).map(
            ([key, value]) => (
              <div key={key} className="flex gap-4 border-b border-edge py-2 last:border-0">
                <dt className="font-mono text-xs text-muted sm:w-64 sm:shrink-0">{key}</dt>
                <dd className="text-xs text-slate-300">{String(value)}</dd>
              </div>
            ),
          )}
        </dl>
      </Panel>

      <Panel
        title="Scenario library"
        subtitle="Magnitudes are recomputed from the stored index closing levels on every request. Nothing here is a hard-coded percentage."
      >
        <div className="overflow-x-auto rounded-md border border-edge">
          <table className="w-full min-w-[760px]">
            <thead className="bg-ink">
              <tr>
                <th className="th">Scenario</th>
                <th className="th">Index</th>
                <th className="th">Peak</th>
                <th className="th">Trough</th>
                <th className="th">Derivation</th>
                <th className="th">Basis</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-edge">
              {Object.values(methodology.scenarios as Record<string, any>).map(
                (scenario: any) => (
                  <tr key={scenario.name}>
                    <td className="td font-mono text-xs text-slate-100">{scenario.name}</td>
                    <td className="td text-xs text-muted">{scenario.index}</td>
                    <td className="td stat text-xs">
                      {scenario.peak_level.toLocaleString()}
                      <div className="text-[11px] text-muted">{scenario.peak_date}</div>
                    </td>
                    <td className="td stat text-xs">
                      {scenario.trough_level.toLocaleString()}
                      <div className="text-[11px] text-muted">{scenario.trough_date}</div>
                    </td>
                    <td className="td font-mono text-xs text-accent">
                      {scenario.derivation}
                    </td>
                    <td className="td text-[11px] text-muted">{scenario.basis}</td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel
        title="Not implemented in V1"
        subtitle="Published rather than left to be discovered."
      >
        <dl className="space-y-3">
          {Object.entries(
            methodology.not_implemented_in_v1 as Record<string, string>,
          ).map(([key, reason]) => (
            <div key={key}>
              <dt className="font-mono text-xs text-warn">{key}</dt>
              <dd className="mt-1 text-xs leading-relaxed text-muted">{reason}</dd>
            </div>
          ))}
        </dl>
        <Note>{methodology.llm_role}</Note>
      </Panel>
    </div>
  );
}
