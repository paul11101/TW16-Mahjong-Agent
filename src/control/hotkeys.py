"""全域熱鍵（W5 D1）：不需要視窗在前景也能暫停／繼續／立即停止。

預設：
    Ctrl+Alt+P  暫停
    Ctrl+Alt+R  繼續
    Ctrl+Alt+S  停止（STOPPED 之後 controller 不能重啟）

做法：背景執行緒輪詢 Win32 GetAsyncKeyState（ctypes，不用新增套件）。
只在「按下的瞬間」觸發一次，按住不放不會重複觸發。
key_state_fn 可替換成假的（測試用），所以非 Windows 也能載入與測試。
"""

from __future__ import annotations

import sys
import threading
from typing import Callable, Mapping, Sequence

from src.control.controller import AgentController

_MODIFIERS = {"shift": 0x10, "ctrl": 0x11, "alt": 0x12}

DEFAULT_BINDINGS: dict[str, tuple[str, ...]] = {
    "pause": ("ctrl", "alt", "p"),
    "resume": ("ctrl", "alt", "r"),
    "stop": ("ctrl", "alt", "s"),
}

KeyStateFn = Callable[[int], bool]


def key_to_vk(key: str) -> int:
    """鍵名 -> Windows virtual-key code（支援 ctrl/alt/shift、A-Z、0-9、f1~f12）。"""
    name = key.lower()
    if name in _MODIFIERS:
        return _MODIFIERS[name]
    if len(name) == 1 and name.isalnum():
        return ord(name.upper())
    if name.startswith("f") and name[1:].isdigit() and 1 <= int(name[1:]) <= 12:
        return 0x70 + int(name[1:]) - 1
    raise ValueError(f"不支援的按鍵：{key}")


def _win32_key_down(vk: int) -> bool:
    import ctypes

    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


class HotkeyWatcher:
    def __init__(
        self,
        controller: AgentController,
        *,
        key_state_fn: KeyStateFn | None = None,
        bindings: Mapping[str, Sequence[str]] | None = None,
        poll_interval: float = 0.03,
        on_trigger: Callable[[str], None] | None = None,
    ) -> None:
        if key_state_fn is None:
            if sys.platform != "win32":
                raise RuntimeError("預設熱鍵只支援 Windows；請傳入 key_state_fn。")
            key_state_fn = _win32_key_down

        chosen = dict(bindings) if bindings is not None else dict(DEFAULT_BINDINGS)
        unknown = set(chosen) - {"pause", "resume", "stop"}
        if unknown:
            raise ValueError(f"不支援的熱鍵動作：{sorted(unknown)}")

        self.controller = controller
        self.poll_interval = poll_interval
        self.on_trigger = on_trigger
        self.triggered: list[str] = []
        self._key_state = key_state_fn
        self._chords = {name: tuple(key_to_vk(k) for k in keys) for name, keys in chosen.items()}
        self._held = {name: False for name in self._chords}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def poll_once(self) -> list[str]:
        """檢查一次；回傳這次新觸發的動作名稱。"""
        fired: list[str] = []
        for name, chord in self._chords.items():
            down = all(self._key_state(vk) for vk in chord)
            if down and not self._held[name]:
                fired.append(name)
                self._trigger(name)
            self._held[name] = down
        return fired

    def _trigger(self, name: str) -> None:
        if name == "pause":
            self.controller.pause()
        elif name == "resume":
            self.controller.resume()
        elif name == "stop":
            self.controller.stop()

        self.triggered.append(name)
        if self.on_trigger is not None:
            self.on_trigger(name)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()

        def loop() -> None:
            while not self._stop_event.is_set():
                self.poll_once()
                self._stop_event.wait(self.poll_interval)

        self._thread = threading.Thread(target=loop, name="hotkey-watcher", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def __enter__(self) -> "HotkeyWatcher":
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()