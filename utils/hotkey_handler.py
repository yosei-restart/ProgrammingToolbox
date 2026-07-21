"""
GUI 元素探查器 - 全局热键与鼠标钩子管理
使用 pynput 实现全局热键监听和检查模式鼠标点击捕获
支持可配置的热键组合
"""

import threading
import json
import os
import ctypes
import ctypes.wintypes
from pynput import keyboard, mouse
from typing import Callable, Optional, List, Set

from utils.logging_utils import get_logger

logger = get_logger(__name__)


# Windows 光标常量
IDC_CROSS = 32515
IDC_ARROW = 32512

# 加载 user32.dll 用于光标切换
user32 = ctypes.windll.user32

# 配置文件路径
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def set_cursor_crosshair():
    """将光标设置为十字准星"""
    hcursor = user32.LoadCursorW(0, IDC_CROSS)
    user32.SetSystemCursor(hcursor, IDC_ARROW)


def set_cursor_arrow():
    """将光标恢复为默认箭头"""
    user32.SystemParametersInfoW(0x0057, 0, None, 0)


# 修饰键映射
MODIFIER_MAP: dict = {
    keyboard.Key.ctrl_l: "Ctrl",
    keyboard.Key.ctrl_r: "Ctrl",
    keyboard.Key.shift_l: "Shift",
    keyboard.Key.shift_r: "Shift",
    keyboard.Key.alt_l: "Alt",
    keyboard.Key.alt_r: "Alt",
    keyboard.Key.cmd_l: "Win",
    keyboard.Key.cmd_r: "Win",
}

# 修饰键 Key 对象集合
MODIFIER_KEYS: set = {
    keyboard.Key.ctrl_l, keyboard.Key.ctrl_r,
    keyboard.Key.shift_l, keyboard.Key.shift_r,
    keyboard.Key.alt_l, keyboard.Key.alt_r,
    keyboard.Key.cmd_l, keyboard.Key.cmd_r,
}


def _vk_to_char_simple(vk: int) -> str:
    """从虚拟键码获取字符，用于处理控制字符场景"""
    # 主键盘区数字键 0-9
    if 0x30 <= vk <= 0x39:
        return str(vk - 0x30)
    # 小键盘数字键 0-9
    if 0x60 <= vk <= 0x69:
        return str(vk - 0x60)
    # 字母键 A-Z
    if 0x41 <= vk <= 0x5A:
        return chr(vk + 32)
    # 功能键 F1-F12 (VK_F1=0x70 ~ VK_F12=0x7B)
    if 0x70 <= vk <= 0x7B:
        return f"f{vk - 0x6F}"
    # 其他键用 MapVirtualKeyExW
    result = ctypes.windll.user32.MapVirtualKeyExW(vk, 2, 0)
    if result == 0:
        return None
    ch = chr(result & 0xFFFF)
    if ch < ' ' or ch > '~':
        return None
    return ch


def _load_config() -> dict:
    """加载热键配置"""
    defaults = {
        "modifiers": ["Ctrl", "Shift"],
        "key": "i",
        "screenshot_modifiers": ["Ctrl", "Shift"],
        "screenshot_key": "s",
    }
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            defaults.update(cfg)
    except Exception as e:
        logger.warning("加载热键配置失败，使用默认值: %s", e)
    return defaults


def _save_config(cfg: dict):
    """保存热键配置"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("保存热键配置失败: %s", e)


def get_hotkey_display() -> str:
    """获取当前热键的显示文本"""
    cfg = _load_config()
    mods = cfg.get("modifiers", ["Ctrl", "Shift"])
    key = cfg.get("key", "i")
    return "+".join(mods + [key.upper()])


def get_screenshot_hotkey_display() -> str:
    """获取截图热键的显示文本"""
    cfg = _load_config()
    mods = cfg.get("screenshot_modifiers", ["Ctrl", "Shift"])
    key = cfg.get("screenshot_key", "s")
    return "+".join(mods + [key.upper()])


_shared_instance = None


class HotkeyHandler:
    """
    全局热键管理器（单例模式）

    监听可配置的热键进入检查模式，
    在检查模式下捕获鼠标左键点击触发检查回调。
    同时监听截图热键触发截图标注功能。

    单例模式：整个应用只有一个 HotkeyHandler 实例，
    避免多个实例同时监听导致热键触发多次。
    """

    @classmethod
    def instance(cls) -> "HotkeyHandler":
        """获取全局共享实例"""
        global _shared_instance
        if _shared_instance is None:
            raise RuntimeError("HotkeyHandler 尚未初始化，请先调用 HotkeyHandler.init()")
        return _shared_instance

    @classmethod
    def init(cls, on_inspect: Callable[[int, int], None],
             on_screenshot: Optional[Callable[[], None]] = None) -> "HotkeyHandler":
        """初始化全局共享实例（仅调用一次）"""
        global _shared_instance
        if _shared_instance is not None:
            logger.warning("HotkeyHandler.init() 被调用多次，返回已有实例")
            return _shared_instance
        _shared_instance = cls(on_inspect, on_screenshot)
        return _shared_instance

    def __init__(self, on_inspect: Callable[[int, int], None],
                 on_screenshot: Optional[Callable[[], None]] = None):
        self.on_inspect = on_inspect
        self.on_screenshot = on_screenshot
        self._inspect_mode = False
        self._kb_listener: Optional[keyboard.Listener] = None
        self._mouse_listener: Optional[mouse.Listener] = None
        self._mode_change_callback: Optional[Callable[[bool], None]] = None

        # 当前按下的修饰键
        self._pressed_modifiers: Set[str] = set()

        # 加载配置
        self._reload_config()

    def _reload_config(self):
        """重新加载热键配置"""
        cfg = _load_config()
        self._required_modifiers = set(cfg.get("modifiers", ["Ctrl", "Shift"]))
        self._trigger_key = cfg.get("key", "i").lower()
        self._screenshot_modifiers = set(cfg.get("screenshot_modifiers", ["Ctrl", "Shift"]))
        self._screenshot_key = cfg.get("screenshot_key", "s").lower()

    def set_hotkey(self, modifiers: List[str], key: str):
        """
        修改热键组合

        Args:
            modifiers: 修饰键列表，如 ["Ctrl", "Shift"]
            key: 触发键，如 "i"
        """
        cfg = _load_config()
        cfg["modifiers"] = modifiers
        cfg["key"] = key.lower()
        _save_config(cfg)
        self._reload_config()
        logger.info("热键已修改为: %s+%s", "+".join(modifiers), key)

    def set_screenshot_hotkey(self, modifiers: List[str], key: str):
        """
        修改截图热键组合

        Args:
            modifiers: 修饰键列表，如 ["Ctrl", "Shift"]
            key: 触发键，如 "s"
        """
        cfg = _load_config()
        cfg["screenshot_modifiers"] = modifiers
        cfg["screenshot_key"] = key.lower()
        _save_config(cfg)
        self._reload_config()
        logger.info("截图热键已修改为: %s+%s", "+".join(modifiers), key)

    def get_hotkey_info(self) -> dict:
        """获取当前热键信息"""
        cfg = _load_config()
        return cfg

    def get_screenshot_hotkey_info(self) -> dict:
        """获取截图热键信息"""
        cfg = _load_config()
        return {
            "modifiers": cfg.get("screenshot_modifiers", ["Ctrl", "Shift"]),
            "key": cfg.get("screenshot_key", "s"),
        }

    def set_mode_change_callback(self, callback: Callable[[bool], None]):
        """设置检查模式变化的回调"""
        self._mode_change_callback = callback

    @property
    def inspect_mode(self) -> bool:
        return self._inspect_mode

    def start(self):
        """启动热键监听（后台线程）"""
        self._kb_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._kb_listener.daemon = True
        self._kb_listener.start()

    def stop(self):
        """停止所有监听"""
        self._exit_inspect_mode()
        if self._kb_listener and self._kb_listener.is_alive():
            self._kb_listener.stop()
        if self._mouse_listener and self._mouse_listener.is_alive():
            self._mouse_listener.stop()

    def _on_key_press(self, key):
        """键盘按下回调"""
        try:
            # 检查模式下按 ESC 退出
            if self._inspect_mode and key == keyboard.Key.esc:
                logger.info("[HOTKEY] ESC 按下，退出检查模式")
                self._exit_inspect_mode()
                return

            # 跟踪修饰键
            if key in MODIFIER_MAP:
                self._pressed_modifiers.add(MODIFIER_MAP[key])
                return

            # 检查触发键
            char = None
            if hasattr(key, "char") and key.char:
                char = key.char.lower()
                # 处理 Ctrl+数字等控制字符，通过 vk 码获取实际字符
                if len(char) == 1 and char < ' ':
                    vk = getattr(key, 'vk', None)
                    if vk:
                        char = _vk_to_char_simple(vk)
            elif hasattr(key, "name") and key.name:
                char = key.name.lower()
            elif hasattr(key, "vk") and key.vk:
                char = _vk_to_char_simple(key.vk)

            if char and char == self._trigger_key:
                if self._required_modifiers.issubset(self._pressed_modifiers):
                    logger.warning("[HOTKEY] 热键匹配成功: modifiers=%s key=%s", 
                                  self._pressed_modifiers, char)
                    self._enter_inspect_mode()
                    return

            # 检查截图热键
            if char and char == self._screenshot_key:
                if self._screenshot_modifiers.issubset(self._pressed_modifiers):
                    logger.warning("[HOTKEY] 截图热键匹配成功: modifiers=%s key=%s",
                                  self._pressed_modifiers, char)
                    if self.on_screenshot:
                        threading.Thread(
                            target=self.on_screenshot, daemon=True
                        ).start()
        except Exception as e:
            logger.warning("键盘按下处理异常: %s", e)

    def _on_key_release(self, key):
        """键盘释放回调"""
        try:
            if key in MODIFIER_MAP:
                self._pressed_modifiers.discard(MODIFIER_MAP[key])
        except Exception as e:
            logger.warning("键盘释放处理异常: %s", e)

    def _enter_inspect_mode(self):
        """进入检查模式"""
        logger.info("[TRACE-HK-1] _enter_inspect_mode 开始")
        if self._inspect_mode:
            logger.info("[TRACE-HK-2] 已在检查模式，直接返回")
            return

        self._inspect_mode = True
        logger.info("[TRACE-HK-3] _inspect_mode 设为 True")
        set_cursor_crosshair()
        logger.info("[TRACE-HK-4] 光标已设为十字")

        if self._mode_change_callback:
            logger.info("[TRACE-HK-5] 调用 _mode_change_callback(True)")
            self._mode_change_callback(True)
            logger.info("[TRACE-HK-6] _mode_change_callback(True) 返回")
        else:
            logger.warning("[TRACE-HK-6W] _mode_change_callback 为空！")

        logger.info("[TRACE-HK-7] 启动 mouse.Listener")
        self._mouse_listener = mouse.Listener(on_click=self._on_click)
        self._mouse_listener.daemon = True
        self._mouse_listener.start()
        logger.info("[TRACE-HK-8] mouse.Listener 已启动")

    def _exit_inspect_mode(self):
        """退出检查模式"""
        logger.info("[TRACE-HK-10] _exit_inspect_mode 开始")
        self._inspect_mode = False
        set_cursor_arrow()

        if self._mouse_listener and self._mouse_listener.is_alive():
            self._mouse_listener.stop()
            self._mouse_listener = None

        if self._mode_change_callback:
            logger.info("[TRACE-HK-11] 调用 _mode_change_callback(False)")
            self._mode_change_callback(False)
            logger.info("[TRACE-HK-12] _mode_change_callback(False) 返回")

    def _on_click(self, x, y, button, pressed):
        """检查模式下鼠标点击回调 - 左键或右键均可触发检查"""
        logger.info("[TRACE-CLICK-1] _on_click x=%d y=%d button=%s pressed=%s",
                    x, y, button, pressed)
        if not self._inspect_mode or not pressed:
            logger.info("[TRACE-CLICK-2] 跳过：inspect_mode=%s pressed=%s",
                        self._inspect_mode, pressed)
            return True

        if button in (mouse.Button.left, mouse.Button.right):
            logger.info("[TRACE-CLICK-3] 匹配 button=%s，退出检查模式并触发拾取", button)
            logger.info("触发拾取: (%d, %d)", x, y)
            self._exit_inspect_mode()

            threading.Thread(
                target=self.on_inspect, args=(x, y), daemon=True
            ).start()

            return False

        return True


class HotkeyCapture:
    """
    热键捕获器 - 用于设置新热键
    监听下一个按键组合并返回
    """

    def __init__(self, on_captured: Callable[[List[str], str], None]):
        self.on_captured = on_captured
        self._pressed_modifiers: Set[str] = set()
        self._listener: Optional[keyboard.Listener] = None
        self._captured = False

    def start(self):
        """开始捕获"""
        self._pressed_modifiers = set()
        self._captured = False
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.daemon = True
        self._listener.start()

    def stop(self):
        """停止捕获"""
        if self._listener and self._listener.is_alive():
            self._listener.stop()

    def _on_press(self, key):
        if self._captured:
            return

        try:
            logger.warning("[CAPTURE] 按键: key=%s char=%s name=%s vk=%s", 
                          key, getattr(key, "char", None), 
                          getattr(key, "name", None), getattr(key, "vk", None))

            if key in MODIFIER_MAP:
                self._pressed_modifiers.add(MODIFIER_MAP[key])
                return

            char = None
            if hasattr(key, "char") and key.char:
                char = key.char
                # 处理控制字符（如 Ctrl+数字）
                if len(char) == 1 and char < ' ':
                    vk = getattr(key, 'vk', None)
                    if vk:
                        char = _vk_to_char_simple(vk)
            elif hasattr(key, "name") and key.name:
                char = key.name
            elif hasattr(key, "vk") and key.vk:
                char = _vk_to_char_simple(key.vk)

            if char and char not in ("ctrl", "shift", "alt", "cmd"):
                logger.warning("[CAPTURE] 捕获成功: mods=%s char=%s", 
                              self._pressed_modifiers, char)
                self._captured = True
                mods = list(self._pressed_modifiers)
                self.stop()
                self.on_captured(mods, char)
            else:
                logger.warning("[CAPTURE] 未捕获: char=%s", char)
        except Exception as e:
            logger.warning("热键捕获异常: %s", e)

    def _on_release(self, key):
        if key in MODIFIER_MAP:
            self._pressed_modifiers.discard(MODIFIER_MAP[key])