# 开发路线图（Development Roadmap）

> 严格按阶段推进：分析 → 设计 → 实现 → 测试 → 修复 → Git Commit → 下一阶段。
> 每阶段结束汇报真实运行结果与测试证据，不宣称未验证的功能。

---

## Phase 0：环境检查与策略审计 ✅

- [x] 检查工作目录、Python/Git/gh 环境
- [x] 完整读取策略 PDF（pdfminer.six 提取，UTF-8 存档）
- [x] 提取完整规则清单 → `docs/strategy/rules_extracted.md`
- [x] 建立规则待确认清单 → `docs/strategy/rules_pending_confirmation.md`
- [x] 数据源可行性评估（akshare 实测）→ `docs/architecture/data_source_assessment.md`
- [x] 技术架构设计 → `docs/architecture/architecture.md`
- [x] 开发路线图（本文件）
- [x] GitHub 认证与私有仓库创建（gh + SSH，private，保护策略 PDF）
- **交付物**：本报告 + 上述文档。

---

## Phase 1：项目初始化 ✅

- [x] 项目目录结构（src/spear_shield 各包 + tests + scripts + docs）
- [x] pyproject.toml（src-layout、动态版本、`spear-shield` 入口）
- [x] 锁定依赖（PySide6 6.8.1.1 等）
- [x] README、.gitignore、.gitattributes、LICENSE
- [x] 最小可启动 GUI（深色主题空壳，8 页面导航）
- [x] 验证启动 + Git Commit

## Phase 2：数据引擎 ✅

- [x] `DataProvider` 抽象接口 + `AkShareProvider` / `SinaProvider` 实现
- [x] 接入核心 ETF / 指数行情（含前复权）
- [x] 周线 / 月线聚合（末交易日结算口径）
- [x] SQLite 缓存 + SQLAlchemy 模型（market_daily / margin_daily / data_update_log）
- [x] 数据质量检查、更新时间管理、来源追溯
- [x] 自动化测试 + Commit

## Phase 3：技术指标引擎 ✅

- [x] SMA / EMA（60周/月线、10/30周线）
- [x] MACD、RSI（Wilder）、布林带（ddof=0）、ATR（14 周 ATR 周线口径）
- [x] 成交量均线 / 量比 / 52 周分位数
- [x] 价格涨跌幅 / 偏离率 / 振幅 / 均线斜率
- [x] `IndicatorEngine` 统一入口（不改动入参、无未来数据、周期隔离）
- [x] 公式与口径文档 → `docs/indicators/indicator_specification.md`
- [x] 手工可复核数值测试 + Commit

> 宏观/策略指标（风格 Z-Score、股债性价比、IV 百分位、两融水位、PE 分位）在 Phase 4 策略引擎中实现——它们属于策略输入而非独立技术指标。

## Phase 4：策略引擎基础 ✅（正式策略仍受规则/数据阻塞）

- [x] 周/月斜率输入构造；Z/比率/历史分位纯数值工具，窗口口径显式参数
- [x] 五维状态与共振矩阵；IV缺失/股债待确认，整体明确不完整
- [x] 第一/二/三档、补投与所有原文离场逐条注册；歧义门控，第四档未定义
- [x] 最高优先级单动作、同级冲突提示、缺失高优先级阻塞
- [x] 动态防守/偏差、熔断未分配部分提示、执行回执状态机
- [x] SQLite完整输入/参数/规则/裁决/分析审计，内容幂等与历史查询
- [x] 边界、缺失/过期/未来、周期隔离、状态及审计测试
- [ ] 正式运行所有规则：等待清单中定义确认及真实宏观数据接入

交付与验证见 `docs/development/phase4_results.md`；未实现未经确认的自动形态算法。

## Phase 5：桌面可视化 ✅（回测计算仍在Phase 6）

- [x] 九页统一深色工作区，Qt Charts原生K线/均线/指标与配置图
- [x] 真实缓存日期/来源/复权展示，Phase 4审计与规则详情，明确可用性诊断
- [x] 可终止QProcess更新、45秒超时/取消/关闭清理、手动/定时更新
- [x] CSV/Excel导入导出、严格预检与备份、数据状态及更新记录
- [x] 持久化手工模拟账户，原始价估值，缺价不填补
- [x] 回测参数及结果界面，未实现计算不展示绩效
- [x] 周报市场/五维变化/周期/信号/建议/观察，PDF和Excel导出
- [x] 真实数据GUI截图、交互测试、启动入口与日志优化

使用说明见 `docs/user_manual/desktop_workbench.md`，验证记录见 `phase5_results.md`。

## Phase 6：历史回测（基础与基准研究已交付，完整策略验收受阻塞）

- [x] 日事件执行引擎、费用/滑点/现金预算/单位、仓位/资金、显式停牌/分红/拆分/日历契约
- [x] 收盘信号与后续开盘分离、目标不可变/冲突校验、输入快照/指纹/报告
- [x] 真实创业板持有/固定防守初始配比研究、桌面独立计算/曲线/交易/ZIP
- [x] 完整策略阻塞检查与Phase4外部快照裁决审计（不是成交账本回放）
- [ ] 完整矛与盾策略资金回测：规则确认、历史可知数据、批次及盘中执行仍不完整
- [ ] 自动完整公司行动/停牌源、正式日历验证及PIT前复权历史

交付证据与限制见 `phase6_results.md`。不得因下一阶段推进而把未勾选项自动视为完成。

## Phase 7：系统测试与优化

- 单元 / 集成 / 策略边界 / 缺失数据 / 数据源中断 / GUI 交互 / 长时运行测试
- 性能优化、修复问题 + Commit

## Phase 8：打包发布

- PyInstaller 生成 Windows exe（免 Python、双击启动、独立数据与配置）
- 使用说明、数据源配置说明、免责声明、版本号、更新日志
- 真实 Windows 环境验证（当前为 Windows，可本机验证）

## Phase 9：GitHub 发布

- 已有私有仓库 spear-shield；无需重复创建。正式发布前重新检查认证/远端/可见性
- 核验README、LICENSE、Topics，发布Release、Windows安装包（须负责人批准）
- 语义化版本号、真实提交历史、敏感信息核查

---

## 提交风格约定

```
chore: initialize project structure
docs: add strategy specification and architecture
feat(data): implement market data provider
feat(indicators): implement macro indicator engine
feat(strategy): implement cycle resonance matrix
feat(strategy): implement P0-P3 risk management
feat(ui): build quantitative dashboard
feat(backtest): implement historical backtesting engine
test: add strategy validation and edge case tests
build: package Windows desktop application
docs: add installation and user guide
```
