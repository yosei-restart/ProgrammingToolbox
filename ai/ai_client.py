"""
AI 客户端模块

调用 OpenAI 兼容 API（支持 OpenAI/DeepSeek/智谱/Kimi 等），
为工具1（GUI 探查器）和工具2（变量追踪器）提供 AI 分析能力。

使用 Python 标准库 urllib 发送 HTTP 请求，零第三方依赖。
许可：PSF（Python Software Foundation License），开源，企业免费，商用可用

功能：
- chat_completion(): 发送消息给 AI，获取回复
- analyze_control(): 分析 GUI 控件信息，返回说明
- analyze_variable_changes(): 分析变量变化序列，判断是否有问题
- chat_completion_with_image(): 调用支持图像的多模态 API
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
import base64
import ssl
import time
from io import BytesIO
from typing import Optional

from ai.ai_config import AIConfig, load_config, mask_api_key
from ai.prompts_config import get_prompt
from utils.logging_utils import get_logger

logger = get_logger(__name__)

_TIMEOUT = 180
_MAX_RETRIES = 2
_RETRY_DELAY = 2


def chat_completion(
    config: AIConfig,
    messages: list,
    temperature: float = 0.3,
    max_tokens: int = 2000,
) -> str:
    """调用 OpenAI 兼容 API 的 chat/completions 接口

    Args:
        config: AI 配置（API Key、Base URL、模型名）
        messages: 消息列表，格式 [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
        temperature: 温度参数（0-1），越低越确定
        max_tokens: 最大返回 token 数

    Returns:
        AI 回复的文本内容

    Raises:
        RuntimeError: 配置无效或 API 请求失败
    """
    if not config.is_valid():
        raise RuntimeError("AI 配置无效，请先在设置中填写 API Key 和 Base URL")

    url = config.base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
    }
    if config.api_key.strip() and not config.is_local():
        headers["Authorization"] = f"Bearer {config.api_key}"
    elif config.is_local():
        headers["Authorization"] = "Bearer ollama"
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    logger.info(
        "AI 请求: model=%s, messages=%d, url=%s",
        config.model,
        len(messages),
        mask_api_key(config.api_key),
    )

    ssl_context = ssl.create_default_context()
    ssl_context.set_ciphers("DEFAULT@SECLEVEL=1")
    ssl_context.options |= ssl.OP_NO_TLSv1_3

    for attempt in range(_MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ssl_context) as resp:
                body = resp.read().decode("utf-8")
                result = json.loads(body)
                content = result["choices"][0]["message"]["content"]
                logger.info("AI 响应: %d 字符", len(content))
                return content
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            logger.error("AI API HTTP 错误 %d: %s", e.code, error_body[:200])
            raise RuntimeError(f"API 错误 {e.code}: {error_body[:200]}") from e
        except (urllib.error.URLError, ConnectionResetError, TimeoutError) as e:
            if attempt < _MAX_RETRIES:
                logger.warning("AI API 网络错误（第 %d/%d 次尝试）: %s，%d 秒后重试", attempt + 1, _MAX_RETRIES + 1, e, _RETRY_DELAY)
                time.sleep(_RETRY_DELAY)
            else:
                logger.error("AI API 网络错误（已重试 %d 次）: %s", _MAX_RETRIES, e)
                raise RuntimeError(f"网络错误: {e}") from e
        except Exception as e:
            logger.error("AI API 调用失败: %s", e)
            raise RuntimeError(f"调用失败: {e}") from e


def analyze_control(
    control_info: dict,
    config: Optional[AIConfig] = None,
) -> str:
    """分析 GUI 控件信息，返回 AI 说明

    将控件的类型、属性、层级等信息发给 AI，让 AI 说明这个控件的作用。

    Args:
        control_info: 控件信息字典，包含 type/name/class_name/properties 等
        config: AI 配置，为 None 时自动加载

    Returns:
        AI 的分析文本
    """
    if config is None:
        config = load_config()

    prompt_template = get_prompt("control_analysis")
    logger.warning("控件分析 - prompt_template 长度: %d, 内容: %s", len(prompt_template), repr(prompt_template[:80]))

    control_info_json = json.dumps(control_info, ensure_ascii=False, indent=2)
    user_prompt = prompt_template.replace("{control_info}", control_info_json)

    messages = [
        {"role": "user", "content": user_prompt},
    ]

    return chat_completion(config, messages, temperature=0.2, max_tokens=1000)


def analyze_variable_changes(
    variable_name: str,
    events_summary: str,
    config: Optional[AIConfig] = None,
) -> str:
    """分析变量变化序列，判断是否有问题

    将变量的生命周期事件（诞生、赋值、使用、消亡）发给 AI，
    让 AI 判断变量变化是否符合预期，是否有潜在 bug。

    Args:
        variable_name: 变量名
        events_summary: 事件摘要文本（格式化的变量变化列表）
        config: AI 配置，为 None 时自动加载

    Returns:
        AI 的分析文本
    """
    if config is None:
        config = load_config()

    prompt_template = get_prompt("variable_analysis")
    logger.warning("变量分析 - prompt_template 长度: %d, 内容: %s", len(prompt_template), repr(prompt_template[:80]))

    user_prompt = prompt_template.replace("{variable_name}", variable_name)
    user_prompt = user_prompt.replace("{events_summary}", events_summary)

    messages = [
        {"role": "user", "content": user_prompt},
    ]

    return chat_completion(config, messages, temperature=0.3, max_tokens=2000)


def _image_to_base64(pixmap) -> str:
    """将 QPixmap 转换为 base64 编码字符串

    Args:
        pixmap: QPixmap 对象

    Returns:
        base64 编码的图片字符串（data URL 格式）
    """
    if pixmap is None:
        raise RuntimeError("图片为空")

    buffer = BytesIO()
    pixmap.save(buffer, "PNG")
    image_data = buffer.getvalue()
    buffer.close()

    base64_str = base64.b64encode(image_data).decode("utf-8")
    return f"data:image/png;base64,{base64_str}"


def chat_completion_with_image(
    config: AIConfig,
    image_base64: str,
    prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 3000,
) -> str:
    """调用支持图像的 OpenAI 兼容 API（多模态）

    使用图像模型的配置（image_base_url, image_model, image_api_key）

    Args:
        config: AI 配置
        image_base64: base64 编码的图片（data URL 格式）
        prompt: 用户提示词
        temperature: 温度参数
        max_tokens: 最大返回 token 数

    Returns:
        AI 回复的文本内容

    Raises:
        RuntimeError: 配置无效或 API 请求失败
    """
    api_key = config.image_api_key.strip() or config.api_key.strip()
    base_url = config.image_base_url.strip() or config.base_url.strip()
    model = config.image_model.strip() or config.model.strip()

    _OLD_ID_TO_URL = {
        "zhipu": "https://open.bigmodel.cn/api/paas/v4",
        "openai": "https://api.openai.com/v1",
        "deepseek": "https://api.deepseek.com/v1",
        "agnes": "https://apihub.agnes-ai.com/v1",
    }
    if base_url in _OLD_ID_TO_URL:
        base_url = _OLD_ID_TO_URL[base_url]
        logger.warning(f"[兼容] 自动将旧标识符 '{config.image_base_url}' 转换为 URL: {base_url}")

    if not base_url:
        raise RuntimeError("图像模型 Base URL 未配置")
    if not model:
        raise RuntimeError("图像模型名称未配置")

    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
    }

    is_local = "localhost" in base_url.lower() or "127.0.0.1" in base_url.lower()
    if api_key and not is_local:
        headers["Authorization"] = f"Bearer {api_key}"
    elif is_local:
        headers["Authorization"] = "Bearer ollama"

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_base64}},
            ],
        }
    ]

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    logger.info(
        "图像 AI 请求: model=%s, url=%s, image_size=%d bytes",
        model,
        base_url,
        len(image_base64),
    )

    ssl_context = ssl.create_default_context()
    ssl_context.set_ciphers("DEFAULT@SECLEVEL=1")
    ssl_context.options |= ssl.OP_NO_TLSv1_3

    for attempt in range(_MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ssl_context) as resp:
                body = resp.read().decode("utf-8")
                result = json.loads(body)
                content = result["choices"][0]["message"]["content"]
                logger.info("图像 AI 响应: %d 字符", len(content))
                return content
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            logger.error("图像 AI API HTTP 错误 %d: %s", e.code, error_body[:200])
            raise RuntimeError(f"API 错误 {e.code}: {error_body[:200]}") from e
        except (urllib.error.URLError, ConnectionResetError, TimeoutError) as e:
            if attempt < _MAX_RETRIES:
                logger.warning("图像 AI API 网络错误（第 %d/%d 次尝试）: %s，%d 秒后重试", attempt + 1, _MAX_RETRIES + 1, e, _RETRY_DELAY)
                time.sleep(_RETRY_DELAY)
            else:
                logger.error("图像 AI API 网络错误（已重试 %d 次）: %s", _MAX_RETRIES, e)
                raise RuntimeError(f"网络错误: {e}") from e
        except Exception as e:
            logger.error("图像 AI API 调用失败: %s", e)
            raise RuntimeError(f"调用失败: {e}") from e