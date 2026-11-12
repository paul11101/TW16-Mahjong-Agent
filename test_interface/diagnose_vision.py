"""視覺診斷（只讀圖，不動滑鼠）：用 run_real_game 存下的畫面，找出 detector 漏掉的手牌原因。

用法（專案根目錄）：
    python -m test_interface.diagnose_vision
    python -m test_interface.diagnose_vision --threshold 0.4 --names 1 13 4

輸出：
1. detector 目前手牌 ROI 的左右邊界（真實 frame 像素），以及整排手牌「不裁左右」、低門檻的候選。
2. 指定牌（--names）的最高分候選：看分數是低於 0.6 門檻，還是根本沒有模板。
"""

from __future__ import annotations

import argparse

import cv2

from src.control.vision_adapter import normalize_frame
from src.perception.detector import MahjongDetector
from src.perception.utils import calculate_dynamic_scale, match_templates_in_crop


def main() -> int:
    parser = argparse.ArgumentParser(description="視覺診斷")
    parser.add_argument("--image", default="data/processed/real_game_frame.png")
    parser.add_argument("--templates", default="data/samples")
    parser.add_argument("--threshold", type=float, default=0.4)
    parser.add_argument("--names", nargs="*", default=["1", "13", "4"], help="要檢查最高分的牌 id")
    args = parser.parse_args()

    image = cv2.imread(args.image)
    if image is None:
        print(f"❌ 讀不到 {args.image}，請先跑一次 run_real_game")
        return 1

    det = MahjongDetector(template_dir=args.templates, threshold=0.6)
    norm, back = normalize_frame(image, det.base_height)
    h, w = norm.shape[:2]
    scale = calculate_dynamic_scale(h, det.base_scale, det.base_height)
    det._update_template_cache(scale)

    real_w = image.shape[1]
    print(f"原圖 {image.shape[1]}x{image.shape[0]}，正規化後 {w}x{h}，回推係數 {back:.4f}")
    print(f"detector 手牌 ROI 真實像素：x {round(real_w * 0.03)} ~ {round(real_w * 0.97)}（左右各裁 3%）")

    keys = [k for k in det.templates if k.isdigit() and int(k) < 34]
    missing_templates = [n for n in args.names if n not in det.templates]
    if missing_templates:
        print(f"⚠️ 沒有這些牌的模板：{missing_templates}")

    roi = {"top": int(h * 0.68), "left": 0, "width": w, "height": int(h * 0.32)}
    found = match_templates_in_crop(
        norm, roi, det.small_templates_gray, det.templates, keys,
        args.threshold, scale, overlap_thresh=0.35,
    )
    print(f"\n不裁左右、門檻 {args.threshold}：共 {len(found)} 個候選（由左到右）")
    for c in found:
        x = round(c["bbox"][0] * back)
        flag = " <-- 低信心" if c.get("low_confidence") else ""
        print(f"  x={x:5d}  牌 {c['name']:>3}  conf={c['confidence']:.3f}  margin={c.get('margin')}{flag}")

    for name in args.names:
        if name not in det.templates:
            continue
        only = match_templates_in_crop(
            norm, roi, det.small_templates_gray, det.templates, [name],
            0.2, scale, overlap_thresh=0.35,
        )
        only.sort(key=lambda c: c["confidence"], reverse=True)
        print(f"\n牌 {name} 的最高分（門檻 0.2）：")
        for c in only[:5]:
            print(f"  x={round(c['bbox'][0] * back):5d}  conf={c['confidence']:.3f}")
        if not only:
            print("  （完全沒有候選）")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())