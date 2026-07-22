"""
辅助编程工具箱 - 主程序入口
PySide6 (LGPLv3) - 工具箱架构，集成多个辅助编程工具

工具列表：
  1. GUI 元素探查器 - 点击控件识别类型/属性/层级
  2. 变量生命周期追踪器（静态）- AST 分析变量从生到死全过程
"""

import sys
import os
import ctypes

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QSystemTrayIcon, QMenu, QProgressBar,
    QSizePolicy, QMessageBox, QFileDialog, QInputDialog,
)
from PySide6.QtCore import Qt, QEvent, Signal, QTimer
from PySide6.QtGui import QFont, QIcon, QAction

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.theme import COLORS, FONT_TITLE, FONT_HEADER, FONT_BODY, FONT_SMALL, get_global_stylesheet, apply_text_selectable
from utils.logging_utils import get_logger
from utils.hotkey_handler import HotkeyHandler

logger = get_logger(__name__)

_ICON_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon.ico")


class ToolCard(QFrame):
    """工具卡片按钮"""

    def __init__(self, title: str, description: str, icon_text: str, on_click, color: str = None):
        super().__init__()
        self.setMinimumHeight(100)
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(), QSizePolicy.Preferred)
        self.setCursor(Qt.PointingHandCursor)
        self._on_click = on_click
        self._color = color or COLORS["accent"]

        self.setStyleSheet(
            f"QFrame{{background:{COLORS['panel']};border:1px solid {COLORS['border']};"
            f"border-left:3px solid {self._color};border-radius:10px}} "
            f"QFrame:hover{{border:2px solid {self._color};}}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        # 图标圆
        icon_circle = QLabel(icon_text)
        icon_circle.setFixedSize(56, 56)
        icon_circle.setAlignment(Qt.AlignCenter)
        icon_circle.setFont(QFont("Segoe UI Emoji", 22))
        icon_circle.setStyleSheet(
            f"background:{self._color};color:{COLORS['head']};"
            f"border-radius:28px"
        )
        layout.addWidget(icon_circle)

        # 文字区
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)

        name_lbl = QLabel(title)
        name_lbl.setFont(FONT_HEADER)
        name_lbl.setStyleSheet(f"color:{self._color};background:transparent")
        text_layout.addWidget(name_lbl)

        desc_lbl = QLabel(description)
        desc_lbl.setFont(FONT_SMALL)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(f"color:{COLORS['dim']};background:transparent")
        text_layout.addWidget(desc_lbl)

        layout.addLayout(text_layout, 1)

        # 进入按钮
        arrow = QLabel("进入 \u203a")
        arrow.setFont(QFont("Noto Sans SC", 14, weight=QFont.Weight.Bold))
        arrow.setStyleSheet(f"color:{self._color};background:transparent")
        layout.addWidget(arrow)

        # 子 QLabel 安装事件过滤器，防止 TextSelectableByMouse 吞掉点击事件
        for child in self.findChildren(QLabel):
            child.installEventFilter(self)

    def eventFilter(self, obj, event):
        """子 QLabel 的鼠标点击转发到卡片点击处理"""
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if self._on_click:
                self._on_click()
            return True
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        """点击卡片（处理 QFrame 自身区域的点击）"""
        if event.button() == Qt.LeftButton and self._on_click:
            self._on_click()


class ToolboxMainWindow(QMainWindow):
    """辅助编程工具箱主窗口"""

    _screenshot_triggered = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("辅助编程工具箱")
        self.resize(800, 500)
        self.setMinimumSize(600, 400)

        # 应用图标
        self._app_icon = QIcon(_ICON_PATH) if os.path.exists(_ICON_PATH) else QIcon()
        self.setWindowIcon(self._app_icon)

        # 应用全局样式
        self.setStyleSheet(get_global_stylesheet())

        # 子窗口引用
        self._sub_windows = {}

        self._build_ui()
        self._init_tray()
        self._init_global_hotkey()
        # 截图触发标志位（跨线程通信最可靠方案）
        # pynput 线程设置标志位，主线程定时器轮询检测
        self._screenshot_pending = False
        # 拾取模式触发标志位
        self._inspect_mode_pending = None  # None=无变化, True=进入模式, False=退出模式
        self._inspect_click_pending = None  # (x, y) 或 None
        self._screenshot_timer = QTimer()
        self._screenshot_timer.timeout.connect(self._check_screenshot_pending)
        self._screenshot_timer.timeout.connect(self._check_inspect_pending)
        self._screenshot_timer.start(50)  # 每 50ms 检查一次
        apply_text_selectable(self)
        logger.info("工具箱启动")

    def _build_ui(self):
        """构建主界面"""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部标题栏
        header = QFrame()
        header.setFixedHeight(60)
        header.setStyleSheet(f"background:{COLORS['head']};border:none")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(24, 12, 24, 12)

        title = QLabel("辅助编程工具箱")
        title.setFont(FONT_TITLE)
        title.setStyleSheet(f"color:{COLORS['accent']};background:transparent")
        hl.addWidget(title)
        hl.addStretch()

        subtitle = QLabel("选择一个工具开始")
        subtitle.setFont(FONT_SMALL)
        subtitle.setStyleSheet(f"color:{COLORS['dim']};background:transparent")
        hl.addWidget(subtitle)

        # 设置按钮
        btn_settings = QPushButton("⚙ 大模型接入/截图热键")
        btn_settings.setFont(FONT_SMALL)
        btn_settings.setCursor(Qt.PointingHandCursor)
        btn_settings.setStyleSheet(
            f"QPushButton{{background:transparent;color:{COLORS['dim']};border:1px solid {COLORS['border']};"
            f"border-radius:6px;padding:4px 12px}} "
            f"QPushButton:hover{{color:{COLORS['accent']};border:1px solid {COLORS['accent']}}}"
        )
        btn_settings.clicked.connect(self._open_settings)
        hl.addWidget(btn_settings)

        layout.addWidget(header)

        # 工具卡片区域
        content = QWidget()
        content.setStyleSheet(f"background:{COLORS['bg']}")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(32, 24, 32, 24)
        cl.setSpacing(16)

        # 工具1: GUI 元素探查器
        card1 = ToolCard(
            "GUI 元素探查器",
            "点击任意 GUI 控件，识别类型、属性、父级层级，生成截图标注和 AI 提示词",
            "\U0001F50D",
            self._open_gui_inspector,
            color=COLORS["accent"],
        )
        cl.addWidget(card1)

        # 工具2: 变量生命周期追踪器
        card2 = ToolCard(
            "变量生命周期追踪器（静态）",
            "AST 分析变量从诞生到消亡的完整生命周期，跨文件追踪，导出 HTML 报告",
            "\U0001F4CA",
            self._open_variable_tracer,
            color=COLORS["ok"],
        )
        cl.addWidget(card2)

        # 工具3: 变量生命周期追踪器（动态）
        card3 = ToolCard(
            "变量生命周期追踪器（动态）",
            "运行程序实时追踪变量值的变化，记录运行时类型和真实数据，sys.settrace 方案",
            "\U0001F504",
            self._open_dynamic_tracer,
            color=COLORS["warn"],
        )
        cl.addWidget(card3)

        # 工具4: 函数调用链分析器
        card4 = ToolCard(
            "函数调用链分析器",
            "AST 分析 Python 源码，构建函数调用关系图，查看调用链和被调用方",
            "\U0001F517",
            self._open_call_chain,
            color=COLORS["title"],
        )
        cl.addWidget(card4)

        # 工具5: 内存使用监控器
        card5 = ToolCard(
            "内存使用监控器",
            "实时监控 Python 进程内存使用（RSS/VMS），绘制曲线图，定位内存瓶颈",
            "\U0001F4C8",
            self._open_memory_monitor,
            color=COLORS["err"],
        )
        cl.addWidget(card5)

        # 工具6: 机器学习模型选择器
        card7 = ToolCard(
            "ML 模型选择器",
            "渐进式问答推荐最适合的机器学习模型，覆盖分类/回归/聚类/降维/异常检测/时序预测",
            "\U0001F9E0",
            self._open_ml_selector,
            color=COLORS["title"],
        )
        cl.addWidget(card7)

        # 工具8: 快速截图标注
        card8 = ToolCard(
            "快速截图标注",
            "热键触发全屏截图，红框/箭头/文本标注，一键复制到剪贴板或另存为",
            "\U0001F4F7",
            self._open_screenshot_info,
            color=COLORS["err"],
        )
        cl.addWidget(card8)

        cl.addStretch()
        layout.addWidget(content, 1)

        # 底部状态栏 + 不确定进度条
        status_bar = QFrame()
        status_bar.setFixedHeight(34)
        status_bar.setStyleSheet(f"background:{COLORS['head']};border-top:1px solid {COLORS['border']}")
        sl = QVBoxLayout(status_bar)
        sl.setContentsMargins(16, 2, 16, 2)
        sl.setSpacing(2)

        self._status_label = QLabel("就绪 - 选择一个工具开始")
        self._status_label.setFont(FONT_SMALL)
        self._status_label.setStyleSheet(f"color:{COLORS['dim']};background:transparent")
        sl.addWidget(self._status_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        self._progress.setStyleSheet(
            f"QProgressBar{{background:{COLORS['border']};border:none;border-radius:2px}} "
            f"QProgressBar::chunk{{background:{COLORS['accent']};border-radius:2px}}"
        )
        sl.addWidget(self._progress)
        layout.addWidget(status_bar)

    def _open_gui_inspector(self):
        """打开 GUI 元素探查器"""
        if "inspector" not in self._sub_windows:
            from ui.inspector_window import GUIInspectorWindow
            self._sub_windows["inspector"] = GUIInspectorWindow(on_back=self._show_toolbox)
        self.hide()
        self._sub_windows["inspector"].show()
        self._sub_windows["inspector"].raise_()
        self._sub_windows["inspector"].activateWindow()
        logger.info("打开 GUI 元素探查器")

    def _open_variable_tracer(self):
        """打开变量生命周期追踪器（静态）"""
        if "tracer" not in self._sub_windows:
            from ui.tracer_window import VariableTracerWindow
            self._sub_windows["tracer"] = VariableTracerWindow(on_back=self._show_toolbox)
        self.hide()
        self._sub_windows["tracer"].show()
        self._sub_windows["tracer"].raise_()
        self._sub_windows["tracer"].activateWindow()
        logger.info("打开变量生命周期追踪器（静态）")

    def _open_dynamic_tracer(self):
        """打开变量生命周期追踪器（动态）"""
        if getattr(self, "_opening_dynamic_tracer", False):
            return
        self._opening_dynamic_tracer = True
        try:
            from ui.dynamic_tracer_window import DynamicTracerWindow
            if "dynamic_tracer" not in self._sub_windows:
                self._sub_windows["dynamic_tracer"] = DynamicTracerWindow(on_back=self._show_toolbox)
            self.hide()
            self._sub_windows["dynamic_tracer"].show()
            self._sub_windows["dynamic_tracer"].raise_()
            self._sub_windows["dynamic_tracer"].activateWindow()
            logger.info("打开变量生命周期追踪器（动态）")
        finally:
            self._opening_dynamic_tracer = False

    def _open_call_chain(self):
        """打开函数调用链分析器"""
        if "call_chain" not in self._sub_windows:
            from ui.call_chain_window import CallChainWindow
            self._sub_windows["call_chain"] = CallChainWindow(on_back=self._show_toolbox)
        self.hide()
        self._sub_windows["call_chain"].show()
        self._sub_windows["call_chain"].raise_()
        self._sub_windows["call_chain"].activateWindow()
        logger.info("打开函数调用链分析器")

    def _open_memory_monitor(self):
        """打开内存使用监控器"""
        if "memory_monitor" not in self._sub_windows:
            from ui.memory_monitor_window import MemoryMonitorWindow
            self._sub_windows["memory_monitor"] = MemoryMonitorWindow(on_back=self._show_toolbox)
        self.hide()
        self._sub_windows["memory_monitor"].show()
        self._sub_windows["memory_monitor"].raise_()
        self._sub_windows["memory_monitor"].activateWindow()
        logger.info("打开内存使用监控器")

    def _open_ml_selector(self):
        """打开机器学习模型选择器"""
        if "ml_selector" not in self._sub_windows:
            from ui.ml_selector_window import MLSelectorWindow
            self._sub_windows["ml_selector"] = MLSelectorWindow(on_back=self._show_toolbox)
        self.hide()
        self._sub_windows["ml_selector"].show()
        self._sub_windows["ml_selector"].raise_()
        self._sub_windows["ml_selector"].activateWindow()
        logger.info("打开 ML 模型选择器")

    def _open_settings(self):
        """打开 AI 设置窗口"""
        if "settings" not in self._sub_windows:
            from ui.settings_window import SettingsWindow
            self._sub_windows["settings"] = SettingsWindow(on_back=self._show_toolbox)
        self.hide()
        self._sub_windows["settings"].show()
        self._sub_windows["settings"].raise_()
        self._sub_windows["settings"].activateWindow()
        logger.info("打开 AI 设置")

    def _init_global_hotkey(self):
        """初始化全局热键监听（单例模式）

        在工具箱主窗口中监听所有热键（拾取 + 截图），不依赖 inspector_window 是否已打开。
        拾取热键触发时自动打开 inspector 窗口并进入检查模式。
        使用标志位 + 主线程定时器轮询，跨线程最可靠方案。
        单例模式：整个应用只有一个 HotkeyHandler 实例，避免重复监听。
        """
        self._hotkey_handler = HotkeyHandler.init(
            on_inspect=self._on_global_inspect_click,
            on_screenshot=self._on_global_screenshot_hotkey,
        )
        self._hotkey_handler.set_mode_change_callback(self._on_global_inspect_mode)
        self._hotkey_handler.set_hwnd(int(self.winId()))
        self._hotkey_handler.start()
        logger.info("全局热键已启动，截图热键: %s", self._hotkey_handler.get_screenshot_hotkey_info())

    def nativeEvent(self, eventType, message):
        """接收 WM_HOTKEY 消息，分发到 HotkeyHandler"""
        WM_HOTKEY = 0x0312
        if eventType == "windows_generic_MSG":
            try:
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY:
                    self._hotkey_handler.handle_hotkey(msg.wParam)
                    return True, 0
            except Exception:
                pass
        return False, 0

    def _on_global_inspect_mode(self, m: bool):
        """全局拾取模式变化回调（从 pynput 后台线程调用）

        设置标志位，由主线程定时器轮询处理。
        """
        import threading
        logger.warning("[INSPECT] 拾取模式变化 m=%s, 线程=%s", m, threading.current_thread().name)
        self._inspect_mode_pending = m

    def _on_global_inspect_click(self, x: int, y: int):
        """全局拾取点击回调（从 pynput 后台线程调用）

        设置标志位，由主线程定时器轮询处理。
        """
        import threading
        logger.warning("[INSPECT] 拾取点击 x=%d y=%d, 线程=%s", x, y, threading.current_thread().name)
        self._inspect_click_pending = (x, y)

    def _on_global_screenshot_hotkey(self):
        """全局截图热键触发回调（从 pynput 后台线程调用）

        使用标志位 + 主线程定时器轮询，跨线程最可靠方案。
        不依赖 Signal/QTimer.singleShot（在非 QThread 中可能不工作）。
        """
        import threading
        logger.warning("[SCREENSHOT] 热键触发, 线程=%s, 设置标志位", threading.current_thread().name)
        self._screenshot_pending = True

    def _check_screenshot_pending(self):
        """主线程定时器回调：检查截图标志位

        每 50ms 检查一次，如果标志位为 True，触发截图。
        这个方法在主线程中运行，可以安全调用 Qt UI 操作。
        """
        if self._screenshot_pending:
            self._screenshot_pending = False
            logger.warning("[SCREENSHOT] 主线程检测到标志位，触发截图")
            self._trigger_screenshot(parent_dialog=None)

    def _check_inspect_pending(self):
        """主线程定时器回调：检查拾取标志位

        每 50ms 检查一次，如果有拾取模式变化或点击事件，触发处理。
        这个方法在主线程中运行，可以安全调用 Qt UI 操作。
        """
        # 处理拾取模式变化
        if self._inspect_mode_pending is not None:
            m = self._inspect_mode_pending
            self._inspect_mode_pending = None
            logger.warning("[INSPECT] 主线程检测到模式变化 m=%s", m)
            self._handle_inspect_mode(m)

        # 处理拾取点击
        if self._inspect_click_pending is not None:
            x, y = self._inspect_click_pending
            self._inspect_click_pending = None
            logger.warning("[INSPECT] 主线程检测到点击 x=%d y=%d", x, y)
            self._handle_inspect_click(x, y)

    def _handle_inspect_mode(self, m: bool):
        """处理拾取模式变化（主线程）

        打开 inspector 窗口（如未打开），并触发检查模式。
        """
        # 确保 inspector 窗口已创建
        if "inspector" not in self._sub_windows:
            from ui.inspector_window import GUIInspectorWindow
            self._sub_windows["inspector"] = GUIInspectorWindow(on_back=self._show_toolbox)
            logger.warning("[INSPECT] 首次创建 inspector 窗口")

        # 隐藏主窗口，显示 inspector 窗口
        self.hide()
        inspector = self._sub_windows["inspector"]
        inspector.show()
        inspector.raise_()
        inspector.activateWindow()

        # 触发检查模式（通过信号槽，确保在 inspector 窗口的主线程执行）
        if m:
            logger.warning("[INSPECT] 触发 inspector 窗口进入检查模式")
            inspector.sig.mode_changed.emit(True)
        else:
            logger.warning("[INSPECT] 触发 inspector 窗口退出检查模式")
            inspector.sig.mode_changed.emit(False)

    def _handle_inspect_click(self, x: int, y: int):
        """处理拾取点击（主线程）

        将点击事件转发给 inspector 窗口。
        """
        if "inspector" in self._sub_windows:
            inspector = self._sub_windows["inspector"]
            logger.warning("[INSPECT] 转发点击事件到 inspector 窗口")
            inspector.sig.inspect_requested.emit(x, y)

    def _open_screenshot_info(self):
        """打开截图工具说明页（显示热键、立即截图按钮）"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout as QVBL, QLabel as QLBL, QPushButton as QBtn
        from utils.hotkey_handler import get_screenshot_hotkey_display

        dlg = QDialog(self)
        dlg.setWindowTitle("快速截图标注")
        dlg.setMinimumWidth(400)
        layout = QVBL(dlg)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLBL("快速截图标注")
        title.setFont(FONT_HEADER)
        title.setStyleSheet(f"color:{COLORS['accent']};background:transparent")
        layout.addWidget(title)

        hotkey = get_screenshot_hotkey_display()
        hk_label = QLBL(f"截图热键：{hotkey}")
        hk_label.setFont(FONT_BODY)
        hk_label.setStyleSheet(f"color:{COLORS['fg']};background:transparent")
        layout.addWidget(hk_label)

        desc = QLBL("按下热键后，全屏冻结为画布。\n可绘制红框、箭头、文本框标注，\n确认后复制到剪贴板或另存为。")
        desc.setFont(FONT_SMALL)
        desc.setStyleSheet(f"color:{COLORS['dim']};background:transparent")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        btn_now = QBtn("立即截图")
        btn_now.setFont(FONT_BODY)
        btn_now.setCursor(Qt.PointingHandCursor)
        btn_now.setStyleSheet(
            f"QPushButton{{background:{COLORS['err']};color:white;border:none;border-radius:8px;padding:10px}}"
            f"QPushButton:hover{{background:{COLORS['hl']}}}"
        )
        btn_now.clicked.connect(lambda: self._trigger_screenshot(dlg))
        layout.addWidget(btn_now)

        btn_close = QBtn("关闭")
        btn_close.setFont(FONT_SMALL)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet(
            f"QPushButton{{background:transparent;color:{COLORS['dim']};border:1px solid {COLORS['border']};border-radius:6px;padding:6px}}"
        )
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close)

        dlg.exec()

    def _trigger_screenshot(self, parent_dialog=None):
        """触发截图标注"""
        logger.warning("[SCREENSHOT] _trigger_screenshot 开始, parent_dialog=%s", parent_dialog)
        if parent_dialog:
            parent_dialog.accept()
        self.hide()
        # 延迟执行，等待窗口隐藏
        QTimer.singleShot(200, self._do_screenshot)
        logger.warning("[SCREENSHOT] 已安排 200ms 后执行 _do_screenshot")

    def _do_screenshot(self):
        """执行截图标注

        加 try/except 防御：任何异常都显示错误对话框，避免程序闪退
        传入 on_closed 回调：截图窗口关闭后重新显示主窗口
            避免：截图窗口关闭后没有可见窗口 → Qt 应用退出（看起来像闪退）
        """
        logger.warning("[SCREENSHOT] _do_screenshot 开始执行")
        try:
            from ui.screenshot_annotator import ScreenshotAnnotator
            self._screenshot_annotator = ScreenshotAnnotator(
                on_closed=self._on_screenshot_closed
            )
            self._screenshot_annotator.start()
        except Exception as e:
            logger.exception("截图标注启动失败")
            # 重新显示主窗口，并提示错误
            self.show()
            self.raise_()
            self.activateWindow()
            QMessageBox.critical(
                self,
                "截图启动失败",
                f"截图标注工具启动失败：\n{e}\n\n请查看日志获取详细信息。",
            )

    def _on_screenshot_closed(self):
        """截图窗口关闭后，重新显示主窗口

        作用：避免截图窗口关闭后没有可见窗口，导致 Qt 应用退出（看起来像闪退）
        """
        try:
            self.show()
            self.raise_()
            self.activateWindow()
            logger.info("截图窗口关闭，已重新显示主窗口")
        except Exception as e:
            logger.exception("重新显示主窗口失败")



    def _show_toolbox(self):
        """返回工具箱主界面"""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _init_tray(self):
        """初始化系统托盘"""
        self._tray = QSystemTrayIcon(self._app_icon, self)
        self._tray.setToolTip("辅助编程工具箱")
        
        self._tray_menu = QMenu()
        
        act_show = QAction("显示工具箱", self)
        act_show.triggered.connect(self._on_tray_show_clicked)
        self._tray_menu.addAction(act_show)
        
        self._tray_menu.addSeparator()
        
        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self._quit_app)
        self._tray_menu.addAction(act_quit)
        
        self._tray.setContextMenu(self._tray_menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()
        logger.info("系统托盘已初始化")

    def _on_tray_show_clicked(self):
        """系统托盘菜单"显示工具箱"点击处理"""
        logger.warning("[TRAY] 菜单点击: 显示工具箱")
        self._show_toolbox()

    def _on_tray_activated(self, reason):
        """双击托盘图标显示主窗口"""
        if reason == QSystemTrayIcon.DoubleClick:
            logger.warning("[TRAY] 双击托盘图标")
            self._show_toolbox()
        elif reason == QSystemTrayIcon.Trigger:
            logger.warning("[TRAY] 单击托盘图标")
            self._show_toolbox()

    def _quit_app(self):
        """退出应用"""
        self._force_quit = True
        # 停止截图轮询定时器
        if hasattr(self, "_screenshot_timer") and self._screenshot_timer:
            self._screenshot_timer.stop()
        # 停止全局热键监听
        if hasattr(self, "_hotkey_handler") and self._hotkey_handler:
            self._hotkey_handler.stop()
        self._tray.hide()
        # 关闭所有子窗口
        for w in self._sub_windows.values():
            if hasattr(w, "close"):
                w.close()
        # 关闭所有剩余的顶级窗口（如未被 _sub_windows 追踪的 AI 分析对话框）
        for w in list(QApplication.topLevelWidgets()):
            if w is not self and w is not self._tray:
                w.close()
        self.close()

    def closeEvent(self, e):
        """关闭按钮最小化到托盘"""
        if getattr(self, "_force_quit", False):
            logger.info("应用退出")
            e.accept()
        else:
            e.ignore()
            self.hide()
            self._tray.showMessage(
                "辅助编程工具箱",
                "程序已最小化到托盘，双击图标可重新打开。",
                QSystemTrayIcon.Information, 3000,
            )


def main():
    """程序入口"""
    app = QApplication(sys.argv)
    app.setApplicationName("辅助编程工具箱")
    if os.path.exists(_ICON_PATH):
        app.setWindowIcon(QIcon(_ICON_PATH))
    window = ToolboxMainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
