"""以真实免费快照核对复权/跨源行情，在真实桌面事件循环运行策略研究回放。"""

import json
import os
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "cache" / "phase5-preview"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["SPEAR_SHIELD_DATA_DIR"] = str(DATA)


def main():
    from spear_shield.data.history_audit import cash_dividends, qfq_asof, compare_prices
    from spear_shield.services.research_dataset import ResearchSnapshots, price_index
    from spear_shield.services.workspace import Workspace
    from spear_shield.database.engine import Database
    from PySide6.QtCore import QTimer, QDate
    from PySide6.QtWidgets import QApplication, QScrollArea
    from spear_shield.ui.main_window import MainWindow
    from spear_shield.ui.theme import apply_theme

    db = Database(f"sqlite:///{(DATA/'spear_shield.db').as_posix()}")
    workspace = Workspace(db)
    sources = ResearchSnapshots()
    end = date(2026, 10, 30)
    results = {}
    raw, _ = sources.read("etf_563020_daily_unadjusted")
    dividends, _ = sources.read("etf_563020_dividends")
    if len(raw) and len(dividends):
        raw = price_index(raw)
        raw["adjust"] = "none"
        actions = cash_dividends(
            "563020", dividends, source="东方财富分红送配详情，支付日按表中明示"
        )
        rebuilt = qfq_asof(raw, actions, as_of=end)
        vendor = workspace.history("563020")
        vendor = vendor.loc[vendor.date.dt.date <= end].copy()
        # 当前供应商qfq的锚点在当前日，比较前先对同一截止日价格单位归一。
        anchor = float(raw.loc[raw.date.dt.date <= end].iloc[-1].close) / float(
            vendor.iloc[-1].close
        )
        vendor["close"] *= anchor
        results["563020_event_reconstruction_vs_vendor"] = compare_prices(
            rebuilt, vendor, end=end
        )
        cumulative, _ = sources.read("etf_563020_cumulative_dividends")
        if len(cumulative):
            import pandas as pd

            actual = pd.DataFrame(
                {
                    "date": pd.to_datetime([a.ex_date for a in actions]),
                    "close": [a.cash_per_unit for a in actions],
                }
            ).sort_values("date")
            actual["close"] = actual.close.cumsum()
            other = cumulative.rename(columns={"日期": "date", "累计分红": "close"})
            results["563020_cumulative_dividends_cross_source"] = compare_prices(
                actual, other, tolerance_abs=0.000001, end=end
            )
    a, _ = sources.read("index_399006_sina")
    b, _ = sources.read("index_399006_em")
    results["399006_cross_source"] = (
        compare_prices(price_index(a), price_index(b), end=end)
        if len(a) and len(b)
        else {"status": "second_source_missing"}
    )
    if len(a) and len(b):
        # 新浪3位与东财2位小数：按两源显示精度误差上界0.0005+0.005另报，不改变原始严阈值结果。
        results["399006_precision_normalized"] = compare_prices(
            price_index(a), price_index(b), tolerance_abs=0.005500001, end=end
        )
        from spear_shield.strategy.features import (
            settled_bars,
            complete_segment_indicators,
        )
        import pandas as pd

        cal, _ = sources.calendar()
        cutoff = pd.Timestamp(end).tz_localize("Asia/Shanghai") + pd.Timedelta(
            hours=15, minutes=30
        )
        sensitivity = {}
        for period in ("week", "month"):
            left = complete_segment_indicators(
                settled_bars(price_index(a), cal, cutoff, period), period
            )
            right = complete_segment_indicators(
                settled_bars(price_index(b), cal, cutoff, period), period
            )
            pair = left[["date", "close", "ma60", "slope_ma60"]].merge(
                right[["date", "close", "ma60", "slope_ma60"]],
                on="date",
                suffixes=("_sina", "_em"),
            )
            pair = pair.loc[pair.date >= pd.Timestamp("2024-01-01")].dropna()
            sensitivity[period] = {
                "common_periods": len(pair),
                "slope_direction_disagreements": int(
                    (pair.slope_ma60_sina.gt(0) != pair.slope_ma60_em.gt(0)).sum()
                ),
                "slope_0_1_disagreements": int(
                    (pair.slope_ma60_sina.ge(0.1) != pair.slope_ma60_em.ge(0.1)).sum()
                ),
                "close_vs_ma60_disagreements": int(
                    (
                        pair.close_sina.gt(pair.ma60_sina)
                        != pair.close_em.gt(pair.ma60_em)
                    ).sum()
                ),
            }
        results["399006_threshold_sensitivity_2024_onwards"] = sensitivity
    (DATA / "phase6_completion_validation.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(results, ensure_ascii=False), flush=True)
    db.close()
    app = QApplication([])
    apply_theme(app)
    window = MainWindow(data_dir=DATA)
    window.resize(1560, 1160)
    window.show()
    window.nav_list.setCurrentRow(5)
    page = window.stack.widget(5)
    page.start.setDate(QDate(2024, 1, 2))
    page.end.setDate(QDate(2026, 10, 30))
    page.fee.setValue(0.03)
    page.slippage.setValue(0.05)
    page.benchmark.setCurrentIndex(4)
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(50)
    exit_status = [1]

    def done(response):
        def save():
            folder = ROOT / "assets" / "phase6"
            window.grab().save(str(folder / "strategy_replay.png"))
            first = response["data"]["runs"][0]
            r = first.get("result")
            results["replay"] = {
                "status": first["status"],
                "blockers": first["blockers"],
                "timer_ticks_50ms": len(ticks),
                "report_saved": Path(page.report_dir, "report.json").is_file(),
                "metrics": r["metrics"] if r else None,
                "attack_trade_count": (
                    r["metadata"]["attack_trade_count"] if r else None
                ),
                "defense_trade_count": (
                    r["metadata"]["defense_trade_count"] if r else None
                ),
                "audits": len(r["metadata"]["strategy_audit"]) if r else None,
                "input_gaps": r["metadata"]["input_gaps"] if r else None,
            }
            (DATA / "phase6_completion_validation.json").write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(results["replay"], ensure_ascii=False), flush=True)
            scroll = page.findChild(QScrollArea)
            scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())

            def finish():
                window.grab().save(str(folder / "strategy_replay_details.png"))
                exit_status[0] = 0 if r else 1
                window.close()
                app.quit()

            QTimer.singleShot(250, finish)

        QTimer.singleShot(400, save)

    page.job.succeeded.connect(done)
    page.job.failed.connect(
        lambda reason: (print(reason, flush=True), window.close(), app.quit())
    )
    QTimer.singleShot(250, page.execute)
    QTimer.singleShot(125000, app.quit)
    app.exec()
    return exit_status[0]


if __name__ == "__main__":
    raise SystemExit(main())
