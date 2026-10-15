"""W3 D4/D5 實機：擷取視窗 -> DOM 牌框 -> baseline 決策 -> 真的點一次 -> ActionReceipt -> JSONL。

事前準備（兩個 PowerShell 視窗，專案根目錄）：
    uvicorn test_interface.app:app --reload
瀏覽器開 http://127.0.0.1:8000（不要最小化、不要被擋住），再執行：
    python -m test_interface.run_auto_discard --delay 3

安全：
- 手牌與規則狀態不一致時不點擊。
- 目標視窗不在前景時不點擊。
- 滑鼠移到螢幕左上角可觸發 PyAutoGUI failsafe 立即中斷。
"""

from __future__ import annotations

import argparse
import time
import urllib.error
from datetime import datetime, timezone

from src.common.logger import AppLogger
from src.control.controller import AgentController
from src.control.pipeline import EventIds, run_discard_turn
from src.control.tile_mapper import TileMapper, boxes_from_dom_layout
from test_interface.agent_runner import SEAT, make_fake_game_state
from test_interface.live_common import (
    add_action_args,
    add_common_args,
    calibration_origin,
    fetch_clicks,
    fetch_layout,
    make_mouse,
    make_verifier_and_retry,
    open_session,
    print_receipt,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="W3 自動丟牌實機測試")
    add_common_args(parser)
    add_action_args(parser)
    args = parser.parse_args()

    session = open_session(args)
    if session is None:
        return 1

    try:
        layout = fetch_layout(args.url)
        clicks_before = len(fetch_clicks(args.url))
    except (urllib.error.URLError, OSError) as exc:
        print(f"❌ 讀不到測試介面：{exc}")
        return 1
    if not layout.get("tiles"):
        print("❌ 網頁還沒回報牌框，請確認瀏覽器已載入首頁（Ctrl+F5）")
        return 1

    origin_px = calibration_origin(session.frame, layout)

    mapper = TileMapper(frame_size=(session.width, session.height))
    mapper.update(boxes_from_dom_layout(layout, seat=SEAT, zone="hand", origin_px=origin_px))

    game_id = "w3_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    state = make_fake_game_state(game_id)

    check = mapper.check_hand(list(state.players[SEAT].hand))
    if not check.ok:
        print(f"❌ 手牌不一致，不點擊：狀態有但畫面沒有 {check.missing}；畫面有但狀態沒有 {check.extra}")
        return 1

    with AppLogger(log_dir=args.log_dir, game_id=game_id) as logger:
        controller = AgentController(
            game_id=game_id, mouse=make_mouse(), capturer=session.capturer, logger=logger
        )
        controller.start()
        verifier, retry = make_verifier_and_retry(args, controller, session)
        try:
            result = run_discard_turn(
                state, SEAT, mapper, session.region, controller,
                game_id=game_id, ids=EventIds(), logger=logger,
                foreground_check=session.locator.is_foreground,
                verifier=verifier,
                retry=retry,
            )
        finally:
            controller.stop()

    if result.receipt is None:
        print(f"❌ 沒有執行動作：{result.error}")
        return 1

    receipt = result.receipt
    print(f"決策：{result.decision.action.id}（{result.decision.reason}）")
    if result.plan is not None:
        print(f"點擊：frame {result.plan.frame_point} -> 螢幕 {result.plan.screen_point}")
    print_receipt(receipt, verifier)

    time.sleep(0.5)
    clicks = fetch_clicks(args.url)
    expected_clicks = (1 if receipt.ui_action_executed else 0) + receipt.retry_count
    page_ack = (
        expected_clicks > 0
        and len(clicks) == clicks_before + expected_clicks
        and all(c.get("tile") == result.decision.action.tile for c in clicks[clicks_before:])
    )
    print(f"網頁收到點擊：{'是' if page_ack else '否'}（網頁回報：{clicks[clicks_before:]}）")
    print(f"JSONL：{args.log_dir}/{game_id}.jsonl")

    if receipt.success and page_ack:
        verified_text = "通過" if receipt.state_verified else "未啟用"
        print(f"✅ 自動丟牌完成（網頁已收到點擊；畫面驗證：{verified_text}）")
        return 0
    print("❌ 未完成，請看上方回執與 error_code")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())