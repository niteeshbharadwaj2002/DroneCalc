"""Reusable widgets: number fields, mass bar, metric grid, notices, themed plots."""

from __future__ import annotations

from collections.abc import Iterable

import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

PALETTE = [
    "#7F77DD",
    "#5DCAA5",
    "#EF9F27",
    "#378ADD",
    "#D4537E",
    "#888780",
    "#B4B2A9",
    "#D85A30",
]
SERIES_COLORS = ["#378ADD", "#D85A30", "#1D9E75", "#7F77DD"]


def is_dark() -> bool:
    app = QApplication.instance()
    return bool(app) and app.palette().window().color().lightness() < 128


# ---- number fields -------------------------------------------------------------------------


class NumberField(QWidget):
    """A spin box, optionally paired with a slider. ``valueChanged`` fires on user edits only."""

    valueChanged = Signal(float)

    def __init__(
        self,
        minimum: float,
        maximum: float,
        value: float,
        step: float = 1.0,
        decimals: int = 1,
        suffix: str = "",
        slider: bool = True,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._step = step
        self.spin = QDoubleSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(step)
        self.spin.setSuffix(suffix)
        self.spin.setKeyboardTracking(False)
        self.spin.setMinimumWidth(110)
        self.spin.setValue(value)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.slider: QSlider | None = None
        if slider:
            self.slider = QSlider(Qt.Horizontal)
            self.slider.setRange(0, round((maximum - minimum) / step))
            self.slider.setMinimumWidth(160)
            self.slider.valueChanged.connect(self._from_slider)
            lay.addWidget(self.slider, 1)
        lay.addWidget(self.spin)
        self.spin.valueChanged.connect(self._from_spin)
        self._sync_slider()

    def value(self) -> float:
        return self.spin.value()

    def setValue(self, value: float) -> None:
        """Set programmatically without emitting ``valueChanged``."""
        self.spin.blockSignals(True)
        self.spin.setValue(value)
        self.spin.blockSignals(False)
        self._sync_slider()

    def _sync_slider(self) -> None:
        if self.slider is not None:
            self.slider.blockSignals(True)
            self.slider.setValue(round((self.spin.value() - self.spin.minimum()) / self._step))
            self.slider.blockSignals(False)

    def _from_slider(self, pos: int) -> None:
        self.spin.blockSignals(True)
        self.spin.setValue(self.spin.minimum() + pos * self._step)
        self.spin.blockSignals(False)
        self.valueChanged.emit(self.spin.value())

    def _from_spin(self, value: float) -> None:
        self._sync_slider()
        self.valueChanged.emit(value)


class OptionalNumberField(QWidget):
    """A checkbox that enables a number; ``value()`` is ``None`` while unchecked."""

    valueChanged = Signal(object)

    def __init__(self, label: str, minimum: float, maximum: float, default: float, **kw):
        super().__init__()
        self.check = QCheckBox(label)
        self.field = NumberField(minimum, maximum, default, slider=False, **kw)
        self.field.setEnabled(False)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.check, 1)
        lay.addWidget(self.field)
        self.check.toggled.connect(self._toggled)
        self.field.valueChanged.connect(lambda _v: self.valueChanged.emit(self.value()))

    def _toggled(self, on: bool) -> None:
        self.field.setEnabled(on)
        self.valueChanged.emit(self.value())

    def value(self) -> float | None:
        return self.field.value() if self.check.isChecked() else None

    def setValue(self, value: float | None) -> None:
        self.check.blockSignals(True)
        self.check.setChecked(value is not None)
        self.check.blockSignals(False)
        self.field.setEnabled(value is not None)
        if value is not None:
            self.field.setValue(value)


# ---- mass bar ------------------------------------------------------------------------------


class MassBar(QWidget):
    """Stacked horizontal bar of mass contributions with a legend."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._parts: list[tuple[str, float]] = []
        self.setMinimumHeight(64)

    def setParts(self, parts: Iterable[tuple[str, float]]) -> None:
        self._parts = [(n, v) for n, v in parts if v > 0]
        self.update()

    def parts(self) -> list[tuple[str, float]]:
        return list(self._parts)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        total = sum(v for _, v in self._parts)
        w, bar_h = self.width(), 22
        text_color = self.palette().text().color()
        if total <= 0:
            p.setPen(text_color)
            p.drawText(QRectF(0, 0, w, bar_h), Qt.AlignVCenter, "No data")
            return
        x = 0.0
        legend_x, legend_y = 0.0, bar_h + 8
        fm = QFontMetrics(self.font())
        for i, (name, grams) in enumerate(self._parts):
            seg = w * grams / total
            color = QColor(PALETTE[i % len(PALETTE)])
            p.fillRect(QRectF(x, 0, seg, bar_h), color)
            x += seg
            label = f"{name} {grams:.0f} g"
            lw = fm.horizontalAdvance(label) + 28
            if legend_x + lw > w and legend_x > 0:
                legend_x, legend_y = 0.0, legend_y + fm.height() + 4
            p.fillRect(QRectF(legend_x, legend_y + 2, 10, 10), color)
            p.setPen(text_color)
            p.drawText(QRectF(legend_x + 14, legend_y, lw, fm.height()), Qt.AlignVCenter, label)
            legend_x += lw
        self.setMinimumHeight(int(legend_y + fm.height() + 8))


# ---- metric grid and notices ---------------------------------------------------------------


class MetricGrid(QWidget):
    """Two-column grid of label/value pairs, arranged in ``columns`` blocks."""

    def __init__(self, columns: int = 2, parent: QWidget | None = None):
        super().__init__(parent)
        self._columns = columns
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(18)
        self._values: dict[str, QLabel] = {}

    def setItems(self, items: list[tuple[str, str]]) -> None:
        while self._grid.count():
            w = self._grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._values.clear()
        rows = -(-len(items) // self._columns)
        for i, (label, value) in enumerate(items):
            col, row = divmod(i, rows) if rows else (0, 0)
            name = QLabel(label)
            name.setStyleSheet("color: palette(mid);")
            val = QLabel(value)
            val.setStyleSheet("font-weight: 600;")
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._grid.addWidget(name, row, col * 2)
            self._grid.addWidget(val, row, col * 2 + 1)
            self._values[label] = val

    def text(self, label: str) -> str:
        return self._values[label].text()

    def labels(self) -> list[str]:
        return list(self._values)


class NoticeList(QWidget):
    """Violations (red) and warnings (amber), one line each; hidden when empty."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(2)
        self._labels: list[QLabel] = []

    def setNotices(self, violations: Iterable[str], warnings: Iterable[str]) -> None:
        for lbl in self._labels:
            lbl.deleteLater()
        self._labels.clear()
        bad = "#E06C6C" if is_dark() else "#A32D2D"
        warn = "#E5A93C" if is_dark() else "#854F0B"
        for text, color, tag in [(v, bad, "Violation") for v in violations] + [
            (w, warn, "Warning") for w in warnings
        ]:
            lbl = QLabel(f"<b>{tag}:</b> {text}")
            lbl.setStyleSheet(f"color: {color};")
            lbl.setWordWrap(True)
            self._lay.addWidget(lbl)
            self._labels.append(lbl)
        self.setVisible(bool(self._labels))

    def texts(self) -> list[str]:
        return [lbl.text() for lbl in self._labels]


# ---- plots ---------------------------------------------------------------------------------


def make_plot(title: str, xlabel: str, ylabel: str, height: int = 190) -> pg.PlotWidget:
    """A themed pyqtgraph plot that follows the application's light/dark palette."""
    dark = is_dark()
    fg = "#D8D8D8" if dark else "#333333"
    pw = pg.PlotWidget(background=None)
    pw.setBackground("#1e1e1e" if dark else "#ffffff")
    pw.setMinimumHeight(height)
    pi = pw.getPlotItem()
    pi.setTitle(title, color=fg, size="10pt")
    pi.setLabel("bottom", xlabel, color=fg)
    pi.setLabel("left", ylabel, color=fg)
    pi.showGrid(x=True, y=True, alpha=0.25)
    for axis in ("bottom", "left"):
        ax = pi.getAxis(axis)
        ax.setPen(fg)
        ax.setTextPen(fg)
    pi.setMenuEnabled(False)
    return pw


def plot_curve(pw: pg.PlotWidget, xs, ys, color: str, name: str | None = None, width: int = 2):
    """Plot a curve skipping ``None`` y values (points where the build cannot hover)."""
    pts = [(x, y) for x, y in zip(xs, ys) if y is not None]
    if not pts:
        return None
    x, y = zip(*pts)
    return pw.plot(list(x), list(y), pen=pg.mkPen(color, width=width), name=name)
