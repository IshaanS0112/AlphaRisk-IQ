import type {
  InvestmentReport,
  MarketDataLoad,
  Portfolio,
  RiskMetrics,
  Scenario,
  ShockMode,
  StressTest,
  Universe,
  UniverseName,
} from "./types";

// In dev, Vite proxies /api -> :8000. In the Docker image, nginx does the same.
// Either way the browser only ever talks to its own origin.
const BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const BACKEND_DOWN =
  "Cannot reach the API. Start the backend in a second terminal — `./dev.sh` from " +
  "the project root, or `uvicorn app.main:app --reload` from backend/ with the " +
  "virtualenv active — then check http://localhost:8000/health responds.";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch (cause) {
    // fetch only rejects on a transport failure - DNS, connection refused,
    // CORS. By far the most common cause here is that the backend simply is not
    // running, so say that instead of surfacing "Failed to fetch".
    throw new ApiError(BACKEND_DOWN, 0, cause);
  }

  // A response body is a single-use stream. Reading it twice - json() in a try
  // and text() in the catch - throws "Body is disturbed or locked" and buries
  // the real failure under a message about stream state. Read it ONCE as text,
  // then parse. This matters most in exactly the situation where you least want
  // a confusing error: the dev proxy returns an empty body when the backend is
  // down, json() throws on the empty string, and the fallback used to throw
  // over the top of it.
  const raw = await response.text().catch(() => "");

  const parsed = (() => {
    if (!raw) return undefined;
    try {
      return JSON.parse(raw);
    } catch {
      return undefined;
    }
  })();

  if (!response.ok) {
    // An empty body on a 5xx from the dev proxy means the upstream never
    // answered - same situation as a rejected fetch, so give the same advice.
    if (!raw && response.status >= 500) {
      throw new ApiError(BACKEND_DOWN, response.status);
    }

    const detail = parsed?.detail ?? (raw || undefined);
    // FastAPI's detail is a string for our explicit HTTPExceptions and an array
    // of error objects for request-validation failures.
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .map((d: any) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`)
              .join("; ")
          : `Request failed (${response.status} ${response.statusText})`;
    throw new ApiError(message, response.status, detail);
  }

  if (response.status === 204 || !raw) return undefined as T;
  if (parsed === undefined) {
    throw new ApiError(
      `Expected JSON from ${path} but got ${raw.slice(0, 80)}`,
      response.status,
    );
  }
  return parsed as T;
}

/** A 404 from a stage that has not been run yet is expected, not an error. */
export async function optional<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export const getUniverses = () =>
  request<Record<UniverseName, Universe>>("/universes");

export const getScenarios = (universe?: UniverseName) =>
  request<{ scenarios: Scenario[]; note: string }>(
    universe ? `/scenarios?universe=${universe}` : "/scenarios",
  );

export const getMethodology = () => request<Record<string, any>>("/methodology");

export const loadMarketData = (universe: UniverseName) =>
  request<MarketDataLoad>("/market-data/load", {
    method: "POST",
    body: JSON.stringify({ universe }),
  });

export const listPortfolios = () => request<Portfolio[]>("/portfolios");

export const getPortfolio = (id: string) => request<Portfolio>(`/portfolios/${id}`);

export const createPortfolio = (payload: {
  name: string;
  universe: UniverseName;
  base_value: number;
  holdings: { ticker: string; weight: number }[];
}) =>
  request<Portfolio>("/portfolios", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const deletePortfolio = (id: string) =>
  request<void>(`/portfolios/${id}`, { method: "DELETE" });

export const computeRiskMetrics = (id: string, riskFree?: number) =>
  request<RiskMetrics>(`/portfolios/${id}/compute-risk-metrics`, {
    method: "POST",
    body: JSON.stringify(
      riskFree === undefined ? {} : { risk_free_annual: riskFree },
    ),
  });

export const getRiskMetrics = (id: string) =>
  request<RiskMetrics>(`/portfolios/${id}/risk-metrics`);

export const runStressTest = (
  id: string,
  payload:
    | { scenario_name: string; mode: ShockMode }
    | { custom_shock_pct: number; custom_label?: string; mode: ShockMode },
) =>
  request<StressTest>(`/portfolios/${id}/stress-test`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const listStressTests = (id: string) =>
  request<StressTest[]>(`/portfolios/${id}/stress-tests`);

export const generateReport = (id: string) =>
  request<InvestmentReport>(`/portfolios/${id}/generate-report`, { method: "POST" });

export const getReport = (id: string) =>
  request<InvestmentReport>(`/portfolios/${id}/investment-report`);
