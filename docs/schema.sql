-- AlphaRisk IQ - PostgreSQL schema.
--
-- This file is the reference; the SQLAlchemy models in backend/app/models are
-- what actually run, and they declare JSONB and UUID as dialect *variants* so
-- the same schema loads under SQLite. That is what lets the API integration
-- tests run on a fresh clone with no database container up.

CREATE TABLE portfolios (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(200) NOT NULL,
    -- Selects the benchmark for beta estimation, the risk-free rate, the
    -- trading-day count, and which crisis magnitudes are meaningful. Applying an
    -- S&P 500 drawdown to an NSE portfolio is a category error and this column
    -- is what prevents it.
    universe    VARCHAR(20)  NOT NULL,
    -- [{ticker, weight, submitted_weight}] - weights normalised to sum to 1 at
    -- write time, with the pre-normalisation figure kept so a portfolio entered
    -- as percentages is not silently reinterpreted.
    holdings    JSONB        NOT NULL DEFAULT '[]'::jsonb,
    -- VaR is a currency amount, so it is meaningless without a notional.
    base_value  DOUBLE PRECISION NOT NULL DEFAULT 1000000,
    currency    VARCHAR(3)   NOT NULL DEFAULT 'INR',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Daily closes and the returns derived from them. return_pct is a DECIMAL
-- FRACTION (0.0123 = +1.23%), never a percentage number: mixing the two is the
-- most common unit bug in risk code and it is wrong by 10,000x in variance terms
-- while still looking like a plausible float.
CREATE TABLE asset_returns (
    id          BIGSERIAL PRIMARY KEY,
    ticker      VARCHAR(30) NOT NULL,
    date        DATE        NOT NULL,
    price       DOUBLE PRECISION NOT NULL,
    -- NULL on the first observation of a series: there is no prior close to
    -- difference against. Stored rather than dropped so the price series stays
    -- complete.
    return_pct  DOUBLE PRECISION,
    source      VARCHAR(300) NOT NULL,
    -- REAL_MARKET_DATA | SYNTHETIC. Carried per row, not per ticker, because a
    -- universe can be half loaded. This column is the reason the provenance
    -- guarantee holds all the way to the sentence the LLM writes.
    provenance  VARCHAR(30)  NOT NULL,
    loaded_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ix_asset_returns_ticker_date ON asset_returns (ticker, date);

-- Structurally identical to asset_returns and deliberately separate: the
-- benchmark is not a holding, and letting it into asset_returns invites a
-- portfolio that accidentally contains its own index.
CREATE TABLE benchmark_returns (
    id          BIGSERIAL PRIMARY KEY,
    symbol      VARCHAR(30) NOT NULL,
    date        DATE        NOT NULL,
    price       DOUBLE PRECISION NOT NULL,
    return_pct  DOUBLE PRECISION,
    source      VARCHAR(300) NOT NULL,
    provenance  VARCHAR(30)  NOT NULL,
    loaded_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ix_benchmark_returns_symbol_date ON benchmark_returns (symbol, date);

-- One row per load operation, so "where did the RELIANCE series come from" is
-- answerable without reading a source string on 1,300 rows and hoping they agree.
CREATE TABLE data_loads (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    universe       VARCHAR(20)  NOT NULL,
    provenance     VARCHAR(30)  NOT NULL,
    source         VARCHAR(300) NOT NULL,
    tickers_loaded INTEGER      NOT NULL DEFAULT 0,
    rows_loaded    INTEGER      NOT NULL DEFAULT 0,
    loaded_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Appended, never updated. "The VaR moved when we extended the window from one
-- year to three" is the finding, not a detail to overwrite.
CREATE TABLE risk_metrics (
    id                            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id                  UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,

    mean_return_daily             DOUBLE PRECISION NOT NULL,
    mean_return_annualised        DOUBLE PRECISION NOT NULL,
    portfolio_std_dev_daily       DOUBLE PRECISION NOT NULL,
    portfolio_std_dev_annualised  DOUBLE PRECISION NOT NULL,

    sharpe_ratio                  DOUBLE PRECISION,
    -- Sortino's own definition: RMS shortfall below the MAR over ALL observations.
    sortino_ratio                 DOUBLE PRECISION,
    -- The widely circulated shortcut: stdev of the negative returns only. Stored
    -- so the gap between the two is a number this system reports rather than a
    -- claim it makes.
    sortino_ratio_negative_only   DOUBLE PRECISION,
    downside_deviation            DOUBLE PRECISION,
    downside_deviation_negative_only DOUBLE PRECISION,
    max_drawdown                  DOUBLE PRECISION,

    -- All POSITIVE loss magnitudes, in the portfolio's currency.
    var_historical_95             DOUBLE PRECISION,
    var_parametric_95             DOUBLE PRECISION,
    var_historical_99             DOUBLE PRECISION,
    var_parametric_99             DOUBLE PRECISION,
    es_historical_95              DOUBLE PRECISION,
    es_parametric_95              DOUBLE PRECISION,

    -- Window bounds, risk-free rate and MAR used, confidence levels, trading-day
    -- count, ddof, quantile method, per-ticker weights, aggregate provenance.
    -- A Sharpe ratio without these is not a reproducible number.
    calculation_basis             JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Per-confidence-level VaR/ES detail, both Kupiec backtests, per-holding
    -- volatilities, diversification statistics.
    detail                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- What could not be computed and precisely why. "Sortino is undefined because
    -- only 3 days fell below the MAR" is an analytical finding about the sample,
    -- not a debug message.
    omitted_metrics               JSONB NOT NULL DEFAULT '[]'::jsonb,

    calculated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_risk_metrics_portfolio ON risk_metrics (portfolio_id);

CREATE TABLE stress_tests (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id           UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    scenario_name          VARCHAR(100) NOT NULL,
    scenario_label         VARCHAR(200) NOT NULL,
    shock_mode             VARCHAR(30)  NOT NULL,   -- UNIFORM | BETA_ADJUSTED
    -- The scenario as applied: index shock, the peak/trough levels it was derived
    -- from, per-holding betas, and the citation.
    shock_config           JSONB NOT NULL DEFAULT '{}'::jsonb,
    portfolio_value_before DOUBLE PRECISION NOT NULL,
    portfolio_value_after  DOUBLE PRECISION NOT NULL,
    pct_loss               DOUBLE PRECISION NOT NULL,
    -- Per-holding contribution, so the answer is decomposable rather than one number.
    holding_impacts        JSONB NOT NULL DEFAULT '[]'::jsonb,
    calculation_basis      JSONB NOT NULL DEFAULT '{}'::jsonb,
    tested_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_stress_tests_portfolio ON stress_tests (portfolio_id);

CREATE TABLE investment_reports (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id       UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    -- The exact payload handed to the model, stored BEFORE the call is made. This
    -- is the artefact that makes the central claim checkable: every figure in the
    -- narrative exists here first, and a reader can diff the two.
    structured_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    ai_narrative       JSONB NOT NULL DEFAULT '{}'::jsonb,
    status             VARCHAR(30) NOT NULL,   -- LLM | TEMPLATE_FALLBACK
    fallback_reason    VARCHAR(400),
    model_used         VARCHAR(80),
    -- Metric keys the model cited that were not in the context it was given.
    -- Dropped from the narrative and recorded here: a model inventing a metric key
    -- is the exact failure this architecture exists to catch.
    dropped_citations  JSONB NOT NULL DEFAULT '[]'::jsonb,
    generated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_investment_reports_portfolio ON investment_reports (portfolio_id);
