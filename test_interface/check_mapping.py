"""W3 D3 實機檢查：擷取測試介面視窗 -> DOM 牌框轉 frame 座標 -> baseline 決策 -> 算點擊座標。

只計算座標並畫 debug 圖，不會點擊（點擊是 W3 D4）。

事前準備（兩個 PowerShell 視窗，專案根目錄）：
    uvicorn test_interface.app:app --reload
然後用瀏覽器開 http://127.0.0.1:8000（不要最小化、不要被擋住），再執行：
    python -m test_interface.check_mapping --delay 3

輸出：data/processed/w3d3_mapping_debug.png
  綠框 = 每張手牌牌框（frame 座標），紅點 = baseline 要點的位置。
  紅點沒有落在牌上 -> 可視區偏移估計不準，用 --offset-x / --offset-y（CSS px）微調。
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import cv2
import numpy as np

from src.control.tile_mapper import (
    CALIB_CSS_SIZE,
    TileMapper,
    TileMappingError,
    boxes_from_dom_layout,
    boxes_from_observation,
    compare_with_reference,
    default_viewport_offset,
    find_calibration_marker,
    plan_discard_click,
)
from src.control.window import DEFAULT_TITLE, WindowLocator
from src.rules.legal_actions import LegalActionGenerator
from src.strategy.adapters import actions_to_legal_actions, game_state_to_observation
from src.strategy.baseline import BaselinePolicy
from test_interface.agent_runner import SEAT, make_fake_game_state

DEBUG_PATH = Path("data/processed/w3d3_mapping_debug.png")


def fetch_layout(base_url: str) -> dict:
    url = base_url.rstrip("/") + "/api/layout"
    with urllib.request.urlopen(url, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="W3 D3 牌框座標映射實機檢查")
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--no-focus", action="store_true")
    parser.add_argument("--offset-x", type=float, default=None, help="可視區左偏移（CSS px）")
    parser.add_argument("--offset-y", type=float, default=None, help="可視區上偏移（CSS px）")
    parser.add_argument("--vision", action="store_true",
                        help="另外跑視覺模板比對並與 DOM 對照（測試介面的牌是文字，預期比對不到）")
    args = parser.parse_args()

    locator = WindowLocator(args.title)
    if locator.find() is None:
        print(f"❌ 找不到視窗（標題含「{args.title}」），請先用瀏覽器開 {args.url}")
        return 1

    for remaining in range(int(args.delay), 0, -1):
        print(f"{remaining} 秒後擷取...")
        time.sleep(1)

    if not args.no_focus:
        print(f"自動切到目標視窗：{'成功' if locator.bring_to_front() else '失敗'}")
        time.sleep(1.0)

    capturer = locator.make_capturer()
    region = capturer.region
    frame = np.ascontiguousarray(capturer.grab())
    height, width = frame.shape[:2]
    print(f"視窗區域：left={region.left} top={region.top} width={region.width} height={region.height}")
    print(f"擷取畫面：{width}x{height}")
    if (width, height) != (region.width, region.height):
        print("⚠️ 擷取大小與視窗區域不同，請檢查 DPI 設定")

    # 1. DOM 牌框（先擷取、再讀 DOM，兩者時間很接近）
    try:
        layout = fetch_layout(args.url)
    except (urllib.error.URLError, OSError) as exc:
        print(f"❌ 讀不到 {args.url}/api/layout：{exc}")
        return 1

    if not layout.get("tiles"):
        print("❌ 網頁還沒回報牌框：請確認瀏覽器已開啟首頁並載入完成")
        return 1

    if args.offset_x is not None or args.offset_y is not None:
        auto_x, auto_y = default_viewport_offset(layout)
        offset = (
            args.offset_x if args.offset_x is not None else auto_x,
            args.offset_y if args.offset_y is not None else auto_y,
        )
    else:
        offset = None

    # 可視區原點來源：手動偏移 > 校正標記（最準）> 估計值
    marker = find_calibration_marker(frame)
    origin_px = None
    if offset is not None:
        method = f"手動偏移 {offset}（CSS px）"
    elif marker is not None:
        origin_px = (marker[0], marker[1])
        dpr = float(layout.get("dpr", 1.0))
        method = f"校正標記，frame 座標 {origin_px}，大小 {marker[2]}x{marker[3]}px（預期約 {CALIB_CSS_SIZE * dpr:.0f}px）"
    else:
        method = "估計值（找不到校正標記：請確認 table_page.py 已加 #calib，並在瀏覽器按 Ctrl+F5）"

    boxes = boxes_from_dom_layout(
        layout, seat=SEAT, zone="hand", offset=offset, origin_px=origin_px
    )
    print(f"DOM：dpr={layout.get('dpr')}，可視區原點來源：{method}")
    print(f"手牌牌框 {len(boxes)} 張")

    if not boxes:
        from collections import Counter

        counts = Counter((t.get("seat"), t.get("zone")) for t in layout.get("tiles", []))
        print(f"❌ 沒有 seat={SEAT}、zone=hand 的牌框。網頁回報的 (seat, zone) 數量：")
        for (seat_id, zone_name), n in sorted(counts.items(), key=str):
            print(f"   seat={seat_id!r} zone={zone_name!r}：{n} 張")
        print("   若 zone 全是 '' 請確認 table_page.py 的 data-zone 修改並按 Ctrl+F5")
        return 1

    mapper = TileMapper(frame_size=(width, height))
    mapper.update(boxes)

    # 2. 畫面手牌 vs 規則狀態手牌
    state = make_fake_game_state("w3d3")
    hand = list(state.players[SEAT].hand)
    check = mapper.check_hand(hand)
    if check.ok:
        print(f"✅ 畫面手牌與規則狀態一致（{len(hand)} 張）")
    else:
        print(f"❌ 手牌不一致：狀態有但畫面沒有 {check.missing}；畫面有但狀態沒有 {check.extra}")

    # 3. baseline 決策 -> 點擊座標
    observation = game_state_to_observation(state, seat=SEAT)
    legal = actions_to_legal_actions(LegalActionGenerator().get_turn_player_actions(hand=hand))
    decision = BaselinePolicy().decide(observation, legal)

    plan = None
    try:
        plan = plan_discard_click(decision, mapper, region)
        print(f"baseline 選擇：{decision.action.id}（{decision.reason}）")
        print(f"  frame 座標：{plan.frame_point}")
        print(f"  螢幕座標：{plan.screen_point}（W3 D4 才會真的點）")
    except TileMappingError as exc:
        print(f"❌ 映射失敗：{exc}")

    # 4. 選用：視覺比對 vs DOM 對照
    if args.vision:
        from src.perception.capture import run_perception_matching

        observation_dict = run_perception_matching(frame=frame)
        detected = boxes_from_observation(observation_dict, min_confidence=0.6)
        report = compare_with_reference(detected, boxes)
        print(f"視覺 vs DOM：偵測 {len(detected)} 張，"
              f"{'一致' if report.ok else f'{len(report.problems)} 項不一致'}，最大誤差 {report.max_error:.1f}px")
        for problem in report.problems[:10]:
            print("  -", problem)

    # 5. debug 圖
    debug = frame.copy()
    for box in mapper.boxes:
        cv2.rectangle(debug, (box.x, box.y), (box.x + box.w, box.y + box.h), (0, 255, 0), 2)
        cv2.putText(debug, str(box.tile), (box.x, max(box.y - 4, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    if plan is not None:
        cv2.circle(debug, plan.frame_point, 8, (0, 0, 255), -1)

    DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(DEBUG_PATH), debug)
    print(f"已儲存 debug 圖：{DEBUG_PATH}（請確認綠框與紅點是否落在手牌上）")

    if check.ok and plan is not None:
        print("✅ W3 D3 牌框映射檢查完成")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())