"""
GUI 元素探查器 - 变量生命周期静态分析引擎

基于 Python 标准库 ast 实现的变量生命周期追踪器。扫描指定文件夹下所有 .py 文件，
追踪指定变量的完整生命周期（诞生、赋值、使用、传参、返回、销毁等）。

特性：
- 纯标准库实现，不依赖任何第三方库
- 支持作用域追踪（模块/函数/类/方法/推导式）
- 支持上下文行提取（前后各2行，共5行）
- 支持模糊匹配变量名（前缀+包含）

遵循 DEVELOPMENT-METHOD.md 第 9 节代码质量基线：
- 函数/类包含 docstring
- 无硬编码、无调试残留
- 关键操作记录日志
"""

import ast
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from utils.logging_utils import get_logger

logger = get_logger(__name__)


# 默认排除的目录（虚拟环境、缓存、构建产物等）
EXCLUDE_DIRS = {
    "venv", ".venv", "__pycache__", ".git", "node_modules",
    ".tox", ".eggs", "build", "dist", ".mypy_cache", ".pytest_cache",
    "backups",
}

# 上下文行数：前后各 2 行，共 5 行
_CONTEXT_BEFORE = 2
_CONTEXT_AFTER = 2


class EventType(Enum):
    """变量事件类型"""

    BIRTH = "诞生"          # 首次赋值/定义
    ASSIGN = "赋值"         # 重新赋值
    AUG_ASSIGN = "增量赋值"  # +=, -= 等
    USE = "使用"            # 读取
    PARAM = "参数"          # 函数参数
    IMPORT = "导入"         # import 语句
    FOR_LOOP = "循环变量"   # for 循环变量
    WITH_AS = "上下文管理"  # with ... as
    DEL = "销毁"           # del 语句
    RETURN = "返回"        # return 中的使用
    ARG_PASS = "传参"      # 作为函数参数传递


# 视作"使用"语义的事件集合（用于 use_count 统计）
_USE_EVENTS = frozenset({
    EventType.USE,
    EventType.AUG_ASSIGN,   # x += 1 隐含读取
    EventType.ARG_PASS,
    EventType.RETURN,
})


class ScopeType(Enum):
    """作用域类型"""

    MODULE = "模块"
    FUNCTION = "函数"
    CLASS = "类"
    METHOD = "方法"
    COMPREHENSION = "推导式"


@dataclass
class VariableEvent:
    """变量事件节点"""

    event_type: EventType        # 事件类型
    file_path: str               # 文件路径（相对路径）
    file_name: str               # 文件名
    line: int                    # 行号
    col: int                     # 列号
    code_line: str               # 该行源代码（去除首尾空白）
    scope: str                   # 所属作用域名称（如 "module:main" / "func:process_data" / "class:MyClass"）
    scope_type: ScopeType        # 作用域类型
    context_lines: List[str] = field(default_factory=list)  # 上下文代码行（前后各2行，共5行）
    detail: str = ""             # 详细描述（如 "赋值: x = 1"）
    type_inferred: str = ""      # 静态推断的变量类型（如 "int", "str", "list", "未知"）
    type_description: str = ""   # 类型简述（如 "整数", "字符串", "列表"）


@dataclass
class LifecycleResult:
    """变量生命周期结果"""

    variable_name: str           # 变量名
    events: List[VariableEvent] = field(default_factory=list)  # 事件列表，按 (file, line, col) 排序
    files_involved: List[str] = field(default_factory=list)    # 涉及的文件列表
    total_events: int = 0        # 总事件数
    birth_count: int = 0         # 诞生次数
    use_count: int = 0           # 使用次数
    death_count: int = 0         # 消亡次数


# 增量赋值运算符到符号的映射
_AUG_OP_SYMBOLS = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.Mod: "%",
    ast.Pow: "**",
    ast.FloorDiv: "//",
    ast.LShift: "<<",
    ast.RShift: ">>",
    ast.BitOr: "|",
    ast.BitAnd: "&",
    ast.BitXor: "^",
    ast.MatMult: "@",
}


def _aug_op_symbol(op: ast.AST) -> str:
    """获取增量赋值运算符的可读符号。"""
    return _AUG_OP_SYMBOLS.get(type(op), "?=")


# 类型推断映射表：构造函数名 -> (类型字符串, 类型简述)
_TYPE_MAP = {
    # 字面量推断
    "int": ("int", "整数"),
    "float": ("float", "浮点数"),
    "str": ("str", "字符串"),
    "bool": ("bool", "布尔值"),
    "NoneType": ("NoneType", "空值"),
    # 构造函数推断
    "list": ("list", "列表"),
    "dict": ("dict", "字典"),
    "set": ("set", "集合"),
    "tuple": ("tuple", "元组"),
    "frozenset": ("frozenset", "冻结集合"),
    "bytes": ("bytes", "字节串"),
    "bytearray": ("bytearray", "字节数组"),
    "complex": ("complex", "复数"),
}

# 已知内置函数的返回类型映射
_KNOWN_FUNC_RETURNS = {
    "range": ("range", "范围序列"),
    "enumerate": ("enumerate", "枚举对象"),
    "zip": ("zip", "zip对象"),
    "map": ("map", "map对象"),
    "filter": ("filter", "filter对象"),
    "open": ("file", "文件对象"),
    "sorted": ("list", "排序后的列表"),
    "reversed": ("reversed", "反向迭代器"),
    "input": ("str", "输入字符串"),
    "len": ("int", "长度整数"),
}


def _infer_type(node: ast.AST) -> tuple:
    """
    根据 AST 节点静态推断变量类型。

    支持字面量、容器字面量、构造函数、推导式、f-string、已知内置函数调用、import 等场景。

    Args:
        node: AST 节点（通常是赋值右侧表达式）

    Returns:
        (type_str, description_str) 元组，无法推断时返回 ("未知", "无法静态推断")
    """
    # 1. 字面量
    if isinstance(node, ast.Constant):
        if node.value is None:
            return ("NoneType", "空值")
        if isinstance(node.value, bool):
            return ("bool", "布尔值")
        if isinstance(node.value, int):
            return ("int", "整数")
        if isinstance(node.value, float):
            return ("float", "浮点数")
        if isinstance(node.value, str):
            return ("str", "字符串")
        if isinstance(node.value, bytes):
            return ("bytes", "字节串")
        if isinstance(node.value, complex):
            return ("complex", "复数")

    # 2. 列表/字典/集合/元组字面量
    if isinstance(node, ast.List):
        return ("list", "列表")
    if isinstance(node, ast.Dict):
        return ("dict", "字典")
    if isinstance(node, ast.Set):
        return ("set", "集合")
    if isinstance(node, ast.Tuple):
        return ("tuple", "元组")

    # 3. 推导式
    if isinstance(node, ast.ListComp):
        return ("list", "列表推导式")
    if isinstance(node, ast.SetComp):
        return ("set", "集合推导式")
    if isinstance(node, ast.DictComp):
        return ("dict", "字典推导式")
    if isinstance(node, ast.GeneratorExp):
        return ("generator", "生成器")

    # 4. f-string
    if isinstance(node, ast.JoinedStr):
        return ("str", "f字符串")

    # 5. 函数调用
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        func_name = node.func.id
        # 已知内置函数返回类型
        if func_name in _KNOWN_FUNC_RETURNS:
            return _KNOWN_FUNC_RETURNS[func_name]
        # 构造函数推断 list() / dict() / set() 等
        if func_name in _TYPE_MAP:
            return _TYPE_MAP[func_name]
        # 自定义类实例化
        return (func_name, f"{func_name}实例")

    # 6. import 语句
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return ("module", "模块")

    # 7. 类型注解节点： ast.Name (如 int, str, bool)
    if isinstance(node, ast.Name):
        name = node.id
        _ANN_MAP = {
            "int": ("int", "整数"),
            "float": ("float", "浮点数"),
            "str": ("str", "字符串"),
            "bool": ("bool", "布尔值"),
            "list": ("list", "列表"),
            "dict": ("dict", "字典"),
            "set": ("set", "集合"),
            "tuple": ("tuple", "元组"),
            "bytes": ("bytes", "字节串"),
            "bytearray": ("bytearray", "字节数组"),
            "complex": ("complex", "复数"),
            "NoneType": ("NoneType", "空值"),
            "Any": ("Any", "任意类型"),
            "Optional": ("Optional", "可选类型"),
            "Union": ("Union", "联合类型"),
            "Callable": ("Callable", "可调用对象"),
            "Iterator": ("Iterator", "迭代器"),
            "Generator": ("Generator", "生成器"),
        }
        if name in _ANN_MAP:
            return _ANN_MAP[name]
        return (name, f"{name}类型")

    # 8. Subscript 注解（如 List[int], Dict[str, int], Optional[str]）
    if isinstance(node, ast.Subscript):
        if isinstance(node.value, ast.Name):
            base_name = node.value.id
            _SUBSCRIPT_MAP = {
                "List": ("list", "列表"),
                "Dict": ("dict", "字典"),
                "Set": ("set", "集合"),
                "Tuple": ("tuple", "元组"),
                "Optional": ("Optional", "可选类型"),
                "Union": ("Union", "联合类型"),
                "FrozenSet": ("frozenset", "冻结集合"),
            }
            if base_name in _SUBSCRIPT_MAP:
                return _SUBSCRIPT_MAP[base_name]
            return (base_name, f"{base_name}类型")

    # 9. ast.Constant 用作注解（如 def f(x: 1) -> None:）
    if isinstance(node, ast.Constant):
        return _infer_type(node)

    # 10. 无法推断
    return ("未知", "无法静态推断")


def _read_source(path: str) -> Optional[str]:
    """
    读取源文件内容。

    先尝试 UTF-8，失败再尝试 GBK，均失败则返回 None 并记录日志。

    Args:
        path: 文件绝对路径

    Returns:
        文件文本内容；无法读取时返回 None
    """
    for encoding in ("utf-8", "gbk"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            logger.warning("读取文件失败: %s | %s", path, exc)
            return None
    logger.warning("无法解码文件（UTF-8/GBK 均失败）: %s", path)
    return None


def _source_segment(source: str, node: ast.AST) -> str:
    """
    获取 AST 节点对应的源代码片段。

    优先使用 ast.get_source_segment，失败时回退到 ast.unparse，再失败返回空串。

    Args:
        source: 完整源代码文本
        node: AST 节点

    Returns:
        节点对应的源代码字符串
    """
    try:
        seg = ast.get_source_segment(source, node)
        if seg is not None:
            return seg.strip()
    except Exception:  # noqa: BLE001 - get_source_segment 在边界情况下可能抛错
        pass
    try:
        return ast.unparse(node).strip()
    except Exception:  # noqa: BLE001
        return ""


def _names_from_target(target: ast.AST) -> List[ast.Name]:
    """
    从赋值/循环 target 节点中提取所有 Name 子节点。

    支持：Name、Tuple、List、Starred(Name)。

    Args:
        target: AST target 节点

    Returns:
        target 中包含的 Name 节点列表
    """
    names: List[ast.Name] = []
    if isinstance(target, ast.Name):
        names.append(target)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            if isinstance(elt, ast.Name):
                names.append(elt)
            elif isinstance(elt, ast.Starred) and isinstance(elt.value, ast.Name):
                names.append(elt.value)
    elif isinstance(target, ast.Starred) and isinstance(target.value, ast.Name):
        names.append(target.value)
    return names


class VariableTracer(ast.NodeVisitor):
    """
    变量生命周期 AST 遍历器。

    维护作用域栈，遍历 AST 并记录目标变量的所有事件。
    每个文件创建一个实例（birth_seen 按文件独立）。

    Args:
        target_name: 目标变量名
        file_path: 文件相对路径
        file_name: 文件名
        source_lines: 源代码按行拆分的列表
        source_text: 完整源代码文本
    """

    def __init__(
        self,
        target_name: str,
        file_path: str,
        file_name: str,
        source_lines: List[str],
        source_text: str,
    ) -> None:
        self.target_name = target_name
        self.file_path = file_path
        self.file_name = file_name
        self.source_lines = source_lines
        self.source_text = source_text
        self.events: List[VariableEvent] = []
        # 作用域栈：元素为 (scope_name, scope_type)
        self.scope_stack: List[tuple] = []
        # 已诞生作用域集合：(file_path, scope_name)，用于区分 BIRTH / ASSIGN
        self.birth_seen: set = set()
        # 已被 RETURN/ARG_PASS 处理的 Name 节点 id，避免重复记录 USE
        self._skip_name_ids: set = set()

    # ------------------------------------------------------------------ #
    # 作用域辅助
    # ------------------------------------------------------------------ #

    def _current_scope(self) -> tuple:
        """返回当前作用域 (scope_name, scope_type)，栈空则为模块级。"""
        if not self.scope_stack:
            return (f"module:{self.file_name}", ScopeType.MODULE)
        return self.scope_stack[-1]

    def _mark_birth(self) -> None:
        """将当前作用域标记为已诞生目标变量。"""
        self.birth_seen.add((self.file_path, self._current_scope()[0]))

    def _is_first_birth(self) -> bool:
        """判断当前作用域是否首次诞生目标变量。"""
        return (self.file_path, self._current_scope()[0]) not in self.birth_seen

    # ------------------------------------------------------------------ #
    # 事件记录
    # ------------------------------------------------------------------ #

    def _get_context(self, line: int) -> List[str]:
        """获取指定行号前后各 2 行的上下文（共 5 行）。"""
        start = max(0, line - 1 - _CONTEXT_BEFORE)
        end = min(len(self.source_lines), line + _CONTEXT_AFTER)
        return self.source_lines[start:end]

    def _add_event(
        self,
        event_type: EventType,
        node: ast.AST,
        detail: str = "",
        value_node: ast.AST = None,
    ) -> None:
        """
        记录一个变量事件。

        Args:
            event_type: 事件类型
            node: 触发事件的 AST 节点（用于定位行号/列号）
            detail: 详细描述文本
            value_node: 用于类型推断的值节点（通常是赋值右侧表达式）；
                        为 None 时不进行类型推断，IMPORT 事件例外（推断为模块）
        """
        scope_name, scope_type = self._current_scope()
        lineno = getattr(node, "lineno", 0)
        col = getattr(node, "col_offset", 0)
        if 0 < lineno <= len(self.source_lines):
            code_line = self.source_lines[lineno - 1].strip()
        else:
            code_line = ""

        # 类型推断
        type_inferred = ""
        type_description = ""
        if value_node is not None:
            type_inferred, type_description = _infer_type(value_node)
        elif event_type == EventType.IMPORT:
            type_inferred, type_description = ("module", "模块")

        self.events.append(VariableEvent(
            event_type=event_type,
            file_path=self.file_path,
            file_name=self.file_name,
            line=lineno,
            col=col,
            code_line=code_line,
            scope=scope_name,
            scope_type=scope_type,
            context_lines=self._get_context(lineno),
            detail=detail,
            type_inferred=type_inferred,
            type_description=type_description,
        ))

    # ------------------------------------------------------------------ #
    # 作用域节点
    # ------------------------------------------------------------------ #

    def _check_args(self, args: ast.arguments) -> None:
        """检查函数参数列表，记录匹配的 PARAM 事件。"""
        all_args: List[ast.arg] = []
        all_args.extend(getattr(args, "posonlyargs", []) or [])
        all_args.extend(args.args or [])
        if args.vararg:
            all_args.append(args.vararg)
        all_args.extend(args.kwonlyargs or [])
        if args.kwarg:
            all_args.append(args.kwarg)
        # 从当前作用域提取函数名（如 "func:main" -> "main"，"method:MyClass.method" -> "MyClass.method"）
        scope_name, _ = self._current_scope()
        func_name = scope_name.split(":", 1)[1] if ":" in scope_name else scope_name
        for arg in all_args:
            if arg.arg == self.target_name:
                # 优先使用参数的类型注解推断类型
                value_node = getattr(arg, "annotation", None)
                self._add_event(
                    EventType.PARAM, arg,
                    f"作为函数参数: {func_name}({arg.arg})",
                    value_node=value_node,
                )
                self._mark_birth()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """处理函数定义：进入函数/方法作用域，检查参数。"""
        scope_name, scope_type = self._current_scope()
        if scope_type == ScopeType.CLASS:
            class_name = scope_name.split(":", 1)[1]
            new_scope = (f"method:{class_name}.{node.name}", ScopeType.METHOD)
        else:
            new_scope = (f"func:{node.name}", ScopeType.FUNCTION)
        self.scope_stack.append(new_scope)
        self._check_args(node.args)
        self.generic_visit(node)
        self.scope_stack.pop()

    # async 函数复用同步函数处理逻辑
    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """处理类定义：进入类作用域。"""
        self.scope_stack.append((f"class:{node.name}", ScopeType.CLASS))
        self.generic_visit(node)
        self.scope_stack.pop()

    def _visit_comprehension(self, node: ast.AST) -> None:
        """处理推导式：进入推导式作用域，处理循环 target。"""
        self.scope_stack.append(
            (f"comprehension@L{getattr(node, 'lineno', 0)}", ScopeType.COMPREHENSION)
        )
        for gen in getattr(node, "generators", []):
            for name in _names_from_target(gen.target):
                if name.id == self.target_name:
                    self._mark_birth()
                    iter_repr = _source_segment(self.source_text, gen.iter)
                    self._add_event(
                        EventType.FOR_LOOP, name,
                        f"作为循环变量: for {self.target_name} in {iter_repr}",
                        value_node=gen.iter,
                    )
        self.generic_visit(node)
        self.scope_stack.pop()

    visit_ListComp = _visit_comprehension
    visit_SetComp = _visit_comprehension
    visit_DictComp = _visit_comprehension
    visit_GeneratorExp = _visit_comprehension

    # ------------------------------------------------------------------ #
    # 赋值类节点
    # ------------------------------------------------------------------ #

    def visit_Assign(self, node: ast.Assign) -> None:
        """处理赋值语句：检查 targets，记录 BIRTH/ASSIGN。

        支持两种形式：
        - 普通变量：x = value → ast.Name
        - 实例属性：self.xxx = value → ast.Attribute
        """
        for target in node.targets:
            # 普通变量名
            for name in _names_from_target(target):
                if name.id == self.target_name:
                    value_repr = _source_segment(self.source_text, node.value)
                    if self._is_first_birth():
                        self._mark_birth()
                        self._add_event(
                            EventType.BIRTH, name,
                            f"定义: {self.target_name} = {value_repr}",
                            value_node=node.value,
                        )
                    else:
                        self._add_event(
                            EventType.ASSIGN, name,
                            f"赋值: {self.target_name} = {value_repr}",
                            value_node=node.value,
                        )
            # 实例属性 self.xxx = value
            if "." in self.target_name and isinstance(target, ast.Attribute):
                if self._matches_target(target):
                    value_repr = _source_segment(self.source_text, node.value)
                    if self._is_first_birth():
                        self._mark_birth()
                        self._add_event(
                            EventType.BIRTH, target,
                            f"定义: {self.target_name} = {value_repr}",
                            value_node=node.value,
                        )
                    else:
                        self._add_event(
                            EventType.ASSIGN, target,
                            f"赋值: {self.target_name} = {value_repr}",
                            value_node=node.value,
                        )
        # value 中的 Name(Load) 由 generic_visit -> visit_Name 记录为 USE
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        """处理增量赋值（+= 等）：记录 AUG_ASSIGN（隐含读取）。"""
        if isinstance(node.target, ast.Name) and node.target.id == self.target_name:
            op_sym = _aug_op_symbol(node.op)
            value_repr = _source_segment(self.source_text, node.value)
            self._add_event(
                EventType.AUG_ASSIGN, node.target,
                f"增量: {self.target_name} {op_sym}= {value_repr}",
                value_node=node.value,
            )
        # value 中的 Name(Load) 记录为 USE
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """处理带类型注解的赋值：x: int = 1。"""
        if (
            isinstance(node.target, ast.Name)
            and node.target.id == self.target_name
            and node.value is not None
        ):
            value_repr = _source_segment(self.source_text, node.value)
            annotation_repr = _source_segment(self.source_text, node.annotation)
            if self._is_first_birth():
                self._mark_birth()
                self._add_event(
                    EventType.BIRTH, node.target,
                    f"定义: {self.target_name}: {annotation_repr} = {value_repr}",
                    value_node=node.value,
                )
            else:
                self._add_event(
                    EventType.ASSIGN, node.target,
                    f"定义: {self.target_name}: {annotation_repr} = {value_repr}",
                    value_node=node.value,
                )
        self.generic_visit(node)

    # ------------------------------------------------------------------ #
    # 读取使用类节点
    # ------------------------------------------------------------------ #

    def _matches_target(self, node: ast.AST) -> bool:
        """判断 AST 节点是否匹配目标变量名。

        支持两种形式：
        - 普通变量名：ast.Name(id='xxx') → 匹配 'xxx'
        - 实例属性：ast.Attribute(value=Name(id='self'), attr='xxx') → 匹配 'self.xxx'
        """
        if isinstance(node, ast.Name) and node.id == self.target_name:
            return True
        # 支持 self.xxx 形式：当目标变量名包含 '.' 时
        if "." in self.target_name and isinstance(node, ast.Attribute):
            # 构建完整属性路径：self.xxx
            parts = []
            current = node
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
                full_name = ".".join(reversed(parts))
                if full_name == self.target_name:
                    return True
        return False

    def visit_Name(self, node: ast.Name) -> None:
        """处理变量名引用：Load 上下文记录 USE。"""
        if id(node) in self._skip_name_ids:
            return
        if node.id == self.target_name and isinstance(node.ctx, ast.Load):
            self._add_event(EventType.USE, node, "在表达式中引用")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """处理属性访问：支持 self.xxx 形式的变量追踪。

        当目标变量名包含 '.'（如 self.xxx）时，
        匹配 ast.Attribute 节点的完整路径。
        """
        if "." not in self.target_name:
            self.generic_visit(node)
            return
        if isinstance(node.ctx, ast.Load) and self._matches_target(node):
            self._add_event(EventType.USE, node, f"在表达式中引用 {self.target_name}")
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        """处理 return 语句：value 中的目标变量记录 RETURN（优先于 USE）。"""
        if node.value is not None:
            value_repr = _source_segment(self.source_text, node.value)
            for n in ast.walk(node.value):
                if (
                    isinstance(n, ast.Name)
                    and isinstance(n.ctx, ast.Load)
                    and n.id == self.target_name
                    and id(n) not in self._skip_name_ids
                ):
                    self._add_event(
                        EventType.RETURN, n,
                        f"作为返回值: return {value_repr}",
                    )
                    self._skip_name_ids.add(id(n))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """处理函数调用：作为实参传递的目标变量记录 ARG_PASS（优先于 USE）。"""
        func_repr = _source_segment(self.source_text, node.func)
        for arg in node.args:
            if (
                isinstance(arg, ast.Name)
                and isinstance(arg.ctx, ast.Load)
                and arg.id == self.target_name
                and id(arg) not in self._skip_name_ids
            ):
                self._add_event(EventType.ARG_PASS, arg, f"作为参数传入: {func_repr}()")
                self._skip_name_ids.add(id(arg))
        for kw in node.keywords:
            if (
                isinstance(kw.value, ast.Name)
                and isinstance(kw.value.ctx, ast.Load)
                and kw.value.id == self.target_name
                and id(kw.value) not in self._skip_name_ids
            ):
                self._add_event(EventType.ARG_PASS, kw.value, f"作为参数传入: {func_repr}()")
                self._skip_name_ids.add(id(kw.value))
        # func 与已处理的 args 通过 generic_visit 继续访问
        self.generic_visit(node)

    # ------------------------------------------------------------------ #
    # 循环 / 上下文管理 / 删除
    # ------------------------------------------------------------------ #

    def visit_For(self, node: ast.For) -> None:
        """处理 for 循环：target 中的目标变量记录 FOR_LOOP。"""
        iter_repr = _source_segment(self.source_text, node.iter)
        for name in _names_from_target(node.target):
            if name.id == self.target_name:
                self._mark_birth()
                self._add_event(
                    EventType.FOR_LOOP, name,
                    f"作为循环变量: for {self.target_name} in {iter_repr}",
                    value_node=node.iter,
                )
        self.generic_visit(node)

    visit_AsyncFor = visit_For

    def visit_With(self, node: ast.With) -> None:
        """处理 with 语句：optional_vars 中的目标变量记录 WITH_AS。"""
        for item in node.items:
            opt = item.optional_vars
            if isinstance(opt, ast.Name) and opt.id == self.target_name:
                self._mark_birth()
                self._add_event(
                    EventType.WITH_AS, opt,
                    f"作为上下文管理器: with ... as {self.target_name}",
                    value_node=item.context_expr,
                )
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def visit_Delete(self, node: ast.Delete) -> None:
        """处理 del 语句：记录 DEL。"""
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == self.target_name:
                self._add_event(EventType.DEL, target, f"显式销毁: del {target.id}")
        self.generic_visit(node)

    # ------------------------------------------------------------------ #
    # 导入节点
    # ------------------------------------------------------------------ #

    def visit_Import(self, node: ast.Import) -> None:
        """处理 import 语句：记录匹配的 IMPORT 事件。"""
        for alias in node.names:
            bound = alias.asname if alias.asname else alias.name.split(".")[0]
            if bound == self.target_name:
                self._mark_birth()
                as_part = f" as {alias.asname}" if alias.asname else ""
                self._add_event(
                    EventType.IMPORT, node,
                    f"从模块导入: import {alias.name}{as_part}",
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """处理 from ... import 语句：记录匹配的 IMPORT 事件。"""
        module = node.module or ""
        for alias in node.names:
            bound = alias.asname if alias.asname else alias.name
            if bound == self.target_name:
                self._mark_birth()
                alias_name = alias.name
                if alias.asname:
                    alias_name = f"{alias.name} as {alias.asname}"
                self._add_event(
                    EventType.IMPORT, node,
                    f"从模块导入: from {module} import {alias_name}",
                )
        self.generic_visit(node)


class _NameCollector(ast.NodeVisitor):
    """收集源码中所有变量名的访问者（用于模糊搜索）。

    支持收集两种形式：
    - 普通变量名：ast.Name → 'xxx'
    - 实例属性：ast.Attribute → 'self.xxx'
    """

    def __init__(self) -> None:
        self.counts: dict = {}

    def _add(self, name: Optional[str]) -> None:
        if name and name.isidentifier():
            self.counts[name] = self.counts.get(name, 0) + 1

    def _add_attr(self, name: str) -> None:
        """添加属性路径名（如 self.xxx），不检查 isidentifier"""
        if name:
            self.counts[name] = self.counts.get(name, 0) + 1

    def visit_Name(self, node: ast.Name) -> None:
        """收集 Name 节点。"""
        self._add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """收集 self.xxx 形式的属性访问路径。"""
        # 构建完整属性路径
        parts = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
            full_name = ".".join(reversed(parts))
            # 只收集 self. 开头的属性（其他对象的属性意义不大）
            if parts[-1] == "self" and len(parts) >= 2:
                self._add_attr(full_name)
        self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> None:
        """收集函数参数名。"""
        self._add(node.arg)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        """收集 import 绑定名。"""
        for alias in node.names:
            self._add(alias.asname or alias.name.split(".")[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """收集 from...import 绑定名。"""
        for alias in node.names:
            self._add(alias.asname or alias.name)
        self.generic_visit(node)


def scan_folder(folder_path: str, exclude_dirs: Optional[List[str]] = None) -> List[str]:
    """
    扫描文件夹，返回所有 .py 文件路径列表。

    自动排除 venv、__pycache__、.git、node_modules 等目录。

    Args:
        folder_path: 待扫描的根目录绝对路径
        exclude_dirs: 自定义排除目录名列表；为 None 时使用默认 EXCLUDE_DIRS

    Returns:
        排序后的 .py 文件绝对路径列表
    """
    excludes = set(exclude_dirs) if exclude_dirs else EXCLUDE_DIRS
    result: List[str] = []
    for root, dirs, files in os.walk(folder_path):
        # 原地过滤目录，阻止 os.walk 进入排除目录
        dirs[:] = [d for d in dirs if d not in excludes]
        for fname in files:
            if fname.endswith(".py"):
                result.append(os.path.join(root, fname))
    result.sort()
    logger.debug("扫描文件夹完成: %s | .py 文件数: %d", folder_path, len(result))
    return result


def extract_variable_events(folder_path: str, variable_name: str) -> LifecycleResult:
    """
    核心函数：扫描文件夹，追踪指定变量的完整生命周期。

    处理流程：
        1. 扫描所有 .py 文件
        2. 对每个文件构建 AST
        3. 遍历 AST，记录目标变量的所有事件
        4. 按 (file_path, line, col) 排序
        5. 返回 LifecycleResult

    Args:
        folder_path: 待扫描的根目录绝对路径
        variable_name: 目标变量名

    Returns:
        LifecycleResult 生命周期结果对象
    """
    if not variable_name:
        logger.warning("variable_name 为空，返回空结果")
        return LifecycleResult(variable_name=variable_name)

    files = scan_folder(folder_path)
    all_events: List[VariableEvent] = []

    for abs_path in files:
        rel_path = os.path.relpath(abs_path, folder_path)
        file_name = os.path.basename(abs_path)
        source_text = _read_source(abs_path)
        if source_text is None:
            continue
        try:
            tree = ast.parse(source_text, filename=abs_path)
        except SyntaxError as exc:
            logger.warning("语法解析失败，跳过文件: %s | %s", rel_path, exc)
            continue
        source_lines = source_text.splitlines()
        tracer = VariableTracer(
            target_name=variable_name,
            file_path=rel_path,
            file_name=file_name,
            source_lines=source_lines,
            source_text=source_text,
        )
        tracer.visit(tree)
        if tracer.events:
            all_events.extend(tracer.events)
            logger.debug(
                "文件 %s 命中事件 %d 个", rel_path, len(tracer.events)
            )

    all_events.sort(key=lambda e: (e.file_path, e.line, e.col))
    files_involved = sorted({e.file_path for e in all_events})

    birth_count = sum(1 for e in all_events if e.event_type == EventType.BIRTH)
    death_count = sum(1 for e in all_events if e.event_type == EventType.DEL)
    use_count = sum(1 for e in all_events if e.event_type in _USE_EVENTS)

    logger.info(
        "变量生命周期追踪完成: 变量=%s | 文件数=%d | 事件数=%d | 诞生=%d 使用=%d 消亡=%d",
        variable_name, len(files_involved), len(all_events),
        birth_count, use_count, death_count,
    )

    return LifecycleResult(
        variable_name=variable_name,
        events=all_events,
        files_involved=files_involved,
        total_events=len(all_events),
        birth_count=birth_count,
        use_count=use_count,
        death_count=death_count,
    )


def get_all_variable_names(folder_path: str) -> List[str]:
    """
    扫描文件夹，提取所有变量名（用于模糊搜索）。

    返回去重后的变量名列表，按出现频率降序排列；频率相同则按名字升序。

    Args:
        folder_path: 待扫描的根目录绝对路径

    Returns:
        去重并排序后的变量名列表
    """
    files = scan_folder(folder_path)
    counter: dict = {}

    for abs_path in files:
        source_text = _read_source(abs_path)
        if source_text is None:
            continue
        try:
            tree = ast.parse(source_text, filename=abs_path)
        except SyntaxError as exc:
            logger.warning("语法解析失败，跳过文件: %s | %s", abs_path, exc)
            continue
        collector = _NameCollector()
        collector.visit(tree)
        for name, cnt in collector.counts.items():
            counter[name] = counter.get(name, 0) + cnt

    sorted_names = [
        name for name, _ in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    logger.debug("变量名提取完成: 文件数=%d | 唯一变量名数=%d", len(files), len(sorted_names))
    return sorted_names


def fuzzy_match(query: str, candidates: List[str], limit: int = 50) -> List[str]:
    """
    模糊匹配：对候选变量名列表做前缀+包含匹配。

    匹配规则（纯 Python 实现，不依赖第三方库）：
        - 前缀匹配优先于包含匹配
        - 前缀匹配中，名字越短越靠前（更精确）
        - 包含匹配中，query 出现位置越靠前越优先，再按名字长度升序
        - 大小写不敏感

    Args:
        query: 查询字符串
        candidates: 候选变量名列表
        limit: 返回结果上限

    Returns:
        按匹配度排序的变量名列表
    """
    query = (query or "").lower()
    if not query:
        return list(candidates)[:limit]

    prefix_matches: List[tuple] = []   # (名字长度, 名字)
    contains_matches: List[tuple] = []  # (出现位置, 名字长度, 名字)
    seen: set = set()

    for cand in candidates:
        cand_lower = cand.lower()
        if cand_lower in seen:
            continue
        seen.add(cand_lower)
        if cand_lower.startswith(query):
            prefix_matches.append((len(cand), cand))
        elif query in cand_lower:
            contains_matches.append((cand_lower.index(query), len(cand), cand))

    prefix_matches.sort(key=lambda x: (x[0], x[1]))
    contains_matches.sort(key=lambda x: (x[0], x[1], x[2]))

    result = [c for _, c in prefix_matches] + [c for _, _, c in contains_matches]
    # 如果输入含 .（如 self.），也匹配 self.xxx 形式的属性名
    if "." in query:
        attr_matches = [c for c in candidates if c.lower().startswith(query) and c not in result]
        result = attr_matches + result
    return result[:limit]
