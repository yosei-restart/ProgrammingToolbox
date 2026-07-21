"""
GUI 元素探查器 - 核心识别引擎
使用 UIAutomation COM API 实现控件识别、属性提取、父级链追溯
"""

import uiautomation as auto
import psutil
import os
import ctypes
from typing import Optional

from utils.logging_utils import get_logger

logger = get_logger(__name__)

# Win32 API 用于跳过隐藏窗口
_user32 = ctypes.windll.user32


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def _window_from_point(x: int, y: int) -> int:
    """用 Win32 API 获取坐标处的窗口句柄（跳过隐藏窗口）

    WindowFromPoint 只返回可见窗口，不会返回被 ShowWindow(SW_HIDE) 隐藏的窗口。
    """
    pt = _POINT(x, y)
    hwnd = _user32.WindowFromPoint(pt)
    return hwnd


def _get_hwnd_pid(hwnd: int) -> int:
    """获取窗口句柄对应的进程 ID"""
    pid = ctypes.c_ulong()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _get_top_level_parent(hwnd: int) -> int:
    """获取窗口的顶层父窗口（跳过子窗口，找到真正的顶层窗口）

    WindowFromPoint 可能返回子窗口（如 CustomControl），但我们需要判断
    顶层窗口（Top-Level Window）是否属于自身进程。
    """
    if hwnd == 0:
        return 0
    # GetAncestor with GA_ROOT = 2 找到顶层窗口
    GA_ROOT = 2
    return _user32.GetAncestor(hwnd, GA_ROOT)


def _find_window_behind(x: int, y: int, skip_hwnd: int = 0) -> int:
    """用 EnumWindows 枚举所有顶层窗口，找到坐标处可见且不属于自身进程的窗口

    EnumWindows 按 Z-Order 顺序（从上到下）枚举所有顶层窗口，
    不受 TOPMOST 窗口层级限制。第一个匹配坐标的可见非自身窗口即为目标。
    相比 GetTopWindow+GetWindow，此方法能跨 TOPMOST 层级找到普通窗口。
    """
    import ctypes.wintypes

    own_pid = os.getpid()
    found = {"hwnd": 0, "pid": 0}

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

    def _enum_cb(hwnd, _lparam):
        if hwnd == skip_hwnd:
            return True
        if not _user32.IsWindowVisible(hwnd):
            return True
        if _user32.IsIconic(hwnd):
            return True
        rect = _RECT()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        if not (rect.left <= x <= rect.right and rect.top <= y <= rect.bottom):
            return True
        win_pid = _get_hwnd_pid(hwnd)
        if win_pid == own_pid:
            return True
        found["hwnd"] = hwnd
        found["pid"] = win_pid
        return False  # 找到，停止枚举

    _user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)

    if found["hwnd"]:
        logger.warning("[INSPECT] EnumWindows 找到背后窗口: hwnd=%d PID=%d", found["hwnd"], found["pid"])
    else:
        logger.warning("[INSPECT] EnumWindows 未找到坐标(%d,%d)处的非自身窗口", x, y)

    return found["hwnd"]


def get_process_name(pid: int) -> str:
    """根据 PID 获取进程名称"""
    try:
        proc = psutil.Process(pid)
        return proc.name()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return f"PID:{pid}"


CONTROL_TYPE_MAP = {
    "ButtonControl": "按钮",
    "EditControl": "文本输入框",
    "CheckBoxControl": "复选框",
    "RadioButtonControl": "单选按钮",
    "ComboBoxControl": "下拉选择框",
    "ListControl": "列表",
    "ListItemControl": "列表项",
    "MenuControl": "菜单",
    "MenuItemControl": "菜单项",
    "TabControl": "选项卡",
    "TabItemControl": "选项卡页",
    "TreeControl": "树形控件",
    "TreeItemControl": "树节点",
    "HyperlinkControl": "超链接",
    "TextControl": "静态文本",
    "ImageControl": "图片",
    "ProgressBarControl": "进度条",
    "ScrollBarControl": "滚动条",
    "SliderControl": "滑块",
    "TitleBarControl": "标题栏",
    "WindowControl": "窗口",
    "ToolTipControl": "提示框",
    "DataGridControl": "数据表格",
    "GroupControl": "分组容器",
    "PaneControl": "面板容器",
    "SplitButtonControl": "拆分按钮",
    "StatusBarControl": "状态栏",
    "ToolBarControl": "工具栏",
    "SpinnerControl": "数值调节器",
    "ThumbControl": "滚动滑块",
    "CalendarControl": "日历",
    "DocumentControl": "文档",
    "HeaderControl": "表头",
    "HeaderItemControl": "表头项",
    "SeparatorControl": "分隔符",
    "SemanticZoomControl": "缩放控件",
    "DataItemControl": "数据项",
    "CustomControl": "自定义控件",
}


def get_control_type_cn(control_type_name: str) -> str:
    """将控件类型名映射为中文描述"""
    return CONTROL_TYPE_MAP.get(control_type_name, "未知控件类型")


def extract_control_info(control: auto.Control) -> dict:
    """提取单个控件的完整属性信息"""
    try:
        rect = control.BoundingRectangle
    except Exception:
        rect = auto.Rect(0, 0, 0, 0)

    info = {
        "control_type": control.ControlTypeName,
        "control_type_cn": get_control_type_cn(control.ControlTypeName),
        "class_name": control.ClassName or "(无)",
        "name": control.Name or "(无)",
        "automation_id": control.AutomationId or "(无)",
        "position": {
            "left": rect.left,
            "top": rect.top,
            "right": rect.right,
            "bottom": rect.bottom,
            "width": rect.width(),
            "height": rect.height(),
        },
        "is_enabled": control.IsEnabled,
        "is_visible": not control.IsOffscreen,
        "is_keyboard_focusable": control.IsKeyboardFocusable,
        "process_id": control.ProcessId,
        "process_name": get_process_name(control.ProcessId),
        "framework_id": control.FrameworkId or "(未知)",
        "native_window_handle": control.NativeWindowHandle,
        "supported_patterns": [],
        "value": None,
    }

    # 获取支持的交互模式
    if hasattr(control, "GetSupportedPatterns"):
        try:
            patterns = control.GetSupportedPatterns()
            info["supported_patterns"] = [p.__class__.__name__ for p in patterns]
        except Exception:
            pass  # 部分控件类型不支持此方法，忽略

    # 尝试获取文本值
    try:
        value_pattern = control.GetPattern(auto.PatternId.ValuePattern)
        if value_pattern:
            info["value"] = value_pattern.Value
    except Exception as e:
        logger.warning("获取值模式失败: %s", e)

    return info


MAX_PARENT_DEPTH = 30


def get_parent_chain(control: auto.Control, max_depth: int = MAX_PARENT_DEPTH) -> list:
    """从当前控件向上遍历获取完整的父级层级链"""
    chain = []
    current = control
    depth = 0

    while current and depth < max_depth:
        try:
            node_info = {
                "depth": depth,
                "control_type": current.ControlTypeName,
                "control_type_cn": get_control_type_cn(current.ControlTypeName),
                "class_name": current.ClassName or "(无)",
                "name": current.Name or "(无)",
                "automation_id": current.AutomationId or "(无)",
            }
            chain.append(node_info)
            current = current.GetParentControl()
            depth += 1
        except Exception as e:
            logger.warning("遍历父级链在第 %d 层中断: %s", depth, e)
            break

    return chain


def _is_own_control(control: auto.Control) -> bool:
    """
    判断控件是否属于自身进程

    检查：
    1. 控件的进程ID是否与当前进程相同
    2. 控件或其父级链中是否包含自身窗口标题关键词
    """
    own_pid = os.getpid()

    try:
        ctrl_pid = control.ProcessId
        if ctrl_pid == own_pid:
            logger.info("[OWN_FILTER] 控件进程ID=%d 与自身PID=%d 相同", ctrl_pid, own_pid)
            return True
    except Exception as e:
        logger.warning("[OWN_FILTER] 获取控件进程ID失败: %s", e)

    try:
        name = control.Name or ""
        ctrl_type = control.ControlTypeName or ""
        if name and ("GUI Element Inspector" in name or "辅助编程" in name):
            logger.info("[OWN_FILTER] 控件名称='%s' 类型='%s' 包含自身关键词", name, ctrl_type)
            return True
    except Exception:
        pass

    try:
        current = control
        for depth in range(10):
            parent = current.GetParentControl()
            if not parent:
                break
            try:
                parent_pid = parent.ProcessId
                parent_name = parent.Name or ""
                parent_type = parent.ControlTypeName or ""
                if parent_pid == own_pid:
                    logger.info("[OWN_FILTER] 父级第%d层 PID=%d 与自身相同 | 类型=%s 名称='%s'", depth+1, parent_pid, parent_type, parent_name)
                    return True
                if parent_name and ("GUI Element Inspector" in parent_name or "辅助编程" in parent_name):
                    logger.info("[OWN_FILTER] 父级第%d层 名称='%s' 包含自身关键词", depth+1, parent_name)
                    return True
            except Exception:
                pass
            current = parent
    except Exception:
        pass

    return False


def inspect_at(x: int, y: int) -> Optional[dict]:
    """
    核心方法：检查指定屏幕坐标的控件

    返回完整的结果字典，包含控件信息、父级链等
    如果无法识别控件，返回 None
    """
    logger.warning("[INSPECT] 开始检查坐标 (%d, %d)", x, y)

    try:
        control = auto.ControlFromPoint(x, y)
    except Exception as e:
        logger.error("[INSPECT] ControlFromPoint 失败 (%d, %d): %s", x, y, e)
        return None

    if control is None:
        logger.warning("[INSPECT] ControlFromPoint 返回 None — 坐标(%d, %d)处无控件", x, y)
        return None

    try:
        ctrl_type = control.ControlTypeName or "(未知)"
        ctrl_name = control.Name or "(无)"
        ctrl_pid = control.ProcessId
        logger.warning("[INSPECT] ControlFromPoint 成功: 类型=%s 名称='%s' PID=%d", ctrl_type, ctrl_name, ctrl_pid)
    except Exception:
        pass

    if _is_own_control(control):
        logger.warning("[INSPECT] 判定为自身控件（UIAutomation 识别到隐藏窗口中的控件），尝试用 Win32 API 找到真正可见的窗口")
        # 用 Win32 API 找到坐标处真正可见的窗口（跳过隐藏窗口）
        pt = _POINT(x, y)
        hwnd = _user32.WindowFromPoint(pt)
        if hwnd == 0:
            logger.warning("[INSPECT] WindowFromPoint 也返回 0 — 坐标处确实无可拾取控件")
            return None

        own_pid = os.getpid()
        win_pid = _get_hwnd_pid(hwnd)
        logger.warning("[INSPECT] WindowFromPoint 返回 hwnd=%d PID=%d (自身PID=%d)", hwnd, win_pid, own_pid)

        if win_pid == own_pid:
            # 获取顶层父窗口来判断是否真的是自身进程
            top_hwnd = _get_top_level_parent(hwnd)
            top_pid = _get_hwnd_pid(top_hwnd) if top_hwnd != 0 else 0
            logger.warning("[INSPECT] 子窗口的顶层父窗口 hwnd=%d PID=%d", top_hwnd, top_pid)

            if top_pid == own_pid:
                logger.warning("[INSPECT] 顶层父窗口也属于自身进程，遍历 Z-Order 找背后的窗口")
                # 遍历 Z-Order，跳过自身窗口，找到坐标处可见的非自身窗口
                behind_hwnd = _find_window_behind(x, y, skip_hwnd=top_hwnd)
                if behind_hwnd == 0:
                    logger.warning("[INSPECT] 无法找到背后的窗口，放弃拾取")
                    return None
                behind_pid = _get_hwnd_pid(behind_hwnd)
                logger.warning("[INSPECT] 背后窗口 hwnd=%d PID=%d", behind_hwnd, behind_pid)
                hwnd = behind_hwnd
                win_pid = behind_pid

        # 用 UIAutomation 从 Win32 窗口句柄重新获取控件
        try:
            control = auto.ControlFromHandle(hwnd)
            if control is None:
                logger.warning("[INSPECT] ControlFromHandle 返回 None — 无法从 hwnd 获取 UIAutomation 控件")
                return None
            ctrl_type2 = control.ControlTypeName or "(未知)"
            ctrl_name2 = control.Name or "(无)"
            logger.warning("[INSPECT] 通过 Win32 窗口重新获取控件成功: 类型=%s 名称='%s' PID=%d", ctrl_type2, ctrl_name2, win_pid)
        except Exception as e:
            logger.error("[INSPECT] ControlFromHandle 失败: %s", e)
            return None

    try:
        control_info = extract_control_info(control)
        logger.warning("[INSPECT] 控件信息提取成功: %s '%s'", control_info.get('control_type', ''), control_info.get('name', ''))
    except Exception as e:
        logger.error("[INSPECT] 提取控件属性失败: %s", e)
        return {"error": f"提取控件属性失败: {str(e)}"}

    try:
        parent_chain = get_parent_chain(control)
    except Exception as e:
        logger.warning("[INSPECT] 获取父级链失败: %s", e)
        parent_chain = []

    logger.warning("[INSPECT] 识别完成: %s '%s' PID=%d", control_info.get('control_type'), control_info.get('name'), control_info.get('process_id'))
    return {
        "control_info": control_info,
        "parent_chain": parent_chain,
        "click_position": {"x": x, "y": y},
    }


def get_control_summary(result: dict) -> str:
    """生成控件识别的简要摘要"""
    if not result or "error" in result:
        return f"识别失败: {result.get('error', '未知错误')}"

    info = result["control_info"]
    chain = result["parent_chain"]

    lines = []
    lines.append(f"控件类型: {info['control_type']} ({info['control_type_cn']})")
    lines.append(f"类名: {info['class_name']}")
    lines.append(f"名称: {info['name']}")
    lines.append(
        f"位置: ({info['position']['left']}, {info['position']['top']}) "
        f"尺寸: {info['position']['width']}x{info['position']['height']}"
    )
    lines.append(f"所属进程: {info['process_name']} (PID: {info['process_id']})")
    lines.append(f"UI框架: {info['framework_id']}")

    if chain:
        lines.append(f"\n控件层级 (共 {len(chain)} 层):")
        for node in reversed(chain):
            indent = "  " * (len(chain) - node["depth"] - 1)
            marker = " ◀ 当前控件" if node["depth"] == 0 else ""
            lines.append(
                f"{indent}└─ {node['control_type']} \"{node['name']}\"{marker}"
            )

    return "\n".join(lines)