"""
截图引擎 - 屏幕捕获、剪贴板操作、文件保存
使用 mss 捕获屏幕，Pillow 处理图像，PySide6 剪贴板复制
"""

import os
from typing import Optional

from PySide6.QtGui import QPixmap, QImage, QPainter, QGuiApplication
from PySide6.QtCore import QRect, QSize

from utils.logging_utils import get_logger

logger = get_logger(__name__)


def capture_screen(exclude_taskbar: bool = True) -> Optional[QPixmap]:
    """捕获屏幕画面

    使用 mss 捕获主屏幕，转换为 QPixmap

    Args:
        exclude_taskbar: 是否过滤掉 Windows 任务栏区域（默认 True）
            True  - 只截取工作区（availableGeometry，不含任务栏）
            False - 截取整个屏幕（geometry，包含任务栏）

    Returns:
        QPixmap: 截图画面，失败返回 None
    """
    # 获取截取区域
    screen = QGuiApplication.primaryScreen()
    if exclude_taskbar and screen is not None:
        # 工作区：去掉任务栏后的可用区域
        capture_geo = screen.availableGeometry()
    else:
        # 整个屏幕（包含任务栏）
        capture_geo = screen.geometry() if screen is not None else QRect(0, 0, 0, 0)

    try:
        import mss
        import mss.tools

        with mss.mss() as sct:
            # mss 使用屏幕绝对坐标
            capture_region = {
                "left": capture_geo.x(),
                "top": capture_geo.y(),
                "width": capture_geo.width(),
                "height": capture_geo.height(),
            }
            raw = sct.grab(capture_region)
            # 转换为 QImage 再转 QPixmap
            img = QImage(
                raw.rgb,
                capture_region["width"],
                capture_region["height"],
                QImage.Format_RGB888,
            )
            pixmap = QPixmap.fromImage(img)
            logger.info(
                "屏幕捕获成功: %dx%d (exclude_taskbar=%s, region=%dx%d@%d,%d)",
                pixmap.width(), pixmap.height(), exclude_taskbar,
                capture_region["width"], capture_region["height"],
                capture_region["left"], capture_region["top"],
            )
            return pixmap
    except Exception as e:
        logger.error("屏幕捕获失败: %s", e)
        # 降级方案：用 Qt 截屏（同样按工作区截取）
        try:
            if screen is not None:
                pixmap = screen.grabWindow(
                    0,
                    capture_geo.x(), capture_geo.y(),
                    capture_geo.width(), capture_geo.height(),
                )
                logger.info(
                    "屏幕捕获成功（Qt降级）: %dx%d (exclude_taskbar=%s)",
                    pixmap.width(), pixmap.height(), exclude_taskbar,
                )
                return pixmap
        except Exception as e2:
            logger.error("Qt降级截屏也失败: %s", e2)
        return None


def copy_to_clipboard(pixmap: QPixmap) -> bool:
    """将 QPixmap 复制到系统剪贴板

    Args:
        pixmap: 要复制的图像

    Returns:
        bool: 是否成功
    """
    try:
        clipboard = QGuiApplication.clipboard()
        clipboard.setPixmap(pixmap)
        logger.info("已复制到剪贴板")
        return True
    except Exception as e:
        logger.error("复制到剪贴板失败: %s", e)
        return False


def save_screenshot(pixmap: QPixmap, file_path: str) -> bool:
    """保存截图到文件

    Args:
        pixmap: 要保存的图像
        file_path: 保存路径（支持 .png/.jpg/.bmp）

    Returns:
        bool: 是否成功
    """
    try:
        # 确保目录存在
        dir_path = os.path.dirname(file_path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path)

        # 根据扩展名选择格式
        ext = os.path.splitext(file_path)[1].lower()
        fmt_map = {
            ".png": "PNG",
            ".jpg": "JPG",
            ".jpeg": "JPG",
            ".bmp": "BMP",
        }
        fmt = fmt_map.get(ext, "PNG")

        pixmap.save(file_path, fmt)
        logger.info("截图已保存: %s", file_path)
        return True
    except Exception as e:
        logger.error("保存截图失败: %s", e)
        return False
