"""試切模板（只讀圖，不改 data/samples）：從實機畫面「依 detector 的座標系」裁出候選模板並驗證分數。

為什麼需要：detector 把畫面正規化到 1980 高再比對，模板必須是同一個大小（約 1980 高畫面裡的牌）。
如果直接從 2880x1575 的截圖裁，模板會比別的模板小約 20%，分數就會掉到 0.5x。
這個工具會：以參考牌（--like，預設 14）的模板大小與 y 位置為準，在你指定的 x（真實畫面像素）裁出候選，
存到 data/processed/，並用 detector 同樣的方式算它在整排手牌上的分數。

用法（專案根目錄）：
    python -m test_interface.try_template --name 13 --x 1660 1665 1670 1675
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from src.control.vision_adapter import normalize_frame
from src.perception.detector import MahjongDetector
from src.perception.utils import calculate_dynamic_scale, match_templates_in_crop


def main() -> int:
    parser = argparse.ArgumentParser(description="試切模板")
    parser.add_argument("--image", default="data/processed/real_game_frame.png")
    parser.add_argument("--templates", default="data/samples")
    parser.add_argument("--name", default="13", help="要做的牌 id")
    parser.add_argument("--like", default="14", help="大小與 y 的參考牌（畫面上有抓到、信心高的牌）")
    parser.add_argument("--x", type=float, nargs="+", required=True, help="這張牌左緣的真實畫面 x（可給多個試）")
    parser.add_argument("--out-dir", default="data/processed")
    args = parser.parse_args()

    image = cv2.imread(args.image)
    if image is None:
        print(f"❌ 讀不到 {args.image}")
        return 1

    det = MahjongDetector(template_dir=args.templates, threshold=0.6)
    norm, back = normalize_frame(image, det.base_height)
    h, w = norm.shape[:2]
    scale = calculate_dynamic_scale(h, det.base_scale, det.base_height)
    det._update_template_cache(scale)

    print("模板大小（高x寬）：")
    for n in (args.name, args.like):
        t = det.templates.get(n)
        print(f"  {n}.png：{'沒有這個模板' if t is None else f'{t.shape[0]}x{t.shape[1]}'}")

    like = det.templates.get(args.like)
    if like is None:
        print(f"❌ 沒有參考模板 {args.like}")
        return 1
    th, tw = like.shape[:2]

    roi = {"top": int(h * 0.68), "left": 0, "width": w, "height": int(h * 0.32)}
    ref = match_templates_in_crop(
        norm, roi, det.small_templates_gray, det.templates, [args.like], 0.7, scale
    )
    if not ref:
        print(f"❌ 畫面上找不到參考牌 {args.like}，請改用 --like 指定別張有抓到的牌")
        return 1
    y = ref[0]["bbox"][1]
    print(f"參考牌 {args.like}：正規化座標 y={y}，模板大小 {th}x{tw}")

    crop_img = norm[roi["top"]:roi["top"] + roi["height"], :]
    small_crop = cv2.cvtColor(
        cv2.resize(crop_img, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for real_x in args.x:
        x = round(real_x / back)
        patch = norm[y:y + th, x:x + tw]
        if patch.shape[:2] != (th, tw):
            print(f"\nx={real_x:.0f}：裁切超出畫面，略過")
            continue

        path = out_dir / f"{args.name}_x{round(real_x)}.png"
        cv2.imwrite(str(path), patch)

        small_t = cv2.cvtColor(
            cv2.resize(patch, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY
        )
        res = cv2.matchTemplate(small_crop, small_t, cv2.TM_CCOEFF_NORMED)
        points = np.argwhere(res >= 0.5)
        points = sorted(points.tolist(), key=lambda p: res[p[0], p[1]], reverse=True)[:3000]

        kept: list[int] = []
        rows: list[tuple[int, float]] = []
        gap = 0.5 * tw * scale
        for py, px in points:
            if all(abs(px - k) > gap for k in kept):
                kept.append(px)
                rows.append((round(px / scale * back), float(res[py, px])))

        rows.sort(key=lambda r: -r[1])
        print(f"\n候選 {path}：最高分的位置（真實 x、分數）")
        for rx, conf in rows[:4]:
            print(f"  x={rx:5d}  conf={conf:.3f}")

    print("\n判讀：若有兩個位置分數 > 0.9（約在兩張五筒的位置），把該候選複製成 data/samples/"
          f"{args.name}.png 即可。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())