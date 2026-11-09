# Phase6.5 回测完整性只读审计

审计日期：2026-11-03。审查 `backtest/{engine,strategy_replay,reporting,models,metrics}.py`、`ui/pages/backtest_center.py`，并追踪策略引擎、成交状态机和定义文档。以下为独立审阅的基线发现，保留复现证据；主执行者的修复、回归及实际回放结果见文末。未改变冻结参数。

主执行者已重跑 2024-01-02..2026-10-30，并保存修复前基线与修复后独立报告。基线描述不代替新一轮实测，也不认证完整策略。

## 优先处理的确定问题

### B01 / P1：风险动作被防守再平衡容差吞掉，并留下虚假 queued

位置：`src/spear_shield/backtest/strategy_replay.py:441` 至 `:456`。

先写 `pending`/`queued_risks`，随后对所有动作应用 0.005 权重偏差过滤。该过滤注释虽称“防守再平衡”，实际也覆盖 P0 和其他进攻风险减仓。

实测：持仓0.1%、stages=(1,)、P0连续两周负斜率；防守计划在合成数据中不执行。`close(2024-01-05)` 返回 None，却留下 `queued_risks={'P0_TREND'}` 及 pending 键。2024-01-12 条件仍真时为 `no_action`。既无 Target 交给引擎，也无回执可释放 queued。

最小建议：0.005 仅用于无策略动作的 `DEFENSE_DYNAMIC`；实际返回 Target 后才登记 queued/pending。记录 `target_emitted` 和未下单原因，不改变0.005或任何策略参数。

### B02 / P1：ATR止损后旧混合挂单可以重新买回进攻资产

位置：`backtest/engine.py:320` 至 `:461`、`:462` 至 `:516`。

pending 目标执行后，stop 可以继续减仓，但 pending 未失效/重裁决。只要另一资产延期，第二天按原目标权重重新买入；策略桥的风险锁存不作用于已在引擎中的旧目标。

实测，初始1000、费/滑点为0、T+1启用，三天 O/C=10：

| 日期 | 事件 | 159915数量 |
|---|---|---:|
| 2024-01-02 | 初始买100份 | 100 |
| 2024-01-03 | 旧目标80%进攻/20%防守；563020停牌，先卖20份进攻 | 80 |
| 同日 | 预置止损线8、low=7，ATR卖40份 | 40 |
| 2024-01-04 | 防守恢复；旧目标自动重试，买回进攻33份，同时买防守18份 | 73 |

止损价8导致权益变化，故买回量为33而非40。没有新策略入场信号。

最小建议：真实保护卖出后冻结/取消旧目标中增加进攻风险的剩余部分，记录取消原因；需要重新裁决后才允许风险增加。若仍执行原目标防守腿，必须保证它不会带回已止损进攻仓位。具体取消整篮子还是仅剩余进攻腿存在执行语义选择，本轮只记录，不擅自落地新规则。

### B03 / P1：部分风险减仓后取消，旧补回额度未失效

位置：`strategy_replay.py:126` 至 `:179`；对照 `portfolio/state.py` “任何新的减仓使此前补回计划失效”。

实测：Position权重0.8，已有 MA10 补回20份、due=2024-01-12；P2_STYLE 实际卖10份但整目标 pending，随后 superseded。结果 `risk_latched={'P2_STYLE'}` 正常保留，但 `restore_quantity=20`、restore_due仍原值。新的实际减仓没有同步废弃旧补回计划。

原因：部分成交只设置 risk_latched；补回清理在整篮子 completed 分支内。最小建议：以实际新增风险卖出回执立即使旧补回计划失效，不能等其他腿完成；对 P3_MA10 自己新建补回额度的完成边界单独记录，避免重复计量。

### B04 / P2：取消部分建仓后持仓存在，生命周期无法完整审计

位置：`strategy_replay.py:138` 至 `:169`、`:244` 至 `:299`。

实测：ENTRY_FIRST 计划50%，买10份后 pending，再 superseded；下一周以实际数量/市值回填后，Position.attack_weight=0.1，但 `stages=()`、`entry_mode=None`、`entry_day=None`，open_lots有1笔。常规加仓要求第一档/entry_mode，无底仓要求attack_weight=0，两条路径均不满足；时间止损和建仓后底部特征也缺起点。

不能把“部分建仓不确认整档”本身判为错误：最终定义明确只有完整目标且有真实进攻成交才确认档位。本问题是留下真实风险敞口却缺少足够的未完成生命周期审计。最小建议先记录 `partial_entry`、累计数量、首次实际成交日、未完成/取消原因及相关规则阻塞原因。是否、何时把部分建仓认作“部署完成”属于定义歧义，本轮不提升档位、不自创恢复流程。

同样，若进攻腿先完成、防守腿延后，entry_day取最终整目标完成日；这与当前“完整部署”选择一致，但必须同时留首次实际进攻成交日，避免把暴露期间隐藏掉。

## 复现方式

B01/B03/B04 使用现有合成 fixture 的纯构造函数（不执行 pytest），避免创建审计测试文件：

```python
import sys, runpy
sys.path.insert(0, 'src')
from spear_shield.strategy.types import Position, Action
from spear_shield.backtest.models import Target
t = runpy.run_path('tests/strategy/test_replay_regressions.py')
r = t['replay'].__wrapped__()
r.position = Position(.001, stages=(1,), entry_mode='normal')
r.snapshot_factory = lambda s,p: t['snapshot'](s.as_of, week_slopes2=(-1.,-1.))
print(r.close(t['instant']('2024-01-05'), {}, t['row'](.1,100.,10000.)))
print(r.queued_risks, list(r.pending))
r.close(t['instant']('2024-01-12'), {}, t['row'](.1,100.,10000.))
print(r.audit[-1]['decision'])  # None / queued P0 / no_action

r = t['replay'].__wrapped__()
r.position = Position(.8, stages=(1,), entry_mode='normal',
                      pending_restore_weight=.2, restore_due='2024-01-12')
r.restore_quantity = 20.
d = t['decision'](r.position,'2024-01-05','P2_STYLE',Action('reduce',.5),2)
target = Target(d.as_of, {'159915':.4}, 'audit-reduce', d.as_of)
r.pending[target.reason] = d
sold = t['fill']('sell',10.)
r.execution(t['receipt']('2024-01-08',target=target,trades=[sold],
                        quantity=70.,cost=7000.,completed=False,status='pending'))
r.execution(t['receipt']('2024-01-09',target=target,target_trades=[sold],
                        quantity=70.,cost=7000.,status='superseded'))
print(r.restore_quantity, r.position.restore_due, r.risk_latched)
# 实测 20.0 / 2024-01-12 / {'P2_STYLE'}
```

B02 使用3日 `MarketData`、2个 `Target` 与只在第二日返回的 `ProtectiveStop('159915',8,.5,首日15:30,'ATR synthetic')`；所有 bar H=11/V=1000，第二日159915 L=7，其余L=9；563020第二日 suspended=True。初始目标首日前15:30发出；80/20目标首日15:30发出。复现参数独立于正式 policy，未改任何冻结配置。

## 风险事件与峰值：正确部分及限制

- 已检查的风险锁存正常路径：部分风险卖出后即锁存，superseded不丢失这次卖出；UNKNOWN不解锁，CLEAR才解锁。B01/B02/B03说明“锁存正确”不等于执行链完整。
- queued/latched 仅为 rule_id 集合，输出回执 `strategy_replay.py:197` 未保留target/reason、累计进攻成交、取消原因关联、事件/cycle ID及锁存前后状态。trades/orders可部分反推，但不能直接证明一次风险事件的已请求/已执行/未完成数量。最小建议加这些审计字段，明确 canceled ≠ filled；engine的 superseded回执 `completed=True` 仅表示终止，不能单独当作成交完成。
- 峰价与历史峰值浮盈分开保存，加仓没有按新成本重估旧峰值、减仓不重置峰值，这符合冻结定义。实测前周price190/cost100、下周high220/close180，输出peak_profit约90%、drawdown_8=False、peak190。**这不是确定bug**：定义文档第239/243行明确采用完成周浮盈和周收盘峰值；不能为了捕获220擅自切换日高/盘中峰值。报告应注明采样频率，禁止称盘中峰值回撤保护。
- 时间窗口在 `strategy_replay.py:353` 仅按4行数值有限就标记已检查；若其他必要字段/规则状态仍UNKNOWN，可能把窗口消费掉。此为静态风险，未单独复现；最小建议记录窗口所需证据与最终可判定状态，再核实，不改4周期限。

## 手续费、分红与资金对账

### 已运行的合成对账

四资产3日场景，初始10000，单边fee=0.001、slippage=0.002；四资产各25%初始买入，第三日全部卖出。下表资产收益由成交净流量和末值独立重建，不从总收益分摊：

| 资产 | 本场景净损益 |
|---|---:|
| 159915 | 481.566996 |
| 563020 | 233.313498 |
| 511360 | -14.940000 |
| 511990 | -262.136496 |
| 合计 | 437.803998 |

实际终值10437.803998，末现金同值；合计与权益增量差约1.25e-12。手续费20.398002、滑点成本40.798。每资产价格依排序159915/511360/511990/563020分别为[10,11,12]/[10,10,10]/[20,19,18]/[10,12,11]；本场景无分红。手续费已在现金与买入成本中计入，滑点已在成交价格中体现，归因时不能再次扣一遍。

原价事件场景：1000买100份@10，次日除息至9，每份现金1，第三日支付并卖出。三日权益均1000；应收为0→100→0；末现金1000；卖出 dividend_pnl=100、realized_pnl=0。确认该基本路径未丢失应收或重复记分红；不证明四资产实际公司行动覆盖完整。

### B05 / P1（验收证据缺口）：收益只有总数，缺四资产/现金归因

位置：`backtest/engine.py:518`、`:585`，`backtest/reporting.py:19/53`，`ui/pages/backtest_center.py:250/303`。

curve保留现金/应收/数量/权重，trades有fee/slippage/realized_price_pnl/dividend_pnl，JSON还含输入行情，原则上可重建；但metrics、HTML和UI没有各资产收益归因或现金对账，UI仓位图也没有现金线。进攻0笔/防守138笔无法说明利润来自哪只资产、分红、持仓浮盈还是现金残留。

主 agent 新真实运行至少给出四资产逐项及现金/应收项，按以下恒等式核验（不能仅把三只防守合成一行）：

```text
V_s,end = Q_s,end * Close_s,end
CF_s = Σ卖出成交金额 - Σ买入成交金额 - Σ双边手续费
D_s = 归属于s的本期现金分红权益（已付+期末应收，按事件计算）
P_s = V_s,end + CF_s + D_s                 # 本回放初始各资产零持仓
Equity_end = Cash_end + ΣV_s,end + Receivable_end
Equity_end - Initial_cash = ΣP_s + 现金独立收益 - 其他独立费用
```

现金余额是终值组成，不可作为利润再加一次。原价现金分红从除息确认权益，付款只是应收转现金；不得以卖出时分摊的 dividend_pnl 再累计同一分红。qfq_research禁叠加现金分红事件，因此D_s在该模型中为0，隐含价格调整效应归入研究单位价格收益；不能把它称真实分红再投资总收益。当前现金无独立计息逻辑，现金收益应显式列0，不用511990替代现金。

最小建议只增加审计字段：每资产末数量/价/市值、买卖总额、费用/滑点、分红已付/应收、已实现/未实现损益、净贡献；现金流水/末现金/应收及两条对账残差。单位统一为金额，贡献分母显式使用初始资本，避免对资产收益率简单相加。

定义冲突记录：operational_definitions.md:241描述分红冲减成本，而原价引擎明确保持成本、另记income_basis并将分红计入卖出损益。基础资金账能自洽，但两种口径会改变profit_pct/止盈武装；现StrategyReplay只支持qfq研究，不能据此断言已在真实回放发生错误。先披露模式与成本口径，不在本轮擅改分红记账。

## 前视、覆盖与可复现性

- 正常执行顺序为公司行动→开盘目标→预置日OHLC止损→收盘估值/信号；收盘信号次日才能执行，Target检查available_at<=signal_at，stop检查known_at<opening。回调副本未暴露当日high/low/close给开盘stop_provider。日OHLC模型的low用于模拟已预置单是否触发，不等于策略提前知道low。
- 实测改变第65根以后的 OHLCV 为10倍，`complete_segment_indicators` 前65根所有列与独立前缀重算完全相同。只证明该合成指标路径的前缀因果性；未认证全部信号或历史复权/宏观修订版本。
- prepared分支按date截断而不逐bar校验available_at；当前Replay固定15:30调用与预先settled_bars相配，不足以认证任意调用者提供prepared或实际历史版本。宏观次交易日09:00是公开研究假设，不是真实发布时间证明。
- `engine.py:577` 的input_sha256仅覆盖执行bars，不含公司行动、交易日历、宏观、指数、policy、配置；report.json整体SHA能保护所保存payload，但并非单一“全部输入指纹”。建议补审计manifest散列及数据版本，不改变原有价格指纹含义。完整缺失宏观输入目前也未逐行封存于结果，源文件/provenance应随本次报告定位。
- `strategy_replay.py:495` 固定coverage_partial=False，未根据请求边界/日历声明计算；实际effective_start/end另有披露。缺乏独立完整日历时不能用这个False作为覆盖认证。主 agent 本次须直接核对请求2024-01-02..2026-10-30与effective区间、四资产逐日覆盖和预热段。
- UI手续费/滑点控件无setValue，Qt默认0；与BacktestConfig默认0.0003/0.0005不同。不是现金计算bug，但新运行必须封存实际request/config，不能根据旧报告推断费用。审计不调整默认值或冻结参数。
- `complete_strategy_validated=False`、研究状态和UI的不完整策略提示应保持。四资产归因正确也不能升级为完整策略：IV/股债/PE/PEG、PIT版本和公司行动等缺口仍需独立审查。

## 最终处置与影响（主执行者补充）

| 编号 | 处置 | 信号/交易/收益影响 |
|---|---|---|
| B01 | 已修复；0.005 容差仅用于无策略动作的防守再平衡，发目标后才登记 queued | 合成小仓 P0 从漏清变为发出全清目标；真实区间无经济变化 |
| B02 | **OPEN / P1**，strict xfail 保存复现 | 实际失败：旧混合目标可在 ATR 后无新信号重买；冻结口径未明确取消整篮子还是进攻腿，未擅选 |
| B03 | 已修复；发生新风险实际减仓后立即清除旧 MA10 补回许可 | 合成部分成交后取消不再保留旧补回许可；真实区间无经济变化 |
| B04 | 仅补审计：实际入场首次日期、累计份额、完成/取消和阶段是否确认 | 不把部分成交晋级，不改建仓规则；跨进程恢复仍未认证 |
| B05 | 新增逐资产/现金净损益及逐日恒等式、HTML/CSV/UI 表 | 纯审计展示，不重复扣费用，不将余额当利润 |

新增测试 `tests/integration/test_phase65_audit.py`；最终全套 283 passed、1 strict xfailed、9 warnings。修复前后独立真实缓存回放的 curve/trades/metrics SHA256 完全相同（`469231dea1c35b0c45c0f8e175ace77bea8ea6161e363b946f19588bc6330e6b`）。这只证明指定样本上无经济变化，不证明所有未来场景等价。

实际重跑 2024-01-02..2026-10-30，初始 100000，费率 0.0003、滑点 0.0005：146 次周审计，138 笔防守成交、0 笔进攻，终值 123662.07099650867。净损益：159915=0；563020=22538.769300077365；511360=1137.40669910122；511990=-14.105002669901253；现金独立收益约0，末现金58.83499650868737。总归因残差约 -8.5e-12，最大日残差约2.0e-11。

完整节点/输入/HTML/CSV 留在 [聚合证据](manifests/replay_evidence.json) 指向的新本地报告目录，基线报告保留。研究单位价格效应不能分解为真实再投资分红收益；没有从本模型捏造分红金额或进攻贡献。**整体仍 PARTIAL，不是完整策略验收。**
