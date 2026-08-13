import type { RiskMetrics } from "../api/types";
import { pct, ratio } from "../api/format";
import { Chip, Note, Panel } from "./Bits";

const VERDICT_TONE = {
  PASS: "good",
  FAIL_UNDERSTATES_RISK: "bad",
  FAIL_OVERSTATES_RISK: "warn",
  NOT_ENOUGH_DATA: "neutral",
} as const;

export default function BacktestPanel({ metrics }: { metrics: RiskMetrics }) {
  const backtests = Object.entries(metrics.detail.backtests ?? {});
  if (backtests.length === 0) return null;

  return (
    <Panel
      title="VaR backtesting — Kupiec proportion-of-failures"
      subtitle="Rolling out-of-sample: each day's threshold is estimated on the trailing window only, then compared against the next day's realised return."
    >
      <div className="overflow-x-auto rounded-md border border-edge">
        <table className="w-full min-w-[720px]">
          <thead className="bg-ink">
            <tr>
              <th className="th">Method</th>
              <th className="th">Days tested</th>
              <th className="th">Breaches</th>
              <th className="th">Rate</th>
              <th className="th">Expected</th>
              <th className="th">Kupiec LR</th>
              <th className="th">p</th>
              <th className="th">Verdict</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-edge">
            {backtests.map(([method, result]) => (
              <tr key={method}>
                <td className="td text-slate-100">{method}</td>
                <td className="td stat">{result.n_tested}</td>
                <td className="td stat">
                  {result.n_breaches}
                  <span className="ml-1 text-[11px] text-muted">
                    (exp {(result.n_tested * result.expected_breach_rate).toFixed(1)})
                  </span>
                </td>
                <td className="td stat">{pct(result.breach_rate)}</td>
                <td className="td stat text-muted">{pct(result.expected_breach_rate)}</td>
                <td className="td stat">
                  {ratio(result.kupiec_lr, 3)}
                  <span className="ml-1 text-[11px] text-muted">
                    / {result.kupiec_critical_value}
                  </span>
                </td>
                <td className="td stat">{ratio(result.kupiec_p_value, 4)}</td>
                <td className="td">
                  <Chip tone={VERDICT_TONE[result.verdict as keyof typeof VERDICT_TONE]}>
                    {result.verdict.replace(/_/g, " ")}
                  </Chip>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4 space-y-3">
        {backtests.map(([method, result]) =>
          result.notes.map((note, index) => (
            <p
              key={`${method}-${index}`}
              className="border-l-2 border-edge pl-3 text-xs leading-relaxed text-muted"
            >
              <span className="font-mono text-accent">{method}</span> {note}
            </p>
          )),
        )}
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {backtests.map(([method, result]) => (
          <div key={method} className="rounded-md border border-edge bg-ink p-3">
            <div className="label">{method} — breach clustering</div>
            <div className="stat text-sm">
              longest run {result.longest_breach_run} day
              {result.longest_breach_run === 1 ? "" : "s"} · {result.consecutive_breach_days}{" "}
              of {result.n_breaches} breaches sat next to another
            </div>
          </div>
        ))}
      </div>

      <Note>
        Kupiec tests the <em>number</em> of breaches, not their <em>timing</em>. A model
        that breaches five times in one week passes it exactly as cleanly as one that
        breaches five times spread across the year — and the first is far more dangerous,
        because clustered breaches are what wipe out a book. The run statistics above make
        that gap visible; the formal fix is Christoffersen&rsquo;s conditional-coverage
        test, documented as V2.
      </Note>
    </Panel>
  );
}
