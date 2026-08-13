import type { RiskMetrics } from "../api/types";
import { money, pct, ratio } from "../api/format";
import { Chip, Note, Panel, Stat } from "./Bits";

export default function RiskMetricsPanel({
  metrics,
  currency,
}: {
  metrics: RiskMetrics;
  currency: string;
}) {
  const basis = metrics.calculation_basis;
  const diversification = metrics.detail.diversification;
  const sharpe = metrics.sharpe_ratio;
  const sortino = metrics.sortino_ratio;
  const naive = metrics.sortino_ratio_negative_only;

  const sortinoGap =
    sortino !== null && naive !== null && naive !== 0
      ? (sortino - naive) / Math.abs(naive)
      : null;

  return (
    <Panel
      title="Risk-adjusted return"
      subtitle={
        <>
          {basis.observations} observations, {basis.window_start} to {basis.window_end}.
          Risk-free {pct(basis.risk_free_annual)} ({basis.risk_free_basis}), annualised
          on {basis.trading_days_per_year} trading days.
        </>
      }
      right={<Chip tone="accent">{basis.rebalancing}</Chip>}
    >
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Annualised return"
          value={pct(metrics.mean_return_annualised)}
          hint={`Geometric ${pct(metrics.detail.risk?.geometric_return_annualised)}`}
        />
        <Stat
          label="Annualised volatility"
          value={pct(metrics.portfolio_std_dev_annualised)}
          hint={`Daily ${pct(metrics.portfolio_std_dev_daily, 3)}`}
        />
        <Stat
          label="Sharpe"
          value={ratio(sharpe)}
          tone={sharpe === null ? "neutral" : sharpe >= 1 ? "good" : sharpe >= 0 ? "warn" : "bad"}
          hint="Penalises upside and downside volatility equally"
        />
        <Stat
          label="Max drawdown"
          value={pct(metrics.max_drawdown)}
          tone={(metrics.max_drawdown ?? 0) > 0.3 ? "bad" : "warn"}
          hint={
            metrics.detail.risk?.max_drawdown_window
              ? `${metrics.detail.risk.max_drawdown_window.peak_date} to ${metrics.detail.risk.max_drawdown_window.trough_date}`
              : undefined
          }
        />
      </div>

      <div className="mt-5">
        <h3 className="label">Sortino, under both conventions</h3>
        <div className="overflow-hidden rounded-md border border-edge">
          <table className="w-full">
            <thead className="bg-ink">
              <tr>
                <th className="th">Convention</th>
                <th className="th">Downside deviation (daily)</th>
                <th className="th">Sortino</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-edge">
              <tr>
                <td className="td">
                  <span className="text-slate-100">STANDARD</span>
                  <div className="text-[11px] text-muted">
                    RMS shortfall below the MAR over all observations — Sortino&rsquo;s own
                    definition
                  </div>
                </td>
                <td className="td stat">{ratio(metrics.downside_deviation, 5)}</td>
                <td className="td stat text-slate-100">{ratio(sortino)}</td>
              </tr>
              <tr>
                <td className="td">
                  <span className="text-slate-100">NEGATIVE_ONLY_STDDEV</span>
                  <div className="text-[11px] text-muted">
                    Standard deviation of the negative returns only — the widely
                    circulated shortcut
                  </div>
                </td>
                <td className="td stat">
                  {ratio(metrics.downside_deviation_negative_only, 5)}
                </td>
                <td className="td stat">{ratio(naive)}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <Note>
          {sortinoGap === null
            ? "Both conventions are reported so a quoted Sortino can be matched to the definition behind it."
            : `The two definitions differ by ${pct(Math.abs(sortinoGap), 1)} on this portfolio. On a symmetric sample the shortcut gives the smaller denominator and so flatters the ratio; left skew reverses that. Knowing which convention a quoted Sortino used is the difference between comparing two portfolios and comparing two spreadsheets.`}
        </Note>
      </div>

      {sharpe !== null && sortino !== null && (
        <Note>
          Sortino {sortino > sharpe ? "exceeds" : "sits below"} Sharpe, so the volatility
          Sharpe penalises is{" "}
          {sortino > sharpe
            ? "disproportionately upside volatility — which an investor is not usually trying to avoid."
            : "concentrated on the downside: the losses are not symmetric with the gains."}
        </Note>
      )}

      {diversification && (
        <div className="mt-5">
          <h3 className="label">Diversification</h3>
          <div className="grid gap-3 sm:grid-cols-3">
            <Stat
              label="Diversification ratio"
              value={ratio(diversification.diversification_ratio)}
              hint="Weighted-average holding vol ÷ realised portfolio vol; 1.00 = no benefit"
            />
            <Stat
              label="Mean pairwise correlation"
              value={ratio(diversification.mean_pairwise_correlation)}
              tone={
                (diversification.mean_pairwise_correlation ?? 0) > 0.6 ? "warn" : "neutral"
              }
            />
            <Stat
              label="Max pairwise correlation"
              value={ratio(diversification.max_pairwise_correlation)}
            />
          </div>
          <Note>{diversification.note}</Note>
        </div>
      )}

      {metrics.omitted_metrics.length > 0 && (
        <div className="mt-5">
          <h3 className="label">Not computed, and why</h3>
          <ul className="space-y-2">
            {metrics.omitted_metrics.map((omission) => (
              <li key={omission.metric} className="text-xs text-muted">
                <span className="font-mono text-warn">{omission.metric}</span> —{" "}
                {omission.reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      <Note>
        Portfolio notional {money(basis.base_value, currency)}. Every parameter above is
        stored with the result and republished at <code>GET /methodology</code>.
      </Note>
    </Panel>
  );
}
