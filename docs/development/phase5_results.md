# Phase 5 交付记录（2026-11-02）

基线：80a225b / main。任务授权与范围见phase5_task.md，详细操作见../user_manual/desktop_workbench.md。

## 交付范围

| 页面 | 已交付行为 |
|---|---|
| 系统总览 | 核心ETF真实缓存价/日期/来源、数据覆盖、最近裁决与风险可判定状态 |
| 五维温度计 | 五卡片、公式阈值、审计来源/可用时间、历史趋势；缺失不合成完整温度 |
| 周期共振 | 周/月K线、MA60与斜率观察、原文矩阵与正式审计状态分开 |
| 策略信号 | 最近100条审计选择、22项规则、条件/原始证据/确认记录；明确空仓可用性诊断 |
| 资产分析 | 日/周/月K线、MA/BOLL、MACD/RSI/ATR/量、框选缩放、样本统计与实际权重 |
| 历史回测 | 日期/资金/费用/滑点/三基准配置与JSON导出、曲线/交易表接口；引擎未实现按钮禁用 |
| 模拟账户 | 一次初始化、四ETF手工记账、整数金额/均价成本、持仓和历史、原始价估值与配置图 |
| 数据管理 | 供应商/口径选择、手动与定时更新、45秒超时/取消、预检、导入导出、日志、SQLite备份 |
| 每周报告 | 缓存市场概况、五维变化、周期/裁决、候选信号、防守端配置、风险/观察、PDF与五表Excel |

原生Qt Charts随已有PySide6 Addons提供，不引入浏览器或外部图表运行服务。
新增运行依赖openpyxl>=3.1,<4，本机已安装3.1.2；其余版本仍为Python3.12.4、PySide6 6.8.1.1、pandas2.3.0、SQLAlchemy2.0.30。

## 新增/修改文件概览

```
.vscode/launch.json
src/spear_shield/__main__.py
src/spear_shield/data/fetch_worker.py
src/spear_shield/portfolio/paper_account.py
src/spear_shield/services/{workspace,reporting}.py
src/spear_shield/ui/{controller,jobs,charts,widgets}.py
src/spear_shield/ui/pages/weekly_report.py
tests/unit/test_phase5_services.py
tests/integration/test_phase5_ui.py
scripts/{prepare_preview_data,capture_phase5}.py
docs/development/{phase5_task,phase5_results}.md
docs/user_manual/desktop_workbench.md
assets/phase5/{dashboard,market,cycle,signals,data,report}.png
```

修改原8页面、统一主题/基础卡片/主窗口、main入口、数据库注册、ETF复权适配、日志路由、既有启动测试、依赖/README/路线图/CHANGELOG。
未修改Phase 4交易阈值、未确认规则或原始策略PDF。

## 实际验证

### 自动化

```
python -m pytest --ignore=tests/integration/test_akshare_provider.py -q --basetemp=D:/spear-shield/cache/pytest-phase5-delivery
176 passed, 9 warnings in 29.41s
```

保留前142项，新增34项。覆盖：复权参数、不污染缓存、原始/复权隔离、真实日期类型、账户成本/现金/卖空/资金不足/缺估值、备份读取、CSV/Excel公式转义、周报时间隔离/变化/配置、九页中文/图表切换、诊断与账户操作、PDF导出、后台成功/错误/超时/立即取消/启动失败、GUI定时器持续响应、跨模块日志落盘。
9条warning来自第三方pytz/openpyxl的UTC弃用调用，不是项目代码异常。
既有3个直接联网pytest未在本轮无界运行；本期改用下述限时真实抓取与实际GUI链路验证，不称其为3项pytest通过。

### 真实数据与GUI链路

| 数据 | 结果 |
|---|---|
| 159915 ETF前复权 / akshare | 2872行，最新行情日2026-11-02 |
| 159915 ETF原始 / akshare | 2872行，最新行情日2026-11-02 |
| 399006 指数点位 / sina | 2873行，最新行情日2026-11-02 |
| 563020 ETF前复权 / GUI后台akshare | 实际写入696行；抓取期间GUI定时器触发151次 |

首轮前复权抓取曾发生stdout日志污染JSON协议，已把供应商导入和调用均置于stderr重定向中，新增独立子进程回归验证。
网络进程只返回JSON，不接触数据库；主进程预检后入库。抓取超时、取消或输出异常不会写半成品行情。
数据与本机模拟/诊断记录仅留在gitignored cache/phase5-preview/，不上传数据库或原始行情文件。
其余未取到标的明确显示缺失，截图未注入测试行情。信号截图由真实调用“空仓可用性诊断”生成，并明确不属于市场交易信号。

### 应用与视觉

```
python -m spear_shield --data-dir D:/spear-shield/cache/phase5-smoke-final --smoke-test
```

真实Qt事件循环启动并自动正常退出（exit0），数据库/desktop.ini初始化、启动日志实际落盘。
截图在Windows的Qt offscreen平台实际渲染，已打开检查：中文、K线、均线、元数据、缺失状态、九页导航及深色布局。
补充Windows本机字体显式加载，不将字体文件复制入仓库；修复终端写入中文转码问题，并用中文标题断言防回归。
未构建exe，未宣称完成最终Windows分发验证（Phase 8）。

## 本期优化与修复

- 修复ETF请求none/hfq时仍返回qfq的错误，原始估值不再依赖错误口径。
- SQLite date读取统一转datetime，修复周/月聚合.dt异常。
- 请求从GUI移到可杀掉的QProcess，解决供应商无限等待造成界面卡死的风险；异常、日志污染及立即取消均有回归测试。
- 日志统一挂在spear_shield父logger，修复只有首个模块有handler导致其他模块INFO不落盘。
- 新增正确的python -m启动入口、--data-dir、启动烟测、VS Code模块调试配置。
- 统一控件/透明文字背景、Windows字体、记住图表/数据源选择和窗口尺寸。

## 仍未完成的范围

- 正式策略仍受原清单确认项、IV/股债等数据缺口阻塞，未把观察图转换为正式买卖裁决。
- 历史时点复权、交易日历、完整最终bar与历史发布时间元数据尚未补齐；不能声称历史无前视偏差。
- 回测计算、撮合/费用/分红/T+1在Phase 6；当前模拟是手工权重/成本记账，不是券商级交易仿真。
- 定时更新仅针对所选标的，默认关闭；周报按查看/刷新生成，没有宣称完成带交易日历的周五无人值守SOP。
- 文件导入与本地计算有大小限制，长时稳定性/大规模性能专项在Phase 7。备份目前只增加，不自动清理。
- 未发Release、未生成安装包，未改变私有仓库可见性。

## Git与下一阶段

提交前检查diff、凭据模式、缓存/数据库/日志排除及源PDF未改动。commit ID以Git日志和阶段汇报为准。
下一阶段为Phase 6历史回测：先设计时点数据/交易日历与企业行为契约，再实现信号与下一交易日成交分离、费用/滑点、基准、绩效与逐笔交易；未确认规则继续保持门控。
