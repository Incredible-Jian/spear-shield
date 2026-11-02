# Phase 4 交付记录（2026-11-02）

基线：`main` / `0487ef8`。执行任务书：`phase4_task.md`。

## 已交付

- 宏观工具：156周Z、显式窗口分位、同日期比率与独立IV提供接口。
- 策略证据、发布时间/过期检查、完整周/月输入构造、15:30确认门控。
- 五维不完整状态、双周期矩阵、22项规则/预警/未定义项登记。
- P0–P3优先级、同级冲突、未知高优先级不当作通过。
- 分档与执行回执状态、建仓路径、核弹锁定、三档关闭、补回次数/时点。
- 防守比例/实际权重偏差、熔断未分配部分；不虚构短债/货币转移比例。
- SQLite策略审计、内容幂等、历史查询、服务编排。

新增核心文件：

```
src/spear_shield/indicators/macro.py
src/spear_shield/strategy/{types,evaluation,inputs,macro,rules,engine,defense,service}.py
src/spear_shield/portfolio/state.py
src/spear_shield/database/strategy_audit.py
tests/strategy/{conftest,test_macro,test_rules,test_inputs_audit_defense,
                test_engine_workflow,test_risk_boundaries}.py
docs/development/{phase4_task,phase4_results}.md
docs/strategy/strategy_engine_specification.md
```

修改：database/engine.py增量注册审计表、strategy/__init__.py公共接口、README、CHANGELOG、路线图与规则待确认清单。
无新增依赖、无金融数据源替换、无GUI业务接线。原Phase 0文档和源PDF保留，本期不修改源PDF。

## 实际测试证据

基线确定性测试59项全部通过。最终运行：

```
python -m pytest --ignore=tests/integration/test_akshare_provider.py -q --basetemp=D:/spear-shield/cache/pytest-phase4-release-check
142 passed, 1 warning in 6.09s
```

其中既有59项，Phase 4新增83项；包含原有GUI构建/导航测试。
唯一warning为第三方pytz中utcfromtimestamp弃用，与本期策略代码无关。

真实网络测试分别在独立pytest子进程运行、每项最多60秒：

| 既有测试 | 实际结果 |
|---|---|
| test_fetch_etf_daily | 1 passed，10.73s |
| test_fetch_margin | 1 passed，29.18s |
| test_fetch_index_daily | 60秒超时，被终止；未记为通过或跳过 |

曾启动不分流的完整pytest，但指数接口长时间未返回，已中止。不能宣称“全部含网络测试通过”。
最终合计144项通过，1项网络超时，145项测试已运行/尝试。
此次未大规模重构Phase 2。指数接口超时边界、供应商级限流与作业取消列为后续数据接线需处理的问题。

## 关键数值验证

- 65根收盘101..165：末期MA60=135.5、前期134.5、斜率100/134.5（%）。
- 第157点对前156个比值的Z与均值78.5、总体方差(156²−1)/12的手算一致。
- P0严格<0；建仓连续周斜率>=0.1；量分位60满足前40%；IV95/80不触发恐慌。
- ATR下跌价差等于2倍不触发；横盘每周恰4%不触发，累计恰±3%包含。
- 权益0.8减25%后0.6，待补回0.2；回执重放幂等；旧状态裁决拒绝再执行。
- 未来/过期证据不可用；未来行不改变历史前缀；缺整周不压缩为连续周；15:30前不发布最终周裁决。
- 同级不叠加；P0空仓时仍禁止入场；缺实际IV/股债数值不能核弹建仓。

## 当前限制

此阶段完成的是可测试的策略计算基础，**完整正式策略仍受规则与数据阻塞**。
IV无真实数据；股债来源未确认；形态、两融、风险预算等定义尚需负责人确认。默认Policy没有虚假批准。
含明确数值的规则已实现；模糊条件保留有确认记录的证据接口，未实现擅定参数的自动形态识别。
Phase 2缓存缺少历史发布时间/最终bar与时点复权版本，不能直接拿当前qfq缓存声称历史无前视偏差。
GUI仍为既有骨架，没有新增真实行情/收益/信号展示；当前无可交付Windows正式安装包。

## Git与下一阶段

提交前检查已包括diff、待提交路径、敏感凭据模式及缓存排除；只提交本期代码、测试和文档。
已核验GitHub登录为Incredible-Jian、仓库私有、默认main、远端基线0487ef8。
本期commit ID以Git日志/最终汇报为准（文档不写自引用commit）。不创建仓库、不改可见性、不发正式Release。

Phase 5建议：先补齐已结算bar/发布时间/来源适配与后台任务超时，再将ResearchResult接入Dashboard、温度计、共振与信号页；默认显式展示受阻原因。后续实现行情图、配置偏差、历史裁决查询与周报入口。未经负责人指示不开始Phase 5。
