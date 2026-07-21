"""
GUI 元素探查器 - 剪贴板工具
支持将文本、图片复制到系统剪贴板
所有 subprocess 调用均使用 CREATE_NO_WINDOW 防止弹出控制台窗口
路径参数经过严格转义，防止命令注入
"""

import logging
import os
import platform
import subprocess

from utils.logging_utils import get_logger

logger = get_logger(__name__)

# Windows 创建进程标志：不创建控制台窗口
CREATE_NO_WINDOW = 0x08000000

# PowerShell 超时时间（秒）
POWERSHELL_TIMEOUT = 10


def _escape_path_for_powershell(path: str) -> str:
    """
    对文件路径进行 PowerShell 安全转义，防止命令注入。

    使用单引号包裹路径，并对路径中的单引号进行双单引号转义。
    PowerShell 单引号字符串中，唯一需要转义的是单引号本身（用两个单引号表示一个）。

    Args:
        path: 原始文件路径

    Returns:
        转义后可安全用于 PowerShell 单引号字符串的路径
    """
    # 将路径中的单引号替换为双单引号（PowerShell 转义规则）
    escaped = path.replace("'", "''")
    return f"'{escaped}'"


def copy_to_clipboard(text: str) -> bool:
    """
    将文本复制到系统剪贴板

    Args:
        text: 要复制的文本内容

    Returns:
        是否复制成功
    """
    try:
        if platform.system() == "Windows":
            process = subprocess.Popen(
                ["clip"],
                stdin=subprocess.PIPE,
                shell=True,
                creationflags=CREATE_NO_WINDOW,
            )
            process.communicate(
                input=text.encode("utf-16-le", errors="replace")
            )
            process.wait()
            logger.info("文本已复制到剪贴板 (长度: %d)", len(text))
            return True
        else:
            cmd = (
                ["pbcopy"]
                if platform.system() == "Darwin"
                else ["xclip", "-selection", "clipboard"]
            )
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            process.communicate(input=text.encode("utf-8"))
            return True
    except Exception as e:
        logger.error("复制文本到剪贴板失败: %s", e, exc_info=True)
        return False


def copy_image_to_clipboard(image_path: str) -> bool:
    """
    将图片文件复制到剪贴板（仅 Windows）

    使用参数化路径传递，避免命令注入风险。

    Args:
        image_path: 图片文件路径

    Returns:
        是否复制成功
    """
    if platform.system() != "Windows":
        return False

    # 验证文件存在
    if not os.path.exists(image_path):
        logger.error("图片文件不存在: %s", image_path)
        return False

    try:
        safe_path = _escape_path_for_powershell(image_path)
        ps_script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "Add-Type -AssemblyName System.Drawing;"
            f"$img = [System.Drawing.Image]::FromFile({safe_path});"
            "[System.Windows.Forms.Clipboard]::SetImage($img);"
            "$img.Dispose()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            timeout=POWERSHELL_TIMEOUT,
            creationflags=CREATE_NO_WINDOW,
        )
        logger.info("图片已复制到剪贴板: %s", image_path)
        return True
    except subprocess.TimeoutExpired:
        logger.error("PowerShell 复制图片超时")
        return False
    except Exception as e:
        logger.error("复制图片到剪贴板失败: %s", e, exc_info=True)
        return False
