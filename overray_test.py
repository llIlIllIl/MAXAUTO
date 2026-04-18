import sys
import ctypes
import threading
import keyboard

from PyQt6.QtCore import (
    Qt,
    QRect,
    QPropertyAnimation,
    QEasingCurve,
    pyqtSignal,
    QObject,
    QTimer,
)
from PyQt6.QtGui import QFont, QGuiApplication, QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
)


class SignalBridge(QObject):
    close_requested = pyqtSignal()


class CircularProgress(QWidget):
    def __init__(self, size=44, thickness=5, parent=None):
        super().__init__(parent)
        self.progress = 0.0
        self.thickness = thickness
        self.setFixedSize(size, size)

    def set_progress(self, value: float):
        self.progress = max(0.0, min(1.0, value))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        rect = self.rect().adjusted(
            self.thickness,
            self.thickness,
            -self.thickness,
            -self.thickness,
        )

        bg_pen = QPen(QColor(255, 255, 255, 70))
        bg_pen.setWidth(self.thickness)
        painter.setPen(bg_pen)
        painter.drawEllipse(rect)

        fg_pen = QPen(QColor(255, 255, 255, 230))
        fg_pen.setWidth(self.thickness)
        fg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(fg_pen)

        start_angle = 90 * 16
        span_angle = int(-360 * 16 * self.progress)
        painter.drawArc(rect, start_angle, span_angle)

        painter.end()


class OneShotOverlay(QWidget):
    def __init__(
        self,
        text="첫 번째 줄\n두 번째 줄\n세 번째 줄",
        width=700,
        min_height=128,
        margin_top=24,
        margin_right=24,
        padding_x=22,
        padding_y=18,
        font_family="Malgun Gothic",
        font_size=19,
        duration_seconds=10,
        progress_size=44,
    ):
        super().__init__()

        self.text_value = text
        self.overlay_width = width
        self.overlay_min_height = min_height
        self.margin_top = margin_top
        self.margin_right = margin_right
        self.padding_x = padding_x
        self.padding_y = padding_y
        self.font_family = font_family
        self.font_size = font_size
        self.duration_seconds = duration_seconds
        self.progress_size = progress_size

        self.is_closing = False
        self.total_duration_ms = max(1, int(self.duration_seconds * 1000))
        self.elapsed_ms = 0

        self.bridge = SignalBridge()
        self.bridge.close_requested.connect(self.start_close_animation)

        self._build_ui()
        self._adjust_size_for_text()
        self._init_positions()
        self._init_animation()
        self._apply_click_through()
        self._init_progress_timer()

    def _build_ui(self):
        self.setWindowTitle("One Shot Overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        self.container = QWidget(self)
        self.container.setObjectName("overlayContainer")
        self.container.setStyleSheet("""
            #overlayContainer {
                background-color: rgba(0, 0, 0, 128);
                border-radius: 16px;
            }
        """)

        self.layout_root = QVBoxLayout(self)
        self.layout_root.setContentsMargins(0, 0, 0, 0)
        self.layout_root.addWidget(self.container)

        self.container_layout = QHBoxLayout(self.container)
        self.container_layout.setContentsMargins(
            self.padding_x, self.padding_y, self.padding_x, self.padding_y
        )
        self.container_layout.setSpacing(16)
        self.container_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.progress_widget = CircularProgress(
            size=self.progress_size,
            thickness=5,
            parent=self.container
        )
        self.container_layout.addWidget(
            self.progress_widget,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        self.text_wrapper = QWidget(self.container)
        self.text_wrapper.setStyleSheet("background: transparent;")

        self.text_wrapper_layout = QVBoxLayout(self.text_wrapper)
        self.text_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        self.text_wrapper_layout.setSpacing(0)
        self.text_wrapper_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.label = QLabel(self.text_value, self.text_wrapper)
        self.label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        font = QFont(self.font_family, self.font_size)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        self.label.setFont(font)

        self.label.setStyleSheet("""
            QLabel {
                color: white;
                background: transparent;
                padding: 0px;
                margin: 0px;
            }
        """)

        self.text_wrapper_layout.addWidget(self.label, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.container_layout.addWidget(self.text_wrapper, stretch=1)

    def _adjust_size_for_text(self):
        text_area_width = (
            self.overlay_width
            - (self.padding_x * 2)
            - self.progress_size
            - self.container_layout.spacing()
        )

        self.label.setFixedWidth(max(120, text_area_width))
        self.label.adjustSize()

        label_height = self.label.sizeHint().height()
        content_height = max(label_height, self.progress_size)
        overlay_height = max(
            self.overlay_min_height,
            content_height + (self.padding_y * 2)
        )

        self.setFixedSize(self.overlay_width, overlay_height)
        self.container.setFixedSize(self.overlay_width, overlay_height)
        self.text_wrapper.setFixedHeight(content_height)

    def _init_positions(self):
        screen = QGuiApplication.primaryScreen().availableGeometry()

        self.visible_x = screen.x() + screen.width() - self.width() - self.margin_right
        self.visible_y = screen.y() + self.margin_top

        self.hidden_x = screen.x() + screen.width() + 20
        self.hidden_y = self.visible_y

        self.setGeometry(self.hidden_x, self.hidden_y, self.width(), self.height())

    def _init_animation(self):
        self.anim = QPropertyAnimation(self, b"geometry")
        self.anim.finished.connect(self._on_animation_finished)

    def _init_progress_timer(self):
        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(16)
        self.progress_timer.timeout.connect(self._update_progress)

    def _apply_click_through(self):
        if sys.platform != "win32":
            return

        hwnd = int(self.winId())

        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020

        user32 = ctypes.windll.user32
        current_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(
            hwnd,
            GWL_EXSTYLE,
            current_style | WS_EX_LAYERED | WS_EX_TRANSPARENT
        )

    def show_with_animation(self):
        self.show()

        self.anim.stop()
        self.anim.setStartValue(QRect(self.hidden_x, self.hidden_y, self.width(), self.height()))
        self.anim.setEndValue(QRect(self.visible_x, self.visible_y, self.width(), self.height()))
        self.anim.setDuration(520)
        self.anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self.anim.start()

        self.progress_widget.set_progress(0.0)
        self.elapsed_ms = 0
        self.progress_timer.start()

    def _update_progress(self):
        if self.is_closing:
            self.progress_timer.stop()
            return

        self.elapsed_ms += self.progress_timer.interval()
        progress = self.elapsed_ms / self.total_duration_ms
        self.progress_widget.set_progress(progress)

        if progress >= 1.0:
            self.progress_timer.stop()
            self.start_close_animation()

    def start_close_animation(self):
        if self.is_closing:
            return

        self.is_closing = True
        self.progress_timer.stop()

        self.anim.stop()
        self.anim.setStartValue(self.geometry())
        self.anim.setEndValue(QRect(self.hidden_x, self.hidden_y, self.width(), self.height()))
        self.anim.setDuration(360)
        self.anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self.anim.start()

    def _on_animation_finished(self):
        current_x = self.geometry().x()

        if self.is_closing and current_x >= self.hidden_x:
            QApplication.instance().quit()

    def start_enter_listener(self):
        def worker():
            keyboard.wait("enter")
            self.bridge.close_requested.emit()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    overlay = OneShotOverlay(
        text=(
            "작업이 완료되었습니다.\n"
            "결과를 확인해 주세요."
            ),
        width=400,
        min_height=20,
        margin_top=28,
        margin_right=28,
        padding_x=22,
        padding_y=18,
        font_family="Malgun Gothic",
        font_size=12,
        duration_seconds=10,
        progress_size=46,
    )

    overlay.show_with_animation()
    overlay.start_enter_listener()

    sys.exit(app.exec())
