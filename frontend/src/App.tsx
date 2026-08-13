import { Link, Route, Routes } from "react-router-dom";

import Dashboard from "./pages/Dashboard";
import Methodology from "./pages/Methodology";
import PortfolioBuilder from "./pages/PortfolioBuilder";
import PortfolioDetail from "./pages/PortfolioDetail";

export default function App() {
  return (
    <div className="mx-auto min-h-screen max-w-6xl px-5 py-8">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-3 border-b border-edge pb-5">
        <div>
          <Link to="/" className="text-xl font-semibold tracking-tight text-slate-100">
            AlphaRisk<span className="text-accent"> IQ</span>
          </Link>
          <p className="mt-1 text-xs text-muted">
            Sharpe &amp; Sortino · historical and parametric VaR with expected shortfall ·
            Kupiec-tested backtesting · beta-adjusted stress scenarios · narrated, not
            decided, by an LLM
          </p>
        </div>
        <nav className="flex gap-2 text-sm">
          <Link to="/" className="text-muted hover:text-accent">
            Portfolios
          </Link>
          <span className="text-edge">/</span>
          <Link to="/new" className="text-muted hover:text-accent">
            Build
          </Link>
          <span className="text-edge">/</span>
          <Link to="/methodology" className="text-muted hover:text-accent">
            Methodology
          </Link>
        </nav>
      </header>

      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/new" element={<PortfolioBuilder />} />
        <Route path="/methodology" element={<Methodology />} />
        <Route path="/portfolios/:portfolioId" element={<PortfolioDetail />} />
        <Route
          path="*"
          element={
            <p className="panel p-6 text-sm text-muted">
              Nothing here.{" "}
              <Link to="/" className="text-accent">
                Back to portfolios
              </Link>
            </p>
          }
        />
      </Routes>
    </div>
  );
}
