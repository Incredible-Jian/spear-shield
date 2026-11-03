import hashlib
import json
import pandas as pd
import pytest

from spear_shield.backtest.models import TradingCalendar
from spear_shield.services.research_dataset import (
    ResearchSnapshots,
    inferred_release_series,
)


def test_snapshot_hash_rejects_changed_history_and_finds_named_artifact(tmp_path):
    file = tmp_path / "qvix_cyb.csv"
    raw = b"date,close\n2024-01-02,21.5\n"
    file.write_bytes(raw)
    record = {
        "key": "qvix",
        "status": "ok",
        "source_url": "https://example.invalid/test-only",
        "retrieved_at": "2026-11-03T00:00:00+00:00",
        "is_official": False,
        "notes": "test-only",
        "artifacts": [{"path": file.name, "sha256": hashlib.sha256(raw).hexdigest()}],
    }
    (tmp_path / "manifest.json").write_text(
        json.dumps({"runs": [{"tasks": [record]}]}), encoding="utf-8"
    )
    reader = ResearchSnapshots(tmp_path)
    frame, meta = reader.read("qvix", "qvix_cyb.csv")
    assert frame.close.tolist() == [21.5]
    file.write_bytes(raw + b"2024-01-03,99\n")
    with pytest.raises(ValueError, match="哈希"):
        reader.read("qvix", "qvix_cyb.csv")


def test_lag_assumption_explicit_and_missing_trading_day_stays_nan():
    from datetime import date

    cal = TradingCalendar(
        (date(2024, 1, 5), date(2024, 1, 8), date(2024, 1, 9), date(2024, 1, 10)),
        "test",
        True,
    )
    frame = pd.DataFrame({"date": ["2024-01-05", "2024-01-09"], "ratio": [2.1, 2.2]})
    result = inferred_release_series(
        frame,
        date_column="date",
        value_column="ratio",
        source="test-only",
        calendar=cal,
    )
    assert len(result) == 3 and pd.isna(result.iloc[1].value)
    assert result.iloc[0].available_at.date() == date(2024, 1, 8)
    assert "假设" in result.iloc[0].source and "不是历史实际" in result.iloc[0].source
