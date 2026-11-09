# 矛与盾·全天候周期共振系统

**Spear & Shield - All-Weather Cycle Resonance System**（V1.0）

一款基于 Python 的桌面量化分析软件，用于研究、监控、回测与模拟决策。

> ⚠️ **免责声明**：本软件是研究、监控、回测与模拟决策工具，**不连接券商账户，不自动执行真实交易**。所有信号与回测结果仅供研究参考，不构成任何投资建议。

---

## 核心能力

- 实时 / 最新市场行情观察，自动获取与更新真实市场数据。
- 自动计算策略所需的技术指标与宏观指标。
- 自动识别**五维宏观温度**（60月线斜率、股债性价比、风格Z-Score、期权IV、两融水位）。
- 自动识别**月线与周线周期共振**。
- 自动判断建仓、加仓、减仓、清仓信号（四档建仓 + P0-P3 离场 + 动态防守）。
- 可视化展示进攻端与防守端资产配置。
- 历史回测与收益分析、模拟资金账户与持仓管理、历史信号记录与策略解释。
- 数据异常、缺失和延迟预警。

## 核心资产池（锁死，严禁变更）

| 角色 | 跟踪指数 | 场内 ETF |
|------|---------|---------|
| 进攻矛 | 创业板指 (399006) | 159915 创业板ETF |
| 防守盾 | 中证红利低波 (H30269) | 563020 红利低波ETF |
| 稳健收益池 | 短债指数 | 511360 短融ETF |
| 流动性现金池 | 货币基金 | 511990 华宝添益 |

## 当前开发进度

负责人已于2026-11-09授权本阶段提交并同步至现有私有仓库；范围及历史证据的时点说明见[阶段同步记录](docs/development/git_delivery_20261109.md)。不公开仓库、不发布Release。

2026-11-09 第三轮已接入模拟账户订单/成交/资产快照、确认后保存的每周裁决、历史周报与Markdown/CSV导出。实际Windows买卖与重启证据、数据限制、修改清单见[本轮交付](docs/development/usability_round3.md)，日常操作和增量数据库方案见[账户与每周闭环](docs/architecture/paper_weekly_workflow.md)。尚待人工验收，未提交或推送。

- [x] Phase 0 环境检查与策略审计
- [x] Phase 1 项目初始化（深色主题 GUI 空壳）
- [x] Phase 2 数据引擎（数据源抽象 + AkShare/Sina + SQLite 缓存 + 周/月聚合）
- [x] Phase 3 技术指标引擎（SMA/EMA、MACD、RSI、布林带、ATR、成交量分位、价格指标）
- [x] Phase 4 策略引擎基础（宏观工具 + 五维状态 + 共振矩阵 + 逐条规则/待确认门控 + 仓位状态 + SQLite审计）
- [x] Phase 5 桌面工作区（九页导航、真实缓存K线/指标、审计、模拟记账、数据管理、PDF/Excel周报）
- [ ] Phase 6 历史回测（执行引擎/真实基准/授权口径策略回放已交付；完整验收仍受实际数据缺口限制）
- [ ] Phase 7 系统测试与优化
- [ ] Phase 8 打包发布
- [ ] Phase 9 GitHub 发布

指标公式与口径见 [docs/indicators/indicator_specification.md](docs/indicators/indicator_specification.md)。

Phase 4 的规则覆盖与接口见 [策略引擎规范](docs/strategy/strategy_engine_specification.md)，执行范围见 [Phase 4 任务书](docs/development/phase4_task.md)。
**完整策略尚未通过正式验收**：本轮负责人已授权工程师自主查证并选择操作定义，33项算法凭据已版本化；完整IV、股债分母/尺度与历史发布版本等事实仍不能制造。引擎逐条返回触发/未触发/数据缺失/待确认/未定义，不默认产生核弹建仓。
信号计算与模拟执行分离。GUI已接入真实缓存观察与审计历史；未确认输入仅可运行明确标注的可用性诊断。原有Phase 2行情缺少历史发布时间和已结算元数据，不能直接当作无前视偏差的策略输入。

桌面操作见 [工作区使用说明](docs/user_manual/desktop_workbench.md)。历史回测现可运行真实缓存的创业板/固定防守基准研究，支持费用、滑点、全区间曲线和ZIP报告；完整策略会列出阻塞项，未完成正式策略资金回测。使用和口径见 [回测手册](docs/user_manual/backtesting.md)，真实验收及剩余缺口见 [Phase 6 记录](docs/development/phase6_results.md)。

补齐阶段增加“授权口径策略研究回放”，连接因果特征、Phase4规则与实际成交回执，提供独立日历、免费历史源/哈希、跨源核对与时点复权重建。它会显示仍缺失的输入及进攻/防守真实成交数，不把可用子模块收益当完整策略收益。见[本轮补齐记录](docs/development/phase6_completion_results.md)与[最终操作定义](docs/strategy/operational_definitions.md#2026-11-03-final)。

## 环境要求

- Python 3.11 ~ 3.12（开发环境 3.12.4）
- Windows 10/11

## 安装与启动（开发模式）

```bash
# 1. 创建并激活虚拟环境（可选）
python -m venv .venv
# Windows:
.venv\Scripts\activate

# 2. 安装依赖
pip install -r requirements.txt -r requirements-dev.txt

# 3. 以可编辑模式安装本项目
pip install -e .

# 4. 启动软件（二选一，VS Code也可F5选择项目调试配置）
spear-shield                      # 控制台入口
python -m spear_shield            # 模块方式
```

## 运行测试

当前阶段：**Phase 6.5 后续桌面实用化 / 完整策略仍PARTIAL**，冻结口径 `delegated-2026-11-03-v1`。2026-11-09完成ATR专项工程复核并交付六标的Dashboard、后台更新和日周月图表增量，最终非网络回归313通过。盘中日线、缺失指标和历史延迟明确显示，不代表完整策略已验收。启动与真实截图见[第一轮记录](docs/development/usability_round1.md)、[第二轮交付](docs/development/usability_round2.md)。原始资料版权及其他审计缺口保留，仓库可见性/历史未更改。

```bash
python -m pytest --ignore=tests/integration/test_akshare_provider.py
```

真实网络测试依赖供应商，需单独限时运行，不能将接口超时当作通过。GUI更新使用独立进程，默认45秒超时可取消。

## 项目结构

```
spear-shield/
├── src/spear_shield/     # 应用源码（见 architecture.md 分层）
├── tests/                # unit / integration / strategy 测试
├── docs/                 # 策略、架构、开发、用户文档
├── scripts/              # 辅助脚本
├── assets/               # 静态资源
└── releases/             # 打包产物（不入库）
```

## 数据源

数据源抽象为独立接口，核心策略不依赖任何单一供应商。当前主源为 AkShare（免费公开数据），预留 Tushare 等可选数据源。

数据缺失时，软件会明确标记「数据不可用 / 待接入」，**绝不编造数据、不把缓存伪装成实时数据**。

## 许可证

[MIT](LICENSE)
