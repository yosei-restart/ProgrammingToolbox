"""
GUI 元素探查器窗口模块
PySide6 (LGPLv3) - 无弹窗、控件作用、框架推测、可配置热键

本模块从原 main.py 中提取，作为「辅助编程工具箱」中的一个子窗口。
GUIInspectorWindow 可独立使用，也可通过 on_back 回调返回工具箱主界面。
配色与字体统一从 theme.py 导入，与其他工具窗口共享主题。
"""

import sys
import os
import json
import threading
import ctypes
import ctypes.wintypes
import shutil
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QLineEdit, QScrollArea, QFrame,
    QFileDialog, QListWidget, QListWidgetItem, QDialog, QAbstractItemView,
    QSystemTrayIcon, QSplitter, QProgressBar,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QFont, QPixmap, QIcon, QAction, QCursor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.inspector_engine import inspect_at
from utils.hotkey_handler import HotkeyHandler, HotkeyCapture, get_hotkey_display
from core.renderer_engine import generate_screenshots
from ai.ai_prompt_generator import generate_ai_prompt, generate_json_output
from utils.clipboard_utils import copy_to_clipboard
from utils.control_descriptions import get_control_description, generate_ai_explanation_prompt
from core.framework_infer import infer_framework
from utils.logging_utils import get_logger
from utils.theme import COLORS as C, FONT_TITLE as FT, FONT_HEADER as FH, FONT_BODY as FB, FONT_MONO as FM, FONT_SMALL as FS, FONT_STATUS as FST, FONT_SIZE_BODY as FSB, apply_text_selectable

logger = get_logger(__name__)

# 应用图标路径
_ICON_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon.ico")

# ── 杂散窗口清理 ──
_user32 = ctypes.windll.user32

def _enum_windows():
    """枚举所有当前顶层窗口句柄"""
    handles = set()
    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def _cb(hwnd, _):
        handles.add(hwnd)
        return True
    _user32.EnumWindows(_cb, 0)
    return handles

def _get_window_pid(hwnd):
    """获取窗口所属进程 ID"""
    pid = ctypes.wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value

def _get_window_title(hwnd):
    """获取窗口标题"""
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value

def _hide_all_windows():
    """隐藏当前进程所有可见的窗口，返回被隐藏的窗口句柄列表（用于恢复）"""
    own_pid = os.getpid()
    handles = _enum_windows()
    SW_HIDE = 0
    hidden = []
    for hwnd in handles:
        if _get_window_pid(hwnd) != own_pid:
            continue
        if not _user32.IsWindowVisible(hwnd):
            continue
        _user32.ShowWindow(hwnd, SW_HIDE)
        hidden.append(hwnd)
    return hidden


def _show_windows(handles):
    """恢复指定列表中的窗口显示"""
    SW_SHOW = 5
    for hwnd in handles:
        if _user32.IsWindow(hwnd):
            _user32.ShowWindow(hwnd, SW_SHOW)


def _force_foreground(hwnd: int):
    """强制将窗口拉到最前面

    使用 AttachThreadInput 方案——Windows 上最可靠的强制置顶方法。

    原理：
    - Windows 前台锁（Foreground Lock）限制后台进程抢占前台
    - 但如果两个线程共享输入队列（AttachThreadInput），则权限共享
    - 通过附加当前前台窗口的线程到本进程线程，借用其前台权限
    - 然后 SetForegroundWindow 即可成功

    替代方案对比：
    - Alt 键方案（keybd_event）：Windows 10/11 上不可靠，常被忽略
    - SetWindowPos 置顶方案：只改 Z 序，不激活窗口，用户需手动点击
    - AttachThreadInput 方案：最可靠，直接获取前台权限
    """
    if not (hwnd and _user32.IsWindow(hwnd)):
        return

    import ctypes

    # 获取本线程ID（GUI线程）
    current_tid = ctypes.windll.kernel32.GetCurrentThreadId()

    # 获取当前前台窗口的线程ID
    # 注意：GetWindowThreadProcessId 返回值 = 线程ID，输出参数 = 进程ID
    fg_hwnd = _user32.GetForegroundWindow()
    fg_tid = 0
    if fg_hwnd:
        pid = ctypes.wintypes.DWORD()
        # 返回值是线程ID，pid 是进程ID（这里只需要线程ID）
        fg_tid = _user32.GetWindowThreadProcessId(fg_hwnd, ctypes.byref(pid))

    # 方案1：AttachThreadInput（核心方案）
    # 附加两个线程的输入队列，共享前台权限
    attached = False
    try:
        if fg_tid and fg_tid != current_tid:
            # 附加：当前前台线程 → 本线程
            if _user32.AttachThreadInput(fg_tid, current_tid, True):
                attached = True
                logger.info("AttachThreadInput 成功：fg_tid=%d, current_tid=%d", fg_tid, current_tid)
            else:
                logger.warning("AttachThreadInput 失败")
    except Exception as e:
        logger.warning("AttachThreadInput 异常: %s", e)

    try:
        # 方案2：SetWindowPos 置顶（配合 AttachThreadInput 使用）
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040
        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        _user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                              SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        _user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                              SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)

        # 方案3：激活窗口（AttachThreadInput 后会成功）
        _user32.SetForegroundWindow(hwnd)
        _user32.BringWindowToTop(hwnd)
        _user32.ShowWindow(hwnd, 5)  # SW_SHOW
    finally:
        # 分离输入队列（必须执行，避免副作用）
        if attached:
            try:
                _user32.AttachThreadInput(fg_tid, current_tid, False)
            except Exception:
                pass


def cleanup_stray_windows(before_handles):
    """
    关闭拾取过程中新出现的、属于自身进程的杂散窗口。
    不触碰主窗口和其他应用的窗口。
    """
    own_pid = os.getpid()
    current = _enum_windows()
    new_windows = current - before_handles
    closed = 0
    for hwnd in new_windows:
        # 只关闭属于自身进程的窗口
        if _get_window_pid(hwnd) != own_pid:
            continue
        # 只关闭可见的窗口
        if not _user32.IsWindowVisible(hwnd):
            continue
        title = _get_window_title(hwnd)
        # 发送 WM_CLOSE 关闭
        _user32.PostMessageW(hwnd, 0x0010, 0, 0)
        closed += 1
    return closed

class Signals(QObject):
    status = Signal(str, str)
    inspect_requested = Signal(int, int)
    result_ready = Signal(object, object)
    screenshot_ready = Signal(str, int)
    screenshot_error = Signal(str)
    ai_analysis_done = Signal(str)
    ai_analysis_error = Signal(str)
    mode_changed = Signal(bool)
    screenshot_triggered = Signal()

def _copy_btn(cb) -> QPushButton:
    b = QPushButton("复制"); b.setFont(FS); b.setFixedSize(42, 22)
    b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(f"QPushButton{{background:{C['copy']};color:{C['fg']};border:none;border-radius:3px;padding:0 6px}} QPushButton:hover{{background:{C['accent']};color:{C['head']}}}")
    b.clicked.connect(cb); return b

def _empty(text):
    l = QLabel(text); l.setFont(FS); l.setAlignment(Qt.AlignCenter)
    l.setStyleSheet(f"color:{C['dim']};background:transparent;padding:20px"); return l

def _sec(text):
    l = QLabel(text); l.setFont(FH)
    l.setStyleSheet(f"color:{C['title']};background:transparent;padding-top:8px"); return l

class GUIInspectorWindow(QMainWindow):
    def __init__(self, on_back=None):
        super().__init__()
        self._on_back = on_back
        self.setWindowTitle("GUI Element Inspector")
        self.resize(1100, 820); self.setMinimumSize(800, 600)
        # 设置窗口图标
        self._app_icon = QIcon(_ICON_PATH) if os.path.exists(_ICON_PATH) else QIcon()
        self.setWindowIcon(self._app_icon)
        self._theme()
        self.results = []; self._sel = -1; self._pix = None
        # 禁用全局 tooltip 防止弹出浮动窗口
        self.setAttribute(Qt.WA_AlwaysShowToolTips, False)
        self.sig = Signals()
        self.sig.status.connect(self._st); self.sig.inspect_requested.connect(self._do_inspect)
        self.sig.screenshot_triggered.connect(self._do_screenshot_from_hotkey)
        self.sig.result_ready.connect(self._on_result); self.sig.screenshot_ready.connect(self._on_ss)
        self.sig.screenshot_error.connect(self._on_ss_error)
        self.sig.ai_analysis_done.connect(self._on_ai_analyze_done)
        self.sig.ai_analysis_error.connect(self._on_ai_analyze_error)
        # 使用全局单例 HotkeyHandler，避免多个实例同时监听导致热键触发两次
        # 注意：单例在 toolbox_main 中初始化，这里只是获取引用
        # 如果单例不存在（直接运行 inspector_window），则创建本地实例
        try:
            self.hotkey = HotkeyHandler.instance()
            logger.info("使用全局单例 HotkeyHandler")
        except RuntimeError:
            self.hotkey = HotkeyHandler(
                on_inspect=self._on_inspect,
                on_screenshot=self._on_screenshot_hotkey,
            )
            self.hotkey.set_mode_change_callback(self._on_mode_signal)
            self.hotkey.start()
            logger.info("未找到全局单例，创建本地 HotkeyHandler")
        self.sig.mode_changed.connect(self._on_mode)
        self._build()
        # 截图触发标志位（跨线程通信最可靠方案）
        self._screenshot_pending = False
        self._screenshot_timer = QTimer()
        self._screenshot_timer.timeout.connect(self._check_screenshot_pending)
        self._screenshot_timer.start(50)
        self._st(f"就绪 - 按 {get_hotkey_display()} 进入检查模式")
        apply_text_selectable(self)

    def _theme(self):
        self.setStyleSheet(f"""
            QMainWindow{{background:{C['bg']}}} QWidget{{background:{C['bg']};color:{C['fg']}}}
            QLabel{{background:transparent}} QPushButton{{border:none;border-radius:4px;padding:6px 14px}}
            QPushButton:hover{{background:{C['accent']};color:{C['head']}}}
            QLineEdit{{background:{C['input']};color:{C['fg']};border:none;border-radius:4px;padding:6px 10px}}
            QTextEdit{{background:{C['panel']};color:{C['fg']};border:none;border-radius:4px;padding:8px 10px}}
            QScrollArea{{border:none;background:transparent}}
            QScrollBar:vertical{{background:{C['bg']};width:8px;border-radius:4px}}
            QScrollBar::handle:vertical{{background:{C['border']};border-radius:4px;min-height:30px}}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0}}
            QListWidget{{background:{C['panel']};color:{C['fg']};border:none;border-radius:4px;padding:4px}}
            QListWidget::item{{padding:6px 8px;border-radius:2px}}
            QListWidget::item:hover{{background:{C['input']}}}
            QListWidget::item:selected{{background:{C['accent']};color:{C['head']}}}
            QSplitter::handle{{background:{C['border']};width:2px}}
        """)

    def _quit_app(self):
        """彻底退出应用"""
        self._force_quit = True
        self.close()

    def _build(self):
        """构建主界面布局"""
        cw = QWidget(); self.setCentralWidget(cw)
        mv = QVBoxLayout(cw); mv.setContentsMargins(0,0,0,0); mv.setSpacing(0)
        self._hdr(mv)
        sp = QSplitter(Qt.Horizontal); sp.setStyleSheet(f"QSplitter{{background:{C['border']}}}")
        self._lst(sp); self._detail(sp); sp.setSizes([200,880]); mv.addWidget(sp,1)
        self._stbar(mv)

    def _hdr(self, pl):
        h = QFrame(); h.setFixedHeight(50); h.setStyleSheet(f"background:{C['head']};border:none")
        hl = QHBoxLayout(h); hl.setContentsMargins(12,6,12,6)
        if self._on_back:
            back_btn = QPushButton("← 返回工具箱")
            back_btn.setFont(FB)
            back_btn.setCursor(Qt.PointingHandCursor)
            back_btn.setStyleSheet(f"QPushButton{{background:transparent;color:{C['accent']};border:none;padding:6px 12px}} QPushButton:hover{{color:{C['ahover']}}}")
            back_btn.clicked.connect(self.close)
            hl.addWidget(back_btn)
        t = QLabel("GUI Element Inspector"); t.setFont(FT); t.setStyleSheet(f"color:{C['accent']};background:transparent")
        hl.addWidget(t); hl.addStretch()
        self.pb = QPushButton(f"拾取 ({get_hotkey_display()})"); self.pb.setFont(FB); self.pb.setCursor(Qt.PointingHandCursor)
        self.pb.setStyleSheet(f"QPushButton{{background:{C['accent']};color:{C['head']};border:none;border-radius:4px;padding:6px 16px}} QPushButton:hover{{background:{C['ahover']}}} QPushButton:disabled{{background:{C['warn']};color:{C['head']}}}")
        self.pb.clicked.connect(self._pick); hl.addWidget(self.pb)
        hk = QPushButton("修改热键"); hk.setFont(FB); hk.setCursor(Qt.PointingHandCursor)
        hk.setStyleSheet(f"QPushButton{{background:{C['input']};color:{C['fg']};border-radius:4px;padding:6px 14px}} QPushButton:hover{{background:{C['accent']};color:{C['head']}}}")
        hk.clicked.connect(self._hk_dlg); hl.addWidget(hk)
        cl = QPushButton("清空"); cl.setFont(FB); cl.setCursor(Qt.PointingHandCursor)
        cl.setStyleSheet(f"QPushButton{{background:{C['input']};color:{C['err']};border-radius:4px;padding:6px 14px}} QPushButton:hover{{background:{C['err']};color:{C['head']}}}")
        cl.clicked.connect(self._clear); hl.addWidget(cl)
        pl.addWidget(h)

    def _lst(self, p):
        pn = QWidget(); pn.setStyleSheet(f"background:{C['panel']};border-radius:6px")
        vl = QVBoxLayout(pn); vl.setContentsMargins(8,8,8,8)
        l = QLabel("已拾取的控件"); l.setFont(FH); l.setStyleSheet(f"color:{C['title']};background:transparent"); vl.addWidget(l)
        self.rl = QListWidget(); self.rl.setFont(FS); self.rl.setSelectionMode(QAbstractItemView.SingleSelection)
        self.rl.currentRowChanged.connect(self._on_sel); vl.addWidget(self.rl)
        self.re = _empty("点击拾取按钮\n或按热键开始"); vl.addWidget(self.re)
        p.addWidget(pn)

    def _detail(self, p):
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ct = QWidget(); ct.setStyleSheet(f"background:{C['bg']}")
        self.dl = QVBoxLayout(ct); self.dl.setContentsMargins(16,12,16,12); self.dl.setSpacing(6)

        # ── 功能引导 ──
        guide = QFrame(); guide.setStyleSheet(f"background:{C['panel']};border:1px solid {C['accent']};border-radius:6px")
        gvl = QVBoxLayout(guide); gvl.setContentsMargins(14,10,14,10); gvl.setSpacing(4)
        g1 = QLabel("学习控件作用"); g1.setFont(FH); g1.setStyleSheet(f"color:{C['accent']};background:transparent")
        g2 = QLabel("拾取控件 → 查看「控件作用」→ 点击「向 AI 请求深入解释」→ 粘贴到 ChatGPT / 通义千问 / DeepSeek 等任意 AI 对话中获取详细解释")
        g2.setFont(FS); g2.setWordWrap(True); g2.setStyleSheet(f"color:{C['dim']};background:transparent")
        gvl.addWidget(g1); gvl.addWidget(g2); self.dl.addWidget(guide)

        # ── 控件作用 ──
        self.dl.addWidget(_sec("控件作用 — 了解此控件的功能和用途"))
        self.df = QFrame(); self.df.setStyleSheet(f"background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #2A1F3D,stop:1 #1E1E2E);border:1px solid {C['title']};border-radius:6px")
        dvl = QVBoxLayout(self.df); dvl.setContentsMargins(14,12,14,12)
        self.dlbl = QLabel(""); self.dlbl.setFont(FB); self.dlbl.setWordWrap(True)
        self.dlbl.setStyleSheet(f"color:{C['fg']};background:transparent"); dvl.addWidget(self.dlbl)
        self.de = _empty("拾取控件后将显示控件作用说明"); dvl.addWidget(self.de); self.dl.addWidget(self.df)

        # AI 解释按钮
        ai_row = QHBoxLayout()
        self.ai_btn = QPushButton("向 AI 请求深入解释（复制提示词，粘贴到任意 AI 对话）")
        self.ai_btn.setFont(FB); self.ai_btn.setCursor(Qt.PointingHandCursor)
        self.ai_btn.setStyleSheet(f"QPushButton{{background:{C['title']};color:{C['head']};border-radius:4px;padding:8px 16px;font-weight:bold}} QPushButton:hover{{background:{C['accent']};color:{C['head']}}}")
        self.ai_btn.clicked.connect(self._ai_explain); ai_row.addWidget(self.ai_btn)

        # AI 在线分析按钮（直接调用 API）
        self.ai_online_btn = QPushButton("AI 在线分析")
        self.ai_online_btn.setFont(FB); self.ai_online_btn.setCursor(Qt.PointingHandCursor)
        self.ai_online_btn.setStyleSheet(
            f"QPushButton{{background:{C['ok']};color:{C['head']};border-radius:4px;padding:8px 16px;font-weight:bold}} "
            f"QPushButton:hover{{background:#2ea043}} "
            f"QPushButton:disabled{{background:{C['panel']};color:{C['dim']}}}"
        )
        self.ai_online_btn.clicked.connect(self._ai_online_analyze)
        ai_row.addWidget(self.ai_online_btn)

        ai_row.addStretch(); self.dl.addLayout(ai_row)

        # AI 分析结果展示区
        self.ai_result_frame = QFrame()
        self.ai_result_frame.setStyleSheet(f"background:{C['panel']};border-radius:6px")
        arl = QVBoxLayout(self.ai_result_frame)
        arl.setContentsMargins(14, 12, 14, 12)
        self.ai_result_title = QLabel("AI 分析结果（点击「AI 在线分析」后显示）")
        self.ai_result_title.setFont(FS)
        self.ai_result_title.setStyleSheet(f"color:{C['dim']};background:transparent")
        arl.addWidget(self.ai_result_title)
        self.ai_result_text = QTextEdit()
        self.ai_result_text.setReadOnly(True)
        self.ai_result_text.setFont(FB)
        self.ai_result_text.setMaximumHeight(200)
        self.ai_result_text.setStyleSheet(
            f"QTextEdit{{background:{C['bg']};color:{C['fg']};border:1px solid {C['border']};border-radius:4px;padding:8px}}"
        )
        self.ai_result_text.setPlaceholderText("配置 AI API 后，拾取控件再点击「AI 在线分析」，AI 会直接返回分析结果。")
        arl.addWidget(self.ai_result_text)
        self.ai_result_frame.hide()
        self.dl.addWidget(self.ai_result_frame)

        # ── 推测框架 ──
        self.dl.addWidget(_sec("推测框架"))
        self.ff = QFrame(); self.ff.setStyleSheet(f"background:{C['panel']};border-radius:6px")
        fvl = QVBoxLayout(self.ff); fvl.setContentsMargins(12,10,12,10)
        self.flbl = QLabel(""); self.flbl.setFont(FB); self.flbl.setWordWrap(True)
        self.flbl.setStyleSheet(f"color:{C['fg']};background:transparent"); fvl.addWidget(self.flbl)
        self.fcode = QTextEdit(); self.fcode.setFont(FM); self.fcode.setReadOnly(True); self.fcode.setFixedHeight(60)
        self.fcode.setPlaceholderText("拾取控件后将推测 UI 框架，此处显示代码示例")
        self.fcode.setStyleSheet(f"QTextEdit{{background:{C['bg']};color:{C['ok']};border-radius:4px;padding:6px 8px}}")
        fvl.addWidget(self.fcode); self.dl.addWidget(self.ff)

        # ── 控件属性 ──
        self.dl.addWidget(_sec("控件属性"))
        self._bp()

        # ── 控件层级 ──
        self.dl.addWidget(_sec("控件层级"))
        self._bh()

        # ── 截图 ──
        self.dl.addWidget(_sec("截图标注"))
        self._bs()

        # ── AI 提示词 ──
        self.dl.addWidget(_sec("AI 提示词"))
        self._bpt()

        # ── 按钮 ──
        self._ba()
        self.dl.addStretch()
        sc.setWidget(ct); p.addWidget(sc)

    def _bp(self):
        self.pf = QFrame(); self.pf.setStyleSheet(f"background:{C['panel']};border-radius:6px")
        self.pl = QVBoxLayout(self.pf); self.pl.setContentsMargins(12,8,12,8); self.pl.setSpacing(1)
        self.pw = {}; self.pe = _empty("拾取控件后将显示属性"); self.pl.addWidget(self.pe)
        self.dl.addWidget(self.pf)

    def _bh(self):
        self.hf = QFrame(); self.hf.setStyleSheet(f"background:{C['panel']};border-radius:6px")
        hl = QVBoxLayout(self.hf); hl.setContentsMargins(0,0,0,0)
        self.ht = QTextEdit(); self.ht.setFont(FM); self.ht.setReadOnly(True); self.ht.setFixedHeight(100)
        self.ht.setPlaceholderText("拾取控件后将显示控件层级结构")
        self.ht.setStyleSheet(f"QTextEdit{{background:{C['panel']};color:{C['fg']};border:none;border-radius:6px;padding:8px 10px}}")
        hl.addWidget(self.ht); self.dl.addWidget(self.hf)

    def _bs(self):
        self.sf = QFrame(); self.sf.setStyleSheet(f"background:{C['panel']};border-radius:6px")
        sl = QVBoxLayout(self.sf); sl.setContentsMargins(8,8,8,8)
        self.slbl = QLabel("拾取控件后将显示标注截图"); self.slbl.setFont(FS); self.slbl.setAlignment(Qt.AlignCenter)
        self.slbl.setStyleSheet(f"color:{C['dim']};background:transparent;padding:20px"); self.slbl.setMinimumHeight(0)
        sl.addWidget(self.slbl); self.dl.addWidget(self.sf)

    def _bpt(self):
        inp = QFrame(); inp.setStyleSheet(f"background:{C['panel']};border-radius:6px")
        il = QVBoxLayout(inp); il.setContentsMargins(12,8,12,8); il.setSpacing(4)
        ql = QLabel("描述你的问题（可选）:"); ql.setFont(FS); ql.setStyleSheet(f"color:{C['dim']};background:transparent")
        il.addWidget(ql)
        self.qe = QLineEdit(); self.qe.setFont(FB); self.qe.setText("请帮我分析这个控件可能存在的问题。"); il.addWidget(self.qe)
        self.dl.addWidget(inp)
        pf = QFrame(); pf.setStyleSheet(f"background:{C['panel']};border-radius:6px")
        pl = QVBoxLayout(pf); pl.setContentsMargins(0,0,0,0)
        self.pt = QTextEdit(); self.pt.setFont(FM); self.pt.setReadOnly(True); self.pt.setFixedHeight(120)
        self.pt.setPlaceholderText("拾取控件后将自动生成 AI 提示词")
        self.pt.setStyleSheet(f"QTextEdit{{background:{C['panel']};color:{C['fg']};border:none;border-radius:6px;padding:8px 10px}}")
        pl.addWidget(self.pt); self.dl.addWidget(pf)

    def _ba(self):
        bf = QWidget(); bf.setStyleSheet("background:transparent")
        bl = QHBoxLayout(bf); bl.setContentsMargins(0,8,0,4); bl.setSpacing(8)
        for txt, cb in [("复制全部属性", self._cp_all), ("复制提示词", self._cp_prompt), ("导出 JSON", self._exp), ("保存截图", self._sv)]:
            b = QPushButton(txt); b.setFont(FB); b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"QPushButton{{background:{C['input']};color:{C['fg']};border-radius:4px;padding:6px 14px}} QPushButton:hover{{background:{C['accent']};color:{C['head']}}}")
            b.clicked.connect(cb); bl.addWidget(b)
        bl.addStretch(); self.dl.addWidget(bf)

    def _stbar(self, pl):
        """状态栏 + 不确定进度条"""
        bar = QFrame()
        vl = QVBoxLayout(bar)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(2)

        self.sl = QLabel(""); self.sl.setFont(FST); self.sl.setFixedHeight(28)
        self.sl.setStyleSheet(f"background:{C['border']};color:{C['dim']};padding:0 12px")
        vl.addWidget(self.sl)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        self._progress.setStyleSheet(
            f"QProgressBar{{background:{C['border']};border:none;border-radius:2px}} "
            f"QProgressBar::chunk{{background:{C['accent']};border-radius:2px}}"
        )
        vl.addWidget(self._progress)
        pl.addWidget(bar)

    def _st(self, t, c=None):
        self.sl.setText(t)
        self.sl.setStyleSheet(f"background:{C['border']};color:{c or C['dim']};padding:0 12px")

    def _on_mode_signal(self, m: bool):
        logger.info("[TRACE-1] _on_mode_signal called with m=%s (thread)", m)
        self.sig.mode_changed.emit(m)

    def _on_mode(self, m):
        logger.info("[TRACE-2] _on_mode called with m=%s (main thread)", m)
        if m:
            self._prev_geometry = self.saveGeometry()
            logger.info("[TRACE-3] _on_mode(m=True) 开始隐藏窗口")
            # 先隐藏所有窗口（包括主窗口和可能存在的旧气泡）
            # 必须在创建新气泡之前执行，否则新气泡会被隐藏
            self._hidden_handles = _hide_all_windows()
            logger.info("[TRACE-4] 已隐藏 %d 个窗口", len(self._hidden_handles))
            # 再创建并显示气泡（新气泡不在已隐藏的列表中，不会被隐藏）
            logger.info("[TRACE-5] _on_mode(m=True) 开始创建气泡")
            self._show_hint()
            logger.info("[TRACE-6] _on_mode(m=True) 气泡创建完成，_hint_win=%s",
                        getattr(self, '_hint_win', None))
            QApplication.processEvents()
            self._st("检查模式已激活 - 请点击目标控件", C["ok"])
            self.pb.setText("检查模式中..."); self.pb.setEnabled(False)
            logger.info("[TRACE-7] _on_mode(m=True) 完成")
        else:
            logger.info("[TRACE-8] _on_mode(m=False) 退出检查模式")
            self._hide_hint()
            self.pb.setText("开始拾取"); self.pb.setEnabled(True)
            if hasattr(self, '_hidden_handles') and self._hidden_handles:
                _show_windows(self._hidden_handles)
                self._hidden_handles = None
            self.show()
            self.raise_()
            self.activateWindow()
            # 强制置顶：Qt 的 raise_/activateWindow 在 Windows 上不足以将窗口置顶
            # 需要调用 Win32 API SetForegroundWindow + BringWindowToTop
            QTimer.singleShot(50, lambda: _force_foreground(int(self.winId())))
            logger.info("[TRACE-9] _on_mode(m=False) 完成")

    def _show_hint(self):
        logger.info("[TRACE-HINT-1] _show_hint 开始，_hint_win=%s",
                    getattr(self, '_hint_win', None))
        if getattr(self, '_hint_win', None):
            logger.info("[TRACE-HINT-2] _hint_win 已存在，直接返回")
            return
        logger.info("[TRACE-HINT-3] 创建新气泡窗口")
        self._hint_win = QWidget(None, Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self._hint_win.setAttribute(Qt.WA_TranslucentBackground)
        self._hint_win.setAttribute(Qt.WA_ShowWithoutActivating)
        self._hint_win.setStyleSheet("""
            QWidget#hintContainer{
                background:rgba(0,0,0,0.85);
                border-radius:10px;
                padding:10px 16px;
            }
            QLabel{background:transparent;color:#fff}
        """)
        container = QWidget(self._hint_win)
        container.setObjectName("hintContainer")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)
        title = QLabel("🎯 点击拾取控件")
        title.setStyleSheet("font-weight:bold;font-size:15px;color:#4fc3f7")
        desc = QLabel("ESC 取消")
        desc.setStyleSheet("color:#aaa;font-size:12px")
        layout.addWidget(title)
        layout.addWidget(desc)
        self._hint_win.setLayout(QVBoxLayout())
        self._hint_win.layout().setContentsMargins(0, 0, 0, 0)
        self._hint_win.layout().addWidget(container)
        self._hint_win.adjustSize()
        logger.info("[TRACE-HINT-4] 调用 _hint_win.show()")
        self._hint_win.show()
        logger.info("[TRACE-HINT-5] _hint_win.show() 完成，isVisible=%s",
                    self._hint_win.isVisible())
        hwnd = int(self._hint_win.winId())
        logger.info("[TRACE-HINT-6] 气泡 hwnd=%s，设置 Win32 置顶样式", hwnd)
        ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
        ex_style = ex_style | 0x00000020 | 0x00080000 | 0x00000008
        ctypes.windll.user32.SetWindowLongW(hwnd, -20, ex_style)
        ctypes.windll.user32.SetWindowPos(
            hwnd, -1, 0, 0, 0, 0,
            0x0001 | 0x0002 | 0x0004 | 0x0020 | 0x0040
        )
        logger.info("[TRACE-HINT-7] Win32 置顶设置完成")
        self._hint_timer = QTimer()
        self._hint_timer.timeout.connect(self._update_hint_pos)
        self._hint_timer.start(30)
        logger.info("[TRACE-HINT-8] 气泡定时器已启动，_show_hint 完成")

    def _update_hint_pos(self):
        if not getattr(self, '_hint_win', None):
            return
        pos = QCursor.pos()
        self._hint_win.move(pos.x() + 20, pos.y() + 20)

    def _hide_hint(self):
        if hasattr(self, '_hint_timer') and self._hint_timer:
            self._hint_timer.stop()
            self._hint_timer = None
        if getattr(self, '_hint_win', None):
            self._hint_win.close()
            self._hint_win = None

    def _pick(self):
        self._st("正在进入检查模式...", C["warn"])
        QTimer.singleShot(100, lambda: self.hotkey._enter_inspect_mode())

    def _on_inspect(self, x, y):
        logger.info("[TRACE-INSPECT-1] _on_inspect called x=%d y=%d (pynput thread)", x, y)
        # 从 pynput 线程发射信号，Qt 自动排队到主线程执行
        self.sig.status.emit("正在识别控件...", C["warn"])
        self.sig.inspect_requested.emit(x, y)
        logger.info("[TRACE-INSPECT-2] inspect_requested 信号已发射")

    def _on_screenshot_hotkey(self):
        """截图热键触发回调（从 pynput 线程调用）

        使用标志位 + 主线程定时器轮询，跨线程最可靠方案。
        不依赖 Signal/QTimer.singleShot（在非 QThread 中可能不工作）。
        """
        logger.warning("[SCREENSHOT] inspector 热键触发，设置标志位")
        self._screenshot_pending = True

    def _check_screenshot_pending(self):
        """主线程定时器回调：检查截图标志位"""
        if self._screenshot_pending:
            self._screenshot_pending = False
            logger.warning("[SCREENSHOT] inspector 主线程检测到标志位，触发截图")
            self._do_screenshot_from_hotkey()

    def _do_screenshot_from_hotkey(self):
        """在主线程中执行截图标注

        调用模块级 _hide_all_windows() 隐藏本进程所有可见窗口，
        保存被隐藏的窗口句柄，用于截图结束后恢复显示。
        """
        self._hidden_handles = _hide_all_windows()
        QTimer.singleShot(200, self._launch_screenshot_annotator)

    def _launch_screenshot_annotator(self):
        """启动截图标注窗口

        加 try/except 防御：任何异常都记录日志，避免闪退
        传入 on_closed 回调：截图窗口关闭后重新显示 inspector 窗口
            避免：截图窗口关闭后没有可见窗口 → Qt 应用退出（看起来像闪退）
        """
        try:
            from ui.screenshot_annotator import ScreenshotAnnotator
            self._screenshot_annotator = ScreenshotAnnotator(
                on_closed=self._on_screenshot_closed
            )
            self._screenshot_annotator.start()
        except Exception as e:
            logger.exception("截图标注启动失败")
            # 重新显示窗口
            self.show()
            self.raise_()
            self.activateWindow()

    def _on_screenshot_closed(self):
        """截图窗口关闭后，恢复显示之前隐藏的窗口

        作用：避免截图窗口关闭后没有可见窗口，导致 Qt 应用退出（看起来像闪退）
        """
        try:
            # 恢复之前隐藏的窗口
            hidden = getattr(self, "_hidden_handles", None)
            if hidden:
                _show_windows(hidden)
                self._hidden_handles = None
            # 确保 inspector 窗口可见
            self.show()
            self.raise_()
            self.activateWindow()
            logger.info("截图窗口关闭，已重新显示 inspector 窗口")
        except Exception as e:
            logger.exception("重新显示 inspector 窗口失败")

    def _do_inspect(self, x, y):
        """在主线程中执行 UIAutomation 调用"""
        import time
        logger.info("_do_inspect start: x=%d y=%d", x, y)
        self._progress.setVisible(True)
        # 拾取前强制隐藏所有自身窗口（包括 hint 窗口和主窗口）
        if getattr(self, '_hint_win', None) and self._hint_win.isVisible():
            self._hint_win.hide()
        # 强制隐藏主窗口（Win32 API 级别，确保 WindowFromPoint 跳过）
        main_hwnd = int(self.winId())
        if main_hwnd and _user32.IsWindow(main_hwnd):
            _user32.ShowWindow(main_hwnd, 0)  # SW_HIDE
        QApplication.processEvents()
        ctypes.windll.kernel32.Sleep(100)
        result = None
        screenshots = None
        try:
            t0 = time.time()
            result = inspect_at(x, y)
            logger.info("inspect_at 耗时 %.2fs", time.time() - t0)
            if result and "control_info" in result:
                info = result["control_info"]
                self._st("正在生成截图...", C["warn"])
                try:
                    t1 = time.time()
                    f, c = generate_screenshots(info)
                    logger.info("截图耗时 %.2fs: %s, %s", time.time() - t1, f, c)
                    screenshots = {"full": f, "closeup": c}
                except Exception as e:
                    logger.error("截图失败: %s", e)
        except Exception as e:
            logger.error("识别异常: %s", e)
            result = {"error": str(e)}
        finally:
            self._progress.setVisible(False)
            self.show(); self.raise_(); self.activateWindow()
            if hasattr(self, "_prev_geometry") and self._prev_geometry:
                self.restoreGeometry(self._prev_geometry)
            hk = get_hotkey_display()
            self._st(f"就绪 - 按 {hk} 进入检查模式")
            self.pb.setText(f"拾取 ({hk})"); self.pb.setEnabled(True)
        self.sig.result_ready.emit(result, screenshots)

    def _on_result(self, r, screenshots=None):
        """处理拾取结果，更新 UI 并启动截图生成"""
        if not r:
            logger.warning("[RESULT] inspect_at 返回 None — 控件未识别，请查看 [INSPECT] 日志定位原因")
            self._st("未能识别控件 - 请重试（可能原因：无控件/未启用无障碍/需管理员权限）", C["err"]); return
        if "error" in r:
            logger.error("识别出错: %s", r['error'])
            self._st(f"识别出错: {r['error']}", C["err"]); return

        info = r["control_info"]
        logger.info("识别成功: %s \"%s\" (%s)", info['control_type'], info['name'], info['process_name'])

        chain = r["parent_chain"]
        q = self.qe.text().strip()
        prompt = generate_ai_prompt(r, q)
        js = generate_json_output(r)

        rec = {"time": datetime.now().strftime("%H:%M:%S"), "result": r, "prompt": prompt, "json": js, "full": None, "closeup": None}
        self.results.append(rec); idx = len(self.results) - 1
        self.re.hide()
        item = QListWidgetItem(f"[{rec['time']}] {info['control_type_cn']}\n\"{info['name']}\" - {info['process_name']}")
        item.setData(Qt.ItemDataRole.UserRole, idx); self.rl.addItem(item); self.rl.setCurrentRow(idx)
        self._sel = idx; self._show(rec)

        if screenshots and "closeup" in screenshots:
            rec["full"] = screenshots.get("full")
            rec["closeup"] = screenshots["closeup"]
            self._st(f"识别完成: {info['control_type_cn']} \"{info['name']}\" ({info['process_name']})", C["ok"])
            self._show_ss(screenshots["closeup"])
        else:
            self._st("正在生成截图...", C["warn"])
            self._progress.setVisible(True)
            threading.Thread(target=self._do_ss, args=(info, idx), daemon=True).start()
            self._st(f"识别完成: {info['control_type_cn']} \"{info['name']}\" ({info['process_name']})", C["ok"])

        QTimer.singleShot(500, self._cleanup_stray)
        self.show(); self.raise_(); self.activateWindow()
        QTimer.singleShot(100, lambda: (self.show(), self.raise_(), self.activateWindow()))
        # 强制置顶：Win32 API 确保窗口在最前面
        QTimer.singleShot(200, lambda: _force_foreground(int(self.winId())))

    def _do_ss(self, info, idx):
        """在后台线程中生成截图"""
        try:
            f, c = generate_screenshots(info)
            self.results[idx]["full"] = f; self.results[idx]["closeup"] = c
            self.sig.screenshot_ready.emit(c, idx)
        except Exception as e:
            logger.error("截图生成失败: %s", e, exc_info=True)
            self.sig.screenshot_error.emit(str(e))

    def _on_ss(self, p, idx):
        """截图完成回调"""
        self._progress.setVisible(False)
        if idx == self._sel: self._show_ss(p)

    def _on_ss_error(self, msg):
        """截图失败回调"""
        self._progress.setVisible(False)
        self._st(f"截图失败: {msg}", C["err"])

    def _cleanup_stray(self):
        """清理拾取过程中产生的杂散窗口（安全网机制）"""
        before = getattr(self, "_win_before", None)
        if before is None:
            return
        own_hwnd = int(self.winId())
        own_pid = os.getpid()
        current = _enum_windows()
        new_windows = current - before
        closed = 0
        for hwnd in new_windows:
            if _get_window_pid(hwnd) != own_pid:
                continue
            if hwnd == own_hwnd:
                continue
            if not _user32.IsWindowVisible(hwnd):
                continue
            _user32.PostMessageW(hwnd, 0x0010, 0, 0)
            closed += 1
        self._win_before = None
        if closed > 0:
            self._st(f"已自动清理 {closed} 个杂散窗口", C["warn"])

    def _on_sel(self, row):
        if 0 <= row < len(self.results): self._sel = row; self._show(self.results[row])

    def _show(self, rec):
        r = rec["result"]; info = r["control_info"]; chain = r["parent_chain"]

        # ── 控件作用 ──
        self.de.hide(); self.dlbl.setText(get_control_description(info["control_type"]))

        # ── 推测框架 ──
        fw = infer_framework(info["class_name"], info["framework_id"], chain, info["process_name"])
        self.flbl.setText(f"<b>{fw['framework']}</b> — 置信度: {fw['confidence']} | 依据: {fw['reason']}<br><span style='color:{C['dim']}'>{fw['description']}</span>")
        self.fcode.setPlainText(fw["code_example"]); self.fcode.setFixedHeight(80)

        # ── 属性 ──
        self._bpr(info)

        # ── 层级 ──
        self._bhr(chain, info)

        # ── 截图 ──
        if rec["closeup"] and os.path.exists(rec["closeup"]):
            self._show_ss(rec["closeup"])
        else:
            self.slbl.setText("(截图生成中...)"); self.slbl.setPixmap(QPixmap())

        # ── 提示词 ──
        self.pt.setPlainText(rec["prompt"]); self.pt.setFixedHeight(160)

    def _bpr(self, info):
        # 清理旧属性行：移除布局项并删除子控件，保留 placeholder(self.pe)
        while self.pl.count() > 1:
            item = self.pl.takeAt(1)  # 跳过 index 0 的 self.pe
            if item is None:
                break
            sub = item.layout()
            if sub:
                while sub.count():
                    sub_item = sub.takeAt(0)
                    if sub_item.widget():
                        sub_item.widget().deleteLater()
                sub.deleteLater()
        self.pw.clear(); self.pe.hide()
        pos = info["position"]
        rows = [
            ("控件类型", f"{info['control_type']} ({info['control_type_cn']})", get_control_description(info["control_type"])[:50] + "…"),
            ("类名", info["class_name"], info["class_name"] + " 是此控件在代码中的类名"),
            ("名称", info["name"], "此控件的显示名称或标题文本"),
            ("自动化ID", info["automation_id"], "用于自动化测试定位的标识符"),
            ("位置", f"({pos['left']}, {pos['top']})", "控件左上角在屏幕上的坐标"),
            ("尺寸", f"{pos['width']} x {pos['height']} px", "控件的显示宽度和高度"),
            ("UI框架", info["framework_id"], "UIAutomation 报告的底层框架类型"),
            ("所属进程", f"{info['process_name']} (PID: {info['process_id']})", "拥有此控件的程序进程"),
            ("窗口句柄", f"0x{info['native_window_handle']:X}" if info["native_window_handle"] else "—", "Windows 原生窗口句柄 (HWND)"),
            ("当前值", info.get("value") or "—", "控件当前包含的文本值或数据"),
        ]
        st = "已启用" if info["is_enabled"] else "已禁用"
        st += " | 可见" if info["is_visible"] else " | 不可见"
        if info["is_keyboard_focusable"]: st += " | 可聚焦"
        rows.append(("状态", st, "控件的可用状态、可见性和键盘交互能力"))

        for lbl, val, desc in rows:
            row = QHBoxLayout(); row.setContentsMargins(0,2,0,2)
            lb = QLabel(lbl + ":"); lb.setFont(FB); lb.setFixedWidth(90)
            lb.setStyleSheet(f"color:{C['dim']};background:transparent"); row.addWidget(lb)
            vl = QLabel(val); vl.setFont(FB); vl.setWordWrap(True)
            vl.setStyleSheet(f"color:{C['fg']};background:transparent")
            vl.setTextInteractionFlags(Qt.TextSelectableByMouse); row.addWidget(vl, 1)
            cb = _copy_btn(lambda checked=False, lt=lbl, vt=val: self._cpr(lt, vt))
            row.addWidget(cb); self.pw[lbl] = (lb, vl, cb); self.pl.addLayout(row)

    def _bhr(self, chain, info):
        self.ht.clear()
        self.ht.setFixedHeight(200)
        if not chain: self.ht.setPlaceholderText("(无层级信息)"); return
        html = f"<pre style='font-family:Consolas;font-size:{FSB}px;color:#CDD6F4;background:#151520;margin:0'>"
        for node in reversed(chain):
            depth = len(chain) - node["depth"] - 1
            indent = "  " * depth
            desc = get_control_description(node["control_type"]).split("：")[0] if "：" in get_control_description(node["control_type"]) else ""
            line = f"{indent}{node['control_type']} \"{node['name']}\" (类名: {node['class_name']})"
            if node["depth"] == 0:
                html += f"<span style='color:#FAB387;font-weight:bold'>{line}  ← 当前控件</span><br>"
            else:
                html += f"{line} <span style='color:{C['dim']}'>— {desc}</span><br>"
        html += "</pre>"; self.ht.setHtml(html)

    def _show_ss(self, p):
        try:
            pm = QPixmap(p)
            if pm.width() > 800: pm = pm.scaledToWidth(800, Qt.SmoothTransformation)
            self._pix = pm; self.slbl.setPixmap(pm); self.slbl.setText(""); self.slbl.setMinimumHeight(100)
        except Exception as e:
            self.slbl.setText(f"截图加载失败: {e}"); self.slbl.setPixmap(QPixmap())

    def _cpr(self, l, v):
        if copy_to_clipboard(f"{l}: {v}"): self._st(f"已复制: {l}", C["ok"])
        else: self._st("复制失败", C["err"])

    def _cp_all(self):
        if self._sel < 0: self._st("请先拾取一个控件", C["warn"]); return
        info = self.results[self._sel]["result"]["control_info"]
        pos = info["position"]
        lines = [
            f"控件类型: {info['control_type']} ({info['control_type_cn']})",
            f"类名: {info['class_name']}", f"名称: {info['name']}",
            f"自动化ID: {info['automation_id']}", f"位置: ({pos['left']}, {pos['top']})",
            f"尺寸: {pos['width']} x {pos['height']} px", f"UI框架: {info['framework_id']}",
            f"所属进程: {info['process_name']} (PID: {info['process_id']})",
            f"窗口句柄: 0x{info['native_window_handle']:X}" if info["native_window_handle"] else "窗口句柄: —",
            f"当前值: {info.get('value') or '—'}",
        ]
        st = "已启用" if info["is_enabled"] else "已禁用"
        st += " | 可见" if info["is_visible"] else " | 不可见"
        if info["is_keyboard_focusable"]: st += " | 可聚焦"
        lines.append(f"状态: {st}")
        if copy_to_clipboard("\n".join(lines)): self._st("全部属性已复制到剪贴板", C["ok"])
        else: self._st("复制失败", C["err"])

    def _cp_prompt(self):
        if self._sel < 0: self._st("请先拾取一个控件", C["warn"]); return
        if copy_to_clipboard(self.results[self._sel]["prompt"]): self._st("AI 提示词已复制到剪贴板", C["ok"])
        else: self._st("复制失败", C["err"])

    def _ai_explain(self):
        if self._sel < 0: self._st("请先拾取一个控件", C["warn"]); return
        info = self.results[self._sel]["result"]["control_info"]
        prompt = generate_ai_explanation_prompt(info["control_type"], info["class_name"])
        if copy_to_clipboard(prompt): self._st("已复制「向AI请求深入解释」提示词，请粘贴到任意 AI 对话中", C["ok"])
        else: self._st("复制失败", C["err"])

    def _ai_online_analyze(self):
        """调用 AI API 在线分析当前控件"""
        if self._sel < 0:
            self._st("请先拾取一个控件", C["warn"])
            return

        # 检查 AI 配置
        from ai.ai_config import load_config
        config = load_config()
        if not config.enable_ai:
            self._st("AI 功能未启用，请先在「AI 设置」中配置并启用", C["warn"])
            return
        if not config.is_valid():
            self._st("AI 配置无效，请先在「AI 设置」中填写 API Key", C["warn"])
            return

        # 获取当前控件信息
        info = self.results[self._sel]["result"]["control_info"]
        self._st("正在请求 AI 分析...", C["warn"])
        self.ai_online_btn.setEnabled(False)
        self.ai_result_frame.show()
        self.ai_result_title.setText("AI 分析中，请稍候...")
        self.ai_result_title.setStyleSheet(
            "background:#fff3cd;color:#dc3545;padding:4px 8px;"
            "border:1px solid #ffc107;border-radius:4px;font-weight:bold"
        )
        self.ai_result_text.setPlainText("")

        # 子线程调用 AI
        threading.Thread(
            target=self._do_ai_analyze,
            args=(info, config),
            daemon=True,
        ).start()

    def _do_ai_analyze(self, control_info: dict, config):
        """子线程：调用 AI 分析控件"""
        from ai.ai_client import analyze_control
        try:
            result = analyze_control(control_info, config)
            self.sig.ai_analysis_done.emit(result)
        except Exception as e:
            self.sig.ai_analysis_error.emit(str(e))

    def _on_ai_analyze_done(self, result: str):
        """AI 分析完成"""
        self.ai_online_btn.setEnabled(True)
        self.ai_result_title.setText("AI 分析结果:")
        self.ai_result_title.setStyleSheet(f"color:{C['ok']};background:transparent;font-weight:bold")
        
        if result and result.strip():
            self.ai_result_text.setPlainText(result.strip())
        else:
            self.ai_result_text.setPlainText("AI 返回结果为空，请检查 API 配置或网络连接。")
        
        self._st("AI 分析完成", C["ok"])

    def _on_ai_analyze_error(self, error: str):
        """AI 分析失败"""
        self.ai_online_btn.setEnabled(True)
        self.ai_result_title.setText("AI 分析失败:")
        self.ai_result_title.setStyleSheet(f"color:{C['err']};background:transparent;font-weight:bold")
        self.ai_result_text.setPlainText(error)
        self._st(f"AI 分析失败: {error}", C["err"])

    def _exp(self):
        """导出当前控件的 JSON 数据到文件"""
        if self._sel < 0: self._st("请先拾取一个控件", C["warn"]); return
        fp, _ = QFileDialog.getSaveFileName(self, "导出 JSON", "element_info.json", "JSON 文件 (*.json);;所有文件 (*.*)")
        if fp:
            try:
                with open(fp, "w", encoding="utf-8") as f: f.write(self.results[self._sel]["json"])
                logger.info("JSON 已导出: %s", fp)
                self._st("JSON 已导出", C["ok"])
            except Exception as e:
                logger.error("导出 JSON 失败: %s", e, exc_info=True)
                self._st(f"导出失败: {e}", C["err"])

    def _sv(self):
        """保存当前控件的特写截图到指定路径"""
        if self._sel < 0: self._st("请先拾取一个控件", C["warn"]); return
        p = self.results[self._sel].get("closeup")
        if not p or not os.path.exists(p): self._st("截图尚未生成", C["warn"]); return
        fp, _ = QFileDialog.getSaveFileName(self, "保存截图", "element_screenshot.png", "PNG 图片 (*.png);;所有文件 (*.*)")
        if fp:
            try:
                shutil.copy2(p, fp)
                logger.info("截图已保存: %s", fp)
                self._st("截图已保存", C["ok"])
            except Exception as e:
                logger.error("保存截图失败: %s", e, exc_info=True)
                self._st(f"保存失败: {e}", C["err"])

    def _clear(self):
        self.results.clear(); self.rl.clear(); self.re.show(); self._sel = -1
        self.dlbl.setText(""); self.de.show()
        self.flbl.setText(""); self.fcode.clear(); self.fcode.setFixedHeight(60); self.fcode.setPlaceholderText("拾取控件后将推测 UI 框架，此处显示代码示例")
        # 清理属性行（与 _bpr 相同的安全清理方式）
        while self.pl.count() > 1:
            item = self.pl.takeAt(1)
            if item is None: break
            sub = item.layout()
            if sub:
                while sub.count():
                    sub_item = sub.takeAt(0)
                    if sub_item.widget(): sub_item.widget().deleteLater()
                sub.deleteLater()
        self.pw.clear(); self.pe.show()
        self.ht.clear(); self.ht.setFixedHeight(100); self.ht.setPlaceholderText("拾取控件后将显示控件层级结构")
        self.slbl.setText("拾取控件后将显示标注截图"); self.slbl.setPixmap(QPixmap())
        self.pt.clear(); self.pt.setFixedHeight(120); self.pt.setPlaceholderText("拾取控件后将自动生成 AI 提示词")
        self._st("已清空所有结果")

    def _hk_dlg(self):
        dlg = QDialog(self); dlg.setWindowTitle("修改热键"); dlg.setFixedSize(500, 240)
        dlg.setStyleSheet(f"background:{C['bg']}")
        l = QVBoxLayout(dlg); l.setContentsMargins(20,16,20,16); l.setSpacing(12)
        t = QLabel(f"当前热键: {get_hotkey_display()}"); t.setFont(FH); t.setStyleSheet(f"color:{C['title']};background:transparent"); l.addWidget(t)
        h = QLabel("请按下新的热键组合（如 Ctrl+Shift+F）"); h.setFont(FB); h.setStyleSheet(f"color:{C['dim']};background:transparent"); l.addWidget(h)
        self.hkl = QLabel("等待按键..."); self.hkl.setFont(FT); self.hkl.setAlignment(Qt.AlignCenter)
        self.hkl.setMinimumHeight(50)
        self.hkl.setStyleSheet(f"background:{C['panel']};color:{C['accent']};border-radius:6px;padding:16px"); l.addWidget(self.hkl)
        br = QHBoxLayout()
        cb = QPushButton("确定"); cb.setFont(FB); cb.setCursor(Qt.PointingHandCursor)
        cb.setEnabled(False)
        cb.setStyleSheet(
            f"QPushButton{{background:{C['input']};color:{C['fg']};border-radius:4px;padding:6px 14px}} "
            f"QPushButton:hover{{background:{C['accent']};color:{C['head']}}} "
            f"QPushButton:disabled{{background:{C['panel']};color:{C['dim']}}}"
        )
        self._pending_hotkey = None
        def _confirm():
            if self._pending_hotkey:
                m, k = self._pending_hotkey
                d = "+".join(m + [k.upper()]) if m else k.upper()
                self.hotkey.set_hotkey(m, k)
                self.pb.setText(f"拾取 ({d})")
                self.pb.adjustSize()
                self._st(f"热键已修改为 {d}", C["ok"])
            dlg.accept()
        cb.clicked.connect(_confirm)
        br.addStretch(); br.addWidget(cb); l.addLayout(br)
        self._hc = HotkeyCapture(on_captured=lambda m, k: self._on_hk_captured(m, k, cb))
        self._hc.start(); dlg.finished.connect(lambda: self._hc.stop()); dlg.exec()

    def _on_hk_captured(self, m, k, btn):
        d = "+".join(m + [k.upper()]) if m else k.upper()
        self.hkl.setText(d)
        self._pending_hotkey = (m, k)
        btn.setEnabled(True)

    def closeEvent(self, e):
        """点击 X 时返回工具箱主界面，而不是真正关闭"""
        if self._on_back:
            e.ignore()
            self.hide()
            self._on_back()
        else:
            # 独立运行模式
            if hasattr(self, 'hotkey') and self.hotkey:
                self.hotkey.stop()
            e.accept()
