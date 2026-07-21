"""
辅助编程工具箱 - 共享主题模块
采用色温分层深色主题，Noto Sans SC 开源商用字体
- 背景色温：中性暗 → 偏暖 → 偏冷 → 反向，用色相区分层级
- 字体：Noto Sans SC (SIL Open Font License)，全系列加粗
- 字号：主标题 20px / 区块标题 16px / 正文 14px / 代码 13px / 辅助 12px
"""

from PySide6.QtGui import QFont
from PySide6.QtCore import Qt

# ── 配色（色温分层深色主题）──
# 设计理念：不同层级用不同色温，而非同一色相的不同明度
COLORS = {
    "bg": "#0F0F14",        # 主背景 - 中性暗
    "fg": "#E0E0F0",        # 主文字 - 高亮
    "panel": "#191926",     # 面板背景 - 偏暖暗
    "accent": "#7EB6FF",    # 强调蓝 - 更鲜艳
    "ahover": "#99CCFF",    # 悬浮蓝
    "ok": "#7EE07E",        # 成功绿 - 更鲜艳
    "warn": "#F5D76E",      # 警告黄 - 更鲜艳
    "err": "#F07080",       # 错误红 - 更鲜艳
    "border": "#2D2D45",    # 边框 - 可见但柔和
    "input": "#151520",     # 输入框背景 - 比卡片更深（反向）
    "head": "#0A0A10",      # 标题栏 - 最暗
    "title": "#C4A0FF",     # 标题紫 - 更鲜艳
    "dim": "#9090A8",       # 次要文字 - 更亮可读
    "hl": "#F0A860",        # 高亮橙 - 更鲜艳
    "copy": "#3A3A55",      # 复制按钮背景
    "orange": "#F0A860",    # 橙色
    "card_bg": "#1E1E30",   # 卡片背景 - 偏冷暗，带蓝调
    "card_hover": "#282840", # 卡片悬浮
    # 色彩分区：每个功能区块的左边框颜色
    "sec_purple": "#C4A0FF",
    "sec_blue": "#7EB6FF",
    "sec_green": "#7EE07E",
    "sec_gray": "#9090A8",
    "sec_orange": "#F0A860",
    "sec_gold": "#F5D76E",
    # 生命周期阶段颜色
    "birth": "#7EE07E",     # 诞生 - 绿色
    "flow": "#7EB6FF",      # 流转 - 蓝色
    "use": "#9090A8",       # 使用 - 灰色
    "branch": "#F0A860",    # 分支 - 橙色
    "death": "#F07080",     # 消亡 - 红色
}


def make_font(family: str, size: int, bold: bool = False, weight: int = None) -> QFont:
    """创建字体对象"""
    f = QFont(family, size)
    if bold:
        f.setBold(True)
    if weight is not None:
        f.setWeight(QFont.Weight(weight))
    return f


# 预定义字体（Noto Sans SC 开源商用 + Consolas 等宽代码）
# 全系列加粗：主标题 20px / 区块标题 16px / 正文 14px / 代码 13px / 辅助 12px
FONT_TITLE = make_font("Noto Sans SC", 20, weight=900)       # H1: 主标题 Black
FONT_SUBHEADER = make_font("Noto Sans SC", 15, weight=700)    # H2.5: 子标题 Bold
FONT_HEADER = make_font("Noto Sans SC", 16, weight=700)       # H2: 区块标题 Bold
FONT_BODY = make_font("Noto Sans SC", 14, weight=700)         # Body: 正文 Bold
FONT_MONO = make_font("Consolas", 13, weight=500)             # Code: 代码 Medium
FONT_SMALL = make_font("Noto Sans SC", 12, weight=500)        # Caption: 辅助 Medium
FONT_STATUS = make_font("Noto Sans SC", 12, weight=500)       # Status: 状态栏 Medium
FONT_CAPTION = make_font("Noto Sans SC", 11, weight=500)      # Caption2: 行号/文件名
FONT_TINY = make_font("Noto Sans SC", 10, weight=500)         # Tiny: 表格脚注/极简说明

# 字号数值常量（用于 HTML inline style 中的 font-size）
FONT_SIZE_TITLE = FONT_TITLE.pointSize()       # 20
FONT_SIZE_SUBHEADER = FONT_SUBHEADER.pointSize()  # 15
FONT_SIZE_HEADER = FONT_HEADER.pointSize()      # 16
FONT_SIZE_BODY = FONT_BODY.pointSize()          # 14
FONT_SIZE_MONO = FONT_MONO.pointSize()          # 13
FONT_SIZE_SMALL = FONT_SMALL.pointSize()        # 12
FONT_SIZE_CAPTION = FONT_CAPTION.pointSize()    # 11
FONT_SIZE_TINY = FONT_TINY.pointSize()          # 10
FONT_SIZE_ICON_LARGE = 24                         # 大图标字号（⚠等）


def get_global_stylesheet() -> str:
    """返回全局样式表，供所有窗口使用

    每个组件类型都明确设置 color，避免继承失效问题。
    """
    C = COLORS
    return f"""
        QMainWindow {{
            background: {C['bg']};
        }}
        QWidget {{
            background: {C['bg']};
            color: {C['fg']};
            font-family: "Noto Sans SC";
        }}
        QLabel {{
            background: transparent;
            color: {C['fg']};
        }}
        QPushButton {{
            background: {C['panel']};
            color: {C['fg']};
            border: 1px solid {C['border']};
            border-radius: 8px;
            padding: 8px 16px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background: {C['border']};
            color: {C['accent']};
            border: 1px solid {C['accent']};
        }}
        QPushButton:disabled {{
            background: {C['panel']};
            color: {C['dim']};
            border: 1px solid {C['border']};
        }}
        QLineEdit {{
            background: {C['input']};
            color: {C['fg']};
            border: 1px solid {C['border']};
            border-radius: 8px;
            padding: 8px 12px;
        }}
        QLineEdit:focus {{
            border: 1px solid {C['accent']};
        }}
        QLineEdit:read-only {{
            background: {C['panel']};
            color: {C['dim']};
        }}
        QTextEdit {{
            background: {C['panel']};
            color: {C['fg']};
            border: 1px solid {C['border']};
            border-radius: 8px;
            padding: 10px 12px;
        }}
        QScrollArea {{
            border: none;
            background: transparent;
        }}
        QScrollBar:vertical {{
            background: transparent;
            width: 14px;
            margin: 0;
        }}
        QScrollBar::handle:vertical {{
            background: #4a90d9;
            border-radius: 7px;
            min-height: 30px;
            margin: 3px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: #5da8f5;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QScrollBar:horizontal {{
            background: transparent;
            height: 14px;
            margin: 0;
        }}
        QScrollBar::handle:horizontal {{
            background: #4a90d9;
            border-radius: 7px;
            min-width: 30px;
            margin: 3px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: #5da8f5;
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0;
        }}
        QListWidget {{
            background: {C['panel']};
            color: {C['fg']};
            border: 1px solid {C['border']};
            border-radius: 8px;
            padding: 4px;
        }}
        QListWidget::item {{
            padding: 6px 8px;
            border-radius: 4px;
        }}
        QListWidget::item:hover {{
            background: {C['border']};
        }}
        QListWidget::item:selected {{
            background: {C['accent']};
            color: {C['head']};
        }}
        QSplitter::handle {{
            background: {C['border']};
            width: 2px;
        }}
        QComboBox {{
            background: {C['input']};
            color: {C['fg']};
            border: 1px solid {C['border']};
            border-radius: 8px;
            padding: 8px 12px;
        }}
        QComboBox QAbstractItemView {{
            background: {C['panel']};
            color: {C['fg']};
            selection-background-color: {C['accent']};
            selection-color: {C['head']};
            border: 1px solid {C['border']};
        }}
        QProgressBar {{
            background: {C['border']};
            border: none;
            border-radius: 2px;
        }}
        QProgressBar::chunk {{
            background: {C['accent']};
            border-radius: 2px;
        }}
    """


def apply_text_selectable(widget):
    """递归设置所有 QLabel 文字可鼠标选中和复制

    用法：在窗口 __init__ 末尾调用 apply_text_selectable(self)
    """
    from PySide6.QtWidgets import QLabel
    for child in widget.findChildren(QLabel):
        child.setTextInteractionFlags(Qt.TextSelectableByMouse)