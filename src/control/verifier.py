"""點擊後畫面驗證（W4 D3）：重新擷取 -> 等畫面變化 -> 等畫面穩定 -> 逾時。

企劃書：每次操作後必須重新觀察；畫面未確認變化就不繼續下一個動作。

做法（不做牌面辨識，只比對畫面像素）：
1. prepare(frame_point)：點擊前先擷取一張基準幀，並以點擊點為中心決定比對區域（ROI）。
2. wait()：點擊後每隔 poll_interval 擷取一次，
   - ROI 內「變化像素比例」>= min_change_ratio -> 視為有變化；
   - 有變化之後，連續 stable_frames 幀與前一幀的差異 <= stable_ratio -> 視為穩定（動畫結束）。
   - 兩個條件都滿足 -> 驗證成功；timeout 前沒滿足 -> 失敗（ACTION_TIMEOUT / ACTION_NOT_STABLE）。

只比對點擊點附近，是為了避免畫面其他地方的動畫或時鐘造成誤判。
門檻是初始值，需要用實機的 change_ratio 校正（runner 會印出）。

兩種擷取模式：
- 整窗模式（預設）：每次都擷取整個視窗，再裁 ROI 比對。視窗被縮放時，畫面大小改變 -> FRAME_SIZE_CHANGED。
- ROI 模式（B2，傳入 roi_capture_fn + frame_size）：只擷取 ROI（實測約 8ms，整窗約 75ms）。
  ROI 大小固定，看不出視窗被縮放或移動，所以要另外傳 region_guard：
  prepare 前與驗證成功前各檢查一次視窗位置沒變，變了就回報 FRAME_SIZE_CHANGED。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol

import numpy as np

from src.control.errors import (  # noqa: F401  (舊路徑相容)
    ERR_ACTION_NOT_STABLE,
    ERR_ACTION_TIMEOUT,
    ERR_CAPTURE_FAILED,
    ERR_FRAME_SIZE_CHANGED,
)
from src.control.tile_mapper import Point

Roi = tuple[int, int, int, int]  # (x0, y0, x1, y1)，frame 像素，x1 / y1 不含
CaptureFn = Callable[[], "np.ndarray | None"]
RoiCaptureFn = Callable[[Roi], "np.ndarray | None"]


def frame_diff_ratio(
    a: np.ndarray,
    b: np.ndarray,
    *,
    roi: Roi | None = None,
    pixel_threshold: int = 25,
    downsample: int = 1,
) -> float:
    """兩張畫面在 ROI 內「差異超過 pixel_threshold 的像素」比例（0~1）。

    兩張畫面大小不同時拋 ValueError（視窗被縮放時畫面不可靠）。
    downsample > 1 時用跳格取樣加速（比例仍是比例）。
    """
    if a.shape != b.shape:
        raise ValueError(f"frame shape mismatch: {a.shape} vs {b.shape}")

    if roi is not None:
        x0, y0, x1, y1 = roi
        a = a[y0:y1, x0:x1]
        b = b[y0:y1, x0:x1]

    if downsample > 1:
        a = a[::downsample, ::downsample]
        b = b[::downsample, ::downsample]

    if a.size == 0:
        return 0.0

    diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
    if diff.ndim == 3:
        diff = diff.max(axis=2)

    return float((diff > pixel_threshold).mean())


@dataclass(frozen=True)
class VerifyResult:
    changed: bool  # 最後一次比對時，畫面相對點擊前是否有變化
    stable: bool  # 變化後是否已穩定
    elapsed_ms: float
    polls: int  # 擷取次數
    change_ratio: float  # 最後一次與基準幀的差異比例（校正門檻用）
    error: str | None = None  # ERR_*；None 代表驗證成功

    @property
    def verified(self) -> bool:
        return self.error is None and self.changed and self.stable

    def describe(self) -> str:
        return (
            f"changed={self.changed} stable={self.stable} "
            f"change_ratio={self.change_ratio:.4f} elapsed={self.elapsed_ms:.0f}ms "
            f"polls={self.polls} error={self.error}"
        )


class Verifier(Protocol):
    """執行器使用的驗證介面（測試可以用假的）。"""

    def prepare(self, frame_point: Point) -> bool:
        """點擊前呼叫：擷取基準幀。回傳 False 代表擷取失敗，不應該點擊。"""
        ...

    def wait(self, timeout: float | None = None) -> VerifyResult:
        """點擊後呼叫：等畫面變化並穩定，或逾時。

        timeout 不給就用預設；重試前的「多等一輪」會用較短的 timeout 沿用同一張基準幀。
        """
        ...


class ActionVerifier:
    """用畫面差異確認「點擊有效果」。"""

    def __init__(
        self,
        capture_fn: CaptureFn,
        *,
        timeout: float = 1.0,
        poll_interval: float = 0.05,
        min_change_ratio: float = 0.005,
        stable_ratio: float = 0.001,
        stable_frames: int = 2,
        pixel_threshold: int = 25,
        roi_margin: int | None = 150,
        downsample: int = 2,
        roi_capture_fn: RoiCaptureFn | None = None,
        frame_size: tuple[int, int] | None = None,
        region_guard: Callable[[], bool] | None = None,
        clock: Callable[[], float] = time.perf_counter,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._capture_fn = capture_fn
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.min_change_ratio = min_change_ratio
        self.stable_ratio = stable_ratio
        self.stable_frames = stable_frames
        self.pixel_threshold = pixel_threshold
        self.roi_margin = roi_margin  # None = 比對整張畫面
        self.downsample = downsample
        self._roi_capture_fn = roi_capture_fn
        self.frame_size = frame_size  # (寬, 高)；ROI 模式用來限制 ROI 不超出畫面
        self.region_guard = region_guard  # ROI 模式：回傳 False 代表視窗位置／大小已改變
        self._clock = clock
        self._sleep = sleep

        self._baseline: np.ndarray | None = None
        self._roi: Roi | None = None
        self._capture_box: Roi | None = None  # ROI 模式：每次只擷取這一塊
        self.history: list[VerifyResult] = []  # 每次 wait() 的結果（runner 印出校正用）

    @property
    def roi_mode(self) -> bool:
        return (
            self._roi_capture_fn is not None
            and self.frame_size is not None
            and self.roi_margin is not None
        )

    def prepare(self, frame_point: Point) -> bool:
        if self.roi_mode:
            return self._prepare_roi(frame_point)

        frame = self._capture_fn()
        if frame is None:
            return False

        self._capture_box = None
        self._baseline = np.array(frame, copy=True)
        self._roi = self._roi_for(self._baseline.shape, frame_point)
        return True

    def _prepare_roi(self, frame_point: Point) -> bool:
        if self.region_guard is not None and not self.region_guard():
            return False  # 視窗已被移動／縮放：不點擊（執行器會要求停止）

        width, height = self.frame_size  # type: ignore[misc]
        box = self._roi_for((height, width), frame_point)
        if box is None:
            return False

        frame = self._roi_capture_fn(box)  # type: ignore[misc]
        if frame is None:
            return False

        self._capture_box = box
        self._roi = None  # 擷取到的就是 ROI，整張比對即可
        self._baseline = np.array(frame, copy=True)
        return True

    def _roi_for(self, shape: tuple[int, ...], point: Point) -> Roi | None:
        if self.roi_margin is None:
            return None

        height, width = shape[:2]
        x, y = point
        m = self.roi_margin
        return max(0, x - m), max(0, y - m), min(width, x + m), min(height, y + m)

    def _next_frame(self) -> np.ndarray | None:
        if self._capture_box is not None:
            return self._roi_capture_fn(self._capture_box)  # type: ignore[misc]
        return self._capture_fn()

    def _diff(self, a: np.ndarray, b: np.ndarray) -> float:
        return frame_diff_ratio(
            a, b,
            roi=self._roi,
            pixel_threshold=self.pixel_threshold,
            downsample=self.downsample,
        )

    def wait(self, timeout: float | None = None) -> VerifyResult:
        if self._baseline is None:
            raise RuntimeError("請先呼叫 prepare() 擷取基準幀")

        limit = self.timeout if timeout is None else timeout
        baseline = self._baseline
        start = self._clock()
        prev = baseline
        changed = False
        stable_count = 0
        polls = 0
        ratio = 0.0

        def finish(error: str | None = None, stable: bool = False) -> VerifyResult:
            result = VerifyResult(
                changed=changed,
                stable=stable,
                elapsed_ms=(self._clock() - start) * 1000.0,
                polls=polls,
                change_ratio=ratio,
                error=error,
            )
            self.history.append(result)
            return result

        while self._clock() - start < limit:
            self._sleep(self.poll_interval)
            frame = self._next_frame()
            polls += 1

            if frame is None:
                return finish(ERR_CAPTURE_FAILED)

            try:
                ratio = self._diff(baseline, frame)
                step = self._diff(prev, frame)
            except ValueError:
                return finish(ERR_FRAME_SIZE_CHANGED)

            changed = ratio >= self.min_change_ratio
            if changed:
                stable_count = stable_count + 1 if step <= self.stable_ratio else 0
                if stable_count >= self.stable_frames:
                    # ROI 模式看不出視窗被移動／縮放，確認成功前再檢查一次視窗位置
                    if (
                        self._capture_box is not None
                        and self.region_guard is not None
                        and not self.region_guard()
                    ):
                        return finish(ERR_FRAME_SIZE_CHANGED)
                    return finish(stable=True)
            else:
                stable_count = 0

            prev = frame

        return finish(ERR_ACTION_NOT_STABLE if changed else ERR_ACTION_TIMEOUT)