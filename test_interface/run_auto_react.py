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
import time
import urllib.error
from datetime import datetime, timezone

from src.common.logger import AppLogger
from src.control.button_mapper import ButtonMapper, boxes_from_dom_buttons, boxes_from_dom_choices
from src.control.controller import AgentController
from src.control.mouse import MouseController
from src.control.pipeline import EventIds, run_reaction_turn
from src.control.tile_mapper import TileMapper, boxes_from_dom_layout
from test_interface.agent_runner import SEAT
from test_interface.live_common import (
    add_action_args,
    add_common_args,
    calibration_origin,
    fetch_layout,
    fetch_reactions,
    make_verifier_and_retry,
    open_session,
    print_receipt,
)
from test_interface.scripted_policy import ScriptedPolicy
from test_interface.table_view import make_reaction_table_state


def expected_reactions(plan, retries: int = 0) -> list[dict]:
    """依點擊計畫，算出網頁應該收到的紀錄（只有單一點擊的動作會重試，重試就是重複最後一筆）。"""
    out = []
    for step in plan.steps:
        if step.kind == "button":
            out.append({"kind": "button", "action": step.target, "id": None})
        else:
            out.append({"kind": "choice", "action": None, "id": step.target})
    return out + out[-1:] * retries


def main() -> int:
    parser = argparse.ArgumentParser(description="W4 自動反應實機測試")
    add_common_args(parser)
    add_action_args(parser)
    parser.add_argument("--action", default="chi_1_2_3", help="要選的合法動作 id")
    parser.add_argument("--step-delay", type=float, default=0.3, help="兩步驟點擊之間等待秒數")
    args = parser.parse_args()

    session = open_session(args, page_hint="/?scenario=reaction")
    if session is None:
        return 1

    try:
        layout = fetch_layout(args.url)
        reactions_before = len(fetch_reactions(args.url))
    except (urllib.error.URLError, OSError) as exc:
        print(f"❌ 讀不到測試介面：{exc}")
        return 1
    if not layout.get("buttons"):
        print("❌ 網頁還沒回報按鈕框：請確認開的是 /?scenario=reaction，並按 Ctrl+F5")
        return 1

    origin_px = calibration_origin(session.frame, layout)
    frame_size = (session.width, session.height)

    game_id = "w4_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    state = make_reaction_table_state(game_id)

    # 確認網頁顯示的就是反應情境（手牌一致）
    tile_mapper = TileMapper(frame_size=frame_size)
    tile_mapper.update(boxes_from_dom_layout(layout, seat=SEAT, zone="hand", origin_px=origin_px))
    check = tile_mapper.check_hand(list(state.players[SEAT].hand))
    if not check.ok:
        print(f"❌ 手牌不一致，不點擊：狀態有但畫面沒有 {check.missing}；畫面有但狀態沒有 {check.extra}")
        print("   請確認瀏覽器網址有 ?scenario=reaction 並按 Ctrl+F5")
        return 1

    mapper = ButtonMapper(frame_size=frame_size)
    mapper.update(
        boxes_from_dom_buttons(layout, origin_px=origin_px),
        boxes_from_dom_choices(layout, origin_px=origin_px),
    )
    print(f"可點按鈕：{list(mapper.enabled_actions())}，組合：{[c.choice_id for c in mapper.choices]}")

    result = None
    with AppLogger(log_dir=args.log_dir, game_id=game_id) as logger:
        controller = AgentController(
            game_id=game_id, mouse=MouseController(), capturer=session.capturer, logger=logger
        )
        controller.start()
        verifier, retry = make_verifier_and_retry(args, controller)
        try:
            result = run_reaction_turn(
                state, SEAT, mapper, session.region, controller,
                game_id=game_id, ids=EventIds(), logger=logger,
                policy=ScriptedPolicy(args.action),
                foreground_check=session.locator.is_foreground,
                step_delay=args.step_delay,
                verifier=verifier,
                retry=retry,
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
    print_receipt(receipt, verifier)

    time.sleep(0.5)
    got = fetch_reactions(args.url)[reactions_before:]
    page_ack = result.plan is not None and got == expected_reactions(result.plan, receipt.retry_count)
    print(f"網頁收到點擊：{'是' if page_ack else '否'}（網頁回報：{got}）")
    print(f"JSONL：{args.log_dir}/{game_id}.jsonl")

    if receipt.success and page_ack:
        print(f"網頁已收到點擊；畫面驗證：{'通過' if receipt.state_verified else '未啟用或未通過'}")
        return 0
    print("❌ 未完成，請看上方回執與 error_code")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())