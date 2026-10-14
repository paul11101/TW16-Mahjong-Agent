"""延遲量測：只量時間，不點擊、不改任何現有程式的行為。

量三件事，並各自跟「可能的改法」比較：

  B1 擷取：目前每次 ScreenCapture.grab() 都重新建立 mss  vs  重用同一個 mss 實例
  B2 擷取範圍：整個視窗  vs  只抓點擊點附近的 300x300 區域（驗證輪詢用）
  B3 前景檢查：目前 WindowLocator.is_foreground()（每次列舉所有視窗）
               vs  只比對 GetForegroundWindow() 與已知的 hwnd
另外量 frame_diff_ratio（驗證輪詢的比對成本），估算一次輪詢花多久。

事前準備（兩個 PowerShell 視窗，專案根目錄）：
    uvicorn test_interface.app:app --reload
瀏覽器開 http://127.0.0.1:8000（不要最小化、不要被擋住），再執行：
    python -m test_interface.measure_latency --delay 3 --n 30

輸出：終端機表格（ms）＋ data/processed/latency_measure.json
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Callable

from src.control.capture import CaptureRegion, ScreenCapture
from src.control.verifier import frame_diff_ratio
from test_interface.live_common import add_common_args, open_session

OUT_PATH = Path("data/processed/latency_measure.json")
ROI_SIZE = 300  # 只抓點擊點附近的邊長（像素）


def time_ms(fn: Callable[[], object], n: int, *, warmup: int = 2) -> list[float]:
    """先暖機 warmup 次（不計），再量 n 次，回傳每次耗時（毫秒）。"""
    for _ in range(warmup):
        fn()

    samples: list[float] = []
    for _ in range(n):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    return samples


def stats_ms(samples: list[float]) -> dict[str, float]:
    """平均、中位數、p95（最近排名法）、最小、最大。"""
    if not samples:
        raise ValueError("samples 不可為空")

    ordered = sorted(samples)
    n = len(ordered)
    p95 = ordered[min(n - 1, math.ceil(0.95 * n) - 1)]
    return {
        "n": n,
        "mean": statistics.fmean(ordered),
        "median": statistics.median(ordered),
        "p95": p95,
        "min": ordered[0],
        "max": ordered[-1],
    }


def _center_roi(region: CaptureRegion) -> CaptureRegion:
    """視窗正中央的 ROI_SIZE x ROI_SIZE 區域（螢幕座標）。"""
    w = min(ROI_SIZE, region.width)
    h = min(ROI_SIZE, region.height)
    return CaptureRegion(
        region.left + (region.width - w) // 2,
        region.top + (region.height - h) // 2,
        w,
        h,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="延遲量測（B1/B2/B3 決策依據）")
    add_common_args(parser)
    parser.add_argument("--n", type=int, default=30, help="每一項量測次數")
    args = parser.parse_args()

    session = open_session(args)
    if session is None:
        return 1

    region, locator, capturer = session.region, session.locator, session.capturer
    results: dict[str, dict[str, float]] = {}

    print()
    print(f"{'項目':<40}{'平均':>8}{'中位':>8}{'p95':>8}{'最大':>8}   （ms，n={args.n}）")

    def run(name: str, fn: Callable[[], object]) -> None:
        results[name] = stats_ms(time_ms(fn, args.n))
        s = results[name]
        print(f"{name:<40}{s['mean']:8.1f}{s['median']:8.1f}{s['p95']:8.1f}{s['max']:8.1f}")

    # ---- B1：擷取（整個視窗）
    run("B1 現況：grab（每次重建 mss）", capturer.grab)

    try:
        import mss
        import numpy as np

        sct = mss.mss()
        target = region.as_mss()
        run("B1 實驗：grab（重用 mss）", lambda: np.array(sct.grab(target))[:, :, :3])

        # ---- B2：只抓點擊點附近
        roi = _center_roi(region)
        roi_target = roi.as_mss()
        run(f"B2 現況：ROI {roi.width}x{roi.height}（重建 mss）", ScreenCapture(region=roi).grab)
        run(f"B2 實驗：ROI {roi.width}x{roi.height}（重用 mss）",
            lambda: np.array(sct.grab(roi_target))[:, :, :3])
        sct.close()
    except ImportError as exc:
        print(f"（略過 B1/B2 實驗：{exc}）")

    # ---- 驗證輪詢的比對成本（與 ActionVerifier 預設值一致：ROI margin 150、downsample 2）
    frame_a = capturer.grab()
    frame_b = capturer.grab()
    h, w = frame_a.shape[:2]
    cx, cy = w // 2, h // 2
    roi_box = (max(0, cx - 150), max(0, cy - 150), min(w, cx + 150), min(h, cy + 150))
    run("驗證：frame_diff_ratio（ROI 300、跳格 2）",
        lambda: frame_diff_ratio(frame_a, frame_b, roi=roi_box, downsample=2))

    # ---- B3：前景檢查
    run("B3 現況：is_foreground（列舉所有視窗）", locator.is_foreground)

    if sys.platform == "win32":
        import ctypes

        win = locator.find()
        if win is not None:
            user32 = ctypes.windll.user32
            hwnd = win.hwnd
            run("B3 實驗：GetForegroundWindow 比對 hwnd",
                lambda: int(user32.GetForegroundWindow() or 0) == hwnd)

    # ---- 一次驗證輪詢的估算
    grab_mean = results["B1 現況：grab（每次重建 mss）"]["mean"]
    diff_mean = results["驗證：frame_diff_ratio（ROI 300、跳格 2）"]["mean"]
    poll = grab_mean + 2 * diff_mean + 50  # 每次輪詢比對兩次（對基準幀、對前一幀）＋ sleep 50ms
    print()
    print(f"估算一次驗證輪詢 ≈ grab {grab_mean:.0f} + 2×diff {2 * diff_mean:.0f} + sleep 50 = {poll:.0f} ms")
    print("判讀：實驗項的平均如果比現況少 20% 以上，才值得改；差不多就不要動。")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 量測完成，已儲存：{OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())