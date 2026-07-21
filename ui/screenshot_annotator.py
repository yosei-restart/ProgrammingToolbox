"""
快速截图标注工具 - 主窗口 + 工具栏 + 文本框组件 + 标注数据类

使用流程：
  1. 按热键 → ScreenshotAnnotator.show_fullscreen()
  2. 选择工具 → 绘制标注（红框/箭头/文本）
  3. 确认截图 → 复制到剪贴板/另存为
  4. ESC 退出

标注类型：
  - RectAnnotation: CAD 风格四边形红框（4 点）
  - ArrowAnnotation: 标准箭头（起点+终点）
  - TextBoxWidget: 可缩放可拖动文本框
"""

import os
import sys
from typing import Optional, List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTextEdit, QFileDialog, QSizeGrip, QApplication, QDialog, QMessageBox,
)
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QPoint, QRect, QTimer
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QPixmap, QPolygonF,
    QGuiApplication, QKeyEvent, QMouseEvent,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.theme import COLORS, FONT_SMALL, FONT_BODY, FONT_HEADER, get_global_stylesheet
from utils.logging_utils import get_logger
from core.screenshot_engine import capture_screen, copy_to_clipboard, save_screenshot

logger = get_logger(__name__)

# 标注颜色（纯红、正红 #FF0000）
ANNOTATION_COLOR = QColor("#FF0000")
PREVIEW_COLOR = QColor(255, 0, 0, 120)  # 半透明纯红（预览用）


# ──────────────────────────────────────────────
# 标注数据类
# ──────────────────────────────────────────────

class RectAnnotation:
    """红框标注 - 2 点对角矩形（CAD 风格，始终是完整四边形）"""

    def __init__(self):
        self.start: Optional[QPointF] = None
        self.end: Optional[QPointF] = None
        self.color = QColor(ANNOTATION_COLOR)

    def is_complete(self) -> bool:
        return self.start is not None and self.end is not None

    def _rect(self) -> Optional[QRectF]:
        if self.start is None:
            return None
        end = self.end if self.end is not None else self.start
        return QRectF(self.start, end).normalized()

    def draw(self, painter: QPainter, preview: bool = False):
        """绘制红框（始终是完整四边形）"""
        rect = self._rect()
        if rect is None:
            return

        pen = QPen(PREVIEW_COLOR if preview else self.color, 3)
        if preview:
            pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        painter.drawRect(rect)


class ArrowAnnotation:
    """箭头标注 - 起点+终点"""

    def __init__(self):
        self.start: Optional[QPointF] = None
        self.end: Optional[QPointF] = None
        self.color = QColor(ANNOTATION_COLOR)

    def is_complete(self) -> bool:
        return self.start is not None and self.end is not None

    def draw(self, painter: QPainter, preview: bool = False):
        """绘制箭头"""
        if self.start is None:
            return

        pen = QPen(PREVIEW_COLOR if preview else self.color, 3)
        painter.setPen(pen)
        painter.setBrush(self.color)

        if self.end is not None:
            # 画线
            painter.drawLine(self.start, self.end)
            # 画箭头头部
            self._draw_arrowhead(painter, self.start, self.end)
        else:
            # 只有起点，画一个点
            painter.drawEllipse(self.start, 4, 4)

    def _draw_arrowhead(self, painter: QPainter, start: QPointF, end: QPointF):
        """画箭头三角"""
        import math

        angle = math.atan2(end.y() - start.y(), end.x() - start.x())
        arrow_size = 15

        p1 = QPointF(
            end.x() - arrow_size * math.cos(angle - 0.4),
            end.y() - arrow_size * math.sin(angle - 0.4),
        )
        p2 = QPointF(
            end.x() - arrow_size * math.cos(angle + 0.4),
            end.y() - arrow_size * math.sin(angle + 0.4),
        )

        poly = QPolygonF([end, p1, p2])
        painter.drawPolygon(poly)


# ──────────────────────────────────────────────
# 文本框组件
# ──────────────────────────────────────────────

class TextBoxWidget(QWidget):
    """可拖动、可缩放的文本框

    - 四角各有一个缩放手柄
    - 内部为 QTextEdit，光标闪烁等待输入
    - 拖动内部移动位置
    - 拖动四角缩放（维持四边形）
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # 默认大小：宽=屏宽/5，高=屏高/10
        screen = QGuiApplication.primaryScreen().geometry()
        w = screen.width() // 5
        h = screen.height() // 10
        self.resize(w, h)
        # 出现位置：屏幕中央
        self.move(
            (screen.width() - w) // 2,
            (screen.height() - h) // 2,
        )

        self._dragging = False
        self._drag_offset = QPoint()
        self._resizing = False
        self._resize_handle = None  # 'tl', 'tr', 'bl', 'br'

        self._build_ui()

    def _build_ui(self):
        """构建文本框 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 文本编辑区
        self._text_edit = QTextEdit()
        self._text_edit.setPlaceholderText("输入文字…")
        self._text_edit.setFont(FONT_BODY)
        self._text_edit.setStyleSheet(
            f"QTextEdit {{"
            f"  background: rgba(30, 30, 48, 220);"
            f"  color: {COLORS['fg']};"
            f"  border: 2px solid {ANNOTATION_COLOR.name()};"
            f"  border-radius: 4px;"
            f"  padding: 8px;"
            f"}}"
        )
        layout.addWidget(self._text_edit)

        # 四角缩放手柄
        self._handles = {}
        for corner in ("tl", "tr", "bl", "br"):
            handle = QSizeGrip(self)
            handle.setFixedSize(12, 12)
            handle.setStyleSheet(
                f"background: {ANNOTATION_COLOR.name()};"
                f"border-radius: 6px;"
            )
            self._handles[corner] = handle

        self._position_handles()

    def _position_handles(self):
        """定位四角手柄"""
        r = self.rect()
        self._handles["tl"].move(0, 0)
        self._handles["tr"].move(r.width() - 12, 0)
        self._handles["bl"].move(0, r.height() - 12)
        self._handles["br"].move(r.width() - 12, r.height() - 12)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_handles()

    def mousePressEvent(self, event: QMouseEvent):
        """拖动文本框"""
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_offset = event.position().toPoint()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            new_pos = self.mapToParent(event.position().toPoint() - self._drag_offset)
            self.move(new_pos)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._dragging = False

    def get_text(self) -> str:
        return self._text_edit.toPlainText()

    def set_focus(self):
        """聚焦文本框"""
        self._text_edit.setFocus()


# ──────────────────────────────────────────────
# 工具栏
# ──────────────────────────────────────────────

class AnnotationToolbar(QWidget):
    """截图标注工具栏 - 顶部中央悬浮"""

    # 按钮信号
    tool_changed = Signal(str)      # 'rect', 'arrow', 'text', None
    undo_clicked = Signal()
    clear_clicked = Signal()
    copy_clicked = Signal()
    save_clicked = Signal()
    analyze_image_clicked = Signal()     # AI图片分析
    analyze_prompt_clicked = Signal()    # AI提示词分析
    close_clicked = Signal()            # 关闭退出

    # 工具定义：(key, icon, tooltip)
    TOOLS = [
        ("rect", "⬜", "绘制红框 (1)"),
        ("arrow", "➤", "标准箭头 (2)"),
        ("text", "文", "文本框 (3)"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(48)
        self._active_tool: Optional[str] = None
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        # 工具按钮
        self._tool_buttons = {}
        for key, icon, tooltip in self.TOOLS:
            btn = QPushButton(icon)
            btn.setFixedSize(40, 40)
            btn.setToolTip(tooltip)
            btn.setCheckable(True)
            btn.setFont(QFont("Segoe UI Emoji", 14))
            btn.clicked.connect(lambda checked, k=key: self._on_tool_clicked(k))
            self._tool_buttons[key] = btn
            layout.addWidget(btn)

        # 分隔线
        sep = QLabel("|")
        sep.setStyleSheet(f"color: {COLORS['dim']}; background: transparent;")
        layout.addWidget(sep)

        # 撤销
        btn_undo = QPushButton("↶")
        btn_undo.setFixedSize(40, 40)
        btn_undo.setToolTip("撤销 (Ctrl+Z)")
        btn_undo.setFont(QFont("Segoe UI Emoji", 14))
        btn_undo.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['panel']};"
            f"  color: {COLORS['fg']};"
            f"  border: 1px solid {COLORS['border']};"
            f"  border-radius: 8px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {COLORS['border']};"
            f"  border: 1px solid {COLORS['accent']};"
            f"}}"
        )
        btn_undo.clicked.connect(self.undo_clicked.emit)
        layout.addWidget(btn_undo)

        # 清除（垃圾桶图标，避免与关闭按钮 ✕ 混淆）
        btn_clear = QPushButton("🗑")
        btn_clear.setFixedSize(40, 40)
        btn_clear.setToolTip("清除全部 (Ctrl+Shift+Z)")
        btn_clear.setFont(QFont("Segoe UI Emoji", 14))
        btn_clear.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['panel']};"
            f"  color: {COLORS['err']};"
            f"  border: 1px solid {COLORS['border']};"
            f"  border-radius: 8px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {COLORS['border']};"
            f"  border: 1px solid {COLORS['err']};"
            f"}}"
        )
        btn_clear.clicked.connect(self.clear_clicked.emit)
        layout.addWidget(btn_clear)

        # 分隔线
        sep2 = QLabel("|")
        sep2.setStyleSheet(f"color: {COLORS['dim']}; background: transparent;")
        layout.addWidget(sep2)

        # 截图到剪贴板
        btn_copy = QPushButton("📷")
        btn_copy.setFixedSize(40, 40)
        btn_copy.setToolTip("确认截图 - 到剪贴板 (Enter)")
        btn_copy.setFont(QFont("Segoe UI Emoji", 14))
        btn_copy.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['panel']};"
            f"  color: {COLORS['fg']};"
            f"  border: 1px solid {COLORS['border']};"
            f"  border-radius: 8px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {COLORS['ok']};"
            f"  color: white;"
            f"  border: 1px solid {COLORS['ok']};"
            f"}}"
        )
        btn_copy.clicked.connect(self.copy_clicked.emit)
        layout.addWidget(btn_copy)

        # 另存为
        btn_save = QPushButton("💾")
        btn_save.setFixedSize(40, 40)
        btn_save.setToolTip("确认截图 - 另存为 (Ctrl+S)")
        btn_save.setFont(QFont("Segoe UI Emoji", 14))
        btn_save.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['panel']};"
            f"  color: {COLORS['fg']};"
            f"  border: 1px solid {COLORS['border']};"
            f"  border-radius: 8px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {COLORS['accent']};"
            f"  color: white;"
            f"  border: 1px solid {COLORS['accent']};"
            f"}}"
        )
        btn_save.clicked.connect(self.save_clicked.emit)
        layout.addWidget(btn_save)

        # 分隔线
        sep3 = QLabel("|")
        sep3.setStyleSheet(f"color: {COLORS['dim']}; background: transparent;")
        layout.addWidget(sep3)

        # AI图片分析
        btn_analyze_image = QPushButton("🔍")
        btn_analyze_image.setFixedSize(40, 40)
        btn_analyze_image.setToolTip("AI 图片分析 (4)")
        btn_analyze_image.setFont(QFont("Segoe UI Emoji", 14))
        btn_analyze_image.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['panel']};"
            f"  color: {COLORS['fg']};"
            f"  border: 1px solid {COLORS['border']};"
            f"  border-radius: 8px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {COLORS['hl']};"
            f"  color: white;"
            f"  border: 1px solid {COLORS['hl']};"
            f"}}"
        )
        btn_analyze_image.clicked.connect(self.analyze_image_clicked.emit)
        layout.addWidget(btn_analyze_image)

        # AI提示词分析
        btn_analyze_prompt = QPushButton("✨")
        btn_analyze_prompt.setFixedSize(40, 40)
        btn_analyze_prompt.setToolTip("AI 提示词分析 (5)")
        btn_analyze_prompt.setFont(QFont("Segoe UI Emoji", 14))
        btn_analyze_prompt.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['panel']};"
            f"  color: {COLORS['fg']};"
            f"  border: 1px solid {COLORS['border']};"
            f"  border-radius: 8px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {COLORS['warn']};"
            f"  color: {COLORS['head']};"
            f"  border: 1px solid {COLORS['warn']};"
            f"}}"
        )
        btn_analyze_prompt.clicked.connect(self.analyze_prompt_clicked.emit)
        layout.addWidget(btn_analyze_prompt)

        # 分隔线
        sep4 = QLabel("|")
        sep4.setStyleSheet(f"color: {COLORS['dim']}; background: transparent;")
        layout.addWidget(sep4)

        # 关闭退出（独立按钮，非工具）
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(40, 40)
        btn_close.setToolTip("关闭退出 (ESC)")
        btn_close.setFont(QFont("Segoe UI Emoji", 14))
        btn_close.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['err']};"
            f"  color: white;"
            f"  border: 1px solid {COLORS['err']};"
            f"  border-radius: 8px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: #cc0000;"
            f"  border: 1px solid #cc0000;"
            f"}}"
        )
        btn_close.clicked.connect(self.close_clicked.emit)
        layout.addWidget(btn_close)

        self._update_button_styles()

    def _on_tool_clicked(self, tool_key: str):
        """工具按钮点击"""
        if self._active_tool == tool_key:
            self._active_tool = None
        else:
            self._active_tool = tool_key
        self._update_button_styles()
        self.tool_changed.emit(self._active_tool)

    def _update_button_styles(self):
        """更新按钮高亮状态"""
        for key, btn in self._tool_buttons.items():
            if key == self._active_tool:
                btn.setStyleSheet(
                    f"QPushButton {{"
                    f"  background: {ANNOTATION_COLOR.name()};"
                    f"  color: white;"
                    f"  border: 2px solid {ANNOTATION_COLOR.name()};"
                    f"  border-radius: 8px;"
                    f"}}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{"
                    f"  background: {COLORS['panel']};"
                    f"  color: {COLORS['fg']};"
                    f"  border: 1px solid {COLORS['border']};"
                    f"  border-radius: 8px;"
                    f"}}"
                    f"QPushButton:hover {{"
                    f"  background: {COLORS['border']};"
                    f"  border: 1px solid {COLORS['accent']};"
                    f"}}"
                )

    def get_active_tool(self) -> Optional[str]:
        return self._active_tool

    def clear_active_tool(self):
        """清除当前激活工具"""
        self._active_tool = None
        self._update_button_styles()

    def set_position_top_center(self, screen_width: int):
        """定位到屏幕顶部中央"""
        toolbar_w = self.sizeHint().width()
        self.move((screen_width - toolbar_w) // 2, 8)


# ──────────────────────────────────────────────
# 截图标注主窗口
# ──────────────────────────────────────────────

class ScreenshotAnnotator(QWidget):
    """截图标注主窗口 - 全屏画布

    Args:
        on_closed: 关闭后的回调（通常用于重新显示 toolbox 主窗口）
            作用：避免关闭截图窗口后没有任何可见窗口，导致 Qt 应用退出
    """

    # 跨线程信号：子线程完成后通知主线程更新 UI
    # 参数：dialog, title_label, result_text, result
    analysis_done = Signal(object, object, object, str, bool)

    def __init__(self, on_closed=None):
        super().__init__()
        self._bg_pixmap: Optional[QPixmap] = None
        self._annotations: List = []  # 所有完成的标注（RectAnnotation / ArrowAnnotation / TextBoxWidget）
        self._current_tool: Optional[str] = None
        self._drawing_annotation = None  # 正在绘制的标注
        self._text_boxes: List[TextBoxWidget] = []
        self._toolbar: Optional[AnnotationToolbar] = None
        self._on_closed = on_closed  # 关闭后回调（重新显示主窗口）

        self._init_window()
        self._build_ui()
        # 连接跨线程信号：子线程发射 → 主线程槽函数执行
        self.analysis_done.connect(self._on_analysis_done)

    def _init_window(self):
        """初始化无边框窗口（覆盖工作区，不覆盖任务栏）

        使用 availableGeometry() 获取工作区：
        - 工作区 = 屏幕去掉任务栏后的可用区域
        - 这样最终保存的截图不包含 Windows 任务栏
        """
        self.setWindowFlags(
            Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        # 工作区（不含任务栏）
        screen = QGuiApplication.primaryScreen()
        work_geo = screen.availableGeometry() if screen else None
        if work_geo is None:
            # 兜底：使用整个屏幕
            work_geo = screen.geometry() if screen else QRect(0, 0, 1920, 1080)
        self.setGeometry(work_geo)
        self.setStyleSheet(f"background: transparent;")

    def _build_ui(self):
        """构建 UI"""
        # 工具栏
        self._toolbar = AnnotationToolbar(self)
        self._toolbar.set_position_top_center(self.width())

        # 连接信号
        self._toolbar.tool_changed.connect(self._on_tool_changed)
        self._toolbar.undo_clicked.connect(self._undo)
        self._toolbar.clear_clicked.connect(self._clear_all)
        self._toolbar.copy_clicked.connect(self._confirm_copy)
        self._toolbar.save_clicked.connect(self._confirm_save)
        self._toolbar.analyze_image_clicked.connect(self._on_analyze_image)
        self._toolbar.analyze_prompt_clicked.connect(self._on_analyze_prompt)
        self._toolbar.close_clicked.connect(self._on_close_clicked)

    def start(self):
        """启动截图标注

        截图时过滤掉 Windows 任务栏区域（exclude_taskbar=True）
        """
        # 捕获屏幕（工作区，不含任务栏）
        self._bg_pixmap = capture_screen(exclude_taskbar=True)
        if self._bg_pixmap is None:
            logger.error("无法捕获屏幕")
            return

        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFocus()
        # 不调用 grabKeyboard()：它会拦截所有键盘事件，导致文本框无法打字
        # 文本框需要获得键盘焦点才能输入文字
        logger.info("截图标注窗口已启动，等待用户操作")

    # ── 工具切换 ──

    def _on_tool_changed(self, tool: Optional[str]):
        self._current_tool = tool
        # 取消正在进行的绘制
        if self._drawing_annotation is not None:
            self._drawing_annotation = None
            self.update()

        # 如果选了文本工具，立即创建文本框
        if tool == "text":
            self._create_text_box()
            self._toolbar.clear_active_tool()

    # ── 标注操作 ──

    def _create_text_box(self):
        """创建文本框"""
        tb = TextBoxWidget(self)
        tb.show()
        tb.set_focus()
        self._text_boxes.append(tb)

    def _undo(self):
        """撤销最后一个标注"""
        # 优先撤销最后一个文本框
        if self._text_boxes:
            tb = self._text_boxes.pop()
            tb.deleteLater()
            logger.info("撤销最后一个文本框")
            return

        # 再撤销最后一个红框/箭头
        if self._annotations:
            self._annotations.pop()
            logger.info("撤销最后一个标注")
            self.update()

    def _clear_all(self):
        """清除所有标注"""
        for tb in self._text_boxes:
            tb.deleteLater()
        self._text_boxes.clear()
        self._annotations.clear()
        self._drawing_annotation = None
        self.update()
        logger.info("清除所有标注")

    # ── 确认截图 ──

    def _confirm_copy(self):
        """确认截图到剪贴板

        加 try/except 防御：任何异常都记录日志，避免闪退
        """
        try:
            self._hide_overlay_for_capture()
            pixmap = self.grab()
            copy_to_clipboard(pixmap)
        except Exception as e:
            logger.exception("复制到剪贴板失败")
        finally:
            self.close()

    def _confirm_save(self):
        """确认截图另存为

        修复 bug：原实现错误地调用了 copy_to_clipboard（另存为不应复制）
        修复路径：~/桌面 → ~/Desktop（Windows 中文系统下桌面是 Desktop）
        加 try/except 防御：任何异常都记录日志，避免闪退
        """
        try:
            self._hide_overlay_for_capture()
            pixmap = self.grab()

            # 默认保存路径：Windows 桌面是 ~/Desktop
            default_path = os.path.join(
                os.path.expanduser("~"), "Desktop", "screenshot.png"
            )

            # 弹出保存对话框
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "保存截图",
                default_path,
                "PNG 图片 (*.png);;JPEG 图片 (*.jpg);;BMP 图片 (*.bmp)",
            )
            if file_path:
                save_screenshot(pixmap, file_path)
        except Exception as e:
            logger.exception("另存为失败")
        finally:
            self.close()

    def _hide_overlay_for_capture(self):
        """截图前隐藏工具栏"""
        if self._toolbar:
            self._toolbar.hide()

    def _on_close_clicked(self):
        """关闭按钮点击处理 - 直接关闭

        第一性原理分析：
        - 之前在 close() 之前调用 releaseKeyboard() 和 QTimer.singleShot(0)
        - 每次在 close() 之前插入事件循环处理，都会导致鼠标点击被"吞掉"
        - 规律：直接 close() = 2次点击，加 processEvents = +1，加 singleShot = +1
        - 根因：grabKeyboard() 在 Windows 上的副作用——事件循环处理时鼠标事件被吞
        - 解决：直接 close()，releaseKeyboard 在 closeEvent 中处理
        """
        self.close()

    def _on_analyze_image(self):
        """AI 图片分析 - 分析截图内容"""
        self._run_ai_analysis(analysis_type="image")

    def _on_analyze_prompt(self):
        """AI 提示词分析 - 分析图片的生成提示词"""
        self._run_ai_analysis(analysis_type="prompt")

    def _run_ai_analysis(self, analysis_type: str):
        """执行 AI 分析（图片分析或提示词分析）

        Args:
            analysis_type: "image" = 图片内容分析, "prompt" = 提示词分析
        """
        logger.info(f"[AI分析] 开始执行 {analysis_type} 分析")
        try:
            # 获取截图（包含标注）
            self._hide_overlay_for_capture()
            pixmap = self.grab()
            self._toolbar.show()
            logger.info(f"[AI分析] 截图获取成功，尺寸: {pixmap.size()}")

            # 在主线程中将 QPixmap 转为 base64（QPixmap 不能在子线程中使用）
            # 注意：QPixmap.save 需要 QIODevice，不能直接用 Python BytesIO
            import base64
            from PySide6.QtCore import QBuffer, QByteArray
            byte_array = QByteArray()
            buffer = QBuffer(byte_array)
            buffer.open(QBuffer.WriteOnly)
            pixmap.save(buffer, "PNG")
            buffer.close()
            image_data = bytes(byte_array)
            image_base64 = base64.b64encode(image_data).decode("utf-8")
            image_base64 = f"data:image/png;base64,{image_base64}"
            logger.info(f"[AI分析] 图片转为 base64，大小: {len(image_data)} bytes")

            # 创建分析结果对话框（独立窗口，不依赖截图窗口）
            # 修复：用户反馈分析时截图界面阻塞操作，改为独立窗口 + 截图界面隐藏
            dialog = QDialog(None)
            dialog.setWindowTitle("AI 分析结果")
            dialog.setFixedSize(600, 500)
            dialog.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint | Qt.WindowMinimizeButtonHint)
            # 保存引用以便关闭时清理
            self._ai_dialog = dialog

            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(16, 16, 16, 16)
            layout.setSpacing(12)

            title = QLabel("AI 分析中...")
            title.setFont(FONT_HEADER)
            title.setStyleSheet(f"color:{COLORS['accent']};background:transparent")
            layout.addWidget(title)

            result_text = QTextEdit()
            result_text.setReadOnly(True)
            result_text.setFont(FONT_BODY)
            result_text.setStyleSheet(
                f"QTextEdit{{background:{COLORS['panel']};color:{COLORS['fg']};"
                f"border:1px solid {COLORS['border']};border-radius:6px;padding:8px}}"
            )
            layout.addWidget(result_text, 1)

            btn_close = QPushButton("关闭")
            btn_close.setFont(FONT_BODY)
            btn_close.setStyleSheet(
                f"QPushButton{{background:{COLORS['accent']};color:{COLORS['head']};"
                f"border:none;border-radius:6px;padding:8px 20px}}"
            )
            # 关闭对话框时：关闭对话框 + 清理引用 + 调用 on_closed 回调（显示主窗口）
            def _on_dialog_closed():
                dialog.close()
                self._ai_dialog = None
                if self._on_closed:
                    try:
                        self._on_closed()
                    except Exception as e:
                        logger.exception("[AI分析] 关闭回调失败")
            btn_close.clicked.connect(_on_dialog_closed)
            layout.addWidget(btn_close)

            dialog.show()
            logger.info("[AI分析] 分析对话框已显示（独立窗口）")

            # 关闭截图界面，让用户可以继续操作其他工具并查看分析结果
            # 使用 close() 而不是 hide()，彻底退出截图工具
            self.releaseKeyboard()
            self.close()
            logger.info("[AI分析] 截图界面已关闭，AI 分析在后台运行")

            # 对话框关闭事件处理（用户点 X 按钮时也触发回调）
            def _dialog_close_event(event):
                self._ai_dialog = None
                if self._on_closed:
                    try:
                        self._on_closed()
                    except Exception as e:
                        logger.exception("[AI分析] 关闭回调失败")
                QDialog.closeEvent(dialog, event)
            dialog.closeEvent = _dialog_close_event

            # 在子线程中执行 AI 分析（传入 base64，避免在子线程中使用 QPixmap）
            def do_analysis():
                try:
                    logger.info(f"[AI分析] 子线程开始执行，分析类型: {analysis_type}")
                    from ai.ai_client import chat_completion_with_image, load_config

                    config = load_config()
                    logger.info(f"[AI分析] 配置加载成功，enable_ai: {config.enable_ai}")

                    if not config.enable_ai:
                        raise RuntimeError("AI 功能未启用，请先在设置中启用")

                    from ai.prompts_config import get_prompt
                    
                    if analysis_type == "image":
                        prompt = get_prompt("image_analysis")
                    else:
                        prompt = get_prompt("image_prompt_reverse")

                    logger.info("[AI分析] 开始调用 chat_completion_with_image")
                    result = chat_completion_with_image(config, image_base64, prompt)
                    logger.info(f"[AI分析] AI 分析完成，结果长度: {len(result)} 字符")

                    # 通过信号通知主线程更新 UI（信号槽是线程安全的）
                    self.analysis_done.emit(dialog, title, result_text, result, True)
                except Exception as e:
                    error_msg = f"分析失败: {str(e)}"
                    logger.error(f"[AI分析] 分析失败: {e}", exc_info=True)
                    self.analysis_done.emit(dialog, title, result_text, error_msg, False)

            import threading
            threading.Thread(target=do_analysis, daemon=True).start()
            logger.info("[AI分析] 分析线程已启动")

        except Exception as e:
            logger.exception("[AI分析] AI 分析启动失败")
            error_msg = f"AI 分析启动失败: {str(e)}"
            QMessageBox.critical(self, "错误", error_msg)
            # 在结果文本中也显示错误
            if hasattr(self, '_ai_dialog') and self._ai_dialog:
                try:
                    self._ai_dialog.close()
                    self._ai_dialog = None
                except Exception:
                    pass

    def _on_analysis_done(self, dialog, title_label, result_text, result, success):
        """AI 分析完成回调（主线程）

        Args:
            success: True=AI正常返回内容（不管内容是什么），False=程序出错（网络/API/异常等）
        """
        title_label.setText("AI 分析结果")
        result_text.setPlainText(result)
        
        if not success:
            msg_box = QMessageBox(
                QMessageBox.Critical,
                "AI 分析失败",
                result,
                QMessageBox.Ok,
                None
            )
            msg_box.setWindowFlags(msg_box.windowFlags() | Qt.WindowStaysOnTopHint)
            msg_box.exec()

    # ── 鼠标事件（绘制标注）──

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton:
            return
        if self._current_tool is None:
            return

        pos = event.position()

        if self._current_tool == "rect":
            # 按下开始绘制
            self._drawing_annotation = RectAnnotation()
            self._drawing_annotation.start = pos
            self._drawing_annotation.end = pos
            self.update()
        elif self._current_tool == "arrow":
            # 按下开始绘制
            self._drawing_annotation = ArrowAnnotation()
            self._drawing_annotation.start = pos
            self._drawing_annotation.end = pos
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drawing_annotation is not None:
            if isinstance(self._drawing_annotation, (RectAnnotation, ArrowAnnotation)):
                if self._drawing_annotation.start is not None:
                    self._drawing_annotation.end = event.position()
                    self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton:
            return
        if self._drawing_annotation is None:
            return

        if isinstance(self._drawing_annotation, RectAnnotation):
            # 松开完成绘制
            self._drawing_annotation.end = event.position()
            if self._drawing_annotation.is_complete():
                self._annotations.append(self._drawing_annotation)
                self._drawing_annotation = None
                self.update()
        elif isinstance(self._drawing_annotation, ArrowAnnotation):
            # 松开完成绘制
            self._drawing_annotation.end = event.position()
            if self._drawing_annotation.is_complete():
                self._annotations.append(self._drawing_annotation)
                self._drawing_annotation = None
                self.update()

    def _handle_rect_click(self, pos: QPointF):
        pass  # 已改为拖拽式绘制

    def _handle_arrow_click(self, pos: QPointF):
        """箭头点击处理"""
        if self._drawing_annotation is None:
            # 第一点
            self._drawing_annotation = ArrowAnnotation()
            self._drawing_annotation.start = pos
        else:
            # 第二点
            self._drawing_annotation.end = pos
            if self._drawing_annotation.is_complete():
                self._annotations.append(self._drawing_annotation)
                self._drawing_annotation = None
        self.update()

    # ── 键盘事件 ──

    def keyPressEvent(self, event: QKeyEvent):
        """键盘事件处理

        用户要求：取消所有快捷键，避免影响文本框输入
        - 仅保留 ESC 键退出截图（ESC 不会影响文本框输入）
        - 其他快捷键全部取消：Ctrl+Z、Ctrl+Shift+Z、Enter、Ctrl+S、1/2/3
        - 这些功能都可以通过工具栏按钮完成
        """
        # ESC：退出截图（基本操作，不影响打字）
        if event.key() == Qt.Key_Escape:
            self.close()
            return

        # 其他所有键盘事件交给父类处理
        # 父类会自动将键盘事件转发给当前焦点控件（如文本框）
        super().keyPressEvent(event)

    # ── 绘制 ──

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        try:
            # 画背景截图
            if self._bg_pixmap:
                painter.drawPixmap(0, 0, self._bg_pixmap)

            # 画已完成的标注
            for ann in self._annotations:
                ann.draw(painter, preview=False)

            # 画正在绘制的标注（预览）
            if self._drawing_annotation is not None:
                self._drawing_annotation.draw(painter, preview=True)
        finally:
            painter.end()

    def closeEvent(self, event):
        """关闭时清理

        关闭后调用回调（重新显示 toolbox 主窗口）
        避免：截图窗口关闭后没有可见窗口 → Qt 应用退出（看起来像闪退）
        
        注意：AI 分析启动后会调用 hide() 而非 close()，所以不会走到这里。
        只有用户主动 ESC 退出或点关闭按钮时才走到这里。
        """
        logger.info("截图标注窗口关闭")
        
        # 释放键盘捕获
        try:
            self.releaseKeyboard()
        except Exception:
            pass
        
        # 清理文本框
        for tb in self._text_boxes:
            try:
                tb.deleteLater()
            except Exception:
                pass
        self._text_boxes.clear()
        
        super().closeEvent(event)
        
        # 关闭后重新显示主窗口（如果有回调）
        if self._on_closed:
            try:
                self._on_closed()
            except Exception as e:
                logger.exception("关闭回调失败")
