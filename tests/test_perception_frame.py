"""perception/capture.py：frame 參數與模板依解析度縮放測試（用合成雜訊圖，不需要真實截圖）。

執行方式（專案根目錄）：
    python -m tests.test_perception_frame
或
    python -m pytest tests/test_perception_frame.py -v

注意：run_perception_matching 會在目前目錄寫 data/processed/*_debug.png（data/ 已被 .gitignore）。
"""

import tempfile
from pathlib import Path

import cv2
import numpy as np

from src.control.capture import ScreenCapture
from src.perception.capture import BASE_WIDTH, run_perception_matching

FRAME_W, FRAME_H = 2880, 1618  # 整合端測試機解析度
CARD_W, CARD_H = 100, 140  # 基準解析度下的模板大小


def _make_case(tmp_dir: Path):
    """做一張 2880x1618 的雜訊畫面，把「縮放後的模板」貼在手牌區。"""
    rng = np.random.default_rng(0)

    template = rng.integers(0, 256, (CARD_H, CARD_W, 3), dtype=np.uint8)
    templates_dir = tmp_dir / "samples"
    templates_dir.mkdir()
    cv2.imwrite(str(templates_dir / "5.png"), template)

    scale = FRAME_W / BASE_WIDTH
    scaled = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    sh, sw = scaled.shape[:2]

    frame = rng.integers(0, 256, (FRAME_H, FRAME_W, 3), dtype=np.uint8)
    x, y = 500, 1250  # 落在手牌 ROI（高度 73%~95%）內
    frame[y:y + sh, x:x + sw] = scaled

    return frame, templates_dir, (x, y, sw, sh)


def test_frame_is_used_and_templates_are_scaled():
    with tempfile.TemporaryDirectory() as d:
        frame, templates_dir, (x, y, sw, sh) = _make_case(Path(d))

        obs = run_perception_matching(frame=frame, templates_dir=str(templates_dir))

        assert obs["window_size"] == [FRAME_W, FRAME_H]
        assert len(obs["detected_cards"]) == 1

        card = obs["detected_cards"][0]
        assert card["card"] == "5"
        assert card["bbox"] == [x, y, sw, sh]  # bbox 為傳入畫面的座標
        assert card["confidence"] > 0.9


def test_without_scaling_the_card_is_missed():
    with tempfile.TemporaryDirectory() as d:
        frame, templates_dir, _ = _make_case(Path(d))

        obs = run_perception_matching(
            frame=frame, templates_dir=str(templates_dir), scale_templates=False
        )
        assert obs["detected_cards"] == []


def test_frame_from_screen_capture_bgra():
    """ScreenCapture.grab() 去掉 alpha 後的非連續陣列也能直接傳入。"""
    with tempfile.TemporaryDirectory() as d:
        frame, templates_dir, _ = _make_case(Path(d))

        bgra = np.dstack([frame, np.full(frame.shape[:2], 255, dtype=np.uint8)])
        grabbed = ScreenCapture(grab_fn=lambda region: bgra).grab()

        obs = run_perception_matching(frame=grabbed, templates_dir=str(templates_dir))
        assert [c["card"] for c in obs["detected_cards"]] == ["5"]


if __name__ == "__main__":
    test_frame_is_used_and_templates_are_scaled()
    test_without_scaling_the_card_is_missed()
    test_frame_from_screen_capture_bgra()
    print("✅ test_perception_frame：3 項測試全部通過")