# Phase6.5 缺失数据只读审计

审计日期：2026-11-03。范围：`strategy/features.py`、`rules.py`、`evaluation.py`、`types.py`、`engine.py`，以及回放的特征消费路径。以下发现保留独立审阅时的基线证据和行号，最终修复处置见文末；不是对修复后代码仍逐条存在这些问题的声明。

## 结论与证据边界

发现特征层 UNKNOWN→False 和日内坏值被周期聚合吞掉的问题；基础三值逻辑及显式缺周期后的指标重新预热在已检查场景中正确。不能因此给缺失数据链路整体 PASS。

独立审阅通过内存合成数据复现问题；主执行者随后新增实际回归及真实缓存回放。合成异常测试与真实资金研究严格分开，最终证据见文末和机器清单。

## 确定发现

### M01 / P2：特征生成器把不可判定写成 False

位置：`src/spear_shield/strategy/features.py:125`、`:150`、`:316`、`:324`。

| 内存输入 | 实际输出 | 问题 |
|---|---|---|
| 当前 OHLC/MA60 有效，但仅有一根周线 | `two_weeks_above_ma60=False` | 两周历史不足被表述为不成立 |
| 前周 C>MA60 且 C<=O，但前周 `vol_pct52=NaN`；两周 MA60 均有效 | `missed_first_nonbullish=False` | 缺量能分位被 `and _finite(...)` 压成 False |
| prepared 当前周 `close=NaN, ma10=NaN` | `week_close=None`，`restore_allowed=False` | 同一快照同时承认缺价却给出确定否定 |

`break_bear_rally_high=bool(x.close > rally)` 也缺少两操作数的有限性检查；NaN 比较返回 False，此项为静态定位，未单独运行触发第三档的全链路。

最小建议：必要输入不齐时不生成该事实或生成 None；可判定 False 才写 False。不要把所有有缺项的 AND 都强制 UNKNOWN：例如已知一个必要条件为 False，仍可合法短路成 False。修复应逐项保持现有三值逻辑与冻结门槛。

影响边界：若另一数值条件已使规则缺失，当前未必立即错误成交；但这些 False 会丢失缺失原因，并可被规则组合、事件解锁逻辑当成已知否定。不得据此声称所有当前收益均受影响。

### M02 / P1：日期完整不等于 OHLCV 完整，NaN 被周/月聚合掩盖

位置：`features.py:44`、`:56`、`:59`、`:71`。

`settled_bars` 只核对日期集合；pandas 的 max/min/sum 跳过 NaN，周期内中间交易日的 close 未参与最终收盘选取。结果可能五字段全部有限，`complete_segment_indicators` 无从重置预热。

复现：从 2022-01-03 起生成 700 个工作日，所有价格 O/C=100、H=101、L=99、V=1000，完整独立日历。把第 330 行（周内非最后一天）的 close 改成 NaN，聚合完成周后 `bars.close.isna().sum()==0`。同一天直接删行则正确得到一个缺失周期。

最小建议：聚合前校验每个预期交易日 OHLCV 全部有限、日期唯一及 OHLC 关系；不合格周期保留整根 NaN 并记录原因，沿用现有重预热算法。不要补值或压缩周期。仅 `.notna()` 也不足以拒绝 inf。

信号指数路径直接读取研究快照，不经过 `backtest.engine.validate_market` 对 ETF 执行行情的有限性校验；不能用后者证明本路径已防住坏值。

### M03 / P2：形态回溯跨越缺口的约束不一致

位置：`features.py:164` 至 `:185`。

双顶只要求最近 9 根 close 非缺失，却在最近 52 根 high/low 上搜索。第 10 至 52 根中的缺口不隔离，max/min 仍可忽略 NaN，以缺口两侧数据形成候选颈线。最近 9 根 high/low 也没有独立有限性检查。

这是静态路径发现，未证明本轮真实数据实际产生错误双顶。最小建议：只在不跨缺口的有效连续段内计算，输出所用区间和候选锚点；缺口导致不能确认时保持 UNKNOWN。候选历史不足应判 False 还是 UNKNOWN 属于定义边界，只记录，不在本轮自定最小观察窗或新门槛。

## 已核实的正常行为

1. `evaluation.py:45/54` 的 AND/OR 使用三值逻辑：False AND UNKNOWN=False、True OR UNKNOWN=True 合法；不能误报为把 UNKNOWN 当 False。`compare` 拒绝 bool/非有限数，`consecutive` 要求两个有限数。7选5按已知真与未知数量确定结果，五个已知真足以触发，不应要求所有组件齐全。
2. `types.py:51` 的 Snapshot.get 对缺键、未可用、过期、Python float 非有限值返回 None；这不保证所有容器、numpy 标量或字段语义自动验证，数值规则另有 `number` 守卫。
3. `engine.py:52`、`:93` 对更高优先级风险未知/入场前风险未知实施阻塞；盘中 ATR 是独立入口，不能从周线入口的阻塞推论现实没有保护单。
4. 显式缺一交易日生成 NaN 周后，后续连续完整段重预热：MA60 首值为段内第60根、斜率第61根、ATR14 第14根。复现缺口计数为1；未发现递推指标永久被污染。无交易整周不造 K 的现有口径不改。
5. `strategy_replay.close` 仅在规则状态为 CLEAR 时移除 `risk_latched`，真实 UNKNOWN 本身不会解锁；上游伪 False 仍需要排查。

## 最小复现入口

在仓库根目录，以 `python -B -` 执行以下 Python，无需修改文件：

```python
import sys
sys.path.insert(0, 'src')
import numpy as np
import pandas as pd
from spear_shield.strategy.features import candle_features, settled_bars
from spear_shield.strategy.operational import operational_policy
from spear_shield.backtest.models import TradingCalendar

p = operational_policy()
w = pd.DataFrame(dict(open=[100.], high=[102.], low=[99.],
                      close=[101.], volume=[100.], ma60=[100.], ret=[1.]))
print(candle_features(w, p)['two_weeks_above_ma60'])  # 实测 False
d = pd.bdate_range('2022-01-03', periods=700)
x = pd.DataFrame(dict(date=d, open=100., high=101., low=99.,
                      close=100., volume=1000.))
x.loc[330, 'close'] = np.nan
cal = TradingCalendar(tuple(d.date), 'audit synthetic', True)
now = d[-1].tz_localize('Asia/Shanghai') + pd.Timedelta(hours=16)
print(settled_bars(x, cal, now, 'week').close.isna().sum())  # 实测 0
```

## 本轮只记录的定义与审计缺口

- 第四档保持 UNDEFINED；股债分母/尺度、IV、PE/PEG 的身份与发布时间缺口不可用代理或临时阈值填补。配置 approval 不等于数据可用。
- 以 `docs/strategy/operational_definitions.md` 最终节及当前 policy 为冻结基线；文档早段有旧快照/冲突说明，不用旧段覆盖最终选择。峰值采样的已有周收盘口径见另一审计文档。
- `strategy_replay.py:383` 的 `missing_inputs` 固定枚举6项，不能代表所有缺失；例如缺成交后生命周期、MA、形态锚点、风险预算字段不在表内。`unresolved_rules` 又没有逐条件缺键/过期/未批准原因。
- 建议最少审计字段：每条条件的 value、inputs、pending_definition、缺失原因；所用连续段起止/完整根数/缺口日期；数据时点 observed_at/available_at/valid_until。保留现有三值状态，不新增策略行为。

## 最终处置（主执行者补充）

- M01 已修复：必要值不足保留 None，保留合法的三值 AND 短路；MA10 补回/突破比较先检查有限性。没有把所有混合条件一概改 UNKNOWN。
- M02 已修复：聚合前检查逐日 OHLCV 数值、有限性、正价、非负量、价位几何及日历重复/缺日；有坏值则整个周期 NaN，并按现有窗口重新预热。
- M03 已修复数据资格部分：双顶使用的原有回看段有缺失 high/low/close 时不生成确定形态；不改变形态阈值或补造新定义。双顶形态算法本身仍无针对性测试，不将此修复当作完整算法验收。
- 每条周规则新增条件表达式、输入键、TRUE/FALSE/UNKNOWN 和待确认定义，GUI 显示判定完整性。特征生命周期和全部缺失原因的统一分类仍有缺口。
- 新回归覆盖周内 NaN 不被吞掉、60 周重新预热、两周不足/缺量 UNKNOWN。完整最终测试 283 passed、1 strict xfailed、9 warnings；真实回放经济指纹与修复前完全相同。

IV、股债、PE/PEG 以及历史实际发布时间/修订数据仍缺，条件不会因配置非空而合格。真实 146 周记录保存在新报告中，可见核弹条件 UNKNOWN 且未发出核弹进攻。详见 [回放证据](manifests/replay_evidence.json) 与 [最终报告](audit_report.md)。**缺失链路整体仍 PARTIAL。**
