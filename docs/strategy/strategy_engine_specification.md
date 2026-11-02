# Phase 4 策略引擎规范

规则版本：`v7.3-phase4.1`。执行范围见 `docs/development/phase4_task.md`。
业务来源只使用 v7.3 原文与负责人 D1–D5；测试夹具中的 approval 字符串不构成正式确认。

## 输入、单位、时间

- `Snapshot`：as_of（带时区）、facts、weekly_final（默认False）。
- `Evidence`：value、source、observed_at、available_at、valid_until。
- `available_at <= as_of <= valid_until` 才可读；缺失、NaN、Inf 不作有效数值。
- 率统一使用百分数：`0.1`=0.1%、`8`=8%；Z 无量纲；权重使用0–1。
- `build_snapshot` 只接收前复权且已结算、当时已发布的周/月数据，必须有 source/available_at/is_final。
- 日期标签唯一、升序，每周/月只有一根bar；整周/月缺口重置预热。最近应结算日期由交易日历传入，旧bar不能冒充本周。
- 完整日历周/月缺失不压缩为“连续两期”；盘中入口只处理P1 ATR。
- 原始OHLCV和发布时间快照写入 `week_input_history` / `month_input_history`，随审计记录保存。
- Phase 2 仓储读取缺少历史发布时点、已结算标记和时点复权版本，**不能直接无条件进入策略**。适配层须补齐经验证的元数据；没有时点版本时，不宣称历史回测已无前视偏差。
- 不设置“本周五就是最后交易日”或“下一周=7天后”等日历假设。调度和成交价属于后续阶段。

## 宏观计算

| 函数/输入 | 公式 | 预热及限制 |
|---|---|---|
| 周/月MA60斜率 | `(MA60_t/MA60_(t-1)-1)*100` | 首值需61根，连续2值需62根完整bar |
| style_zscore | `(R_t-mean(R,156))/std(R,156)`，R=创业板/红利 | ddof=0/1、含不含当期均须显式传入；分别需156/157根；零标准差NaN |
| historical_percentile | `count(历史<=当前)/window*100` | 明确window、含当期；不足/缺失NaN；PE和IV不自行定年限 |
| ratio(percent=False) | 分子/分母 | 日期精确相同、单位已统一；分母<=0返回NaN，不填补 |
| 两融水位/交易占比 | ratio(...,percent=True) | 分子分母的正式定义、单位、发布时间需负责人确认 |
| 股债性价比 | 沪深300全收益/二级债基 | D3未确认；不接入任何代理 |

`IVProvider` 仅定义历史接口，不含付费或估算实现。温度计返回五个独立维度、公式、阈值、来源与时间，历史由证据/审计查询提供；缺IV/股债时 `complete=False`。
月线方向按原文斜率>0战略做多；周线方向规则未明确，矩阵只接收经确认的 `week_direction_up`。

## 规则覆盖和阻塞

| ID | 判定/动作 | 默认限制 |
|---|---|---|
| P0_TREND | 周斜率连续2周<0 OR 月斜率连续2月<0；全清 | 有完整证据即可判定；空仓时维持防守、禁止建仓 |
| P1_FALSE_BREAK | 周收盘<MA60；清空 eligible_lot_weight 指定的已买入批次 | 批次权重须来自账户层，不猜全仓 |
| P1_TIME | 建仓后4周收盘<=建仓周高、每周振幅<4%、累计±3%；减半 | 建仓完成时点与四周窗口需确认；rows=(高,低,收,前收) |
| P1_ATR | 最大下跌价差>2*14周ATR；盘中减半 | 最大下跌基准和ATR时点待确认，不能把百分数和价格ATR相比较 |
| P2_STYLE | Z>2 AND (长上影 OR 缩量滞涨)；减半 | Z和形态定义待确认 |
| P2_TOP | 原文7项至少5项为真；减半 | 未知不计真也不当False；5个已知真已充分，无须降低分母 |
| P2_MARGIN | 两融占比>确认红线 AND 顶背离；减30% | 红线必须明确为2.3–2.5中的一个值，口径/背离需确认 |
| P2_MARGIN_TURNOVER | 两融交易占比>10% AND 顶背离 | **仅预警**，原文未指定交易幅度，不产生动作 |
| P3_MA10 | 浮盈>30% AND 收盘<MA10；减25% | 数字条件可直接算，仍需通过更高优先级裁决 |
| P3_DOUBLE_TOP | 第二顶 AND 52周量分位<=30；减半 | 双顶算法待确认 |
| P3_NECKLINE | 跌破颈线；全清 | 颈线算法待确认 |
| P3_TRAILING | 浮盈>100% AND 回撤8%；全清 | 浮盈/峰值回撤语义待确认 |
| P3_STALL | 浮盈>120% AND 放量滞涨；全清 | 滞涨定义待确认 |
| ENTRY_FIRST | 连续2周斜率>=0.1、月斜率>0、有效站上、收阳、量分位>=60；50% | 有效站上/收阳需确认 |
| ENTRY_NUCLEAR | 第一档条件+Z<-2+股债极值+IV(>95且>80)+两融出清；100% | 必须有实际Z/股债比值/IV分位/两融数值；D2/D3当前使其不可用 |
| ENTRY_BEAR | 熊市第一档20% | 与月线前置条件的矛盾需确认 |
| ENTRY_FAST | 周涨>=8、量分位>=60、PE分位<50；50% | 仅豁免月线；与熊市20%关系待确认 |
| ENTRY_SECOND | 已建底仓+回踩偏离<=+3%+收阳；+20% | 回踩定义/允许下探幅度需确认；已执行不重加 |
| ENTRY_THIRD | 放量突破上一熊反高点+PE分位<60；+30% | 高点与放量需确认；三档关闭标志不可自动复位 |
| ENTRY_CATCHUP | 第一档因未收阳错失后，连续2周站稳；70% | 时序及站稳定义需确认 |
| P3_RESTORE | 仅次周收回10周线，补回先前实际减仓权重；最多2次 | 收回及入场滤网关系待确认；日历结算日必须显式提供 |
| ENTRY_FOURTH | 无动作 | D1：未定义 |

所有入场还检查：核弹未锁、两融红线、单笔风险预算。单笔3%–5%未指定止损价与最终阈值，不默认当作通过。
建仓增量按总资产；减仓按当前权益仓位比例。超100%返回blocked，不自动裁剪。

## 三值判定与裁决

`Condition.value` 为True/False/None。AND有False即False；否则缺失为None；OR有True即True；否则缺失为None。
`RuleResult` 保存条件名称、输入key、表达式、未知定义、状态和动作。状态为触发/未触发/数据缺失/待确认/未定义。

P0>P1>P2>P3；只选最高级一项。多个同级动作触发时返回conflict，不私自取最大/相加。只有预警而无交易动作的项不参与交易优先级。
若更高级不可判定，则低级动作保留在结果里，但总裁决blocked。所有风险检查不完整时不新增权益。
核弹替代常规第一档（原文已明确），其他入场路径冲突返回conflict。完整周线裁决入口拒绝盘中数据。
盘中ATR入口会服从输入中已确认的P0裁决；没有最终周线时只评估盘中ATR，不声称完成周线风险审核。

## 确认定义契约

`Policy.approvals` 是 `定义名 -> 负责人确认记录引用`。默认空字典，生产代码中不内置任何假批准。
`Policy.parameters['margin_redline_pct']` 必须是已确认的2.3–2.5范围数值。

定义名可在 `strategy/rules.py` 的 `defined` / `confirmed_numeric` 调用处查阅。主要包括：

- 数据：signal_series_definition、zscore_definition、iv_definition、equity_bond_definition、equity_bond_extreme、margin_definition、margin_redline、margin_clear_definition、pe_definition。
- 建仓：effective_break_definition、bullish_definition、retest_definition、bear_rally_high_definition、breakout_volume_definition、bear_precondition_conflict、fast_bear_precedence、catchup_definition、single_trade_risk_definition。
- 风控：entry_completion_definition、atr_drawdown_definition、candle_definition、stall_definition、bottom_definition、above_ma30_definition、volume_baseline_definition、rsi_definition、divergence_definition、double_top_definition、profit_drawdown_definition、restore_definition。
- 展示：week_direction_definition、defense_fuse_definition。

模糊形态以带来源/时间的布尔证据接入；本阶段不冒充已经实现未确认的自动形态识别算法。

## 防守与仓位状态

防守内部比例严格按原文20/70/10、60/30/10、80/10/10。提供与实际防守权重的偏差。
熔断把红利减半，释放部分记 `unallocated`，短债/货币去向未确认，不输出伪完整可执行组合。
防守端内部比例如何映射到进攻尚未满仓时的总资产比例仍待确认；本接口标明 scope=defensive_sleeve。

`confirm_execution` 只接受绑定当前Position的actionable裁决。回执ID重放幂等；状态变化后旧裁决禁止执行。
Position保存entry_mode，熊市20%和快速通道50%不默认为常规底仓，不自动适用后续加仓。
核弹成交锁定阶梯；已执行档位不重复；第三档关闭后不自动复位；MA10减仓记录实际减仓权重和日历指定次周日期；补回最多2次。
此状态机是按计划完整模拟成交的权重状态，不处理部分成交、成交价、费用和持仓估值（后续阶段）。

## 持久化与调用

`run_research(session, snapshot, position, policy)` 返回裁决、温度计、矩阵、防守、audit_id与observed_position。
服务将负月斜率写入第三档关闭标志；调用者须保留observed_position，并用该状态确认后续模拟回执。单独调用引擎时，调用者先用observe_month更新此标志。
调用方 `session.commit()` 才提交。`strategy_audit` 以内容SHA256主键存储输入/参数/确认记录/状态/全部规则结果/分析；相同内容幂等。
`load_history(session, limit=100)` 按UTC时间降序查询；重启SQLite仍可读取。建表为增量create_all，不删除既有行情表。
没有券商连接或自动订单操作。GUI接线在Phase 5，周报/回测尚未实现。

## 数值验证与复现

- 比值1..156：均值78.5、总体方差 `(156²-1)/12`；第157点对前156周的Z与手算一致。
- 65根收盘101..165：末期MA60=135.5，前期134.5；斜率 `100/134.5`（%）。
- 量分位等于60符合“前40%”；P0斜率等于0不符合<0；IV恰95/80不符合恐慌。
- ATR跌差等于2倍不触发；横盘振幅恰4%不触发；累计恰±3%包含。
- 0.8权益减25%=0.6，待补回0.2；回执重复不再减仓。

测试命令与实际通过数量见 `docs/development/phase4_results.md`。
