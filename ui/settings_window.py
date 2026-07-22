"""
AI 设置窗口

设计参考：选择本地模型类型时即时检测模型列表，显示清晰反馈。
支持 Ollama（命令行 ollama list）和 LM Studio（HTTP /v1/models）。

依赖：PySide6（LGPLv3，开源，企业免费，商用可用）
"""

from __future__ import annotations

import threading

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QCheckBox, QFrame, QTextEdit,
    QScrollArea, QTabWidget, QSizePolicy, QMessageBox,
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer

from utils.theme import COLORS, FONT_TITLE, FONT_HEADER, FONT_BODY, FONT_SMALL, FONT_MONO, FONT_SIZE_BODY, get_global_stylesheet, apply_text_selectable
from ai.ai_config import AIConfig, load_config, save_config
from ai.prompts_config import load_prompts, save_prompts, DEFAULT_PROMPTS, PROMPT_KEYS, PROMPT_LABELS, PROMPT_PLACEHOLDERS
from ai.ai_client import chat_completion
from utils.logging_utils import get_logger

logger = get_logger(__name__)

# 云端 API 预设
_CLOUD_APIS = [
    ("https://api.deepseek.com/v1", "DeepSeek (深度求索)", "deepseek-chat"),
    ("https://api.openai.com/v1", "OpenAI", "gpt-4o"),
    ("https://open.bigmodel.cn/api/paas/v4", "智谱 AI (ChatGLM)", "glm-4-flash"),
    ("https://api.moonshot.cn/v1", "月之暗面 (Kimi)", "moonshot-v1-8k"),
    ("https://apihub.agnes-ai.com/v1", "Agnes AI", "agnes-2.0-flash"),
]

# 本地服务预设
_LOCAL_SERVICES = [
    ("Ollama", "http://localhost:11434/v1"),
    ("LM Studio", "http://127.0.0.1:1234/v1"),
]

_MODEL_VENDOR_MAP = {
    "qwen": "阿里通义千问", "qwq": "阿里通义千问",
    "llama": "Meta", "mistral": "Mistral AI", "mixtral": "Mistral AI",
    "gemma": "Google", "deepseek": "深度求索", "phi": "微软",
    "yi": "零一万物", "baichuan": "百川",
    "chatglm": "智谱", "glm": "智谱", "codellama": "Meta Code",
}


class SettingsSignals(QObject):
    status = Signal(str, str)
    config_saved = Signal(bool)
    models_detected = Signal(bool, list, str)
    ollama_started = Signal(bool, str)  # success, message
    show_error = Signal(str, str)  # title, message


class SettingsWindow(QWidget):
    """AI 设置窗口"""

    def __init__(self, on_back=None):
        super().__init__()
        self.setWindowTitle("大模型接入/截图热键")
        self.resize(720, 850)
        self.setMinimumSize(640, 850)
        self._on_back = on_back
        self._config = load_config()
        self._key_placeholder_active = True
        self._detecting = False

        self.setStyleSheet(get_global_stylesheet())
        self.sig = SettingsSignals()
        self.sig.status.connect(self._on_status)
        self.sig.config_saved.connect(self._on_config_saved)
        self.sig.models_detected.connect(self._on_models_detected)
        self.sig.ollama_started.connect(self._on_ollama_started)
        self.sig.show_error.connect(self._on_show_error)

        self._build_ui()
        self._load_config_to_ui()
        apply_text_selectable(self)

    # ─── UI 构建 ───

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏
        header = QFrame()
        header.setFixedHeight(56)
        header.setStyleSheet(f"background:{COLORS['head']};border:none")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(24, 6, 24, 12)
        if self._on_back:
            btn_back = QPushButton("← 返回")
            btn_back.setFont(FONT_SMALL)
            btn_back.setStyleSheet(f"QPushButton{{background:transparent;color:{COLORS['accent']};border:none}}")
            btn_back.clicked.connect(self._go_back)
            hl.addWidget(btn_back)
        title = QLabel("大模型接入/截图热键")
        title.setFont(FONT_TITLE)
        title.setStyleSheet(f"color:{COLORS['accent']};background:transparent")
        hl.addWidget(title)
        hl.addStretch()
        layout.addWidget(header)

        content = QWidget()
        content.setStyleSheet(f"background:{COLORS['bg']}")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(24, 16, 24, 16)
        cl.setSpacing(8)

        # 说明
        info = QLabel(
            "配置 AI API 后，可让 AI 解释控件作用、分析变量变化、分析图片内容。\n"
            "支持 OpenAI 兼容 API：云端（DeepSeek/OpenAI/智谱/Kimi 等）和本地模型（Ollama/LM Studio 等）。"
        )
        info.setFont(FONT_SMALL)
        info.setWordWrap(True)
        info.setStyleSheet(f"color:{COLORS['dim']};background:transparent")
        cl.addWidget(info)

        # 启用
        enable_row = QHBoxLayout()
        enable_row.setSpacing(8)
        self._chk_enable = QCheckBox("启用 AI 功能")
        self._chk_enable.setFont(FONT_BODY)
        self._chk_enable.setStyleSheet(f"QCheckBox{{color:{COLORS['fg']};background:transparent;font-size:{FONT_SIZE_BODY}px}}")
        enable_row.addWidget(self._chk_enable)
        enable_row.addStretch()
        self._status_label = QLabel("")
        self._status_label.setFont(FONT_SMALL)
        self._status_label.setWordWrap(False)
        self._status_label.setStyleSheet(f"color:{COLORS['dim']};background:transparent")
        self._status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._status_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        enable_row.addWidget(self._status_label)
        cl.addLayout(enable_row)

        # 模型配置选项卡
        self._tab_widget = QTabWidget()
        self._tab_widget.setStyleSheet(
            f"QTabWidget::pane{{border:1px solid {COLORS['border']};border-radius:8px;background:{COLORS['panel']};}}"
            f"QTabBar::tab{{background:{COLORS['panel']};color:{COLORS['dim']};padding:8px 16px;border-radius:6px;margin-right:4px;}}"
            f"QTabBar::tab:selected{{background:{COLORS['accent']};color:white;}}"
        )

        # 选项卡1：文字语言模型
        text_tab = QWidget()
        text_layout = QVBoxLayout(text_tab)
        text_layout.setContentsMargins(16, 12, 16, 12)
        text_layout.setSpacing(8)
        self._build_text_model_tab(text_layout)
        self._tab_widget.addTab(text_tab, "文字语言模型")

        # 选项卡2：图像识别模型
        image_tab = QWidget()
        image_layout = QVBoxLayout(image_tab)
        image_layout.setContentsMargins(16, 12, 16, 12)
        image_layout.setSpacing(8)
        self._build_image_model_tab(image_layout)
        self._tab_widget.addTab(image_tab, "图像识别模型")

        # 选项卡3：AI 提示词
        prompts_tab = QWidget()
        prompts_layout = QVBoxLayout(prompts_tab)
        prompts_layout.setContentsMargins(16, 12, 16, 12)
        prompts_layout.setSpacing(8)
        self._build_prompts_tab(prompts_layout)
        self._tab_widget.addTab(prompts_tab, "AI 提示词")

        cl.addWidget(self._tab_widget)

        # 按钮区
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self._btn_test = QPushButton("测试连接")
        self._btn_test.setFont(FONT_BODY)
        self._btn_test.setStyleSheet(
            f"QPushButton{{background:{COLORS['panel']};color:{COLORS['accent']};"
            f"border:1px solid {COLORS['accent']};border-radius:6px;padding:8px 16px}}"
            f"QPushButton:hover{{border:2px solid {COLORS['hl']};}}"
        )
        self._btn_test.clicked.connect(self._on_test)
        btn_row.addWidget(self._btn_test)
        btn_row.addStretch()
        self._btn_save = QPushButton("保存配置")
        self._btn_save.setFont(FONT_BODY)
        self._btn_save.setStyleSheet(
            f"QPushButton{{background:{COLORS['accent']};color:{COLORS['head']};"
            f"border:none;border-radius:6px;padding:8px 20px;font-weight:bold}}"
            f"QPushButton:hover{{background:{COLORS['hl']};}}"
        )
        self._btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(self._btn_save)
        cl.addLayout(btn_row)

        # 截图热键配置
        cl.addWidget(self._label("截图热键"))
        hk_row = QHBoxLayout()
        from utils.hotkey_handler import get_screenshot_hotkey_display
        self._screenshot_hk_label = QLabel(f"当前：{get_screenshot_hotkey_display()}")
        self._screenshot_hk_label.setFont(FONT_BODY)
        self._screenshot_hk_label.setStyleSheet(f"color:{COLORS['fg']};background:transparent")
        hk_row.addWidget(self._screenshot_hk_label)
        self._btn_set_screenshot_hk = QPushButton("修改截图热键")
        self._btn_set_screenshot_hk.setFont(FONT_SMALL)
        self._btn_set_screenshot_hk.setStyleSheet(
            f"QPushButton{{background:{COLORS['panel']};color:{COLORS['accent']};border:1px solid {COLORS['border']};border-radius:6px;padding:4px 12px}}"
            f"QPushButton:hover{{border:1px solid {COLORS['accent']}}}"
        )
        self._btn_set_screenshot_hk.clicked.connect(self._on_set_screenshot_hotkey)
        hk_row.addWidget(self._btn_set_screenshot_hk)
        cl.addLayout(hk_row)
        cl.addStretch()

        # 将内容区放入滚动区域，避免窗口高度不足时文字被截断
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:{COLORS['bg']};}}"
            f"QScrollBar:vertical{{background:transparent;width:14px;border-radius:7px}}"
            f"QScrollBar::handle:vertical{{background:{COLORS['accent']};border-radius:7px;min-height:30px}}"
            f"QScrollBar::handle:vertical:hover{{background:{COLORS['hl']}}}"
        )
        layout.addWidget(scroll, 1)

        # Tab 循环
        self.setTabOrder(self._url_combo, self._key_edit)
        self.setTabOrder(self._key_edit, self._model_combo)
        self.setTabOrder(self._model_combo, self._url_combo)

    def _label(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setFont(FONT_BODY)
        l.setStyleSheet(f"color:{COLORS['fg']};background:transparent;font-weight:bold")
        return l

    def _combo_style(self) -> str:
        return (f"QComboBox{{background:{COLORS['input']};color:{COLORS['fg']};"
                f"border:1px solid {COLORS['border']};border-radius:6px;padding:6px 10px}}")

    def _build_text_model_tab(self, layout):
        """构建文字语言模型选项卡"""
        # 模型类型
        layout.addWidget(self._label("模型类型"))
        self._type_combo = QComboBox()
        self._type_combo.setFont(FONT_BODY)
        self._type_combo.addItem("网络模型调用", "cloud")
        self._type_combo.addItem("本地模型调用", "local")
        self._type_combo.setStyleSheet(self._combo_style())
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        layout.addWidget(self._type_combo)

        # 本地提示
        self._local_hint = QLabel("")
        self._local_hint.setFont(FONT_SMALL)
        self._local_hint.setWordWrap(True)
        self._local_hint.setStyleSheet(f"color:{COLORS['ok']};background:transparent")
        self._local_hint.hide()
        layout.addWidget(self._local_hint)

        # Base URL
        layout.addWidget(self._label("API Base URL（接口地址）"))
        self._url_combo = QComboBox()
        self._url_combo.setEditable(True)
        self._url_combo.setFont(FONT_BODY)
        self._url_combo.setStyleSheet(self._combo_style())
        layout.addWidget(self._url_combo)

        # Base URL 提示
        self._url_hint = QLabel("")
        self._url_hint.setFont(FONT_SMALL)
        self._url_hint.setStyleSheet(f"color:{COLORS['dim']};background:transparent")
        self._url_hint.hide()
        layout.addWidget(self._url_hint)

        # API Key
        layout.addWidget(self._label("API Key（密钥）"))
        self._key_edit = QLineEdit()
        self._key_edit.setFont(FONT_MONO)
        self._key_edit.setEchoMode(QLineEdit.Password)
        self._key_edit.setPlaceholderText("请输入 API Key")
        self._key_edit.setStyleSheet(
            f"QLineEdit{{background:{COLORS['input']};color:{COLORS['fg']};"
            f"border:1px solid {COLORS['border']};border-radius:6px;padding:6px 10px;font-family:Consolas}}"
        )
        self._key_edit.focusInEvent = self._on_key_focus_in
        layout.addWidget(self._key_edit)

        # 模型名
        model_row = QHBoxLayout()
        model_row.addWidget(self._label("模型名（Model）"))
        model_row.addStretch()
        self._btn_refresh = QPushButton("刷新模型列表")
        self._btn_refresh.setFont(FONT_SMALL)
        self._btn_refresh.setCursor(Qt.PointingHandCursor)
        self._btn_refresh.setStyleSheet(
            f"QPushButton{{background:transparent;color:{COLORS['accent']};"
            f"border:1px solid {COLORS['accent']};border-radius:4px;padding:2px 10px}} "
            f"QPushButton:hover{{background:{COLORS['accent']};color:{COLORS['head']}}} "
            f"QPushButton:disabled{{color:{COLORS['dim']};border:1px solid {COLORS['dim']}}}"
        )
        self._btn_refresh.clicked.connect(self._on_refresh_models)
        self._btn_refresh.hide()
        model_row.addWidget(self._btn_refresh)

        self._btn_start_ollama = QPushButton("🔄 启动 Ollama")
        self._btn_start_ollama.setFont(FONT_SMALL)
        self._btn_start_ollama.setCursor(Qt.PointingHandCursor)
        self._btn_start_ollama.setStyleSheet(
            f"QPushButton{{background:{COLORS['warn']};color:{COLORS['head']};"
            f"border:none;border-radius:4px;padding:2px 10px;font-weight:bold}} "
            f"QPushButton:hover{{background:#e6a817}} "
            f"QPushButton:disabled{{background:{COLORS['border']};color:{COLORS['dim']}}}"
        )
        self._btn_start_ollama.clicked.connect(self._on_start_ollama)
        self._btn_start_ollama.hide()
        model_row.addWidget(self._btn_start_ollama)
        layout.addLayout(model_row)

        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.setFont(FONT_BODY)
        self._model_combo.setStyleSheet(self._combo_style())
        layout.addWidget(self._model_combo)

        # 模型检测状态
        self._model_status = QLabel("")
        self._model_status.setFont(FONT_SMALL)
        self._model_status.setWordWrap(True)
        self._model_status.hide()
        layout.addWidget(self._model_status)

        layout.addStretch()

    def _build_image_model_tab(self, layout):
        """构建图像识别模型选项卡"""
        # 模型类型
        layout.addWidget(self._label("模型类型"))
        self._image_type_combo = QComboBox()
        self._image_type_combo.setFont(FONT_BODY)
        self._image_type_combo.addItem("网络模型调用", "cloud")
        self._image_type_combo.addItem("本地模型调用", "local")
        self._image_type_combo.setStyleSheet(self._combo_style())
        self._image_type_combo.currentIndexChanged.connect(self._on_image_type_changed)
        layout.addWidget(self._image_type_combo)

        # 本地提示
        self._image_local_hint = QLabel("")
        self._image_local_hint.setFont(FONT_SMALL)
        self._image_local_hint.setWordWrap(True)
        self._image_local_hint.setStyleSheet(f"color:{COLORS['ok']};background:transparent")
        self._image_local_hint.hide()
        layout.addWidget(self._image_local_hint)

        # Base URL
        layout.addWidget(self._label("图像模型 Base URL"))
        self._image_url_combo = QComboBox()
        self._image_url_combo.setEditable(True)
        self._image_url_combo.setFont(FONT_BODY)
        self._image_url_combo.setStyleSheet(self._combo_style())
        layout.addWidget(self._image_url_combo)

        # API Key
        layout.addWidget(self._label("图像模型 API Key（为空则使用文字模型的 Key）"))
        self._image_key_edit = QLineEdit()
        self._image_key_edit.setFont(FONT_MONO)
        self._image_key_edit.setEchoMode(QLineEdit.Password)
        self._image_key_edit.setPlaceholderText("请输入图像模型 API Key（可选）")
        self._image_key_edit.setStyleSheet(
            f"QLineEdit{{background:{COLORS['input']};color:{COLORS['fg']};"
            f"border:1px solid {COLORS['border']};border-radius:6px;padding:6px 10px;font-family:Consolas}}"
        )
        layout.addWidget(self._image_key_edit)

        # 模型名
        layout.addWidget(self._label("图像模型名（Model）"))
        self._image_model_combo = QComboBox()
        self._image_model_combo.setEditable(True)
        self._image_model_combo.setFont(FONT_BODY)
        self._image_model_combo.setStyleSheet(self._combo_style())
        layout.addWidget(self._image_model_combo)

        # 说明
        self._image_hint = QLabel(
            "提示：图像识别模型需要支持多模态（如 glm-4v、gpt-4o）\n"
            "用于截图标注工具中的 AI 图片分析功能"
        )
        self._image_hint.setFont(FONT_SMALL)
        self._image_hint.setWordWrap(True)
        self._image_hint.setStyleSheet(f"color:{COLORS['dim']};background:transparent")
        layout.addWidget(self._image_hint)

        layout.addStretch()

    def _build_prompts_tab(self, layout: QVBoxLayout):
        """构建 AI 提示词 tab：4 个可编辑 QTextEdit + 重置按钮 + 保存按钮

        Args:
            layout: QVBoxLayout 父布局
        """
        # 提示信息
        hint_label = QLabel("💡 修改提示词后点击底部「保存配置」按钮生效。删除全部内容将自动恢复为默认值。")
        hint_label.setFont(FONT_SMALL)
        hint_label.setStyleSheet(f"QLabel{{color:{COLORS['dim']};background:transparent;padding:8px;}}")
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)

        # 用 QScrollArea 包裹 4 个提示词编辑区，避免内容超出窗口
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{border:none;background:transparent;}}")

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(12)

        # 4 个提示词编辑区
        self._prompt_edits = {}  # key -> QTextEdit
        for key in PROMPT_KEYS:
            label_info = PROMPT_LABELS[key]

            # 标题行：提示词名称 + 重置按钮
            header_row = QHBoxLayout()
            header_row.setContentsMargins(0, 0, 0, 0)
            header_row.setSpacing(8)

            name_label = QLabel(f"📝 {label_info['name']}")
            name_label.setFont(FONT_HEADER)
            name_label.setStyleSheet(f"QLabel{{color:{COLORS['title']};background:transparent;}}")
            header_row.addWidget(name_label)

            header_row.addStretch()

            reset_btn = QPushButton("重置为默认")
            reset_btn.setFont(FONT_SMALL)
            reset_btn.setFixedHeight(28)
            reset_btn.setCursor(Qt.PointingHandCursor)
            reset_btn.setStyleSheet(
                f"QPushButton{{background:{COLORS['panel']};color:{COLORS['dim']};"
                f"border:1px solid {COLORS['border']};border-radius:4px;padding:0 10px;}}"
                f"QPushButton:hover{{background:{COLORS['input']};color:{COLORS['fg']};}}"
            )
            reset_btn.clicked.connect(lambda checked=False, k=key: self._on_reset_single_prompt(k))
            header_row.addWidget(reset_btn)

            scroll_layout.addLayout(header_row)

            # 用途说明
            desc_label = QLabel(label_info['description'])
            desc_label.setFont(FONT_SMALL)
            desc_label.setStyleSheet(f"QLabel{{color:{COLORS['dim']};background:transparent;padding:0 4px;}}")
            desc_label.setWordWrap(True)
            scroll_layout.addWidget(desc_label)

            # 占位符提示
            placeholders = PROMPT_PLACEHOLDERS.get(key, [])
            if placeholders:
                ph_text = "可用占位符：" + "  ".join(placeholders)
                ph_label = QLabel(ph_text)
                ph_label.setFont(FONT_SMALL)
                ph_label.setStyleSheet(f"QLabel{{color:{COLORS['accent']};background:transparent;padding:0 4px;}}")
                ph_label.setWordWrap(True)
                scroll_layout.addWidget(ph_label)

            # QTextEdit 编辑框
            edit = QTextEdit()
            edit.setFont(FONT_MONO)
            edit.setMinimumHeight(100)
            edit.setLineWrapMode(QTextEdit.WidgetWidth)
            edit.setStyleSheet(
                f"QTextEdit{{background:{COLORS['input']};color:{COLORS['fg']};"
                f"border:1px solid {COLORS['border']};border-radius:6px;padding:8px;}}"
                f"QTextEdit:focus{{border:1px solid {COLORS['accent']};}}"
            )
            scroll_layout.addWidget(edit)

            self._prompt_edits[key] = edit

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, 1)

    def _load_prompts_to_ui(self):
        """从 prompts_config 加载提示词到 4 个 QTextEdit"""
        prompts = load_prompts()
        for key, edit in self._prompt_edits.items():
            text = prompts.get(key, DEFAULT_PROMPTS.get(key, ""))
            edit.setPlainText(text)

    def _on_reset_single_prompt(self, key: str):
        """重置某个 QTextEdit 为 DEFAULT_PROMPTS[key]

        注意：不立即写入 prompts.json，需用户点击「保存所有提示词」才生效。
        """
        default_text = DEFAULT_PROMPTS.get(key, "")
        if key in self._prompt_edits:
            self._prompt_edits[key].setPlainText(default_text)
            name = PROMPT_LABELS[key]['name']
            self._status_label.setText(f"已重置「{name}」为默认值（需点击保存按钮生效）")

    def _on_save_prompts(self):
        """保存 4 个 QTextEdit 的内容到 prompts.json"""
        prompts = {}
        for key, edit in self._prompt_edits.items():
            prompts[key] = edit.toPlainText()

        if save_prompts(prompts):
            self._status_label.setText("✅ 提示词已保存")
            logger.info("AI 提示词已保存到 %s", "~/.gui_inspector/prompts.json")
        else:
            self._status_label.setText("❌ 保存失败，请查看日志")

    def _on_image_type_changed(self):
        """图像模型类型切换"""
        if self._image_type_combo.currentData() == "cloud":
            self._set_image_cloud_mode()
        else:
            self._set_image_local_mode()

    # 图像模型预设：(URL, 标签, 模型名)
    _IMAGE_CLOUD_APIS = [
        ("https://open.bigmodel.cn/api/paas/v4", "智谱 AI (ChatGLM)", "glm-4v"),
        ("https://api.openai.com/v1", "OpenAI", "gpt-4o"),
        ("https://api.deepseek.com/v1", "DeepSeek", "deepseek-chat"),
        ("https://apihub.agnes-ai.com/v1", "Agnes AI", "agnes-2.0-flash"),
    ]

    def _set_image_cloud_mode(self):
        """图像模型 - 网络模式"""
        self._image_local_hint.hide()
        self._image_url_combo.clear()
        for url, label, _ in self._IMAGE_CLOUD_APIS:
            self._image_url_combo.addItem(f"{url}  — {label}", url)
        self._image_model_combo.clear()
        for url, label, model in self._IMAGE_CLOUD_APIS:
            self._image_model_combo.addItem(f"{model}  — {label}", model)
        self._image_url_combo.currentIndexChanged.connect(self._on_image_cloud_url_changed)
        self._image_key_edit.setReadOnly(False)
        self._image_key_edit.setEchoMode(QLineEdit.Password)
        self._image_key_edit.setPlaceholderText("请输入图像模型 API Key（可选）")
        self._image_key_edit.setStyleSheet(
            f"QLineEdit{{background:{COLORS['input']};color:{COLORS['fg']};"
            f"border:1px solid {COLORS['border']};border-radius:6px;padding:6px 10px;font-family:Consolas}}"
        )
        self._image_hint.setText(
            "提示：图像识别模型需要支持多模态（如 glm-4v、gpt-4o）\n"
            "用于截图标注工具中的 AI 图片分析功能"
        )

    def _set_image_local_mode(self):
        """图像模型 - 本地模式"""
        self._image_local_hint.setText("ℹ️ 本地服务不需要 API Key")
        self._image_local_hint.setStyleSheet(f"color:{COLORS['ok']};background:transparent")
        self._image_local_hint.show()
        self._image_url_combo.clear()
        for name, url in _LOCAL_SERVICES:
            self._image_url_combo.addItem(f"{url}  — 本地 {name}", url)
        self._image_model_combo.clear()
        self._image_model_combo.setEditText("")
        self._image_key_edit.setReadOnly(True)
        self._image_key_edit.setEchoMode(QLineEdit.Normal)
        self._image_key_edit.setText("本地模型不需要输入")
        self._image_key_edit.setStyleSheet(
            f"QLineEdit{{background:#fff3cd;color:#dc3545;"
            f"border:1px solid #ffc107;border-radius:6px;padding:6px 10px;"
            f"font-family:Consolas;font-weight:bold}}"
        )
        self._image_hint.setText(
            "提示：本地图像模型需支持多模态（如 llava、bakllava）\n"
            "请在上方手动输入模型名"
        )

    # ─── 模型类型切换 ───

    def _on_type_changed(self):
        if self._type_combo.currentData() == "cloud":
            self._set_cloud_mode()
        else:
            self._set_local_mode()

    def _on_cloud_url_changed(self, index: int):
        if 0 <= index < len(_CLOUD_APIS):
            model = _CLOUD_APIS[index][2]
            self._model_combo.setCurrentIndex(index)

    def _on_image_cloud_url_changed(self, index: int):
        """图像模型 URL 切换时自动切换对应模型名"""
        if 0 <= index < len(self._IMAGE_CLOUD_APIS):
            self._image_model_combo.setCurrentIndex(index)

    def _set_cloud_mode(self):
        self._url_hint.hide()
        self._local_hint.hide()
        self._model_status.hide()
        self._btn_refresh.hide()
        self._btn_start_ollama.hide()
        # 填充云端 URL
        self._url_combo.clear()
        for url, label, _ in _CLOUD_APIS:
            self._url_combo.addItem(f"{url}  — {label}", url)
        # 填充云端模型
        self._model_combo.clear()
        for url, label, model in _CLOUD_APIS:
            self._model_combo.addItem(f"{model}  — {label}", model)
        self._model_combo.setCurrentIndex(0)
        self._url_combo.currentIndexChanged.connect(self._on_cloud_url_changed)
        self._set_key_mode("cloud")

    def _set_local_mode(self):
        self._local_hint.setText("ℹ️ 本地服务不需要 API Key")
        self._local_hint.setStyleSheet(f"color:{COLORS['ok']};background:transparent")
        self._local_hint.show()
        self._url_combo.clear()
        for name, url in _LOCAL_SERVICES:
            self._url_combo.addItem(f"{url}  — 本地 {name}", url)
        self._url_hint.setText("💡 Base URL 已自动配置为默认地址，可手动修改。点击「刷新模型列表」获取已安装的模型。")
        self._url_hint.setStyleSheet(f"color:{COLORS['dim']};background:transparent")
        self._url_hint.show()
        self._set_key_mode("local")
        self._btn_refresh.show()
        self._model_status.show()
        self._model_status.setText("💡 点击「刷新模型列表」获取已安装的模型，或手动输入模型名")
        self._model_status.setStyleSheet(f"color:{COLORS['dim']};background:transparent")

    # ─── API Key 模式 ───

    def _set_key_mode(self, mode: str):
        if mode == "local":
            self._key_edit.setReadOnly(True)
            self._key_edit.setEchoMode(QLineEdit.Normal)
            self._key_edit.setText("本地模型不需要输入")
            self._key_edit.setStyleSheet(
                f"QLineEdit{{background:#fff3cd;color:#dc3545;"
                f"border:1px solid #ffc107;border-radius:6px;padding:6px 10px;"
                f"font-family:Consolas;font-weight:bold}}"
            )
        else:
            self._key_edit.setReadOnly(False)
            self._key_edit.setEchoMode(QLineEdit.Password)
            self._key_edit.setText("请输入 API Key")
            self._key_edit.setStyleSheet(
                f"QLineEdit{{background:#0d6efd;color:#ffffff;"
                f"border:1px solid #0d6efd;border-radius:6px;padding:6px 10px;"
                f"font-family:Consolas}}"
            )
            self._key_placeholder_active = True

    def _on_key_focus_in(self, event):
        if self._key_edit.isReadOnly():
            return QLineEdit.focusInEvent(self._key_edit, event)
        if self._key_placeholder_active:
            self._key_edit.setText("")
            self._key_placeholder_active = False
        return QLineEdit.focusInEvent(self._key_edit, event)

    # ─── 模型检测 ───

    def _detect_models(self):
        """检测本地模型列表"""
        self._model_status.show()
        self._model_status.setText("正在检测本地模型...")
        self._model_status.setStyleSheet(f"color:{COLORS['warn']};background:transparent")
        self._btn_refresh.setEnabled(False)
        self._detecting = True
        threading.Thread(target=self._do_detect_models, daemon=True).start()
        # 看门狗：5 秒后若线程未返回，强制结束
        self._detect_watchdog = QTimer.singleShot(5000, self._on_detect_watchdog)

    def _on_detect_watchdog(self):
        if self._detecting:
            logger.warning("模型检测看门狗触发：5秒未返回，强制结束")
            self._detecting = False
            self._btn_refresh.setEnabled(True)
            self._btn_start_ollama.show()
            self._model_status.setText("✗ 检测超时。请确认 Ollama 服务已启动（端口 11434），或点击「🔄 启动 Ollama」一键启动。")
            self._model_status.setStyleSheet(f"color:{COLORS['err']};background:transparent")

    def _on_refresh_models(self):
        self._detect_models()

    def _on_start_ollama(self):
        """一键启动 Ollama 服务"""
        self._btn_start_ollama.setEnabled(False)
        self._btn_start_ollama.setText("⏳ 启动中...")
        self._model_status.show()
        self._model_status.setText("正在启动 Ollama 服务...")
        self._model_status.setStyleSheet(f"color:{COLORS['warn']};background:transparent")
        threading.Thread(target=self._do_start_ollama, daemon=True).start()

    def _do_start_ollama(self):
        """子线程：启动 Ollama 并等待就绪"""
        import subprocess
        import os

        try:
            # 先检查 Ollama 是否已在运行
            check = subprocess.run(
                ["ollama", "list"], capture_output=True, text=True, timeout=5
            )
            if check.returncode == 0:
                logger.info("Ollama 已在运行，无需启动")
                self.sig.ollama_started.emit(True, "Ollama 已在运行，点击「刷新模型列表」获取模型")
                return

            # 启动 Ollama serve（后台，无窗口）
            logger.info("正在启动 Ollama serve...")
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )

            # 轮询等待就绪，最多等 15 秒
            for i in range(15):
                import time
                time.sleep(1)
                check = subprocess.run(
                    ["ollama", "list"], capture_output=True, text=True, timeout=5
                )
                if check.returncode == 0:
                    logger.info("Ollama 启动成功，耗时 %d 秒", i + 1)
                    self.sig.ollama_started.emit(
                        True, f"Ollama 已启动（耗时 {i + 1} 秒），正在获取模型列表..."
                    )
                    return

            self.sig.ollama_started.emit(
                False, "Ollama 启动超时（15 秒），请手动运行 ollama serve 检查"
            )

        except FileNotFoundError:
            self.sig.ollama_started.emit(
                False,
                "未找到 ollama 命令。请确认 Ollama 已安装，并添加到系统 PATH 环境变量中。\n"
                "下载地址：https://ollama.com/download"
            )
        except Exception as e:
            logger.error("启动 Ollama 失败: %s", e)
            self.sig.ollama_started.emit(False, f"启动失败: {e}")

    def _on_ollama_started(self, success: bool, message: str):
        """Ollama 启动完成"""
        self._btn_start_ollama.setEnabled(True)
        self._btn_start_ollama.setText("🔄 启动 Ollama")

        if success:
            self._model_status.setText(f"✓ {message}")
            self._model_status.setStyleSheet(f"color:{COLORS['ok']};background:transparent")
            # 启动成功后自动检测模型
            self._detect_models()
        else:
            self._model_status.setText(f"✗ {message}")
            self._model_status.setStyleSheet(f"color:{COLORS['err']};background:transparent")
            self._btn_start_ollama.show()

    def _do_detect_models(self):
        """检测本地模型（子线程）

        使用 socket.create_connection 直连，5 秒超时。
        不经过 urllib / http.client / subprocess。
        """
        import socket
        import json as _json

        models = []
        detected = False
        error_msg = ""
        port = 11434  # 默认 Ollama

        try:
            current_url = self._url_combo.currentData() or self._url_combo.currentText().strip()
            port = 1234 if "1234" in current_url else 11434
            logger.info("开始检测本地模型: 127.0.0.1:%d", port)

            # 用 create_connection 连接，超时 5 秒
            sock = socket.create_connection(("127.0.0.1", port), timeout=5)
            logger.info("TCP 连接成功: 127.0.0.1:%d", port)

            # 发送 HTTP 请求
            sock.sendall(
                f"GET /api/tags HTTP/1.0\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                f"Accept: application/json\r\n"
                f"\r\n".encode()
            )
            logger.info("HTTP 请求已发送")

            # 读取响应
            sock.settimeout(5)
            response = b""
            while True:
                try:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                except socket.timeout:
                    break
            sock.close()
            logger.info("收到响应: %d 字节", len(response))

            # 解析
            body = response.split(b"\r\n\r\n", 1)[-1]
            data = _json.loads(body.decode("utf-8"))
            if "models" in data:
                models = [m.get("name", "") for m in data["models"]]
            elif "data" in data:
                models = [m.get("id", "") for m in data["data"]]
            detected = True
            logger.info("检测完成: %d 个模型", len(models))

        except socket.timeout:
            logger.warning("检测超时: 127.0.0.1:%d", port)
            error_msg = f"连接超时，端口 {port} 无响应。请确认 Ollama 服务已启动。"
        except ConnectionRefusedError:
            logger.warning("连接被拒绝: 127.0.0.1:%d", port)
            error_msg = f"端口 {port} 拒绝连接。请先运行 ollama serve。"
        except Exception as e:
            logger.error("检测失败: %s", e)
            error_msg = f"连接失败: {e}"

        if self._detecting:
            self._detecting = False
            self.sig.models_detected.emit(detected, models, error_msg)

    def _on_models_detected(self, detected: bool, models: list, error_msg: str):
        """模型检测完成"""
        self._btn_refresh.setEnabled(True)

        if detected and models:
            # 有模型
            self._btn_start_ollama.hide()
            self._model_combo.clear()
            for m in models:
                for keyword, vendor in _MODEL_VENDOR_MAP.items():
                    if keyword in m.lower():
                        self._model_combo.addItem(f"{m}  — {vendor}", m)
                        break
                else:
                    self._model_combo.addItem(m, m)
            self._model_combo.setCurrentIndex(0)
            self._model_status.setText(f"✓ 已连接，检测到 {len(models)} 个模型")
            self._model_status.setStyleSheet(f"color:{COLORS['ok']};background:transparent")
        elif detected:
            # 连接成功但无模型
            self._btn_start_ollama.hide()
            self._model_combo.clear()
            self._model_status.setText(
                "⚠️ 连接成功，但未找到任何模型\n"
                "可能原因：尚未下载模型\n"
                "解决方法：运行 ollama pull qwen2.5 下载模型"
            )
            self._model_status.setStyleSheet(f"color:{COLORS['warn']};background:transparent")
        else:
            # 连接失败
            self._btn_start_ollama.show()
            self._model_status.setText(
                f"✗ {error_msg}\n"
                "请确认服务已启动，或点击「🔄 启动 Ollama」一键启动"
            )
            self._model_status.setStyleSheet(f"color:{COLORS['err']};background:transparent")

    # ─── 配置加载/收集 ───

    def _load_config_to_ui(self):
        self._chk_enable.setChecked(self._config.enable_ai)
        is_local = self._config.is_local()
        self._type_combo.setCurrentIndex(1 if is_local else 0)
        if is_local:
            self._set_local_mode()
        else:
            self._set_cloud_mode()
        # 匹配 URL
        for i in range(self._url_combo.count()):
            if self._url_combo.itemData(i) == self._config.base_url:
                self._url_combo.setCurrentIndex(i)
                break
        else:
            self._url_combo.setEditText(self._config.base_url)
        if not is_local and self._config.api_key:
            self._key_edit.setText(self._config.api_key)
            self._key_placeholder_active = False
        self._model_combo.setCurrentText(self._config.model)

        # 加载图像模型配置
        image_is_local = (
            "localhost" in self._config.image_base_url.lower()
            or "127.0.0.1" in self._config.image_base_url.lower()
        )
        self._image_type_combo.setCurrentIndex(1 if image_is_local else 0)
        if image_is_local:
            self._set_image_local_mode()
        else:
            self._set_image_cloud_mode()

        # 匹配图像 URL
        matched = False
        for i in range(self._image_url_combo.count()):
            data = self._image_url_combo.itemData(i)
            text = self._image_url_combo.itemText(i)
            if data and data == self._config.image_base_url:
                self._image_url_combo.setCurrentIndex(i)
                matched = True
                break
            elif self._config.image_base_url in text:
                self._image_url_combo.setCurrentIndex(i)
                matched = True
                break
        if not matched:
            self._image_url_combo.setEditText(self._config.image_base_url)

        if image_is_local:
            self._image_key_edit.setText("本地模型不需要输入")
        elif self._config.image_api_key:
            self._image_key_edit.setText(self._config.image_api_key)

        self._image_model_combo.setCurrentText(self._config.image_model)

    def _collect_config(self) -> AIConfig:
        mode = self._type_combo.currentData()
        url = self._url_combo.currentData() or self._url_combo.currentText().strip()
        model = self._model_combo.currentData() or self._model_combo.currentText().strip()
        if "  — " in model:
            model = model.split("  — ")[0].strip()
        key = self._key_edit.text().strip()
        if mode == "local" or key in ("本地模型不需要输入", "请输入 API Key"):
            key = ""

        # 收集图像模型配置
        image_mode = self._image_type_combo.currentData()
        image_url = self._image_url_combo.currentData() or self._image_url_combo.currentText().strip()
        if "  — " in image_url:
            image_url = image_url.split("  — ")[0].strip()
        image_model = self._image_model_combo.currentData() or self._image_model_combo.currentText().strip()
        if "  — " in image_model:
            image_model = image_model.split("  — ")[0].strip()
        image_key = self._image_key_edit.text().strip()
        if image_mode == "local" or image_key in ("本地模型不需要输入", "请输入图像模型 API Key（可选）"):
            image_key = ""

        return AIConfig(
            api_key=key,
            base_url=url,
            model=model,
            enable_ai=self._chk_enable.isChecked(),
            image_base_url=image_url,
            image_model=image_model,
            image_api_key=image_key,
        )

    # ─── 测试/保存 ───

    def _on_test(self):
        config = self._collect_config()
        current_tab = self._tab_widget.currentIndex()
        
        if current_tab == 0:
            if not config.text_is_valid():
                self._on_status("请先填写文字模型配置信息", COLORS["warn"])
                return
            test_type = "文字模型"
            test_url = config.base_url
            test_model = config.model
        elif current_tab == 1:
            if not config.image_is_valid():
                self._on_status("请先填写图像模型配置信息", COLORS["warn"])
                return
            test_type = "图像模型"
            test_url = config.image_base_url
            test_model = config.image_model
        else:
            self._on_status("请切换到文字模型或图像模型 tab 进行测试", COLORS["warn"])
            return
        
        self._btn_test.setEnabled(False)
        self._on_status(f"正在测试{test_type}连接: {test_url} | model={test_model}", COLORS["warn"])
        threading.Thread(target=self._do_test, args=(config, current_tab), daemon=True).start()

    def _do_test(self, config: AIConfig, tab_index: int):
        try:
            if tab_index == 0:
                reply = chat_completion(config, [{"role": "user", "content": "回复'连接成功'四个字"}], temperature=0, max_tokens=20)
                self.sig.status.emit(f"文字模型连接成功！AI 回复: {reply}", COLORS["ok"])
            else:
                test_config = AIConfig(
                    base_url=config.image_base_url,
                    api_key=config.image_api_key,
                    model=config.image_model,
                    enable_ai=True,
                )
                reply = chat_completion(test_config, [{"role": "user", "content": "回复'连接成功'四个字"}], temperature=0, max_tokens=20)
                self.sig.status.emit(f"图像模型连接成功！AI 回复: {reply}", COLORS["ok"])
        except Exception as e:
            full_error = f"连接失败: {e}"
            self.sig.status.emit("错误：具体见警告框", COLORS["err"])
            self.sig.show_error.emit("连接失败", full_error)

    def _on_save(self):
        config = self._collect_config()
        if save_config(config):
            self._config = config
            self.sig.config_saved.emit(config.enable_ai)
            
            prompts = {}
            if hasattr(self, '_prompt_edits'):
                for key, edit in self._prompt_edits.items():
                    prompts[key] = edit.toPlainText()
                save_prompts(prompts)
            
            self._on_status(f"配置已保存 | AI 功能: {'已启用' if config.enable_ai else '已禁用'}", COLORS["ok"])
        else:
            self._on_status("保存失败，请检查权限", COLORS["err"])

    def _on_status(self, msg: str, color: str):
        self._btn_test.setEnabled(True)
        self._status_label.setStyleSheet(f"color:{color};background:transparent")
        self._status_label.setText(msg)

    def _on_config_saved(self, enabled: bool):
        pass

    def _on_show_error(self, title: str, message: str):
        QMessageBox.critical(self, title, message, QMessageBox.Ok)

    # ─── 截图热键 ───

    def _on_set_screenshot_hotkey(self):
        """捕获新的截图热键"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
        from utils.hotkey_handler import HotkeyCapture, get_screenshot_hotkey_display

        dlg = QDialog(self)
        dlg.setWindowTitle("修改截图热键")
        dlg.setMinimumWidth(360)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        hint = QLabel(f"当前热键：{get_screenshot_hotkey_display()}\n\n按下新的快捷键组合…")
        hint.setFont(FONT_BODY)
        hint.setStyleSheet(f"color:{COLORS['fg']};background:transparent")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)

        result_label = QLabel("")
        result_label.setFont(FONT_BODY)
        result_label.setStyleSheet(f"color:{COLORS['ok']};background:transparent")
        result_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(result_label)

        btn_close = QPushButton("关闭")
        btn_close.setFont(FONT_SMALL)
        btn_close.setStyleSheet(
            f"QPushButton{{background:transparent;color:{COLORS['dim']};border:1px solid {COLORS['border']};border-radius:6px;padding:6px}}"
        )
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close)

        dlg.show()

        def on_captured(mods, key):
            from utils.hotkey_handler import _load_config, _save_config
            cfg = _load_config()
            cfg["screenshot_modifiers"] = mods
            cfg["screenshot_key"] = key.lower()
            _save_config(cfg)
            display = "+".join(mods + [key.upper()])
            result_label.setText(f"截图热键已设为：{display}")
            self._screenshot_hk_label.setText(f"当前：{display}")

        capture = HotkeyCapture(on_captured=on_captured)
        capture.start()
        dlg.exec()
        capture.stop()

    def _go_back(self):
        self.close()

    def showEvent(self, e):
        """窗口显示时重新加载配置，确保显示最新配置"""
        super().showEvent(e)
        self._config = load_config()
        self._load_config_to_ui()
        self._load_prompts_to_ui()
        logger.info("设置窗口已显示，重新加载配置")

    def closeEvent(self, e):
        if self._on_back:
            e.ignore()
            self.hide()
            self._on_back()
        else:
            e.accept()