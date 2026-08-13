import { useState } from "react";

import type { InvestmentReport } from "../api/types";
import { Chip, Note, Panel } from "./Bits";

export default function ReportView({ report }: { report: InvestmentReport }) {
  const [showContext, setShowContext] = useState(false);
  const narrative = report.ai_narrative;

  return (
    <Panel
      title="Investment report"
      subtitle="The model is given a frozen structured payload and forbidden from computing anything. That payload is stored on this row and is one click away."
      right={
        <div className="flex items-center gap-2">
          <Chip tone={report.status === "LLM" ? "accent" : "neutral"}>
            {report.status === "LLM" ? report.model_used : "Deterministic template"}
          </Chip>
        </div>
      }
    >
      <h3 className="mb-4 text-lg font-medium leading-snug text-slate-100">
        {narrative.headline}
      </h3>

      <div className="space-y-4 text-sm leading-relaxed text-slate-300">
        <p>{narrative.risk_summary}</p>
        <p>{narrative.var_interpretation}</p>
        {narrative.stress_interpretation && <p>{narrative.stress_interpretation}</p>}
      </div>

      <div className="mt-5 grid gap-5 md:grid-cols-2">
        <div>
          <h4 className="label">Key risks</h4>
          <ul className="space-y-2">
            {narrative.key_risks.map((risk, index) => (
              <li key={index} className="flex gap-2 text-sm text-slate-300">
                <span className="text-bad">•</span>
                <span>{risk}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className="label">Caveats</h4>
          <ul className="space-y-2">
            {narrative.caveats.map((caveat, index) => (
              <li key={index} className="flex gap-2 text-sm text-muted">
                <span className="text-muted">•</span>
                <span>{caveat}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {report.fallback_reason && <Note>{report.fallback_reason}</Note>}

      {report.dropped_citations.length > 0 && (
        <div className="mt-4 rounded-md border border-bad/40 bg-bad/10 p-3 text-xs text-bad">
          <strong>Dropped citations:</strong>{" "}
          {report.dropped_citations.join(", ")}. The model named metric keys that were not
          in the context it was given. They were stripped from the narrative and recorded
          here — catching exactly this is why the context is frozen before the call.
        </div>
      )}

      <div className="mt-5">
        <button
          type="button"
          className="btn-ghost"
          onClick={() => setShowContext((value) => !value)}
        >
          {showContext ? "Hide" : "Show"} the exact payload the model was given
        </button>
        {showContext && (
          <pre className="mt-3 max-h-96 overflow-auto rounded-md border border-edge bg-ink p-4 text-[11px] leading-relaxed text-slate-400">
            {JSON.stringify(report.structured_context, null, 2)}
          </pre>
        )}
      </div>

      <Note>
        Cited context keys: {narrative.cited_metrics.join(", ") || "none"}. Every figure in
        the prose above exists in the payload before the model is called, so the narrative
        can be diffed against it.
      </Note>
    </Panel>
  );
}
