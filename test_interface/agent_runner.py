"""W2 最小串接：假 GameState → 策略 → 點擊 → ActionReceipt → JSONL。

A7 整理後，這裡不再自己重做「記錄狀態、產生合法動作、決策、回執」，
全部交給 src.control.pipeline.run_discard_turn，本檔只負責：

    1. 準備假牌局與「假牌框」（牌 -> 固定座標）
    2. 預設用 FakeMouse（不會真的動滑鼠）
    3. 把 TurnResult 整理成測試介面 /api/run 回傳的 dict

流程：
    rules.GameState（假資料）
        -> pipeline.run_discard_turn
           （Observation -> LegalActionGenerator -> BaselinePolicy -> execute_discard）
        -> common.schemas.ActionReceipt
        -> logs/<game_id>.jsonl

注意：
- 假牌框的中心就是 FAKE_HAND_START_X / FAKE_HAND_STEP_X / FAKE_HAND_Y 算出的點，
  視窗偏移為 (0, 0)，所以螢幕座標等於假座標。真正的座標映射見 src/control/tile_mapper.py。
- 沒有重新擷取畫面驗證，所以 receipt.state_verified 固定為 False。
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from src.common.logger import AppLogger
from src.common.schemas import ActionType
from src.control.capture import CaptureRegion
from src.control.controller import AgentController
from src.control.errors import ERR_NO_LEGAL_ACTIONS
from src.control.pipeline import EventIds, TurnResult, run_discard_turn
from src.control.tile_mapper import TileBox, TileMapper
from src.rules.game_state import GameState, PlayerState
from src.strategy.adapters import game_state_to_observation
from test_interface.fakes import FakeMouse  # noqa: F401  (保留舊的 import 路徑)

# 假座標映射：手牌由小到大排序後，依序橫向排列
FAKE_HAND_START_X = 300
FAKE_HAND_STEP_X = 180
FAKE_HAND_Y = 1660

# 假牌框的視窗範圍；偏移為 (0, 0)，所以 frame 座標 = 螢幕座標
FAKE_REGION = CaptureRegion(0, 0, 3840, 2160)

SEAT = 0


def make_fake_game_state(game_id: str) -> GameState:
    """固定的假牌局：輪到玩家 0，剛摸牌後手牌 17 張。"""
    hand = [0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 27, 31, 31, 33]

    return GameState(
        game_id=game_id,
        current_turn=SEAT,
        wall_count=80,
        players={
            0: PlayerState(seat_id=0, hand=hand),
            1: PlayerState(seat_id=1),
            2: PlayerState(seat_id=2),
            3: PlayerState(seat_id=3),
        },
    )


def make_fake_tile_mapper(hand: list[int]) -> TileMapper:
    """假牌框：牌框中心剛好落在 (START_X + 排序位置 * STEP_X, Y)。"""
    boxes = [
        TileBox(tile, FAKE_HAND_START_X + i * FAKE_HAND_STEP_X - 1, FAKE_HAND_Y - 1, 2, 2)
        for i, tile in enumerate(sorted(hand))
    ]
    mapper = TileMapper()
    mapper.update(boxes)
    return mapper


def _failure(message: str, **extra: Any) -> dict[str, Any]:
    return {
        "success": False,
        "observation": extra.get("observation"),
        "decision": extra.get("decision"),
        "execution": extra.get("execution"),
        "receipt": extra.get("receipt"),
        "message": message,
    }


def run_agent(
    *,
    log_dir: str = "logs",
    game_id: str | None = None,
    mouse: Any | None = None,
) -> dict[str, Any]:
    """執行一次：假牌局 -> 決策 -> 模擬點擊 -> 回執 -> JSONL。"""
    if game_id is None:
        game_id = "fake_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    mouse = mouse if mouse is not None else FakeMouse()

    state = make_fake_game_state(game_id)
    observation_dict = asdict(game_state_to_observation(state, seat=SEAT))
    mapper = make_fake_tile_mapper(list(state.players[SEAT].hand))

    with AppLogger(log_dir=log_dir, game_id=game_id) as logger:
        controller = AgentController(game_id=game_id, mouse=mouse, logger=logger)
        controller.start()

        try:
            result = run_discard_turn(
                state, SEAT, mapper, FAKE_REGION, controller,
                game_id=game_id, ids=EventIds(), logger=logger,
            )
        finally:
            controller.stop()

    return _to_response(result, observation_dict)


def _to_response(result: TurnResult, observation_dict: dict[str, Any]) -> dict[str, Any]:
    if result.decision is None or result.receipt is None:
        message = (
            "沒有可執行的合法動作"
            if result.error == ERR_NO_LEGAL_ACTIONS
            else f"沒有執行動作：{result.error}"
        )
        return _failure(message, observation=observation_dict)

    selected = result.decision.action
    receipt = result.receipt
    clicked = receipt.success
    click_point = result.plan.screen_point if result.plan is not None else None

    decision_dict = {
        "success": True,
        "action": {
            "type": ActionType(selected.action).value,
            "tile": selected.tile,
            "id": selected.id,
        },
        "score": result.decision.score,
        "reason": result.decision.reason,
        "message": "策略已選擇動作",
    }

    execution_dict = {
        "success": clicked,
        "message": (
            f"測試模式：模擬點擊牌 {selected.tile}，座標 {click_point}"
            if clicked
            else (receipt.error_message or "點擊失敗")
        ),
        "clicked_tile": selected.tile if clicked else None,
        "click": {"x": click_point[0], "y": click_point[1]} if click_point else None,
    }

    return {
        "success": clicked,
        "observation": observation_dict,
        "decision": decision_dict,
        "execution": execution_dict,
        "receipt": receipt.model_dump(mode="json"),
        "message": execution_dict["message"],
    }