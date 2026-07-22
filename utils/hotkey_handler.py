"""
GUI 元素探查器 - 全局热键与鼠标钩子管理
使用 Win32 RegisterHotKey API 注册热键，不干扰系统键盘输入
"""

import threading
import json
import os
import ctypes
import ctypes.wintypes
from pynput import mouse
from typing import Callable, Optional, List, Set

import keyboard as kb_lib

from utils.logging_utils import get_logger

logger = get_logger(__name__)


# ── Windows 常量 ──────────────────────────────────────────────
IDC_CROSS = 32515
IDC_ARROW = 32512

# RegisterHotKey 修饰键常量
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

# 字符串 → 修饰键标记
_MODIFIER_FLAGS = {
    "ctrl": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "alt": MOD_ALT,
    "win": MOD_WIN,
}

# 热键 ID
HOTKEY_ID_PICK = 1
HOTKEY_ID_SCREENSHOT = 2

# 虚拟键码映射
_VK_MAP = {}
# 字母 A-Z (0x41-0x5A)
for i in range(26):
    _VK_MAP[chr(ord('a') + i)] = 0x41 + i
# 数字 0-9 (0x30-0x39)
for i in range(10):
    _VK_MAP[str(i)] = 0x30 + i
# 功能键 F1-F12 (0x70-0x7B)
for i in range(1, 13):
    _VK_MAP[f"f{i}"] = 0x6F + i
# 其他常用键
_VK_MAP.update({
    "space": 0x20,
    "tab": 0x09,
    "enter": 0x0D,
    "backspace": 0x08,
    "delete": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "escape": 0x1B,
    "esc": 0x1B,
    "printscreen": 0x2C,
    "scrolllock": 0x91,
    "pause": 0x13,
    "numlock": 0x90,
    "capslock": 0x14,
    "-": 0xBD,
    "=": 0xBB,
    "[": 0xDB,
    "]": 0xDD,
    "\\": 0xDC,
    ";": 0xBA,
    "'": 0xDE,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
    "`": 0xC0,
})

user32 = ctypes.windll.user32

# 配置文件路径
_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".gui_inspector")
CONFIG_FILE = os.path.join(_CONFIG_DIR, "hotkey_config.json")


def _key_to_vk(key: str) -> int:
    """将键名字符串转为虚拟键码"""
    k = key.lower()
    if k in _VK_MAP:
        return _VK_MAP[k]
    if len(k) == 1:
        return ord(k.upper())
    raise ValueError(f"不支持的键: {key}")


def _modifiers_to_flags(modifiers: set) -> int:
    """将修饰键集合转为 RegisterHotKey 标志位"""
    flags = 0
    for m in modifiers:
        flags |= _MODIFIER_FLAGS.get(m.lower(), 0)
    return flags


def set_cursor_crosshair():
    """将光标设置为十字准星"""
    hcursor = user32.LoadCursorW(0, IDC_CROSS)
    user32.SetSystemCursor(hcursor, IDC_ARROW)


def set_cursor_arrow():
    """将光标恢复为默认箭头"""
    user32.SystemParametersInfoW(0x0057, 0, None, 0)


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
        os.makedirs(_CONFIG_DIR, exist_ok=True)
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
    """全局热键管理器（单例模式）

    使用 Win32 RegisterHotKey API 注册热键，
    不拦截系统键盘输入，Ctrl+C/V/Z 等全部正常工作。
    """

    @classmethod
    def instance(cls) -> "HotkeyHandler":
        global _shared_instance
        if _shared_instance is None:
            raise RuntimeError("HotkeyHandler 尚未初始化，请先调用 HotkeyHandler.init()")
        return _shared_instance

    @classmethod
    def init(cls, on_inspect: Callable[[int, int], None],
             on_screenshot: Optional[Callable[[], None]] = None) -> "HotkeyHandler":
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
        self._hwnd = 0  # 主窗口句柄，用于 RegisterHotKey
        self._mouse_listener: Optional[mouse.Listener] = None
        self._mode_change_callback: Optional[Callable[[bool], None]] = None
        self._esc_hook_id = None
        self._hotkeys_registered = False

        self._reload_config()

    def set_hwnd(self, hwnd: int):
        """设置主窗口句柄（必须在 start() 之前调用）"""
        self._hwnd = hwnd

    def _reload_config(self):
        cfg = _load_config()
        self._required_modifiers = set(cfg.get("modifiers", ["Ctrl", "Shift"]))
        self._trigger_key = cfg.get("key", "i").lower()
        self._screenshot_modifiers = set(cfg.get("screenshot_modifiers", ["Ctrl", "Shift"]))
        self._screenshot_key = cfg.get("screenshot_key", "s").lower()

    def set_hotkey(self, modifiers: List[str], key: str):
        cfg = _load_config()
        cfg["modifiers"] = modifiers
        cfg["key"] = key.lower()
        _save_config(cfg)
        self._reload_config()
        self._reregister_hotkeys()
        logger.info("热键已修改为: %s+%s", "+".join(modifiers), key)

    def set_screenshot_hotkey(self, modifiers: List[str], key: str):
        cfg = _load_config()
        cfg["screenshot_modifiers"] = modifiers
        cfg["screenshot_key"] = key.lower()
        _save_config(cfg)
        self._reload_config()
        self._reregister_hotkeys()
        logger.info("截图热键已修改为: %s+%s", "+".join(modifiers), key)

    def get_hotkey_info(self) -> dict:
        return _load_config()

    def get_screenshot_hotkey_info(self) -> dict:
        cfg = _load_config()
        return {
            "modifiers": cfg.get("screenshot_modifiers", ["Ctrl", "Shift"]),
            "key": cfg.get("screenshot_key", "s"),
        }

    def set_mode_change_callback(self, callback: Callable[[bool], None]):
        self._mode_change_callback = callback

    @property
    def inspect_mode(self) -> bool:
        return self._inspect_mode

    # ── 热键注册 ──────────────────────────────────────────────

    def start(self):
        """注册热键（必须在主线程且 set_hwnd() 之后调用）"""
        if not self._hwnd:
            logger.error("[HOTKEY] HWND 未设置，无法注册热键")
            return
        self._register_pick_hotkey()
        self._register_screenshot_hotkey()
        self._hotkeys_registered = True
        logger.info("[HOTKEY] 热键已注册 (RegisterHotKey)")

    def stop(self):
        """停止所有监听"""
        self._exit_inspect_mode()
        self._unregister_all_hotkeys()
        self._hotkeys_registered = False

    def _register_pick_hotkey(self):
        try:
            mod = _modifiers_to_flags(self._required_modifiers) | MOD_NOREPEAT
            vk = _key_to_vk(self._trigger_key)
            result = user32.RegisterHotKey(self._hwnd, HOTKEY_ID_PICK, mod, vk)
            if result:
                logger.info("[HOTKEY] 拾取热键注册成功: mods=%s key=%s",
                           self._required_modifiers, self._trigger_key)
            else:
                logger.warning("[HOTKEY] 拾取热键注册失败: GetLastError=%s",
                              ctypes.get_last_error())
        except Exception as e:
            logger.warning("[HOTKEY] 拾取热键注册异常: %s", e)

    def _register_screenshot_hotkey(self):
        try:
            mod = _modifiers_to_flags(self._screenshot_modifiers) | MOD_NOREPEAT
            vk = _key_to_vk(self._screenshot_key)
            result = user32.RegisterHotKey(self._hwnd, HOTKEY_ID_SCREENSHOT, mod, vk)
            if result:
                logger.info("[HOTKEY] 截图热键注册成功: mods=%s key=%s",
                           self._screenshot_modifiers, self._screenshot_key)
            else:
                logger.warning("[HOTKEY] 截图热键注册失败: GetLastError=%s",
                              ctypes.get_last_error())
        except Exception as e:
            logger.warning("[HOTKEY] 截图热键注册异常: %s", e)

    def _unregister_all_hotkeys(self):
        if self._hwnd:
            user32.UnregisterHotKey(self._hwnd, HOTKEY_ID_PICK)
            user32.UnregisterHotKey(self._hwnd, HOTKEY_ID_SCREENSHOT)

    def _reregister_hotkeys(self):
        """修改热键后重新注册"""
        if self._hotkeys_registered and self._hwnd:
            self._unregister_all_hotkeys()
            self._register_pick_hotkey()
            self._register_screenshot_hotkey()

    # ── WM_HOTKEY 分发 ────────────────────────────────────────

    def handle_hotkey(self, hotkey_id: int):
        """处理 WM_HOTKEY 消息（由 main window 的 nativeEvent 调用）"""
        if hotkey_id == HOTKEY_ID_PICK:
            logger.info("[HOTKEY] WM_HOTKEY: 拾取")
            self._enter_inspect_mode()
        elif hotkey_id == HOTKEY_ID_SCREENSHOT:
            logger.info("[HOTKEY] WM_HOTKEY: 截图")
            if self.on_screenshot:
                threading.Thread(target=self.on_screenshot, daemon=True).start()

    # ── 拾取模式 ──────────────────────────────────────────────

    def _enter_inspect_mode(self):
        logger.info("[TRACE-HK-1] _enter_inspect_mode 开始")
        if self._inspect_mode:
            logger.info("[TRACE-HK-2] 已在检查模式，直接返回")
            return

        self._inspect_mode = True
        logger.info("[TRACE-HK-3] _inspect_mode 设为 True")

        # 拾取模式期间：热键由 RegisterHotKey 管理，无需暂停
        # 启动轻量 ESC 监听
        self._start_esc_hook()

        set_cursor_crosshair()
        logger.info("[TRACE-HK-4] 光标已设为十字")

        if self._mode_change_callback:
            self._mode_change_callback(True)

        self._mouse_listener = mouse.Listener(on_click=self._on_click)
        self._mouse_listener.daemon = True
        self._mouse_listener.start()
        logger.info("[TRACE-HK-8] mouse.Listener 已启动")

    def _start_esc_hook(self):
        try:
            self._esc_hook_id = kb_lib.on_press_key('esc', self._on_esc_in_inspect, suppress=False)
            logger.info("[TRACE-HK] ESC 钩子已注册: id=%s", self._esc_hook_id)
        except Exception as e:
            logger.warning("[TRACE-HK] 注册 ESC 钩子失败: %s", e)

    def _stop_esc_hook(self):
        if self._esc_hook_id is not None:
            try:
                kb_lib.unhook(self._esc_hook_id)
                logger.info("[TRACE-HK] ESC 钩子已移除")
            except Exception as e:
                logger.warning("[TRACE-HK] 移除 ESC 钩子失败: %s", e)
            self._esc_hook_id = None

    def _on_esc_in_inspect(self, event):
        if self._inspect_mode:
            logger.info("[HOTKEY] 拾取模式下 ESC 按下，退出检查模式")
            self._exit_inspect_mode()

    def _exit_inspect_mode(self):
        logger.info("[TRACE-HK-10] _exit_inspect_mode 开始")
        self._inspect_mode = False
        set_cursor_arrow()

        self._stop_esc_hook()

        if self._mouse_listener and self._mouse_listener.is_alive():
            self._mouse_listener.stop()
            self._mouse_listener = None

        if self._mode_change_callback:
            self._mode_change_callback(False)

    def _on_click(self, x, y, button, pressed):
        if not self._inspect_mode or not pressed:
            return True

        if button in (mouse.Button.left, mouse.Button.right):
            logger.info("触发拾取: (%d, %d)", x, y)
            self._exit_inspect_mode()
            threading.Thread(target=self.on_inspect, args=(x, y), daemon=True).start()
            return False

        return True


class HotkeyCapture:
    """热键捕获器 - 用于设置新热键"""

    def __init__(self, on_captured: Callable[[List[str], str], None]):
        self.on_captured = on_captured
        self._pressed_modifiers: Set[str] = set()
        self._hook_id = None
        self._captured = False

    def start(self):
        self._pressed_modifiers = set()
        self._captured = False
        self._hook_id = kb_lib.hook(self._on_event, suppress=False)

    def stop(self):
        if self._hook_id is not None:
            try:
                kb_lib.unhook(self._hook_id)
            except Exception:
                pass
            self._hook_id = None

    def _on_event(self, event):
        if self._captured:
            return

        try:
            if event.event_type != 'down':
                return

            name = event.name.lower() if event.name else None

            if name in ("ctrl", "shift", "alt", "cmd"):
                self._pressed_modifiers.add(name)
                return

            char = name
            if char is None or char in ("ctrl", "shift", "alt", "cmd"):
                return

            logger.info("[CAPTURE] 捕获成功: mods=%s key=%s", self._pressed_modifiers, char)
            self._captured = True
            mods = list(self._pressed_modifiers)
            self.stop()
            self.on_captured(mods, char)
        except Exception as e:
            logger.warning("热键捕获异常: %s", e)