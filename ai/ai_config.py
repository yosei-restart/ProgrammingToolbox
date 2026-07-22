"""
AI 配置管理模块

存储和管理 AI API 的配置信息（API Key、Base URL、模型名等）。
配置保存为 JSON 文件，位于用户目录下。

依赖：仅 Python 标准库（json, os, pathlib）
许可：PSF（Python Software Foundation License），开源，企业免费，商用可用
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from typing import Optional

from utils.logging_utils import get_logger

logger = get_logger(__name__)

# 配置文件路径：用户目录下的 .ai_inspector_config.json
_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".gui_inspector")
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "ai_config.json")


@dataclass
class AIConfig:
    """AI API 配置

    Attributes:
        api_key: API 密钥（OpenAI/DeepSeek/智谱等）
        base_url: API 基础 URL（如 https://api.openai.com/v1）
        model: 模型名称（如 gpt-4o / deepseek-chat / glm-4）
        enable_ai: 是否启用 AI 功能
        image_base_url: 图像模型 API 基础 URL
        image_model: 图像模型名称（如 gpt-4o / glm-4v）
        image_api_key: 图像模型 API 密钥（可选，为空则使用 api_key）
    """
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    enable_ai: bool = True
    image_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    image_model: str = "glm-4v"
    image_api_key: str = ""

    def is_local(self) -> bool:
        """检查是否为本地模型服务（Ollama/LM Studio 等）

        本地服务不需要 API Key。

        Returns:
            True 如果 base_url 指向 localhost 或 127.0.0.1
        """
        url = self.base_url.lower()
        return "localhost" in url or "127.0.0.1" in url or "0.0.0.0" in url

    def is_valid(self) -> bool:
        """检查文字模型配置是否有效（可以发起 API 请求）

        本地模型（Ollama/LM Studio）不需要 API Key；
        云端 API 必须填写 API Key。

        Returns:
            True 如果配置有效
        """
        return self.text_is_valid()

    def text_is_valid(self) -> bool:
        """检查文字模型配置是否有效"""
        if not self.base_url.strip():
            return False
        if self._is_local_url(self.base_url):
            return True
        return bool(self.api_key.strip())

    def image_is_valid(self) -> bool:
        """检查图像模型配置是否有效"""
        if not self.image_base_url.strip():
            return False
        if self._is_local_url(self.image_base_url):
            return True
        key = self.image_api_key.strip() or self.api_key.strip()
        return bool(key)

    def _is_local_url(self, url: str) -> bool:
        """检查 URL 是否指向本地服务"""
        url_lower = url.lower()
        return "localhost" in url_lower or "127.0.0.1" in url_lower or "0.0.0.0" in url_lower

    def to_dict(self) -> dict:
        """转为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AIConfig":
        """从字典创建配置"""
        return cls(
            api_key=data.get("api_key", ""),
            base_url=data.get("base_url", "https://api.deepseek.com/v1"),
            model=data.get("model", "deepseek-chat"),
            enable_ai=data.get("enable_ai", False),
            image_base_url=data.get("image_base_url", "https://open.bigmodel.cn/api/paas/v4"),
            image_model=data.get("image_model", "glm-4v"),
            image_api_key=data.get("image_api_key", ""),
        )


def load_config() -> AIConfig:
    """从本地文件加载配置

    文件不存在时返回默认配置。

    Returns:
        AIConfig 配置对象
    """
    try:
        if os.path.exists(_CONFIG_FILE):
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            config = AIConfig.from_dict(data)
            logger.info("AI 配置已加载: model=%s, enable=%s", config.model, config.enable_ai)
            return config
    except Exception as e:
        logger.error("加载 AI 配置失败: %s", e)
    return AIConfig()


def save_config(config: AIConfig) -> bool:
    """保存配置到本地文件

    Args:
        config: AI 配置对象

    Returns:
        True 如果保存成功
    """
    try:
        os.makedirs(_CONFIG_DIR, exist_ok=True)
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info("AI 配置已保存: model=%s", config.model)
        return True
    except Exception as e:
        logger.error("保存 AI 配置失败: %s", e)
        return False


def mask_api_key(key: str) -> str:
    """脱敏 API Key（用于日志和显示）

    保留前4后4，中间用星号代替。

    Args:
        key: 原始 API Key

    Returns:
        脱敏后的字符串，如 sk-x****6789
    """
    if not key or len(key) <= 8:
        return "****"
    return key[:4] + "*" * (len(key) - 8) + key[-4:]
