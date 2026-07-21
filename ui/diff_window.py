"""
代码差异对比器 - UI 窗口

PySide6 (LGPLv3) - GitHub Dark 主题
"""

from __future__ import annotations

import os
import threading

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QFileDialog, QProgressBar, QLineEdit,
    QTextEdit, QTextBrowser, QApplication, QSplitter, QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QFont, QTextCursor, QColor, QTextCharFormat, QSyntaxHighlighter
from utils.theme import get_global_stylesheet, COLORS as C, FONT_TITLE, FONT_HEADER, FONT_BODY, FONT_MONO, FONT_SMALL, FONT_SIZE_BODY, FONT_SIZE_MONO, apply_text_selectable

from core.diff_engine import DiffEngine, DiffResult, DiffLine, CodeChangeAnalyzer
from utils.logging_utils import get_logger

logger = get_logger(__name__)


class DiffSignals(QObject):
    status = Signal(str, str)
    diff_done = Signal(object)


class DiffWindow(QWidget):
    """代码差异对比器窗口"""

    def __init__(self, on_back=None):
        super().__init__()
        self.setWindowTitle("代码差异对比器")
        self.resize(1200, 750)
        self.setMinimumSize(800, 500)
        self._on_back = on_back
        self._engine = DiffEngine()

        self.setStyleSheet(get_global_stylesheet())
        self.sig = DiffSignals()
        self.sig.status.connect(self._on_status)
        self.sig.diff_done.connect(self._on_diff_done)

        self._build_ui()
        apply_text_selectable(self)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_header())
        layout.addWidget(self._build_input())
        layout.addWidget(self._build_content(), 1)
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
        t = QLabel("代码差异对比器")
        t.setFont(FONT_TITLE); t.setStyleSheet(f"color:{C['accent']};background:transparent")
        hl.addWidget(t); hl.addStretch()
        return h

    def _build_input(self):
        p = QFrame()
        p.setStyleSheet(f"background:{C['panel']};border-bottom:1px solid {C['border']}")
        vl = QVBoxLayout(p); vl.setContentsMargins(16, 12, 16, 12); vl.setSpacing(8)

        for side, side_label, has_compare in [("left", "旧文件", False), ("right", "新文件", True)]:
            row = QHBoxLayout(); row.setSpacing(10)
            lbl = QLabel(f"{side_label}:")
            lbl.setFont(FONT_BODY); lbl.setStyleSheet(f"color:{C['fg']};background:transparent")
            lbl.setFixedWidth(60)
            row.addWidget(lbl)
            edit = QLineEdit()
            edit.setFont(FONT_BODY)
            edit.setPlaceholderText("选择文件...")
            edit.setStyleSheet(
                f"QLineEdit{{background:{C['input']};color:{C['fg']};border:1px solid {C['border']};border-radius:8px;padding:6px 10px}}"
            )
            row.addWidget(edit, 1)
            btn = QPushButton("选择")
            btn.setFont(FONT_SMALL)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedSize(70, 28)
            btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{C['accent']};border:1px solid {C['accent']};border-radius:8px;padding:4px 10px}} "
                f"QPushButton:hover{{background:{C['accent']};color:{C['head']}}}"
            )
            btn.clicked.connect(lambda checked=False, e=edit: self._select_file(e))
            row.addWidget(btn)
            if has_compare:
                self._btn_compare = QPushButton("对比差异")
                self._btn_compare.setFont(FONT_BODY)
                self._btn_compare.setCursor(Qt.PointingHandCursor)
                self._btn_compare.setMinimumWidth(100)
                self._btn_compare.setStyleSheet(
                    f"QPushButton{{background:{C['accent']};color:{C['head']};border:none;border-radius:8px;padding:4px 16px;font-weight:bold}} "
                    f"QPushButton:hover{{background:{C['ahover']}}}"
                )
                self._btn_compare.clicked.connect(self._compare)
                row.addWidget(self._btn_compare)
            else:
                row.addStretch()
            vl.addLayout(row)
            setattr(self, f"_{side}_edit", edit)

        return p

    def _build_content(self):
        # 颜色图例
        legend = QFrame()
        legend.setStyleSheet(f"background:{C['panel']};border-bottom:1px solid {C['border']}")
        ll = QHBoxLayout(legend); ll.setContentsMargins(16, 6, 16, 6); ll.setSpacing(16)

        ll.addWidget(QLabel("图例："))
        items = [
            ("#3fb950", "#0d3320", "新增  "),
            ("#f85149", "#3d1115", "删除  "),
            ("#d29922", "#2d2010", "修改  "),
            ("", "", "相同  "),
        ]
        for color, bg, label in items:
            chip = QLabel(f"  {label}  ")
            chip.setFont(FONT_SMALL)
            if color:
                chip.setStyleSheet(
                    f"color:{color};background:{bg};border-radius:4px;padding:2px 6px;font-weight:bold"
                )
            else:
                chip.setStyleSheet(
                    f"color:{C['dim']};background:transparent;padding:2px 6px"
                )
            ll.addWidget(chip)

        # 语义标注图例
        sep = QLabel("|")
        sep.setStyleSheet(f"color:{C['border']};background:transparent")
        ll.addWidget(sep)
        sem_chip = QLabel("  ▎ 语义标记  ")
        sem_chip.setFont(FONT_SMALL)
        sem_chip.setStyleSheet(
            f"color:#c586c0;background:#3a2540;border-radius:4px;padding:2px 6px;font-weight:bold"
        )
        ll.addWidget(sem_chip)
        ll.addWidget(QLabel("← 旧文件"))
        sem_chip2 = QLabel("  ▎ 语义标记  ")
        sem_chip2.setFont(FONT_SMALL)
        sem_chip2.setStyleSheet(
            f"color:#569cd6;background:#1a3550;border-radius:4px;padding:2px 6px;font-weight:bold"
        )
        ll.addWidget(sem_chip2)
        ll.addWidget(QLabel("← 新文件"))

        ll.addStretch()

        # 语义变更摘要（QTextBrowser + setOpenLinks(False)，避免自动导航）
        self._semantic_browser = QTextBrowser()
        self._semantic_browser.setOpenLinks(False)  # 关键：阻止自动导航，只触发 anchorClicked
        self._semantic_browser.setFont(FONT_SMALL)
        self._semantic_browser.setFrameShape(QTextBrowser.NoFrame)
        self._semantic_browser.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._semantic_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._semantic_browser.setMinimumHeight(28)
        self._semantic_browser.setMaximumHeight(400)
        self._semantic_browser.setStyleSheet(
            f"color:{C['dim']};background:{C['panel']};border-bottom:1px solid {C['border']};padding:4px 16px"
        )
        self._semantic_browser.setHtml(
            '<span style="color:#666">📋 对比两个 Python 文件后，这里将显示语义变更摘要（可点击跳转）</span>'
        )
        self._semantic_browser.anchorClicked.connect(self._on_semantic_click)

        # 左右分栏
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet(f"QSplitter::handle{{background:{C['border']};width:2px}}")

        for side, title_text in [("left", "📄 旧文件"), ("right", "📄 新文件")]:
            panel = QFrame()
            panel.setStyleSheet(f"background:{C['bg']};border:none")
            pl = QVBoxLayout(panel); pl.setContentsMargins(0, 0, 0, 0); pl.setSpacing(0)

            # 标题栏
            title_color = C["title"] if side == "left" else C["accent"]
            title_border = "2px solid #c586c0" if side == "left" else "2px solid #569cd6"
            title = QLabel(title_text)
            title.setFont(FONT_HEADER)
            title.setStyleSheet(
                f"color:{title_color};background:{C['panel']};"
                f"padding:6px 12px;border-bottom:1px solid {C['border']};"
                f"border-left:{title_border}"
            )
            pl.addWidget(title)

            # 代码区
            text_edit = QTextEdit()
            text_edit.setFont(FONT_MONO)
            text_edit.setReadOnly(True)
            text_edit.setStyleSheet(
                f"QTextEdit{{background:{C['input']};color:{C['fg']};border:none;padding:8px;font-family:Consolas}}"
            )
            pl.addWidget(text_edit, 1)

            splitter.addWidget(panel)
            setattr(self, f"_{side}_text", text_edit)
            setattr(self, f"_{side}_title", title)

        # 统计标签
        self._stats_label = QLabel("")
        self._stats_label.setFont(FONT_SMALL)
        self._stats_label.setStyleSheet(f"color:{C['dim']};background:transparent;padding:4px 12px")

        wrapper = QWidget()
        wl = QVBoxLayout(wrapper); wl.setContentsMargins(0, 0, 0, 0); wl.setSpacing(0)
        wl.addWidget(legend)
        wl.addWidget(self._semantic_browser)
        wl.addWidget(splitter, 1)
        wl.addWidget(self._stats_label)
        return wrapper

    def _build_bottom(self):
        f = QFrame()
        f.setFixedHeight(34)
        f.setStyleSheet(f"background:{C['head']};border-top:1px solid {C['border']}")
        sl = QVBoxLayout(f); sl.setContentsMargins(16, 2, 16, 2); sl.setSpacing(2)
        self._status_label = QLabel("就绪 - 选择两个文件进行对比")
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

    def _select_file(self, edit: QLineEdit):
        fp, _ = QFileDialog.getOpenFileName(self, "选择文件", "", "所有文件 (*.*);;Python 文件 (*.py);;文本文件 (*.txt)")
        if fp:
            edit.setText(fp)

    def _compare(self):
        left_path = self._left_edit.text().strip()
        right_path = self._right_edit.text().strip()
        if not left_path or not right_path:
            self._on_status("请先选择两个文件", C["warn"])
            return

        self._on_status("正在对比...", C["warn"])
        self._progress.setVisible(True)
        self._btn_compare.setEnabled(False)
        threading.Thread(target=self._do_compare, args=(left_path, right_path), daemon=True).start()

    def _do_compare(self, left_path: str, right_path: str):
        try:
            result = self._engine.compare_files(left_path, right_path)
            self.sig.diff_done.emit(result)
        except Exception as e:
            self.sig.status.emit(f"对比失败: {e}", C["err"])

    def _on_diff_done(self, result: DiffResult):
        self._progress.setVisible(False)
        self._btn_compare.setEnabled(True)

        if result.is_identical:
            self._semantic_browser.setHtml(
                '<span style="color:#3fb950;font-weight:bold">✅ 两个文件完全相同</span>'
            )
            self._semantic_browser.setMaximumHeight(28)
            self._left_text.setPlainText("\n".join(result.left_lines))
            self._right_text.setPlainText("\n".join(result.right_lines))
            self._left_title.setText("📄 旧文件")
            self._right_title.setText("📄 新文件")
            self._stats_label.setText("✓ 两个文件完全相同")
            self._stats_label.setStyleSheet(f"color:{C['ok']};background:transparent;padding:4px 12px;font-weight:bold")
            self._on_status("对比完成: 两个文件完全相同", C["ok"])
            return

        # 渲染左右差异
        self._render_side_by_side(result)

        # 更新标题栏显示文件名
        import os
        left_path = self._left_edit.text().strip()
        right_path = self._right_edit.text().strip()
        left_name = os.path.basename(left_path) if left_path else "旧文件"
        right_name = os.path.basename(right_path) if right_path else "新文件"
        self._left_title.setText(f"📄 {left_name}（旧文件）")
        self._right_title.setText(f"📄 {right_name}（新文件）")

        # 统计
        s = result.stats
        self._stats_label.setText(
            f"对比完成 | 相同: {s['equal']} | 新增: {s['added']} | 删除: {s['removed']} | 修改: {s['modified']}"
        )
        self._stats_label.setStyleSheet(f"color:{C['dim']};background:transparent;padding:4px 12px")
        self._on_status(
            f"+{s['added']} -{s['removed']} ~{s['modified']} ={s['equal']}",
            C["warn"] if s["added"] + s["removed"] + s["modified"] > 0 else C["ok"]
        )

        # 渲染语义变更摘要
        self._render_semantic_summary(result)

    def _render_semantic_summary(self, result: DiffResult):
        """渲染语义变更摘要到 QTextBrowser（可点击跳转）"""
        sem = result.semantic
        logger.info("_render_semantic_summary: sem=%s", bool(sem))

        if not sem:
            self._semantic_browser.setHtml(
                '<span style="color:#666">⚠ 语义分析未执行（非 Python 文件或分析失败）</span>'
            )
            return

        has_data = any(
            len(sem.get(k, {}).get("removed", [])) + len(sem.get(k, {}).get("added", [])) > 0
            for k in ["variables", "functions", "imports", "classes"]
        )
        has_unchanged = any(
            len(sem.get(k, {}).get("unchanged", [])) > 0
            for k in ["variables", "functions", "imports", "classes"]
        )

        if not has_data and not has_unchanged:
            self._semantic_browser.setHtml(
                '<span style="color:#666">⚠ 无法提取语义信息（AST 解析失败）</span>'
            )
            return

        if not has_data:
            self._semantic_browser.setHtml(
                '<span style="color:#3fb950;font-weight:bold">'
                '✅ 语义检查通过：变量名、函数签名、导入、类定义均无变化'
                '（代码有行级差异，但功能结构一致，不影响程序逻辑）</span>'
            )
            return

        # 有语义变更，构建表格式 HTML
        changed_lines = sem.get("_changed_lines", {})
        html = (
            f'<div style="font-family:Noto Sans SC;font-size:{FONT_SIZE_BODY}px;line-height:2.0">'
            f'<b style="color:{C["hl"]};font-size:{FONT_SIZE_BODY}px">📋 语义变更摘要（点击跳转）</b><br>'
            # 图例
            f'<span style="color:{C["err"]};background:#3d1115;border-radius:3px;'
            f'padding:2px 8px;margin:0 2px;text-decoration:line-through;font-family:Consolas;font-size:{FONT_SIZE_BODY}px">旧文件已删除</span>'
            f'<span style="color:{C["dim"]};margin:0 4px;font-size:{FONT_SIZE_MONO}px">= 左侧文件有，右侧文件已删除</span><br>'
            f'<span style="color:{C["ok"]};background:#0d3320;border-radius:3px;'
            f'padding:2px 8px;margin:0 2px;font-weight:bold;font-family:Consolas;font-size:{FONT_SIZE_BODY}px">新文件已新增</span>'
            f'<span style="color:{C["dim"]};margin:0 4px;font-size:{FONT_SIZE_MONO}px">= 右侧文件新增</span><br>'
            f'<span style="color:#c586c0;font-weight:bold">▎</span>'
            f'<span style="color:{C["dim"]};margin:0 4px;font-size:{FONT_SIZE_MONO}px">= 旧文件（左）语义变更行</span>'
            f'<span style="color:#569cd6;font-weight:bold">▎</span>'
            f'<span style="color:{C["dim"]};margin:0 4px;font-size:{FONT_SIZE_MONO}px">= 新文件（右）语义变更行</span>'
            f'<br>'
        )

        for key in ["variables", "functions", "imports", "classes"]:
            info = sem[key]
            if not info["changed"]:
                continue

            html += (
                f'<div style="margin:6px 0;padding:6px 0;border-top:1px solid {C["border"]}">'
                f'<b style="color:{C["dim"]}">{info["label"]}变更</b>'
            )

            # 删除项（旧文件独有）
            removed_lines = changed_lines.get(key, {}).get("removed_lines", [])
            if info["removed"]:
                html += (
                    f'<div style="margin:4px 0 2px 0">'
                    f'<span style="color:{C["err"]};font-size:{FONT_SIZE_MONO}px">🔴 已删除（旧文件独有）：</span>'
                )
                for idx, item in enumerate(info["removed"]):
                    escaped = item.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    ln_tuple = removed_lines[idx] if idx < len(removed_lines) else (0, 0)
                    if isinstance(ln_tuple, tuple):
                        start, end = ln_tuple
                    else:
                        start = end = ln_tuple
                    anchor = f"L:{start}" if start > 0 else "#"
                    range_text = f"第{start}~{end}行" if end > start else f"第{start}行"
                    html += (
                        f'<a href="{anchor}" style="display:inline-block;min-width:260px;'
                        f'color:{C["err"]};background:#3d1115;'
                        f'border-radius:3px;padding:2px 8px;margin:2px 4px;white-space:nowrap;'
                        f'text-decoration:line-through;font-family:Consolas;text-decoration:none;font-size:{FONT_SIZE_MONO}px">'
                        f'{range_text}：{escaped}</a>'
                    )
                    if (idx + 1) % 4 == 0 and idx < len(info["removed"]) - 1:
                        html += "<br>"
                html += "</div>"

            # 新增项（新文件独有）
            added_lines = changed_lines.get(key, {}).get("added_lines", [])
            if info["added"]:
                html += (
                    f'<div style="margin:4px 0 2px 0">'
                    f'<span style="color:{C["ok"]};font-size:{FONT_SIZE_MONO}px">🟢 已新增（新文件独有）：</span>'
                )
                for idx, item in enumerate(info["added"]):
                    escaped = item.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    ln_tuple = added_lines[idx] if idx < len(added_lines) else (0, 0)
                    if isinstance(ln_tuple, tuple):
                        start, end = ln_tuple
                    else:
                        start = end = ln_tuple
                    anchor = f"R:{start}" if start > 0 else "#"
                    range_text = f"第{start}~{end}行" if end > start else f"第{start}行"
                    html += (
                        f'<a href="{anchor}" style="display:inline-block;min-width:260px;'
                        f'color:{C["ok"]};background:#0d3320;'
                        f'border-radius:3px;padding:2px 8px;margin:2px 4px;white-space:nowrap;'
                        f'font-weight:bold;font-family:Consolas;text-decoration:none;font-size:{FONT_SIZE_MONO}px">'
                        f'{range_text}：{escaped}</a>'
                    )
                    if (idx + 1) % 4 == 0 and idx < len(info["added"]) - 1:
                        html += "<br>"
                html += "</div>"

            html += "</div>"

        # 总结
        summary = sem["summary"]
        if summary["total_changed"] <= 2:
            summary_text = f"⚠ 有 {summary['total_changed']} 类语义变更，请检查变量名和函数签名"
            summary_color = C["warn"]
        else:
            summary_text = f"🔴 有 {summary['total_changed']} 类语义变更，变量/函数/导入/类均有变化，建议仔细检查"
            summary_color = C["err"]

        html += (
            f'<b style="color:{summary_color}">{summary_text}</b>'
            f'</div>'
        )

        self._semantic_browser.setHtml(html)
        self._semantic_browser.setMaximumHeight(400)
        logger.info("语义摘要面板已更新（可点击跳转）")

    def _on_semantic_click(self, url):
        """点击语义变更项 → 跳转到对应代码行"""
        anchor = url.toString()
        logger.info("语义点击: %s", anchor)

        if ":" not in anchor:
            return
        side, lineno_str = anchor.split(":", 1)
        try:
            lineno = int(lineno_str)
        except ValueError:
            return

        if side.lower() == "l":
            self._scroll_to_line(self._left_text, lineno)
        elif side.lower() == "r":
            self._scroll_to_line(self._right_text, lineno)

    def _scroll_to_line(self, text_edit: QTextEdit, lineno: int):
        """滚动 QTextEdit 到指定行并高亮

        注意：diff 视图的 block 编号 ≠ 原始文件行号。
        每行渲染格式为 "[▎]{lineno:>4} code"，需要搜索包含行号文本的 block。
        """
        if lineno <= 0:
            return
        doc = text_edit.document()
        pattern = f"{lineno:>4} "  # 例如 " 109 "
        logger.info("_scroll_to_line: 搜索行号 '%s'", pattern)

        # 遍历所有 block，找到包含行号标记的（不要求开头，因为有 ▎ 标记）
        block = doc.begin()
        while block.isValid():
            if pattern in block.text():
                cursor = QTextCursor(block)
                text_edit.setTextCursor(cursor)
                text_edit.ensureCursorVisible()
                block_num = block.blockNumber()
                logger.info("_scroll_to_line: 找到行号 %d → block %d", lineno, block_num)
                self._flash_line(text_edit, block_num)
                return
            block = block.next()

        logger.warning("_scroll_to_line: 未找到行号 %d", lineno)

    def _flash_line(self, text_edit: QTextEdit, block_num: int):
        """用 ExtraSelections 高亮指定行（覆盖层，不受 HTML 样式影响）"""
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(QColor("#5a4a20"))
        sel.format.setProperty(QTextCharFormat.FullWidthSelection, True)
        sel.cursor = QTextCursor(text_edit.document().findBlockByNumber(block_num))
        sel.cursor.select(QTextCursor.LineUnderCursor)
        text_edit.setExtraSelections([sel])
        # 0.8 秒后清除
        QTimer.singleShot(800, lambda te=text_edit: te.setExtraSelections([]))

    def _render_side_by_side(self, result: DiffResult):
        """渲染左右对比视图"""
        # 收集语义变更的行号（用于额外标注）
        semantic_left_lines: set[int] = set()
        semantic_right_lines: set[int] = set()
        if result.semantic and "_changed_lines" in result.semantic:
            for key_info in result.semantic["_changed_lines"].values():
                for ln_tuple in key_info.get("removed_lines", []):
                    start, _end = ln_tuple if isinstance(ln_tuple, tuple) else (ln_tuple, ln_tuple)
                    if start > 0:
                        semantic_left_lines.add(start)
                for ln_tuple in key_info.get("added_lines", []):
                    start, _end = ln_tuple if isinstance(ln_tuple, tuple) else (ln_tuple, ln_tuple)
                    if start > 0:
                        semantic_right_lines.add(start)

        left_html = f'<pre style="font-family:Consolas;font-size:{FONT_SIZE_BODY}px;line-height:1.8;margin:0">'
        right_html = f'<pre style="font-family:Consolas;font-size:{FONT_SIZE_BODY}px;line-height:1.8;margin:0">'

        for dl in result.diff_lines:
            if dl.kind == "equal":
                left_color = right_color = ""
                left_bg = right_bg = ""
            elif dl.kind == "added":
                left_color = "color:#555"
                left_bg = ""
                right_color = "color:#3fb950"
                right_bg = "background:#0d3320"
            elif dl.kind == "removed":
                left_color = "color:#f85149"
                left_bg = "background:#3d1115"
                right_color = "color:#555"
                right_bg = ""
            elif dl.kind == "modified":
                left_color = "color:#d29922"
                left_bg = "background:#2d2010"
                right_color = "color:#d29922"
                right_bg = "background:#2d2010"

            # 语义变更标注：行首加彩色 ▎ 标记
            left_marker = ""
            right_marker = ""
            if dl.left_line_no and dl.left_line_no in semantic_left_lines:
                left_marker = '<span style="color:#c586c0;font-weight:bold">▎</span>'
            if dl.right_line_no and dl.right_line_no in semantic_right_lines:
                right_marker = '<span style="color:#569cd6;font-weight:bold">▎</span>'

            left_no = f"{dl.left_line_no:>4}" if dl.left_line_no else "    "
            right_no = f"{dl.right_line_no:>4}" if dl.right_line_no else "    "
            left_txt = dl.left_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            right_txt = dl.right_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

            left_html += f'{left_marker}<span style="{left_color};{left_bg}">{left_no} {left_txt}</span>\n'
            right_html += f'{right_marker}<span style="{right_color};{right_bg}">{right_no} {right_txt}</span>\n'

        left_html += "</pre>"
        right_html += "</pre>"

        self._left_text.setHtml(left_html)
        self._right_text.setHtml(right_html)

        # 同步滚动
        self._sync_scroll()

    def _sync_scroll(self):
        """同步左右滚动条"""
        left_v = self._left_text.verticalScrollBar()
        right_v = self._right_text.verticalScrollBar()
        if left_v and right_v:
            left_v.valueChanged.connect(right_v.setValue)
            right_v.valueChanged.connect(left_v.setValue)

    def _on_status(self, msg: str, color: str):
        self._progress.setVisible(False)
        self._status_label.setStyleSheet(f"color:{color};background:transparent")
        self._status_label.setText(msg)

    def closeEvent(self, e):
        if self._on_back:
            self._on_back()
        else:
            e.accept()