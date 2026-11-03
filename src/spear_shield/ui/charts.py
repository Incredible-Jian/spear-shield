"""Qt原生行情图：K线/均线/指标，只绘制调用方提供的真实缓存。"""

from __future__ import annotations

import math
import pandas as pd
from PySide6.QtCore import QDateTime, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtCharts import (
    QChart,
    QChartView,
    QLineSeries,
    QDateTimeAxis,
    QValueAxis,
    QCandlestickSeries,
    QCandlestickSet,
    QPieSeries,
)

from .theme import COLORS


class MarketChart(QChartView):
    def __init__(self, parent=None, height=290):
        super().__init__(parent)
        self.setMinimumHeight(height)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRubberBand(QChartView.RectangleRubberBand)
        self.draw(pd.DataFrame(), title="暂无真实缓存")

    def draw(
        self,
        frame,
        title="",
        lines=("ma60",),
        candles=False,
        thresholds=(),
        max_points=180,
    ):
        old = self.chart()
        chart = QChart()
        chart.setAnimationOptions(QChart.NoAnimation)
        chart.setBackgroundBrush(QColor(COLORS["card"]))
        chart.setPlotAreaBackgroundBrush(QColor(COLORS["panel"]))
        chart.setPlotAreaBackgroundVisible(True)
        chart.setTitle(title)
        chart.setTitleBrush(QColor(COLORS["text_muted"]))
        chart.legend().setLabelColor(QColor(COLORS["text_muted"]))
        self.setChart(chart)
        if old:
            old.deleteLater()
        if frame.empty:
            return
        data = (frame if max_points is None else frame.tail(max_points)).reset_index(
            drop=True
        )
        times = [
            pd.Timestamp(d).tz_localize("Asia/Shanghai").timestamp() * 1000
            for d in data.date
        ]
        axis_x = QDateTimeAxis()
        axis_x.setFormat("yy-MM-dd")
        axis_x.setTickCount(5)
        axis_x.setLabelsColor(QColor(COLORS["text_faint"]))
        axis_x.setGridLineColor(QColor(COLORS["border"]))
        axis_y = QValueAxis()
        axis_y.setLabelsColor(QColor(COLORS["text_muted"]))
        axis_y.setGridLineColor(QColor(COLORS["border"]))
        axis_y.setLabelFormat("%.2f")
        chart.addAxis(axis_x, Qt.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignLeft)
        values = []
        if candles:
            series = QCandlestickSeries()
            series.setName("OHLC")
            series.setIncreasingColor(QColor(COLORS["up"]))
            series.setDecreasingColor(QColor(COLORS["down"]))
            for i, row in data.iterrows():
                if all(
                    pd.notna(row[k]) and math.isfinite(row[k])
                    for k in ("open", "high", "low", "close")
                ):
                    series.append(
                        QCandlestickSet(
                            row.open, row.high, row.low, row.close, times[i]
                        )
                    )
                    values.extend([row.low, row.high])
            chart.addSeries(series)
            series.attachAxis(axis_x)
            series.attachAxis(axis_y)
        colors = (COLORS["accent"], COLORS["warn"], COLORS["down"], COLORS["up"])
        for idx, col in enumerate(lines):
            if col not in data:
                continue
            segment = None
            first = True
            for t, v in zip(times, data[col]):
                if pd.isna(v) or not math.isfinite(v):
                    segment = None
                    continue
                if segment is None:
                    segment = QLineSeries()
                    segment.setName(col)
                    segment.setPen(QPen(QColor(colors[idx % len(colors)]), 1.7))
                    chart.addSeries(segment)
                    segment.attachAxis(axis_x)
                    segment.attachAxis(axis_y)
                    if not first:
                        for marker in chart.legend().markers(segment):
                            marker.setVisible(False)
                    first = False
                segment.append(t, float(v))
                values.append(float(v))
        for value in thresholds:
            series = QLineSeries()
            series.setName(f"阈值 {value}")
            pen = QPen(QColor(COLORS["warn"]), 1, Qt.DashLine)
            series.setPen(pen)
            series.append(times[0], value)
            series.append(times[-1], value)
            chart.addSeries(series)
            series.attachAxis(axis_x)
            series.attachAxis(axis_y)
            values.append(value)
        pad = max(86400000, (times[-1] - times[0]) * 0.02)
        axis_x.setRange(
            QDateTime.fromMSecsSinceEpoch(int(times[0] - pad)),
            QDateTime.fromMSecsSinceEpoch(int(times[-1] + pad)),
        )
        if values:
            lo, hi = min(values), max(values)
            margin = max((hi - lo) * 0.1, abs(hi) * 0.005, 0.01)
            axis_y.setRange(lo - margin, hi + margin)


class AllocationChart(QChartView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(240)
        self.setRenderHint(QPainter.Antialiasing)
        self.draw({}, "配置数据不可用")

    def draw(self, weights, title):
        old = self.chart()
        chart = QChart()
        chart.setBackgroundBrush(QColor(COLORS["card"]))
        chart.setTitle(title)
        chart.setTitleBrush(QColor(COLORS["text_muted"]))
        chart.legend().setLabelColor(QColor(COLORS["text_muted"]))
        self.setChart(chart)
        if old:
            old.deleteLater()
        if not weights:
            return
        series = QPieSeries()
        series.setHoleSize(0.63)
        colors = (
            COLORS["accent"],
            COLORS["warn"],
            COLORS["down"],
            COLORS["neutral"],
            COLORS["up"],
        )
        for i, (label, value) in enumerate(weights.items()):
            if value > 0 and math.isfinite(value):
                piece = series.append(f"{label} {value*100:.1f}%", value)
                piece.setColor(QColor(colors[i % len(colors)]))
                piece.setBorderColor(QColor(COLORS["card"]))
        chart.addSeries(series)
