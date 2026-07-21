"""
内存使用监控器引擎

功能：
- 监控指定 Python 进程的内存使用（RSS、VMS）
- 实时采样，生成时间序列数据
- 支持监控正在运行的进程或启动新进程进行监控
- 导出为 JSON 数据

依赖：psutil（跨平台进程监控）
"""

from __future__ import annotations

import os
import time
import threading
import subprocess
from dataclasses import dataclass, field


@dataclass
class MemorySnapshot:
    """内存快照"""
    timestamp: float            # 相对起始时间（秒）
    rss_mb: float               # 物理内存（MB）
    vms_mb: float               # 虚拟内存（MB）
    cpu_percent: float = 0.0    # CPU 使用率
    num_threads: int = 0        # 线程数


@dataclass
class MonitorResult:
    """监控结果"""
    process_name: str
    pid: int
    snapshots: list[MemorySnapshot] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    peak_rss_mb: float = 0.0
    peak_vms_mb: float = 0.0
    avg_rss_mb: float = 0.0
    avg_cpu: float = 0.0


class MemoryMonitor:
    """内存监控器"""

    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None
        self._result: MonitorResult | None = None
        self._on_snapshot = None

    def start_monitor(self, pid: int, interval: float = 0.5,
                      on_snapshot=None) -> MonitorResult:
        """启动监控（阻塞模式）"""
        import psutil

        self._running = True
        self._on_snapshot = on_snapshot
        self._result = MonitorResult(
            process_name="",
            pid=pid,
            start_time=time.time(),
        )

        try:
            proc = psutil.Process(pid)
            self._result.process_name = proc.name()

            while self._running:
                try:
                    mem = proc.memory_info()
                    cpu = proc.cpu_percent(interval=0.1)
                    snapshot = MemorySnapshot(
                        timestamp=time.time() - self._result.start_time,
                        rss_mb=mem.rss / (1024 * 1024),
                        vms_mb=mem.vms / (1024 * 1024),
                        cpu_percent=cpu,
                        num_threads=proc.num_threads(),
                    )
                    self._result.snapshots.append(snapshot)

                    if on_snapshot:
                        on_snapshot(snapshot)

                    time.sleep(interval)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    break

        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            pass

        self._result.end_time = time.time()
        self._compute_stats()
        self._running = False
        return self._result

    def start_monitor_async(self, pid: int, interval: float = 0.5,
                            on_snapshot=None, on_done=None):
        """启动监控（异步模式）"""
        self._thread = threading.Thread(
            target=self._run_async,
            args=(pid, interval, on_snapshot, on_done),
            daemon=True,
        )
        self._thread.start()

    def _run_async(self, pid, interval, on_snapshot, on_done):
        result = self.start_monitor(pid, interval, on_snapshot)
        if on_done:
            on_done(result)

    def stop(self):
        """停止监控"""
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def get_result(self) -> MonitorResult | None:
        return self._result

    def _compute_stats(self):
        """计算统计信息"""
        if not self._result or not self._result.snapshots:
            return
        snaps = self._result.snapshots
        self._result.peak_rss_mb = max(s.rss_mb for s in snaps)
        self._result.peak_vms_mb = max(s.vms_mb for s in snaps)
        self._result.avg_rss_mb = sum(s.rss_mb for s in snaps) / len(snaps)
        self._result.avg_cpu = sum(s.cpu_percent for s in snaps) / len(snaps)

    def launch_and_monitor(self, script_path: str, args: list[str] | None = None,
                           interval: float = 0.5, on_snapshot=None,
                           on_done=None) -> subprocess.Popen:
        """启动脚本并监控内存"""
        cmd = ["python", script_path]
        if args:
            cmd.extend(args)

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

        self.start_monitor_async(proc.pid, interval, on_snapshot, on_done)
        return proc

    def get_running_processes(self) -> list[dict]:
        """获取正在运行的所有进程列表（按内存降序）"""
        import psutil
        processes = []
        for proc in psutil.process_iter(["pid", "name", "cmdline", "memory_info"]):
            try:
                info = proc.info
                cmdline = info["cmdline"] or []
                cmd_str = " ".join(cmdline)
                mem = info["memory_info"]
                rss_mb = mem.rss / (1024 * 1024) if mem else 0
                if rss_mb < 1:  # 跳过小于 1MB 的进程，减少噪音
                    continue
                processes.append({
                    "pid": info["pid"],
                    "name": info["name"] or "未知",
                    "cmdline": cmd_str[:120] or info["name"] or "",
                    "rss_mb": rss_mb,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        return sorted(processes, key=lambda p: p["rss_mb"], reverse=True)