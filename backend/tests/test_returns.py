"""Return construction: the layer where unit and alignment bugs live."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pytest

from app.enums import ReturnMethod
from app.services import returns as returns_service


def test_first_return_is_none_so_dates_stay_aligned():
    out = returns_service.prices_to_returns([100.0, 110.0, 99.0])
    assert out[0] is None
    assert len(out) == 3


def test_simple_returns_are_exact():
    out = returns_service.prices_to_returns([100.0, 110.0, 99.0])
    assert out[1] == pytest.approx(0.10)
    assert out[2] == pytest.approx(-0.10)


def test_log_returns_are_additive_across_time_but_simple_ones_are_not():
    prices = [100.0, 110.0, 99.0]
    log_returns = returns_service.prices_to_returns(prices, ReturnMethod.LOG)
    assert sum(log_returns[1:]) == pytest.approx(math.log(99.0 / 100.0))

    simple = returns_service.prices_to_returns(prices)
    assert sum(simple[1:]) != pytest.approx(99.0 / 100.0 - 1.0)


def test_portfolio_return_is_the_weighted_sum_of_simple_returns():
    """The reason the engine uses simple returns at all.

    Weighting log returns would not reproduce the portfolio's actual return, and
    the error is small enough to look like rounding while being systematic.
    """
    aligned = returns_service.AlignedReturns(
        dates=[date(2026, 1, 5), date(2026, 1, 6)],
        tickers=["A", "B"],
        matrix=np.array([[0.02, -0.01], [0.00, 0.03]]),
    )
    series = returns_service.portfolio_series(aligned, {"A": 0.6, "B": 0.4})
    assert series[0] == pytest.approx(0.6 * 0.02 + 0.4 * -0.01)
    assert series[1] == pytest.approx(0.4 * 0.03)


def test_alignment_intersects_dates_and_reports_what_it_dropped():
    series = {
        "A": {date(2026, 1, 5): 0.01, date(2026, 1, 6): 0.02, date(2026, 1, 7): 0.03},
        "B": {date(2026, 1, 5): -0.01, date(2026, 1, 7): 0.00},
    }
    aligned = returns_service.align(series)
    assert aligned.dates == [date(2026, 1, 5), date(2026, 1, 7)]
    assert aligned.dropped_dates == [date(2026, 1, 6)]
    assert aligned.raw_counts == {"A": 3, "B": 2}


def test_alignment_never_forward_fills():
    """A filled day would enter as a 0% return and deflate measured volatility."""
    series = {
        "A": {date(2026, 1, 5): 0.05, date(2026, 1, 6): -0.05},
        "B": {date(2026, 1, 5): 0.05},
    }
    aligned = returns_service.align(series)
    assert aligned.n == 1
    assert 0.0 not in aligned.matrix.flatten()


def test_disjoint_series_are_an_error_not_an_empty_result():
    with pytest.raises(ValueError, match="share no common trading dates"):
        returns_service.align(
            {"A": {date(2026, 1, 5): 0.01}, "B": {date(2026, 2, 5): 0.01}}
        )


def test_non_positive_price_is_rejected():
    with pytest.raises(ValueError, match="Non-positive price"):
        returns_service.prices_to_returns([100.0, 0.0, 50.0])


def test_weights_normalise_and_report_the_submitted_sum():
    holdings, raw = returns_service.normalise_weights(
        [{"ticker": "A", "weight": 40}, {"ticker": "B", "weight": 60}]
    )
    assert raw == 100
    assert [h["weight"] for h in holdings] == [0.4, 0.6]


def test_weights_that_do_not_cover_the_aligned_tickers_are_an_error():
    aligned = returns_service.AlignedReturns(
        dates=[date(2026, 1, 5)], tickers=["A", "B"], matrix=np.array([[0.01, 0.02]])
    )
    with pytest.raises(ValueError, match="No weight supplied"):
        returns_service.portfolio_series(aligned, {"A": 1.0})
