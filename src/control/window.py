"""視窗定位：用視窗標題找到目標視窗，回傳「客戶區」的螢幕座標範圍。

W3 D2：目標是 test_interface 的瀏覽器頁面（標題含「台灣16張麻將 Agent 測試介面」）。
W5 之後換成真實遊戲畫面時，只要改 title_contains 即可，其他程式不用動。

為什麼用 ctypes + Win32：
- 不需要新增套件（pygetwindow / pywin32 都不用裝），requirements.txt 不用改。
- 直接取得「客戶區」（不含標題列與邊框），Win10/11 的隱形陰影邊框不會讓座標偏移。

注意：
- 本模組只在 Windows 實際列舉視窗；其他系統 import 沒問題，但呼叫預設後端會拋 RuntimeError
  （測試請傳入 list_fn 假後端）。
- mss 擷取的是「螢幕上實際看到的像素」，所以目標視窗必須在前景、沒有被其他視窗蓋住。
- 瀏覽器的客戶區包含分頁列與網址列，網頁內容從更下方開始；W3 D3 做座標映射時，
  請以「擷取到的畫面」為基準，再用 frame_to_screen() 換回螢幕座標。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable, Sequence

from src.control.capture import CaptureRegion, ScreenCapture

DEFAULT_TITLE = "台灣16張麻將 Agent 測試介面"


class WindowNotFoundError(RuntimeError):
    """找不到符合條件的可見視窗。"""


@dataclass(frozen=True)
class WindowInfo:
    """一個視窗的資訊；left/top/width/height 為客戶區的螢幕像素座標。"""

    hwnd: int
    title: str
    left: int
    top: int
    width: int
    height: int
    visible: bool = True
    minimized: bool = False
    foreground: bool = False

    def to_region(self) -> CaptureRegion:
        return CaptureRegion(self.left, self.top, self.width, self.height)


# 視窗列舉函式：由上到下（Z 軸順序）回傳所有視窗；測試時可替換成假資料
ListWindowsFn = Callable[[], Sequence[WindowInfo]]


def frame_to_screen(region: CaptureRegion, x: int, y: int) -> tuple[int, int]:
    """把「擷取畫面內」的座標換成「螢幕」座標（點擊用）。

    視覺回傳的 bbox 是相對擷取畫面的；實際點擊要加上視窗左上角偏移。
    """
    return region.left + x, region.top + y


def _enable_dpi_awareness() -> None:
    """讓座標使用實際像素，與 mss / pyautogui 一致（否則縮放 125% 以上會偏移）。"""
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _win32_list_windows() -> list[WindowInfo]:
    """預設後端：用 Win32 API 列舉所有有標題的視窗。"""
    if sys.platform != "win32":
        raise RuntimeError("預設視窗列舉只支援 Windows；請傳入 list_fn。")

    import ctypes
    from ctypes import wintypes

    _enable_dpi_awareness()
    user32 = ctypes.windll.user32

    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetForegroundWindow.restype = wintypes.HWND

    foreground_hwnd = user32.GetForegroundWindow()
    windows: list[WindowInfo] = []

    def _callback(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True

        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)

        rect = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        origin = wintypes.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(origin))

        windows.append(
            WindowInfo(
                hwnd=int(hwnd or 0),
                title=buf.value,
                left=origin.x,
                top=origin.y,
                width=rect.right - rect.left,
                height=rect.bottom - rect.top,
                visible=bool(user32.IsWindowVisible(hwnd)),
                minimized=bool(user32.IsIconic(hwnd)),
                foreground=(hwnd == foreground_hwnd),
            )
        )
        return True

    user32.EnumWindows(enum_proc(_callback), 0)
    return windows


def _win32_bring_to_front(hwnd: int) -> bool:
    """把視窗拉到最前景；成功回傳 True。

    先用一般的 SetForegroundWindow；失敗才用「模擬按一下 Alt」的老方法再試一次
    （Windows 會限制背景程式搶前景）。
    """
    if sys.platform != "win32":
        raise RuntimeError("bring_to_front 只支援 Windows；請傳入 focus_fn。")

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.GetForegroundWindow.restype = wintypes.HWND

    def _is_front() -> bool:
        return int(user32.GetForegroundWindow() or 0) == hwnd

    user32.SetForegroundWindow(hwnd)
    if not _is_front():
        user32.keybd_event(0x12, 0, 0, 0)  # Alt down
        user32.keybd_event(0x12, 0, 2, 0)  # Alt up
        user32.SetForegroundWindow(hwnd)

    return _is_front()


class WindowLocator:
    """依標題關鍵字找視窗，並產生固定區域的擷取器。"""

    def __init__(
        self,
        title_contains: str = DEFAULT_TITLE,
        *,
        exclude_titles: Sequence[str] = (),
        list_fn: ListWindowsFn | None = None,
        focus_fn: Callable[[int], bool] | None = None,
    ) -> None:
        self.title_contains = title_contains
        self.exclude_titles = tuple(exclude_titles)
        self._list_fn = list_fn or _win32_list_windows
        self._focus_fn = focus_fn or _win32_bring_to_front

    def find(self) -> WindowInfo | None:
        """回傳最上層、可見、未最小化、客戶區大小 > 0 的符合視窗；找不到回傳 None。"""
        keyword = self.title_contains.lower()
        excluded = [t.lower() for t in self.exclude_titles]

        for win in self._list_fn():
            title = win.title.lower()
            if keyword not in title:
                continue
            if any(ex in title for ex in excluded):
                continue
            if not win.visible or win.minimized:
                continue
            if win.width <= 0 or win.height <= 0:
                continue
            return win

        return None

    def locate(self) -> CaptureRegion:
        """回傳目標視窗的擷取範圍；找不到就拋 WindowNotFoundError。"""
        win = self.find()
        if win is None:
            raise WindowNotFoundError(
                f"找不到視窗（標題含「{self.title_contains}」，需可見且未最小化）"
            )
        return win.to_region()

    def is_foreground(self) -> bool:
        """目標視窗目前是否在最前景（W5 的「視窗不在前景就停止操作」會用到）。"""
        win = self.find()
        return win is not None and win.foreground

    def bring_to_front(self) -> bool:
        """把目標視窗拉到最前景（避免被 PowerShell 等視窗蓋住）；找不到視窗回傳 False。"""
        win = self.find()
        if win is None:
            return False
        return bool(self._focus_fn(win.hwnd))

    def make_capturer(self, **kwargs) -> ScreenCapture:
        """找到視窗後建立固定區域的 ScreenCapture（可直接傳給 AgentController）。

        視窗移動或縮放後，用 capturer.region = locator.locate() 重新定位。
        """
        return ScreenCapture(region=self.locate(), **kwargs)



if __name__ == "__main__":
    import argparse
    import time

    parser = argparse.ArgumentParser(description="視窗定位與擷取測試")
    parser.add_argument("--title", default=DEFAULT_TITLE, help="視窗標題關鍵字")
    parser.add_argument("--out", default="data/raw/window_capture_test.png")
    parser.add_argument("--delay", type=float, default=0.0,
                        help="開始前倒數秒數（想手動切到瀏覽器時使用）")
    parser.add_argument("--no-focus", action="store_true",
                        help="不要自動把目標視窗拉到前景")
    args = parser.parse_args()

    locator = WindowLocator(args.title)

    if locator.find() is None:
        print(f"❌ 找不到視窗（標題含「{args.title}」，需可見且未最小化）")
        print("請先用瀏覽器開啟 http://127.0.0.1:8000 ，且不要最小化。")
        raise SystemExit(1)

    for remaining in range(int(args.delay), 0, -1):
        print(f"{remaining} 秒後擷取...")
        time.sleep(1)

    if not args.no_focus:
        ok = locator.bring_to_front()
        print(f"自動切到目標視窗：{'成功' if ok else '失敗（請手動點一下瀏覽器，或用 --delay 5）'}")
        time.sleep(1.0)  # 等視窗切換與重繪完成

    capturer = locator.make_capturer()
    region = capturer.region
    print(f"找到視窗：left={region.left} top={region.top} "
          f"width={region.width} height={region.height}")
    print(f"目標視窗是否在前景：{locator.is_foreground()}")

    frame = capturer.grab()
    path = capturer.save(args.out)
    print(f"擷取畫面大小：{frame.shape[1]}x{frame.shape[0]}（應與視窗大小相同）")
    print(f"✅ 已儲存視窗截圖：{path}")