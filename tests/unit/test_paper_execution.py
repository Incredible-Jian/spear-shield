from datetime import datetime, timedelta, timezone
import json
import pandas as pd
import pytest
from spear_shield.database.engine import Database
from spear_shield.services.workspace import Workspace
from spear_shield.portfolio.paper_account import (
    initialize,
    PaperAccount,
    PaperHolding,
    PaperTrade,
    SCALE,
)
from spear_shield.portfolio.paper_execution import (
    execute_reference_order,
    cancel_order,
    execution_history,
    PaperReceipt,
    mark_equity,
)


@pytest.fixture
def setup(tmp_path):
    db = Database(f"sqlite:///{(tmp_path/'paper.db').as_posix()}")
    db.init()
    w = Workspace(db)
    now = datetime.now(timezone.utc)
    day = pd.Timestamp(now.date() - timedelta(days=2))
    df = pd.DataFrame(
        dict(
            date=[day],
            open=[10.0],
            high=[11.0],
            low=[9.0],
            close=[10.0],
            volume=[100.0],
        )
    )
    for code in ("159915", "511990"):
        w.store(code, "none", df, "synthetic-test-only")
    with db.new_session() as s:
        initialize(s, 100000)
        s.commit()
    yield db, w
    db.close()


def submit(setup, **kw):
    db, w = setup
    with db.new_session() as s:
        r = execute_reference_order(
            s,
            w,
            kw.pop("code", "511990"),
            kw.pop("side", "buy"),
            kw.pop("quantity", 10),
            **kw,
        )
        s.commit()
        return r


def test_complete_roundtrip_fees_slippage_and_ledger_reconcile(setup):
    buy = submit(setup, order_id="buy")
    assert buy["status"] == "FILLED" and buy["receipt"]["model_price"] == 10.005
    assert buy["receipt"]["fee"] == 0.03
    sell = submit(setup, side="sell", order_id="sell")
    db, w = setup
    with db.new_session() as s:
        a = s.get(PaperAccount, 1)
        h = s.get(PaperHolding, "511990")
        assert h.quantity == 0 and h.cost == 0
        assert a.cash / SCALE == pytest.approx(100000 - 0.1 - 0.06)
        history = execution_history(s)
        assert len(history["orders"]) == 2 and len(history["marks"]) == 2
        assert history["marks"][-1]["equity"] == pytest.approx(a.cash / SCALE)
        for o in history["orders"]:
            r = o["receipt"]
            t = s.get(PaperTrade, r["trade_id"])
            assert (
                t.quantity == r["filled_quantity"]
                and t.price / SCALE == r["model_price"]
            )


def test_partial_fill_duplicate_requests_cancel_and_restart(setup):
    r = submit(setup, order_id="partial", quantity=100, max_fill_quantity=30)
    assert r["status"] == "PARTIAL" and r["filled_quantity"] == 30
    assert (
        submit(setup, order_id="partial", quantity=100, max_fill_quantity=30)[
            "filled_quantity"
        ]
        == 30
    )
    r = submit(
        setup,
        order_id="partial",
        quantity=100,
        max_fill_quantity=20,
        attempt_id="second",
    )
    assert r["filled_quantity"] == 50 and len(r["receipts"]) == 2
    db, w = setup
    with db.new_session() as s:
        assert cancel_order(s, "partial")["status"] == "CANCELLED"
        before = execution_history(s)
        assert cancel_order(s, "partial")["status"] == "CANCELLED"
        assert execution_history(s) == before
        s.commit()
    db.engine.dispose()
    assert (
        submit(setup, order_id="partial", quantity=100, attempt_id="third")[
            "filled_quantity"
        ]
        == 50
    )
    with db.new_session() as s:
        assert s.get(PaperHolding, "511990").quantity == 50
        assert s.query(PaperReceipt).count() == 2


def test_missing_raw_never_uses_adjusted_price_and_pending_can_retry(setup):
    db, w = setup
    raw = w.history("511990", "none")
    w.store("563020", "qfq", raw, "synthetic-test-only-adjusted")
    assert submit(setup, code="563020", order_id="pending")["status"] == "PENDING"
    with db.new_session() as s:
        assert s.query(PaperTrade).count() == 0
    w.store("563020", "none", raw, "synthetic-test-only-raw")
    assert submit(setup, code="563020", order_id="pending")["status"] == "FILLED"


@pytest.mark.parametrize("side,quantity", [("buy", 1000000), ("sell", 1)])
def test_insufficient_cash_or_holdings_never_fills(setup, side, quantity):
    r = submit(setup, side=side, quantity=quantity)
    assert r["status"] == "REJECTED" and r["receipts"] == []
    db, _ = setup
    with db.new_session() as s:
        assert (
            s.get(PaperAccount, 1).cash == 100000 * SCALE
            and s.query(PaperTrade).count() == 0
        )


def test_t_plus_one_rejection_preserves_position(setup):
    assert submit(setup, code="159915")["status"] == "FILLED"
    assert submit(setup, code="159915", side="sell")["status"] == "REJECTED"


def test_future_stale_and_incomplete_prices_are_blocked(setup):
    db, w = setup
    raw = w.history("511990", "none")
    raw.loc[:, "date"] = pd.Timestamp(datetime.now().date() - timedelta(days=10))
    w.store("511990", "none", raw, "synthetic-test-only")
    assert (
        submit(setup, as_of=datetime.now(timezone.utc) - timedelta(days=20))["status"]
        == "PENDING"
    )
    # No stale substitute is used when the current latest bar is absent.
    with db.new_session() as s:
        s.query(
            __import__(
                "spear_shield.database.models", fromlist=["MarketDaily"]
            ).MarketDaily
        ).filter_by(symbol_code="511990").delete()
        s.commit()
    w.store("511990", "none", raw, "synthetic-test-only")
    assert submit(setup)["status"] == "PENDING"


def test_failed_receipt_write_rolls_back_cash_trade_and_order(setup, monkeypatch):
    db, w = setup
    with db.new_session() as s:
        original = s.add

        def fail(obj, *args, **kw):
            if isinstance(obj, PaperReceipt):
                raise OSError("synthetic write failure")
            return original(obj, *args, **kw)

        monkeypatch.setattr(s, "add", fail)
        with pytest.raises(OSError):
            execute_reference_order(s, w, "511990", "buy", 10, order_id="recover")
        s.rollback()
    assert submit(setup, order_id="recover")["status"] == "FILLED"
    with db.new_session() as s:
        assert (
            s.query(PaperTrade).count() == 1
            and s.get(PaperHolding, "511990").quantity == 10
        )


def test_reused_order_id_cannot_change_intent(setup):
    submit(setup, order_id="immutable")
    with pytest.raises(ValueError):
        submit(setup, order_id="immutable", quantity=11)


def test_failed_update_requires_explicit_cache_permission(setup):
    _, w = setup
    w.failure("511990", "synthetic-test-only")
    assert submit(setup)["status"] == "PENDING"
    r = submit(setup, allow_failed_cache=True)
    assert r["status"] == "FILLED" and r["receipt"]["allow_failed_cache"] is True


def test_valuation_failure_is_unknown_and_never_reverts_fills(setup):
    db, w = setup
    assert submit(setup)["status"] == "FILLED"
    w.failure("511990", "synthetic failed update")
    with db.new_session() as s:
        mark = mark_equity(s, w)
        assert mark["quality"] == "UNKNOWN" and mark["valuation_issues"]
        assert mark["holdings"][0]["quantity"] == 10
        assert mark["initial"] == 100000 and mark["return_pct"] is not None
        assert s.query(PaperTrade).count() == 1


def test_future_execution_rejected_without_order_or_trade(setup):
    with pytest.raises(ValueError):
        submit(setup, as_of=datetime.now(timezone.utc) + timedelta(days=1))
    db, _ = setup
    with db.new_session() as s:
        assert not execution_history(s)["orders"]
        assert s.query(PaperTrade).count() == 0


def test_additive_schema_and_legacy_account_observation_require_confirmation(setup):
    from spear_shield.portfolio.paper_execution import (
        PaperAccountOrigin,
        adopt_legacy_account,
    )

    db, w = setup
    with db.new_session() as s:
        s.query(PaperAccountOrigin).delete()
        s.commit()  # test-only emulates pre-upgrade DB
    db.init()
    db.init()
    r = submit(setup, order_id="legacy-observation")
    assert r["status"] == "PENDING"
    with db.new_session() as s:
        assert s.get(PaperAccount, 1).cash == 100000 * SCALE
        adopt_legacy_account(s)
        s.commit()
    assert submit(setup, order_id="legacy-observation")["status"] == "FILLED"
