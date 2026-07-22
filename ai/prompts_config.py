"""
AI 提示词配置模块

管理 4 个 AI 提示词模板的默认值、加载、保存、读取。
配置保存为 JSON 文件，位于用户目录 ~/.gui_inspector/prompts.json。

依赖：仅 Python 标准库（json, os, copy）
许可：PSF（Python Software Foundation License），开源，企业免费，商用可用
"""

from __future__ import annotations

import json
import os
import copy
from typing import Optional

from utils.logging_utils import get_logger

logger = get_logger(__name__)

# 配置文件路径（与 ai_config.json 同目录）
_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".gui_inspector")
_PROMPTS_FILE = os.path.join(_CONFIG_DIR, "prompts.json")

# 4 个提示词的键名
PROMPT_KEYS = [
    "control_analysis",       # 控件分析
    "variable_analysis",      # 变量分析
    "image_analysis",         # 图片分析
    "image_prompt_reverse",   # 图片提示词反推
]

# 4 个提示词的中文标签和用途说明（用于 UI 显示）
PROMPT_LABELS = {
    "control_analysis": {
        "name": "控件分析提示词",
        "description": "用于 analyze_control() 函数，当用户拾取控件后点击 AI 分析时使用",
    },
    "variable_analysis": {
        "name": "变量分析提示词",
        "description": "用于 analyze_variable_changes() 函数，分析变量生命周期变化时使用",
    },
    "image_analysis": {
        "name": "图片分析提示词",
        "description": "用于 analyze_image() 函数，分析截图内容时使用（多模态）",
    },
    "image_prompt_reverse": {
        "name": "图片提示词反推",
        "description": "用于 analyze_image_prompt() 函数，推测生成图片可能使用的提示词（多模态）",
    },
}

# 代码内置的默认提示词（完整模板，含占位符）
DEFAULT_PROMPTS = {
    "control_analysis": (
        "你是一个 GUI 控件分析专家。以下是控件信息：\n\n"
        "{control_info}\n\n"
        "请用中文简洁地说明：\n"
        "1. 这个控件是什么类型，通常用来做什么\n"
        "2. 它的关键属性值意味着什么\n"
        "3. 在程序中可能的用途\n"
        "请用分点说明，每点不超过2句话。"
    ),
    "variable_analysis": (
        "你是一个 Python 代码分析专家。以下是变量的变化记录：\n\n"
        "变量名: {variable_name}\n\n"
        "变化记录：\n{events_summary}\n\n"
        "请用中文分析：\n"
        "1. 变量的生命周期是否正常（诞生→使用→消亡）\n"
        "2. 值的变化是否符合逻辑（是否有异常跳变、类型不匹配等）\n"
        "3. 是否有潜在 bug（如：使用前未初始化、使用后未释放、值不符合预期等）\n"
        "4. 如果有问题，给出具体的修改建议\n"
        "请用分点说明，直接指出问题所在。"
    ),
    "image_analysis": (
        "请分析这张截图，详细描述图片中显示的内容，包括：\n"
        "1. 界面布局和结构\n"
        "2. 主要控件和元素\n"
        "3. 文字内容（如果能识别）\n"
        "4. 整体用途和功能推测\n"
        "请用中文分点说明，语言简洁清晰。"
    ),
    "image_prompt_reverse": (
        "请分析这张图片，推测生成这张图片可能使用的 AI 图像生成提示词（Prompt）。\n"
        "要求：\n"
        "1. 分析图片中的主题、风格、色彩、构图等特征\n"
        "2. 给出 2-3 个不同风格的提示词\n"
        "3. 每个提示词包含主题描述、风格描述、参数设置等\n"
        "4. 如果是截图或界面图片，说明其设计特点\n"
        "请用中文分点说明，语言简洁清晰。"
    ),
}

# 各提示词支持的占位符列表（用于 UI 提示）
PROMPT_PLACEHOLDERS = {
    "control_analysis": ["{control_info}（控件信息 JSON）"],
    "variable_analysis": ["{variable_name}（变量名）", "{events_summary}（事件摘要）"],
    "image_analysis": ["（无占位符，图片单独传入）"],
    "image_prompt_reverse": ["（无占位符，图片单独传入）"],
}


def load_prompts() -> dict:
    """从本地文件加载提示词
    
    文件不存在时返回 DEFAULT_PROMPTS 的副本。
    JSON 解析失败时记录 WARNING 并返回 DEFAULT_PROMPTS。
    单项缺失时用 DEFAULT_PROMPTS 对应项兜底。
    
    Returns:
        dict: 包含 4 个提示词的字典
    """
    result = copy.deepcopy(DEFAULT_PROMPTS)
    
    if not os.path.exists(_PROMPTS_FILE):
        logger.info("提示词配置文件不存在，使用默认值")
        return result
    
    try:
        with open(_PROMPTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        if not isinstance(data, dict):
            logger.warning("提示词配置文件格式错误（非 dict），使用默认值")
            return result
        
        # 逐项合并：用户值覆盖默认值，缺失项用默认值兜底
        for key in PROMPT_KEYS:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                result[key] = value
            else:
                logger.info("提示词项 '%s' 缺失或为空，使用默认值", key)
        
        logger.info("提示词配置已加载: %s", _PROMPTS_FILE)
        return result
    except json.JSONDecodeError as e:
        logger.warning("提示词配置文件 JSON 解析失败: %s，使用默认值", e)
        return result
    except Exception as e:
        logger.warning("加载提示词配置失败: %s，使用默认值", e)
        return result


def save_prompts(prompts: dict) -> bool:
    """保存提示词到本地文件
    
    Args:
        prompts: 包含 4 个提示词的字典
    
    Returns:
        True 如果保存成功
    """
    try:
        os.makedirs(_CONFIG_DIR, exist_ok=True)
        
        # 只保存 4 个已知的键，忽略其他键
        data = {key: prompts.get(key, DEFAULT_PROMPTS[key]) for key in PROMPT_KEYS}
        
        with open(_PROMPTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info("提示词配置已保存: %s", _PROMPTS_FILE)
        return True
    except Exception as e:
        logger.error("保存提示词配置失败: %s", e)
        return False


def get_prompt(key: str) -> str:
    """读取单个提示词
    
    Args:
        key: 提示词键名（PROMPT_KEYS 之一）
    
    Returns:
        提示词字符串。key 无效时返回 DEFAULT_PROMPTS 中对应项，仍无效时返回空字符串。
    """
    if key not in PROMPT_KEYS:
        logger.warning("未知的提示词键名: %s", key)
        return ""
    
    prompts = load_prompts()
    return prompts.get(key, DEFAULT_PROMPTS.get(key, ""))
