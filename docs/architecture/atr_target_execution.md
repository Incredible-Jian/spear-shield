# ATR触发后目标失效：方案A执行契约

执行语义版本：`atr-target-invalidation-A-20261108-v1`。负责人于2026-11-08明确批准方案A。此编号仅版本化执行补充，不替换 `delegated-2026-11-03-v1` 的33项定义/29参数。

## 状态与时序

目标 `pending → cancelled_atr` 后永久失效，已完成的目标不再有剩余意图可取消。单一执行器只保留一笔pending，ATR针对当前含正159915目标权重的整笔目标取消；不将纯防守目标当作新增进攻授权。取消覆盖全部标的未执行意图，不生成防守替代目标、不更改既有持仓。

1. 上一完整周数据产生当日预置ProtectiveStop，known_at必须严格早于开盘。生成指令不等于触发、提交或成交。
2. 非停牌且开盘价严格低于止损线时，已有开盘价即可确认越线；先确认事件、持久化旧目标取消，再提交保护卖出，此后旧目标不能生成开盘买单。
3. 开盘未越线，盘中low严格越线时，日OHLC模型只能在开盘操作之后确定该事件；保留开盘已发生的实际成交。确认后先取消pending，再提交保护卖出，不回滚已成交单。
4. 确认事件与取消在SQLite追加记录中分别落地；随后记录stop_submission，最后receipt记录实际成交或T+1/停牌状态。取消回执没有成交、completed=False，不确认档位，也不产生清仓交易。
5. T+1零成交/部分成交不恢复旧目标。首次触发固定请求数量，重试只处理该事件余量，不对每天剩余持仓重新减半；事件完成后的重复投递只记录already_executed，不成交、不重复撤销新目标。
6. 新的周度策略裁决仍经原有风险、阶段和数据门槛，创建独立新target_id。该事件后的旧时点授权即使换ID也不能被当成新裁决使用；相同ID不能改时间/权重/原因恢复执行。调用方伪造新事实不是执行器能够认证的范围。

停牌不会仅因输入low越线就被认作可成交或已确认的ATR触发，保留原模型资格要求；恰好等于线不触发。盘中模型的15:30字段是阶段排序锚点，**不是声称真实触发分钟为15:30**。审计显式保存invalidation_phase与time_precision；同日收盘后的全新裁决可以发下一交易日目标，没有新增冷却期或永久禁止入场规则。

## 数据契约

| 字段 | 定义 |
|---|---|
| target_id | 默认由信号/可用时点、原因、权重生成稳定哈希；也可明确传ID，但不允许同ID改变内容 |
| target_status | 回放当前状态；SQLite取消墓碑重载为cancelled_atr，不能写回pending |
| invalidation_reason/event_id/time/phase | 原因、对应ATR事件、模型排序时点及开盘/盘中阶段 |
| cancelled_remaining_quantity | 每标的buy/sell待执行量快照；按取消前实际份额及当前开盘模型估值换算，不是虚构逐笔限价挂单，也不是ATR卖出数量 |
| executed_quantity | 该目标累计实际buy/sell份额，不包含独立ATR成交；历史成交不回滚 |
| cancelled_target_weights | 失效的完整篮子权重；即使取消时某腿剩余量为0，该旧权重也不能日后再生成买单 |
| related_stop_order_id | 关联保护单；stop_event_id在同一事件多日部分执行保持一致，stop_order_id区分当日尝试 |

## 持久化和重启

`backtest/execution_journal.py` 使用独立SQLite，`audit(kind,id,payload)` 唯一键、同步写入、追加不覆盖。重复相同内容为幂等；相同键不同内容抛错停止。kind包括binding、target、stop_confirmation、cancel、stop_submission、receipt。cancel为持久墓碑，`target_state(id)`合并返回最终取消状态。它不修改行情库、模拟账户或旧报告。

桌面调用链：`BacktestCenterPage.execute → backtest.worker.main → run_benchmarks(strategy_research, journal_path) → StrategyReplay.run → BacktestEngine.run`。工作进程将日志放在请求JSON旁的 `*.execution.sqlite`，重启用同一请求/日志路径。低层研究API不传journal_path时只用内存SQLite，结果明确durable=False；需要跨进程恢复时必须传持久路径，不将该模式声称为已落盘。

现回测引擎从区间起点重建账户，因此恢复机制是**绑定完整行情/日历/公司行动/费用配置的确定性重放**，不是从任意盘中位置接续实盘账户。历史阶段早于失效时允许重放当时真实成交；达到失效阶段后墓碑仍然有效，后续不能重启旧意图。同一审计键校验一致而不新增历史成交行；输入改变会拒绝，需独立新研究运行，不能覆盖旧运行。

新进程应创建新的StrategyReplay以从历史回执重建内存阶段/风险状态。不得把重放回调直接写入已经记账的外部账户。缺原始数据/请求不能猜测恢复，不能复制部分数据库后绕开binding。SQLite本身是本地审计，不承诺认证被人为编辑的数据库、实盘券商幂等或高并发多写者恢复。

## 改动边界与验证

生产改动限于models.Target标识、engine取消/事件幂等、execution_journal、StrategyReplay取消回执消费及run_benchmarks/worker持久路径传递。未修改ATR算法、两倍/50%阈值、入场/离场其他规则、指标或账户模块。已有状态机仍按真实成交推进；取消不会晋级未完成档位。

测试涵盖原100份目标不再补买、部分建仓、T+1部分/零成交、同期开盘/盘中、跨周、独立Python进程重启、事件/取消幂等、新裁决新目标、账务与费用对账。最终结果及真实历史比较见[验收记录](../phase6_5/atr_target_fix_results.md)。
