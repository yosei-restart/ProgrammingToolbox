"""
变量生命周期追踪器 - 动态追踪 UI 窗口
PySide6 (LGPLv3) - GitHub Dark 主题

通过 sys.settrace 在子进程中运行目标程序，追踪变量的运行时值变化。

用户流程：
1. 选择文件夹（项目根目录）
2. 选择入口文件（main.py）
3. 输入要追踪的变量名
4. 输入运行参数（可选）
5. 点击"开始动态追踪" → 目标程序启动 → 用户操作 → 关闭目标程序
6. 追踪结果展示在卡片链上
"""

import os
import sys
import json
import subprocess
import tempfile
import threading
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QLineEdit, QScrollArea, QFrame, QFileDialog, QProgressBar,
    QComboBox, QApplication, QDialog, QTextEdit, QDialogButtonBox, QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QProcess
from PySide6.QtGui import QFont

from utils.theme import COLORS, FONT_TITLE, FONT_HEADER, FONT_BODY, FONT_MONO, FONT_SMALL, FONT_SIZE_ICON_LARGE, get_global_stylesheet, apply_text_selectable
from utils.logging_utils import get_logger
from core.lifecycle_tracer import get_all_variable_names, fuzzy_match
from core.dynamic_tracer import load_result, DynamicResult, DynamicEvent

logger = get_logger(__name__)


def _generate_gradient_colors(count: int, start_hue: float = 0.35, end_hue: float = 0.95) -> list:
    """生成渐变色列表，从绿色（诞生）到红色（消亡）"""
    if count <= 1:
        return ["#3fb950"]
    import colorsys
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


def _find_venv(folder_path: str):
    """在目标文件夹及其上层目录中查找虚拟环境

    查找顺序：
    1. 目标文件夹子目录中的 venv/.venv
    2. 向上逐级查找父目录及子目录

    Returns:
        虚拟环境根目录路径（包含 pyvenv.cfg 的目录），找不到返回 None
    """
    def _check_dir(path):
        """检查目录是否为虚拟环境（存在 pyvenv.cfg）"""
        return os.path.isfile(os.path.join(path, "pyvenv.cfg"))

    # 从当前文件夹向上查找
    current = os.path.abspath(folder_path)
    for _ in range(10):  # 最多向上查 10 级
        if _check_dir(current):
            return current
        # 检查子目录中的 venv / .venv
        for venv_name in ("venv", ".venv", "env", ".env"):
            candidate = os.path.join(current, venv_name)
            if _check_dir(candidate):
                return candidate
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


def _get_venv_python(venv_root: str):
    """获取虚拟环境的 Python 解释器路径

    Args:
        venv_root: 虚拟环境根目录（包含 pyvenv.cfg 的目录）

    Returns:
        Python 解释器路径，找不到返回 None
    """
    if sys.platform == "win32":
        candidates = [
            os.path.join(venv_root, "Scripts", "python.exe"),
            os.path.join(venv_root, "Scripts", "python3.exe"),
        ]
    else:
        candidates = [
            os.path.join(venv_root, "bin", "python"),
            os.path.join(venv_root, "bin", "python3"),
        ]

    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


class DynamicTracerSignals(QObject):
    """动态追踪器信号"""
    status = Signal(str, str)
    scan_done = Signal(list)
    trace_done = Signal(object)
    trace_error = Signal(str)
    busy_changed = Signal(bool)
    target_lines_ready = Signal(list)  # 静态分析完成，传递目标行列表
    ai_done = Signal(str)
    ai_error = Signal(str)


class DynamicTracerWindow(QWidget):
    """变量生命周期动态追踪器窗口"""

    def __init__(self, on_back=None):
        super().__init__()
        self.setWindowTitle("变量生命周期追踪器 - 动态追踪")
        self.resize(1200, 800)
        self.setMinimumSize(900, 600)
        self._on_back = on_back
        self._folder_path = ""
        self._all_vars = []
        self._entry_files = []
        self._result = None
        self._html_path = None
        self._qprocess = None
        self._result_file = None

        self.setStyleSheet(self._global_style())

        self.sig = DynamicTracerSignals()
        self.sig.status.connect(self._on_status)
        self.sig.scan_done.connect(self._on_scan_done)
        self.sig.trace_done.connect(self._on_trace_done)
        self.sig.trace_error.connect(self._on_trace_error)
        self.sig.busy_changed.connect(self._on_busy)
        self.sig.target_lines_ready.connect(self._on_target_lines_ready)
        self.sig.ai_done.connect(self._on_ai_done)
        self.sig.ai_error.connect(self._on_ai_error)

        self._build_ui()
        self._on_status("请选择一个包含 Python 源码的文件夹", COLORS["warn"])
        apply_text_selectable(self)

    def _global_style(self) -> str:
        """窗口级全局样式"""
        C = COLORS
        return f"""
            QWidget {{ background:{C['bg']}; color:{C['fg']}; }}
            QLabel {{ background:transparent; color:{C['fg']}; }}
            QFrame {{ background:{C['bg']}; color:{C['fg']}; }}
            QPushButton {{ background:{C['panel']}; color:{C['fg']};
                border:1px solid {C['border']}; border-radius:6px; padding:6px 14px; }}
            QPushButton:hover {{ background:{C['border']}; color:{C['accent']}; border:1px solid {C['accent']}; }}
            QPushButton:disabled {{ background:{C['panel']}; color:{C['dim']}; border:1px solid {C['border']}; }}
            QLineEdit {{ background:{C['input']}; color:{C['fg']};
                border:1px solid {C['border']}; border-radius:6px; padding:6px 10px; }}
            QLineEdit:focus {{ border:1px solid {C['accent']}; }}
            QLineEdit:read-only {{ background:{C['panel']}; color:{C['dim']}; }}
            QComboBox {{ background:{C['input']}; color:{C['fg']};
                border:1px solid {C['border']}; border-radius:6px; padding:6px 10px; }}
            QComboBox QAbstractItemView {{ background:{C['panel']}; color:{C['fg']};
                selection-background-color:{C['accent']}; selection-color:{C['head']}; border:1px solid {C['border']}; }}
            QScrollArea {{ border:none; background:transparent; }}
            QScrollBar:vertical {{ background:transparent; width:14px; margin:0; }}
            QScrollBar::handle:vertical {{ background:#4a90d9; border-radius:7px; min-height:30px; margin:3px; }}
            QScrollBar::handle:vertical:hover {{ background:#5da8f5; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
            QScrollBar:horizontal {{ background:transparent; height:14px; margin:0; }}
            QScrollBar::handle:horizontal {{ background:#4a90d9; border-radius:7px; min-width:30px; margin:3px; }}
            QScrollBar::handle:horizontal:hover {{ background:#5da8f5; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width:0; }}
            QProgressBar {{ background:{C['border']}; border:none; border-radius:2px; }}
            QProgressBar::chunk {{ background:{C['accent']}; border-radius:2px; }}
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
        header.setStyleSheet(
            f"background:{COLORS['head']};border-bottom:1px solid {COLORS['border']}"
        )
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

        title = QLabel("变量生命周期追踪器 — 动态追踪")
        title.setFont(FONT_TITLE)
        title.setStyleSheet(f"color:{COLORS['accent']};background:transparent")
        hl.addWidget(title)
        hl.addStretch()

        event_hint = QLabel("📋 诞生=首次创建 | 使用=读取/传参 | 赋值=值变化 | 销毁=作用域结束")
        event_hint.setFont(FONT_BODY)
        event_hint.setStyleSheet(f"color:#FF00FF;background:transparent")
        hl.addWidget(event_hint)
        hl.addSpacing(12)

        self._btn_force_stop = QPushButton("强制停止")
        self._btn_force_stop.setFont(FONT_BODY)
        self._btn_force_stop.setCursor(Qt.PointingHandCursor)
        self._btn_force_stop.setEnabled(False)
        self._btn_force_stop.setStyleSheet(
            f"QPushButton{{background:{COLORS['err']};color:{COLORS['head']};"
            f"border:none;border-radius:6px;padding:6px 14px;font-weight:bold}} "
            f"QPushButton:hover{{background:#f85149}} "
            f"QPushButton:disabled{{background:{COLORS['panel']};color:{COLORS['dim']}}}"
        )
        self._btn_force_stop.clicked.connect(self._force_stop_trace)
        hl.addWidget(self._btn_force_stop)

        return header

    def _build_input_area(self):
        """输入区：文件夹+入口文件+变量名+运行参数"""
        frame = QFrame()
        frame.setStyleSheet(
            f"background:{COLORS['panel']};border-bottom:1px solid {COLORS['border']}"
        )
        vl = QVBoxLayout(frame)
        vl.setContentsMargins(16, 12, 16, 12)
        vl.setSpacing(8)

        # 第1行：文件夹选择
        row1 = QHBoxLayout()
        lbl1 = QLabel("目标文件夹:")
        lbl1.setFont(FONT_BODY)
        lbl1.setStyleSheet(f"color:{COLORS['fg']};background:transparent;font-weight:bold")
        row1.addWidget(lbl1)

        self._folder_edit = QLineEdit()
        self._folder_edit.setFont(FONT_BODY)
        self._folder_edit.setPlaceholderText("选择包含 .py 文件的项目文件夹...")
        self._folder_edit.setReadOnly(True)
        row1.addWidget(self._folder_edit, 1)

        btn_browse = QPushButton("选择文件夹")
        btn_browse.setFont(FONT_BODY)
        btn_browse.setCursor(Qt.PointingHandCursor)
        btn_browse.setStyleSheet(
            f"QPushButton{{background:{COLORS['accent']};color:{COLORS['head']};"
            f"border:none;border-radius:6px;padding:6px 14px;font-weight:bold}} "
            f"QPushButton:hover{{background:{COLORS['ahover']}}}"
        )
        btn_browse.clicked.connect(self._on_browse)
        row1.addWidget(btn_browse)
        vl.addLayout(row1)

        # 第2行：Python 解释器选择
        row_interp = QHBoxLayout()
        lbl_interp = QLabel("Python 解释器:")
        lbl_interp.setFont(FONT_BODY)
        lbl_interp.setStyleSheet(f"color:{COLORS['fg']};background:transparent;font-weight:bold")
        row_interp.addWidget(lbl_interp)

        self._interp_combo = QComboBox()
        self._interp_combo.setFont(FONT_BODY)
        self._interp_combo.setPlaceholderText("选择运行目标程序使用的 Python 解释器...")
        self._detect_interpreters()
        row_interp.addWidget(self._interp_combo, 1)
        vl.addLayout(row_interp)

        # 第3行：入口文件选择（下拉框）
        row2 = QHBoxLayout()
        lbl2 = QLabel("入口文件:")
        lbl2.setFont(FONT_BODY)
        lbl2.setStyleSheet(f"color:{COLORS['fg']};background:transparent;font-weight:bold")
        row2.addWidget(lbl2)

        self._entry_combo = QComboBox()
        self._entry_combo.setFont(FONT_BODY)
        self._entry_combo.setEnabled(False)
        self._entry_combo.setPlaceholderText("选择程序入口文件（如 main.py）...")
        row2.addWidget(self._entry_combo, 1)
        vl.addLayout(row2)

        # 第3行：变量名标签+输入框+运行参数标签+输入框+追踪按钮（等比例）
        row3 = QHBoxLayout()
        row3.setSpacing(8)

        lbl3 = QLabel("变量名:")
        lbl3.setFont(FONT_BODY)
        lbl3.setStyleSheet(f"color:{COLORS['fg']};background:transparent;font-weight:bold")
        row3.addWidget(lbl3)

        self._var_edit = QLineEdit()
        self._var_edit.setFont(FONT_BODY)
        self._var_edit.setPlaceholderText("输入要追踪的变量名...")
        self._var_edit.textChanged.connect(self._on_var_input)
        row3.addWidget(self._var_edit, 1)

        lbl4 = QLabel("运行参数:")
        lbl4.setFont(FONT_BODY)
        lbl4.setStyleSheet(f"color:{COLORS['fg']};background:transparent;font-weight:bold")
        row3.addWidget(lbl4)

        self._args_edit = QLineEdit()
        self._args_edit.setFont(FONT_BODY)
        self._args_edit.setPlaceholderText("可选，如 --input data.txt")
        row3.addWidget(self._args_edit, 1)

        self._btn_trace = QPushButton("开始动态追踪")
        self._btn_trace.setFont(FONT_BODY)
        self._btn_trace.setCursor(Qt.PointingHandCursor)
        self._btn_trace.setEnabled(False)
        self._btn_trace.setStyleSheet(
            f"QPushButton{{background:{COLORS['accent']};color:{COLORS['head']};"
            f"border:none;border-radius:6px;padding:8px 24px;font-weight:bold}} "
            f"QPushButton:hover{{background:{COLORS['ahover']}}} "
            f"QPushButton:disabled{{background:{COLORS['border']};color:{COLORS['dim']};border:none}}"
        )
        self._btn_trace.clicked.connect(self._on_trace)
        row3.addWidget(self._btn_trace, 1)
        vl.addLayout(row3)

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
        vl = QVBoxLayout(container)
        vl.setContentsMargins(16, 4, 16, 4)
        vl.setSpacing(8)

        self._empty_label = QLabel(
            "选择文件夹 → 选择入口文件 → 输入变量名 → 点击「开始动态追踪」\n\n"
            "追踪流程：\n"
            "1. 工具在子进程中启动你的程序\n"
            "2. 你正常操作程序（点击按钮、输入数据等）\n"
            "3. 工具在后台记录变量每次值的变化\n"
            "4. 关闭程序后，追踪结果自动展示在这里\n\n"
            "动态追踪能看到变量运行时的真实值和类型变化"
        )
        self._empty_label.setFont(FONT_BODY)
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet(
            f"color:{COLORS['dim']};background:transparent;padding:40px"
        )
        vl.addWidget(self._empty_label)

        self._card_container = QWidget()
        self._card_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._card_layout = QHBoxLayout(self._card_container)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.setSpacing(12)
        self._card_layout.setAlignment(Qt.AlignTop)
        self._card_layout.addStretch()
        self._card_container.hide()
        vl.addWidget(self._card_container, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(container)
        scroll.setStyleSheet("QScrollArea{border:none}")
        return scroll

    def _build_bottom_bar(self):
        """底部操作栏 + 状态栏 + 进度条"""
        bar = QFrame()
        bar.setFixedHeight(70)
        bar.setStyleSheet(
            f"background:{COLORS['head']};border-top:1px solid {COLORS['border']}"
        )
        vl = QVBoxLayout(bar)
        vl.setContentsMargins(16, 4, 16, 4)
        vl.setSpacing(2)

        hl = QHBoxLayout()

        self._status_label = QLabel("")
        self._status_label.setFont(FONT_SMALL)
        self._status_label.setWordWrap(True)
        self._status_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._status_label.setStyleSheet(f"color:{COLORS['fg']};background:transparent")
        hl.addWidget(self._status_label, 1)

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

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        vl.addWidget(self._progress)

        return bar

    # ─── 复制工具 ───

    def _copy_btn(self, text: str, tooltip: str = "复制", label: str = "") -> QPushButton:
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
        cb = QApplication.clipboard()
        cb.setText(text)
        if label:
            self._on_status(f"已复制：{label}的内容", COLORS["ok"])
        else:
            self._on_status(f"已复制：{text[:40]}", COLORS["ok"])

    def _on_busy(self, busy: bool):
        self._progress.setVisible(busy)

    # ─── 事件处理 ───

    def _detect_interpreters(self, folder_path: str = ""):
        """自动检测系统中可用的 Python 解释器

        优先级：
        1. 目标文件夹及其上层目录中的虚拟环境 (venv/.venv)
        2. 系统安装的 Python（完整标准库）
        3. 工具箱自身的 Python（可能缺少 tkinter 等）

        Args:
            folder_path: 目标文件夹路径，用于搜索附近的虚拟环境
        """
        import shutil
        candidates = []  # [(path, label, priority)] priority 越小越优先
        seen = set()

        def _add(path: str, priority: int, tag: str = ""):
            abs_path = os.path.abspath(path)
            if abs_path in seen or not os.path.isfile(abs_path):
                return
            # 获取版本号
            try:
                result = subprocess.run(
                    [abs_path, "--version"],
                    capture_output=True, text=True, timeout=3,
                )
                version = (result.stdout or result.stderr).strip()
            except Exception:
                version = ""
            # 检查是否有 tkinter（关键依赖）
            try:
                tk_check = subprocess.run(
                    [abs_path, "-c", "import tkinter"],
                    capture_output=True, timeout=3,
                )
                has_tk = tk_check.returncode == 0
            except Exception:
                has_tk = False

            tk_tag = " ✓tkinter" if has_tk else " ✗tkinter"
            tag_str = f" [{tag}]" if tag else ""
            label = f"{abs_path}  ({version}{tk_tag}){tag_str}"
            candidates.append((priority, abs_path, label))
            seen.add(abs_path)

        # ── 优先级 1：目标文件夹及上层目录的虚拟环境 ──
        if folder_path:
            venv_root = _find_venv(folder_path)
            if venv_root:
                venv_python = _get_venv_python(venv_root)
                if venv_python:
                    _add(venv_python, 0, "项目虚拟环境")

        # ── 优先级 2：系统安装的 Python ──
        # 使用 LOCALAPPDATA 环境变量动态获取用户目录，避免硬编码用户名
        localappdata = os.environ.get("LOCALAPPDATA", "")
        system_pythons = []
        if localappdata:
            system_pythons.extend([
                os.path.join(localappdata, "Programs", "Python", "Python312", "python.exe"),
                os.path.join(localappdata, "Programs", "Python", "Python311", "python.exe"),
                os.path.join(localappdata, "Programs", "Python", "Python310", "python.exe"),
            ])
        system_pythons.extend([
            r"C:\Python312\python.exe",
            r"C:\Python311\python.exe",
            r"C:\Python310\python.exe",
        ])
        for py_path in system_pythons:
            _add(py_path, 1, "系统Python")

        # PATH 中的 python
        for name in ("python", "python3"):
            path = shutil.which(name)
            if path:
                _add(path, 2, "PATH")

        # ── 优先级 3：工具箱自身的 Python（最后选项）──
        _add(sys.executable, 3, "工具箱Python")

        # 按优先级排序
        candidates.sort(key=lambda x: x[0])

        # 填充下拉框
        self._interp_combo.clear()
        for _, path, label in candidates:
            self._interp_combo.addItem(label, path)

        # 默认选优先级最高的
        if candidates:
            self._interp_combo.setCurrentIndex(0)

    def _on_browse(self):
        """选择文件夹"""
        folder = QFileDialog.getExistingDirectory(self, "选择包含 Python 源码的文件夹")
        if folder:
            self._folder_path = folder
            self._folder_edit.setText(folder)
            # 重新检测解释器（优先搜索文件夹附近的虚拟环境）
            self._detect_interpreters(folder)
            self._on_status(f"正在扫描 {folder} ...", COLORS["warn"])
            self.sig.busy_changed.emit(True)
            threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self):
        """后台扫描文件夹中所有变量名和入口文件"""
        try:
            # 扫描变量名
            names = get_all_variable_names(self._folder_path)
            # 扫描入口文件（.py 文件，优先显示含 if __name__ 的）
            entry_files = []
            for root, dirs, files in os.walk(self._folder_path):
                # 排除目录
                dirs[:] = [d for d in dirs if d not in {
                    "venv", ".venv", "__pycache__", ".git", "node_modules",
                    ".tox", ".eggs", "build", "dist", ".mypy_cache", ".pytest_cache",
                    "backups",
                }]
                for f in files:
                    if f.endswith(".py"):
                        fp = os.path.join(root, f)
                        rel = os.path.relpath(fp, self._folder_path)
                        # 检查是否含 if __name__
                        try:
                            with open(fp, "r", encoding="utf-8") as fh:
                                content = fh.read()
                            is_entry = "__name__" in content and "__main__" in content
                        except Exception:
                            is_entry = False
                        entry_files.append((rel, is_entry))
            # 入口文件排在前面
            entry_files.sort(key=lambda x: (not x[1], x[0]))
            self._entry_files = entry_files
            self.sig.scan_done.emit(names)
        except Exception as e:
            logger.error("扫描文件夹失败: %s", e, exc_info=True)
            self.sig.status.emit(f"扫描失败: {e}", COLORS["err"])
        finally:
            self.sig.busy_changed.emit(False)

    def _on_scan_done(self, names):
        """扫描完成"""
        self._all_vars = names
        # 填充入口文件下拉框
        self._entry_combo.clear()
        for rel_path, is_entry in self._entry_files:
            label = f"{rel_path}" + (" ★入口" if is_entry else "")
            self._entry_combo.addItem(label, rel_path)
        self._entry_combo.setEnabled(True)
        self._on_status(
            f"扫描完成: {len(names)} 个变量, {len(self._entry_files)} 个 .py 文件",
            COLORS["ok"],
        )
        self._var_edit.setFocus()

    def _on_var_input(self, text):
        """输入框文本变化，实时模糊搜索"""
        text = text.strip()
        if not text:
            self._suggestion_frame.hide()
            self._btn_trace.setEnabled(False)
            return
        # _all_vars 为空只影响自动补全，不阻止追踪
        if not self._all_vars:
            self._suggestion_frame.hide()
            self._btn_trace.setEnabled(self._entry_combo.currentData() is not None)
            return

        matched = fuzzy_match(text, self._all_vars, limit=30)
        if not matched:
            self._suggestion_frame.hide()
            self._btn_trace.setEnabled(bool(text) and self._entry_combo.currentData() is not None)
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
        self._check_trace_ready()

    def _on_select_suggestion(self, name):
        self._var_edit.setText(name)
        self._suggestion_frame.hide()
        self._check_trace_ready()

    def _check_trace_ready(self):
        """检查是否可以开始追踪"""
        ready = (
            bool(self._var_edit.text().strip())
            and self._entry_combo.currentData() is not None
            and bool(self._folder_path)
        )
        self._btn_trace.setEnabled(ready)

    def _on_trace(self):
        """开始动态追踪

        优化流程（子线程版，不阻塞 UI）：
        1. 在子线程中用静态分析（AST）扫描变量位置
        2. 完成后通过信号回主线程
        3. 主线程启动子进程运行目标程序
        """
        var_name = self._var_edit.text().strip()
        entry_rel = self._entry_combo.currentData()
        if not var_name or not entry_rel:
            self._on_status("请先选择入口文件并输入变量名", COLORS["warn"])
            return

        # 保存参数，供 _on_target_lines_ready 使用
        self._pending_entry_path = os.path.join(self._folder_path, entry_rel)
        self._pending_var_name = var_name
        self._pending_run_args = (
            self._args_edit.text().split() if self._args_edit.text().strip() else []
        )

        # 创建临时结果文件
        self._result_file = os.path.join(
            tempfile.gettempdir(),
            f"dynamic_trace_{var_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        )

        self._btn_trace.setEnabled(False)
        self._on_status(
            f"正在分析变量 [{var_name}] 的代码位置...",
            COLORS["warn"],
        )
        self.sig.busy_changed.emit(True)

        # 在子线程中执行静态分析（不阻塞 UI）
        threading.Thread(
            target=self._do_build_target_lines,
            args=(var_name,),
            daemon=True,
        ).start()

    def _do_build_target_lines(self, var_name: str):
        """子线程：执行静态分析，构建目标行列表"""
        try:
            target_lines = self._build_target_lines(var_name)
            self.sig.target_lines_ready.emit(target_lines or [])
        except Exception as e:
            logger.error("静态分析失败: %s", e, exc_info=True)
            self.sig.target_lines_ready.emit([])

    def _on_target_lines_ready(self, target_lines: list):
        """主线程：静态分析完成，启动子进程"""
        var_name = self._pending_var_name
        entry_path = self._pending_entry_path
        run_args = self._pending_run_args
        entry_rel = os.path.relpath(entry_path, self._folder_path)

        if target_lines:
            self._on_status(
                f"静态分析完成: 找到 {len(target_lines)} 个目标位置 · 正在启动目标程序: {entry_rel} · 追踪变量: {var_name} · 请操作目标程序，完成后关闭它即可查看追踪结果",
                COLORS["warn"],
            )
        else:
            self._on_status(
                f"未找到变量 [{var_name}] 的静态位置，将追踪所有行 · 正在启动目标程序: {entry_rel} · 请操作目标程序，完成后关闭它即可查看追踪结果",
                COLORS["warn"],
            )

        # 在子进程中运行追踪（传入 target_lines）
        self._run_tracer_subprocess(entry_path, var_name, run_args, target_lines)

    def _build_target_lines(self, var_name: str) -> list:
        """用静态分析构建目标行列表（包含函数名信息用于优化）

        扫描目标文件夹中所有 .py 文件，找出变量 var_name 出现的所有位置。

        Args:
            var_name: 目标变量名

        Returns:
            [[abs_file_path, line_no, func_name], ...] 列表，空列表表示未找到
        """
        try:
            from core.lifecycle_tracer import extract_variable_events

            result = extract_variable_events(self._folder_path, var_name)
            if not result or not result.events:
                return []

            target_lines = []
            seen = set()
            for event in result.events:
                if not event.file_path or not event.line:
                    continue
                abs_file = os.path.realpath(os.path.join(self._folder_path, event.file_path))
                # 正确提取函数名：只有 func: 和 method: 开头的 scope 才有函数名
                # module: 开头的是模块级，没有函数名
                func_name = ""
                if ":" in event.scope:
                    scope_type, scope_body = event.scope.split(":", 1)
                    if scope_type in ("func", "method"):
                        # 函数/方法名：method:ClassName.method -> ClassName.method
                        # 运行时 frame.f_code.co_name 只有方法名（不含类名），所以取最后一段
                        func_name = scope_body.split(".")[-1]
                key = (abs_file, event.line)
                if key in seen:
                    continue
                seen.add(key)
                target_lines.append([abs_file, event.line, func_name])
                logger.warning("[BUILD_TARGET] 文件=%s 行=%d 类型=%s 函数=%r 代码=%r", event.file_path, event.line, event.event_type, func_name, event.code_line)

            return target_lines
        except Exception as e:
            logger.error("静态分析构建 target_lines 失败: %s", e, exc_info=True)
            return []

    def _run_tracer_subprocess(self, entry_path: str, var_name: str, run_args: list, target_lines: list = None):
        """在子进程中运行追踪代理

        Args:
            entry_path: 目标程序入口文件路径
            var_name: 要追踪的变量名
            run_args: 传给目标程序的命令行参数
            target_lines: 静态分析定位的变量出现位置列表，
                          [[abs_file_path, line_no], ...]
        """
        # 使用用户选择的 Python 解释器，默认回退到当前 Python
        python_exe = self._interp_combo.currentData() or sys.executable

        # 计算项目根目录（包含 core/ 的目录）
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # 写入临时代理脚本（将 target_lines 嵌入脚本）
        target_lines_repr = repr(target_lines) if target_lines else "None"
        agent_code = f"""
import sys
sys.path.insert(0, r"{project_root}")
from core.dynamic_tracer import run_tracer
run_tracer(
    r"{entry_path}",
    "{var_name}",
    r"{self._folder_path}",
    r"{self._result_file}",
    {run_args!r},
    target_lines={target_lines_repr},
)
"""

        agent_file = os.path.join(tempfile.gettempdir(), "_dynamic_tracer_agent.py")
        with open(agent_file, "w", encoding="utf-8") as f:
            f.write(agent_code)

        # 使用 QProcess 在子进程中运行
        self._qprocess = QProcess(self)
        self._qprocess.setProcessChannelMode(QProcess.SeparateChannels)
        self._qprocess.finished.connect(self._on_process_finished)
        self._qprocess.errorOccurred.connect(self._on_process_error)
        # 捕获 stderr 输出，用于显示启动失败原因
        self._qprocess.readyReadStandardError.connect(self._on_stderr_ready)
        self._process_stderr = ""
        self._qprocess.start(python_exe, [agent_file])
        self._btn_force_stop.setEnabled(True)

    def _force_stop_trace(self):
        """强制停止追踪进程"""
        self._force_stopped = True
        if self._qprocess and self._qprocess.state() != QProcess.NotRunning:
            self._qprocess.kill()
            self._qprocess.waitForFinished(3000)
            self._on_status("已强制停止追踪", COLORS["warn"])
            self._btn_force_stop.setEnabled(False)

    def _on_process_error(self, error):
        """QProcess 启动失败"""
        error_msgs = {
            QProcess.FailedToStart: "无法启动进程（Python 路径错误或权限不足）",
            QProcess.Crashed: "进程崩溃",
            QProcess.Timedout: "超时",
            QProcess.WriteError: "写入错误",
            QProcess.ReadError: "读取错误",
            QProcess.UnknownError: "未知错误",
        }
        msg = error_msgs.get(error, f"错误码 {error}")
        self._on_status(f"启动失败: {msg}", COLORS["err"])
        self.sig.busy_changed.emit(False)
        self._btn_trace.setEnabled(True)

    def _on_stderr_ready(self):
        """捕获子进程 stderr 输出，显示进度日志"""
        data = self._qprocess.readAllStandardError()
        if data:
            text = bytes(data).decode("utf-8", errors="replace")
            self._process_stderr = getattr(self, "_process_stderr", "") + text
            for line in text.strip().split("\n"):
                    if "[TRACE]" in line:
                        progress = line.split("[TRACE]")[-1].strip()
                        self._on_status(f"追踪进度: {progress}", COLORS["warn"])
                        logger.warning("[TRACE] %s", progress)
                    elif "[BUILD_TARGET]" in line:
                        idx = line.find("[BUILD_TARGET]")
                        target_log = line[idx:]
                        self._on_status(f"动态追踪命中: {target_log}", COLORS["warn"])
                        logger.warning(target_log)

    def _on_process_finished(self, exit_code, exit_status):
        """子进程结束，读取结果"""
        self.sig.busy_changed.emit(False)
        self._btn_trace.setEnabled(True)
        self._btn_force_stop.setEnabled(False)

        # 用户主动强制停止，不弹错误
        if getattr(self, "_force_stopped", False):
            self._force_stopped = False
            self._on_status("已强制停止追踪", COLORS["warn"])
            return

        if not os.path.exists(self._result_file):
            # 显示捕获的 stderr 帮助用户定位启动失败原因
            stderr = getattr(self, "_process_stderr", "").strip()
            if stderr:
                # 弹出独立错误窗口，方便查看完整错误信息
                self._show_error_dialog(
                    "目标程序启动失败",
                    f"退出码: {exit_code}\n\n{stderr}",
                )
                self._on_status(
                    f"目标程序启动失败 (exit_code={exit_code})，请查看错误窗口",
                    COLORS["err"],
                )
            else:
                self._on_status(
                    f"追踪结束但未找到结果文件（程序可能异常退出，exit_code={exit_code}）",
                    COLORS["err"],
                )
            return

        try:
            result = load_result(self._result_file)
            self.sig.trace_done.emit(result)
        except Exception as e:
            logger.error("加载追踪结果失败: %s", e, exc_info=True)
            self.sig.trace_error.emit(str(e))

    def _on_trace_done(self, result):
        """追踪完成，渲染卡片链"""
        self._result = result
        self._btn_export.setEnabled(result.total_events > 0)
        self._btn_ai.setEnabled(result.total_events > 0)

        if result.error:
            # 弹出错误窗口显示完整错误信息
            self._show_error_dialog("目标程序运行出错", result.error)
            self._on_status(
                f"程序运行出错，请查看错误窗口",
                COLORS["err"],
            )

        if result.total_events == 0:
            self._on_status(
                f"未追踪到变量「{result.variable_name}」的任何事件\n"
                f"可能原因：变量未在运行时被创建，或程序未执行到相关代码",
                COLORS["warn"],
            )
            return

        # 清空旧卡片
        while self._card_layout.count() > 1:
            item = self._card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._empty_label.hide()
        self._card_container.show()

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

        stats = (
            f"变量: {result.variable_name} | "
            f"总事件: {result.total_events} | "
            f"诞生: {result.birth_count} | "
            f"赋值: {result.assign_count} | "
            f"使用: {result.use_count} | "
            f"消亡: {result.death_count} | "
            f"运行时长: {result.duration}s"
        )
        self._on_status(stats, COLORS["ok"])
        logger.info("动态追踪完成: %s, %d 个事件", result.variable_name, result.total_events)

    def _on_trace_error(self, msg):
        self._btn_trace.setEnabled(True)
        self._on_status(f"追踪失败: {msg}", COLORS["err"])

    def _show_error_dialog(self, title: str, error_text: str):
        """弹出独立错误窗口显示子进程的完整错误输出

        Args:
            title: 窗口标题
            error_text: 错误文本（完整 stderr）
        """
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(700, 450)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 错误图标 + 标题
        header = QHBoxLayout()
        icon = QLabel("⚠")
        icon.setStyleSheet(f"font-size:{FONT_SIZE_ICON_LARGE}px;color:{COLORS['warn']};background:transparent")
        header.addWidget(icon)
        label = QLabel("目标程序运行出错，以下是完整错误信息：")
        label.setStyleSheet(f"color:{COLORS['fg']};background:transparent;font-weight:bold")
        label.setWordWrap(True)
        header.addWidget(label, 1)
        layout.addLayout(header)

        # 错误文本区域（可选中复制）
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setFont(FONT_MONO)
        text_edit.setStyleSheet(
            f"QTextEdit{{background:{COLORS['input']};color:{COLORS['fg']};"
            f"border:1px solid {COLORS['border']};border-radius:6px;padding:8px}}"
        )
        text_edit.setPlainText(error_text)
        layout.addWidget(text_edit, 1)

        # 关闭按钮
        btn_box = QDialogButtonBox(QDialogButtonBox.Close)
        btn_box.setStyleSheet(
            f"QPushButton{{background:{COLORS['accent']};color:{COLORS['head']};"
            f"border:none;border-radius:6px;padding:6px 20px}}"
        )
        btn_box.rejected.connect(dlg.close)
        layout.addWidget(btn_box)

        dlg.exec_()

    def _create_event_card(self, event: DynamicEvent, index: int, gradient_color: str) -> QFrame:
        """创建单个事件卡片"""
        card = QFrame()
        card.setMinimumWidth(400)
        card.setObjectName("dynCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        card.setStyleSheet(
            f"QFrame#dynCard{{background:{COLORS['panel']};"
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

        content = QVBoxLayout()
        content.setContentsMargins(8, 0, 8, 0)
        content.setSpacing(0)

        # 第1行：序号 + 事件类型 + 时间戳 + 复制
        header_row = QHBoxLayout()
        idx_lbl = QLabel(f"#{index}")
        idx_lbl.setFont(FONT_SMALL)
        idx_lbl.setStyleSheet(f"color:{COLORS['dim']};background:transparent")
        _make_selectable(idx_lbl)
        header_row.addWidget(idx_lbl)

        type_lbl = QLabel(event.event_type)
        type_lbl.setFont(FONT_HEADER)
        type_lbl.setStyleSheet(
            f"color:{gradient_color};background:transparent;font-weight:bold"
        )
        _make_selectable(type_lbl)
        header_row.addWidget(type_lbl)

        time_lbl = QLabel(f"程序运行时长@{event.timestamp:.3f}s")
        time_lbl.setFont(FONT_SMALL)
        time_lbl.setStyleSheet(f"color:{COLORS['dim']};background:transparent")
        _make_selectable(time_lbl)
        header_row.addWidget(time_lbl)
        header_row.addStretch()
        header_row.addWidget(self._copy_btn(event.event_type, "复制事件类型", "事件类型"))
        content.addLayout(header_row)

        # 第2行：文件位置
        loc_text = f"{event.file_name}:{event.line}"
        loc_row = QHBoxLayout()
        loc_lbl = QLabel(f"文件（变量所在文件）: {loc_text}")
        loc_lbl.setFont(FONT_SMALL)
        loc_lbl.setWordWrap(True)
        loc_lbl.setStyleSheet(f"color:{COLORS['accent']};background:transparent")
        _make_selectable(loc_lbl)
        loc_row.addWidget(loc_lbl, 1)
        loc_row.addWidget(self._copy_btn(loc_text, "复制文件位置", "文件（变量所在文件）"))
        content.addLayout(loc_row)

        # 第3行：作用域
        scope_row = QHBoxLayout()
        scope_lbl = QLabel(f"作用域（变量所属范围）: {event.scope}")
        scope_lbl.setFont(FONT_SMALL)
        scope_lbl.setWordWrap(True)
        scope_lbl.setStyleSheet(f"color:{COLORS['fg']};background:transparent")
        _make_selectable(scope_lbl)
        scope_row.addWidget(scope_lbl, 1)
        scope_row.addWidget(self._copy_btn(event.scope, "复制作用域", "作用域（变量所属范围）"))
        content.addLayout(scope_row)

        # 第3.5行：运行时类型（绿色背景标签）
        type_info_text = f"运行时类型: {event.value_type}"
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
        type_row.addWidget(self._copy_btn(event.value_type, "复制类型", "运行时类型"))
        content.addLayout(type_row)

        # 第4行：运行时值（核心！黄色高亮）
        val_title = QLabel("运行时值（变量此刻的真实值）:")
        val_title.setFont(FONT_SMALL)
        val_title.setStyleSheet(f"color:{COLORS['dim']};background:transparent")
        content.addWidget(val_title)

        val_edit = QTextEdit()
        val_edit.setReadOnly(True)
        val_edit.setText(event.value_repr)
        val_edit.setFont(FONT_MONO)
        val_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        val_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        val_edit.setStyleSheet(f"""
            QTextEdit {{
                background:{COLORS['input']};
                color:{COLORS['fg']};
                border:1px solid {COLORS['warn']};
                border-radius:4px;
                padding:4px;
                font-family:Consolas;
            }}
        """)

        min_val_height = FONT_MONO.pointSize() * 3 * 1.6 + 8
        val_edit.setMinimumHeight(int(min_val_height))

        val_row = QHBoxLayout()
        val_row.addWidget(val_edit, 1)
        val_row.addWidget(self._copy_btn(event.value_repr, "复制值", "运行时值（变量此刻的真实值）"))
        content.addLayout(val_row)

        # 第5行：代码片段（超出显示横向和纵向滚动条）
        code_title = QLabel("代码片段（变量所在代码行）:")
        code_title.setFont(FONT_SMALL)
        code_title.setStyleSheet(f"color:{COLORS['dim']};background:transparent")
        content.addWidget(code_title)

        code_edit = QTextEdit()
        code_edit.setReadOnly(True)
        code_edit.setText(event.code_line)
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

        code_row = QHBoxLayout()
        code_row.addWidget(code_edit, 1)
        code_row.addWidget(self._copy_btn(event.code_line, "复制代码", "代码片段（变量所在代码行）"))
        content.addLayout(code_row)

        # 第6行：上下文（一个文本框，目标行高亮黄色底色，超出显示滚动条）
        if event.context_lines:
            ctx_title = QLabel("上下文（前后2行代码，帮助理解上下文）:")
            ctx_title.setFont(FONT_SMALL)
            ctx_title.setStyleSheet(f"color:{COLORS['dim']};background:transparent")
            content.addWidget(ctx_title)

            ctx_rows = []
            target_idx = event.target_idx
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

            ctx_row = QHBoxLayout()
            ctx_row.addWidget(ctx_edit, 1)
            ctx_text = "\n".join(event.context_lines)
            ctx_row.addWidget(self._copy_btn(ctx_text, "复制上下文", "上下文（前后2行代码，帮助理解上下文）"))
            content.addLayout(ctx_row)

        vl.addLayout(content)
        return card

    def closeEvent(self, e):
        """点击 X 时返回工具箱主界面，而不是真正关闭"""
        # 如果正在追踪，先 kill 子进程
        if self._qprocess and self._qprocess.state() != QProcess.NotRunning:
            self._qprocess.kill()
            self._qprocess.waitForFinished(3000)
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
                f"[{e.event_type}] 程序运行时长@{e.timestamp:.3f}s | "
                f"值: {e.value_repr} (类型: {e.value_type}) | "
                f"代码: {e.code_line}"
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
        self._show_ai_result(result)

    def _on_ai_error(self, error: str):
        """AI 分析失败"""
        self._btn_ai.setEnabled(True)
        self.sig.busy_changed.emit(False)
        self._on_status(f"AI 分析失败: {error}", COLORS["err"])

    def _show_ai_result(self, result: str):
        """弹出 AI 分析结果窗口"""
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
            self._on_status("请先执行动态追踪", COLORS["warn"])
            return

        # 复用静态追踪器的 HTML 导出
        from core.html_exporter import export_lifecycle_html

        # 将 DynamicResult 转换为 html_exporter 兼容的格式
        from core.lifecycle_tracer import LifecycleResult, VariableEvent, EventType

        # 映射事件类型
        type_map = {
            "诞生": EventType.BIRTH,
            "赋值": EventType.ASSIGN,
            "使用": EventType.USE,
            "销毁": EventType.DEL,
            "消亡": EventType.DEL,
        }

        events = []
        for e in self._result.events:
            events.append(VariableEvent(
                event_type=type_map.get(e.event_type, EventType.USE),
                file_path=e.file_path,
                file_name=e.file_name,
                line=e.line,
                col=0,
                code_line=e.code_line,
                scope=e.scope,
                scope_type=None,
                context_lines=e.context_lines,
                detail=f"程序运行时长@{e.timestamp:.3f}s | 运行时值: {e.value_repr} (类型: {e.value_type})",
                type_inferred=e.value_type,
                type_description="运行时类型",
            ))

        result = LifecycleResult(
            variable_name=self._result.variable_name,
            events=events,
            files_involved=self._result.files_involved,
            total_events=self._result.total_events,
            birth_count=self._result.birth_count,
            use_count=self._result.use_count,
            death_count=self._result.death_count,
        )

        default_name = f"dynamic_{self._result.variable_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        fp, _ = QFileDialog.getSaveFileName(
            self, "导出 HTML 报告", default_name, "HTML 文件 (*.html);;所有文件 (*.*)"
        )
        if fp:
            try:
                export_lifecycle_html(result, fp)
                self._html_path = fp
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
        """打开 HTML 报告"""
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
        self._status_label.setText(text)
        self._status_label.setStyleSheet(
            f"color:{color or COLORS['fg']};background:transparent"
        )
