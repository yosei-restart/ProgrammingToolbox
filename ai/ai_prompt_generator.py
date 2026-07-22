"""
GUI 元素探查器 - AI 提示词生成器
将控件识别结果转换为可直接嵌入 AI 对话的结构化描述
"""

import json
from typing import Optional

from utils.logging_utils import get_logger

logger = get_logger(__name__)


# UI Automation Pattern 中文名称映射表
PATTERN_CN_MAP = {
    "InvokePattern": "可点击调用",
    "ValuePattern": "可读写值",
    "SelectionPattern": "可选择",
    "SelectionItemPattern": "可作为选择项",
    "TogglePattern": "可切换状态",
    "ExpandCollapsePattern": "可展开/折叠",
    "ScrollPattern": "可滚动",
    "TextPattern": "可文本操作",
    "WindowPattern": "窗口操作",
    "TransformPattern": "可移动/缩放",
    "GridPattern": "网格",
    "GridItemPattern": "网格项",
    "TablePattern": "表格",
    "TableItemPattern": "表格项",
    "RangeValuePattern": "范围值",
    "DockPattern": "可停靠",
    "MultipleViewPattern": "多视图",
    "VirtualizedItemPattern": "虚拟化项",
}


def generate_ai_prompt(
    result: dict,
    user_question: str = "",
) -> str:
    """
    生成 AI 友好的结构化提示词文本

    Args:
        result: inspector_engine.inspect_at() 的返回结果
        user_question: 用户自定义的问题描述

    Returns:
        可直接复制到 AI 对话中的提示词文本
    """
    if not result or "error" in result:
        return f"识别失败，请重试。错误: {result.get('error', '未知错误')}"

    logger.info("生成 AI 提示词: 控件=%s", result.get("control_info", {}).get("control_type", ""))
    info = result["control_info"]
    chain = result["parent_chain"]
    pos = info["position"]

    lines = []
    lines.append("我正在调试一个 GUI 界面问题，请帮我分析以下控件：")
    lines.append("")

    # 控件基本信息
    lines.append("【控件信息】")
    lines.append(f"- 控件类型: {info['control_type']}（{info['control_type_cn']}）")
    lines.append(f"- 类名: {info['class_name']}")
    lines.append(f"- 控件名称: \"{info['name']}\"")
    lines.append(f"- 自动化ID: {info['automation_id']}")
    lines.append(f"- UI框架: {info['framework_id']}")
    lines.append(f"- 所属进程: {info['process_name']} (PID: {info['process_id']})")
    lines.append(f"- 原生窗口句柄: {info['native_window_handle']}")

    if info.get("value"):
        lines.append(f"- 当前值: \"{info['value']}\"")
    lines.append("")

    # 位置和尺寸
    lines.append("【位置和尺寸】")
    lines.append(
        f"- 屏幕坐标: (x={pos['left']}, y={pos['top']})"
    )
    lines.append(f"- 控件尺寸: 宽{pos['width']}px, 高{pos['height']}px")
    lines.append(f"- 右下角坐标: (x={pos['right']}, y={pos['bottom']})")

    # 位置描述
    try:
        from mss import mss
        with mss() as sct:
            screen_w = sct.monitors[1]["width"]
            screen_h = sct.monitors[1]["height"]
    except Exception as e:
        logger.warning("获取屏幕分辨率失败: %s", e)
        screen_w, screen_h = 1920, 1080

    h_desc = "左侧" if pos["left"] < screen_w / 3 else ("右侧" if pos["left"] > screen_w * 2 / 3 else "中间")
    v_desc = "顶部" if pos["top"] < screen_h / 3 else ("底部" if pos["top"] > screen_h * 2 / 3 else "中部")
    lines.append(f"- 所在区域: 屏幕{v_desc}{h_desc}")
    lines.append("")

    # 控件层级
    lines.append("【控件层级】")
    if chain:
        for node in reversed(chain):
            indent = "  " * (len(chain) - node["depth"] - 1)
            marker = "  ← 当前控件" if node["depth"] == 0 else ""
            lines.append(
                f"{indent}└─ {node['control_type']} \"{node['name']}\""
                f" (类名: {node['class_name']}){marker}"
            )
    lines.append("")

    # 当前状态
    lines.append("【当前状态】")
    lines.append(f"- 启用: {'是' if info['is_enabled'] else '否'}")
    lines.append(f"- 可见: {'是' if info['is_visible'] else '否'}")
    lines.append(f"- 可键盘聚焦: {'是' if info['is_keyboard_focusable'] else '否'}")
    lines.append("")

    # 支持的交互模式
    if info.get("supported_patterns"):
        lines.append("【支持的交互模式】")
        for p in info["supported_patterns"]:
            cn = PATTERN_CN_MAP.get(p, p)
            lines.append(f"- {p}: {cn}")
        lines.append("")

    # 用户问题
    if user_question:
        lines.append("【我的问题】")
        lines.append(user_question)
    else:
        lines.append("【我的问题】")
        lines.append("请根据以上控件信息，帮我分析可能存在的界面问题。")

    return "\n".join(lines)


def generate_json_output(result: dict) -> str:
    """
    生成 JSON 格式的结构化数据

    Returns:
        格式化的 JSON 字符串
    """
    if not result or "error" in result:
        return json.dumps({"error": result.get("error", "未知错误")}, ensure_ascii=False, indent=2)

    info = result["control_info"]
    chain = result["parent_chain"]

    output = {
        "schema_version": "1.0",
        "element": {
            "control_type": info["control_type"],
            "control_type_cn": info["control_type_cn"],
            "class_name": info["class_name"],
            "name": info["name"],
            "automation_id": info["automation_id"],
            "state": {
                "enabled": info["is_enabled"],
                "visible": info["is_visible"],
                "focusable": info["is_keyboard_focusable"],
            },
            "geometry": {
                "x": info["position"]["left"],
                "y": info["position"]["top"],
                "width": info["position"]["width"],
                "height": info["position"]["height"],
            },
            "value": info.get("value"),
            "framework": info["framework_id"],
            "process": {
                "id": info["process_id"],
                "name": info["process_name"],
            },
            "supported_patterns": info.get("supported_patterns", []),
        },
        "parent_hierarchy": [
            {
                "level": node["depth"],
                "control_type": node["control_type"],
                "control_type_cn": node["control_type_cn"],
                "class_name": node["class_name"],
                "name": node["name"],
                "automation_id": node["automation_id"],
            }
            for node in chain
        ],
        "top_level_window": chain[-1]["name"] if chain else "",
    }

    return json.dumps(output, ensure_ascii=False, indent=2)