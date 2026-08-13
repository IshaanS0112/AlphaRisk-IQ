import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import * as api from "../api/client";
import type { Portfolio } from "../api/types";
import { date, money, pct } from "../api/format";
import { Empty, ErrorBox, Panel } from "../components/Bits";

export default function Dashboard() {
  const [portfolios, setPortfolios] = useState<Portfolio[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listPortfolios()
      .then(setPortfolios)
      .catch((e) => {
        setError(e.message);
        // Clear the loading state too. Leaving portfolios as null showed the
        // error banner AND a permanent "Loading..." underneath it, which reads
        // like the page is still trying.
        setPortfolios([]);
      });
  }, []);

  return (
    <div className="space-y-6">
      {error && <ErrorBox message={error} />}
      <Panel
        title="Portfolios"
        right={
          <Link to="/new" className="btn-primary">
            New portfolio
          </Link>
        }
      >
        {portfolios === null && <Empty>Loading…</Empty>}
        {portfolios?.length === 0 && (
          <Empty>
            No portfolios yet.{" "}
            <Link to="/new" className="text-accent">
              Build one
            </Link>
            .
          </Empty>
        )}
        {portfolios && portfolios.length > 0 && (
          <div className="overflow-hidden rounded-md border border-edge">
            <table className="w-full">
              <thead className="bg-ink">
                <tr>
                  <th className="th">Name</th>
                  <th className="th">Universe</th>
                  <th className="th">Notional</th>
                  <th className="th">Holdings</th>
                  <th className="th">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-edge">
                {portfolios.map((portfolio) => (
                  <tr key={portfolio.id} className="hover:bg-ink/60">
                    <td className="td">
                      <Link
                        to={`/portfolios/${portfolio.id}`}
                        className="text-accent hover:underline"
                      >
                        {portfolio.name}
                      </Link>
                    </td>
                    <td className="td text-muted">{portfolio.universe}</td>
                    <td className="td stat">
                      {money(portfolio.base_value, portfolio.currency)}
                    </td>
                    <td className="td text-muted">
                      {portfolio.holdings
                        .map((h) => `${h.ticker} ${pct(h.weight, 0)}`)
                        .join(" · ")}
                    </td>
                    <td className="td text-muted">{date(portfolio.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
