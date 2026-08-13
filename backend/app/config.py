"""Application configuration.

Every constant that can move a reported number lives here and is echoed by
``GET /methodology``. Nothing in the risk calculator, the VaR engine, the
backtester or the stress engine reads a magic number that is not declared in
this file, and the resolved parameter set is written into the
``calculation_basis`` of every stored result.

That discipline matters more in this project than in most. A Sharpe ratio is a
single float, and two people computing "the Sharpe ratio" of the same portfolio
routinely disagree - because one annualised with 252 and the other with 250, one
de-annualised the risk-free rate geometrically and the other divided by 252, one
used a sample standard deviation and the other a population one. None of those
are errors; they are conventions. Publishing the convention is what makes the
number checkable.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Infrastructure -----------------------------------------------------
    database_url: str = (
        "postgresql+psycopg2://alpharisk:alpharisk@localhost:5432/alphariskiq"
    )
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Root of the data/ directory: price series, universe definitions and the
    # scenario library. Empty resolves to the repository's own data/ folder,
    # which is what a local checkout wants. The Docker image mounts the same
    # folder read-only at /data and sets this explicitly, because relying on a
    # relative path that happens to work out to the right place after the source
    # is copied into a container is the kind of thing that breaks silently the
    # first time anyone changes the WORKDIR.
    data_root: str = ""

    # --- LLM ----------------------------------------------------------------
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    llm_timeout_seconds: float = 30.0
    llm_max_tokens: int = 1800

    # --- Annualisation ------------------------------------------------------
    # Daily figures are scaled to annual by sqrt(T) for volatility and by T for
    # mean return. 252 is the conventional US count; NSE settles ~246-250 trading
    # days a year. The difference moves an annualised Sharpe by well under 2%,
    # which is far smaller than the estimation error on the mean itself - but it
    # is declared per universe rather than assumed, and recorded in every result.
    trading_days_per_year: int = 252

    # Sample (ddof=1) rather than population standard deviation. With a
    # two-year daily window (~500 points) the two differ by ~0.1%; the sample
    # form is the unbiased estimator of the variance of the return-generating
    # process, which is the quantity a forward-looking risk number is about.
    std_ddof: int = 1

    # --- Sharpe / Sortino ---------------------------------------------------
    # The risk-free rate is quoted annually and must be converted to the return
    # interval before subtracting. Geometric de-annualisation,
    # (1+rf)^(1/T) - 1, is used rather than rf/T. For rf=6.5% and T=252 the two
    # differ by ~1e-6/day - immaterial - but the geometric form is the one that
    # compounds back to the quoted annual rate, and being asked "why did you
    # divide?" is a question with no good answer.
    risk_free_geometric_deannualisation: bool = True

    # Minimum Acceptable Return for the Sortino denominator, as an ANNUAL rate.
    # 0.0 means "any loss is downside", which is the most common convention and
    # makes Sortino comparable across portfolios. Setting it to the risk-free
    # rate instead answers a different question ("volatility of underperforming
    # cash"), so it is explicit rather than inherited from the Sharpe input.
    sortino_mar_annual: float = 0.0

    # A Sortino ratio computed off a handful of losing days is noise. Below this
    # many observations strictly below the MAR the ratio is returned as null with
    # a stated reason rather than as a large and meaningless number.
    sortino_min_downside_observations: int = 5

    # A standard deviation below this is treated as exactly zero. np.std of a
    # constant array is not 0.0 but around 1e-19 - the accumulated floating-point
    # residue of summing squared differences - so a naive `if sigma > 0` guard
    # never fires and the ratio comes back as 7e16 instead of as "undefined".
    # A number that large is obviously wrong to a human and completely invisible
    # to a chart axis. Daily returns are O(1e-2), so 1e-12 is nine orders of
    # magnitude below anything real.
    degenerate_std_threshold: float = 1e-12

    # --- Sample window ------------------------------------------------------
    # Every risk figure here is an estimate from a finite sample. Below this many
    # observations the estimates are too noisy to report at all: at n=30 the 95%
    # confidence interval on an annualised volatility estimate is roughly
    # +/-25% of the estimate.
    min_observations: int = 60
    # Historical VaR at 99% needs enough points that the quantile is not
    # interpolated between two extreme observations. 1/(1-0.99) = 100 is the bare
    # floor for a single tail observation; this requires several.
    min_observations_per_tail_point: int = 3

    # --- Value at Risk ------------------------------------------------------
    default_confidence_level: float = 0.95
    # Parametric VaR subtracts the sample mean: VaR = V * (z*sigma - mu). Setting
    # this False gives the zero-drift form V * z * sigma that most textbooks
    # quote. Over a one-day horizon mu is ~1e-4 against z*sigma ~2e-2, so it
    # moves the number by well under a percent; over longer horizons it does not.
    parametric_var_includes_drift: bool = True
    # numpy's default linear interpolation between order statistics. The
    # alternative ("lower") always returns an actually-observed return, which is
    # more conservative and more defensible at high confidence on short samples.
    # Declared because two implementations differing only here will disagree.
    historical_var_quantile_method: str = "linear"

    # --- VaR backtesting (Kupiec) -------------------------------------------
    # Rolling-window VaR is re-estimated every day on the trailing window, then
    # compared against the next day's realised return. This is the out-of-sample
    # test; using the full sample to set the threshold and then counting breaches
    # in that same sample is circular and always passes.
    backtest_window: int = 250
    # Chi-square(1) critical value at 95%. Kupiec's proportion-of-failures test
    # statistic is asymptotically chi-square with one degree of freedom.
    kupiec_critical_value_95: float = 3.841

    # --- Stress testing -----------------------------------------------------
    # Beta is estimated by OLS of asset excess-free returns on the benchmark's
    # over the sample window. Below this many overlapping observations the
    # estimate is not reported and the holding falls back to beta=1.
    beta_min_observations: int = 60
    # A shock of this magnitude or larger is refused as a data-entry error rather
    # than silently producing a negative portfolio value.
    max_shock_pct: float = 99.0

    # --- Report generation --------------------------------------------------
    # The LLM is allowed to cite metric keys; any key it cites that is not
    # present in the structured context it was given is dropped from the stored
    # report. Set False only to debug what the model tried to say.
    drop_uncited_metrics: bool = True

    @property
    def data_path(self) -> Path:
        if self.data_root:
            return Path(self.data_root)
        # backend/app/config.py -> backend/app -> backend -> repo root
        return Path(__file__).resolve().parents[2] / "data"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def _check_invariants(self) -> "Settings":
        if self.trading_days_per_year <= 0:
            raise ValueError("trading_days_per_year must be positive")
        if self.std_ddof not in (0, 1):
            raise ValueError("std_ddof must be 0 (population) or 1 (sample)")
        if not 0.5 < self.default_confidence_level < 1.0:
            raise ValueError(
                "default_confidence_level must be a probability strictly between "
                "0.5 and 1.0, e.g. 0.95. A confidence level below 0.5 would put "
                "'VaR' on the profitable side of the distribution."
            )
        if self.historical_var_quantile_method not in ("linear", "lower", "higher"):
            raise ValueError(
                "historical_var_quantile_method must be one of linear/lower/higher"
            )
        if self.min_observations < 2:
            raise ValueError("min_observations must be at least 2")
        if self.backtest_window < self.min_observations:
            raise ValueError(
                "backtest_window must be at least min_observations, otherwise each "
                "rolling re-estimate would be computed on a sample the engine "
                "elsewhere refuses to report on"
            )
        if not 0 < self.max_shock_pct < 100:
            raise ValueError("max_shock_pct must be between 0 and 100 exclusive")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
