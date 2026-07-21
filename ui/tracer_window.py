"""
变量生命周期追踪器 - 静态追踪 UI 窗口
PySide6 (LGPLv3) - GitHub Dark 主题，高对比度

改进点：
1. GitHub Dark 官方配色，高对比度文字
2. 卡片链使用渐变色表示进度递进
3. 每个字段都有复制按钮 + 所有文字可鼠标选中复制
4. 导出按钮旁加"打开报告"按钮，保存后才能点击
5. 底部不确定进度条
"""

import os
import subprocess
import threading
import colorsys
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QLineEdit, QScrollArea, QFrame, QFileDialog, QProgressBar,
    QApplication, QSizePolicy, QTextEdit,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QFont

from utils.theme import COLORS, FONT_TITLE, FONT_HEADER, FONT_BODY, FONT_MONO, FONT_SMALL, apply_text_selectable
from utils.logging_utils import get_logger
from core.lifecycle_tracer import (
    extract_variable_events, get_all_variable_names, fuzzy_match,
    LifecycleResult, VariableEvent, EventType,
)
from core.html_exporter import export_lifecycle_html

logger = get_logger(__name__)


def _generate_gradient_colors(count: int, start_hue: float = 0.35, end_hue: float = 0.95) -> list:
    """生成渐变色列表，从绿色（诞生）到红色（消亡）"""
    if count <= 1:
        return ["#3fb950"]
    colors = []
    for i in range(count):
        ratio = i / (count - 1)
        hue = start_hue + (end_hue - start_hue) * ratio
        rgb = colorsys.hsv_to_rgb(hue % 1.0, 0.65, 0.85)
        hex_color = "#{:02X}{:02X}{:02X}".format(
            int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255)
        )
        colors.append(hex_color)
    return colors


def _make_selectable(label: QLabel) -> QLabel:
    """让 QLabel 文字可以被鼠标选中复制"""
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    label.setCursor(Qt.IBeamCursor)
    return label


class TracerSignals(QObject):
    """变量追踪器信号"""
    status = Signal(str, str)
    scan_done = Signal(list)
    trace_done = Signal(object)
    ai_done = Signal(str)
    ai_error = Signal(str)
    trace_error = Signal(str)
    busy_changed = Signal(bool)


class VariableTracerWindow(QWidget):
    """变量生命周期静态追踪器窗口"""

    def __init__(self, on_back=None):
        super().__init__()
        self.setWindowTitle("变量生命周期追踪器 - 静态分析")
        self.resize(1200, 800)
        self.setMinimumSize(900, 600)
        self._on_back = on_back
        self._folder_path = ""
        self._all_vars = []
        self._result = None
        self._html_path = None

        # 应用全局样式
        self.setStyleSheet(self._global_style())

        self.sig = TracerSignals()
        self.sig.status.connect(self._on_status)
        self.sig.scan_done.connect(self._on_scan_done)
        self.sig.trace_done.connect(self._on_trace_done)
        self.sig.trace_error.connect(self._on_trace_error)
        self.sig.busy_changed.connect(self._on_busy)
        self.sig.ai_done.connect(self._on_ai_done)
        self.sig.ai_error.connect(self._on_ai_error)

        self._build_ui()
        self._on_status("请选择一个包含 Python 源码的文件夹", COLORS["warn"])
        apply_text_selectable(self)

    def _global_style(self) -> str:
        """窗口级全局样式，确保所有文字高对比度"""
        C = COLORS
        return f"""
            QWidget {{
                background: {C['bg']};
                color: {C['fg']};
            }}
            QLabel {{
                background: transparent;
                color: {C['fg']};
            }}
            QFrame {{
                background: {C['bg']};
                color: {C['fg']};
            }}
            QPushButton {{
                background: {C['panel']};
                color: {C['fg']};
                border: 1px solid {C['border']};
                border-radius: 6px;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                background: {C['border']};
                color: {C['accent']};
                border: 1px solid {C['accent']};
            }}
            QPushButton:disabled {{
                background: {C['panel']};
                color: {C['dim']};
                border: 1px solid {C['border']};
            }}
            QLineEdit {{
                background: {C['input']};
                color: {C['fg']};
                border: 1px solid {C['border']};
                border-radius: 6px;
                padding: 6px 10px;
            }}
            QLineEdit:focus {{
                border: 1px solid {C['accent']};
            }}
            QLineEdit:read-only {{
                background: {C['panel']};
                color: {C['dim']};
            }}
            QScrollArea {{
                border: none;
                background: transparent;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 14px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: #4a90d9;
                border-radius: 7px;
                min-height: 30px;
                margin: 3px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: #5da8f5;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
            QScrollBar:horizontal {{
                background: transparent;
                height: 14px;
                margin: 0;
            }}
            QScrollBar::handle:horizontal {{
                background: #4a90d9;
                border-radius: 7px;
                min-width: 30px;
                margin: 3px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: #5da8f5;
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0;
            }}
            QProgressBar {{
                background: {C['border']};
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background: {C['accent']};
                border-radius: 2px;
            }}
        """

    # ─── UI 构建 ───

    def _build_ui(self):
        """构建界面布局"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_header())
        layout.addWidget(self._build_input_area())
        layout.addWidget(self._build_card_area(), 1)
        layout.addWidget(self._build_bottom_bar())

    def _build_header(self):
        """顶部标题栏"""
        header = QFrame()
        header.setFixedHeight(50)
        header.setStyleSheet(f"background:{COLORS['head']};border-bottom:1px solid {COLORS['border']}")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(12, 6, 12, 6)

        if self._on_back:
            back = QPushButton("← 返回工具箱")
            back.setFont(FONT_BODY)
            back.setCursor(Qt.PointingHandCursor)
            back.setStyleSheet(
                f"QPushButton{{background:transparent;color:{COLORS['accent']};"
                f"border:none;padding:6px 12px}} "
                f"QPushButton:hover{{color:{COLORS['ahover']}}}"
            )
            back.clicked.connect(self.close)
            hl.addWidget(back)

        title = QLabel("变量生命周期追踪器 — 静态分析")
        title.setFont(FONT_TITLE)
        title.setStyleSheet(f"color:{COLORS['accent']};background:transparent")
        hl.addWidget(title)
        hl.addStretch()

        event_hint = QLabel("📋 诞生=首次定义 | 赋值=值变化 | 使用=读取/传参 | 销毁=作用域结束")
        event_hint.setFont(FONT_BODY)
        event_hint.setStyleSheet(f"color:#FF00FF;background:transparent")
        hl.addWidget(event_hint)
        hl.addSpacing(12)
        return header

    def _build_input_area(self):
        """文件夹选择 + 变量搜索输入区"""
        frame = QFrame()
        frame.setStyleSheet(f"background:{COLORS['panel']};border-bottom:1px solid {COLORS['border']}")
        vl = QVBoxLayout(frame)
        vl.setContentsMargins(16, 12, 16, 12)
        vl.setSpacing(8)

        # 文件夹选择行
        folder_row = QHBoxLayout()
        lbl = QLabel("目标文件夹:")
        lbl.setFont(FONT_BODY)
        lbl.setStyleSheet(f"color:{COLORS['fg']};background:transparent;font-weight:bold")
        folder_row.addWidget(lbl)

        self._folder_edit = QLineEdit()
        self._folder_edit.setFont(FONT_BODY)
        self._folder_edit.setPlaceholderText("点击右侧按钮选择包含 .py 文件的文件夹...")
        self._folder_edit.setReadOnly(True)
        folder_row.addWidget(self._folder_edit, 1)

        btn_browse = QPushButton("选择文件夹")
        btn_browse.setFont(FONT_BODY)
        btn_browse.setCursor(Qt.PointingHandCursor)
        btn_browse.setStyleSheet(
            f"QPushButton{{background:{COLORS['accent']};color:{COLORS['head']};"
            f"border:none;border-radius:6px;padding:6px 14px;font-weight:bold}} "
            f"QPushButton:hover{{background:{COLORS['ahover']}}}"
        )
        btn_browse.clicked.connect(self._on_browse)
        folder_row.addWidget(btn_browse)
        vl.addLayout(folder_row)

        # 变量搜索行
        var_row = QHBoxLayout()
        lbl2 = QLabel("变量名:")
        lbl2.setFont(FONT_BODY)
        lbl2.setStyleSheet(f"color:{COLORS['fg']};background:transparent;font-weight:bold")
        var_row.addWidget(lbl2)

        self._var_edit = QLineEdit()
        self._var_edit.setFont(FONT_BODY)
        self._var_edit.setPlaceholderText("输入变量名，自动模糊匹配...")
        self._var_edit.textChanged.connect(self._on_var_input)
        var_row.addWidget(self._var_edit, 1)

        self._btn_trace = QPushButton("追踪生命周期")
        self._btn_trace.setFont(FONT_BODY)
        self._btn_trace.setCursor(Qt.PointingHandCursor)
        self._btn_trace.setEnabled(False)
        self._btn_trace.setStyleSheet(
            f"QPushButton{{background:{COLORS['accent']};color:{COLORS['head']};"
            f"border:none;border-radius:6px;padding:6px 16px;font-weight:bold}} "
            f"QPushButton:hover{{background:{COLORS['ahover']}}} "
            f"QPushButton:disabled{{background:{COLORS['border']};color:{COLORS['dim']};border:none}}"
        )
        self._btn_trace.clicked.connect(self._on_trace)
        var_row.addWidget(self._btn_trace)
        vl.addLayout(var_row)

        # 模糊匹配下拉列表
        self._suggestion_frame = QFrame()
        self._suggestion_frame.setStyleSheet(
            f"background:{COLORS['panel']};border:1px solid {COLORS['accent']};border-radius:6px"
        )
        self._suggestion_frame.setMinimumWidth(400)
        self._suggestion_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._suggestion_layout = QGridLayout(self._suggestion_frame)
        self._suggestion_layout.setContentsMargins(8, 4, 8, 4)
        self._suggestion_layout.setSpacing(2)
        self._suggestion_frame.hide()
        vl.addWidget(self._suggestion_frame)

        return frame

    def _build_card_area(self):
        """横向卡片链滚动区域"""
        container = QFrame()
        container.setStyleSheet(f"background:{COLORS['bg']}")
        container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        vl = QVBoxLayout(container)
        vl.setContentsMargins(16, 12, 16, 12)
        vl.setSpacing(8)

        # 空状态提示
        self._empty_label = QLabel(
            "选择文件夹 → 输入变量名 → 点击「追踪生命周期」\n\n"
            "支持追踪：赋值 / 读取 / 增量赋值 / 函数参数 / 导入 / 循环变量 / "
            "上下文管理 / del 销毁 / return 返回 / 传参\n\n"
            "追踪结果以横向卡片链展示，可导出 HTML 报告"
        )
        self._empty_label.setFont(FONT_BODY)
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet(
            f"color:{COLORS['dim']};background:transparent;padding:40px"
        )
        vl.addWidget(self._empty_label)

        # 卡片链容器（添加滚动条，统一高度）
        self._card_scroll = QScrollArea()
        self._card_scroll.setWidgetResizable(False)
        self._card_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._card_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._card_scroll.setStyleSheet("QScrollArea{border:none}")
        self._card_container = QWidget()
        self._card_layout = QHBoxLayout(self._card_container)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.setSpacing(12)
        self._card_layout.addStretch()
        self._card_container.hide()
        self._card_scroll.setWidget(self._card_container)
        self._card_scroll.setMinimumHeight(180)
        self._card_scroll.installEventFilter(self)
        vl.addWidget(self._card_scroll, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(container)
        scroll.setStyleSheet("QScrollArea{border:none}")
        scroll.installEventFilter(self)
        self._outer_card_scroll = scroll
        return scroll

    def _build_bottom_bar(self):
        """底部操作栏 + 状态栏 + 进度条"""
        bar = QFrame()
        bar.setFixedHeight(70)
        bar.setStyleSheet(f"background:{COLORS['head']};border-top:1px solid {COLORS['border']}")
        vl = QVBoxLayout(bar)
        vl.setContentsMargins(16, 4, 16, 4)
        vl.setSpacing(2)

        # 上层：状态 + 按钮
        hl = QHBoxLayout()

        self._status_label = QLabel("")
        self._status_label.setFont(FONT_SMALL)
        self._status_label.setStyleSheet(f"color:{COLORS['fg']};background:transparent")
        hl.addWidget(self._status_label)
        hl.addStretch()

        # 导出按钮
        self._btn_export = QPushButton("导出 HTML 报告")
        self._btn_export.setFont(FONT_BODY)
        self._btn_export.setCursor(Qt.PointingHandCursor)
        self._btn_export.setEnabled(False)
        self._btn_export.setStyleSheet(
            f"QPushButton{{background:{COLORS['panel']};color:{COLORS['fg']};"
            f"border:1px solid {COLORS['border']};border-radius:6px;padding:6px 14px}} "
            f"QPushButton:hover{{background:{COLORS['border']};color:{COLORS['accent']}}} "
            f"QPushButton:disabled{{background:{COLORS['panel']};color:{COLORS['dim']}}}"
        )
        self._btn_export.clicked.connect(self._on_export)
        hl.addWidget(self._btn_export)

        # 打开报告按钮（保存后才能点击）
        self._btn_open = QPushButton("打开 HTML 报告")
        self._btn_open.setFont(FONT_BODY)
        self._btn_open.setCursor(Qt.PointingHandCursor)
        self._btn_open.setEnabled(False)
        self._btn_open.setStyleSheet(
            f"QPushButton{{background:{COLORS['panel']};color:{COLORS['dim']};"
            f"border:1px solid {COLORS['border']};border-radius:6px;padding:6px 14px}} "
            f"QPushButton:disabled{{background:{COLORS['panel']};color:{COLORS['dim']}}}"
        )
        self._btn_open.clicked.connect(self._on_open_html)
        hl.addWidget(self._btn_open)

        # AI 分析按钮
        self._btn_ai = QPushButton("AI 分析变量变化")
        self._btn_ai.setFont(FONT_BODY)
        self._btn_ai.setCursor(Qt.PointingHandCursor)
        self._btn_ai.setEnabled(False)
        self._btn_ai.setStyleSheet(
            f"QPushButton{{background:{COLORS['ok']};color:{COLORS['head']};"
            f"border:none;border-radius:6px;padding:6px 14px;font-weight:bold}} "
            f"QPushButton:hover{{background:#2ea043}} "
            f"QPushButton:disabled{{background:{COLORS['panel']};color:{COLORS['dim']}}}"
        )
        self._btn_ai.clicked.connect(self._on_ai_analyze)
        hl.addWidget(self._btn_ai)

        vl.addLayout(hl)

        # 下层：不确定进度条
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        vl.addWidget(self._progress)

        return bar

    # ─── 复制工具 ───

    def _copy_btn(self, text: str, tooltip: str = "复制", label: str = "") -> QPushButton:
        """创建小复制按钮"""
        btn = QPushButton("复制")
        btn.setFont(FONT_SMALL)
        btn.setFixedSize(42, 22)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(tooltip)
        btn.setStyleSheet(
            f"QPushButton{{background:{COLORS['copy']};color:{COLORS['fg']};"
            f"border:1px solid {COLORS['border']};border-radius:3px;padding:0 6px}} "
            f"QPushButton:hover{{background:{COLORS['accent']};color:{COLORS['head']};border:none}}"
        )
        btn.clicked.connect(lambda: self._copy_text(text, label))
        return btn

    def _copy_text(self, text: str, label: str = ""):
        """复制文本到剪贴板"""
        cb = QApplication.clipboard()
        cb.setText(text)
        if label:
            self._on_status(f"已复制：{label}的内容", COLORS["ok"])
        else:
            self._on_status(f"已复制：{text[:40]}", COLORS["ok"])

    # ─── 进度条控制 ───

    def _on_busy(self, busy: bool):
        """忙碌状态切换"""
        self._progress.setVisible(busy)

    # ─── 事件处理 ───

    def _on_browse(self):
        """选择文件夹"""
        folder = QFileDialog.getExistingDirectory(self, "选择包含 Python 源码的文件夹")
        if folder:
            self._folder_path = folder
            self._folder_edit.setText(folder)
            self._on_status(f"正在扫描 {folder} ...", COLORS["warn"])
            self.sig.busy_changed.emit(True)
            threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self):
        """后台扫描文件夹中所有变量名"""
        try:
            names = get_all_variable_names(self._folder_path)
            self.sig.scan_done.emit(names)
        except Exception as e:
            logger.error("扫描文件夹失败: %s", e, exc_info=True)
            self.sig.status.emit(f"扫描失败: {e}", COLORS["err"])
        finally:
            self.sig.busy_changed.emit(False)

    def _on_scan_done(self, names):
        """扫描完成"""
        self._all_vars = names
        count = len(names)
        self._on_status(f"扫描完成: 发现 {count} 个变量名", COLORS["ok"])
        self._var_edit.setFocus()

    def _on_var_input(self, text):
        """输入框文本变化，实时模糊搜索"""
        text = text.strip()
        if not text or not self._all_vars:
            self._suggestion_frame.hide()
            self._btn_trace.setEnabled(False)
            return

        matched = fuzzy_match(text, self._all_vars, limit=30)
        if not matched:
            self._suggestion_frame.hide()
            self._btn_trace.setEnabled(bool(text))
            return

        while self._suggestion_layout.count():
            item = self._suggestion_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        col_count = max(1, min(6, len(matched) // 3 + 1))
        row_count = (len(matched) + col_count - 1) // col_count

        for idx, name in enumerate(matched):
            lbl = QPushButton(name)
            lbl.setFont(FONT_MONO)
            lbl.setCursor(Qt.PointingHandCursor)
            lbl.setMinimumHeight(32)
            lbl.setStyleSheet(
                f"QPushButton{{background:transparent;color:{COLORS['fg']};"
                f"border:none;text-align:left;padding:6px 10px;min-height:32px}} "
                f"QPushButton:hover{{background:{COLORS['border']};color:{COLORS['accent']}}}"
            )
            lbl.clicked.connect(lambda checked=False, n=name: self._on_select_suggestion(n))
            row = idx % row_count
            col = idx // row_count
            self._suggestion_layout.addWidget(lbl, row, col)

        for c in range(col_count):
            self._suggestion_layout.setColumnStretch(c, 1)

        self._suggestion_frame.show()
        self._btn_trace.setEnabled(bool(text))

    def _on_select_suggestion(self, name):
        """选择建议项"""
        self._var_edit.setText(name)
        self._suggestion_frame.hide()

    def _on_trace(self):
        """开始追踪变量生命周期"""
        var_name = self._var_edit.text().strip()
        if not var_name or not self._folder_path:
            self._on_status("请先选择文件夹并输入变量名", COLORS["warn"])
            return

        self._btn_trace.setEnabled(False)
        self._on_status(f"正在追踪变量「{var_name}」的生命周期...", COLORS["warn"])
        self.sig.busy_changed.emit(True)

        threading.Thread(target=self._do_trace, args=(var_name,), daemon=True).start()

    def _do_trace(self, var_name):
        """后台执行变量追踪"""
        try:
            result = extract_variable_events(self._folder_path, var_name)
            self.sig.trace_done.emit(result)
        except Exception as e:
            logger.error("变量追踪失败: %s", e, exc_info=True)
            self.sig.trace_error.emit(str(e))
        finally:
            self.sig.busy_changed.emit(False)

    def _on_trace_done(self, result):
        """追踪完成，渲染卡片链"""
        self._result = result
        self._btn_trace.setEnabled(True)
        self._btn_export.setEnabled(result.total_events > 0)
        self._btn_ai.setEnabled(result.total_events > 0)

        if result.total_events == 0:
            self._on_status(
                f"未找到变量「{result.variable_name}」的任何事件", COLORS["warn"]
            )
            return

        # 清空旧卡片
        while self._card_layout.count() > 1:
            item = self._card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._empty_label.hide()
        self._empty_label.setMaximumHeight(0)
        self._empty_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._card_container.show()

        # 生成渐变色
        gradient_colors = _generate_gradient_colors(len(result.events))

        for i, event in enumerate(result.events):
            card = self._create_event_card(event, i + 1, gradient_colors[i])
            self._card_layout.insertWidget(self._card_layout.count() - 1, card)

            if i < len(result.events) - 1:
                arrow = QLabel("→")
                arrow.setFont(FONT_HEADER)
                arrow.setStyleSheet(
                    f"color:{gradient_colors[i]};background:transparent;font-weight:bold"
                )
                arrow.setFixedWidth(20)
                arrow.setAlignment(Qt.AlignCenter)
                self._card_layout.insertWidget(self._card_layout.count() - 1, arrow)

        # 卡片容器固定尺寸：宽度=所有卡片+箭头的自然宽度，高度延迟到布局更新后调整
        card_count = len(result.events)
        total_w = card_count * 400 + (card_count - 1) * 20 + (card_count * 2 - 2) * 12 + 20
        self._card_container.setFixedWidth(total_w)
        QTimer.singleShot(0, self._adjust_card_height)

        stats = (
            f"变量: {result.variable_name} | "
            f"总事件: {result.total_events} | "
            f"诞生: {result.birth_count} | "
            f"使用: {result.use_count} | "
            f"消亡: {result.death_count} | "
            f"文件: {len(result.files_involved)} 个"
        )
        self._on_status(stats, COLORS["ok"])
        logger.info("追踪完成: %s, %d 个事件", result.variable_name, result.total_events)

    def eventFilter(self, obj, event):
        """事件过滤器：监听_card_scroll和外层scroll大小变化，自动调整卡片容器高度"""
        if (obj is self._card_scroll or obj is self._outer_card_scroll) and event.type() == event.Type.Resize and self._card_container.isVisible():
            QTimer.singleShot(0, self._adjust_card_height)
        return super().eventFilter(obj, event)

    def _adjust_card_height(self):
        """调整卡片容器高度：等于视口高度，代码片段和上下文会自动拉伸填满"""
        self._card_layout.activate()
        viewport_h = self._card_scroll.viewport().height()
        if viewport_h != self._card_container.height():
            self._card_container.setFixedHeight(viewport_h)

    def _on_trace_error(self, msg):
        """追踪失败"""
        self._btn_trace.setEnabled(True)
        self._on_status(f"追踪失败: {msg}", COLORS["err"])

    def _create_event_card(self, event: VariableEvent, index: int, gradient_color: str) -> QFrame:
        """创建单个事件卡片

        每个字段都有复制按钮 + 所有文字可鼠标选中复制
        """
        card = QFrame()
        card.setMinimumWidth(400)
        card.setObjectName("eventCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        card.setStyleSheet(
            f"QFrame#eventCard{{background:{COLORS['panel']};"
            f"border:1px solid {COLORS['border']};border-radius:8px}}"
        )

        vl = QVBoxLayout(card)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        vl.setAlignment(Qt.AlignTop)

        # 顶部渐变色条
        top_bar = QFrame()
        top_bar.setFixedHeight(6)
        top_bar.setStyleSheet(
            f"background:{gradient_color};border:none;"
            f"border-top-left-radius:8px;border-top-right-radius:8px"
        )
        vl.addWidget(top_bar)

        # 内容区
        content = QVBoxLayout()
        content.setContentsMargins(8, 0, 8, 0)
        content.setSpacing(0)

        # ── 第1行：序号 + 事件类型 + 时间戳 + 复制按钮 ──
        header_row = QHBoxLayout()
        idx_lbl = QLabel(f"#{index}")
        idx_lbl.setFont(FONT_SMALL)
        idx_lbl.setStyleSheet(f"color:{COLORS['dim']};background:transparent")
        _make_selectable(idx_lbl)
        header_row.addWidget(idx_lbl)

        type_lbl = QLabel(event.event_type.value)
        type_lbl.setFont(FONT_HEADER)
        type_lbl.setStyleSheet(
            f"color:{gradient_color};background:transparent;font-weight:bold"
        )
        _make_selectable(type_lbl)
        header_row.addWidget(type_lbl)
        header_row.addStretch()

        # 复制事件类型
        copy_type = self._copy_btn(event.event_type.value, "复制事件类型", "事件类型")
        header_row.addWidget(copy_type)
        content.addLayout(header_row)

        # ── 第2行：文件名:行号 + 复制按钮 ──
        loc_text = f"{event.file_name}:{event.line}"
        loc_row = QHBoxLayout()
        loc_lbl = QLabel(f"文件（变量所在文件）: {loc_text}")
        loc_lbl.setFont(FONT_SMALL)
        loc_lbl.setWordWrap(True)
        loc_lbl.setStyleSheet(f"color:{COLORS['accent']};background:transparent")
        _make_selectable(loc_lbl)
        loc_row.addWidget(loc_lbl, 1)
        copy_loc = self._copy_btn(loc_text, "复制文件位置", "文件（变量所在文件）")
        loc_row.addWidget(copy_loc)
        content.addLayout(loc_row)

        # ── 第3行：作用域 + 复制按钮 ──
        scope_text = event.scope
        scope_row = QHBoxLayout()
        scope_lbl = QLabel(f"作用域（变量所属范围）: {scope_text}")
        scope_lbl.setFont(FONT_SMALL)
        scope_lbl.setWordWrap(True)
        scope_lbl.setStyleSheet(f"color:{COLORS['fg']};background:transparent")
        _make_selectable(scope_lbl)
        scope_row.addWidget(scope_lbl, 1)
        copy_scope = self._copy_btn(scope_text, "复制作用域", "作用域（变量所属范围）")
        scope_row.addWidget(copy_scope)
        content.addLayout(scope_row)

        # ── 第3.5行：变量类型推断（始终显示，绿色背景标签） ──
        type_str = event.type_inferred if event.type_inferred else "未知"
        type_desc = event.type_description if event.type_description else "无法静态推断"
        type_info_text = f"变量类型: {type_str}（{type_desc}）"
        type_row = QHBoxLayout()
        type_lbl2 = QLabel(type_info_text)
        type_lbl2.setFont(FONT_SMALL)
        type_lbl2.setWordWrap(True)
        type_lbl2.setStyleSheet(
            f"color:{COLORS['head']};background:{COLORS['ok']};"
            f"border-radius:4px;padding:1px 6px;font-weight:bold"
        )
        _make_selectable(type_lbl2)
        type_row.addWidget(type_lbl2, 1)
        copy_type_info = self._copy_btn(type_str, "复制类型", "变量类型")
        type_row.addWidget(copy_type_info)
        content.addLayout(type_row)

        # ── 第4行：代码片段标签 + 代码 + 复制按钮 ──
        code_label_title = QLabel("代码片段（变量所在代码行）:")
        code_label_title.setFont(FONT_SMALL)
        code_label_title.setStyleSheet(f"color:{COLORS['dim']};background:transparent")
        content.addWidget(code_label_title)

        code_text = event.code_line
        code_row = QHBoxLayout()
        code_edit = QTextEdit()
        code_edit.setReadOnly(True)
        code_edit.setText(code_text)
        code_edit.setFont(FONT_MONO)
        code_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        code_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        code_edit.setStyleSheet(f"""
            QTextEdit {{
                background:{COLORS['input']};
                color:{COLORS['fg']};
                border:1px solid {COLORS['warn']};
                border-radius:4px;
                padding:4px;
                font-family:Consolas;
            }}
        """)
        min_code_height = FONT_MONO.pointSize() * 3 * 1.6 + 8
        code_edit.setMinimumHeight(int(min_code_height))
        code_row.addWidget(code_edit, 1)

        copy_code = self._copy_btn(code_text, "复制代码", "代码片段（变量所在代码行）")
        code_row.addWidget(copy_code)
        content.addLayout(code_row)

        # ── 第5行：上下文代码标签 + 上下文 + 复制按钮 ──
        if event.context_lines:
            ctx_title = QLabel("上下文（前后2行代码，帮助理解上下文）:")
            ctx_title.setFont(FONT_SMALL)
            ctx_title.setStyleSheet(f"color:{COLORS['dim']};background:transparent")
            content.addWidget(ctx_title)

            ctx_text = "\n".join(event.context_lines)
            ctx_row = QHBoxLayout()

            ctx_rows = []
            target_idx = len(event.context_lines) // 2
            for ci, cline in enumerate(event.context_lines):
                if ci == target_idx:
                    ctx_rows.append(f'<span style="background:{COLORS["warn"]};color:{COLORS["head"]};font-weight:bold">{cline}</span>')
                else:
                    ctx_rows.append(f'<span style="color:{COLORS["dim"]};">{cline}</span>')
            ctx_html = "<br>".join(ctx_rows)

            ctx_edit = QTextEdit()
            ctx_edit.setReadOnly(True)
            ctx_edit.setHtml(ctx_html)
            ctx_edit.setFont(FONT_MONO)
            ctx_edit.setLineWrapMode(QTextEdit.WidgetWidth)
            ctx_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            ctx_edit.setStyleSheet(f"""
                QTextEdit {{
                    background:{COLORS['bg']};
                    color:{COLORS['fg']};
                    border:1px solid {COLORS['border']};
                    border-radius:3px;
                    padding:4px;
                    font-family:Consolas;
                }}
            """)
            min_ctx_height = FONT_MONO.pointSize() * 5 * 1.6 + 8
            ctx_edit.setMinimumHeight(int(min_ctx_height))
            ctx_row.addWidget(ctx_edit, 1)

            copy_ctx = self._copy_btn(ctx_text, "复制上下文", "上下文（前后2行代码，帮助理解上下文）")
            ctx_row.addWidget(copy_ctx)
            content.addLayout(ctx_row)

        # ── 第6行：详细信息 + 复制按钮 ──
        if event.detail:
            detail_text = event.detail
            detail_row = QHBoxLayout()
            detail_lbl = QLabel(f"详情（此事件的详细说明）: {detail_text}")
            detail_lbl.setFont(FONT_SMALL)
            detail_lbl.setWordWrap(True)
            detail_lbl.setStyleSheet(f"color:{COLORS['dim']};background:transparent")
            _make_selectable(detail_lbl)
            detail_row.addWidget(detail_lbl, 1)
            copy_detail = self._copy_btn(detail_text, "复制详情", "详情（此事件的详细说明）")
            detail_row.addWidget(copy_detail)
            content.addLayout(detail_row)

        vl.addLayout(content)
        return card

    def closeEvent(self, e):
        """点击 X 时返回工具箱主界面，而不是真正关闭"""
        if self._on_back:
            e.ignore()
            self.hide()
            self._on_back()
        else:
            e.accept()

    def _on_ai_analyze(self):
        """调用 AI 分析变量变化"""
        if not self._result or not self._result.events:
            self._on_status("请先执行追踪", COLORS["warn"])
            return

        from ai.ai_config import load_config
        config = load_config()
        if not config.enable_ai:
            self._on_status("AI 功能未启用，请先在「AI 设置」中配置并启用", COLORS["warn"])
            return
        if not config.is_valid():
            self._on_status("AI 配置无效，请先在「AI 设置」中填写 API Key", COLORS["warn"])
            return

        # 构建变量变化摘要
        summary_lines = []
        for e in self._result.events:
            summary_lines.append(
                f"[{e.event_type}] {e.file_name}:{e.line} | "
                f"作用域:{e.scope} | 代码:{e.code_line}"
            )
        events_summary = "\n".join(summary_lines)

        self._btn_ai.setEnabled(False)
        self._on_status("正在请求 AI 分析变量变化...", COLORS["warn"])
        self.sig.busy_changed.emit(True)

        threading.Thread(
            target=self._do_ai_analyze,
            args=(self._result.variable_name, events_summary, config),
            daemon=True,
        ).start()

    def _do_ai_analyze(self, var_name: str, events_summary: str, config):
        """子线程：调用 AI 分析变量变化"""
        from ai.ai_client import analyze_variable_changes
        try:
            result = analyze_variable_changes(var_name, events_summary, config)
            self.sig.ai_done.emit(result)
        except Exception as e:
            self.sig.ai_error.emit(str(e))

    def _on_ai_done(self, result: str):
        """AI 分析完成"""
        self._btn_ai.setEnabled(True)
        self.sig.busy_changed.emit(False)
        self._on_status("AI 分析完成", COLORS["ok"])
        # 弹出结果窗口
        self._show_ai_result(result)

    def _on_ai_error(self, error: str):
        """AI 分析失败"""
        self._btn_ai.setEnabled(True)
        self.sig.busy_changed.emit(False)
        self._on_status(f"AI 分析失败: {error}", COLORS["err"])

    def _show_ai_result(self, result: str):
        """弹出 AI 分析结果窗口"""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextEdit, QVBoxLayout, QLabel
        dlg = QDialog(self)
        dlg.setWindowTitle("AI 分析结果")
        dlg.resize(650, 480)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel(f"变量「{self._result.variable_name}」的 AI 分析结果：")
        header.setFont(FONT_HEADER)
        header.setStyleSheet(f"color:{COLORS['accent']};background:transparent")
        layout.addWidget(header)

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setFont(FONT_BODY)
        text_edit.setStyleSheet(
            f"QTextEdit{{background:{COLORS['input']};color:{COLORS['fg']};"
            f"border:1px solid {COLORS['border']};border-radius:6px;padding:8px}}"
        )
        text_edit.setPlainText(result)
        layout.addWidget(text_edit, 1)

        btn_box = QDialogButtonBox(QDialogButtonBox.Close)
        btn_box.setStyleSheet(
            f"QPushButton{{background:{COLORS['accent']};color:{COLORS['head']};"
            f"border:none;border-radius:6px;padding:6px 20px}}"
        )
        btn_box.rejected.connect(dlg.close)
        layout.addWidget(btn_box)

        dlg.exec_()

    def _on_export(self):
        """导出 HTML 报告"""
        if not self._result:
            self._on_status("请先执行变量追踪", COLORS["warn"])
            return

        default_name = f"lifecycle_{self._result.variable_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        fp, _ = QFileDialog.getSaveFileName(
            self, "导出 HTML 报告", default_name, "HTML 文件 (*.html);;所有文件 (*.*)"
        )
        if fp:
            try:
                export_lifecycle_html(self._result, fp)
                self._html_path = fp
                # 启用打开按钮
                self._btn_open.setEnabled(True)
                self._btn_open.setStyleSheet(
                    f"QPushButton{{background:{COLORS['ok']};color:{COLORS['head']};"
                    f"border:none;border-radius:6px;padding:6px 14px;font-weight:bold}} "
                    f"QPushButton:hover{{background:#2ea043}}"
                )
                self._on_status(f"HTML 报告已导出: {fp}", COLORS["ok"])
            except Exception as e:
                logger.error("导出 HTML 失败: %s", e, exc_info=True)
                self._on_status(f"导出失败: {e}", COLORS["err"])

    def _on_open_html(self):
        """打开已导出的 HTML 报告"""
        if not self._html_path or not os.path.exists(self._html_path):
            self._on_status("报告文件不存在，请先导出", COLORS["warn"])
            return
        try:
            os.startfile(self._html_path)
            logger.info("打开 HTML 报告: %s", self._html_path)
        except Exception as e:
            logger.error("打开 HTML 报告失败: %s", e, exc_info=True)
            self._on_status(f"打开失败: {e}", COLORS["err"])

    def _on_status(self, text, color=None):
        """更新状态栏"""
        self._status_label.setText(text)
        self._status_label.setStyleSheet(
            f"color:{color or COLORS['fg']};background:transparent"
        )
