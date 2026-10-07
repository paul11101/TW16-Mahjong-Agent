"""W4 D1/D2 實機：擷取視窗 -> DOM 按鈕框 -> 反應決策 -> 真的點（1~2 次）-> ActionReceipt -> JSONL。

事前準備（兩個 PowerShell 視窗，專案根目錄）：
    uvicorn test_interface.app:app --reload
瀏覽器開 http://127.0.0.1:8000/?scenario=reaction（要有 ?scenario=reaction；按 Ctrl+F5，
不要最小化、不要被擋住），再執行：
    python -m test_interface.run_auto_react --delay 3

預設選 chi_1_2_3（會點「吃」再點組合，共 2 次）；可用 --action pong_2 / pass 等切換。
安全：手牌不一致不點、視窗不在前景不點、滑鼠移到螢幕左上角可觸發 failsafe。
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import numpy as np

from src.common.logger import AppLogger
from src.control.button_mapper import ButtonMapper, boxes_from_dom_buttons, boxes_from_dom_choices
from src.control.controller import AgentController
from src.control.mouse import MouseController
from src.control.pipeline import EventIds, run_reaction_turn
from src.control.tile_mapper import TileMapper, boxes_from_dom_layout, find_calibration_marker
from src.control.window import DEFAULT_TITLE, WindowLocator
from test_interface.agent_runner import SEAT
from test_interface.check_mapping import fetch_layout
from test_interface.scripted_policy import ScriptedPolicy
from test_interface.table_view import make_reaction_table_state


def fetch_reactions(base_url: str) -> list[dict]:
    with urllib.request.urlopen(base_url.rstrip("/") + "/api/reactions", timeout=3) as r:
        return json.loads(r.read().decode("utf-8")).get("reactions", [])


def expected_reactions(plan) -> list[dict]:
    """依點擊計畫，算出網頁應該收到的紀錄。"""
    out = []
    for step in plan.steps:
        if step.kind == "button":
            out.append({"kind": "button", "action": step.target, "id": None})
        else:
            out.append({"kind": "choice", "action": None, "id": step.target})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="W4 自動反應實機測試")
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--no-focus", action="store_true")
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--action", default="chi_1_2_3", help="要選的合法動作 id")
    parser.add_argument("--step-delay", type=float, default=0.3, help="兩步驟點擊之間等待秒數")
    args = parser.parse_args()

    locator = WindowLocator(args.title)
    if locator.find() is None:
        print(f"❌ 找不到視窗（標題含「{args.title}」），請先用瀏覽器開 {args.url}/?scenario=reaction")
        return 1

    for remaining in range(int(args.delay), 0, -1):
        print(f"{remaining} 秒後開始...")
        time.sleep(1)

    if not args.no_focus:
        print(f"自動切到目標視窗：{'成功' if locator.bring_to_front() else '失敗'}")
        time.sleep(1.0)

    capturer = locator.make_capturer()
    region = capturer.region
    frame = np.ascontiguousarray(capturer.grab())
    height, width = frame.shape[:2]

    try:
        layout = fetch_layout(args.url)
        reactions_before = len(fetch_reactions(args.url))
    except (urllib.error.URLError, OSError) as exc:
        print(f"❌ 讀不到測試介面：{exc}")
        return 1
    if not layout.get("buttons"):
        print("❌ 網頁還沒回報按鈕框：請確認開的是 /?scenario=reaction，並按 Ctrl+F5")
        return 1

    marker = find_calibration_marker(frame)
    origin_px = (marker[0], marker[1]) if marker else None
    print("可視區原點：" + (f"校正標記 {origin_px}" if marker else "估計值（找不到校正標記）"))

    game_id = "w4_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    state = make_reaction_table_state(game_id)

    # 確認網頁顯示的就是反應情境（手牌一致）
    tile_mapper = TileMapper(frame_size=(width, height))
    tile_mapper.update(boxes_from_dom_layout(layout, seat=SEAT, zone="hand", origin_px=origin_px))
    check = tile_mapper.check_hand(list(state.players[SEAT].hand))
    if not check.ok:
        print(f"❌ 手牌不一致，不點擊：狀態有但畫面沒有 {check.missing}；畫面有但狀態沒有 {check.extra}")
        print("   請確認瀏覽器網址有 ?scenario=reaction 並按 Ctrl+F5")
        return 1

    mapper = ButtonMapper(frame_size=(width, height))
    mapper.update(
        boxes_from_dom_buttons(layout, origin_px=origin_px),
        boxes_from_dom_choices(layout, origin_px=origin_px),
    )
    print(f"可點按鈕：{list(mapper.enabled_actions())}，組合：{[c.choice_id for c in mapper.choices]}")

    result = None
    with AppLogger(log_dir=args.log_dir, game_id=game_id) as logger:
        controller = AgentController(game_id=game_id, mouse=MouseController(), logger=logger)
        controller.start()
        try:
            result = run_reaction_turn(
                state, SEAT, mapper, region, controller,
                game_id=game_id, ids=EventIds(), logger=logger,
                policy=ScriptedPolicy(args.action),
                foreground_check=locator.is_foreground,
                step_delay=args.step_delay,
            )
        except ValueError as exc:
            print(f"❌ {exc}")
            return 1
        finally:
            controller.stop()

    if result.skipped:
        print("只有 PASS 可選，已略過（沒有點擊）")
        return 0
    if result.receipt is None:
        print(f"❌ 沒有執行動作：{result.error}")
        return 1

    receipt = result.receipt
    print(f"決策：{result.decision.action.id}（{result.decision.reason}）")
    if result.plan is not None:
        for step in result.plan.steps:
            print(f"點擊[{step.kind} {step.target}]：frame {step.frame_point} -> 螢幕 {step.screen_point}")
    print(f"回執：success={receipt.success} ui_action_executed={receipt.ui_action_executed} "
          f"state_verified={receipt.state_verified} latency={receipt.latency_ms:.1f}ms "
          f"error={receipt.error_code}")

    time.sleep(0.5)
    got = fetch_reactions(args.url)[reactions_before:]
    page_ack = result.plan is not None and got == expected_reactions(result.plan)
    print(f"網頁收到點擊：{'是' if page_ack else '否'}（網頁回報：{got}）")
    print(f"JSONL：{args.log_dir}/{game_id}.jsonl")

    if receipt.success and page_ack:
        print("✅ 自動反應完成（網頁已收到點擊；畫面驗證留待 W4 D3）")
        return 0
    print("❌ 未完成，請看上方回執與 error_code")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())