# Phase 6.5 操作定义最终静态审计

审计日期：2026-11-03。主执行者在修改前实际核查：基线 HEAD `5aa322defdbc7fa10f121a39acb92e3bb0950ddb`，main，工作区干净，无原有未跟踪文件。最终口径以 [操作定义第6节](../strategy/operational_definitions.md#2026-11-03-final) 优先。独立审阅者只做静态阅读；主执行者另行完成回归、局部实现修复和证据冻结，见最终报告。

结论：33个非空approval不等于33项完整验收。静态完成 12，部分完成 21，未实现 0，无法验证 0。后两项为0仅表示33键都有可定位代码，不能证明数据完备、跨入口等价或实盘有效。

## 范围、证据和计数

- 已实际阅读特征、规则、仲裁、回放/执行、持仓、宏观/防守、数据加载与对应测试函数体；JSON逐项保存文件、函数、行号和断言范围。33键按operational_policy原顺序一一映射，无重复遗漏。
- 有至少一个局部直接断言的定义 26 项；仅间接 5 项；未发现针对测试 2 项。映射去重测试函数 46 个，参数化不展开、不按定义重复累加。直接涵盖“规则消费手工事实”的局部测试时已明确标注，绝不视为特征生成覆盖。
- 本文的逐项覆盖分类来自独立静态审阅，局部断言不是全面覆盖。主执行者随后实际运行最终测试：283 passed、1 strict xfailed、9 warnings；对应映射测试的执行状态写入机器映射。不能将总通过数当作33项逐一完整验证。
- 配置授权是负责人允许自主查证/选择下的工程定义，非用户逐项指定，非原作者唯一规定，非网页证明最优。所有33项凭据都只引用同一版本与最终节，Policy.approved仅检查非空字符串，不能验证事实数据或细项算法一致性。
- 股债两键不在33内；第四档明确未定义。PEG无独立键且缺合格构造。正式历史IV/PE/公司行动/历史发布时间本轮未独立认证，不能因审计状态有“完成”而认为取得数据。

## 需要优先披露的具体差异

1. **信号资产错位（高）**：StrategyReplay._context的底部涨幅用159915周low；定义要求399006周close低点。横盘四周与部署周高同样用ETF，§32仍要求399006。第6节只把ATR与风险预算明确改为ETF，没有把全部进攻信号改为ETF。
2. **背离比较公式不同（高）**：实际价格>=前26周最高，且当前两融<前26周两融最大；定义是严格价格新高，并与价格前高对应周（并列取最近）的两融比较。已有测试证明历史发布时间隔离，没有检验这两个比较差异。
3. **入场事件/滤网不完整（高）**：补投不保存当时普通条件仅因未收阳而错失的完整事件，观察周数也与未被明确替换的细则不同。补回缺正月线、两周周斜率和站MA60显式滤网。FAST月线未知走50%默认分支，20%封顶只覆盖已知负/零月线。
4. **跨入口行为不同（高）**：旧inputs.build_snapshot允许159915信号且输出当周ATR；回放ATR用前周ETF。run_research在P0尚未成交时可返回active/executable防守计划，回放则用同一目标、先卖后买和现金预算执行。GUI diagnose仍传空事实与默认空Policy，33项配置并未接入该诊断入口。
5. **周期与状态只是内存（高）**：回放新周期重置third_disabled/restore_count，独用confirm_execution保留，两条链不等价。无周期/峰值/熔断/风险事件的跨进程恢复；防守熔断额外要求创业板同跌，较§28收紧且第6节未明确替换；也未按§28锁存轮次。不能把构造新Position视为已恢复历史。
6. **宏观输入资格不足（高）**：PE/IV通用builder对已发布行直接滚动，外传序列未校验交易日完整性、正值或方法/标的；加载器补日只能覆盖其自身路径。两融范围代码只保留集合，任意有限turnover都被标valid；出清生成漏>=0，虽核弹另有非负守卫，错误事实仍存在。
7. **风险执行缺复核（高）**：信号时已按动作增量加成本/压力核预算，次日开盘目标执行未按新价格重新核算；另有仅距离乘份额的重复检查。日OHLC止损模型已披露，不是分钟成交与真实3%损失保证。
8. **最大减仓测试不证明同级分支（高）**：test_delegated_same_priority_is_single_largest_action实际断言P0_TREND，P0仅一候选。无授权最大减仓/同量注册顺序直接断言；回放eligible_lot_weight对有lot直接给全进攻权重，未逐批资格换算，T+1可卖量不参与仲裁。

## 配置是否进入执行链

29个参数中 9 个在operational.py之外无精确键常量消费者。扫描范围为src全部Python，随后结合已读函数确认；不把metadata整包输出当执行读取，不把参数名相同的函数形参当Policy读取。

| 参数 | 冻结值 | 实际消费/缺口 |
|---|---|---|
| `margin_redline_pct` | `2.3` | src/spear_shield/strategy/macro.py:57；src/spear_shield/strategy/rules.py:17 |
| `margin_clear_pct` | `2.0` | src/spear_shield/strategy/features.py:399 |
| `risk_budget_pct` | `3.0` | src/spear_shield/backtest/strategy_replay.py:419；src/spear_shield/strategy/rules.py:223 |
| `signal_symbol` | `"399006"` | 未读取；见下文固定实现/未接链解释 |
| `style_dividend_symbol` | `"H30269"` | 未读取；见下文固定实现/未接链解释 |
| `zscore_ddof` | `0` | 未读取；见下文固定实现/未接链解释 |
| `zscore_include_current` | `false` | 未读取；见下文固定实现/未接链解释 |
| `zscore_window` | `156` | 未读取；见下文固定实现/未接链解释 |
| `iv_short_window` | `252` | src/spear_shield/strategy/features.py:378 |
| `iv_long_window` | `756` | src/spear_shield/strategy/features.py:379 |
| `iv_long_underlying` | `"沪深300股指"` | 未读取；见下文固定实现/未接链解释 |
| `pe_window` | `1260` | src/spear_shield/strategy/features.py:380 |
| `volume_baseline_weeks` | `13` | src/spear_shield/strategy/features.py:136,137 |
| `stall_return_abs_pct` | `1.0` | src/spear_shield/strategy/features.py:144 |
| `low_volume_ratio` | `0.7` | src/spear_shield/strategy/features.py:147 |
| `high_volume_ratio` | `1.5` | src/spear_shield/strategy/features.py:148 |
| `upper_shadow_fraction` | `0.6` | src/spear_shield/strategy/features.py:131 |
| `divergence_window` | `26` | src/spear_shield/strategy/features.py:426 |
| `same_priority` | `"largest_reduction"` | src/spear_shield/strategy/engine.py:64 |
| `entry_precedence` | `["ENTRY_NUCLEAR", "ENTRY_CATCHUP", "ENTRY_BEAR", "ENTRY_FIRST", "ENTRY_FAST", "ENTRY_SECOND", "ENTRY_THIRD", "P3_RESTORE"]` | src/spear_shield/strategy/engine.py:114 |
| `defense_transfer` | `"all_to_511360"` | src/spear_shield/strategy/defense.py:46 |
| `defense_scope` | `"only_when_attack_zero"` | 未读取；见下文固定实现/未接链解释 |
| `negative_month_fast_cap` | `0.2` | src/spear_shield/strategy/rules.py:268 |
| `profit_drawdown_basis` | `"peak"` | src/spear_shield/strategy/rules.py:167 |
| `atr_once_per_week` | `true` | src/spear_shield/strategy/rules.py:92 |
| `third_lock_scope` | `"entry_cycle"` | 未读取；见下文固定实现/未接链解释 |
| `restore_limit_scope` | `"entry_cycle"` | 未读取；见下文固定实现/未接链解释 |
| `risk_budget_method` | `"per_action"` | src/spear_shield/strategy/rules.py:198,213 |
| `risk_gap_stress_pct` | `1.0` | src/spear_shield/backtest/strategy_replay.py:304 |

未读不一概等于“功能完全没做”：signal/style身份由加载器固定；Z主builder硬编码156、不含本周、ddof0；IV加载固定IO文件；周期reset由回放硬编码实现；defense_scope没有约束service的P0提前激活。atr_once_per_week虽在rules读取，stop_provider仍无条件周去重，参数不会控制该执行入口。volume_1_5固定1.5而high_volume_ratio只控制放量滞涨，两者当前数值一致但不是同一配置驱动。

## 逐项映射

下列“直接”只按列出的断言范围计算；例如注入retest=True后断言二档动作，只覆盖消费，不覆盖回踩计算。逐项的source授权性质均为前述工程授权，主依据为最终第6节；每项同时列出补充章节，不采用旧并行快照推翻最终选择。

### 01. 信号序列与指数/ETF分工 · 部分完成

- definition_id：`signal_series_definition`；risk：高。
- source：最终§6优先，补充§6、§18、§21；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/features.py:17` → `settled_bars`；`src/spear_shield/strategy/features.py:192` → `build_operational_snapshot`；`src/spear_shield/strategy/inputs.py:58` → `build_snapshot`；`src/spear_shield/services/research_dataset.py:136` → `load_operational_dataset`；`src/spear_shield/backtest/strategy_replay.py:242` → `StrategyReplay._context`。
- test_file / test_case：
  - **直接** `tests/strategy/test_operational_features.py:71` / `test_entire_missing_trading_week_is_preserved_and_indicator_rewarms`：缺掉有交易整周保留NaN并重新预热。
  - **直接** `tests/strategy/test_inputs_audit_defense.py:83` / `test_signal_basis_not_silently_selected`：旧builder缺approval拒绝；不验证固定399006。
  - **直接** `tests/strategy/test_operational_features.py:84` / `test_future_prices_do_not_change_current_snapshot`：未来价格改变不影响当前已断言字段。
- notes：研究加载器固定399006/H30269，日历聚合已实现；signal_symbol/style_dividend_symbol配置未读。旧build_snapshot仍允许159915。回放bottom及横盘用ETF，见后项；输入缺身份/原生点位强校验，当前历史复权版本未认证。

### 02. 156观测周Z，不含本周、ddof0 · 部分完成

- definition_id：`zscore_definition`；risk：中。
- source：最终§6优先，补充§6、§22；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/features.py:192` → `build_operational_snapshot`；`src/spear_shield/indicators/macro.py:26` → `style_zscore`；`src/spear_shield/indicators/macro.py:18` → `ratio`。
- test_file / test_case：
  - **直接** `tests/strategy/test_macro.py:12` / `test_zscore_known_uniform_sequence_and_prefix`：工具手算156/不含当前/ddof0。
  - **直接** `tests/strategy/test_macro.py:25` / `test_zscore_missing_zero_std_and_length`：工具零方差/缺失。
  - **间接** `tests/strategy/test_operational_features.py:84` / `test_future_prices_do_not_change_current_snapshot`：主builder仅比较前缀不变，未手算Z。
- notes：主builder硬编码156/shift(1)/ddof0，数值与冻结选择一致，但三项zscore配置未读，未调用已测试style_zscore。主builder直接相除未限制红利分母>0，工具ratio会拒绝非正分母；工具按自然连续周拒绝长假整周，而settled_bars不造无交易周。两套实现边界不一致。

### 03. 有效站上60周线 · 部分完成

- definition_id：`effective_break_definition`；risk：高。
- source：最终§6优先，补充§6、§7；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/features.py:114` → `candle_features`；`src/spear_shield/strategy/rules.py:185` → `entry_rules`。
- test_file / test_case：
  - **间接** `tests/strategy/test_rules.py:111` / `test_entry_boundaries_with_explicit_test_approvals`：规则层注入effective=True后验证斜率/量门槛；不验证站上算法。
- notes：effective_above_ma60只算当周C>MA60；§7的两周确认未被第6节另行明确替换，two_weeks_above_ma60另算两周且仅补投使用。只有一周站上的FIRST/BEAR可能提前通过。缺前周MA时two_weeks标False而非未知。

### 04. 当周收阳 · 完成

- definition_id：`bullish_definition`；risk：低。
- source：最终§6优先，补充§6、§8；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/features.py:114` → `candle_features`；`src/spear_shield/strategy/rules.py:185` → `entry_rules`。
- test_file / test_case：
  - **间接** `tests/strategy/test_rules.py:111` / `test_entry_boundaries_with_explicit_test_approvals`：手工注入bullish=True，未断言C与O的计算。
- notes：实际为C>O，等号False，与冻结口径一致。未发现针对阴线/平开平收及相对前收下跌阳线的生成器断言；完成仅指静态算法落地。

### 05. 回踩MA60与3%边界 · 部分完成

- definition_id：`retest_definition`；risk：中。
- source：最终§6优先，补充§6、§9；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/features.py:114` → `candle_features`；`src/spear_shield/strategy/rules.py:185` → `entry_rules`。
- test_file / test_case：
  - **直接** `tests/strategy/test_rules.py:130` / `test_second_and_third_additions_and_third_permanent_disable`：注入retest=True且偏离=3验证二档20%；未测OHLC生成。
- notes：低<=MA60×1.03、收>=MA60，规则偏离<=3已进入链；第6节明确的条件满足。§9前周收>前周MA60未实现，未见最终节明确撤销此条件；均线为0亦无本地防护，未覆盖生成器端点。

### 06. 上一熊市段反弹高点 · 部分完成

- definition_id：`bear_rally_high_definition`；risk：高。
- source：最终§6优先，补充§6、§10；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/features.py:192` → `build_operational_snapshot`；`src/spear_shield/strategy/rules.py:185` → `entry_rules`。
- test_file / test_case：
  - **直接** `tests/strategy/test_rules.py:130` / `test_second_and_third_additions_and_third_permanent_disable`：第三档消费手工突破标志，未测段落识别。
- notes：采用最近已发生连续月斜率<=0映射周段的历史high最大值，第6节已授权该自动算法，不能再按§10旧稿称未批准。仅C>rally，未检查§10独立明确的前周<=阈值首次上穿；段中NaN由max跳过，缺失段可能被压缩；无直接形态生成测试。

### 07. 突破放量52周分位 · 完成

- definition_id：`breakout_volume_definition`；risk：低。
- source：最终§6优先，补充§6、§10；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/features.py:192` → `build_operational_snapshot`；`src/spear_shield/indicators/volume.py:22` → `volume_percentile`；`src/spear_shield/strategy/rules.py:185` → `entry_rules`。
- test_file / test_case：
  - **直接** `tests/unit/test_indicators.py:124` / `test_volume_percentile_boundaries`：工具经验<=、含当前的小窗口手算。
  - **直接** `tests/strategy/test_rules.py:130` / `test_second_and_third_additions_and_third_permanent_disable`：第三档消费手工volume_breakout=True。
- notes：量分位>=60，52周含当前由IndicatorEngine固定调用；无1.5倍暗加条件。放量标志仅在monthly非空分支生成，主链52周边界未直接断言；工具小窗测试不等于主链全覆盖。

### 08. 长上影 · 完成

- definition_id：`candle_definition`；risk：低。
- source：最终§6优先，补充§6、§11；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/features.py:114` → `candle_features`；`src/spear_shield/strategy/rules.py:30` → `exit_rules`。
- test_file / test_case：
  - **间接** `tests/strategy/test_risk_boundaries.py:71` / `test_p2_dominates_p3_without_reduction_stacking`：手工long_upper_shadow=True，仅验证优先级。
- notes：H-max(O,C)占振幅严格>0.60，读取upper_shadow_fraction；第6节优先于§11旧稿>=，不把严格边界报成偏差。无OHLC算法或恰60%直接测试。

### 09. 缩量/放量滞涨 · 完成

- definition_id：`stall_definition`；risk：中。
- source：最终§6优先，补充§6、§11；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/features.py:114` → `candle_features`；`src/spear_shield/strategy/rules.py:30` → `exit_rules`。
- test_file / test_case：空；未发现针对测试，不用fixture中的占位值补计。
- notes：此前13周均量、abs周收益<1%、缩量<0.7、放量>=1.5，参数均实际读取；第6节严格<覆盖§11旧稿<=。缺ret或均量无效不生成。未发现生成及边界直接测试，不能因fixture提供False而称覆盖。

### 10. 26周两融顶背离 · 部分完成

- definition_id：`divergence_definition`；risk：高。
- source：最终§6优先，补充§6、§12；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/features.py:192` → `build_operational_snapshot`；`src/spear_shield/strategy/rules.py:30` → `exit_rules`。
- test_file / test_case：
  - **直接** `tests/strategy/test_replay_regressions.py:438` / `test_divergence_uses_each_historical_week_publication_cutoff`：各历史周available_at截止/晚发布未知；未区分前高对应周与全窗最大值。
- notes：历史发布时间因果对齐已落地；实际C>=历史最高close，margin当前<历史margin最大值。§12要求C严格新高且与价格前高对应周j的margin比较、并列j取最近；第6节只覆盖时间对齐未替换此公式。价格等前高或两融峰不在价格峰时可误判。

### 11. 自动双顶H2/颈线 · 部分完成

- definition_id：`double_top_definition`；risk：高。
- source：最终§6优先，补充§6、§13；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/features.py:162` → `double_top_features`；`src/spear_shield/strategy/rules.py:30` → `exit_rules`。
- test_file / test_case：空；未发现针对测试，不用fixture中的占位值补计。
- notes：第6节已批准52周、首顶左右2根、第二顶当前候选、3%/5%；代码有这些结构。只校验末9周close，52周high/low缺失被max/min跳过；不足9周返回缺失，但局部完整时可把未完整形态证据写False。颈线由遍历最后候选覆盖，未测多候选/缺失/时序。规则当前量分位对当前第二顶相容，不将旧稿延迟确认警告直接报成现错。

### 12. 本轮底部涨幅100% · 部分完成

- definition_id：`bottom_definition`；risk：高。
- source：最终§6优先，补充§6、§14、§21；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/backtest/strategy_replay.py:242` → `StrategyReplay._context`；`src/spear_shield/strategy/rules.py:30` → `exit_rules`。
- test_file / test_case：
  - **间接** `tests/strategy/test_rules.py:71` / `test_seven_of_five_does_not_count_unknown_as_true`：手工rise_from_bottom_100=True验证三值计数。
- notes：实际用ETF159915本轮周low最小值×2比较ETF当前close；§14/21要求399006本轮完成周close最小值。资产与低点字段均不同，min亦可跳过NaN；第6节未改变该项定义。无生成器针对测试。

### 13. 8周至少6周站MA30 · 完成

- definition_id：`above_ma30_definition`；risk：低。
- source：最终§6优先，补充§6、§14；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/backtest/strategy_replay.py:307` → `StrategyReplay.close`；`src/spear_shield/strategy/rules.py:30` → `exit_rules`。
- test_file / test_case：
  - **直接** `tests/strategy/test_rules.py:71` / `test_seven_of_five_does_not_count_unknown_as_true`：注入布尔后的七选五消费；未测8周生成。
- notes：回放使用399006，末8周各自close>ma30计数>=6，ma30须齐全。仅回放close注入，通用builder不生成；未发现恰6/恰MA30的生成测试。

### 14. 1.5倍量基准 · 完成

- definition_id：`volume_baseline_definition`；risk：低。
- source：最终§6优先，补充§6、§11、§14；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/features.py:114` → `candle_features`；`src/spear_shield/strategy/rules.py:30` → `exit_rules`。
- test_file / test_case：
  - **直接** `tests/strategy/test_rules.py:71` / `test_seven_of_five_does_not_count_unknown_as_true`：手工volume_1_5=True，直接验证其计一项。
- notes：shift(1).rolling(13)读取窗口，volume_1_5使用硬编码>=1.5；与冻结值一致，但不读high_volume_ratio（后者只用于high_volume_stall）。额外依赖ret有效才生成量能标志，尚无量基准/端点直接测试。

### 15. 14周Wilder RSI · 完成

- definition_id：`rsi_definition`；risk：低。
- source：最终§6优先，补充§6、§14；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/indicators/rsi.py:19` → `rsi`；`src/spear_shield/indicators/_common.py:13` → `wilder_smooth`；`src/spear_shield/indicators/engine.py:40` → `IndicatorEngine.compute`；`src/spear_shield/strategy/rules.py:30` → `exit_rules`。
- test_file / test_case：
  - **直接** `tests/unit/test_indicators.py:49` / `test_rsi_rising`：period3单边上涨100。
  - **直接** `tests/unit/test_indicators.py:57` / `test_rsi_falling`：period3下跌0。
  - **直接** `tests/unit/test_indicators.py:64` / `test_rsi_flat`：period3平盘50。
  - **直接** `tests/unit/test_indicators.py:72` / `test_rsi_insufficient_length_is_nan`：period14历史不足。
- notes：周线传入RSI14，首14差种子、Wilder递推，规则严格>88。工具方向/预热有断言，无混合涨跌14周手算及88等号主链测试。

### 16. 399006 PE分位 · 部分完成

- definition_id：`pe_definition`；risk：高。
- source：最终§6优先，补充§6；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/features.py:192` → `build_operational_snapshot`；`src/spear_shield/indicators/macro.py:42` → `historical_percentile`；`src/spear_shield/services/research_dataset.py:136` → `load_operational_dataset`；`src/spear_shield/strategy/rules.py:185` → `entry_rules`；`src/spear_shield/strategy/rules.py:30` → `exit_rules`。
- test_file / test_case：
  - **直接** `tests/strategy/test_macro.py:52` / `test_percentile_ties_and_explicit_window`：通用分位小窗，并列<=/是否含当前。
  - **直接** `tests/strategy/test_rules.py:130` / `test_second_and_third_additions_and_third_permanent_disable`：注入PE59.9消费；非PE历史验证。
- notes：1260窗口被读取且不含当前；真实加载器不接PE/PEG，外传pe缺指数身份、剔亏TTM方法、正值、交易日完整性验证。已发布行过滤后按行滚动可能压缩缺日；只有inferred_release_series路径补交易日。PEG未实现合格构造，仅消费任意peg数字，未覆盖披露。

### 17. 短252/长IO756 IV分位 · 部分完成

- definition_id：`iv_definition`；risk：高。
- source：最终§6优先，补充§6、§4、§17；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/data/research_sources.py:219` → `_fetch_task`；`src/spear_shield/services/research_dataset.py:136` → `load_operational_dataset`；`src/spear_shield/services/research_dataset.py:83` → `inferred_release_series`；`src/spear_shield/strategy/features.py:192` → `build_operational_snapshot`；`src/spear_shield/strategy/rules.py:185` → `entry_rules`。
- test_file / test_case：
  - **直接** `tests/unit/test_research_sources.py:118` / `test_qvix_raw_bytes_and_correct_index_columns`：模拟CSV原字节和CYB74/IO20列映射。
  - **直接** `tests/strategy/test_operational_features.py:107` / `test_macro_future_publication_not_seen_and_iv_is_not_return_volatility`：未给IV时保持None。
  - **直接** `tests/strategy/test_engine_workflow.py:63` / `test_iv_strict_panic_boundaries`：注入分位95/80不触发恐慌。
- notes：第6节批准算法而非真实序列，不沿用§3旧未批准说法。窗口实际读取，iv_long_underlying未读；加载器固定文件。已补本地交易日后不缩缺日，但通用builder外传宏观未校验日历/正值/方法或标的，可接受不合格序列。未独立复验本地真实源覆盖；文件记载HTTP/HTTPS失败只作历史说明，无本轮联网结论。

### 18. 两融发布方占比与范围 · 部分完成

- definition_id：`margin_definition`；risk：高。
- source：最终§6优先，补充§6、§5；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/data/research_sources.py:219` → `_fetch_task`；`src/spear_shield/services/research_dataset.py:136` → `load_operational_dataset`；`src/spear_shield/services/research_dataset.py:83` → `inferred_release_series`；`src/spear_shield/strategy/features.py:192` → `build_operational_snapshot`；`src/spear_shield/strategy/rules.py:16` → `margin_entry_check`；`src/spear_shield/strategy/rules.py:30` → `exit_rules`。
- test_file / test_case：
  - **直接** `tests/unit/test_research_sources.py:210` / `test_publisher_margin_report_retains_percent_units_and_scope`：模拟发布方字段2.31、BOARD_CODE保留。
  - **直接** `tests/unit/test_research_dataset.py:37` / `test_lag_assumption_explicit_and_missing_trading_day_stays_nan`：下一交易日09:00假设、缺日NaN。
- notes：最终节明确改采发布方MARGIN_A_RATIO/MARGIN_A_TRADE，不能以未重建三所原始分母单独判违规。范围代码只聚合保存set，未逐观测绑定范围/变更；builder任意有限turnover即valid=True，未核口径、负值与范围，7天陈旧容忍可跨周。历史实际发布时间仍无法由研究延迟假设证明。

### 19. 两融红线2.3% · 完成

- definition_id：`margin_redline`；risk：低。
- source：最终§6优先，补充§6、§23；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/rules.py:16` → `margin_entry_check`；`src/spear_shield/strategy/macro.py:21` → `thermometer`。
- test_file / test_case：
  - **直接** `tests/strategy/test_engine_workflow.py:73` / `test_margin_redline_strict_boundary`：2.3允许、2.3001禁止。
  - **直接** `tests/strategy/test_engine_workflow.py:78` / `test_unknown_redline_cannot_be_replaced_by_boolean`：无数值红线布尔不替代。
- notes：读取2.3且限制2.3—2.5合法；入场<=、红线>，P2另需背离，未变成P0。测试为明确夹具策略，不冒称真实数据验收。

### 20. 两融出清0到2.0% · 部分完成

- definition_id：`margin_clear_definition`；risk：高。
- source：最终§6优先，补充§6、§23；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/features.py:192` → `build_operational_snapshot`；`src/spear_shield/strategy/rules.py:185` → `entry_rules`。
- test_file / test_case：
  - **间接** `tests/strategy/test_engine_workflow.py:45` / `test_full_nuclear_requires_actual_four_dimensions`：手工margin_cleared=True参与核弹，未测数值生成。
- notes：读取margin_clear_pct，但生成式仅value<=2.0缺>=0；核弹另检margin>=0可阻断负值最终动作，仍会输出错误出清事实。无0/2.0/负数生成器测试。

### 21. 熊市20%豁免正月线 · 完成

- definition_id：`bear_precondition_conflict`；risk：中。
- source：最终§6优先，补充§6、§24；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/features.py:192` → `build_operational_snapshot`；`src/spear_shield/strategy/rules.py:185` → `entry_rules`。
- test_file / test_case：
  - **直接** `tests/strategy/test_rules.py:143` / `test_fast_bear_and_catchup_paths`：注入熊市许可，BEAR份额20%；旧fixture FAST50%是另一参数策略。
- notes：BEAR月<=0、周两斜率、有效站上/收阳/量能及风险滤网生效，固定20%。未发现月=0完整主链测试；有效站上算法缺口见对应项。

### 22. 快速熊市封顶20% · 部分完成

- definition_id：`fast_bear_precedence`；risk：高。
- source：最终§6优先，补充§6、§24；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/rules.py:185` → `entry_rules`。
- test_file / test_case：
  - **直接** `tests/strategy/test_operational_features.py:148` / `test_bear_fast_cap_is_20_not_50`：负月线FAST action.fraction=0.2。
- notes：负/零已知月斜率读negative_month_fast_cap=.2，符合最终节（覆盖§24旧禁FAST）。但月斜率未知时走else=.5，FAST条件本身不要求月线已知，可能生成50%动作。该缺失分支与月=0未直接测试。

### 23. 按动作增量核3%风险 · 部分完成

- definition_id：`single_trade_risk_definition`；risk：高。
- source：最终§6优先，补充§6、§26；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/rules.py:185` → `entry_rules`；`src/spear_shield/backtest/strategy_replay.py:242` → `StrategyReplay._context`；`src/spear_shield/backtest/strategy_replay.py:307` → `StrategyReplay.close`；`src/spear_shield/backtest/engine.py:111` → `BacktestEngine.run`。
- test_file / test_case：
  - **直接** `tests/strategy/test_replay_regressions.py:372` / `test_each_entry_and_restore_checks_its_fraction_and_all_cost_buffers`：各动作份额×止损距离+双边成本/压力；缺buffer不通过。
- notes：规则与context真实计算，1个百分点压力有披露。close另有仅距离×份额的重复简化检查；次日开盘成交路径未重新核ETF MA60止损距离与3%预算，可因跳空突破计划预算。§6选择ETF MA60已覆盖旧指数映射疑问，不能再认定无止损定义；真实跳空损失非3%硬保证。

### 24. 错失事件补投70% · 部分完成

- definition_id：`catchup_definition`；risk：高。
- source：最终§6优先，补充§6、§24；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/features.py:114` → `candle_features`；`src/spear_shield/strategy/rules.py:185` → `entry_rules`；`src/spear_shield/strategy/engine.py:15` → `StrategyEngine.evaluate`。
- test_file / test_case：
  - **直接** `tests/strategy/test_rules.py:143` / `test_fast_bear_and_catchup_paths`：注入错失/两周站稳后70%；未验证事件来源。
- notes：第6节允许CATCHUP优先FIRST。实际仅检查紧前一周收<=开、收>MA60、量>=60，未验证该周其他普通条件/当时风险；未持久化错失事件及有效期。当前两周站稳包含错失周，未实现§24所述其后两周；最终节未给明确替代观察长度。无事件级测试。

### 25. 峰值浮盈武装与价格回撤8% · 部分完成

- definition_id：`profit_drawdown_definition`；risk：中。
- source：最终§6优先，补充§6、§29；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/backtest/strategy_replay.py:242` → `StrategyReplay._context`；`src/spear_shield/backtest/strategy_replay.py:75` → `StrategyReplay.execution`；`src/spear_shield/strategy/rules.py:30` → `exit_rules`。
- test_file / test_case：
  - **直接** `tests/strategy/test_replay_regressions.py:310` / `test_peak_survives_buy_without_revaluing_old_peak_at_new_cost`：加仓保留已观察峰值浮盈，不用新成本回估；8%回撤True。
- notes：内存保存价格峰及观测峰值浮盈，全清重置，避免减仓制造净值回撤；规则peak_profit>100。无100/8%端点、减仓保峰与重启持久化直接测试；研究qfq单位已披露，真实公司行动/历史版本未认证，跨进程峰值无法恢复。

### 26. MA10次周按实际份额补回 · 部分完成

- definition_id：`restore_definition`；risk：高。
- source：最终§6优先，补充§6、§27、§30；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/backtest/strategy_replay.py:75` → `StrategyReplay.execution`；`src/spear_shield/backtest/strategy_replay.py:242` → `StrategyReplay._context`；`src/spear_shield/portfolio/state.py:19` → `confirm_execution`；`src/spear_shield/strategy/rules.py:185` → `entry_rules`。
- test_file / test_case：
  - **直接** `tests/strategy/test_replay_regressions.py:287` / `test_restore_budget_tracks_actual_sold_units_at_current_price`：20单位随当前价110换算目标22%。
  - **直接** `tests/strategy/test_engine_workflow.py:90` / `test_restore_exact_next_week_and_maximum_twice`：次周匹配、第二次后拒绝；规则/状态层。
- notes：回放按卖出单位换算，旧confirm_execution独用仍保存历史权重；跨周期reset只在回放首次入场实现，restore_limit_scope未读。规则补回缺月>0、周两斜率>=0.1及C>MA60显式检查，不能用P0/P1未触发代替。部分减仓未整单完成时未建立可补回单位。无生命周期持久化/重启测试。

### 27. 部署完成与固定四周窗口 · 部分完成

- definition_id：`entry_completion_definition`；risk：高。
- source：最终§6优先，补充§6、§27、§32；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/backtest/strategy_replay.py:75` → `StrategyReplay.execution`；`src/spear_shield/backtest/strategy_replay.py:242` → `StrategyReplay._context`；`src/spear_shield/backtest/strategy_replay.py:307` → `StrategyReplay.close`；`src/spear_shield/portfolio/state.py:19` → `confirm_execution`；`src/spear_shield/portfolio/state.py:11` → `observe_month`；`src/spear_shield/strategy/rules.py:30` → `exit_rules`。
- test_file / test_case：
  - **直接** `tests/strategy/test_replay_regressions.py:236` / `test_partial_fill_waits_for_completed_cumulative_receipt`：整目标完成及累计进攻成交才确认、重复回执幂等。
  - **直接** `tests/strategy/test_replay_regressions.py:336` / `test_first_four_week_window_closes_and_later_entry_does_not_reset`：首次四周失败也关闭，后续加仓不重置。
  - **直接** `tests/strategy/test_rules.py:61` / `test_time_stop_manual_values_and_amplitude_boundary`：幅度恰4%不触发。
- notes：回放完成/窗口机制已实现，但四周与entry_week_high取ETF，§32要求399006；day=目标最终完成日，历史最后一笔进攻成交较早时仍等目标完成，属明确选择。third_lock_scope未读：回放新周期重置、独用confirm_execution保留锁/次数；所有cycle事件/峰值为内存，缺重启恢复。

### 28. 共振周方向MA60斜率>0 · 完成

- definition_id：`week_direction_definition`；risk：低。
- source：最终§6优先，补充§6、§22；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/features.py:192` → `build_operational_snapshot`；`src/spear_shield/strategy/service.py:24` → `run_research`；`src/spear_shield/strategy/macro.py:66` → `resonance`。
- test_file / test_case：
  - **直接** `tests/strategy/test_macro.py:59` / `test_matrix`：四布尔象限/未知；不测试周斜率生成。
- notes：builder用>0，已知0归False；service有approval门控。无斜率=0/未知端点集成断言，不能拿矩阵测试证明生成链。

### 29. 防守熔断两周相对下跌 · 部分完成

- definition_id：`defense_fuse_definition`；risk：高。
- source：最终§6优先，补充§6、§28；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/features.py:192` → `build_operational_snapshot`；`src/spear_shield/strategy/defense.py:11` → `defense_plan`。
- test_file / test_case：
  - **直接** `tests/strategy/test_inputs_audit_defense.py:108` / `test_defense_fuse_does_not_invent_bond_cash_split`：注入fuse=True减红利半，不授权转移则不可执行。
  - **间接** `tests/strategy/test_operational_features.py:139` / `test_defense_fuse_allocates_to_short_bond_only_under_delegated_policy`：注入fuse，不验证两周生成。
- notes：实际要求两指数均跌且红利跌更多；§28允许红利跌而创业板涨时计更差，第6节只确定激活/资金执行与转移，没有明确替换相对跌幅公式，故额外要求创业板也跌属于实现收紧。未实现§28防守轮次熔断锁存/退出后重置，连续窗口恢复可立即回补；defense_scope未读，研究服务P0未成交也可active并返回executable计划，回放则受目标卖出与现金预算。无生成器和轮次测试。

### 30. 熔断释放全部转511360 · 完成

- definition_id：`defense_transfer_definition`；risk：中。
- source：最终§6优先，补充§6、§28；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/defense.py:11` → `defense_plan`；`src/spear_shield/backtest/strategy_replay.py:307` → `StrategyReplay.close`；`src/spear_shield/backtest/engine.py:111` → `BacktestEngine.run`。
- test_file / test_case：
  - **直接** `tests/strategy/test_operational_features.py:139` / `test_defense_fuse_allocates_to_short_bond_only_under_delegated_policy`：中间Z档30/60/10，无未分配且可执行。
  - **直接** `tests/strategy/test_inputs_audit_defense.py:99` / `test_defense_exact_thresholds`：三档基础权重边界，非三档熔断全测。
- notes：approval+all_to_511360实际读取，释放量全进短融、货币不变。三档熔断中仅中档直接断言，实际卖出/现金预算链静态可见；P0未成交服务展示语义问题见防守熔断项。

### 31. 同级单一最大减仓及事件锁存 · 部分完成

- definition_id：`same_priority_definition`；risk：高。
- source：最终§6优先，补充§6、§25；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/engine.py:15` → `StrategyEngine.evaluate`；`src/spear_shield/strategy/rules.py:30` → `exit_rules`；`src/spear_shield/backtest/strategy_replay.py:307` → `StrategyReplay.close`；`src/spear_shield/backtest/strategy_replay.py:75` → `StrategyReplay.execution`。
- test_file / test_case：
  - **间接** `tests/strategy/test_operational_features.py:169` / `test_delegated_same_priority_is_single_largest_action`：断言P0_TREND，只有一个P0动作，未进入同级len>1分支。
  - **直接** `tests/strategy/test_rules.py:54` / `test_same_priority_conflict_not_stacked`：无同级approval时P1冲突；非授权最大分支。
  - **直接** `tests/strategy/test_replay_regressions.py:174` / `test_risk_latches_after_fill_rearms_only_on_known_false`：已卖风险锁存、未知不解除、False重武装及部分成交取消。
- notes：max fraction/clear=1、并列注册顺序已实现，与最终节一致，不报旧rule_id排序差异。eligible先按权重换算，但回放eligible_lot_weight对有lot直接用全持仓，未逐lot资格；T+1实际可卖量不参与仲裁。授权最大与并列无直接测试，事件锁存仅内存。

### 32. 入场路径仲裁顺序 · 完成

- definition_id：`entry_precedence_definition`；risk：中。
- source：最终§6优先，补充§6、§24；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/strategy/engine.py:15` → `StrategyEngine.evaluate`；`src/spear_shield/strategy/operational.py:9` → `operational_policy`。
- test_file / test_case：
  - **直接** `tests/strategy/test_engine_workflow.py:84` / `test_entry_paths_conflict_without_invented_precedence`：无授权多入口冲突。
  - **直接** `tests/strategy/test_engine_workflow.py:45` / `test_full_nuclear_requires_actual_four_dimensions`：核弹替代FIRST；缺核弹数据可回FIRST，非完整tuple。
  - **间接** `tests/strategy/test_replay_regressions.py:372` / `test_each_entry_and_restore_checks_its_fraction_and_all_cost_buffers`：只调用entry_rules逐项看预算，没有调用仲裁。
- notes：读取完整tuple，仅已触发动作参与，核弹替代FIRST，注册顺序可审阅。没有直接断言CATCHUP>BEAR>FIRST>FAST>SECOND>THIRD>RESTORE完整次序；完成是静态实现结论，不是全顺序测试通过。

### 33. 前周ETF ATR14冻结、日OHLC止损 · 部分完成

- definition_id：`atr_drawdown_definition`；risk：高。
- source：最终§6优先，补充§6、§15、§31；负责人自主选择授权，非逐项用户指定。
- implementation_file / function：`src/spear_shield/backtest/strategy_replay.py:210` → `StrategyReplay.stop_provider`；`src/spear_shield/backtest/strategy_replay.py:75` → `StrategyReplay.execution`；`src/spear_shield/backtest/strategy_replay.py:242` → `StrategyReplay._context`；`src/spear_shield/indicators/atr.py:20` → `atr`；`src/spear_shield/indicators/_common.py:13` → `wilder_smooth`；`src/spear_shield/backtest/engine.py:111` → `BacktestEngine.run`；`src/spear_shield/strategy/inputs.py:58` → `build_snapshot`；`src/spear_shield/strategy/rules.py:30` → `exit_rules`。
- test_file / test_case：
  - **直接** `tests/unit/test_indicators.py:91` / `test_atr_hand_calc`：TR种子和Wilder递推，period3。
  - **直接** `tests/strategy/test_risk_boundaries.py:15` / `test_atr_strict_price_boundary`：注入价差恰2倍不触发。
  - **直接** `tests/unit/test_backtest_stops.py:73` / `test_gapdown_and_intraday_cross_use_fixed_line_not_future_low`：通用引擎固定stop价、跳空/滑点，provider是测试preset。
  - **直接** `tests/unit/test_backtest_stops.py:185` / `test_t_plus_one_can_sell_old_shares_but_not_today_top_up`：引擎T+1部分可卖，不测回放stop_remaining续卖。
  - **直接** `tests/unit/test_backtest_stops.py:204` / `test_provider_controls_reissue_no_engine_weekly_deduplication`：明确引擎依赖provider，测试preset可重复减半。
- notes：最终节已改ETF159915，不报§31旧指数冲突。回放前周ATR/收盘固定线与stop_remaining/周锁已编码；未发现直接测试StrategyReplay.stop_provider的冻结、每周一次与T+1续卖。atr_once_per_week只在周规则读取，provider无条件去重；旧build_snapshot输出当周信号资产ATR。盘中引擎目标开盘先于stop执行，故不是全路径P0/ATR行为等价。

## 未覆盖与验收边界

完全未发现针对测试的定义：`stall_definition`、`double_top_definition`。

只有间接调用证据的定义：`effective_break_definition`、`bullish_definition`、`candle_definition`、`bottom_definition`、`margin_clear_definition`。

即使列有直接测试，仍未覆盖主builder的收阳/回踩/上影/滞涨生成端点、形态多候选与52周缺失、底部资产口径、8周生成、完整入场tuple、同级授权max/tie、周期重启恢复、回放stop_provider冻结/周去重/T+1续卖，以及开盘风险重新核算。逐项已说明部分断言和fixture局限。

第6节已最终明确的选择不再按旧稿误报：自动形态和IV窗口已获算法授权；入场CATCHUP优先FIRST、负/零月线FAST20%、同级同量注册顺序、上影严格>60%、滞涨严格<1%、ETF前周ATR、每周期重置均按最终选择审。两融直接发布方占比已替代早稿原始逐股重建目标。保留其数据和实现缺口，但不另提新参数、不修改冻结口径。

写入后只做JSON结构、33键集合/顺序、定位函数存在性、计数与文件哈希复核；不运行项目代码。已有src/tests/docs/scripts文件与写入前SHA256逐一比较未变（两份新增文件除外）。原策略仅引用路径、章节与必要短公式，未复制原策略长段落。
