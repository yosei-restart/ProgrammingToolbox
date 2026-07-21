"""
函数调用链分析引擎

功能：
- 扫描指定文件夹/文件中的 Python 源码
- 解析所有函数定义（def/async def）
- 分析函数之间的调用关系（caller → callee）
- 生成调用链图（树形结构）
- 支持查看某个函数的被调用方和调用方

依赖：Python 标准库 ast 模块
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field


@dataclass
class FunctionInfo:
    """函数信息"""
    name: str                  # 函数名
    file_path: str             # 文件路径
    line: int                  # 定义行号
    end_line: int              # 结束行号
    args: list[str] = field(default_factory=list)       # 参数列表
    decorators: list[str] = field(default_factory=list) # 装饰器
    docstring: str = ""         # 文档字符串
    is_async: bool = False     # 是否异步函数
    is_method: bool = False    # 是否类方法
    class_name: str = ""       # 所属类名（方法时）
    calls: list[CallRef] = field(default_factory=list)  # 调用的函数
    called_by: list[str] = field(default_factory=list)  # 被哪些函数调用


@dataclass
class CallRef:
    """调用引用"""
    target_name: str    # 被调用函数名
    line: int           # 调用所在行号
    is_method_call: bool = False  # 是否是 obj.method() 形式


@dataclass
class ChainNode:
    """调用链节点"""
    func: FunctionInfo
    depth: int
    children: list[ChainNode] = field(default_factory=list)


class CallChainAnalyzer:
    """函数调用链分析器"""

    def __init__(self):
        self._functions: dict[str, list[FunctionInfo]] = {}
        self._func_by_fullname: dict[str, FunctionInfo] = {}
        self._all_functions: list[FunctionInfo] = []

    _SKIP_DIRS = {
        "venv", ".venv", "env", ".env",
        "node_modules", "__pycache__", ".git", ".svn", ".hg",
        "build", "dist", ".idea", ".vscode", "site-packages",
    }

    def analyze(self, root_path: str) -> list[FunctionInfo]:
        """分析指定路径下的所有 Python 文件"""
        import time
        t0 = time.time()
        self._functions.clear()
        self._func_by_fullname.clear()
        self._all_functions.clear()

        py_files = []
        if os.path.isfile(root_path) and root_path.endswith(".py"):
            py_files.append(root_path)
        else:
            for dirpath, dirnames, filenames in os.walk(root_path):
                dirnames[:] = [d for d in dirnames if d not in self._SKIP_DIRS]
                for f in filenames:
                    if f.endswith(".py"):
                        py_files.append(os.path.join(dirpath, f))

        t1 = time.time()
        print(f"[CallChain] 扫描文件完成: {len(py_files)} 个, 耗时 {t1-t0:.2f}s")

        for i, fp in enumerate(py_files):
            self._analyze_file(fp)
            if (i + 1) % 50 == 0:
                t = time.time()
                print(f"[CallChain] 已分析 {i+1}/{len(py_files)} 文件, 耗时 {t-t0:.2f}s")

        t2 = time.time()
        print(f"[CallChain] AST解析完成: {len(self._all_functions)} 个函数, 耗时 {t2-t1:.2f}s")

        self._resolve_calls()

        t3 = time.time()
        print(f"[CallChain] 调用关系解析完成, 耗时 {t3-t2:.2f}s")
        print(f"[CallChain] 总计耗时 {t3-t0:.2f}s")

        return self._all_functions

    def _analyze_file(self, file_path: str):
        """分析单个文件"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source, filename=file_path)
        except (SyntaxError, UnicodeDecodeError, OSError):
            return

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func = self._extract_function(node, file_path, source, class_name="")
                self._add_function(func)
            elif isinstance(node, ast.ClassDef):
                for item in ast.iter_child_nodes(node):
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        func = self._extract_function(item, file_path, source, class_name=node.name)
                        func.is_method = True
                        self._add_function(func)

    def _extract_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef,
                          file_path: str, source: str, class_name: str) -> FunctionInfo:
        """提取函数信息"""
        args = []
        for arg in node.args.args:
            args.append(arg.arg)

        decorators = []
        for d in node.decorator_list:
            if isinstance(d, ast.Name):
                decorators.append(d.id)
            elif isinstance(d, ast.Attribute):
                decorators.append(f"{ast.unparse(d.value)}.{d.attr}")

        docstring = ast.get_docstring(node) or ""

        # 提取调用信息
        calls = []
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    calls.append(CallRef(child.func.id, child.lineno))
                elif isinstance(child.func, ast.Attribute):
                    calls.append(CallRef(ast.unparse(child.func), child.lineno, is_method_call=True))

        return FunctionInfo(
            name=node.name,
            file_path=file_path,
            line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            args=args,
            decorators=decorators,
            docstring=docstring,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            is_method=bool(class_name),
            class_name=class_name,
            calls=calls,
        )

    def _add_function(self, func: FunctionInfo):
        """添加到索引"""
        self._all_functions.append(func)
        if func.name not in self._functions:
            self._functions[func.name] = []
        self._functions[func.name].append(func)
        full_name = f"{func.class_name}.{func.name}" if func.class_name else func.name
        self._func_by_fullname[full_name] = func

    def _resolve_calls(self):
        """解析调用关系"""
        for func in self._all_functions:
            for call in func.calls:
                targets = self._resolve_call_target(func, call)
                for target in targets:
                    caller_label = f"{func.class_name}.{func.name}" if func.class_name else func.name
                    if caller_label not in target.called_by:
                        target.called_by.append(caller_label)

    def _resolve_call_target(self, caller_func: FunctionInfo, call: CallRef) -> list[FunctionInfo]:
        """解析调用目标，返回匹配的函数列表"""
        target = call.target_name
        if not call.is_method_call:
            return self._functions.get(target, [])

        parts = target.split(".", 1)
        if len(parts) != 2:
            return []
        obj_prefix, method_name = parts

        if obj_prefix == "self" and caller_func.class_name:
            full_name = f"{caller_func.class_name}.{method_name}"
            if full_name in self._func_by_fullname:
                return [self._func_by_fullname[full_name]]
            return []

        results = []
        if method_name in self._functions:
            for f in self._functions[method_name]:
                if f.is_method:
                    results.append(f)
        return results

    def _lookup_function(self, func_name: str) -> FunctionInfo | None:
        """按名称查找函数，支持 'ClassName.method' 和纯函数名两种格式"""
        if func_name in self._func_by_fullname:
            return self._func_by_fullname[func_name]
        if func_name in self._functions and self._functions[func_name]:
            return self._functions[func_name][0]
        return None

    def get_call_chain(self, func_name: str, max_depth: int = 5) -> ChainNode | None:
        func = self._lookup_function(func_name)
        if not func:
            return None
        return self._build_chain(func, 0, max_depth, set())

    def _build_chain(self, func: FunctionInfo, depth: int, max_depth: int,
                     visited: set) -> ChainNode:
        """递归构建调用链"""
        node = ChainNode(func=func, depth=depth)
        if depth >= max_depth:
            return node

        visited_key = f"{func.file_path}:{func.class_name}:{func.name}"
        if visited_key in visited:
            return node
        visited.add(visited_key)

        seen = set()
        for call in func.calls:
            targets = self._resolve_call_target(func, call)
            for target in targets:
                tkey = f"{target.class_name}:{target.name}"
                if tkey in seen:
                    continue
                seen.add(tkey)
                child = self._build_chain(target, depth + 1, max_depth, visited.copy())
                node.children.append(child)

        return node

    def get_callers(self, func_name: str) -> list[FunctionInfo]:
        """获取调用某个函数的所有函数"""
        target = self._lookup_function(func_name)
        if not target:
            return []
        target_key = f"{target.file_path}:{target.class_name}:{target.name}"
        result = []
        for func in self._all_functions:
            for call in func.calls:
                targets = self._resolve_call_target(func, call)
                for t in targets:
                    tkey = f"{t.file_path}:{t.class_name}:{t.name}"
                    if tkey == target_key:
                        result.append(func)
                        break
                else:
                    continue
                break
        return result

    def get_callees(self, func_name: str) -> list[FunctionInfo]:
        """获取某个函数调用的所有函数"""
        func = self._lookup_function(func_name)
        if not func:
            return []
        result = []
        seen = set()
        for call in func.calls:
            targets = self._resolve_call_target(func, call)
            for t in targets:
                tkey = f"{t.file_path}:{t.class_name}:{t.name}"
                if tkey in seen:
                    continue
                seen.add(tkey)
                result.append(t)
        return result

    def get_function_list(self) -> list[FunctionInfo]:
        """获取所有函数列表"""
        return sorted(self._all_functions, key=lambda f: f.name.lower())

    def get_stats(self) -> dict:
        total = len(self._all_functions)
        if total == 0:
            return {"total": 0, "files": 0, "max_depth": 0, "most_called": "", "most_calls": ""}

        files = set(f.file_path for f in self._all_functions)

        call_count = {}
        out_count = {}
        for f in self._all_functions:
            full = f"{f.class_name}.{f.name}" if f.class_name else f.name
            call_count[full] = len(f.called_by)
            out_count[full] = len(f.calls)

        most_called = max(call_count, key=call_count.get)
        most_calls = max(out_count, key=out_count.get)

        return {
            "total": total,
            "files": len(files),
            "max_depth": self._max_depth(),
            "most_called": f"{most_called} ({call_count[most_called]}次)",
            "most_calls": f"{most_calls} ({out_count[most_calls]}次)",
        }

    def _max_depth(self) -> int:
        memo = {}

        def depth_of(func_key: str) -> int:
            if func_key in memo:
                return memo[func_key]
            memo[func_key] = -1
            if func_key not in self._func_by_fullname:
                memo[func_key] = 0
                return 0
            func = self._func_by_fullname[func_key]
            max_child = 0
            for call in func.calls:
                targets = self._resolve_call_target(func, call)
                for t in targets:
                    tkey = f"{t.class_name}.{t.name}" if t.class_name else t.name
                    d = depth_of(tkey)
                    if d > max_child:
                        max_child = d
            memo[func_key] = max_child + 1
            return memo[func_key]

        max_d = 0
        for f in self._all_functions:
            key = f"{f.class_name}.{f.name}" if f.class_name else f.name
            d = depth_of(key)
            if d > max_d:
                max_d = d
        return max_d