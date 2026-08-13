import type { RiskMetrics } from "../api/types";
import { money, pct, ratio } from "../api/format";
import { Chip, Note, Panel } from "./Bits";

/** The comparison the whole project is built around. */
export default function VarPanel({
  metrics,
  currency,
}: {
  metrics: RiskMetrics;
  currency: string;
}) {
  const levels = Object.entries(metrics.detail.var ?? {}).sort(
    ([a], [b]) => Number(a) - Number(b),
  );
  if (levels.length === 0) return null;

  return (
    <Panel
      title="Value at Risk and Expected Shortfall"
      subtitle="One-day horizon, expressed as a positive loss against the portfolio notional."
    >
      <div className="overflow-x-auto rounded-md border border-edge">
        <table className="w-full min-w-[640px]">
          <thead className="bg-ink">
            <tr>
              <th className="th">Confidence</th>
              <th className="th">VaR historical</th>
              <th className="th">VaR parametric</th>
              <th className="th">hist ÷ param</th>
              <th className="th">ES historical</th>
              <th className="th">ES parametric</th>
              <th className="th">hist ÷ param</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-edge">
            {levels.map(([level, detail]) => (
              <tr key={level}>
                <td className="td stat text-slate-100">{pct(Number(level), 1)}</td>
                <td className="td stat">{money(detail.var_historical, currency)}</td>
                <td className="td stat">{money(detail.var_parametric, currency)}</td>
                <td className="td">
                  <Chip tone={detail.tail_ratio > 1 ? "bad" : "good"}>
                    {ratio(detail.tail_ratio)}×
                  </Chip>
                </td>
                <td className="td stat">{money(detail.es_historical, currency)}</td>
                <td className="td stat">{money(detail.es_parametric, currency)}</td>
                <td className="td">
                  <Chip tone={detail.es_ratio > 1 ? "bad" : "good"}>
                    {ratio(detail.es_ratio)}×
                  </Chip>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4 space-y-3">
        {levels.map(([level, detail]) =>
          detail.notes.map((note, index) => (
            <p
              key={`${level}-${index}`}
              className="border-l-2 border-edge pl-3 text-xs leading-relaxed text-muted"
            >
              <span className="font-mono text-accent">{pct(Number(level), 1)}</span> {note}
            </p>
          )),
        )}
      </div>

      <Note>
        The parametric method fits a normal distribution, which has a thinner extreme tail
        than real returns — but also a flatter body. A leptokurtic distribution&rsquo;s
        quantile only overtakes the normal&rsquo;s somewhere between 95% and 99%
        confidence, so &ldquo;fat tails, therefore historical VaR is bigger&rdquo; is only
        true at the top of that range. Expected shortfall has no such crossover: it
        averages the whole tail rather than reading one point off it, so it registers fat
        tails at every confidence level.
      </Note>
    </Panel>
  );
}
