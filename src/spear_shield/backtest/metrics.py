"""绩效公式；夏普按实际观测日收益样本估计，默认无风险利率为0。"""

import numpy as np
import pandas as pd


def performance(curve, trades, initial_cash):
    if curve.empty:
        raise ValueError("无资金曲线")
    equity = curve.equity.astype(float)
    # 初始资金也进入高水位，第一天的成本不可从回撤中消失。
    values = pd.Series([initial_cash, *equity])
    returns = values.pct_change().dropna()
    dd = values / values.cummax() - 1
    # 初始资金对应首个交易日开盘，终值对应最后一个交易日收盘，时间基准一致。
    start = pd.Timestamp(curve.iloc[0].date) + pd.Timedelta(hours=9, minutes=30)
    end = pd.Timestamp(curve.iloc[-1].date) + pd.Timedelta(hours=15)
    days = (end - start).total_seconds() / 86400
    total = equity.iloc[-1] / initial_cash - 1
    years = days / 365.2425
    # 短于一年不展示高度不稳定的年化外推，累计收益仍完整保留。
    annual = float(np.expm1(np.log1p(total) / years)) if years >= 1 else None
    if annual is not None and not np.isfinite(annual):
        annual = None
    std = returns.std(ddof=1)
    sharpe = (
        float(returns.mean() / std * np.sqrt(252))
        if len(returns) > 1 and std > 1e-15
        else None
    )
    closed = [t["realized_pnl"] for t in trades if t["side"] == "sell"]
    wins, losses = [x for x in closed if x > 0], [x for x in closed if x < 0]
    return {
        "total_return": float(total),
        "annual_return": annual,
        "max_drawdown": float(dd.min()),
        "sharpe": sharpe,
        "win_rate": len(wins) / len(closed) if closed else None,
        "payoff_ratio": (
            float(np.mean(wins) / -np.mean(losses)) if wins and losses else None
        ),
        "profit_factor": float(sum(wins) / -sum(losses)) if losses else None,
        "trade_count": len(trades),
        "closed_trade_count": len(closed),
        "fees": sum(t["fee"] for t in trades),
        "slippage_cost": sum(t["slippage_cost"] for t in trades),
        "final_equity": float(equity.iloc[-1]),
    }
