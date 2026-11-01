"""指标引擎：统一入口，组合各指标并附带参数与周期元信息。

引擎不做重采样：周期类型（day/week/month）仅作为元信息记录，
调用方需先通过 DataService 取到对应周期的 bar（日线/周线/月线）再传入。
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .atr import atr as compute_atr
from .bollinger import bollinger as compute_bollinger
from .macd import macd as compute_macd
from .moving_average import ema as compute_ema
from .moving_average import sma as compute_sma
from .price import amplitude_pct, deviation_pct, pct_change, slope
from .rsi import rsi as compute_rsi
from .volume import volume_ma, volume_percentile, volume_ratio

_REQUIRED_COLUMNS = {"date", "open", "high", "low", "close", "volume"}


@dataclass(frozen=True)
class IndicatorResult:
    """指标计算结果：原始行情字段 + 指标字段，以及参数/周期元信息。"""

    data: pd.DataFrame
    meta: dict


class IndicatorEngine:
    """对标准化 bar DataFrame 计算一组默认指标。"""

    def __init__(self, period: str = "day") -> None:
        if period not in ("day", "week", "month"):
            raise ValueError(f"未知周期类型: {period!r}")
        self.period = period

    def compute(self, df: pd.DataFrame) -> IndicatorResult:
        """计算默认指标集，返回 IndicatorResult（不改动入参）。"""
        self._validate(df)
        out = df.copy()
        meta: dict[str, dict] = {}

        # 均线（MA60 周线 / 60 月线 / 10 周线 / 30 周线 均由此覆盖）
        for w in (5, 10, 30, 60):
            col = f"ma{w}"
            out[col] = compute_sma(out["close"], w)
            meta[col] = {"indicator": "sma", "window": w}

        for w in (12, 26):
            col = f"ema{w}"
            out[col] = compute_ema(out["close"], w)
            meta[col] = {"indicator": "ema", "window": w}

        dif, dea, hist = compute_macd(out["close"])
        out["dif"], out["dea"], out["macd_hist"] = dif, dea, hist
        meta["dif"] = meta["dea"] = meta["macd_hist"] = {
            "indicator": "macd", "fast": 12, "slow": 26, "signal": 9,
        }

        out["rsi14"] = compute_rsi(out["close"], 14)
        meta["rsi14"] = {"indicator": "rsi", "period": 14}

        mid, up, low, width = compute_bollinger(out["close"])
        out["boll_mid"], out["boll_up"], out["boll_low"], out["boll_width"] = (
            mid, up, low, width,
        )
        meta["boll_mid"] = meta["boll_up"] = meta["boll_low"] = meta["boll_width"] = {
            "indicator": "bollinger", "period": 20, "num_std": 2.0, "ddof": 0,
        }

        out["atr14"] = compute_atr(out["high"], out["low"], out["close"], 14)
        meta["atr14"] = {"indicator": "atr", "period": 14}

        out["vol_ma5"] = volume_ma(out["volume"], 5)
        out["vol_ratio5"] = volume_ratio(out["volume"], 5)
        out["vol_pct52"] = volume_percentile(out["volume"], 52)
        meta["vol_ma5"] = {"indicator": "volume_ma", "window": 5}
        meta["vol_ratio5"] = {"indicator": "volume_ratio", "window": 5}
        meta["vol_pct52"] = {"indicator": "volume_percentile", "window": 52}

        out["ret"] = pct_change(out["close"], 1)
        out["dev_ma60"] = deviation_pct(out["close"], 60)
        out["amplitude"] = amplitude_pct(out["high"], out["low"], out["close"], 1)
        out["slope_ma60"] = slope(out["ma60"], 1)
        meta["ret"] = {"indicator": "pct_change", "periods": 1}
        meta["dev_ma60"] = {"indicator": "deviation_pct", "window": 60}
        meta["amplitude"] = {"indicator": "amplitude_pct", "periods": 1}
        meta["slope_ma60"] = {"indicator": "slope", "source": "ma60", "periods": 1}

        return IndicatorResult(
            data=out,
            meta={"period": self.period, "indicators": meta},
        )

    @staticmethod
    def _validate(df: pd.DataFrame) -> None:
        missing = _REQUIRED_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(f"缺少必需列: {sorted(missing)}")
        if df["date"].duplicated().any():
            raise ValueError("存在重复日期")
        if not df["date"].is_monotonic_increasing:
            raise ValueError("日期未按升序排列")
