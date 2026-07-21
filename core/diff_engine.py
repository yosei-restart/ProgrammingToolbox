"""
代码差异对比引擎

功能：
- 使用 difflib 进行逐行差异对比
- 支持 unified diff 和 side-by-side diff
- 支持文件对比和文本片段对比
- 语义变更分析（变量、函数、导入、类）
- 生成 HTML 格式的差异报告

依赖：Python 标准库 difflib + ast
"""

from __future__ import annotations

import ast
import difflib
import os
from dataclasses import dataclass, field

from utils.logging_utils import get_logger

logger = get_logger(__name__)


@dataclass
class DiffLine:
    """差异行"""
    left_line_no: int | None   # 左侧行号（None 表示新增行）
    right_line_no: int | None  # 右侧行号（None 表示删除行）
    left_text: str             # 左侧文本
    right_text: str            # 右侧文本
    kind: str                  # "equal" | "added" | "removed" | "modified"


@dataclass
class DiffResult:
    """差异对比结果"""
    left_name: str             # 左侧文件名/标签
    right_name: str            # 右侧文件名/标签
    left_lines: list[str]      # 左侧所有行
    right_lines: list[str]     # 右侧所有行
    diff_lines: list[DiffLine] = field(default_factory=list)
    stats: dict = field(default_factory=lambda: {"added": 0, "removed": 0, "modified": 0, "equal": 0})
    is_identical: bool = False
    semantic: dict | None = None  # 语义变更分析结果


def _line_similarity(a: str, b: str) -> float:
    """计算两行代码的相似度（0~1），忽略空白差异"""
    if a == b:
        return 1.0
    a_stripped = a.strip()
    b_stripped = b.strip()
    if a_stripped == b_stripped:
        return 0.95
    if not a_stripped or not b_stripped:
        return 0.0
    return difflib.SequenceMatcher(None, a_stripped, b_stripped).ratio()


def _match_replace_block(
    left_chunk: list[str],
    right_chunk: list[str],
    left_start: int,
    right_start: int,
) -> list[DiffLine]:
    """对 replace 块做子序列匹配，将相似行配对，识别移动的代码块"""
    result: list[DiffLine] = []
    used_right: set[int] = set()

    # 第一遍：为每个左侧行找最相似的右侧行（相似度 > 0.6 才配对）
    for li, l_text in enumerate(left_chunk):
        best_j = -1
        best_sim = 0.0
        for rj, r_text in enumerate(right_chunk):
            if rj in used_right:
                continue
            sim = _line_similarity(l_text, r_text)
            if sim > best_sim:
                best_sim = sim
                best_j = rj
        if best_sim > 0.6:
            used_right.add(best_j)
            kind = "equal" if best_sim > 0.85 else "modified"
            result.append(DiffLine(
                left_line_no=left_start + li + 1,
                right_line_no=right_start + best_j + 1,
                left_text=l_text,
                right_text=right_chunk[best_j],
                kind=kind,
            ))
        else:
            result.append(DiffLine(
                left_line_no=left_start + li + 1,
                right_line_no=None,
                left_text=l_text,
                right_text="",
                kind="removed",
            ))

    # 第二遍：处理右侧未匹配的行
    for rj, r_text in enumerate(right_chunk):
        if rj not in used_right:
            result.append(DiffLine(
                left_line_no=None,
                right_line_no=right_start + rj + 1,
                left_text="",
                right_text=r_text,
                kind="added",
            ))

    # 按右侧行号排序（有行号的在前，None 在后）
    result.sort(key=lambda dl: (
        dl.right_line_no is None,
        dl.right_line_no or 0,
    ))
    return result


class DiffEngine:
    """差异对比引擎"""

    def compare_files(self, left_path: str, right_path: str) -> DiffResult:
        """对比两个文件"""
        left_text = self._read_file(left_path)
        right_text = self._read_file(right_path)
        return self.compare_text(
            left_text,
            right_text,
            left_name=os.path.basename(left_path),
            right_name=os.path.basename(right_path),
        )

    def compare_text(self, left_text: str, right_text: str,
                     left_name: str = "左侧", right_name: str = "右侧") -> DiffResult:
        """对比两段文本"""
        left_lines = left_text.splitlines(keepends=False)
        right_lines = right_text.splitlines(keepends=False)

        result = DiffResult(
            left_name=left_name,
            right_name=right_name,
            left_lines=left_lines,
            right_lines=right_lines,
        )

        if left_lines == right_lines:
            result.is_identical = True
            for i, line in enumerate(left_lines, 1):
                result.diff_lines.append(DiffLine(
                    left_line_no=i, right_line_no=i,
                    left_text=line, right_text=line,
                    kind="equal",
                ))
            result.stats["equal"] = len(left_lines)
            return result

        # 使用 SequenceMatcher 进行逐行对比（autojunk=False 避免丢弃高频行）
        sm = difflib.SequenceMatcher(
            lambda line: False,  # isjunk: 不丢弃任何行
            left_lines, right_lines,
            autojunk=False,
        )
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    result.diff_lines.append(DiffLine(
                        left_line_no=i1 + k + 1,
                        right_line_no=j1 + k + 1,
                        left_text=left_lines[i1 + k],
                        right_text=right_lines[j1 + k],
                        kind="equal",
                    ))
                    result.stats["equal"] += 1

            elif tag == "replace":
                # 对 replace 块做子序列匹配，识别移动/相似的代码行
                left_chunk = left_lines[i1:i2]
                right_chunk = right_lines[j1:j2]
                result.diff_lines.extend(
                    _match_replace_block(left_chunk, right_chunk, i1, j1)
                )
                for dl in result.diff_lines[-max(len(left_chunk), len(right_chunk)):]:
                    if dl.kind == "modified":
                        result.stats["modified"] += 1
                    elif dl.kind == "equal":
                        result.stats["equal"] += 1
                    elif dl.kind == "removed":
                        result.stats["removed"] += 1
                    elif dl.kind == "added":
                        result.stats["added"] += 1

            elif tag == "delete":
                for k in range(i2 - i1):
                    result.diff_lines.append(DiffLine(
                        left_line_no=i1 + k + 1,
                        right_line_no=None,
                        left_text=left_lines[i1 + k],
                        right_text="",
                        kind="removed",
                    ))
                    result.stats["removed"] += 1

            elif tag == "insert":
                for k in range(j2 - j1):
                    result.diff_lines.append(DiffLine(
                        left_line_no=None,
                        right_line_no=j1 + k + 1,
                        left_text="",
                        right_text=right_lines[j1 + k],
                        kind="added",
                    ))
                    result.stats["added"] += 1

        # 语义变更分析（仅对 Python 文件）
        if left_name.endswith(".py") or right_name.endswith(".py"):
            try:
                result.semantic = CodeChangeAnalyzer.analyze(left_text, right_text)
                logger.info(
                    "语义分析完成: %s vs %s, 变更=%s",
                    left_name, right_name,
                    result.semantic["summary"]["total_changed"],
                )
            except Exception as e:
                logger.warning("语义分析失败: %s", e)

        return result

    def generate_unified_diff(self, left_text: str, right_text: str,
                              left_name: str = "a", right_name: str = "b") -> str:
        """生成 unified diff 格式"""
        left_lines = left_text.splitlines(keepends=True)
        right_lines = right_text.splitlines(keepends=True)
        diff = difflib.unified_diff(
            left_lines, right_lines,
            fromfile=left_name, tofile=right_name,
        )
        return "".join(diff)

    def _read_file(self, path: str) -> str:
        """读取文件内容"""
        for encoding in ["utf-8", "gbk", "latin-1"]:
            try:
                with open(path, "r", encoding=encoding) as f:
                    return f.read()
            except (UnicodeDecodeError, OSError):
                continue
        return ""


class CodeChangeAnalyzer:
    """语义变更分析器 - 用 AST 提取变量、函数、导入、类的变化"""

    @staticmethod
    def analyze(left_text: str, right_text: str) -> dict:
        """分析两段代码的语义差异，返回结构化结果"""
        left_info = CodeChangeAnalyzer._extract(left_text)
        right_info = CodeChangeAnalyzer._extract(right_text)
        logger.info(
            "语义提取: left(vars=%d funcs=%d imports=%d classes=%d) right(vars=%d funcs=%d imports=%d classes=%d)",
            len(left_info["variables"]), len(left_info["functions"]),
            len(left_info["imports"]), len(left_info["classes"]),
            len(right_info["variables"]), len(right_info["functions"]),
            len(right_info["imports"]), len(right_info["classes"]),
        )
        result = CodeChangeAnalyzer._compare(left_info, right_info)
        logger.info("语义对比: total_changed=%d", result["summary"]["total_changed"])
        return result

    @staticmethod
    def _extract(source: str) -> dict:
        """从源码中提取变量、函数、导入、类"""
        try:
            tree = ast.parse(source)
        except Exception as e:
            logger.warning("AST 解析失败: %s", e)
            return {"variables": [], "functions": [], "imports": [], "classes": []}

        variables = set()
        functions = []
        imports = []
        classes = []

        # 行号映射：{名称: (start_lineno, end_lineno)}
        var_lines: dict[str, tuple[int, int]] = {}
        func_lines: dict[str, tuple[int, int]] = {}
        import_lines: dict[str, tuple[int, int]] = {}
        class_lines: dict[str, tuple[int, int]] = {}

        for node in ast.walk(tree):
            if not hasattr(node, "lineno"):
                continue
            end_lineno = getattr(node, "end_lineno", node.lineno)

            # 变量赋值（普通赋值 a = 1）
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    for name_node in ast.walk(target):
                        if isinstance(name_node, ast.Name):
                            variables.add(name_node.id)
                            if name_node.id not in var_lines:
                                var_lines[name_node.id] = (node.lineno, end_lineno)

            # 类型注解赋值 a: int = 1
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                variables.add(node.target.id)
                if node.target.id not in var_lines:
                    var_lines[node.target.id] = (node.lineno, end_lineno)

            # 增量赋值 a += 1
            if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                variables.add(node.target.id)
                if node.target.id not in var_lines:
                    var_lines[node.target.id] = (node.lineno, end_lineno)

            # for 循环变量 for x in items
            if isinstance(node, ast.For):
                for name_node in ast.walk(node.target):
                    if isinstance(name_node, ast.Name):
                        variables.add(name_node.id)
                        if name_node.id not in var_lines:
                            var_lines[name_node.id] = (node.lineno, end_lineno)

            # with 上下文变量 with open(...) as f
            if isinstance(node, ast.With):
                for item in node.items:
                    if item.optional_vars:
                        for name_node in ast.walk(item.optional_vars):
                            if isinstance(name_node, ast.Name):
                                variables.add(name_node.id)
                                if name_node.id not in var_lines:
                                    var_lines[name_node.id] = (node.lineno, end_lineno)

            # except 异常变量 except ValueError as e
            if isinstance(node, ast.ExceptHandler) and node.name:
                variables.add(node.name)
                if node.name not in var_lines:
                    var_lines[node.name] = (node.lineno, end_lineno)

            # 函数定义
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # 装饰器
                decorators = ""
                if node.decorator_list:
                    try:
                        dec_names = [ast.unparse(d) for d in node.decorator_list]
                        decorators = ";".join(dec_names) + " "
                    except Exception:
                        pass

                args = []
                for arg in node.args.args:
                    arg_str = arg.arg
                    if arg.annotation:
                        try:
                            arg_str += f": {ast.unparse(arg.annotation)}"
                        except Exception:
                            pass
                    args.append(arg_str)
                # 返回值类型
                returns = ""
                if node.returns:
                    try:
                        returns = f" -> {ast.unparse(node.returns)}"
                    except Exception:
                        pass
                sig = f"{decorators}def {node.name}({', '.join(args)}){returns}"
                functions.append(sig)
                if sig not in func_lines:
                    func_lines[sig] = (node.lineno, end_lineno)

            # 导入
            if isinstance(node, ast.Import):
                for alias in node.names:
                    stmt = f"import {alias.name}"
                    imports.append(stmt)
                    if stmt not in import_lines:
                        import_lines[stmt] = (node.lineno, end_lineno)
            elif isinstance(node, ast.ImportFrom):
                names = ", ".join(a.name for a in node.names)
                stmt = f"from {node.module or ''} import {names}"
                imports.append(stmt)
                if stmt not in import_lines:
                    import_lines[stmt] = (node.lineno, end_lineno)

            # 类定义
            if isinstance(node, ast.ClassDef):
                # 装饰器
                decorators = ""
                if node.decorator_list:
                    try:
                        dec_names = [ast.unparse(d) for d in node.decorator_list]
                        decorators = ";".join(dec_names) + " "
                    except Exception:
                        pass

                bases = []
                for base in node.bases:
                    try:
                        bases.append(ast.unparse(base))
                    except Exception:
                        bases.append(str(base))
                sig = f"{decorators}class {node.name}"
                if bases:
                    sig += f"({', '.join(bases)})"
                classes.append(sig)
                if sig not in class_lines:
                    class_lines[sig] = (node.lineno, end_lineno)

        return {
            "variables": sorted(variables, key=str.lower),
            "functions": functions,
            "imports": imports,
            "classes": classes,
            "_lines": {
                "variables": var_lines,
                "functions": func_lines,
                "imports": import_lines,
                "classes": class_lines,
            },
        }

    @staticmethod
    def _compare(left: dict, right: dict) -> dict:
        """对比两侧的语义信息"""
        result = {}
        changed_lines: dict[str, dict[str, list[tuple[int, int]]]] = {}

        for key, label in [
            ("variables", "变量"),
            ("functions", "函数"),
            ("imports", "导入"),
            ("classes", "类"),
        ]:
            left_set = set(left[key])
            right_set = set(right[key])
            unchanged = sorted(left_set & right_set, key=str.lower)
            removed = sorted(left_set - right_set, key=str.lower)
            added = sorted(right_set - left_set, key=str.lower)

            result[key] = {
                "label": label,
                "unchanged": unchanged,
                "removed": removed,
                "added": added,
                "left_count": len(left_set),
                "right_count": len(right_set),
                "changed": len(removed) + len(added) > 0,
            }

            # 提取变更项的行号（(start, end) 元组）
            left_lines_map = left.get("_lines", {}).get(key, {})
            right_lines_map = right.get("_lines", {}).get(key, {})
            changed_lines[key] = {
                "removed_lines": [left_lines_map.get(item, (0, 0)) for item in removed if item in left_lines_map],
                "added_lines": [right_lines_map.get(item, (0, 0)) for item in added if item in right_lines_map],
            }

        result["_changed_lines"] = changed_lines

        # 汇总
        total_changed = sum(
            1 for k in result
            if isinstance(result[k], dict) and result[k].get("changed")
        )
        result["summary"] = {
            "total_changed": total_changed,
            "has_changes": total_changed > 0,
            "identical": total_changed == 0,
        }

        return result