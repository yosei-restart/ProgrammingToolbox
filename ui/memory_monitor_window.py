"""
内存使用监控器 - UI 窗口

PySide6 (LGPLv3) - GitHub Dark 主题
"""

from __future__ import annotations

import threading
import time

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QProgressBar, QComboBox, QSpinBox,
    QTextEdit, QApplication, QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QFont, QPainter, QColor, QPen, QBrush, QPainterPath

from utils.theme import COLORS, FONT_TITLE, FONT_HEADER, FONT_BODY, FONT_MONO, FONT_SMALL, FONT_SIZE_BODY, FONT_SIZE_MONO, FONT_SIZE_SMALL, FONT_SIZE_CAPTION, FONT_SIZE_TINY, get_global_stylesheet, apply_text_selectable
from core.memory_monitor import MemoryMonitor, MemorySnapshot, MonitorResult
from utils.logging_utils import get_logger

logger = get_logger(__name__)
C = COLORS


class MemoryChart(QWidget):
    """内存曲线图（纯 QPainter 绘制）"""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(200)
        self._snapshots: list[MemorySnapshot] = []
        self._peak_rss = 0
        self._peak_vms = 0
        self._total_time = 0

    def set_data(self, snapshots: list[MemorySnapshot], peak_rss: float, peak_vms: float):
        self._snapshots = snapshots
        self._peak_rss = peak_rss
        self._peak_vms = peak_vms
        self._total_time = snapshots[-1].timestamp if snapshots else 0
        self.update()

    def paintEvent(self, event):
        if not self._snapshots:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        margin = 40

        # 背景
        p.fillRect(0, 0, w, h, QColor(C["input"]))

        max_mem = max(self._peak_rss, self._peak_vms) * 1.2 or 10
        total_time = self._total_time or 1

        # 计算合理的Y轴刻度
        num_ticks = 8
        tick_step = max_mem / (num_ticks - 1)

        # 网格线和Y轴刻度
        p.setPen(QPen(QColor(C["border"]), 1, Qt.DashLine))
        for i in range(num_ticks):
            y = int(margin + (h - margin - 10) * i / (num_ticks - 1))
            p.drawLine(margin, y, w - 10, y)
            p.setPen(QPen(QColor(C["dim"])))
            p.setFont(FONT_SMALL)
            value = max_mem * (num_ticks - 1 - i) / (num_ticks - 1)
            p.drawText(2, y + 4, f"{value:.1f}")
            p.setPen(QPen(QColor(C["border"]), 1, Qt.DashLine))

        # Y轴标签
        p.setPen(QPen(QColor(C["dim"])))
        p.setFont(FONT_SMALL)
        p.save()
        p.translate(10, h / 2)
        p.rotate(-90)
        p.drawText(0, 0, "内存 (MB)")
        p.restore()

        # RSS 曲线
        rss_path = QPainterPath()
        vms_path = QPainterPath()
        first = True
        for s in self._snapshots:
            x = margin + (s.timestamp / total_time) * (w - margin - 10)
            ry = h - 10 - (s.rss_mb / max_mem) * (h - margin - 10)
            vy = h - 10 - (s.vms_mb / max_mem) * (h - margin - 10)
            if first:
                rss_path.moveTo(x, ry)
                vms_path.moveTo(x, vy)
                first = False
            else:
                rss_path.lineTo(x, ry)
                vms_path.lineTo(x, vy)

        p.setPen(QPen(QColor(C["accent"]), 2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(rss_path)

        p.setPen(QPen(QColor(C["warn"]), 1.5, Qt.DashLine))
        p.drawPath(vms_path)

        # 图例
        p.setPen(QPen(QColor(C["accent"])))
        p.drawText(margin, 16, f"RSS (物理内存)  峰值: {self._peak_rss:.1f} MB")
        p.setPen(QPen(QColor(C["warn"])))
        p.drawText(margin + 280, 16, f"VMS (虚拟内存)  峰值: {self._peak_vms:.1f} MB")

        p.end()


class MemoryMonitorSignals(QObject):
    status = Signal(str, str)
    snapshot = Signal(object)
    done = Signal(object)
    processes = Signal(list)


class MemoryMonitorWindow(QWidget):
    """内存使用监控器窗口"""

    def __init__(self, on_back=None):
        super().__init__()
        self.setWindowTitle("内存使用监控器")
        self.resize(1000, 700)
        self.setMinimumSize(700, 500)
        self._on_back = on_back
        self._monitor = MemoryMonitor()
        self._monitoring = False
        self._total_snapshots = 0

        self.setStyleSheet(get_global_stylesheet())
        self.sig = MemoryMonitorSignals()
        self.sig.status.connect(self._on_status)
        self.sig.snapshot.connect(self._on_snapshot)
        self.sig.done.connect(self._on_done)
        self.sig.processes.connect(self._on_processes)

        self._build_ui()
        apply_text_selectable(self)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_header())
        layout.addWidget(self._build_input())
        layout.addWidget(self._build_chart(), 1)
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
        t = QLabel("内存使用监控器")
        t.setFont(FONT_TITLE); t.setStyleSheet(f"color:{C['accent']};background:transparent")
        hl.addWidget(t); hl.addStretch()
        return h

    def _build_input(self):
        p = QFrame()
        p.setStyleSheet(f"background:{C['panel']};border-bottom:1px solid {C['border']}")
        vl = QVBoxLayout(p); vl.setContentsMargins(16, 10, 16, 10); vl.setSpacing(8)

        row1 = QHBoxLayout()
        lbl = QLabel("监控进程:")
        lbl.setFont(FONT_BODY); lbl.setStyleSheet(f"color:{C['fg']};background:transparent")
        row1.addWidget(lbl)

        self._proc_combo = QComboBox()
        self._proc_combo.setFont(FONT_BODY); self._proc_combo.setMinimumWidth(300)
        self._proc_combo.setStyleSheet(
            f"QComboBox{{background:{C['input']};color:{C['fg']};border:1px solid {C['border']};border-radius:6px;padding:6px 10px}}"
        )
        row1.addWidget(self._proc_combo, 1)

        btn_refresh = QPushButton("刷新")
        btn_refresh.setFont(FONT_SMALL)
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C['accent']};border:1px solid {C['accent']};border-radius:6px;padding:4px 12px}} "
            f"QPushButton:hover{{background:{C['accent']};color:{C['head']}}}"
        )
        btn_refresh.clicked.connect(self._refresh_processes)
        row1.addWidget(btn_refresh)
        vl.addLayout(row1)

        row2 = QHBoxLayout()
        lbl2 = QLabel("采样间隔:")
        lbl2.setFont(FONT_BODY); lbl2.setStyleSheet(f"color:{C['fg']};background:transparent")
        row2.addWidget(lbl2)
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(1, 60); self._interval_spin.setValue(1)
        self._interval_spin.setSuffix(" 秒")
        self._interval_spin.setFont(FONT_BODY)
        self._interval_spin.setStyleSheet(
            f"QSpinBox{{background:{C['input']};color:{C['fg']};border:1px solid {C['border']};border-radius:6px;padding:4px 8px}}"
        )
        row2.addWidget(self._interval_spin)
        row2.addStretch()

        self._btn_start = QPushButton("开始监控")
        self._btn_start.setFont(FONT_BODY)
        self._btn_start.setCursor(Qt.PointingHandCursor)
        self._btn_start.setStyleSheet(
            f"QPushButton{{background:{C['ok']};color:{C['head']};border:none;border-radius:6px;padding:6px 20px;font-weight:bold}} "
            f"QPushButton:hover{{background:#2ea043}} QPushButton:disabled{{background:{C['border']};color:{C['dim']}}}"
        )
        self._btn_start.clicked.connect(self._toggle_monitor)
        row2.addWidget(self._btn_start)

        vl.addLayout(row2)
        return p

    def _build_chart(self):
        sc = QScrollArea()
        self._chart_scroll = sc
        sc.setWidgetResizable(True)
        sc.setStyleSheet(f"QScrollArea{{background:{C['bg']};border:none}}")
        ct = QWidget()
        ct.setStyleSheet(f"background:{C['bg']}")
        cl = QVBoxLayout(ct); cl.setContentsMargins(16, 12, 16, 12); cl.setSpacing(10)

        self._chart = MemoryChart()
        self._chart.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        cl.addWidget(self._chart, 2)

        # 状态栏（监控停止/运行中提示）
        self._status_label = QLabel("就绪 - 点击「刷新」获取进程列表")
        self._status_label.setFont(FONT_SMALL)
        self._status_label.setStyleSheet(
            f"color:{C['dim']};background:{C['panel']};border-radius:6px;padding:6px 12px"
        )
        cl.addWidget(self._status_label)

        # 实时数据 + 统计（两列布局）
        row = QHBoxLayout()
        row.setSpacing(10)

        self._live_text = QTextEdit()
        self._live_text.setFont(FONT_MONO)
        self._live_text.setReadOnly(True)
        self._live_text.setMinimumHeight(100)
        self._live_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._live_text.setStyleSheet(
            f"QTextEdit{{background:{C['input']};color:{C['fg']};border:1px solid {C['border']};border-radius:8px;padding:8px 10px}}"
        )
        self._live_text.setHtml(
            f'<div style="font-family:Noto Sans SC;font-size:{FONT_SIZE_BODY}px;color:#9090A8">'
            '💡 点击「开始监控」后，这里将实时显示内存使用数据'
            '</div>'
        )
        row.addWidget(self._live_text)

        # 统计
        self._stats_text = QTextEdit()
        self._stats_text.setFont(FONT_MONO)
        self._stats_text.setReadOnly(True)
        self._stats_text.setMinimumHeight(100)
        self._stats_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._stats_text.setStyleSheet(
            f"QTextEdit{{background:{C['input']};color:{C['fg']};border:1px solid {C['border']};border-radius:8px;padding:10px}}"
        )
        self._stats_text.setHtml(
            f'<div style="font-family:Noto Sans SC;font-size:{FONT_SIZE_BODY}px;color:#9090A8">'
            '📊 监控结束后，这里将显示统计汇总'
            '</div>'
        )
        row.addWidget(self._stats_text)
        cl.addLayout(row)

        cl.addStretch()
        sc.setWidget(ct)
        return sc

    def _build_bottom(self):
        f = QFrame()
        f.setFixedHeight(10)
        f.setStyleSheet(f"background:{C['head']};border-top:1px solid {C['border']}")
        sl = QVBoxLayout(f); sl.setContentsMargins(0, 0, 0, 0); sl.setSpacing(0)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0); self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False); self._progress.setVisible(False)
        self._progress.setStyleSheet(
            f"QProgressBar{{background:{C['border']};border:none;border-radius:2px}} "
            f"QProgressBar::chunk{{background:{C['accent']};border-radius:2px}}"
        )
        sl.addWidget(self._progress)
        return f

    def _refresh_processes(self):
        self._on_status("正在获取进程列表...", C["warn"])
        threading.Thread(target=self._do_refresh, daemon=True).start()

    def _do_refresh(self):
        try:
            procs = self._monitor.get_running_processes()
            self.sig.processes.emit(procs)
        except Exception as e:
            self.sig.status.emit(f"获取进程失败: {e}", C["err"])

    def _on_processes(self, procs: list):
        self._proc_combo.clear()
        for p in procs:
            label = f"PID {p['pid']} | {p['rss_mb']:.1f} MB | {p['cmdline'][:80]}"
            self._proc_combo.addItem(label, p["pid"])
        self._on_status(f"找到 {len(procs)} 个进程（内存 > 1MB）", C["ok"])

    def _toggle_monitor(self):
        if self._monitoring:
            self._monitor.stop()
            self._btn_start.setText("开始监控")
            self._btn_start.setStyleSheet(
                f"QPushButton{{background:{C['ok']};color:{C['head']};border:none;border-radius:6px;padding:6px 20px;font-weight:bold}} "
            )
            self._monitoring = False
            self._on_status("监控已停止", C["warn"])
        else:
            pid = self._proc_combo.currentData()
            if not pid:
                self._on_status("请先选择一个进程", C["warn"])
                return
            self._monitoring = True
            self._total_snapshots = 0
            self._live_text.setVisible(True)
            self._btn_start.setText("停止监控")
            self._btn_start.setStyleSheet(
                f"QPushButton{{background:{C['err']};color:{C['head']};border:none;border-radius:6px;padding:6px 20px;font-weight:bold}} "
            )
            self._on_status("正在监控...", C["accent"])
            interval = self._interval_spin.value()
            self._monitor.start_monitor_async(
                pid, interval,
                on_snapshot=lambda s: self.sig.snapshot.emit(s),
                on_done=lambda r: self.sig.done.emit(r),
            )

    def _on_snapshot(self, snapshot: MemorySnapshot):
        self._total_snapshots += 1
        html = (
            f'<div style="font-family:Noto Sans SC,Consolas;font-size:{FONT_SIZE_SMALL}px;line-height:1.8">'
            f'<div style="font-weight:bold;color:{C["accent"]};margin-bottom:6px">'
            f'🔴 实时采样 #{self._total_snapshots}（每 {self._interval_spin.value()} 秒记录一次）</div>'
            f'<table style="border-collapse:collapse;width:100%">'
            f'<tr>'
            f'<td style="padding:4px 8px"><b style="color:{C["accent"]}">物理内存 RSS</b> <span style="color:{C["dim"]};font-size:{FONT_SIZE_TINY}px">实际占用的内存条空间</span></td>'
            f'<td style="padding:4px 8px;text-align:right;font-weight:bold;color:{C["accent"]}">{snapshot.rss_mb:.1f} MB</td>'
            f'</tr>'
            f'<tr>'
            f'<td style="padding:4px 8px"><b style="color:{C["warn"]}">虚拟内存 VMS</b> <span style="color:{C["dim"]};font-size:{FONT_SIZE_TINY}px">程序申请的地址空间总量（含未实际使用的）</span></td>'
            f'<td style="padding:4px 8px;text-align:right;font-weight:bold;color:{C["warn"]}">{snapshot.vms_mb:.1f} MB</td>'
            f'</tr>'
            f'<tr>'
            f'<td style="padding:4px 8px"><b style="color:{C["ok"]}">CPU 使用率</b> <span style="color:{C["dim"]};font-size:{FONT_SIZE_TINY}px">当前消耗的 CPU 百分比</span></td>'
            f'<td style="padding:4px 8px;text-align:right;font-weight:bold;color:{C["ok"]}">{snapshot.cpu_percent:.1f}%</td>'
            f'</tr>'
            f'<tr>'
            f'<td style="padding:4px 8px"><b style="color:{C["hl"]}">线程数</b> <span style="color:{C["dim"]};font-size:{FONT_SIZE_TINY}px">程序同时运行的任务数</span></td>'
            f'<td style="padding:4px 8px;text-align:right;font-weight:bold;color:{C["hl"]}">{snapshot.num_threads} 个</td>'
            f'</tr>'
            f'<tr>'
            f'<td style="padding:4px 8px"><b style="color:{C["dim"]}">已运行时间</b> <span style="color:{C["dim"]};font-size:{FONT_SIZE_TINY}px">从开始监控到现在的时间</span></td>'
            f'<td style="padding:4px 8px;text-align:right;font-weight:bold;color:{C["dim"]}">{snapshot.timestamp:.1f} 秒</td>'
            f'</tr>'
            f'</table>'
            f'</div>'
        )
        self._live_text.setHtml(html)

    def _on_done(self, result: MonitorResult):
        self._monitoring = False
        self._btn_start.setText("开始监控")
        self._btn_start.setStyleSheet(
            f"QPushButton{{background:{C['ok']};color:{C['head']};border:none;border-radius:6px;padding:6px 20px;font-weight:bold}} "
        )
        self._chart.set_data(result.snapshots, result.peak_rss_mb, result.peak_vms_mb)

        duration = result.end_time - result.start_time
        n = len(result.snapshots)
        peak = result.peak_rss_mb
        avg_rss = result.avg_rss_mb
        avg_cpu = result.avg_cpu

        # 判断内存趋势（比较前 1/3 和后 1/3 的均值）
        trend_text = ""
        trend_color = C["dim"]
        if n >= 6:
            first_third = result.snapshots[:n//3]
            last_third = result.snapshots[2*n//3:]
            first_avg = sum(s.rss_mb for s in first_third) / len(first_third)
            last_avg = sum(s.rss_mb for s in last_third) / len(last_third)
            diff = last_avg - first_avg
            if diff > 50:
                trend_text = f"⚠ 内存持续增长（+{diff:.1f} MB），可能存在内存泄漏！"
                trend_color = C["err"]
            elif diff > 10:
                trend_text = f"⚡ 内存轻微增长（+{diff:.1f} MB），建议关注"
                trend_color = C["warn"]
            elif diff < -10:
                trend_text = f"✅ 内存正在释放（{diff:.1f} MB），运行正常"
                trend_color = C["ok"]
            else:
                trend_text = f"✅ 内存稳定（波动 {abs(diff):.1f} MB），运行正常"
                trend_color = C["ok"]

        html = (
            f'<div style="font-family:Noto Sans SC,Consolas;font-size:{FONT_SIZE_SMALL}px;line-height:1.8">'
            f'<div style="font-weight:bold;color:{C["ok"]};font-size:{FONT_SIZE_MONO}px;margin-bottom:8px">'
            f'✅ 监控完成</div>'

            f'<div style="background:{C["panel"]};border-radius:6px;padding:8px 12px;margin-bottom:8px">'
            f'<div style="font-size:{FONT_SIZE_MONO}px;font-weight:bold;color:{trend_color};margin-bottom:4px">'
            f'📈 内存趋势判断：{trend_text}</div>'
            f'<div style="color:{C["dim"]};font-size:{FONT_SIZE_TINY}px">'
            f'对比监控前 1/3 和后 1/3 时段的平均内存，判断是否有内存泄漏（内存持续增长不释放）'
            f'</div></div>'

            f'<table style="border-collapse:collapse;width:100%">'
            f'<tr style="border-bottom:1px solid {C["border"]}">'
            f'<th style="padding:4px 8px;text-align:left;color:{C["dim"]};font-size:{FONT_SIZE_CAPTION}px">指标</th>'
            f'<th style="padding:4px 8px;text-align:right;color:{C["dim"]};font-size:{FONT_SIZE_CAPTION}px">数值</th>'
            f'<th style="padding:4px 8px;text-align:left;color:{C["dim"]};font-size:{FONT_SIZE_CAPTION}px">说明</th>'
            f'</tr>'

            f'<tr>'
            f'<td style="padding:4px 8px"><b style="color:{C["accent"]}">监控时长</b></td>'
            f'<td style="padding:4px 8px;text-align:right;font-weight:bold">{duration:.1f} 秒</td>'
            f'<td style="padding:4px 8px;color:{C["dim"]};font-size:{FONT_SIZE_TINY}px">总共监控了多久</td>'
            f'</tr>'

            f'<tr>'
            f'<td style="padding:4px 8px"><b style="color:{C["err"]}">峰值内存</b></td>'
            f'<td style="padding:4px 8px;text-align:right;font-weight:bold;color:{C["err"]}">{peak:.1f} MB</td>'
            f'<td style="padding:4px 8px;color:{C["dim"]};font-size:{FONT_SIZE_TINY}px">监控期间占用的最高内存（等于内存条峰值占用）</td>'
            f'</tr>'

            f'<tr>'
            f'<td style="padding:4px 8px"><b style="color:{C["accent"]}">平均内存</b></td>'
            f'<td style="padding:4px 8px;text-align:right;font-weight:bold">{avg_rss:.1f} MB</td>'
            f'<td style="padding:4px 8px;color:{C["dim"]};font-size:{FONT_SIZE_TINY}px">监控期间的平均占用（反映程序的日常开销）</td>'
            f'</tr>'

            f'<tr>'
            f'<td style="padding:4px 8px"><b style="color:{C["ok"]}">平均 CPU</b></td>'
            f'<td style="padding:4px 8px;text-align:right;font-weight:bold">{avg_cpu:.1f}%</td>'
            f'<td style="padding:4px 8px;color:{C["dim"]};font-size:{FONT_SIZE_TINY}px">CPU 平均使用率（越高越耗电，越低越省电）</td>'
            f'</tr>'

            f'<tr>'
            f'<td style="padding:4px 8px"><b style="color:{C["dim"]}">采样次数</b></td>'
            f'<td style="padding:4px 8px;text-align:right;font-weight:bold">{n}</td>'
            f'<td style="padding:4px 8px;color:{C["dim"]};font-size:{FONT_SIZE_TINY}px">总共记录了多少次数据（越多越精确）</td>'
            f'</tr>'

            f'</table>'
            f'</div>'
        )
        self._stats_text.setHtml(html)

        # 停止时：隐藏实时区，状态栏显示停止信息
        self._live_text.setVisible(False)
        self._on_status(
            f"监控已停止（共采集 {n} 次，详见下方统计汇总）",
            C["accent"]
        )

        # 自动滚动到统计汇总区域
        QTimer.singleShot(100, lambda: self._chart_scroll.ensureWidgetVisible(self._stats_text, 0, 0))

    def _on_status(self, msg: str, color: str):
        self._status_label.setStyleSheet(
            f"color:{color};background:{C['panel']};border-radius:6px;padding:6px 12px"
        )
        self._status_label.setText(msg)

    def closeEvent(self, e):
        if self._monitoring:
            self._monitor.stop()
        if self._on_back:
            self._on_back()
        else:
            e.accept()