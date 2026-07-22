"""
变量生命周期动态追踪引擎

使用 sys.settrace() 在运行时追踪目标程序中指定变量的值变化，
记录变量完整的生命周期事件：诞生、赋值、使用、销毁。

与 lifecycle_tracer.py（静态 AST 分析）互补：
- 静态分析：扫描源码，找出变量在代码中出现的所有位置（编译期视角）
- 动态追踪：运行程序，记录变量在运行时实际的值变化轨迹（运行期视角）

纯 Python 标准库实现，不依赖任何第三方库。
设计为在子进程中运行，通过 JSON 文件与主进程交换结果。

使用方式::

    from core.dynamic_tracer import run_tracer
    result = run_tracer(
        target_script="app.py",
        variable_name="my_var",
        folder_path="/path/to/project",
        output_path="/tmp/result.json",
    )

局限性：
- sys.settrace 仅追踪主线程，子线程中的变量不会被追踪
- 追踪会显著降低程序运行速度（每行代码都会触发回调）
- 大循环中的变量会产生大量事件
"""

import sys
import os
import json
import time
import runpy
import traceback
import threading
from dataclasses import dataclass, field, asdict
from typing import List, Optional
from datetime import datetime

from utils.logging_utils import get_logger

logger = get_logger(__name__)


def _setup_subprocess_logging():
    """设置子进程日志，确保 INFO 级别日志能实时输出到 stderr 被主进程捕获"""
    import logging
    import sys

    # 清除已有 handler（get_logger 会添加 console_handler + file_handler），
    # 避免重复输出到 stderr
    logger.handlers.clear()

    # 添加专用的 stderr handler
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.INFO)
    stderr_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(stderr_handler)
    logger.setLevel(logging.INFO)

    # 启动时立刻输出，确认日志系统正常
    logger.info("[TRACE] 子进程启动，日志系统初始化完成")
    sys.stderr.flush()


__all__ = [
    "DynamicEvent",
    "DynamicResult",
    "VariableTracer",
    "run_tracer",
    "load_result",
]


# repr 最大长度限制，防止超大对象撑爆输出
_MAX_VALUE_REPR = 500


@dataclass
class DynamicEvent:
    """动态追踪事件节点。

    记录变量在运行时的单次状态变化，是 DynamicResult.events 列表中的元素。
    """

    seq: int                    # 序号（从1开始）
    timestamp: float            # 运行时时间戳（相对程序启动的秒数）
    event_type: str             # 事件类型: "诞生"/"赋值"/"使用"/"销毁"
    file_path: str              # 文件路径（相对路径）
    file_name: str              # 文件名
    line: int                   # 行号
    code_line: str              # 该行源代码（已 strip）
    value_repr: str             # 变量值的 repr（如 "30", "'hello'", "[1, 2, 3]"）
    value_type: str             # 变量运行时类型（如 "int", "str", "list"）
    scope: str                   # 作用域（函数名或 "module: 文件名"）
    context_lines: list = field(default_factory=list)  # 前后各2行上下文
    target_idx: int = -1                              # 目标行在上下文中的索引


@dataclass
class DynamicResult:
    """动态追踪结果。

    包含变量的完整运行时事件轨迹和统计摘要，可序列化为 JSON。
    """

    variable_name: str          # 追踪的变量名
    events: list                # DynamicEvent 列表
    total_events: int           # 总事件数
    birth_count: int            # 诞生次数
    assign_count: int           # 赋值次数
    use_count: int              # 使用次数
    death_count: int            # 销毁次数
    files_involved: list        # 涉及的文件列表
    start_time: str             # 程序启动时间（格式化字符串）
    end_time: str               # 程序结束时间（格式化字符串）
    duration: float             # 运行时长（秒）
    error: str = ""             # 如果程序出错，记录错误信息


class VariableTracer:
    """
    sys.settrace 追踪器。

    在子进程中运行，追踪目标变量的运行时值变化。

    通过 sys.settrace() 注册全局追踪函数，在每行代码执行时检查
    frame.f_locals 中目标变量的值，判断事件类型并记录。

    优化：通过 target_lines 精确定位，只追踪静态分析找到的变量出现位置，
    其他行直接跳过，大幅降低性能开销。

    防重入机制：追踪函数内部调用辅助方法（如 _get_source_line）时会触发
    新的 trace 事件，通过 _processing 标志阻止递归，避免无限循环。

    值变化检测：使用 repr() 字符串比较替代 identity（is）比较，能正确
    检测可变对象的就地修改（如 list.append），并避免小整数缓存导致的误判。

    Args:
        variable_name: 要追踪的变量名
        folder_path: 项目根目录（用于解析相对路径和读取源码）
        target_lines: 静态分析找到的变量出现位置集合，
                      格式 {(abs_file_path, line_no), ...}，
                      为 None 时追踪所有行（兼容旧逻辑）
    """

    def __init__(self, variable_name: str, folder_path: str, target_lines: set = None, target_funcs: set = None):
        """初始化追踪器。

        Args:
            variable_name: 要追踪的变量名
            folder_path: 项目根目录（用于解析相对路径和读取源码）
            target_lines: 静态分析定位的变量出现位置集合，None 时追踪所有行
            target_funcs: 静态分析定位的包含变量的函数名集合，用于优化 call 事件过滤
        """
        self.variable_name = variable_name
        self.folder_path = folder_path
        self.target_lines = target_lines  # {(abs_file_path, line_no), ...}
        self.target_funcs = target_funcs  # {func_name, ...}

        # 预计算：文件集合 + 文件→行号集合映射，全部 O(1) 查找
        self._target_files = set()
        self._target_lines_by_file: dict = {}  # {abs_file_path: set(line_no), ...}
        if target_lines:
            for file_path, line_no in target_lines:
                self._target_files.add(file_path)
                if file_path not in self._target_lines_by_file:
                    self._target_lines_by_file[file_path] = set()
                self._target_lines_by_file[file_path].add(line_no)

        # 性能计数器
        self._call_count = 0
        self._call_filtered = 0
        self._line_count = 0
        self._line_filtered = 0

        # 路径缓存：避免重复调用 os.path.abspath
        self._abs_path_cache: dict = {}

        self.events: List[DynamicEvent] = []
        self._seq = 0
        self._start_time: Optional[float] = None
        self._last_repr = ...   # 哨兵值，表示"还未出现"
        self._last_value = ...  # 哨兵值，表示"还未出现"
        self._born = False
        self._source_cache: dict = {}   # 文件路径 -> 行列表，缓存用
        self._processing = False        # 防止 trace_func 重入
        self._pending_line = None       # 延迟记录：保存上一个目标行的状态，用于判断赋值/诞生

    def _get_abs_path(self, filename: str) -> str:
        """获取文件的绝对路径（带缓存），使用 realpath 统一 8.3 短名格式"""
        cached = self._abs_path_cache.get(filename)
        if cached is not None:
            return cached
        try:
            abs_file = os.path.realpath(filename)
        except Exception:
            abs_file = filename
        self._abs_path_cache[filename] = abs_file
        return abs_file

    def trace_func(self, frame, event, arg):
        """sys.settrace 回调函数。

        优化策略（类似 VS Code 断点）：
        1. 只追踪主线程，非主线程直接返回 None
        2. call 事件：文件级 O(1) + 函数级 O(1) 过滤，非目标函数返回 None
        3. line 事件：行级过滤，非目标行直接 return
        4. return 事件：记录销毁，不卸载 settrace（在回调内卸载会导致 CPython 状态不一致）
        """
        # 防止重入
        if self._processing:
            return self.trace_func

        # 只追踪主线程，避免 keyboard/tkinter 等库的后台线程导致 GIL 崩溃
        if threading.current_thread() is not threading.main_thread():
            return None

        if event == "call":
            self._call_count += 1
            filename = frame.f_code.co_filename

            if self.target_lines:
                abs_file = self._get_abs_path(filename)

                # 第一步：文件级过滤 O(1)
                if abs_file not in self._target_files:
                    self._call_filtered += 1
                    return None

                # 第二步：函数级过滤 O(1)
                func_name = frame.f_code.co_name
                # 模块级代码（<module>）不做函数过滤，只要文件匹配就追踪
                # 因为模块级代码没有函数名，target_funcs 中存的是函数名
                if func_name != "<module>" and self.target_funcs and func_name and func_name not in self.target_funcs:
                    self._call_filtered += 1
                    return None
            else:
                if not self._is_target_file(filename):
                    self._call_filtered += 1
                    return None

            return self.trace_func

        if event == "line":
            self._line_count += 1

            # 行级过滤：非目标行直接返回，不进入 _on_line
            if self.target_lines is not None:
                filename = frame.f_code.co_filename
                lineno = frame.f_lineno
                abs_file = self._get_abs_path(filename)
                lines_set = self._target_lines_by_file.get(abs_file)
                if lines_set is None or lineno not in lines_set:
                    self._line_filtered += 1
                    return self.trace_func

            self._processing = True
            try:
                self._on_line(frame)
            except Exception as exc:
                logger.error("追踪行事件出错: %s", exc)
            finally:
                self._processing = False
        elif event == "return":
            self._processing = True
            try:
                self._on_return(frame, arg)
            except Exception as exc:
                logger.error("追踪返回事件出错: %s", exc)
            finally:
                self._processing = False

        return self.trace_func

    def _is_target_file(self, filename: str) -> bool:
        """判断文件是否在目标文件夹内（只追踪用户代码，不追踪标准库）

        Args:
            filename: 文件绝对路径

        Returns:
            True 如果文件在目标文件夹内
        """
        if not filename or not self.folder_path:
            return False
        try:
            abs_file = os.path.abspath(filename)
            abs_folder = os.path.abspath(self.folder_path)
            return abs_file.startswith(abs_folder)
        except Exception:
            return False

    def _resolve_value(self, locals_dict: dict):
        """从 frame.f_locals 中解析变量值，支持 self.xxx 属性访问。

        Args:
            locals_dict: frame.f_locals 字典

        Returns:
            (found: bool, value: Any) — found=False 表示变量不存在
        """
        if "." not in self.variable_name:
            # 普通变量
            if self.variable_name not in locals_dict:
                return False, None
            return True, locals_dict[self.variable_name]

        # 支持 self.xxx 形式
        parts = self.variable_name.split(".")
        root_name = parts[0]
        if root_name not in locals_dict:
            return False, None

        current = locals_dict[root_name]
        for attr in parts[1:]:
            try:
                current = getattr(current, attr)
            except AttributeError:
                return False, None
        return True, current

    def _record_event(self, filename, lineno, code_line, context_lines, target_idx,
                      scope, value_repr, value_type, event_type):
        """记录一个动态事件。

        Args:
            filename: 文件绝对路径
            lineno: 行号
            code_line: 代码行内容
            context_lines: 上下文行列表
            target_idx: 目标行在上下文中的索引
            scope: 作用域名称
            value_repr: 变量值的 repr
            value_type: 变量类型名
            event_type: 事件类型（诞生/赋值/使用/消亡）
        """
        self._seq += 1
        timestamp = time.time() - self._start_time if self._start_time else 0.0

        try:
            rel_path = (
                os.path.relpath(filename, self.folder_path)
                if self.folder_path
                else filename
            )
        except ValueError:
            rel_path = filename

        try:
            log_rel_path = rel_path
        except Exception:
            log_rel_path = filename

        logger.warning("[BUILD_TARGET] 文件=%s 行=%d 类型=%s 函数=%r 代码=%r",
                      log_rel_path, lineno, event_type, scope, code_line)

        event = DynamicEvent(
            seq=self._seq,
            timestamp=round(timestamp, 6),
            event_type=event_type,
            file_path=rel_path,
            file_name=os.path.basename(filename),
            line=lineno,
            code_line=code_line,
            value_repr=value_repr[:_MAX_VALUE_REPR],
            value_type=value_type,
            scope=scope,
            context_lines=context_lines,
            target_idx=target_idx,
        )
        self.events.append(event)

    def _flush_pending_line(self, current_found, current_repr, current_value_type=""):
        """处理 pending 行，判断上一个目标行导致了什么事件并记录。

        Args:
            current_found: 当前行执行前变量是否存在
            current_repr: 当前行执行前变量的值的 repr
            current_value_type: 当前行执行前变量的类型名
        """
        if not self._pending_line:
            return

        p = self._pending_line
        prev_found = p["found_before"]
        prev_repr = p["value_repr_before"]

        if not prev_found and current_found:
            event_type = "诞生"
            self._born = True
            self._record_event(
                p["filename"], p["lineno"], p["code_line"],
                p["context_lines"], p["target_idx"],
                p["scope"], current_repr, current_value_type, event_type,
            )
        elif prev_found and current_found and prev_repr != current_repr:
            event_type = "赋值"
            self._record_event(
                p["filename"], p["lineno"], p["code_line"],
                p["context_lines"], p["target_idx"],
                p["scope"], current_repr, current_value_type, event_type,
            )
        elif prev_found and current_found and prev_repr == current_repr:
            event_type = "使用"
            self._record_event(
                p["filename"], p["lineno"], p["code_line"],
                p["context_lines"], p["target_idx"],
                p["scope"], prev_repr, p["value_type"], event_type,
            )

        self._pending_line = None

    def _on_line(self, frame):
        """每行代码执行时回调。

        注意：行级过滤已在 trace_func 中完成，进入此方法时
        当前行一定是目标行。

        延迟记录机制：
        line 事件在代码执行前触发，此时读到的值是"执行前"的值。
        我们保存当前行的状态为 pending，等下一个目标行的 line 事件
        触发时，再判断上一行执行后值是否变化，从而确定事件类型。
        这样诞生/赋值事件的行号就落在正确的赋值行上。
        """
        filename = frame.f_code.co_filename
        lineno = frame.f_lineno

        locals_dict = frame.f_locals
        found, current_value = self._resolve_value(locals_dict)

        try:
            current_repr = repr(current_value) if found else None
        except Exception:
            current_repr = "<无法表示>" if found else None
        value_type = type(current_value).__name__ if found else ""

        code_line = self._get_source_line(filename, lineno)
        context_lines, target_idx = self._get_context(filename, lineno)
        if not code_line and context_lines:
            if 0 <= target_idx < len(context_lines):
                code_line = context_lines[target_idx].strip()

        scope = frame.f_code.co_name or "module"
        if scope == "<module>":
            scope = "module: " + os.path.basename(filename)

        # 如果有上一个 pending 行，先处理它（用当前行的值判断上一行是否导致了变化）
        if self._pending_line:
            self._flush_pending_line(found, current_repr, value_type)

        # 将当前行保存为 pending，等下一行再判断
        self._pending_line = {
            "filename": filename,
            "lineno": lineno,
            "code_line": code_line,
            "context_lines": context_lines,
            "target_idx": target_idx,
            "scope": scope,
            "found_before": found,
            "value_repr_before": current_repr,
            "value_type": value_type,
        }

    def _on_return(self, frame, arg):
        """函数返回时回调。

        当函数返回时，如果目标变量在该函数的局部作用域中，
        则记录"销毁"事件（局部变量随函数返回而销毁）。

        模块级作用域的 return 不记录销毁（程序结束即隐式销毁）。

        注意：返回事件不做 target_lines 过滤，因为 frame.f_lineno
        是函数最后一行，通常不在静态分析的目标行中。

        另外：return 时先处理 pending 行（函数内最后一个目标行），
        因为 return 时的值就是函数最后一行执行后的值。

        Args:
            frame: 返回的栈帧
            arg: 返回值
        """
        co_name = frame.f_code.co_name
        # 跳过模块级 return（程序结束时所有变量隐式销毁，不需要单独记录）
        if co_name == "<module>":
            return

        locals_dict = frame.f_locals
        found, current_value = self._resolve_value(locals_dict)
        if not found:
            return

        filename = frame.f_code.co_filename
        lineno = frame.f_lineno
        code_line = self._get_source_line(filename, lineno)
        context_lines, target_idx = self._get_context(filename, lineno)
        if not code_line and context_lines:
            if 0 <= target_idx < len(context_lines):
                code_line = context_lines[target_idx].strip()

        try:
            value_repr = repr(current_value)
        except Exception:
            value_repr = "<无法表示>"
        value_type = type(current_value).__name__

        try:
            rel_path = (
                os.path.relpath(filename, self.folder_path)
                if self.folder_path
                else filename
            )
        except ValueError:
            rel_path = filename

        # 先处理 pending 行（函数内最后一个目标行）
        # return 时的值就是最后一行执行后的值，可以用来判断最后一个目标行的事件类型
        if self._pending_line and self._pending_line["filename"] == filename:
            self._flush_pending_line(True, value_repr)

        # 记录销毁事件
        self._record_event(
            filename, lineno, code_line,
            context_lines, target_idx,
            co_name, value_repr, value_type, "销毁",
        )

    def _get_source_line(self, filename: str, lineno: int) -> str:
        """获取指定文件指定行的源代码。

        Args:
            filename: 文件绝对路径
            lineno: 行号（从1开始）

        Returns:
            该行源代码（已 strip）；行号越界时返回空串
        """
        lines = self._get_source_lines(filename)
        if 0 < lineno <= len(lines):
            return lines[lineno - 1].strip()
        return ""

    def _get_source_lines(self, filename: str) -> list:
        """获取文件的所有行（带缓存）。

        优先 UTF-8 解码，失败回退 GBK，均失败返回空列表。
        结果缓存在 _source_cache 中，避免重复读取。

        Args:
            filename: 文件绝对路径

        Returns:
            按行拆分的列表（保留换行符）
        """
        if filename not in self._source_cache:
            lines = []
            for encoding in ("utf-8", "gbk"):
                try:
                    with open(filename, "r", encoding=encoding) as f:
                        lines = f.readlines()
                    break
                except UnicodeDecodeError:
                    continue
                except OSError:
                    break
            self._source_cache[filename] = lines
        return self._source_cache[filename]

    def _get_context(self, filename: str, lineno: int) -> tuple:
        """获取前后各2行上下文（共5行）。

        Args:
            filename: 文件绝对路径
            lineno: 目标行号（从1开始）

        Returns:
            (context_lines, target_idx) — 上下文行列表和目标行索引
        """
        lines = self._get_source_lines(filename)
        start = max(0, lineno - 3)
        end = min(len(lines), lineno + 2)
        context_lines = [l.rstrip() for l in lines[start:end]]
        target_idx = lineno - start - 1
        if target_idx < 0 or target_idx >= len(context_lines):
            target_idx = len(context_lines) // 2
        return context_lines, target_idx

    def start(self):
        """开始追踪。

        记录启动时间戳并注册全局 trace 函数。
        目标函数返回后自动卸载 settrace，避免 Tkinter 主循环开销。
        """
        self._start_time = time.time()
        sys.settrace(self.trace_func)
        # 禁止新创建的线程被追踪（避免 keyboard/tkinter 等库的后台线程导致 GIL 崩溃）
        threading.settrace(None)
        logger.debug("动态追踪已启动: 变量=%s (仅主线程)", self.variable_name)

    def stop(self):
        """停止追踪。

        注销全局 trace 函数，输出性能统计。
        """
        sys.settrace(None)
        sys.setprofile(None)

        # 处理最后一个 pending 行（模块级最后一个目标行可能没有下一个 line 事件）
        if self._pending_line and self._born:
            p = self._pending_line
            if p["found_before"]:
                self._record_event(
                    p["filename"], p["lineno"], p["code_line"],
                    p["context_lines"], p["target_idx"],
                    p["scope"], p["value_repr_before"], p["value_type"], "使用",
                )
            self._pending_line = None
        total_calls = self._call_count
        filtered_calls = self._call_filtered
        total_lines = self._line_count
        filtered_lines = self._line_filtered
        call_pass_rate = ((total_calls - filtered_calls) / total_calls * 100) if total_calls > 0 else 0
        line_pass_rate = ((total_lines - filtered_lines) / total_lines * 100) if total_lines > 0 else 0
        logger.info(
            "[TRACE_PERF] call事件: 总计=%d 过滤=%d (%.1f%%被拦截) | "
            "line事件: 总计=%d 进入_on_line=%d (%.1f%%被拦截) | "
            "目标文件数=%d 目标函数数=%d | 事件数=%d",
            total_calls, filtered_calls, (filtered_calls / total_calls * 100) if total_calls > 0 else 0,
            total_lines, total_lines - filtered_lines, (filtered_lines / total_lines * 100) if total_lines > 0 else 0,
            len(self._target_files), len(self.target_funcs or {}),
            len(self.events),
        )

    def get_result(self) -> DynamicResult:
        """获取追踪结果。

        汇总事件统计，构建 DynamicResult 对象。

        Returns:
            包含完整事件轨迹和统计摘要的 DynamicResult
        """
        end_time = time.time()
        birth_count = sum(1 for e in self.events if e.event_type == "诞生")
        assign_count = sum(1 for e in self.events if e.event_type == "赋值")
        use_count = sum(1 for e in self.events if e.event_type == "使用")
        death_count = sum(1 for e in self.events if e.event_type == "销毁")
        # 去重保序
        files = list(dict.fromkeys(e.file_path for e in self.events))

        start_str = ""
        if self._start_time is not None:
            start_str = datetime.fromtimestamp(self._start_time).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

        return DynamicResult(
            variable_name=self.variable_name,
            events=self.events,
            total_events=len(self.events),
            birth_count=birth_count,
            assign_count=assign_count,
            use_count=use_count,
            death_count=death_count,
            files_involved=files,
            start_time=start_str,
            end_time=datetime.fromtimestamp(end_time).strftime("%Y-%m-%d %H:%M:%S"),
            duration=round(end_time - self._start_time, 3)
            if self._start_time
            else 0.0,
        )


def run_tracer(
    target_script: str,
    variable_name: str,
    folder_path: str,
    output_path: str,
    run_args: list = None,
    target_lines: list = None,
) -> DynamicResult:
    """
    追踪代理入口：运行目标程序并追踪变量。

    此函数设计为在子进程中调用。主进程通过 subprocess 启动子进程，
    子进程调用此函数执行追踪，结果写入 JSON 文件，主进程读取 JSON。

    优化：target_lines 由主进程通过静态分析生成，只追踪变量出现的行。

    Args:
        target_script: 目标程序入口文件路径
        variable_name: 要追踪的变量名
        folder_path: 项目根目录（用于解析相对路径和添加 sys.path）
        output_path: 结果输出路径（JSON 文件）
        run_args: 传给目标程序的命令行参数（sys.argv）
        target_lines: 静态分析定位的变量出现位置列表，
                      格式 [[abs_file_path, line_no], ...]，
                      为 None 时追踪所有行

    Returns:
        DynamicResult 追踪结果对象
    """
    _setup_subprocess_logging()

    logger.info(
        "启动动态追踪: 脚本=%s | 变量=%s | 输出=%s | 目标行数=%s",
        target_script,
        variable_name,
        output_path,
        len(target_lines) if target_lines else "全部",
    )
    if target_lines:
        for item in target_lines[:5]:
            logger.info("[TARGET] 文件=%s 行=%d 函数=%s", item[0], item[1], item[2] if len(item) > 2 else "?")
        if len(target_lines) > 5:
            logger.info("[TARGET] ...共 %d 个目标位置", len(target_lines))

    # 设置 sys.argv（让目标程序的 argparse 等正常工作）
    sys.argv = [target_script] + (run_args or [])

    # 将项目根目录加入 sys.path（让目标程序的 import 正常工作）
    if folder_path and folder_path not in sys.path:
        sys.path.insert(0, folder_path)

    # 将 target_lines 列表转为集合（查找 O(1)）
    lines_set = None
    func_set = None
    if target_lines:
        lines_set = set()
        func_set = set()
        for item in target_lines:
            file_path, line = item[0], item[1]
            func_name = item[2] if len(item) > 2 else ""
            lines_set.add((file_path, line))
            if func_name:
                func_set.add(func_name)

    # 创建追踪器
    tracer = VariableTracer(variable_name, folder_path, target_lines=lines_set, target_funcs=func_set)

    # 启动心跳线程：每5秒输出一条日志，证明子进程还活着
    _heartbeat_running = True
    _heartbeat_count = [0]

    def _heartbeat_loop():
        import time as _time
        import sys as _sys
        while _heartbeat_running:
            _time.sleep(5)
            if not _heartbeat_running:
                break
            _heartbeat_count[0] += 1
            try:
                event_count = len(tracer.events)
                logger.info("[TRACE] 心跳 %ds: 事件=%d | call=%d(过滤=%d) line=%d(过滤=%d)",
                            _heartbeat_count[0] * 5, event_count,
                            tracer._call_count, tracer._call_filtered,
                            tracer._line_count, tracer._line_filtered)
                _sys.stderr.flush()
            except Exception as e:
                logger.error("[TRACE] 心跳异常: %s", e)
                _sys.stderr.flush()

    _heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
    _heartbeat_thread.start()
    logger.info("[TRACE] 心跳线程已启动")

    # watchdog 线程：检测 call 数是否停止增长（程序已关闭窗口/停止执行）
    # 原理：call 数连续 15 秒不变化 → Python 执行已停止 → 保存结果并退出
    _watchdog_running = [True]

    def _watchdog_loop():
        """检测 call 数停止增长后自动保存结果并退出"""
        import time as _wtime
        import sys as _wsys
        _wtime.sleep(10)  # 等目标程序充分启动
        _last_call = -1
        _dead_count = 0
        while _watchdog_running[0]:
            _wtime.sleep(5)
            if not _watchdog_running[0]:
                break
            try:
                current_call = tracer._call_count
                if current_call == _last_call:
                    _dead_count += 1
                    logger.info("[TRACE] watchdog: call=%d 未变化 (连续%d次)", current_call, _dead_count)
                    _wsys.stderr.flush()
                    if _dead_count >= 3:
                        # call 连续 15 秒不变化，判定程序已停止
                        logger.info("[TRACE] watchdog: 确认程序已停止，保存结果并退出")
                        _wsys.stderr.flush()
                        _watchdog_running[0] = False
                        _heartbeat_running = False
                        tracer.stop()
                        result = tracer.get_result()
                        result.error = error_msg
                        result_dict = {
                            "variable_name": result.variable_name,
                            "total_events": result.total_events,
                            "birth_count": result.birth_count,
                            "assign_count": result.assign_count,
                            "use_count": result.use_count,
                            "death_count": result.death_count,
                            "files_involved": result.files_involved,
                            "start_time": result.start_time,
                            "end_time": result.end_time,
                            "duration": result.duration,
                            "error": result.error,
                            "events": [asdict(e) for e in result.events],
                        }
                        out_dir = os.path.dirname(os.path.abspath(output_path))
                        if out_dir:
                            os.makedirs(out_dir, exist_ok=True)
                        with open(output_path, "w", encoding="utf-8") as f:
                            json.dump(result_dict, f, ensure_ascii=False, indent=2)
                        logger.info("[TRACE] watchdog: 结果已保存 (事件数=%d)，强制退出", result.total_events)
                        _wsys.stderr.flush()
                        os._exit(0)
                else:
                    _dead_count = 0
                    _last_call = current_call
            except Exception:
                pass

    _watchdog_thread = threading.Thread(target=_watchdog_loop, daemon=True)
    _watchdog_thread.start()
    logger.info("[TRACE] watchdog 线程已启动")

    # 开始追踪
    tracer.start()

    error_msg = ""
    try:
        # 运行目标程序（以 __main__ 模式执行）
        abs_script = os.path.abspath(target_script)
        runpy.run_path(abs_script, run_name="__main__")
    except SystemExit:
        # 程序调用 sys.exit()，视为正常退出
        pass
    except Exception:
        error_msg = traceback.format_exc()
        logger.error("目标程序执行出错:\n%s", error_msg)
    finally:
        # 停止心跳线程
        _heartbeat_running = False
        logger.info("[TRACE] 目标程序已退出，开始停止追踪...")
        tracer.stop()

    # 获取结果并保存
    logger.info("[TRACE] 正在汇总追踪结果...")
    result = tracer.get_result()
    result.error = error_msg

    # 序列化为 JSON
    logger.info("[TRACE] 正在序列化结果（事件数=%d）...", result.total_events)
    result_dict = {
        "variable_name": result.variable_name,
        "total_events": result.total_events,
        "birth_count": result.birth_count,
        "assign_count": result.assign_count,
        "use_count": result.use_count,
        "death_count": result.death_count,
        "files_involved": result.files_involved,
        "start_time": result.start_time,
        "end_time": result.end_time,
        "duration": result.duration,
        "error": result.error,
        "events": [asdict(e) for e in result.events],
    }

    # 确保输出目录存在
    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    logger.info("[TRACE] 正在写入结果文件: %s", output_path)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result_dict, f, ensure_ascii=False, indent=2)

    logger.info(
        "动态追踪完成: 变量=%s | 事件数=%d | 耗时=%.3fs | 输出=%s",
        variable_name,
        result.total_events,
        result.duration,
        output_path,
    )

    return result


def load_result(json_path: str) -> DynamicResult:
    """从 JSON 文件加载追踪结果。

    与 run_tracer 的输出配套使用：主进程从子进程生成的 JSON 文件
    重建 DynamicResult 对象。

    Args:
        json_path: JSON 文件路径

    Returns:
        重建的 DynamicResult 对象

    Raises:
        FileNotFoundError: 文件不存在
        json.JSONDecodeError: JSON 格式错误
        TypeError: 缺少必需字段或字段类型不匹配
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 从 JSON 重建事件列表
    events_data = data.pop("events", [])
    events = [DynamicEvent(**e) for e in events_data]

    return DynamicResult(**data, events=events)
