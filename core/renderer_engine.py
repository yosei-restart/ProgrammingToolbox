"""
GUI 元素探查器 - 截图标注引擎
使用 mss 高速截图 + Pillow 绘制高亮标注
"""

import os
import mss
import mss.tools
from PIL import Image, ImageDraw, ImageFont

from utils.logging_utils import get_logger

logger = get_logger(__name__)


# 输出目录
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")


def _ensure_output_dir():
    """确保截图输出目录存在"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def _get_font(size: int = 14) -> ImageFont.FreeTypeFont:
    """获取字体，优先使用系统字体"""
    font_paths = [
        "C:/Windows/Fonts/msyh.ttc",       # 微软雅黑
        "C:/Windows/Fonts/simhei.ttf",      # 黑体
        "C:/Windows/Fonts/simsun.ttc",      # 宋体
        "C:/Windows/Fonts/arial.ttf",       # Arial
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception as e:
                logger.debug("字体加载失败 %s: %s", path, e)
                continue
    return ImageFont.load_default()


def capture_fullscreen_with_highlight(
    left: int, top: int, width: int, height: int,
    label_text: str = "",
    output_filename: str = "inspector_screenshot_full.png"
) -> str:
    """
    全屏截图并在目标控件上绘制高亮边框

    Args:
        left, top, width, height: 控件在屏幕上的位置和尺寸
        label_text: 控件标签文字
        output_filename: 输出文件名

    Returns:
        截图文件路径
    """
    _ensure_output_dir()

    with mss.mss() as sct:
        # 获取主显示器截图
        monitor = sct.monitors[1]
        screenshot = sct.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)

    draw = ImageDraw.Draw(img)
    font = _get_font(14)
    font_bold = _get_font(16)

    # 绘制高亮边框（红色，4px 宽）
    for offset in range(4):
        draw.rectangle(
            [left - offset, top - offset, left + width + offset, top + height + offset],
            outline="#FF0000",
            width=1,
        )

    # 半透明红色遮罩填充
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle(
        [left, top, left + width, top + height],
        fill=(255, 0, 0, 40),
    )
    img = img.convert("RGBA")
    img = Image.alpha_composite(img, overlay)
    img = img.convert("RGB")

    draw = ImageDraw.Draw(img)

    # 绘制标签背景
    if label_text:
        text_bbox = draw.textbbox((0, 0), label_text, font=font_bold)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]

        label_x = left
        label_y = top - text_height - 12

        if label_y < 0:
            label_y = top + height + 4

        # 白色背景
        draw.rectangle(
            [label_x - 4, label_y - 2, label_x + text_width + 4, label_y + text_height + 2],
            fill="#FFFFFF",
            outline="#FF0000",
            width=1,
        )
        draw.text((label_x, label_y), label_text, fill="#FF0000", font=font_bold)

    output_path = os.path.join(OUTPUT_DIR, output_filename)
    img.save(output_path, "PNG")
    return output_path


def capture_element_closeup(
    left: int, top: int, width: int, height: int,
    margin: int = 40,
    output_filename: str = "inspector_screenshot_closeup.png"
) -> str:
    """
    控件特写截图（仅控件区域 + 边距）

    Returns:
        截图文件路径
    """
    _ensure_output_dir()

    # 计算截图区域，确保不超出屏幕边界
    capture_top = max(0, top - margin)
    capture_left = max(0, left - margin)
    capture_width = width + 2 * margin
    capture_height = height + 2 * margin

    region = {
        "top": capture_top,
        "left": capture_left,
        "width": capture_width,
        "height": capture_height,
    }

    with mss.mss() as sct:
        screenshot = sct.grab(region)
        img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)

    # 控件在截图中的实际位置（考虑边距裁剪）
    draw = ImageDraw.Draw(img)
    element_left = left - capture_left
    element_top = top - capture_top
    element_right = element_left + width
    element_bottom = element_top + height

    for offset in range(3):
        draw.rectangle(
            [
                element_left - offset,
                element_top - offset,
                element_right + offset,
                element_bottom + offset,
            ],
            outline="#FF0000",
            width=1,
        )

    output_path = os.path.join(OUTPUT_DIR, output_filename)
    img.save(output_path, "PNG")
    return output_path


def generate_screenshots(control_info: dict) -> tuple:
    """
    生成完整截图和特写截图

    Args:
        control_info: inspector_engine 提取的控件信息

    Returns:
        (full_path, closeup_path) 截图文件路径元组
    """
    logger.info("开始生成截图: %s", control_info.get("name", ""))
    pos = control_info["position"]
    left, top = pos["left"], pos["top"]
    width, height = pos["width"], pos["height"]

    label = f"{control_info['control_type_cn']}: {control_info['name']}"
    if len(label) > 60:
        label = label[:57] + "..."

    full_path = capture_fullscreen_with_highlight(
        left, top, width, height,
        label_text=label,
    )

    closeup_path = capture_element_closeup(
        left, top, width, height,
    )

    logger.info("截图生成完成: full=%s, closeup=%s", full_path, closeup_path)
    return full_path, closeup_path