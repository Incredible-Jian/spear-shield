from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import pytest
from spear_shield.services.market_view import quote_view, chart_period_note
from spear_shield.config.symbols import get_symbol

SH = ZoneInfo("Asia/Shanghai")


def frame(updated="2026-11-09T06:30:00Z"):
    return pd.DataFrame(
        dict(
            date=pd.to_datetime(["2026-11-06", "2026-11-09"]),
            open=[10.0, 10.0],
            high=[11.0, 12.0],
            low=[9.0, 9.0],
            close=[10.0, 11.0],
            volume=[100.0, 200.0],
            source="synthetic-test-only",
            updated_at=pd.to_datetime([updated, updated], utc=True),
        )
    )


def test_intraday_cache_does_not_turn_final_when_clock_moves_past_close():
    row = quote_view(
        get_symbol("159915"),
        pd.DataFrame(),
        frame(),
        now=datetime(2026, 11, 9, 18, tzinfo=SH),
    )
    assert not row["complete"] and "未完成" in row["completion"]
    assert row["change_pct"] == pytest.approx(10.0)
    assert row["basis"] == "前复权研究价"


def test_raw_same_date_is_preferred_and_postclose_write_is_explicit():
    row = quote_view(
        get_symbol("159915"),
        frame("2026-11-09T08:00:00Z"),
        frame(),
        now=datetime(2026, 11, 9, 18, tzinfo=SH),
    )
    assert row["basis"] == "原始行情" and row["complete"]


def test_future_bad_or_missing_quotes_do_not_become_zero_or_valid():
    symbol = get_symbol("159915")
    assert quote_view(symbol, pd.DataFrame(), pd.DataFrame())["price"] is None
    df = frame()
    df.loc[1, "close"] = float("nan")
    row = quote_view(
        symbol, pd.DataFrame(), df, now=datetime(2026, 11, 8, 18, tzinfo=SH)
    )
    assert row["price"] is None and row["quality"].startswith("FALSE")


def test_week_month_current_bar_is_observation_unknown():
    for period in ("week", "month"):
        assert "UNKNOWN" in chart_period_note(
            frame(), period, now=datetime(2026, 11, 9, 18, tzinfo=SH)
        )


def test_h30269_provider_reuses_existing_csi_source(monkeypatch):
    import akshare as ak
    from spear_shield.data.akshare_provider import AkShareProvider

    calls = []

    def csi(symbol):
        calls.append(symbol)
        return frame().drop(columns=["source", "updated_at"])

    monkeypatch.setattr(ak, "stock_zh_index_daily_em", csi)
    result = AkShareProvider().fetch_daily(
        get_symbol("H30269"), "2026-11-01", "2026-11-09"
    )
    assert calls == ["csiH30269"] and len(result) == 2
