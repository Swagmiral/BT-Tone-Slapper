from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QEnterEvent,
    QIcon,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPolygon,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
    QTableWidget,
    QWidget,
)

from .fonts import emphasis_font
from .resources import asset_path
from .theme import COLORS


class MinimalComboBox(QComboBox):
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(
            QColor(COLORS["disabled"] if not self.isEnabled() else COLORS["text"])
        )
        center_x = self.width() - 17
        center_y = self.height() // 2
        painter.drawPolygon(
            QPolygon(
                (
                    QPoint(center_x - 5, center_y - 2),
                    QPoint(center_x + 5, center_y - 2),
                    QPoint(center_x, center_y + 3),
                )
            )
        )


class RoundedPanel(QFrame):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        corner_radius: int = 8,
    ) -> None:
        super().__init__(parent)
        self.corner_radius = corner_radius
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)


class AdaptiveButtonRow(QWidget):
    def __init__(
        self,
        button: QWidget,
        parent: QWidget | None = None,
        *,
        maximum_button_width: int = 480,
    ) -> None:
        super().__init__(parent)
        self.button = button
        self.maximum_button_width = maximum_button_width
        self.expanded = False
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addWidget(button)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_expanded(self, expanded: bool) -> None:
        if self.expanded == expanded:
            return
        self.expanded = expanded
        self._update_margins()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_margins()

    def _update_margins(self) -> None:
        horizontal_margin = (
            0
            if self.expanded
            else max(0, (self.width() - self.maximum_button_width) // 2)
        )
        self._layout.setContentsMargins(
            horizontal_margin,
            0,
            horizontal_margin,
            0,
        )
        self._layout.activate()


class ProgressButton(QPushButton):
    progress_mode_changed = Signal(bool)

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._available = False
        self._progress = 0.0
        self._progress_active = False
        self._success = False
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(emphasis_font(14))
        self.setMinimumHeight(46)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_enabled(self, enabled: bool) -> None:
        self.setEnabled(enabled)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if enabled
            else Qt.CursorShape.ArrowCursor
        )
        self.update()

    def set_available(self, available: bool) -> None:
        self._available = available
        self.update()

    def begin(self, text: str) -> None:
        self._progress = 0.0
        self._set_progress_active(True)
        self._success = False
        self.setText(text)
        self.update()

    def set_progress(self, fraction: float, text: str) -> None:
        self._progress = max(0.0, min(1.0, fraction))
        self._set_progress_active(True)
        self._success = False
        self.setText(text)
        self.update()

    def complete(self, text: str = "Success!") -> None:
        self._progress = 1.0
        self._set_progress_active(False)
        self._success = True
        self.setText(text)
        self.update()

    def reset(self, *, enabled: bool) -> None:
        self.set_enabled(enabled)
        self.set_available(enabled)
        self._progress = 0.0
        self._set_progress_active(False)
        self._success = False
        self.setText("Upload")
        self.update()

    def _set_progress_active(self, active: bool) -> None:
        if self._progress_active == active:
            return
        self._progress_active = active
        self.progress_mode_changed.emit(active)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bounds = QRectF(self.rect())
        radius = 0.0 if self._progress_active else 8.0
        shape = QPainterPath()
        shape.addRoundedRect(bounds, radius, radius)

        if self._success:
            background = COLORS["success"]
        elif self._progress_active:
            background = COLORS["surface_hover"]
        elif not self._available:
            background = "#2a2a2a"
        elif self.isDown():
            background = COLORS["accent_pressed"]
        elif self.underMouse():
            background = COLORS["accent_hover"]
        else:
            background = COLORS["accent"]
        painter.fillPath(shape, QColor(background))

        if self._progress_active and self._progress > 0:
            fill_width = round(bounds.width() * self._progress)
            painter.save()
            painter.setClipPath(shape)
            painter.fillRect(
                QRectF(0, 0, fill_width, bounds.height()),
                QColor(COLORS["accent"]),
            )
            painter.restore()

        painter.setFont(self.font())
        painter.setPen(
            QColor(
                "#ffffff"
                if self._available or self._progress_active or self._success
                else COLORS["disabled"]
            )
        )
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


class ResetButton(QPushButton):
    hovered = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Reset", parent)
        self._enabled_for_row = True
        self._row_hovered = False
        self._normal_icon = QIcon(str(asset_path("icons/material_refresh_accent_18.png")))
        self._hover_icon = QIcon(str(asset_path("icons/material_refresh_hover_18.png")))
        self._disabled_icon = QIcon(
            str(asset_path("icons/material_refresh_disabled_18.png"))
        )
        self.setObjectName("resetButton")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setFont(emphasis_font(10))
        self.setIconSize(QSize(18, 18))
        self._refresh()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled_for_row = enabled
        self.setEnabled(enabled)
        self._refresh()

    def set_row_hover(self, hovered: bool) -> None:
        self._row_hovered = hovered
        self._refresh()

    def enterEvent(self, event: QEnterEvent) -> None:
        self.hovered.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self.hovered.emit(False)
        super().leaveEvent(event)

    def _refresh(self) -> None:
        if not self._enabled_for_row:
            color = COLORS["disabled"]
            icon = self._disabled_icon
        elif self._row_hovered or self.underMouse():
            color = "#ffffff"
            icon = self._hover_icon
        else:
            color = COLORS["accent_hover"]
            icon = self._normal_icon
        self.setIcon(icon)
        self.setStyleSheet(
            "QPushButton {"
            "min-height: 0; border: 0; padding: 0; background: transparent;"
            f"color: {color}; font-size: 10pt; font-weight: 700;"
            "}"
            "QPushButton:hover, QPushButton:pressed, QPushButton:disabled {"
            "border: 0; background: transparent;"
            f"color: {color};"
            "}"
        )


class PromptItemDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index) -> None:
        background = index.data(Qt.ItemDataRole.BackgroundRole)
        if isinstance(background, QBrush) and background.color().alpha() > 0:
            painter.fillRect(option.rect, background)
        super().paint(painter, option, index)


class PromptTable(QTableWidget):
    row_hovered = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setItemDelegate(PromptItemDelegate(self))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.viewport().setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground,
            True,
        )
        self.viewport().setAutoFillBackground(False)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self.row_hovered.emit(self.rowAt(event.position().toPoint().y()))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self.row_hovered.emit(-1)
        super().leaveEvent(event)


class FlyingTip(QLabel):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFont(emphasis_font(10))
        self.setStyleSheet(
            "QLabel {"
            "border: 0;"
            "padding: 3px 8px;"
            "background: #000000;"
            "color: #ffffff;"
            "}"
        )
        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._animation = QParallelAnimationGroup(self)
        self._position_animation = QPropertyAnimation(self, b"pos", self)
        self._opacity_animation = QPropertyAnimation(
            self._opacity,
            b"opacity",
            self,
        )
        self._animation.addAnimation(self._position_animation)
        self._animation.addAnimation(self._opacity_animation)
        self._animation.finished.connect(self.hide)
        self.hide()

    def show_for(self, anchor: QWidget, text: str) -> None:
        self._animation.stop()
        self.setText(text)
        self.adjustSize()

        anchor_top_left = anchor.mapTo(self.parentWidget(), QPoint(0, 0))
        start = QPoint(
            anchor_top_left.x() + (anchor.width() - self.width()) // 2,
            anchor_top_left.y() - self.height() + 20,
        )
        end = QPoint(start.x(), start.y() - 30)

        self.move(start)
        self._opacity.setOpacity(1.0)
        self.raise_()
        self.show()

        duration = 1620
        self._position_animation.setDuration(duration)
        self._position_animation.setStartValue(start)
        self._position_animation.setEndValue(end)
        self._position_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._opacity_animation.setDuration(duration)
        self._opacity_animation.setStartValue(1.0)
        self._opacity_animation.setKeyValueAt(0.68, 1.0)
        self._opacity_animation.setEndValue(0.0)
        self._animation.start()

    def dismiss(self) -> None:
        self._animation.stop()
        self.hide()
