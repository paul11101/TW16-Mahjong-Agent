"""W5 D1 熱鍵測試（假按鍵狀態，不會讀真的鍵盤）。

執行方式（專案根目錄）：
    python -m tests.test_hotkeys
或
    python -m pytest tests/test_hotkeys.py -v
"""

import time

import pytest

from src.control.controller import AgentController, ControlState
from src.control.hotkeys import DEFAULT_BINDINGS, HotkeyWatcher, key_to_vk
from test_interface.fakes import FakeMouse
from tests._runner import run_module


def chord(name):
    return {key_to_vk(k) for k in DEFAULT_BINDINGS[name]}


def make(down, **kw):
    controller = AgentController(game_id="t", mouse=FakeMouse())
    controller.start()
    watcher = HotkeyWatcher(controller, key_state_fn=lambda vk: vk in down, **kw)
    return watcher, controller


def test_key_to_vk():
    assert key_to_vk("ctrl") == 0x11 and key_to_vk("ALT") == 0x12 and key_to_vk("shift") == 0x10
    assert key_to_vk("p") == 0x50 and key_to_vk("5") == 0x35
    assert key_to_vk("f1") == 0x70 and key_to_vk("F12") == 0x7B
    with pytest.raises(ValueError):
        key_to_vk("enter")


def test_pause_resume_stop_chords():
    down = set()
    watcher, controller = make(down)

    down |= chord("pause")
    assert watcher.poll_once() == ["pause"]
    assert controller.state == ControlState.PAUSED

    down.clear()
    watcher.poll_once()
    down |= chord("resume")
    assert watcher.poll_once() == ["resume"]
    assert controller.state == ControlState.RUNNING

    down.clear()
    watcher.poll_once()
    down |= chord("stop")
    assert watcher.poll_once() == ["stop"]
    assert controller.is_stopped
    assert watcher.triggered == ["pause", "resume", "stop"]


def test_holding_keys_triggers_once_and_repress_triggers_again():
    down = chord("pause")
    triggers = []
    watcher, controller = make(down, on_trigger=triggers.append)

    assert watcher.poll_once() == ["pause"]
    assert watcher.poll_once() == []  # 按住不放
    assert watcher.poll_once() == []

    down.clear()
    assert watcher.poll_once() == []
    down |= chord("pause")
    assert watcher.poll_once() == ["pause"]  # 放開再按才算第二次
    assert triggers == ["pause", "pause"]


def test_partial_chord_does_not_trigger():
    down = {key_to_vk("ctrl"), key_to_vk("p")}  # 少了 Alt
    watcher, controller = make(down)

    assert watcher.poll_once() == []
    assert controller.is_running


def test_custom_bindings_and_unknown_action():
    down = {key_to_vk("f9")}
    watcher, controller = make(down, bindings={"stop": ("f9",)})

    assert watcher.poll_once() == ["stop"]
    assert controller.is_stopped

    with pytest.raises(ValueError):
        make(set(), bindings={"explode": ("f1",)})


def test_background_thread_pauses_controller():
    down = set()
    watcher, controller = make(down, poll_interval=0.01)

    with watcher:
        down |= chord("pause")
        deadline = time.monotonic() + 2.0
        while not controller.is_paused and time.monotonic() < deadline:
            time.sleep(0.01)

    assert controller.is_paused
    assert watcher._thread is None  # close() 已結束執行緒


if __name__ == "__main__":
    run_module(globals(), "test_hotkeys")