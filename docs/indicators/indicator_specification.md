# 技术指标规范（Indicator Specification）

> 本文件是 `src/spear_shield/indicators/` 模块的唯一公式与口径基准。
> 只描述「如何计算指标」，不含任何交易/信号判断。
> 所有实现差异必须回到本文件核对；如需修改口径，先改本文件再改代码。

---

## 0. 通用约定

| 项 | 约定 |
|----|------|
| 输入 | 标准化 bar DataFrame，列 `date, open, high, low, close, volume`（`amount` 可选） |
| 输出 | 新增指标列；**不改动调用者传入的 DataFrame**（引擎内部 `copy`） |
| 预热期 | 数据不足时返回 **NaN**，**绝不伪造数值** |
| 未来数据 | 所有指标只用当前及历史数据，不读取未来数据 |
| 周期隔离 | 指标在「给定 bar」上计算，不做重采样；周线 ATR 必须传入周线数据，日线数值不得当作周线 ATR |
| 比率单位 | `price` 模块所有「率/幅/偏离/斜率」返回**百分比数值**（1.0 = 1%） |
| NaN | 输入含 NaN 时对应窗口输出 NaN，不填充、不丢弃 |
| 日期 | 引擎要求日期唯一且升序，否则抛 `ValueError` |
| 失败 | 参数非法抛 `ValueError`；不静默吞异常 |

---

## 1. 移动平均线（moving_average.py）

### 1.1 SMA

```
SMA[i] = mean(close[i-window+1 .. i])
```

- 参数：`window`（正整数）
- 预热期：前 `window-1` 根为 NaN
- 实现：`rolling(window, min_periods=window).mean()`

### 1.2 EMA

```
alpha = 2 / (window + 1)
EMA[window-1] = SMA(close[0 .. window-1])        # 初始值（SMA 种子）
EMA[i] = EMA[i-1] + alpha * (close[i] - EMA[i-1])
```

- 参数：`window`
- 预热期：前 `window-1` 根为 NaN
- 明确记录：初始值采用**前 window 根简单平均**（SMA 种子），非「首个收盘价」；`alpha = 2/(N+1)`

### 关键场景映射

| 策略口径 | 实现 |
|---------|------|
| 60 周线 | 周线数据上 `SMA(close, 60)` |
| 60 月线 | 月线数据上 `SMA(close, 60)` |
| 10 周线 / 30 周线 | 周线数据上 `SMA(close, 10/30)` |

---

## 2. MACD（macd.py）

```
DIF   = EMA(close, fast) - EMA(close, slow)
DEA   = EMA(DIF, signal)            # 仅在 DIF 有效段计算
MACD柱 = 2 * (DIF - DEA)
```

- 默认参数：`fast=12, slow=26, signal=9`
- EMA 口径：见 1.2（SMA 种子 + alpha=2/(N+1)）
- MACD 柱采用 **2× 系数**（中国软件通用口径）
- 预热期：DIF 自 `slow-1` 根起有效；DEA/MACD柱 自 `slow-1 + (signal-1)` 根起有效

---

## 3. RSI（rsi.py，Wilder 平滑）

```
delta = close.diff()
gain  = max(delta, 0)
loss  = max(-delta, 0)
avg_gain = WilderSmooth(gain, period)   # 首值 = 前 period 期简单均值
avg_loss = WilderSmooth(loss, period)
RS   = avg_gain / avg_loss
RSI  = 100 - 100 / (1 + RS)
```

- 默认参数：`period=14`
- Wilder 平滑递归：`s[i] = s[i-1] + (v[i] - s[i-1]) / period`
- 边界：`loss=0, gain>0 → RSI=100`；`gain=0, loss>0 → RSI=0`；`gain=loss=0（零波动）→ RSI=50`
- 预热期：前 `period` 根为 NaN（需 `period` 个涨跌幅）
- 测试场景：上涨（→100）、下跌（→0）、横盘/零波动（→50）

---

## 4. 布林带（bollinger.py）

```
MID   = SMA(close, period)
STD   = 总体标准差（ddof=0）
UPPER = MID + num_std * STD
LOWER = MID - num_std * STD
WIDTH = (UPPER - LOWER) / MID
```

- 默认参数：`period=20, num_std=2.0, ddof=0`
- **标准差 ddof=0（总体标准差）**，与通达信/同花顺 BOLL 一致
- 预热期：前 `period-1` 根为 NaN

---

## 5. ATR（atr.py，True Range + Wilder）

```
TR[0] = high - low
TR[i] = max(high-low, |high - prev_close|, |low - prev_close|)
ATR   = WilderSmooth(TR, period)
```

- 默认参数：`period=14`
- 预热期：前 `period-1` 根为 NaN（首根即有 TR）
- **重要**：函数与周期无关。原策略「14 周 ATR」= 周线数据上的 ATR(14)；严禁用日线 ATR 数值冒充周线 ATR

---

## 6. 成交量指标（volume.py）

### 6.1 成交量均线

```
VOL_MA = SMA(volume, window)     # 默认 window=5
```

### 6.2 量比

```
VOL_RATIO = volume / SMA(volume, window)     # 默认 window=5
```

### 6.3 成交量滚动分位数（0~100）

```
对于窗口 [volume[i-window+1 .. i]]（含当前根）：
PCT[i] = count(v <= volume[i]) / window * 100
```

- 默认 `window=52`（对应「过去 52 周」）
- **统计窗口含当前根**，当前值参与统计
- **算法**：经验累积分布（`<=` 计数）
- 语义：100 = 当前为窗口内最大；「位列过去 52 周前 40%」⇔ `PCT >= 60`
- 预热期：前 `window-1` 根为 NaN

---

## 7. 价格指标（price.py，返回值均为百分比）

### 7.1 周期涨跌幅

```
RET = (close - close.shift(periods)) / close.shift(periods) * 100
```

- 使用字段：收盘价（前 `periods` 周期收盘为基准），默认 `periods=1`

### 7.2 价格相对均线偏离率

```
DEV = (close - SMA(close, window)) / SMA(close, window) * 100
```

- 用于「周线收盘价相对 60 周线偏离率」：周线数据上 `deviation_pct(close, 60)`

### 7.3 周期振幅

```
AMP = (high - low) / close.shift(periods) * 100
```

- 使用字段：最高价、最低价，以及前 `periods` 周期收盘价作基准（默认 `periods=1`，即「上周/上月收盘」）
- 与原策略 P1 横盘口径「(最高-最低)/上周收盘 < 4%」一致

### 7.4 序列斜率

```
SLOPE = (series - series.shift(periods)) / series.shift(periods) * 100
```

- 用于「60 月/周线斜率」「连续周线均线斜率」：对 MA 序列取 `slope(ma, 1)`
- 与原策略「(本月60月均线值 − 上月60月均线值) ÷ 上月60月均线值」一致

---

## 8. 指标引擎（engine.py）

`IndicatorEngine(period)` 计算默认指标集，返回 `IndicatorResult(data, meta)`。

| 输出列 | 指标 | 参数 |
|--------|------|------|
| `ma5/10/30/60` | SMA | window |
| `ema12/26` | EMA | window |
| `dif / dea / macd_hist` | MACD | 12/26/9 |
| `rsi14` | RSI | 14 |
| `boll_mid/up/low/width` | 布林带 | 20/2.0/ddof=0 |
| `atr14` | ATR | 14 |
| `vol_ma5 / vol_ratio5 / vol_pct52` | 成交量 | 5/5/52 |
| `ret` | 涨跌幅 | periods=1 |
| `dev_ma60` | 偏离率 | window=60 |
| `amplitude` | 振幅 | periods=1 |
| `slope_ma60` | 斜率 | source=ma60 |

- `period` 为元信息（`day/week/month`），**不做重采样**，调用方先取对应周期 bar 再传入
- `meta` 记录每个指标的参数，供回测与展示追溯

---

## 9. 测试结果

- 指标单元/集成测试：`tests/unit/test_moving_average.py`、`test_indicators.py`、`test_engine.py`
- 全部用手工可复核的已知数据验证数值（线性/非线性序列、涨跌横盘、边界分位等）
- 覆盖：SMA/EMA 手算、MACD 手算、RSI 三态、布林带、ATR 手算、成交量均线/分位边界、长度不足、NaN 输入、重复日期、不改动入参、无未来数据（截断对比）、日/周/月周期隔离、预热期 NaN

---

## 10. 已知限制

- MACD 的 EMA 采用 SMA 种子口径（非通达信「首值种子」），与通达信 MACD 在预热期存在细微差异；策略规则未引用 MACD，不影响策略正确性。
- `volume_percentile` 采用 `<=` 经验分布（含当前根、含等值），分位语义与「前 40%」的对应关系见 6.3。
- 引擎默认指标集为常用集合；后续策略阶段如需额外窗口（如 13 周均量）在策略层按需调用模块函数。
