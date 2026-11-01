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

## Phase 4：策略引擎

- 宏观指标：60月/周线斜率、风格 Z-Score、股债性价比、IV 百分位、两融水位、PE 分位（不可得项标记「不可计算/待确认」）
- 五维宏观温度计、双周期共振矩阵
- 四档建仓（仅实现已确认规则，第四档标记未定义）
- P0-P3 离场规则、动态防守、仓位管理、规则优先级
- 信号解释系统（每条信号记录触发依据）
- 策略边界测试 + Commit

## Phase 5：桌面可视化

- Dashboard、宏观温度计、周期共振、行情图表、策略信号中心、资产配置、回测中心、模拟账户、数据管理、周报
- 深色专业量化终端风格 + Commit

## Phase 6：历史回测

- 回测引擎、交易成本、仓位变化、停牌/分红/交易日历
- 三大基准对比（矛与盾完整策略 / 纯持有创业板ETF / 防守资产组合）
- 防未来数据泄露（信号与执行分离）、回测报告
- 真实历史数据回测 + Commit

## Phase 7：系统测试与优化

- 单元 / 集成 / 策略边界 / 缺失数据 / 数据源中断 / GUI 交互 / 长时运行测试
- 性能优化、修复问题 + Commit

## Phase 8：打包发布

- PyInstaller 生成 Windows exe（免 Python、双击启动、独立数据与配置）
- 使用说明、数据源配置说明、免责声明、版本号、更新日志
- 真实 Windows 环境验证（当前为 Windows，可本机验证）

## Phase 9：GitHub 发布

- 检查 Incredible-Jian 账号（已确认存在，无 spear-shield 仓库，需新建）
- 创建仓库、README、LICENSE、Topics、Release、Windows 安装包
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
