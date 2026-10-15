"""實機 runner 共用流程（A8）：check_mapping / run_auto_discard / run_auto_react 都用這裡。

包含：
- 共用命令列參數（add_common_args、add_action_args）
- 找視窗 -> 倒數 -> 拉前景 -> 擷取（open_session）
- 讀測試介面的 /api/layout、/api/clicks、/api/reactions
- 校正標記取得可視區原點（calibration_origin）
- 建立驗證器與重試設定（make_verifier_and_retry）

這是「實機測試工具」，放在 test_interface/；不可 import tests/。
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from src.control.action_executor import RetryPolicy
from src.control.capture import CaptureRegion, ScreenCapture
from src.control.controller import AgentController
from src.control.mouse import MouseController
from src.control.tile_mapper import default_viewport_offset, find_calibration_marker
from src.control.verifier import ActionVerifier
from src.control.window import DEFAULT_TITLE, WindowLocator, WindowNotFoundError

DEFAULT_URL = "http://127.0.0.1:8000"


# ------------------------------------------------------------------ 參數

def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--delay", type=float, default=0.0, help="開始前倒數秒數")
    parser.add_argument("--no-focus", action="store_true", help="不要自動把目標視窗拉到前景")


def add_action_args(parser: argparse.ArgumentParser) -> None:
    """會真的點擊的 runner 才需要（run_auto_discard / run_auto_react）。"""
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--no-verify", action="store_true", help="不做點擊後畫面驗證（也不重試）")
    parser.add_argument("--verify-timeout", type=float, default=1.0, help="驗證逾時秒數")
    parser.add_argument("--min-change", type=float, default=0.005, help="視為有變化的像素比例門檻")
    parser.add_argument("--max-retries", type=int, default=1, help="逾時後最多重點幾次（0 = 只多等不重點）")
    parser.add_argument("--grace", type=float, default=0.5, help="重點前多觀察的秒數（只看不點）")
    parser.add_argument("--full-verify", action="store_true",
                        help="驗證時擷取整個視窗（較慢；預設只擷取點擊點附近，實測 latency 約少一半）")
    # 舊參數：ROI 驗證現在是預設，保留這個參數讓舊指令不會報錯
    parser.add_argument("--roi-verify", action="store_true", help=argparse.SUPPRESS)


# ------------------------------------------------------------------ 視窗與擷取

@dataclass
class LiveSession:
    """一次實機執行用到的視窗與第一張畫面。"""

    locator: WindowLocator
    capturer: ScreenCapture
    region: CaptureRegion
    frame: np.ndarray

    @property
    def width(self) -> int:
        return self.frame.shape[1]

    @property
    def height(self) -> int:
        return self.frame.shape[0]


def open_session(
    args: argparse.Namespace,
    *,
    page_hint: str = "",
    locator: WindowLocator | None = None,
    grab_fn: Callable[[CaptureRegion | None], np.ndarray] | None = None,
) -> LiveSession | None:
    """找視窗 -> 倒數 -> 拉前景 -> 擷取一張畫面。找不到視窗回傳 None（已印出原因）。

    page_hint：找不到視窗時附加在網址後面的提示，例如「/?scenario=reaction」。
    locator / grab_fn：測試用，傳入假的就不會碰 Win32 與 mss。
    """
    locator = locator or WindowLocator(args.title)
    if locator.find() is None:
        print(f"❌ 找不到視窗（標題含「{args.title}」），請先用瀏覽器開 {args.url}{page_hint}")
        return None

    for remaining in range(int(args.delay), 0, -1):
        print(f"{remaining} 秒後開始...")
        time.sleep(1)

    if not args.no_focus:
        print(f"自動切到目標視窗：{'成功' if locator.bring_to_front() else '失敗'}")
        time.sleep(1.0)  # 等視窗切換與重繪完成

    capturer = locator.make_capturer(grab_fn=grab_fn)
    region = capturer.region
    frame = np.ascontiguousarray(capturer.grab())
    height, width = frame.shape[:2]

    print(f"視窗區域：left={region.left} top={region.top} width={region.width} height={region.height}")
    print(f"擷取畫面：{width}x{height}")
    if (width, height) != (region.width, region.height):
        print("⚠️ 擷取大小與視窗區域不同，請檢查 DPI 設定")

    return LiveSession(locator=locator, capturer=capturer, region=region, frame=frame)


# ------------------------------------------------------------------ 測試介面 API

def fetch_json(base_url: str, path: str, *, timeout: float = 3.0) -> Any:
    with urllib.request.urlopen(base_url.rstrip("/") + path, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_layout(base_url: str) -> dict:
    return fetch_json(base_url, "/api/layout")


def fetch_clicks(base_url: str) -> list[dict]:
    return fetch_json(base_url, "/api/clicks").get("clicks", [])


def fetch_reactions(base_url: str) -> list[dict]:
    return fetch_json(base_url, "/api/reactions").get("reactions", [])


# ------------------------------------------------------------------ 滑鼠、原點、驗證器

def make_mouse() -> MouseController:
    """實機用滑鼠：先把 pyautogui 載入好，第一次點擊的 latency 才不會包含 import 時間。"""
    mouse = MouseController()
    mouse.warmup()
    return mouse


def calibration_origin(frame: np.ndarray, layout: dict | None = None) -> tuple[int, int] | None:
    """用校正標記找「網頁可視區原點」（frame 像素）；找不到回傳 None 並印出估計值。"""
    marker = find_calibration_marker(frame)
    if marker is not None:
        origin = (marker[0], marker[1])
        print(f"可視區原點：校正標記 {origin}")
        return origin

    estimate = default_viewport_offset(layout) if layout else None
    print(f"可視區原點：估計值 {estimate}（找不到校正標記，請確認網頁已載入並按 Ctrl+F5）")
    return None


def make_verifier_and_retry(
    args: argparse.Namespace,
    controller: AgentController,
    session: LiveSession | None = None,
) -> tuple[ActionVerifier | None, RetryPolicy | None]:
    """--no-verify 時兩者都是 None（沒有驗證就不重試）。

    有傳入 session 且沒有 --full-verify 時，預設用 ROI 擷取（B2）：
    只抓點擊點附近，並用 region_guard 確認視窗位置／大小沒變
    （ROI 大小固定，看不出視窗被縮放或移動）。沒有 session 時退回整窗擷取。
    """
    if args.no_verify:
        return None, None

    options: dict[str, Any] = {}
    if not getattr(args, "full_verify", False) and session is not None:

        def region_guard() -> bool:
            try:
                return session.locator.locate() == session.region
            except WindowNotFoundError:
                return False

        options = dict(
            roi_capture_fn=controller.capture_roi,
            frame_size=(session.width, session.height),
            region_guard=region_guard,
        )

    verifier = ActionVerifier(
        controller.capture,
        timeout=args.verify_timeout,
        min_change_ratio=args.min_change,
        **options,
    )
    return verifier, RetryPolicy(args.max_retries, args.grace)


def print_receipt(receipt: Any, verifier: ActionVerifier | None) -> None:
    """印出回執與每次驗證的結果（校正門檻用）。"""
    print(
        f"回執：success={receipt.success} ui_action_executed={receipt.ui_action_executed} "
        f"state_verified={receipt.state_verified} retry_count={receipt.retry_count} "
        f"latency={receipt.latency_ms:.1f}ms error={receipt.error_code}"
    )
    if verifier is not None:
        for i, v in enumerate(verifier.history, 1):
            print(f"驗證[{i}]：{v.describe()}")