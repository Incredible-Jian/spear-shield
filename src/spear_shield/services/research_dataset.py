"""加载经过哈希校验的免费研究快照；不把抓取时间当历史发布时间。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from ..backtest.models import TradingCalendar
from ..data.research_sources import DEFAULT_OUTPUT

SH = ZoneInfo("Asia/Shanghai")


class ResearchSnapshots:
    def __init__(self, root=DEFAULT_OUTPUT):
        self.root = Path(root).resolve()
        path = self.root / "manifest.json"
        self.manifest = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.is_file()
            else {"runs": []}
        )

    def read(self, key, artifact_name=None):
        # 优先最近成功快照，失败刷新不会覆盖仍可审计的历史文件。
        for run in reversed(self.manifest["runs"]):
            for item in run["tasks"]:
                if item["key"] != key or item["status"] != "ok":
                    continue
                for artifact in item["artifacts"]:
                    if artifact_name and Path(artifact["path"]).name != artifact_name:
                        continue
                    path = (self.root / artifact["path"]).resolve()
                    if not path.is_relative_to(self.root):
                        raise ValueError("快照路径越出数据目录")
                    payload = path.read_bytes()
                    if hashlib.sha256(payload).hexdigest() != artifact["sha256"]:
                        raise ValueError(f"{key}源文件哈希不匹配")
                    frame = pd.read_csv(
                        path, dtype={"BOARD_CODE": str, "指数代码": str}
                    )
                    return frame, {
                        "key": key,
                        "source_url": item["source_url"],
                        "retrieved_at": item["retrieved_at"],
                        "sha256": artifact["sha256"],
                        "is_official": item["is_official"],
                        "notes": item["notes"],
                    }
        return pd.DataFrame(), {"key": key, "status": "missing"}

    def calendar(self):
        frame, meta = self.read("trade_calendar_sina")
        if frame.empty:
            raise ValueError("缺少独立交易日历，请运行collect_research_sources.py")
        dates = tuple(pd.to_datetime(frame.trade_date).dt.date)
        return TradingCalendar(dates, "新浪历史交易日历/" + meta["sha256"], True), meta


def price_index(frame):
    if frame.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    df = frame.rename(
        columns={
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
        }
    ).copy()
    df["date"] = pd.to_datetime(df.date)
    return df.sort_values("date").reset_index(drop=True)


def inferred_release_series(
    frame, *, date_column, value_column, source, calendar, lag_sessions=1
):
    """研究用保守延迟假设，明确与官方actual publication区分。

    默认观测交易日的下一交易日09:00；不能证明供应商当时已发布或未修订。
    """
    df = (
        frame[[date_column, value_column]]
        .rename(columns={date_column: "date", value_column: "value"})
        .copy()
    )
    df["date"] = pd.to_datetime(df.date)
    df["value"] = pd.to_numeric(df.value, errors="raise")
    if df.date.duplicated().any():
        raise ValueError("宏观源重复日期")
    sessions = list(calendar.sessions)
    lookup = {d: i for i, d in enumerate(sessions)}

    def release(day):
        i = lookup.get(day)
        if i is None or i + lag_sessions >= len(sessions):
            return pd.NaT
        return datetime.combine(sessions[i + lag_sessions], time(9), SH)

    if len(df):
        expected = pd.DataFrame(
            {
                "date": pd.to_datetime(
                    [
                        d
                        for d in sessions
                        if df.date.min().date() <= d <= df.date.max().date()
                    ]
                )
            }
        )
        df = expected.merge(df, on="date", how="left")  # 只显露缺失NaN，不填入数字。
    df["available_at"] = df.date.dt.date.map(release)
    df["source"] = source + ";发布时间为下一交易日09:00研究假设，不是历史实际发布记录"
    return df.dropna(subset=["available_at"]).sort_values("date").reset_index(drop=True)


@dataclass
class OperationalDataset:
    growth: pd.DataFrame
    dividend: pd.DataFrame
    calendar: TradingCalendar
    macros: dict
    provenance: dict
    limitations: list[str]


def load_operational_dataset(workspace, root=DEFAULT_OUTPUT):
    reader = ResearchSnapshots(root)
    calendar, calendar_meta = reader.calendar()
    growth, growth_meta = reader.read("index_399006_sina")
    if growth.empty:
        growth = workspace.history("399006", "qfq")
        growth_meta = {"source": "现有399006缓存", "actual_publication": "unknown"}
    dividend, dividend_meta = reader.read("index_H30269")
    macros, provenance, limitations = (
        {},
        {"calendar": calendar_meta, "399006": growth_meta, "H30269": dividend_meta},
        [],
    )
    for name, artifact in (
        ("iv_short", "qvix_cyb.csv"),
        ("iv_long", "qvix_300index.csv"),
    ):
        frame, meta = reader.read("qvix", artifact)
        provenance[name] = meta
        if not frame.empty:
            macros[name] = inferred_release_series(
                frame,
                date_column="date",
                value_column="close",
                source="非官方期权论坛QVIX/" + meta["sha256"],
                calendar=calendar,
            )
        else:
            limitations.append(f"{name}免费QVIX源本次不可用，相关规则保持数据缺失")
    margin, margin_meta = reader.read("margin_market_statistics")
    provenance["margin_market_statistics"] = margin_meta
    if len(margin):
        if not {
            "MARGIN_A_RATIO",
            "MARGIN_A_TRADE",
            "TRADE_DATE",
            "MARKET",
            "BOARD_CODE",
        } <= set(margin):
            raise ValueError("发布方两融统计缺明确占比字段/范围")
        if margin.TRADE_DATE.duplicated().any():
            raise ValueError("两融同日多范围不能直接混合")
        for key, col in (
            ("margin_pct", "MARGIN_A_RATIO"),
            ("margin_turnover_pct", "MARGIN_A_TRADE"),
        ):
            macros[key] = inferred_release_series(
                margin,
                date_column="TRADE_DATE",
                value_column=col,
                source=f"东方财富RPT_MARGIN_DATASTATISTICS/{col}/百分数/"
                + margin_meta["sha256"],
                calendar=calendar,
            )
        provenance["margin_scope_codes"] = sorted(set(margin.BOARD_CODE.astype(str)))
    # 分子可取，不能靠任选分母/基日使原文1.0阈值人为成立。
    numerator, numerator_meta = reader.read("index_H00300_csindex")
    provenance["equity_bond_numerator"] = numerator_meta
    if not numerator.empty:
        # 中证请求起点锚点可能落在1990；官方基日前的伪锚点严格排除。
        numerator = numerator.loc[
            pd.to_datetime(numerator["日期"]) >= pd.Timestamp("2004-12-31")
        ]
        if not numerator["指数代码"].astype(str).eq("H00300").all():
            raise ValueError("股债分子不是H00300全收益指数")
        macros["equity_bond_numerator"] = inferred_release_series(
            numerator,
            date_column="日期",
            value_column="收盘",
            source="中证H00300全收益/" + numerator_meta["sha256"],
            calendar=calendar,
        )
    limitations.extend(
        [
            "回溯公开行情与宏观序列：可用时间按经济日期保守滞后一交易日假设，不是假称历史实际发布版本",
            "股债分子必须为有来源的H00300全收益；二级债基金具体分母、共同基准尺度及1.0阈值不能从原文或公开资料唯一推出",
            "两融占比采用发布方直接统计字段并保留历史范围变更，非交易所原始分母逐日重建；PE/PEG仍须同口径真实历史",
            "当前ETF前复权缓存仅用于研究单位；官方完整公司行动、历史数据修订和停牌完整性未认证",
        ]
    )
    return OperationalDataset(
        price_index(growth),
        price_index(dividend),
        calendar,
        macros,
        provenance,
        limitations,
    )
