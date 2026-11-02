"""五维展示与共振矩阵：保留缺失/待确认，不输出伪完整判断。"""
from __future__ import annotations

from dataclasses import dataclass, replace

from .evaluation import number
from .types import Policy, Snapshot


@dataclass(frozen=True)
class Dimension:
    name: str
    status: str
    value: object
    formula: str
    thresholds: str
    sources: tuple[str, ...]
    timestamps: tuple[str, ...]


def thermometer(snapshot: Snapshot, policy: Policy) -> dict:
    def dim(name, keys, formula, thresholds, classify, definition=None):
        values = tuple(snapshot.get(k) for k in keys)
        state = ("待确认" if definition and not policy.approved(definition) else
                 "数据缺失" if not all(number(v) for v in values) else classify(*values))
        evidence = [snapshot.facts[k] for k in keys if k in snapshot.facts]
        return Dimension(name, state, values, formula, thresholds,
                         tuple(e.source for e in evidence),
                         tuple(e.available_at.isoformat() for e in evidence))

    dimensions = [
        dim("60月线斜率", ("month_slope",), "(MA60本月/MA60上月-1)*100",
            ">0战略做多；<=0战略防守", lambda v: "战略做多" if v > 0 else "战略防守"),
        dim("股债性价比", ("equity_bond_ratio",), "沪深300全收益/二级债基",
            "逼近1.0（阈值待确认）", lambda v: "数值可用，极值阈值待确认",
            "equity_bond_definition"),
        dim("风格Z-Score", ("zscore",), "(创业板/红利比值-156周均值)/156周标准差",
            "Z>2成长泡沫；Z<-2成长极度超跌",
            lambda v: "成长泡沫" if v > 2 else "成长极度超跌" if v < -2 else "阈值内",
            "zscore_definition"),
        dim("期权IV", ("iv_short_pct", "iv_long_pct"), "短期/长期IV历史分位",
            ">95且>80极度恐慌；<20且<30极度自满",
            lambda a, b: "极度恐慌" if a > 95 and b > 80 else
            "极度自满" if a < 20 and b < 30 else "阈值内"),
        dim("两融水位", ("margin_pct", "margin_turnover_pct"),
            "两融余额/流通市值*100；两融交易额/A股成交额*100",
            "出清2.0%附近；极值2.3%–2.5%；透支>10%且顶背离",
            lambda a, b: "数值可用，红线/形态定义需单独审核", "margin_definition"),
    ]
    iv = dimensions[3]
    if iv.status != "数据缺失":
        if not all(0 <= v <= 100 for v in iv.value):
            dimensions[3] = replace(iv, status="数据异常")
        elif not policy.approved("iv_definition"):
            dimensions[3] = replace(iv, status="待确认")
    # 数字齐全也不意味着未确认的 IV 窗口和两融阈值已经正式生效。
    redline = policy.parameters.get("margin_redline_pct")
    complete = (all(d.status not in ("待确认", "数据缺失", "数据异常") for d in dimensions)
                and number(redline) and 2.3 <= redline <= 2.5
                and all(policy.approved(k) for k in
                        ("iv_definition", "margin_redline", "equity_bond_extreme")))
    return {"complete": complete, "status": "完整" if complete else "五维不完整",
            "dimensions": tuple(dimensions)}


def resonance(month_up: bool | None, week_up: bool | None) -> dict:
    """纯矩阵；方向判定由已确认的定义提供，不自行把周斜率0划为上下。"""
    if month_up is None or week_up is None:
        return {"status": "待确认或数据缺失", "quadrant": None}
    if not isinstance(month_up, bool) or not isinstance(week_up, bool):
        raise ValueError("周期方向必须是 bool/None")
    states = {(True, True): "绝对主升浪", (True, False): "牛市中期回调",
              (False, True): "熊市反弹中继", (False, False): "绝对主跌浪"}
    return {"status": states[month_up, week_up], "quadrant": (month_up, week_up)}
