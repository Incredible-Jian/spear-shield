# Phase6.5 B02 方案A修复验收记录

日期：2026-11-08。状态：**生产修复已实现，等待人工验收；未提交、未推送**。负责人已明确批准方案A：ATR确认后取消相关整笔未完成目标，保留全部实际成交，重新入场需新裁决和新目标。操作定义 `delegated-2026-11-03-v1` 参数不变，执行补充编号 `atr-target-invalidation-A-20261108-v1`。

**2026-11-09专项复核：工程验收通过，未发现新的高风险问题。** 本轮不重写生产ATR逻辑；补充止损提交审计失败及成交回执写入失败两项注入，取消持久化保留，错误终止而非虚构成交，重放后旧目标仍无效。完整回归305 passed（79.16秒，9 warnings），覆盖此前303项与本轮2项。现可继续独立行情/桌面开发；整体Phase6.5数据/定义/版权问题仍保留。详见[第一轮实测记录](../development/usability_round1.md)，11月8日历史数据和哈希不覆盖。

## 1. 本轮修改文件（不把已有未提交修改冒充本轮工作）

| 文件 | 本轮变更 |
|---|---|
| `src/spear_shield/backtest/models.py` | Target稳定ID，默认内容哈希，可明确传ID但不允许重用ID改变意图 |
| `src/spear_shield/backtest/engine.py` | 确认/取消/提交/成交分序；整目标失效、事件余量/幂等、审计标识、持久日志注入 |
| `src/spear_shield/backtest/execution_journal.py`（新增） | SQLite追加审计、输入绑定、取消墓碑、target_state重载、冲突写入拒绝 |
| `src/spear_shield/backtest/strategy_replay.py` | 消费cancelled_atr、释放桥内pending/queued状态，取消不晋级、不回滚实际份额，回执记录ID和状态；传持久路径 |
| `src/spear_shield/backtest/research.py` | 仅研究入口传递journal_path |
| `src/spear_shield/backtest/worker.py` | 请求旁独立execution.sqlite，行情库仍只读 |
| `tests/unit/test_atr_target_invalidation.py`（新增） | 生产引擎安全/重启/幂等/账务及策略桥回归 |
| `tests/fixtures/b02_legacy_engine.py`（新增） | 修复前执行器只供历史诊断对照，除调整绝对导入外保留旧行为，不被生产引用 |
| `tests/unit/test_atr_stop_reentry_diagnosis.py` | 保留原全部诊断预期，fixture绑定修复前引擎以继续证明缺陷原貌 |
| `tests/integration/test_phase65_audit.py` | 只移除已修复B02的xfail标记；原“不应补买”断言及复现输入完整保留 |
| `scripts/compare_atr_target_fix.py`（新增） | 使用同真实缓存抓取独立before/after研究证据，不联网、不覆盖旧报告 |
| `docs/phase6_5/atr_stop_reentry_decision.md` | 保留历史分析，补正式批准、实施和限制 |
| `docs/phase6_5/audit_report.md` | 顶部补当前B02状态，保留历史A–I结果 |
| `docs/architecture/atr_target_execution.md`（新增） | 执行时序、字段、恢复机制与限制 |
| 本文、`manifests/atr_target_fix_evidence.json`（新增） | 逐项验收及可核对前后结果 |
| `manifests/atr_target_fix_SHA256.txt`（新增） | 本轮17个变更/新增交付文件实际字节哈希；不递归散列自身 |
| `CHANGELOG.md` | 11月8日本轮记录，不改写11月3日历史条目 |

## 2. 调用链与状态

`桌面回测页 → worker → run_benchmarks(strategy_research) → StrategyReplay.run → BacktestEngine.run → stop_provider → ATR确认 → invalidate_target → 持久cancelled_atr + 零成交取消回执 → stop_submission → 实际卖出/延期receipt → StrategyReplay.execution`。

下一交易日没有旧pending可重试；后续新周裁决创建独立Target，不能恢复已取消ID。开盘跳空确认在旧目标开盘执行前；盘中确认保留已经完成的开盘成交，之后立即撤销剩余意图。严格触发线及原50%比例未扩大。取消不增加卖出量，不抹除已有防守/进攻持仓，T+1余量不是原买入目标的恢复。

持久cancel记录至少含：target_id、target_status、invalidation_reason/event_id/time/phase、cancelled_remaining_quantity、executed_quantity、related_stop_order_id。数量按每个标的分别记录buy/sell，取消时未成交量只是当前模型快照，完整旧权重同时失效。真实剩余仓位独立保存在回执/曲线，不能把取消数量当作实际成交。

执行恢复方式、无分钟时点的披露及API持久化要求见[执行契约](../architecture/atr_target_execution.md)。没有券商连接，没有另造实盘账户恢复功能。

## 3. 测试覆盖

| 用户要求 | 直接证据 |
|---|---|
| 原100份目标止损后40份不补买 | 原安全断言正式运行；100→40→40的原最小样本新旧对照 |
| 部分目标成交 | 初始80/60份、目标100份，取消后分别保留40/30份 |
| 止损部分/零成交 | T+1请求40份、先卖20再卖20；首日可卖0时先0再40，旧目标始终无效 |
| 同周期时序 | gap场景取消回执在保护单成交前且无新开盘买入；盘中场景保留此前真实买入60份 |
| 跨周 | 周五取消、周一不补买；不依赖周集合自动失效 |
| 程序重启 | 新Engine和SQLite连接、两个独立Python进程重跑相同输入，成交/净值相同且审计行数不增 |
| 同事件重复 | cancelled墓碑重复写入幂等，冲突写入拒绝；完成止损后重复输入无卖出、不取消新目标 |
| 新裁决新目标 | 新周度授权不同ID可入场，旧ID取消不变；相同ID改时点/权重被拒绝 |
| 成交不回滚 | 原交易保留；cancelled_atr回执trades为空、completed=False |
| 取消不自动全清 | 保留40/30份及实际防守持仓；没有取消诱发的清仓成交 |
| 净值/费用/历史一致 | 逐日现金+进攻市值+防守市值对账；费用和滑点分别与实际成交求和一致；策略桥不错误确认未完成档位 |

最终非网络测试结果见机器证据。逐项对照上轮XML中283个通过用例的完整classname/name，全部仍通过；原B02安全不变量另外转为正式通过，没有以跳过或修改预期消除。新增测试文件包含14个参数展开用例。历史诊断5项继续使用明确隔离的旧引擎，不计作生产安全覆盖。

最终实际结果：**303 passed、0 failed、0 skipped、0 xfailed，9 warnings，86.03秒**。构成为原283项通过用例＋原B02安全断言1项＋历史诊断5项＋本轮生产安全14项。结果XML为 `cache/phase65/atr-fix-20261108/acceptance-tests.xml`，文件SHA256见机器证据。

```powershell
python -m pytest --ignore=tests/integration/test_akshare_provider.py -q --basetemp=cache/phase65/atr-fix-20261108/pytest-acceptance --junitxml=cache/phase65/atr-fix-20261108/acceptance-tests.xml
```

本轮没有重跑网络数据接口，因为修复不涉及采集器、数据源或网络；未沿用旧网络成功数计为本次通过。Qt启动/后台工作/报告保存等仍包含在完整非网络回归中。9条第三方pytz/openpyxl弃用告警未伪称修复。

## 4. 相同真实数据集前后比较

修改生产代码前本轮重新运行并保存 `cache/phase65/atr-fix-20261108/real-before.json`，修改后同数据重跑至 `real-after-final.json`；未借用旧审计终值作为本轮实测。区间2024-01-02..2026-10-30，初始100000、费率0.0003、滑点0.0005。数据指纹相同。

| 比较项 | 修复前 | 修复后 |
|---|---:|---:|
| 周度裁决审计 | 146 | 146，逐项内容相同 |
| ATR预置单检查 | 683 | 683 |
| 严格越线但无仓位 | 4 | 4 |
| ATR实际卖出成交 | 0 | 0 |
| 订单尝试记录总数（不等于成交数） | 730 | 730 |
| 实际进攻/防守成交 | 0 / 138 | 0 / 138 |
| 目标取消次数 | 0 | 0 |
| 实际进攻/防守权重与份额 | 完整日序列 | 逐日完全相同 |
| 期末研究净值 | 123662.07099650867 | 123662.07099650867 |
| 手续费 | 171.21782799135 | 171.21782799135 |
| 滑点成本（已在成交价内） | 285.3381754999619 | 285.3381754999619 |
| 重复ATR卖出/取消 | 0 / 0 | 0 / 0 |

交易、订单、信号比较只剔除新增target/stop审计ID后全部一致；资金曲线、权重、metrics及周度审计未作字段裁剪，全部一致。没有进攻持仓的真实样本不能证明B02异常路径已充分经历，所以以下人工异常样本是独立必要证据。仍是qfq单位研究，PIT/宏观数据缺口不因本次修复而消失。

## 5. 异常样本的可解释经济变化

全部为明确合成测试，未混入真实回放。

| 相同输入场景 | 修复前 | 修复后 | 因果说明 |
|---|---|---|---|
| 原三日最小复现 | 100→40→73份；5笔成交 | 100→40→40份；3笔成交 | 取消原80/20整目标，少买33进攻、18防守；历史卖出均保留 |
| 80份底仓、目标100份、平价零费 | 终值920；5笔 | 终值920；3笔 | 取消旧目标后不再卖防守/补买进攻；虽然终值相同，持仓不同 |
| 同场景费0.001、滑点0.002、末日进攻收11 | 终值1004.9680200000003；费2.01198；滑点4.02 | 终值956.0686600000001；费1.31134；滑点2.62 | 少执行旧目标后续成交，进攻反弹敞口较少；结果低约48.89936，不能为保收益恢复旧买单 |
| 同一ATR事件重复、其后新决策入场 | 终值856；6笔 | 终值920；5笔 | 原引擎对同事件再减半；新引擎已完成事件不再卖出，新目标独立入场 |

没有修改冻结参数来得到结果。每个差异样本保存逐笔交易、完整曲线、取消target_id及关联event/order ID，可逐个解释，见[机器证据](manifests/atr_target_fix_evidence.json)。被阻止的买入是旧目标的未执行意图，未删除修复前报告中的任何真实成交记录。

## 6. Git、范围与剩余限制

开始时已有上轮Phase6.5未提交修改。本次未reset、未清理、未覆盖原报告/原manifest/行情数据库。HEAD仍为 `5aa322defdbc7fa10f121a39acb92e3bb0950ddb`，main；未commit、未push，工作区不干净是预期。具体原有修改和本轮增量通过本地before_files快照区分。

指标引擎、ATR公式、冻结policy文件、其他退出/入场规则、仲裁器及portfolio/state字节未变。执行语义会影响“存在ATR与pending交叉”的交易路径，这是批准的修复效果；不能称对所有策略收益毫无影响。普通未触发ATR路径和指定真实样本通过回归。

恢复依赖同一完整数据集、请求及日志；这是回测重放恢复，不是任意时点实盘检查点续跑。低层API不传journal_path不会持久化，桌面strategy_research已接持久路径。外部伪造新裁决或人为编辑SQLite不在本地审计可认证范围。其他Phase6.5定义、数据时点及版权问题继续保留，本次不扩大处理范围、不进入Phase7。最终状态等待人工验收。
