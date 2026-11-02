"""原文逐条规则。模糊术语只接受有确认记录的证据，不内置猜测算法。"""
from __future__ import annotations

from zoneinfo import ZoneInfo

from .evaluation import (all_of, any_of, check, compare, consecutive, fixed,
                         flag, number, result)
from .types import Action, Policy, Position, RuleResult, Snapshot, Status


def confirmed_numeric(s, policy, definition, keys, predicate, expression):
    return check(s, definition, keys, compare(predicate), expression,
                 policy=policy, definition=definition)


def margin_entry_check(s: Snapshot, policy: Policy, *, breach: bool = False):
    threshold = policy.parameters.get("margin_redline_pct")
    valid = number(threshold) and 2.3 <= threshold <= 2.5
    return all_of("两融禁止建仓滤网", (
        fixed("红线具体数值", True if valid else None,
              f"确认的两融红线={threshold}%，必须在原文2.3–2.5范围", "margin_redline"),
        confirmed_numeric(s, policy, "margin_definition", ("margin_pct",),
                          lambda v: v > threshold if breach else 0 <= v <= threshold,
                          "两融余额占比>已确认红线" if breach else "0<=两融余额占比<=已确认红线") if valid else
        fixed("两融数值", None, "缺少已确认红线参数", "margin_redline"),
        fixed("红线定义", True if policy.approved("margin_redline") else None,
              "红线已由负责人确认", "margin_redline")))


def exit_rules(s: Snapshot, p: Position, policy: Policy) -> tuple[RuleResult, ...]:
    def numeric(name, keys, predicate, expression):
        return check(s, name, keys, compare(predicate), expression)

    def defined(key, definition):
        return flag(s, key, policy, definition)

    holding = fixed("holding", p.attack_weight > 0, f"权益权重={p.attack_weight}>0")
    out = []

    def add(rule, priority, conditions, action, explanation):
        out.append(result(rule, priority, (holding, *conditions), action, explanation))

    negative = any_of("P0趋势终结", (
        consecutive(s, "week_slopes2", lambda v: v < 0, "连续2个已结算周斜率<0"),
        consecutive(s, "month_slopes2", lambda v: v < 0, "连续2个已结算月斜率<0")))
    out.append(result("P0_TREND", 0, (negative,), Action("clear", 1),
        "60周线连续2周<0或60月线连续2月<0，下一交易日开盘清空进攻端；防守另算"))

    eligible = s.get("eligible_lot_weight")
    valid_lots = number(eligible) and 0 <= eligible <= p.attack_weight
    fraction = eligible / p.attack_weight if valid_lots else 1.0
    add("P1_FALSE_BREAK", 1, (
        numeric("跌破60周线", ("week_close", "week_ma60"), lambda c, m: c < m,
                "周收盘<60周均线"),
        fixed("买入后该笔仓位", eligible > 0 if valid_lots else None,
              "eligible_lot_weight 为已在买入后观察周收盘的实际批次权重")),
        Action("reduce", fraction, scope="eligible_lots"), "清空受影响批次，不摊低成本")

    def sideways(rows, entry_high):
        if not isinstance(rows, (list, tuple)) or len(rows) != 4 or not number(entry_high):
            return None
        if any(not isinstance(r, (list, tuple)) or len(r) != 4 or
               not all(number(v) for v in r) or r[3] <= 0 for r in rows):
            return None
        if any(l <= 0 or h < l or not l <= c <= h for h,l,c,prev in rows):
            return None
        if any(rows[i][3] != rows[i-1][2] for i in range(1,4)):
            return None
        # rows=(high,low,close,prev_close)，必须由完成建仓后的连续4周构造。
        narrow = all((h-l)/prev < .04 and close <= entry_high
                     for h, l, close, prev in rows)
        return narrow and .97 * rows[0][3] <= rows[-1][2] <= 1.03 * rows[0][3]

    add("P1_TIME", 1, (
        defined("post_entry_four_weeks", "entry_completion_definition"),
        check(s, "横盘4周", ("sideways_rows", "entry_week_high"), sideways,
              "连续4周收盘<=建仓周最高；每周(高-低)/前收<4%；累计涨跌±3%")),
        Action("reduce", .5), "时间成本止损减半；建仓完成口径须确认")

    add("P1_ATR", 1, (
        confirmed_numeric(s, policy, "atr_drawdown_definition", ("max_week_drop_price", "week_atr14"),
                          lambda drop, atr: atr >= 0 and drop > 2 * atr,
                          "同价格单位的单周最大下跌价差>2*14周ATR（取值时点已确认）"),),
        Action("reduce", .5, timing="intraday"),
        "单周最大下跌价差>2*14周ATR；价差基准/盘中ATR取值时点待确认")

    add("P2_STYLE", 2, (
        numeric("风格泡沫", ("zscore",), lambda z: z > 2, "Z>2"),
        fixed("Z口径", True if policy.approved("zscore_definition") else None,
              "156周窗口/ddof/标的已确认", "zscore_definition"),
        any_of("上影或滞涨", (defined("long_upper_shadow", "candle_definition"),
                               defined("low_volume_stall", "stall_definition")))),
        Action("reduce", .5), "Z>2且长上影或缩量滞涨，减半")

    top_conditions = (
        numeric("浮盈", ("profit_pct",), lambda v: v >= 80, "浮盈>=80%"),
        defined("rise_from_bottom_100", "bottom_definition"),
        defined("six_of_eight_above_ma30", "above_ma30_definition"),
        numeric("单周涨幅", ("week_return_pct",), lambda v: v >= 10, "周涨幅>=10%"),
        defined("volume_1_5", "volume_baseline_definition"),
        confirmed_numeric(s, policy, "rsi_definition", ("rsi",), lambda v: v > 88, "确认周期的RSI>88"),
        all_of("PE与PEG", (
            confirmed_numeric(s, policy, "pe_definition", ("pe_percentile",), lambda v: v > 80, "PE分位>80%"),
            numeric("PEG", ("peg",), lambda v: v > 2, "PEG>2"))),
    )
    positives = sum(c.value is True for c in top_conditions)
    unknowns = sum(c.value is None for c in top_conditions)
    top = (True if positives >= 5 else False if positives + unknowns < 5 else None)
    # 不把缺失项记为False；5个已知真足以证明“7选5”。
    count = fixed("7选5", top, f"已知真={positives},未知={unknowns},需>=5",
                  "top_components" if top is None and any(c.pending_definition for c in top_conditions) else None)
    top_result = result("P2_TOP", 2, (holding, count), Action("reduce", .5),
                        "高位7项至少5项成立，减半")
    out.append(RuleResult(top_result.rule_id, 2, top_result.status,
                          (holding, count, *top_conditions), top_result.action,
                          top_result.explanation))
    add("P2_MARGIN", 2, (margin_entry_check(s, policy, breach=True),
                         defined("top_divergence", "divergence_definition")),
        Action("reduce", .3), "两融红线且顶背离，减仓30%；不自动当成P0触发")
    add("P2_MARGIN_TURNOVER", 2, (
        numeric("两融交易占比", ("margin_turnover_pct",), lambda v: v > 10, "两融交易额/A股成交额>10%"),
        defined("margin_turnover_valid", "margin_definition"),
        defined("top_divergence", "divergence_definition")),
        None, "原文仅规定P2预警，无减仓幅度；禁止转换为交易动作")

    add("P3_MA10", 3, (
        numeric("浮盈", ("profit_pct",), lambda v: v > 30, "浮盈>30%"),
        numeric("跌破10周线", ("week_close", "week_ma10"), lambda c, m: c < m,
                "周收盘<10周均线")), Action("reduce", .25), "中继减仓25%；次周收回另查补回")
    add("P3_DOUBLE_TOP", 3, (
        defined("second_top", "double_top_definition"),
        numeric("H2缩量", ("volume_pct52",), lambda v: 0 <= v <= 30, "H2成交量位于52周后30%")),
        Action("reduce", .5), "第二顶缩量减半")
    add("P3_NECKLINE", 3, (defined("below_neckline", "double_top_definition"),),
        Action("clear", 1), "跌破已确认双顶颈线，全清")
    add("P3_TRAILING", 3, (
        numeric("浮盈", ("profit_pct",), lambda v: v > 100, "浮盈>100%"),
        defined("drawdown_8", "profit_drawdown_definition")),
        Action("clear", 1), "浮盈>100%且回撤8%全清；浮盈取峰值或当前值待确认")
    add("P3_STALL", 3, (
        numeric("浮盈", ("profit_pct",), lambda v: v > 120, "浮盈>120%"),
        defined("high_volume_stall", "stall_definition")),
        Action("clear", 1), "浮盈>120%且放量滞涨，全清")
    return tuple(out)


def entry_rules(s: Snapshot, p: Position, policy: Policy) -> tuple[RuleResult, ...]:
    def defined(key, definition):
        return flag(s, key, policy, definition)

    def numeric(name, keys, predicate, expression):
        return check(s, name, keys, compare(predicate), expression)

    slope2 = consecutive(s, "week_slopes2", lambda v: v >= .1,
                         "60周线斜率连续2周>=0.1%（1=1%）")
    monthly = numeric("月线战略方向", ("month_slope",), lambda v: v > 0, "60月线斜率>0")
    redline = margin_entry_check(s, policy)
    guards = (fixed("阶梯未锁", not p.nuclear, "核弹后关闭后续阶梯"), redline,
              defined("risk_budget_pass", "single_trade_risk_definition"))
    first_conditions = (slope2, monthly, defined("effective_above_ma60", "effective_break_definition"),
                        defined("bullish_week", "bullish_definition"),
                        numeric("放量", ("volume_pct52",), lambda v: 60 <= v <= 100, "52周量分位>=60（前40%）"))
    out = []

    def add(rule, conditions, action, explanation):
        out.append(result(rule, 4, (*guards, *conditions), action, explanation))

    no_base = fixed("无底仓", p.attack_weight == 0 and not p.stages, "无权益且未建第一档")
    add("ENTRY_FIRST", (no_base, *first_conditions), Action("entry", .5, stages=(1,)),
        "常规第一档占总资产50%，须已确认有效站上/收阳等定义")
    add("ENTRY_NUCLEAR", (no_base, *first_conditions,
        confirmed_numeric(s, policy, "zscore_definition", ("zscore",), lambda v: v < -2, "Z<-2"),
        numeric("股债比值真实存在", ("equity_bond_ratio",), lambda v: v > 0, "沪深300全收益/二级债基真实数值>0"),
        fixed("股债数据口径", True if policy.approved("equity_bond_definition") else None,
              "D3：分子分母未确认不使用代理", "equity_bond_definition"),
        defined("equity_bond_extreme", "equity_bond_extreme"),
        confirmed_numeric(s, policy, "iv_definition", ("iv_short_pct", "iv_long_pct"),
                          lambda a,b: 95 < a <= 100 and 80 < b <= 100, "短IV>95且长IV>80"),
        numeric("两融出清数值存在", ("margin_pct",), lambda v: v >= 0, "两融余额占比可计算"),
        defined("margin_cleared", "margin_clear_definition")),
        Action("entry", 1, stages=(1,)), "四条件同时满足才100%；缺IV/股债条件不成立为可执行信号")
    add("ENTRY_BEAR", (no_base, slope2,
        numeric("月线向下", ("month_slope",), lambda v: v <= 0, "月斜率<=0"),
        defined("bear_entry_allowed", "bear_precondition_conflict"),
        *first_conditions[2:]), Action("entry", .2, stages=(1,)),
        "熊市20%与月线前置条件矛盾，须确认豁免关系")
    add("ENTRY_FAST", (no_base, slope2,
        numeric("快速涨幅", ("week_return_pct",), lambda v: v >= 8, "周涨幅>=8%"),
        numeric("放量", ("volume_pct52",), lambda v: 60 <= v <= 100, "量分位>=60"),
        confirmed_numeric(s, policy, "pe_definition", ("pe_percentile",), lambda v: 0 <= v < 50, "PE分位<50%"),
        defined("fast_entry_allowed", "fast_bear_precedence")),
        Action("entry", .5, stages=(1,)), "快速通道50%，仅豁免月线；负月线与20%上限关系待确认")
    normal_base = fixed("常规阶梯底仓", p.attack_weight > 0 and 1 in p.stages and
                        not p.nuclear and p.entry_mode in ("normal", "catchup"),
                        "已记录常规/补投底仓；熊市/快速通道不默认为常规底仓")
    add("ENTRY_SECOND", (normal_base, slope2, monthly,
        fixed("二档未执行", 2 not in p.stages, "第二档仅一次"),
        defined("retest_ma60", "retest_definition"),
        numeric("回踩上界", ("deviation_ma60_pct",), lambda v: v <= 3, "偏离<=+3%"),
        defined("bullish_week", "bullish_definition")),
        Action("entry", .2, stages=(2,)), "第二档总资产增量20%")
    add("ENTRY_THIRD", (normal_base, slope2, monthly,
        fixed("三档未执行且未永久关闭", 3 not in p.stages and not p.third_disabled,
              "月线向下记录后，本轮第三档永久关闭"),
        defined("break_bear_rally_high", "bear_rally_high_definition"),
        defined("volume_breakout", "breakout_volume_definition"),
        confirmed_numeric(s, policy, "pe_definition", ("pe_percentile",), lambda v: 0 <= v < 60, "PE分位<60%")),
        Action("entry", .3, stages=(3,)), "第三档总资产增量30%")
    add("ENTRY_CATCHUP", (no_base, slope2, monthly,
        defined("missed_first_nonbullish", "catchup_definition"),
        defined("two_weeks_above_ma60", "effective_break_definition")),
        Action("entry", .7, stages=(1, 2)), "因第一档未收阳错失后，连续2周站稳合并70%")
    restore_due = (p.restore_due is not None and
                   s.as_of.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat() == p.restore_due)
    add("P3_RESTORE", (
        fixed("可补回", p.pending_restore_weight > 0 and p.restore_count < 2 and restore_due,
              "仅上次25%减仓的次周结算，最多2次"),
        numeric("收回10周线", ("week_close", "week_ma10"), lambda c, m: c >= m, "周收盘>=10周线"),
        defined("restore_allowed", "restore_definition")),
        Action("restore", p.pending_restore_weight), "补回前次实际减仓权重；收回定义及入场滤网适用性待确认")
    out.append(RuleResult("ENTRY_FOURTH", 4, Status.UNDEFINED, (), None, "D1：原文第四档未定义"))
    return tuple(out)
