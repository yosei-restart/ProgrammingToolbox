"""
GUI 元素探查器 - 变量生命周期 HTML 报告导出模块

将 LifecycleResult 导出为完全自包含的 HTML 文件（CSS 内联，暗色 Catppuccin Mocha 主题），
可直接在浏览器中打开、打印，不依赖任何第三方库。

特性：
- 纯 Python 字符串模板生成 HTML，零第三方依赖
- 暗色主题，与桌面应用配色一致（背景 #1E1E2E）
- 事件卡片横向排列、自动换行，箭头连接符串联生命周期
- 轻量级 Python 语法高亮（关键字/字符串/数字/注释）
- 打印友好（@media print）
- UTF-8 编码保存

依赖：
- lifecycle_tracer.LifecycleResult / VariableEvent / EventType
- logging_utils.get_logger
"""

from __future__ import annotations

import colorsys
import html
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from utils.logging_utils import get_logger

logger = get_logger(__name__)

# 尝试导入生命周期追踪数据结构。
# 当 lifecycle_tracer 尚未实现时降级，保证本模块可独立导入与编译。
try:
    from core.lifecycle_tracer import EventType, LifecycleResult, VariableEvent  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - lifecycle_tracer 尚未实现时的降级保护
    LifecycleResult = None  # type: ignore[assignment, misc]
    VariableEvent = None  # type: ignore[assignment, misc]

    from enum import Enum as _Enum

    class EventType(_Enum):  # type: ignore[no-redef]
        """生命周期事件类型枚举（降级占位，成员名/值与正式版一致）。"""

        BIRTH = "诞生"
        ASSIGN = "赋值"
        AUG_ASSIGN = "增量赋值"
        USE = "使用"
        PARAM = "参数"
        IMPORT = "导入"
        FOR_LOOP = "循环变量"
        WITH_AS = "上下文管理"
        DEL = "销毁"
        RETURN = "返回"
        ARG_PASS = "传参"


__all__ = ["export_lifecycle_html"]


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 事件类型元信息：规范化名称 -> (中文标签, 主题色)
# 颜色取自 Catppuccin Mocha 调色板，与需求文档一致。
_EVENT_META: Dict[str, Tuple[str, str]] = {
    "BIRTH": ("诞生", "#A6E3A1"),
    "ASSIGN": ("赋值", "#89B4FA"),
    "AUG_ASSIGN": ("增量赋值", "#74C7EC"),
    "USE": ("使用", "#6C7086"),
    "PARAM": ("参数", "#CBA6F7"),
    "IMPORT": ("导入", "#FAB387"),
    "FOR_LOOP": ("循环变量", "#F9E2AF"),
    "WITH_AS": ("上下文管理", "#FAB387"),
    "DEL": ("销毁", "#F38BA8"),
    "RETURN": ("返回", "#89B4FA"),
    "ARG_PASS": ("传参", "#6C7086"),
}


def _generate_gradient_color(index: int, total: int) -> str:
    """
    根据事件在生命周期中的位置，生成渐变色。

    从绿色（诞生，hue=0.35）渐变到红色（消亡，hue=0.95），
    与桌面 UI 的渐变色逻辑一致。

    Args:
        index: 事件序号（从 1 开始）
        total: 事件总数

    Returns:
        hex 颜色字符串，如 "#3FB950"
    """
    if total <= 1:
        return "#3FB950"
    ratio = (index - 1) / (total - 1)
    start_hue = 0.35   # 绿色
    end_hue = 0.95     # 红色
    hue = start_hue + (end_hue - start_hue) * ratio
    rgb = colorsys.hsv_to_rgb(hue % 1.0, 0.65, 0.85)
    return "#{:02X}{:02X}{:02X}".format(
        int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255)
    )

# Python 关键字集合（用于轻量语法高亮）
_PY_KEYWORDS = {
    "False", "None", "True", "and", "as", "assert", "async", "await",
    "break", "class", "continue", "def", "del", "elif", "else", "except",
    "finally", "for", "from", "global", "if", "import", "in", "is",
    "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try",
    "while", "with", "yield",
}

# 常见内建函数（高亮为黄色，增强可读性）
_PY_BUILTINS = {
    "print", "len", "range", "str", "int", "float", "list", "dict", "set",
    "tuple", "bool", "open", "isinstance", "issubclass", "getattr",
    "setattr", "hasattr", "delattr", "enumerate", "zip", "map", "filter",
    "sorted", "reversed", "sum", "min", "max", "abs", "type", "super",
    "property", "staticmethod", "classmethod", "iter", "next", "id",
    "repr", "format", "input", "any", "all", "vars", "dir", "globals",
    "locals", "round", "bin", "hex", "oct", "ord", "chr", "bytes",
}

# 轻量语法高亮分词器：注释 / 字符串 / 数字 / 标识符 / 其他
_TOKEN_RE = re.compile(
    r"(?P<comment>\#[^\n]*)"
    r"|(?P<string>(?:[rRbBuUfF]{1,2})?"
    r"(?:\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'))"
    r"|(?P<number>\b\d+\.?\d*(?:[eE][+-]?\d+)?\b)"
    r"|(?P<name>[A-Za-z_]\w*)"
    r"|(?P<other>\s+|.)",
    re.DOTALL,
)

# 卡片之间的箭头连接符（Unicode →）
_ARROW = '<span class="arrow" aria-hidden="true">\u2192</span>'


# ---------------------------------------------------------------------------
# 内部工具函数
# ---------------------------------------------------------------------------

def _esc(value: Any) -> str:
    """
    HTML 转义文本，防止 XSS 与结构破坏。

    Args:
        value: 任意可被 str() 转换的值

    Returns:
        转义后的字符串（< > & " ' 均已转义）
    """
    return html.escape(str(value), quote=True)


def _as_list(value: Any) -> List[Any]:
    """将单个值或序列统一转为列表。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _first_attr(obj: Any, names: Sequence[str], default: Any = None) -> Any:
    """
    按优先级尝试多个属性名，返回第一个非空的值。

    同时兼容对象属性访问与字典键访问，提升对不同 LifecycleResult /
    VariableEvent 实现的鲁棒性。

    Args:
        obj: 数据对象或字典
        names: 候选属性名列表（按优先级排序）
        default: 全部缺失时的默认值

    Returns:
        第一个命中的非空属性值，或 default
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        for n in names:
            if n in obj and obj[n] is not None:
                return obj[n]
        return default
    for n in names:
        val = getattr(obj, n, None)
        if val is not None:
            return val
    return default


def _event_type_name(event_type: Any) -> str:
    """
    从事件类型中提取规范化名称字符串。

    兼容枚举成员（取 .name）、字符串、以及带 value 的对象。

    Args:
        event_type: 事件类型（枚举成员或字符串）

    Returns:
        规范化名称（大写字符串），无法识别时返回空串
    """
    if event_type is None:
        return ""
    if isinstance(event_type, str):
        return event_type
    name = getattr(event_type, "name", None)
    if name:
        return str(name)
    val = getattr(event_type, "value", None)
    if val is not None:
        return str(val)
    return str(event_type)


def _event_meta(event_type: Any) -> Tuple[str, str]:
    """
    获取事件类型的中文标签与主题色。

    标签优先取枚举自身的 value（lifecycle_tracer 已将 value 定义为中文），
    其次查 _EVENT_META，最后回退到名称本身。

    Args:
        event_type: 事件类型（枚举成员或字符串）

    Returns:
        (中文标签, 颜色十六进制) 元组；未知类型返回 (名称, 灰色)
    """
    name = _event_type_name(event_type).upper()
    label, color = _EVENT_META.get(name, ("", "#6C7086"))
    enum_value = getattr(event_type, "value", None)
    if isinstance(enum_value, str) and enum_value:
        label = enum_value
    if not label:
        raw = _event_type_name(event_type)
        label = raw if raw else "未知"
    return (label, color)


def _highlight_python(code: str) -> str:
    """
    对 Python 代码做轻量语法高亮（关键字/字符串/数字/注释/内建函数）。

    采用“先分词、逐段转义再包裹 span”的策略，保证不会破坏 HTML 结构，
    且无需任何第三方库。

    Args:
        code: 原始代码字符串（可为多行）

    Returns:
        带 <span> 标签的 HTML 片段
    """
    if not code:
        return ""
    out: List[str] = []
    for m in _TOKEN_RE.finditer(code):
        kind = m.lastgroup
        text = m.group()
        esc = _esc(text)
        if kind == "comment":
            out.append(f'<span class="t-cm">{esc}</span>')
        elif kind == "string":
            out.append(f'<span class="t-str">{esc}</span>')
        elif kind == "number":
            out.append(f'<span class="t-num">{esc}</span>')
        elif kind == "name":
            if text in _PY_KEYWORDS:
                out.append(f'<span class="t-kw">{esc}</span>')
            elif text in _PY_BUILTINS:
                out.append(f'<span class="t-bi">{esc}</span>')
            else:
                out.append(esc)
        else:
            out.append(esc)
    return "".join(out)


def _format_context(ctx_val: Any, center_text: Any = None, target_idx: int = -1) -> str:
    """
    格式化上下文代码块（前后 2 行）。

    兼容多种存储形式：
    - dict: {"before": [...], "after": [...], "line"/"code": "<中心行>"}
    - list/tuple: 逐行文本（lifecycle_tracer 的 context_lines 即此形式）
    - str: 整段文本

    对于 list/tuple 形式，若提供 center_text（事件源代码行），则将与之匹配的
    上下文行高亮为中心行，便于定位。

    Args:
        ctx_val: 上下文数据
        center_text: 事件源代码行文本，用于在列表上下文中定位中心行（可选）

    Returns:
        HTML 片段；无内容时返回空串
    """
    entries: List[Tuple[str, bool]] = []  # (text, is_center)
    center_norm = (str(center_text) if center_text is not None else "").strip()

    if ctx_val is None:
        return ""

    if isinstance(ctx_val, dict):
        before = _as_list(ctx_val.get("before") or ctx_val.get("context_before"))
        after = _as_list(ctx_val.get("after") or ctx_val.get("context_after"))
        center = ctx_val.get("line") or ctx_val.get("code") or ctx_val.get("center")
        for b in before:
            entries.append((str(b), False))
        if center is not None:
            entries.append((str(center), True))
        for a in after:
            entries.append((str(a), False))
    elif isinstance(ctx_val, (list, tuple)):
        ctx_list = list(ctx_val)
        # 使用传入的 target_idx，如果没传则用中间行
        if target_idx < 0 or target_idx >= len(ctx_list):
            target_idx = len(ctx_list) // 2
        for i, x in enumerate(ctx_val):
            s = str(x)
            is_center = (i == target_idx) or (bool(center_norm) and s.strip() == center_norm)
            entries.append((s, is_center))
    else:
        entries.append((str(ctx_val), False))

    if not entries:
        return ""

    parts: List[str] = []
    for text, is_center in entries:
        cls = "ctx-line ctx-center" if is_center else "ctx-line"
        parts.append(f'<span class="{cls}">{_esc(text)}</span>')
    return f'<div class="context"><div class="ctx-inner">{"".join(parts)}</div></div>'


# ---------------------------------------------------------------------------
# HTML 片段构建
# ---------------------------------------------------------------------------

def _build_header(
    var_name: str, total: int, files: Sequence[str], gen_time: str
) -> str:
    """构建报告头部信息块。"""
    files_count = len(files)
    return (
        '<header class="header">'
        '<h1>变量生命周期追踪报告</h1>'
        '<div class="meta">'
        f'<span><em>变量名:</em> <strong>{_esc(var_name)}</strong></span>'
        f'<span><em>总事件:</em> <strong>{total}</strong></span>'
        f'<span><em>文件:</em> <strong>{files_count} 个</strong></span>'
        f'<span><em>生成时间:</em> <strong>{_esc(gen_time)}</strong></span>'
        '</div>'
        '</header>'
    )


def _build_card(event: Any, index: int, total: int) -> str:
    """
    构建单个事件卡片 HTML。

    Args:
        event: VariableEvent 对象
        index: 事件序号（从 1 开始）
        total: 事件总数

    Returns:
        卡片 HTML 片段
    """
    et = _first_attr(event, ["event_type", "type", "kind"], default=None)
    label, _ = _event_meta(et)
    # 使用渐变色替代固定事件类型颜色，从绿到红表示进度递进
    color = _generate_gradient_color(index, total)

    file_val = _first_attr(
        event, ["file_name", "file_path", "file", "filename", "path"],
        default="未知文件",
    )
    line_val = _first_attr(
        event, ["line", "lineno", "line_number"], default=0
    )
    scope_val = _first_attr(
        event, ["scope", "scope_name", "scope_path"], default="<全局>"
    )
    code_val = _first_attr(
        event,
        ["code_line", "code", "code_snippet", "source", "source_line", "source_code"],
        default="",
    )
    ctx_val = _first_attr(
        event,
        ["context", "context_lines", "surrounding_lines", "context_code"],
        default=None,
    )
    type_inferred = _first_attr(
        event, ["type_inferred", "inferred_type", "type"], default=""
    )
    type_desc = _first_attr(
        event, ["type_description", "type_desc"], default=""
    )
    detail_val = _first_attr(
        event, ["detail", "description", "desc"], default=""
    )

    fname = os.path.basename(str(file_val)) if file_val else "未知文件"
    loc = f"{fname}:{line_val}"

    code_html = _highlight_python(str(code_val)) if code_val else (
        '<span class="t-cm">&lt;无代码片段&gt;</span>'
    )
    target_idx_val = _first_attr(event, ["target_idx"], default=-1)
    ctx_html = _format_context(ctx_val, center_text=str(code_val), target_idx=target_idx_val)

    # 类型推断行（始终显示）
    type_str = str(type_inferred) if type_inferred else "未知"
    type_d = str(type_desc) if type_desc else "无法静态推断"
    type_html = (
        f'<div class="type-info">变量类型: {_esc(type_str)}（{_esc(type_d)}）</div>'
    )

    # 详情行
    detail_html = ""
    if detail_val:
        detail_html = (
            f'<div class="detail">详情（此事件的详细说明）: {_esc(str(detail_val))}</div>'
        )

    return (
        f'<div class="event-card" style="--accent:{color}">'
        '<div class="top-bar"></div>'
        '<div class="card-body">'
        f'<span class="type-label">{_esc(label)}'
        f'<em class="idx">#{index}</em></span>'
        f'<div class="location">文件（变量所在文件）: {_esc(loc)}</div>'
        f'<div class="scope">作用域（变量所属范围）: {_esc(str(scope_val))}</div>'
        f'{type_html}'
        f'{detail_html}'
        f'<div class="code-label">代码片段（变量所在代码行）:</div>'
        f'<div class="code">{code_html}</div>'
        f'{ctx_html}'
        '</div>'
        '</div>'
    )


def _build_summary(
    type_counts: Dict[str, int],
    type_order: List[str],
    total: int,
    files: Sequence[str],
) -> str:
    """构建统计摘要块。"""
    items: List[str] = []
    items.append(
        '<div class="stat-item total">'
        f'<span class="num">{total}</span>'
        '<span class="lbl">总事件</span>'
        '</div>'
    )
    for name in type_order:
        label, color = _event_meta(name)
        cnt = type_counts[name]
        items.append(
            '<div class="stat-item">'
            f'<span class="dot" style="background:{color}"></span>'
            f'<span class="num">{cnt}</span>'
            f'<span class="lbl">{_esc(label)}</span>'
            '</div>'
        )

    files_html = ""
    if files:
        file_items = "".join(f"<li>{_esc(f)}</li>" for f in files)
        files_html = (
            '<div class="file-list">'
            '<div class="lbl">涉及文件</div>'
            f'<ul>{file_items}</ul>'
            '</div>'
        )

    return (
        '<section class="summary">'
        '<h2>事件统计</h2>'
        f'<div class="stats">{"".join(items)}</div>'
        f'{files_html}'
        '</section>'
    )


# ---------------------------------------------------------------------------
# 内联 CSS（Catppuccin Mocha 暗色主题）
# ---------------------------------------------------------------------------

_CSS = """\
:root{
  --bg:#1E1E2E;
  --panel:#181825;
  --panel2:#11111B;
  --text:#CDD6F4;
  --dim:#6C7086;
  --border:#313244;
}
*{box-sizing:border-box;margin:0;padding:0;}
html,body{background:var(--bg);color:var(--text);}
body{
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",Roboto,sans-serif;
  padding:24px;line-height:1.6;font-size:14px;
}
.header{
  background:var(--panel);border:1px solid var(--border);
  border-radius:12px;padding:20px 24px;margin-bottom:24px;
}
.header h1{font-size:20px;margin-bottom:12px;font-weight:700;letter-spacing:.5px;}
.header .meta{display:flex;flex-wrap:wrap;gap:8px 20px;font-size:12px;color:var(--dim);}
.header .meta em{font-style:normal;color:var(--dim);}
.header .meta strong{color:var(--text);font-weight:600;}
.event-chain{
  display:flex;flex-wrap:wrap;align-items:stretch;
  gap:12px;margin-bottom:24px;
}
.event-card{
  --accent:#6C7086;
  background:var(--panel);border:1px solid var(--border);
  border-radius:10px;min-width:280px;max-width:380px;
  flex:1 1 280px;overflow:hidden;position:relative;
  box-shadow:0 4px 12px rgba(0,0,0,.30);
  transition:transform .15s ease,box-shadow .15s ease,border-color .15s ease;
}
.event-card:hover{
  transform:translateY(-2px);
  box-shadow:0 10px 24px rgba(0,0,0,.45);
  border-color:var(--accent);
}
.event-card .top-bar{height:4px;width:100%;background:var(--accent);}
.event-card .card-body{padding:14px 16px;}
.event-card .type-label{
  display:inline-flex;align-items:center;gap:6px;
  font-size:12px;font-weight:700;padding:3px 10px;
  border-radius:6px;margin-bottom:10px;
  background:var(--accent);color:#1E1E2E;
}
.event-card .type-label .idx{font-style:normal;opacity:.7;font-weight:600;}
.event-card .location{
  font-family:Consolas,"Courier New",monospace;font-size:12px;
  color:var(--dim);margin-bottom:4px;
}
.event-card .scope{font-size:12px;color:var(--dim);margin-bottom:4px;}
.event-card .type-info{
  font-size:12px;font-weight:bold;color:#0d1117;
  margin-bottom:4px;padding:3px 8px;
  background:#d29922;border-radius:4px;
  display:inline-block;
}
.event-card .detail{
  font-size:12px;color:var(--dim);margin-bottom:8px;
}
.event-card .code-label{
  font-size:11px;color:var(--dim);margin-bottom:2px;
}
.event-card .code{
  background:rgba(210,153,34,0.15);border:1px solid #d29922;
  border-radius:6px;padding:10px 12px;
  font-family:Consolas,"Courier New",monospace;font-size:12.5px;
  color:var(--text);white-space:pre;overflow-x:auto;margin-bottom:8px;
}
.event-card .context{
  background:rgba(108,112,134,.10);border:1px solid var(--border);
  border-radius:6px;padding:0;
  font-family:Consolas,"Courier New",monospace;font-size:11px;
  color:var(--dim);overflow-x:auto;
}
.event-card .context .ctx-inner{
  display:inline-block;min-width:100%;box-sizing:border-box;
  padding:8px 12px;
}
.event-card .context .ctx-line{display:block;white-space:pre;}
.event-card .context .ctx-center{
  color:#0d1117;background:#d29922;
  margin:0 -12px;padding:0 12px;font-weight:bold;
  border-radius:3px;
  display:block;
}
.arrow{
  align-self:center;color:var(--dim);font-size:18px;
  flex:0 0 auto;padding:0 2px;user-select:none;
}
.empty{
  background:var(--panel);border:1px dashed var(--border);
  border-radius:10px;padding:32px;text-align:center;color:var(--dim);
}
.summary{
  background:var(--panel);border:1px solid var(--border);
  border-radius:12px;padding:20px 24px;
}
.summary h2{font-size:16px;font-weight:700;margin-bottom:14px;}
.summary .stats{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px;}
.stat-item{
  display:inline-flex;align-items:center;gap:8px;
  background:var(--bg);border:1px solid var(--border);
  border-radius:8px;padding:8px 14px;font-size:13px;
}
.stat-item .dot{width:10px;height:10px;border-radius:50%;display:inline-block;}
.stat-item .num{font-weight:700;font-size:16px;}
.stat-item .lbl{color:var(--dim);font-size:12px;}
.stat-item.total{border-color:var(--text);}
.summary .file-list .lbl{color:var(--dim);font-size:12px;margin-bottom:6px;}
.summary .file-list ul{list-style:none;display:flex;flex-direction:column;gap:4px;}
.summary .file-list li{
  font-family:Consolas,"Courier New",monospace;font-size:12px;color:var(--text);
  background:var(--bg);border:1px solid var(--border);border-radius:6px;
  padding:6px 10px;word-break:break-all;
}
/* 轻量语法高亮 token 颜色 */
.t-kw{color:#CBA6F7;}
.t-str{color:#A6E3A1;}
.t-num{color:#FAB387;}
.t-cm{color:#6C7086;font-style:italic;}
.t-bi{color:#F9E2AF;}
@media print{
  body{background:#fff;color:#000;padding:0;font-size:12px;}
  .header,.summary,.event-card,.stat-item,.file-list li{
    background:#fff;border-color:#ccc;color:#000;
  }
  .header .meta,.header .meta em,.stat-item .lbl,.summary .file-list .lbl{
    color:#555;
  }
  .event-card{box-shadow:none;break-inside:avoid;}
  .arrow{display:none;}
  .event-card .code,.event-card .context{background:#f5f5f5;color:#222;border-color:#ddd;}
  .event-card .context .ctx-center{background:#d29922;color:#0d1117;}
  .t-cm{color:#888;}
  .t-kw,.t-str,.t-num,.t-bi{color:#333;}
}
"""


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def export_lifecycle_html(result: "LifecycleResult", output_path: str) -> str:
    """
    将变量生命周期结果导出为自包含的 HTML 文件。

    生成的 HTML 文件 CSS 全部内联，无外部资源依赖，可直接在浏览器打开或打印。
    采用 Catppuccin Mocha 暗色主题，与桌面应用配色一致。

    Args:
        result: LifecycleResult 对象（从 lifecycle_tracer 模块导入），
                需包含变量名、事件列表等属性
        output_path: 输出文件路径（.html）

    Returns:
        生成的 HTML 文件路径（即 output_path）

    Raises:
        ValueError: result 为 None 时抛出
        OSError: 文件写入失败时抛出
    """
    if result is None:
        raise ValueError("result 不能为 None")

    # 提取基础信息（兼容多种属性命名）
    var_name = _first_attr(
        result, ["variable_name", "var_name", "name", "variable"],
        default="<未知变量>",
    )
    events_raw = _first_attr(
        result, ["events", "event_list", "lifecycle"], default=[]
    )
    events: List[Any] = list(events_raw) if events_raw else []

    files = _first_attr(
        result, ["files_involved", "files", "file_list", "file_paths"],
        default=None,
    )
    # 若 result 未提供文件列表，则从事件中派生
    if not files:
        seen: List[str] = []
        for ev in events:
            f = _first_attr(
                ev, ["file_name", "file_path", "file", "filename", "path"],
                default=None,
            )
            if f and f not in seen:
                seen.append(f)
        files = seen
    files = list(files) if files else []

    total = len(events)
    gen_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 统计各事件类型数量（保持首次出现顺序）
    type_counts: Dict[str, int] = {}
    type_order: List[str] = []
    for ev in events:
        et = _first_attr(ev, ["event_type", "type", "kind"], default=None)
        name = _event_type_name(et)
        if name not in type_counts:
            type_counts[name] = 0
            type_order.append(name)
        type_counts[name] += 1

    # 构建 HTML 各部分
    header_html = _build_header(str(var_name), total, files, gen_time)

    if events:
        cards = [_build_card(ev, i + 1, total) for i, ev in enumerate(events)]
        chain_html = (
            f'<div class="event-chain">{_ARROW.join(cards)}</div>'
        )
    else:
        chain_html = (
            '<div class="empty">该变量暂无生命周期事件记录</div>'
        )

    summary_html = _build_summary(type_counts, type_order, total, files)

    title = f"变量生命周期 - {var_name}"
    html_doc = (
        '<!DOCTYPE html>\n'
        '<html lang="zh-CN">\n'
        '<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'<title>{_esc(title)}</title>\n'
        f'<style>\n{_CSS}\n</style>\n'
        '</head>\n'
        '<body>\n'
        f'{header_html}\n'
        f'{chain_html}\n'
        f'{summary_html}\n'
        '</body>\n'
        '</html>\n'
    )

    # 确保输出目录存在
    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # 以 UTF-8 编码写入文件
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_doc)

    logger.info(
        "生命周期 HTML 报告已导出: %s (变量=%s, 事件数=%d, 文件数=%d)",
        output_path, var_name, total, len(files),
    )
    return output_path
