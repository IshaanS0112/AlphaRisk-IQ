"""Closed vocabularies.

Every one of these ends up serialised into a stored ``calculation_basis`` or a
provenance field, so they are enums rather than free strings: a typo in a basis
record is worse than useless, because the record exists precisely so a reader can
check what was done.
"""

from __future__ import annotations

from enum import Enum


class Provenance(str, Enum):
    """Where a price series came from.

    This is the most important enum in the project. A risk number computed on
    synthetic data is not a risk number, it is a demonstration - and the
    difference has to survive all the way from the CSV loader to the sentence the
    LLM writes. Every return row carries one of these, every metrics response
    reports the aggregate, and the report generator refuses to describe a
    ``SYNTHETIC`` portfolio without saying so.
    """

    REAL_MARKET_DATA = "REAL_MARKET_DATA"
    SYNTHETIC = "SYNTHETIC"


class ReturnMethod(str, Enum):
    """Simple (arithmetic) or log returns.

    V1 computes on SIMPLE returns and the choice is not cosmetic: a portfolio's
    simple return is the weighted sum of its holdings' simple returns, whereas
    log returns are *not* additive across assets. Aggregating log returns with
    portfolio weights is a common and silently wrong shortcut. LOG is exposed for
    single-asset diagnostics only.
    """

    SIMPLE = "SIMPLE"
    LOG = "LOG"


class Rebalancing(str, Enum):
    """How the stated weights are maintained over the sample window.

    ``DAILY_CONSTANT_WEIGHT`` means the portfolio is assumed rebalanced back to
    the stated weights every day, so the portfolio return on day t is exactly
    ``sum(w_i * r_it)``. That is the standard convention for risk reporting on a
    *stated* weight vector, and it is what every formula in this project assumes.

    ``BUY_AND_HOLD`` would let weights drift with performance, which measures a
    different portfolio by the end of the window. Documented as V2 rather than
    silently approximated.
    """

    DAILY_CONSTANT_WEIGHT = "DAILY_CONSTANT_WEIGHT"


class VarMethod(str, Enum):
    HISTORICAL = "HISTORICAL"
    PARAMETRIC = "PARAMETRIC"


class SortinoConvention(str, Enum):
    """Which downside deviation definition a Sortino figure was built on.

    ``STANDARD`` is Sortino's own: root-mean-square of ``min(r - MAR, 0)`` over
    **all** observations. ``NEGATIVE_ONLY_STDDEV`` is the widely circulated
    shortcut - the sample standard deviation of only the negative returns. They
    are different numbers and this project reports both; see
    ``services/risk_calculator.py``.
    """

    STANDARD = "STANDARD"
    NEGATIVE_ONLY_STDDEV = "NEGATIVE_ONLY_STDDEV"


class ShockMode(str, Enum):
    """How a scenario's index-level shock reaches the individual holdings.

    ``UNIFORM``: every holding moves by the full index shock (implicitly beta=1).
    ``BETA_ADJUSTED``: each holding moves by ``beta_i * index_shock``, where beta
    is estimated by OLS of the asset's returns on the benchmark's over the sample
    window.
    """

    UNIFORM = "UNIFORM"
    BETA_ADJUSTED = "BETA_ADJUSTED"


class ReportStatus(str, Enum):
    LLM = "LLM"
    TEMPLATE_FALLBACK = "TEMPLATE_FALLBACK"
