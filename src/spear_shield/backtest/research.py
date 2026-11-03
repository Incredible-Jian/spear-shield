"""现有缓存的基准研究与严格策略回放预检；不伪造完整策略绩效。"""

from dataclasses import asdict
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .engine import BacktestEngine
from .models import MarketData, Target, TradingCalendar
from ..strategy.engine import StrategyEngine
from ..strategy.types import Policy, Position

SH = ZoneInfo("Asia/Shanghai")
FULL_STRATEGY_BLOCKERS = [
    "原始规则仍有待确认项（见 rules_pending_confirmation.md），IV缺失、股债性价比待确认",
    "缓存没有历史时点可知的前复权版本/指标发布时间，不能证明不存在前视偏差",
    "尚无覆盖区间的公司行动/停牌/交易日历完整性证明与批次持仓、盘中ATR执行数据",
]


def replay_decisions(snapshots, *, policy=None, position=None):
    """回放真实时点证据，仅审计裁决，不把未成交动作当作持仓。

    提供调用者注入执行账本之前，每条输入使用显式position，不推进持仓；
    此接口不是完整资金回测，也不计算收益。
    """
    engine = StrategyEngine(policy or Policy())
    previous = None
    output = []
    for snapshot in snapshots:
        if previous is not None and snapshot.as_of <= previous:
            raise ValueError("快照须严格按可知时间升序")
        previous = snapshot.as_of
        output.append(engine.evaluate(snapshot, position or Position()))
    return output


def run_benchmarks(
    workspace, config, *, selection="comparison", defense_weights=None, calendar=None
):
    if config.mode != "qfq_research":
        raise ValueError(
            "缓存研究入口仅支持前复权研究；原始价公司行动模式使用独立引擎接口"
        )
    if selection not in ("strategy", "attack", "defense", "comparison"):
        raise ValueError("未知回测方案")
    weights = defense_weights or {"563020": 0.6, "511360": 0.3, "511990": 0.1}
    # 固定权重仅为公开、可调整的基准场景，不表示当前Z/正式防守裁决。
    if (
        set(weights) != {"563020", "511360", "511990"}
        or abs(sum(weights.values()) - 1) > 1e-9
    ):
        raise ValueError("防守基准三个权重须合计100%")
    output = []
    if selection in ("strategy", "comparison"):
        output.append(
            {
                "name": "矛与盾完整策略",
                "status": "blocked",
                "blockers": FULL_STRATEGY_BLOCKERS,
                "result": None,
            }
        )
    for key, name, allocation in (
        ("attack", "持有创业板ETF（前复权单位研究）", {"159915": 1.0}),
        ("defense", "防守固定初始配比（买入持有，不再平衡）", weights),
    ):
        if selection not in (key, "comparison"):
            continue
        try:
            frames = {
                s: workspace.history(s, "qfq") for s, w in allocation.items() if w > 0
            }
            if missing := [s for s, df in frames.items() if df.empty]:
                raise ValueError(f"行情缺失:{','.join(missing)}")
            anchor = workspace.history("399006", "qfq")
            if calendar is None:
                # 并集显露缺口，不用交集悄悄消除停牌/未上市区间。
                dates = sorted(
                    {
                        d.date()
                        for df in [*frames.values(), anchor]
                        for d in df.date
                        if config.start <= d.date() <= config.end
                    }
                )
                current_calendar = TradingCalendar(
                    tuple(dates), "缓存行情日期并集（非完整交易日历认证）"
                )
            else:
                current_calendar = calendar
            signal_time = datetime.combine(
                config.start - timedelta(days=1), time(15, 30), SH
            )
            target = Target(
                signal_time,
                {s: w for s, w in allocation.items() if w > 0},
                "预先指定的基准初始配置；非历史策略买入信号",
                signal_time,
            )
            result = BacktestEngine().run(
                MarketData(frames, current_calendar), config, [target]
            )
            result.metadata.update(
                {
                    "name": name,
                    "initial_weights": allocation,
                    "rebalancing": "buy_and_hold",
                    "risk_free_rate": 0,
                    "universe": "用户指定核心ETF固定池，不作全市场筛选/上市前替代",
                }
            )
            partial = not current_calendar.complete and (
                result.metadata["effective_start"] != config.start.isoformat()
                or result.metadata["effective_end"] != config.end.isoformat()
            )
            coverage = (
                f"请求{config.start}至{config.end}；实际观测{result.metadata['effective_start']}至"
                f"{result.metadata['effective_end']}；行情并集无法验证共同缺日/非交易日"
            )
            result.metadata["coverage_note"] = coverage
            result.metadata["coverage_partial"] = partial
            output.append(
                {
                    "name": name,
                    "status": "partial_research" if partial else "research_only",
                    "blockers": ["仅部分日期区间研究：" + coverage] if partial else [],
                    "result": result,
                }
            )
        except (ValueError, KeyError) as exc:
            output.append(
                {
                    "name": name,
                    "status": "blocked",
                    "blockers": [str(exc)],
                    "result": None,
                }
            )
    return output


def result_payload(result):
    def records(frame):
        return [
            {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()}
            for r in frame.to_dict("records")
        ]

    return {
        "config": asdict(result.config),
        "curve": records(result.curve),
        "trades": result.trades,
        "orders": result.orders,
        "signals": result.signals,
        "metrics": result.metrics,
        "metadata": result.metadata,
    }
