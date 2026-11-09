import copy
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import json
import pandas as pd
import pytest

from spear_shield.database.engine import Database
from spear_shield.services.workspace import Workspace
from spear_shield.services.weekly_workflow import (
    prepare_weekly,
    confirm_weekly,
    weekly_history,
    content_digest,
    WeeklyDecision,
)
from spear_shield.services.weekly_documents import make_weekly_document, export_document
from spear_shield.backtest.models import TradingCalendar, Target
from spear_shield.portfolio.paper_account import initialize


@pytest.fixture
def setup(tmp_path, monkeypatch):
    db = Database(f"sqlite:///{(tmp_path/'week.db').as_posix()}")
    db.init()
    w = Workspace(db)
    dates = pd.bdate_range("2020-01-01", "2026-11-06")
    df = pd.DataFrame(
        dict(date=dates, open=10.0, high=11.0, low=9.0, close=10.0, volume=100.0)
    )
    for code in ("399006", "H30269"):
        w.store(code, "qfq", df, "synthetic-test-only")
    calendar = TradingCalendar(
        tuple(pd.bdate_range("2020-01-01", "2026-12-31").date),
        "synthetic-test-only",
        True,
    )
    data = SimpleNamespace(
        calendar=calendar,
        macros={},
        provenance={
            "calendar": {
                "source": "synthetic-test-only",
                "retrieved_at": "2020-01-01T00:00:00Z",
            }
        },
        limitations=["synthetic-test-only"],
    )
    monkeypatch.setattr(
        "spear_shield.services.weekly_workflow.load_operational_dataset",
        lambda *a, **k: data,
    )
    with db.new_session() as s:
        initialize(s, 100000)
        s.commit()
    yield db, w
    db.close()


def test_unfinished_week_unknown_and_user_confirmation_required(setup):
    db, w = setup
    with db.new_session() as s:
        draft = prepare_weekly(
            s, w, as_of=datetime(2026, 11, 9, 23, tzinfo=timezone.utc)
        )
        assert draft["body"]["week_complete"] is False
        assert not draft["body"]["audit"]["snapshot"]["weekly_final"]
        assert draft["body"]["unknown"]
        assert draft["body"]["audit"]["position"]["attack_weight"] is None
        no_base = [
            c
            for r in draft["body"]["audit"]["decision"]["results"]
            for c in r["conditions"]
            if c["name"] == "无底仓"
        ]
        assert no_base and all(c["value"] is None for c in no_base)
        assert s.query(WeeklyDecision).count() == 0
        assert draft["body"]["audit"]["decision"]["selected"] is None
        id = confirm_weekly(s, draft)
        s.commit()
        assert confirm_weekly(s, draft) == id
        assert len(weekly_history(s)) == 1


def test_snapshot_report_immutable_after_market_updates_and_restart(setup, tmp_path):
    db, w = setup
    with db.new_session() as s:
        draft = prepare_weekly(s, w)
        id = confirm_weekly(s, draft)
        s.commit()
        document = make_weekly_document(s, id)
        s.commit()
        assert document["snapshot_digest"] == draft["digest"]
    # New market price is intentionally synthetic, not mixed into any real run.
    df = w.history("399006")
    df.loc[df.index[-1], "close"] = 10.5
    w.store("399006", "qfq", df, "synthetic-test-only-revision")
    db.engine.dispose()
    with db.new_session() as s:
        assert weekly_history(s)[0] == draft["body"]
        assert make_weekly_document(s, id) == document
        changed = copy.deepcopy(draft)
        changed["body"]["market"][0]["price"] = 999
        with pytest.raises(ValueError):
            confirm_weekly(s, changed)
        changed["digest"] = content_digest(changed["body"])
        with pytest.raises(ValueError):
            confirm_weekly(s, changed)
    export_document(document, tmp_path / "report.md", "md")
    export_document(document, tmp_path / "tables", "csv")
    export_document(document, tmp_path / "report.xlsx", "xlsx")
    assert document["snapshot_id"] in (tmp_path / "report.md").read_text(
        encoding="utf8"
    )
    identity = json.loads(
        (tmp_path / "tables/snapshot_identity.json").read_text(encoding="utf8")
    )
    assert identity["snapshot_digest"] == draft["digest"]
    assert (tmp_path / "report.xlsx").read_bytes()[:2] == b"PK"
    conditions = pd.read_csv(tmp_path / "tables/conditions.csv")
    assert "UNKNOWN" in set(conditions.state)
    assert len(conditions) == sum(
        len(r["conditions"]) for r in draft["body"]["audit"]["decision"]["results"]
    )
    assert "建议状态" in document["markdown"]


def test_future_data_not_used_and_new_decisions_do_not_reuse_identity(setup):
    db, w = setup
    with db.new_session() as s:
        ancient = datetime(2019, 1, 1, tzinfo=timezone.utc)
        past = prepare_weekly(s, w, as_of=ancient)
        assert all(r["price"] is None for r in past["body"]["market"])
        assert past["body"]["audit"]["decision"]["selected"] is None
        one = prepare_weekly(s, w)
        two = prepare_weekly(s, w)
        assert one["body"]["id"] != two["body"]["id"]
    now = datetime.now(timezone.utc)
    first = Target(now, {"159915": 0.5}, "new-decision-one", now)
    second = Target(
        now + timedelta(seconds=1), {"159915": 0.5}, "new-decision-two", now
    )
    assert first.target_id != second.target_id
