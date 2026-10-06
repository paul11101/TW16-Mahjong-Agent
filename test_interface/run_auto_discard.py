"""W3 D4 實機：擷取視窗 -> DOM 牌框 -> baseline 決策 -> 真的點一次 -> ActionReceipt -> JSONL。

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
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import numpy as np

from src.common.events import EventSource, EventType, create_event, event_from_model
from src.common.logger import AppLogger
from src.common.schemas import Decision as SchemaDecision
from src.common.schemas import LegalActions as SchemaLegalActions
from src.control.controller import AgentController
from src.control.discard_executor import execute_discard
from src.control.mouse import MouseController
from src.control.tile_mapper import (
    TileMapper,
    boxes_from_dom_layout,
    default_viewport_offset,
    find_calibration_marker,
)
from src.control.window import DEFAULT_TITLE, WindowLocator
from src.rules.legal_actions import LegalActionGenerator
from src.strategy.adapters import actions_to_legal_actions, game_state_to_observation
from src.strategy.baseline import BaselinePolicy
from test_interface.agent_runner import SEAT, _EventIds, _to_schema_action, make_fake_game_state
from test_interface.check_mapping import fetch_layout


def fetch_clicks(base_url: str) -> list[dict]:
    with urllib.request.urlopen(base_url.rstrip("/") + "/api/clicks", timeout=3) as r:
        return json.loads(r.read().decode("utf-8")).get("clicks", [])


def main() -> int:
    parser = argparse.ArgumentParser(description="W3 D4 自動丟牌實機測試")
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--no-focus", action="store_true")
    parser.add_argument("--log-dir", default="logs")
    args = parser.parse_args()

    locator = WindowLocator(args.title)
    if locator.find() is None:
        print(f"❌ 找不到視窗（標題含「{args.title}」），請先用瀏覽器開 {args.url}")
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
        clicks_before = len(fetch_clicks(args.url))
    except (urllib.error.URLError, OSError) as exc:
        print(f"❌ 讀不到測試介面：{exc}")
        return 1
    if not layout.get("tiles"):
        print("❌ 網頁還沒回報牌框，請確認瀏覽器已載入首頁（Ctrl+F5）")
        return 1

    marker = find_calibration_marker(frame)
    origin_px = (marker[0], marker[1]) if marker else None
    print("可視區原點：" + (f"校正標記 {origin_px}" if marker else f"估計值 {default_viewport_offset(layout)}"))

    boxes = boxes_from_dom_layout(layout, seat=SEAT, zone="hand", origin_px=origin_px)
    mapper = TileMapper(frame_size=(width, height))
    mapper.update(boxes)

    state = make_fake_game_state("w3d4")
    hand = list(state.players[SEAT].hand)
    check = mapper.check_hand(hand)
    if not check.ok:
        print(f"❌ 手牌不一致，不點擊：狀態有但畫面沒有 {check.missing}；畫面有但狀態沒有 {check.extra}")
        return 1

    game_id = "w3d4_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    ids = _EventIds()

    with AppLogger(log_dir=args.log_dir, game_id=game_id) as logger:
        controller = AgentController(game_id=game_id, mouse=MouseController(), logger=logger)
        controller.start()
        try:
            # 決策
            observation = game_state_to_observation(state, seat=SEAT)
            legal = actions_to_legal_actions(LegalActionGenerator().get_turn_player_actions(hand=hand))
            schema_actions = [_to_schema_action(a) for a in legal]

            legal_event_id = ids.next()
            legal_event = event_from_model(
                event_id=legal_event_id, game_id=game_id,
                event_type=EventType.LEGAL_ACTIONS_GENERATED, source=EventSource.RULES,
                model=SchemaLegalActions(
                    game_id=game_id, event_id=legal_event_id,
                    state_event_id="n/a", actions=schema_actions,
                ),
            )
            logger.log_event(legal_event, console_message=f"{len(legal)} legal actions.")

            decision = BaselinePolicy().decide(observation, legal)
            selected_schema = _to_schema_action(decision.action)
            decision_id = f"decision_{ids.next()}"
            decision_event_id = ids.next()
            logger.log_event(
                event_from_model(
                    event_id=decision_event_id, game_id=game_id,
                    event_type=EventType.DECISION_MADE, source=EventSource.STRATEGY,
                    model=SchemaDecision(
                        decision_id=decision_id, game_id=game_id, event_id=decision_event_id,
                        legal_actions_event_id=legal_event_id, selected_action=selected_schema,
                        confidence=min(max(decision.score, 0.0), 1.0), reason=decision.reason,
                        strategy_version="baseline_v0", approved_for_execution=True,
                    ),
                    parent_event_id=legal_event_id,
                ),
                console_message=f"Decision: {decision.action.id}",
            )

            # 點擊 + 回執
            receipt, plan = execute_discard(
                decision, mapper, region, controller,
                game_id=game_id, decision_id=decision_id, schema_action=selected_schema,
                next_event_id=ids.next, logger=logger, parent_event_id=decision_event_id,
                foreground_check=locator.is_foreground,
            )
        finally:
            controller.stop()

    print(f"決策：{decision.action.id}（{decision.reason}）")
    if plan is not None:
        print(f"點擊：frame {plan.frame_point} -> 螢幕 {plan.screen_point}")
    print(f"回執：success={receipt.success} ui_action_executed={receipt.ui_action_executed} "
          f"state_verified={receipt.state_verified} latency={receipt.latency_ms:.1f}ms "
          f"error={receipt.error_code}")

    time.sleep(0.5)
    clicks = fetch_clicks(args.url)
    page_ack = len(clicks) == clicks_before + 1 and clicks[-1].get("tile") == decision.action.tile
    print(f"網頁收到點擊：{'是' if page_ack else '否'}（網頁回報：{clicks[clicks_before:]}）")
    print(f"JSONL：{args.log_dir}/{game_id}.jsonl")

    if receipt.success and page_ack:
        print("✅ W3 D4 自動丟牌完成（網頁已收到點擊；畫面驗證留待 W4 D3）")
        return 0
    print("❌ W3 D4 未完成，請看上方回執與 error_code")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())