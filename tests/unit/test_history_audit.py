from datetime import date
import pandas as pd
import pytest
from spear_shield.data.history_audit import cash_dividends, qfq_asof, compare_prices
from spear_shield.backtest.models import CorporateAction


def test_dividend_per_ten_is_not_per_one_and_pay_date_is_real():
    frame = pd.DataFrame(
        {
            "除息日": ["2024-01-08"],
            "分红发放日": ["2024-01-11"],
            "每10份分红": ["每10份派现金0.1200元"],
        }
    )
    events = cash_dividends("563020", frame, source="test-only")
    assert events[0].cash_per_unit == 0.012 and events[0].pay_date == date(2024, 1, 11)
    with pytest.raises(ValueError):
        cash_dividends(
            "563020", frame.assign(每10份分红="每份0.1200"), source="test-only"
        )


def test_qfq_reconstruction_cannot_see_future_dividend():
    raw = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-05", "2024-01-08", "2024-01-09"]),
            "open": [10.0, 9.0, 9.0],
            "high": [10.0, 9.0, 9.0],
            "low": [10.0, 9.0, 9.0],
            "close": [10.0, 9.0, 9.0],
            "adjust": "none",
        }
    )
    event = CorporateAction(
        "563020", date(2024, 1, 8), date(2024, 1, 11), 1.0, source="test-only"
    )
    before = qfq_asof(raw, [event], as_of=date(2024, 1, 5))
    assert before.close.tolist() == [10.0]
    after = qfq_asof(raw, [event], as_of=date(2024, 1, 9))
    assert after.close.tolist() == [9.0, 9.0, 9.0]
    other_future = CorporateAction(
        "563020", date(2025, 1, 8), date(2025, 1, 11), 7.0, source="test-only"
    )
    pd.testing.assert_frame_equal(
        after, qfq_asof(raw, [event, other_future], as_of=date(2024, 1, 9))
    )


def test_compare_never_fills_or_hides_missing_dates():
    a = pd.DataFrame({"date": ["2024-01-05", "2024-01-08"], "close": [10.0, 11.0]})
    b = pd.DataFrame({"date": ["2024-01-08", "2024-01-09"], "close": [12.0, 13.0]})
    result = compare_prices(a, b)
    assert (
        result["common_dates"] == 1
        and result["left_only"] == 1
        and result["right_only"] == 1
    )
    assert result["mismatch_count"] == 1
