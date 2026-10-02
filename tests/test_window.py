"""W3 D2 視窗定位／固定視窗擷取測試（使用假視窗清單，不需要瀏覽器）。

執行方式（專案根目錄）：
    python -m tests.test_window
或
    python -m pytest tests/test_window.py -v
"""

import numpy as np

from src.control.capture import CaptureRegion, ScreenCapture
from src.control.controller import AgentController
from src.control.window import (
    WindowInfo,
    WindowLocator,
    WindowNotFoundError,
    frame_to_screen,
)

TITLE = "台灣16張麻將 Agent 測試介面"


def _win(title, hwnd=1, **kw):
    base = dict(left=100, top=50, width=800, height=600)
    base.update(kw)
    return WindowInfo(hwnd=hwnd, title=title, **base)


def _locator(windows, **kw):
    return WindowLocator(TITLE, list_fn=lambda: windows, **kw)


def test_find_matches_title_case_insensitive():
    loc = WindowLocator("AGENT 測試", list_fn=lambda: [_win(TITLE + " - Google Chrome")])
    assert loc.find() is not None


def test_locate_returns_client_region():
    region = _locator([_win(TITLE + " - Chrome", left=10, top=20, width=1280, height=720)]).locate()
    assert (region.left, region.top, region.width, region.height) == (10, 20, 1280, 720)


def test_skips_invisible_minimized_and_empty_windows():
    windows = [
        _win(TITLE, hwnd=1, visible=False),
        _win(TITLE, hwnd=2, minimized=True),
        _win(TITLE, hwnd=3, width=0),
        _win("別的視窗", hwnd=4),
        _win(TITLE, hwnd=5, left=7),
    ]
    found = _locator(windows).find()
    assert found is not None and found.hwnd == 5


def test_picks_topmost_when_multiple_match():
    windows = [_win(TITLE, hwnd=1, left=1), _win(TITLE, hwnd=2, left=2)]
    assert _locator(windows).find().hwnd == 1


def test_exclude_titles():
    windows = [_win(TITLE + " - Visual Studio Code", hwnd=1), _win(TITLE + " - Chrome", hwnd=2)]
    found = _locator(windows, exclude_titles=["Visual Studio Code"]).find()
    assert found is not None and found.hwnd == 2


def test_not_found_raises():
    loc = _locator([_win("別的視窗")])
    assert loc.find() is None
    try:
        loc.locate()
    except WindowNotFoundError:
        pass
    else:
        raise AssertionError("應該拋出 WindowNotFoundError")


def test_is_foreground():
    assert _locator([_win(TITLE, foreground=True)]).is_foreground() is True
    assert _locator([_win(TITLE, foreground=False)]).is_foreground() is False
    assert _locator([]).is_foreground() is False


def test_bring_to_front_calls_focus_fn_with_hwnd():
    calls = []
    loc = WindowLocator(
        TITLE,
        list_fn=lambda: [_win(TITLE, hwnd=42)],
        focus_fn=lambda hwnd: calls.append(hwnd) or True,
    )
    assert loc.bring_to_front() is True
    assert calls == [42]

    # 找不到視窗時不呼叫 focus_fn
    calls.clear()
    empty = WindowLocator(TITLE, list_fn=lambda: [], focus_fn=lambda h: calls.append(h) or True)
    assert empty.bring_to_front() is False
    assert calls == []


def test_frame_to_screen_adds_offset():
    region = CaptureRegion(100, 50, 800, 600)
    assert frame_to_screen(region, 30, 40) == (130, 90)


def test_capturer_uses_window_region_and_relocate():
    windows = [_win(TITLE, left=100, top=50, width=800, height=600)]
    loc = _locator(windows)
    seen = []

    def fake_grab(region):
        seen.append(region)
        return np.zeros((region.height, region.width, 4), dtype=np.uint8)

    capturer = loc.make_capturer(grab_fn=fake_grab)
    assert capturer.grab().shape == (600, 800, 3)

    # 視窗移動／縮放後重新定位
    windows[0] = _win(TITLE, left=0, top=0, width=400, height=300)
    capturer.region = loc.locate()
    assert capturer.grab().shape == (300, 400, 3)
    assert seen[0].left == 100 and seen[1].left == 0


def test_controller_capture_with_window_capturer():
    loc = _locator([_win(TITLE, width=320, height=240)])
    capturer = loc.make_capturer(
        grab_fn=lambda r: np.zeros((r.height, r.width, 4), dtype=np.uint8)
    )
    controller = AgentController(capturer=capturer)
    assert controller.capture().shape == (240, 320, 3)
    controller.stop()
    assert controller.capture() is None


if __name__ == "__main__":
    test_find_matches_title_case_insensitive()
    test_locate_returns_client_region()
    test_skips_invisible_minimized_and_empty_windows()
    test_picks_topmost_when_multiple_match()
    test_exclude_titles()
    test_not_found_raises()
    test_is_foreground()
    test_bring_to_front_calls_focus_fn_with_hwnd()
    test_frame_to_screen_adds_offset()
    test_capturer_uses_window_region_and_relocate()
    test_controller_capture_with_window_capturer()
    print("✅ test_window：11 項測試全部通過")