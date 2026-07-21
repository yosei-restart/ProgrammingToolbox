"""
函数调用链分析器 - UI 窗口

PySide6 (LGPLv3) - GitHub Dark 主题
"""

from __future__ import annotations

import os
import threading

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QScrollArea, QFrame, QFileDialog, QProgressBar,
    QComboBox, QApplication, QTextEdit, QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QFont

from utils.theme import COLORS, FONT_TITLE, FONT_HEADER, FONT_BODY, FONT_MONO, FONT_SMALL, FONT_SIZE_SUBHEADER, FONT_SIZE_MONO, FONT_SIZE_SMALL, FONT_SIZE_CAPTION, get_global_stylesheet, apply_text_selectable
from core.call_chain_analyzer import CallChainAnalyzer, FunctionInfo, ChainNode
from utils.logging_utils import get_logger

logger = get_logger(__name__)
C = COLORS


class CallChainSignals(QObject):
    status = Signal(str, str)
    scan_done = Signal(list, dict)
    chain_done = Signal(object)


class CallChainWindow(QWidget):
    """函数调用链分析器窗口"""

    def __init__(self, on_back=None):
        super().__init__()
        self.setWindowTitle("函数调用链分析器")
        self.resize(1300, 750)
        self.setMinimumSize(900, 500)
        self._on_back = on_back
        self._analyzer = CallChainAnalyzer()
        self._current_func_name = None
        self._current_callers = None
        self._current_chain = None
        self._current_callees = None

        self.setStyleSheet(get_global_stylesheet())
        self.sig = CallChainSignals()
        self.sig.status.connect(self._on_status)
        self.sig.scan_done.connect(self._on_scan_done)
        self.sig.chain_done.connect(self._on_chain_done)

        self._build_ui()
        apply_text_selectable(self)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏
        layout.addWidget(self._build_header())

        # 输入区
        layout.addWidget(self._build_input())

        # 内容区
        layout.addWidget(self._build_content(), 1)

        # 底栏
        layout.addWidget(self._build_bottom())

    def _build_header(self):
        h = QFrame()
        h.setFixedHeight(50)
        h.setStyleSheet(f"background:{C['head']};border:none")
        hl = QHBoxLayout(h); hl.setContentsMargins(16, 8, 16, 8)
        if self._on_back:
            btn = QPushButton("← 返回工具箱")
            btn.setFont(FONT_SMALL)
            btn.setStyleSheet(f"QPushButton{{background:transparent;color:{C['accent']};border:none}}")
            btn.clicked.connect(self.close)
            hl.addWidget(btn)
        t = QLabel("函数调用链分析器")
        t.setFont(FONT_TITLE); t.setStyleSheet(f"color:{C['accent']};background:transparent")
        hl.addWidget(t); hl.addStretch()
        return h

    def _build_input(self):
        p = QFrame()
        p.setStyleSheet(f"background:{C['panel']};border-bottom:1px solid {C['border']}")
        vl = QVBoxLayout(p); vl.setContentsMargins(16, 10, 16, 10); vl.setSpacing(8)

        # 文件夹选择
        row1 = QHBoxLayout()
        lbl = QLabel("目标文件夹:")
        lbl.setFont(FONT_BODY); lbl.setStyleSheet(f"color:{C['fg']};background:transparent")
        row1.addWidget(lbl)
        self._folder_edit = QLineEdit()
        self._folder_edit.setFont(FONT_BODY)
        self._folder_edit.setPlaceholderText("选择包含 .py 文件的文件夹...")
        self._folder_edit.setStyleSheet(
            f"QLineEdit{{background:{C['input']};color:{C['fg']};border:1px solid {C['border']};border-radius:6px;padding:6px 10px}}"
        )
        row1.addWidget(self._folder_edit, 1)
        btn = QPushButton("选择文件夹")
        btn.setFont(FONT_SMALL)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton{{background:{C['accent']};color:{C['head']};border:none;border-radius:6px;padding:6px 14px}} "
            f"QPushButton:hover{{background:{C['ahover']}}}"
        )
        btn.clicked.connect(self._select_folder)
        row1.addWidget(btn)
        vl.addLayout(row1)

        # 文件过滤
        row_file = QHBoxLayout()
        lbl_file = QLabel("文件过滤:")
        lbl_file.setFont(FONT_BODY); lbl_file.setStyleSheet(f"color:{C['fg']};background:transparent")
        row_file.addWidget(lbl_file)
        self._file_combo = QComboBox()
        self._file_combo.setFont(FONT_BODY); self._file_combo.setMinimumWidth(200)
        self._file_combo.setStyleSheet(
            f"QComboBox{{background:{C['input']};color:{C['fg']};border:1px solid {C['border']};border-radius:6px;padding:6px 10px}}"
        )
        self._file_combo.currentIndexChanged.connect(self._on_file_filter_changed)
        row_file.addWidget(self._file_combo, 1)
        vl.addLayout(row_file)

        # 函数选择 + 分析按钮
        row2 = QHBoxLayout()
        lbl2 = QLabel("选择函数:")
        lbl2.setFont(FONT_BODY); lbl2.setStyleSheet(f"color:{C['fg']};background:transparent")
        row2.addWidget(lbl2)
        self._func_combo = QComboBox()
        self._func_combo.setFont(FONT_BODY); self._func_combo.setMinimumWidth(200)
        self._func_combo.setStyleSheet(
            f"QComboBox{{background:{C['input']};color:{C['fg']};border:1px solid {C['border']};border-radius:6px;padding:6px 10px}}"
        )
        self._func_combo.currentIndexChanged.connect(self._on_func_selected)
        row2.addWidget(self._func_combo, 1)

        self._btn_analyze = QPushButton("分析调用链")
        self._btn_analyze.setFont(FONT_BODY)
        self._btn_analyze.setCursor(Qt.PointingHandCursor)
        self._btn_analyze.setStyleSheet(
            f"QPushButton{{background:{C['ok']};color:{C['head']};border:none;border-radius:6px;padding:6px 16px;font-weight:bold}} "
            f"QPushButton:hover{{background:#2ea043}} QPushButton:disabled{{background:{C['border']};color:{C['dim']}}}"
        )
        self._btn_analyze.clicked.connect(self._analyze_chain)
        self._btn_analyze.setEnabled(False)
        row2.addWidget(self._btn_analyze)
        vl.addLayout(row2)

        return p

    def _build_content(self):
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setStyleSheet(f"QScrollArea{{background:{C['bg']};border:none}}")

        ct = QWidget()
        ct.setStyleSheet(f"background:{C['bg']}")
        self._content_layout = QVBoxLayout(ct)
        self._content_layout.setContentsMargins(16, 12, 16, 12)
        self._content_layout.setSpacing(10)

        # 统计面板
        self._stats_frame = QFrame()
        self._stats_frame.setStyleSheet(f"background:{C['panel']};border-radius:8px;border:1px solid {C['border']}")
        self._stats_layout = QHBoxLayout(self._stats_frame)
        self._stats_layout.setContentsMargins(16, 10, 16, 10)
        self._stats_layout.setSpacing(20)
        self._stat_labels = {}
        stat_items = [
            ("函数总数", "total", C["accent"]),
            ("文件数", "files", C["ok"]),
            ("最大调用深度", "max_depth", C["warn"]),
            ("调用最多", "most_calls", C["hl"]),
            ("被调用最多", "most_called", C["title"]),
        ]
        for label, key, color in stat_items:
            col = QVBoxLayout()
            vl = QLabel("0")
            vl.setFont(FONT_HEADER); vl.setAlignment(Qt.AlignCenter)
            vl.setStyleSheet(f"color:{color};background:transparent;font-weight:bold")
            col.addWidget(vl)
            ll = QLabel(label)
            ll.setFont(FONT_SMALL); ll.setAlignment(Qt.AlignCenter)
            ll.setStyleSheet(f"color:{C['dim']};background:transparent")
            col.addWidget(ll)
            self._stats_layout.addLayout(col)
            self._stat_labels[key] = vl
        self._content_layout.addWidget(self._stats_frame)

        # 调用链展示区
        self._chain_title = QLabel("选择文件夹后, 点击「分析调用链」查看函数调用关系")
        self._chain_title.setFont(FONT_SMALL)
        self._chain_title.setStyleSheet(f"color:{C['dim']};background:transparent;padding:6px 0")
        self._content_layout.addWidget(self._chain_title)

        self._chain_area = QTextEdit()
        self._chain_area.setFont(FONT_MONO)
        self._chain_area.setReadOnly(True)
        self._chain_area.setStyleSheet(
            f"QTextEdit{{background:{C['panel']};color:{C['fg']};border:1px solid {C['border']};border-radius:8px;padding:10px}}"
        )
        self._content_layout.addWidget(self._chain_area, 1)

        self._content_layout.addStretch()
        sc.setWidget(ct)
        return sc

    def _build_bottom(self):
        f = QFrame()
        f.setFixedHeight(34)
        f.setStyleSheet(f"background:{C['head']};border-top:1px solid {C['border']}")
        sl = QVBoxLayout(f); sl.setContentsMargins(16, 2, 16, 2); sl.setSpacing(2)
        self._status_label = QLabel("就绪")
        self._status_label.setFont(FONT_SMALL)
        self._status_label.setStyleSheet(f"color:{C['dim']};background:transparent")
        sl.addWidget(self._status_label)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0); self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False); self._progress.setVisible(False)
        self._progress.setStyleSheet(
            f"QProgressBar{{background:{C['border']};border:none;border-radius:2px}} "
            f"QProgressBar::chunk{{background:{C['accent']};border-radius:2px}}"
        )
        sl.addWidget(self._progress)
        return f

    def _select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择包含 Python 源码的文件夹")
        if folder:
            self._folder_edit.setText(folder)
            self._scan_folder(folder)

    def _scan_folder(self, folder: str):
        self._on_status("正在扫描函数定义...", C["warn"])
        self._progress.setVisible(True)
        self._btn_analyze.setEnabled(False)
        threading.Thread(target=self._do_scan, args=(folder,), daemon=True).start()

    def _do_scan(self, folder: str):
        try:
            import time
            t0 = time.time()
            funcs = self._analyzer.analyze(folder)
            t1 = time.time()
            print(f"[CallChain] analyze 耗时 {t1-t0:.2f}s", flush=True)
            stats = self._analyzer.get_stats()
            t2 = time.time()
            print(f"[CallChain] get_stats 耗时 {t2-t1:.2f}s", flush=True)
            print(f"[CallChain] 总耗时 {t2-t0:.2f}s, 函数数 {len(funcs)}", flush=True)
            self.sig.scan_done.emit(funcs, stats)
        except Exception as e:
            import traceback
            print(f"[CallChain] 扫描异常: {e}\n{traceback.format_exc()}", flush=True)
            self.sig.status.emit(f"扫描失败: {e}", C["err"])

    def _on_scan_done(self, funcs: list, stats: dict):
        self._progress.setVisible(False)
        self._all_funcs = funcs
        try:
            files = sorted(set(f.file_path for f in funcs))
            self._file_combo.blockSignals(True)
            self._file_combo.clear()
            self._file_combo.addItem("全部文件", "")
            for fp in files:
                self._file_combo.addItem(os.path.basename(fp), fp)
            self._file_combo.blockSignals(False)
            self._refresh_func_combo()
        except Exception as e:
            logger.error("填充文件列表失败: %s", e, exc_info=True)

        if funcs:
            self._on_status(
                f"扫描完成: {stats['total']} 个函数, {stats['files']} 个文件, "
                f"最多调用: {stats['most_calls']}, 被调用最多: {stats['most_called']}",
                C["ok"]
            )
            self._btn_analyze.setEnabled(True)
            self._chain_title.setText("选择一个函数，点击「分析调用链」查看调用关系")
            try:
                self._update_stats(stats)
            except Exception as e:
                logger.error("更新统计失败: %s", e, exc_info=True)
        else:
            self._on_status("未找到任何函数定义", C["warn"])

    def _on_file_filter_changed(self, idx: int):
        self._refresh_func_combo()

    def _refresh_func_combo(self):
        filter_path = self._file_combo.currentData() if self._file_combo.count() else ""
        self._func_combo.blockSignals(True)
        self._func_combo.clear()
        for f in getattr(self, '_all_funcs', []):
            if filter_path and f.file_path != filter_path:
                continue
            prefix = f"{f.class_name}." if f.is_method else ""
            label = f"{prefix}{f.name} (行 {f.line})"
            full_name = f"{prefix}{f.name}"
            self._func_combo.addItem(label, full_name)
        self._func_combo.blockSignals(False)

    def _update_stats(self, stats: dict):
        for key, label in self._stat_labels.items():
            val = str(stats.get(key, 0))
            if len(val) > 30:
                label.setToolTip(val)
                val = val[:28] + "…"
            else:
                label.setToolTip("")
            label.setText(val)

    def _on_func_selected(self, idx: int):
        pass

    def _analyze_chain(self):
        func_name = self._func_combo.currentData()
        if not func_name:
            return
        self._on_status("正在分析调用链...", C["warn"])
        self._progress.setVisible(True)
        self._btn_analyze.setEnabled(False)
        threading.Thread(target=self._do_chain, args=(func_name,), daemon=True).start()

    def _do_chain(self, func_name: str):
        try:
            chain = self._analyzer.get_call_chain(func_name, max_depth=10)
            callers = self._analyzer.get_callers(func_name)
            callees = self._analyzer.get_callees(func_name)
            self.sig.chain_done.emit((chain, callers, callees, func_name))
        except Exception as e:
            self.sig.status.emit(f"分析失败: {e}", C["err"])

    def _on_chain_done(self, data):
        self._progress.setVisible(False)
        self._btn_analyze.setEnabled(True)
        chain, callers, callees, func_name = data

        # 保存当前分析结果，用于窗口 resize 时重新渲染
        self._current_func_name = func_name
        self._current_callers = callers
        self._current_chain = chain
        self._current_callees = callees

        # 根据窗口宽度计算字体缩放比例
        scale_factor = self._calculate_font_scale()
        base_font_size = int(FONT_SIZE_SUBHEADER * scale_factor)
        header_font_size = int(FONT_SIZE_SUBHEADER * scale_factor)
        small_font_size = int(FONT_SIZE_SMALL * scale_factor)
        caption_font_size = int(FONT_SIZE_CAPTION * scale_factor)
        mono_font_size = int(FONT_SIZE_MONO * scale_factor)

        # 构建 HTML 展示 - 小白友好版
        html = f'<div style="font-family:Noto Sans SC,Consolas;font-size:{base_font_size}px;color:{C["fg"]};line-height:1.9">'

        # ── 分析函数对象 ──
        html += f'<div style="background:#fff3cd;color:#dc3545;border:1px solid #ffc107;border-radius:8px;padding:10px 14px;margin-bottom:14px;font-weight:bold">'
        html += f'📌 分析函数对象：{func_name}'
        html += f'</div>'

        # ── 1. 谁在调用它（上游调用方）──
        html += f'<div style="margin-bottom:14px">'
        html += f'<div style="color:{C["hl"]};font-weight:bold;font-size:{header_font_size}px;margin-bottom:6px">⬆ 谁调用了这个函数？（上游调用方）</div>'
        html += f'<div style="color:{C["dim"]};font-size:{small_font_size}px;margin-bottom:4px">这些函数在执行过程中会调用 {func_name}</div>'
        if callers:
            html += '<div style="margin-left:12px">'
            for i, c in enumerate(callers):
                html += (
                    f'<div style="background:{C["panel"]};border-left:3px solid {C["accent"]};'
                    f'border-radius:4px;padding:6px 10px;margin-bottom:4px">'
                    f'<span style="color:{C["accent"]};font-weight:bold">{c.name}</span>'
                    f'<span style="color:{C["dim"]};font-size:{caption_font_size}px;margin-left:8px">'
                    f'定义于 {os.path.basename(c.file_path)} 第{c.line}行</span>'
                    f'</div>'
                )
            html += '</div>'
        else:
            html += f'<div style="color:#dc3545;margin-left:12px;font-weight:bold">⚠ 没有其他函数调用 {func_name}（可能是入口函数或未被使用）</div>'
        html += "</div>"

        # ── 2. 它调用了谁（下游调用链）──
        html += f'<div style="margin-bottom:14px">'
        html += f'<div style="color:{C["ok"]};font-weight:bold;font-size:{header_font_size}px;margin-bottom:6px">⬇ 它调用了哪些函数？（下游调用链）</div>'
        html += f'<div style="color:{C["dim"]};font-size:{small_font_size}px;margin-bottom:4px">按调用顺序展示，缩进表示深度（A调用B，B调用C...）</div>'
        if chain and chain.children:
            html += '<div style="margin-left:12px;background:{C["input"]};border-radius:6px;padding:10px;font-family:Consolas">'
            html += self._render_chain_html(chain, is_root=True, scale_factor=scale_factor)
            html += '</div>'
        elif callees:
            html += f'<div style="margin-left:12px;color:{C["dim"]}">⚠ 直接调用了 {len(callees)} 个函数，但无法构建完整调用链（可能是外部库函数）</div>'
        else:
            html += f'<div style="margin-left:12px;color:#dc3545;font-weight:bold">⚠ 该函数没有调用其他函数（叶子节点）</div>'
        html += "</div>"

        # ── 3. 直接调用的函数列表 ──
        if callees:
            html += f'<div style="margin-bottom:14px">'
            html += f'<div style="color:{C["title"]};font-weight:bold;font-size:{header_font_size}px;margin-bottom:6px">📋 直接调用的函数（共 {len(callees)} 个）</div>'
            html += '<div style="margin-left:12px;display:flex;flex-wrap:wrap;gap:6px">'
            for c in callees:
                html += (
                    f'<span style="background:{C["copy"]};color:{C["ok"]};border-radius:4px;padding:3px 10px;font-size:{small_font_size}px">'
                    f'{c.name}</span>'
                )
            html += '</div></div>'

        # ── 4. 总结 ──
        total_downstream = 0
        if chain:
            total_downstream = self._count_nodes(chain) - 1
        html += f'<div style="background:{C["panel"]};border-radius:8px;padding:10px 14px;margin-top:8px">'
        html += f'<div style="color:{C["dim"]};font-size:{mono_font_size}px">'
        html += f'📊 分析总结：<b>{func_name}</b> 被 <b style="color:{C["accent"]}">{len(callers)}</b> 个函数调用，'
        html += f'它调用了 <b style="color:{C["ok"]}">{len(callees)}</b> 个函数'
        if total_downstream > 0:
            html += f'，下游调用链共涉及 <b style="color:{C["hl"]}">{total_downstream}</b> 个函数节点'
        html += f'</div></div>'

        html += "</div>"
        self._chain_area.setHtml(html)
        self._chain_title.hide()
        self._on_status(f"调用链分析完成: {func_name}", C["ok"])

    def _render_chain_html(self, node: ChainNode, prefix: str = "", is_root: bool = False, scale_factor: float = 1.0) -> str:
        """递归渲染调用链 HTML"""
        color = [C["birth"], C["flow"], C["warn"], C["hl"], C["err"]][min(node.depth, 4)]
        caption_font_size = int(FONT_SIZE_CAPTION * scale_factor)

        if is_root:
            # 根节点：当前分析的函数本身
            line = (
                f'<div style="color:{C["ok"]};font-weight:bold;margin-bottom:4px">'
                f'● {node.func.name} '
                f'<span style="color:{C["dim"]};font-size:{caption_font_size}px;font-weight:normal">'
                f'({os.path.basename(node.func.file_path)}:{node.func.line})</span>'
                f'</div>'
            )
            for i, child in enumerate(node.children):
                is_last = (i == len(node.children) - 1)
                connector = "└─ " if is_last else "├─ "
                line += self._render_child_html(child, "", connector, is_last, scale_factor)
        else:
            line = (
                f'<span style="color:{color}">├─ {node.func.name}</span> '
                f'<span style="color:{C["dim"]};font-size:{caption_font_size}px">'
                f'({os.path.basename(node.func.file_path)}:{node.func.line})</span><br>'
            )
            for i, child in enumerate(node.children):
                is_last = (i == len(node.children) - 1)
                new_prefix = prefix + ("  " * 2)
                line += self._render_chain_html(child, new_prefix, scale_factor=scale_factor)

        return line

    def _render_child_html(self, node: ChainNode, indent: str, connector: str, is_last: bool, scale_factor: float = 1.0) -> str:
        """渲染子节点（带树形连接线）"""
        color = [C["birth"], C["flow"], C["warn"], C["hl"], C["err"]][min(node.depth, 4)]
        caption_font_size = int(FONT_SIZE_CAPTION * scale_factor)
        line = (
            f'<div style="margin-left:20px">'
            f'<span style="color:{C["dim"]}">{indent}{connector}</span>'
            f'<span style="color:{color};font-weight:bold">{node.func.name}</span>'
            f'<span style="color:{C["dim"]};font-size:{caption_font_size}px"> '
            f'({os.path.basename(node.func.file_path)}:{node.func.line})</span>'
            f'</div>'
        )
        child_indent = indent + ("  " if is_last else "│ ")
        for i, child in enumerate(node.children):
            child_is_last = (i == len(node.children) - 1)
            child_connector = "└─ " if child_is_last else "├─ "
            line += self._render_child_html(child, child_indent, child_connector, child_is_last)
        return line

    def _count_nodes(self, node: ChainNode) -> int:
        """统计调用链节点总数"""
        count = 1
        for child in node.children:
            count += self._count_nodes(child)
        return count

    def _on_status(self, msg: str, color: str):
        self._progress.setVisible(False)
        self._status_label.setStyleSheet(f"color:{color};background:transparent")
        self._status_label.setText(msg)

    def _calculate_font_scale(self) -> float:
        """根据窗口宽度计算字体缩放比例"""
        width = self.width()
        base_width = 1300
        min_scale = 0.7
        max_scale = 1.5
        scale_factor = width / base_width
        return max(min(scale_factor, max_scale), min_scale)

    def resizeEvent(self, event):
        """窗口大小变化时重新渲染，实现文字自适应"""
        super().resizeEvent(event)
        if self._current_func_name:
            QTimer.singleShot(50, self._re_render_content)

    def _re_render_content(self):
        """重新渲染内容区域，应用新的字体大小"""
        if not self._current_func_name:
            return
        self._on_chain_done((
            self._current_chain,
            self._current_callers,
            self._current_callees,
            self._current_func_name
        ))

    def closeEvent(self, e):
        """点击 X 时返回工具箱主界面，而不是真正关闭"""
        if self._on_back:
            e.ignore()
            self.hide()
            self._on_back()
        else:
            e.accept()