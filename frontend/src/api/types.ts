export type UniverseName = "NSE_INDIA" | "US";
export type ShockMode = "UNIFORM" | "BETA_ADJUSTED";
export type Provenance = "REAL_MARKET_DATA" | "SYNTHETIC" | "MIXED";

export interface UniverseTicker {
  ticker: string;
  name: string;
  sector: string;
}

export interface Universe {
  name: UniverseName;
  label: string;
  currency: string;
  benchmark_symbol: string;
  benchmark_label: string;
  trading_days_per_year: number;
  trading_days_note: string;
  risk_free_annual: number;
  risk_free_basis: string;
  risk_free_as_of: string;
  risk_free_status: string;
  tickers: UniverseTicker[];
  price_data_available: string[];
}

export interface Scenario {
  name: string;
  universe: UniverseName;
  label: string;
  index: string;
  peak_date: string;
  peak_level: number;
  trough_date: string;
  trough_level: number;
  shock_pct: number;
  basis: string;
  source: string;
  verification_status: string;
  note: string;
  derivation: string;
}

export interface Holding {
  ticker: string;
  weight: number;
  submitted_weight?: number;
}

export interface Portfolio {
  id: string;
  name: string;
  universe: UniverseName;
  holdings: Holding[];
  base_value: number;
  currency: string;
  created_at: string;
}

export interface OmittedMetric {
  metric: string;
  reason: string;
}

export interface VarDetail {
  confidence: number;
  var_historical: number;
  var_parametric: number;
  es_historical: number;
  es_parametric: number;
  historical_quantile: number;
  parametric_quantile: number;
  z_score: number;
  n_observations: number;
  n_tail_observations: number;
  tail_ratio: number;
  es_ratio: number;
  notes: string[];
}

export interface BacktestDetail {
  method: string;
  confidence: number;
  window: number;
  n_tested: number;
  n_breaches: number;
  breach_rate: number;
  expected_breach_rate: number;
  kupiec_lr: number | null;
  kupiec_p_value: number | null;
  kupiec_critical_value: number;
  passes: boolean | null;
  verdict: string;
  longest_breach_run: number;
  consecutive_breach_days: number;
  notes: string[];
}

export interface Diversification {
  weighted_average_holding_vol_annualised: number;
  portfolio_vol_annualised: number;
  diversification_ratio: number | null;
  mean_pairwise_correlation: number | null;
  max_pairwise_correlation: number | null;
  note: string;
}

export interface RiskMetrics {
  id: string;
  portfolio_id: string;
  mean_return_daily: number;
  mean_return_annualised: number;
  portfolio_std_dev_daily: number;
  portfolio_std_dev_annualised: number;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  sortino_ratio_negative_only: number | null;
  downside_deviation: number | null;
  downside_deviation_negative_only: number | null;
  max_drawdown: number | null;
  var_historical_95: number | null;
  var_parametric_95: number | null;
  var_historical_99: number | null;
  var_parametric_99: number | null;
  es_historical_95: number | null;
  es_parametric_95: number | null;
  calculation_basis: Record<string, any>;
  detail: {
    risk?: Record<string, any>;
    var?: Record<string, VarDetail>;
    backtests?: Record<string, BacktestDetail>;
    per_holding?: Record<string, { weight: number; std_annualised: number }>;
    diversification?: Diversification;
  };
  omitted_metrics: OmittedMetric[];
  calculated_at: string;
}

export interface HoldingImpact {
  ticker: string;
  weight: number;
  beta: number;
  effective_shock: number;
  value_before: number;
  value_after: number;
  loss: number;
  contribution_to_portfolio_loss_pct: number;
}

export interface StressTest {
  id: string;
  portfolio_id: string;
  scenario_name: string;
  scenario_label: string;
  shock_mode: ShockMode;
  shock_config: {
    index_shock_pct: number;
    portfolio_beta: number;
    notes: string[];
    scenario: Partial<Scenario> & { source?: string; verification_status?: string };
  };
  portfolio_value_before: number;
  portfolio_value_after: number;
  pct_loss: number;
  holding_impacts: HoldingImpact[];
  calculation_basis: Record<string, any>;
  tested_at: string;
}

export interface Narrative {
  headline: string;
  risk_summary: string;
  var_interpretation: string;
  stress_interpretation?: string;
  key_risks: string[];
  cited_metrics: string[];
  caveats: string[];
}

export interface InvestmentReport {
  id: string;
  portfolio_id: string;
  structured_context: Record<string, any>;
  ai_narrative: Narrative;
  status: "LLM" | "TEMPLATE_FALLBACK";
  fallback_reason: string | null;
  model_used: string | null;
  dropped_citations: string[];
  generated_at: string;
}

export interface MarketDataLoad {
  universe: string;
  provenance: Provenance;
  source: string;
  tickers_loaded: number;
  benchmark_symbol: string | null;
  rows_loaded: number;
  first_date: string | null;
  last_date: string | null;
  warnings: string[];
}
