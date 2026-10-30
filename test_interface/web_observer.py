"""測試網頁的「觀察器」（W6）：把網頁回報的牌桌資訊轉成 GameRunner 需要的 Snapshot。

只讀「玩家看得到的資訊」（/api/table?scenario=game 已經把其他玩家手牌藏起來）。
階段是從可見資訊推出來的，不是讀模擬器內部狀態：
    牌局結束旗標 -> over；有可點的反應按鈕 -> reaction；
    輪到自己且手牌張數 = 暗牌數 + 1 -> my_turn；其他 -> waiting。
這樣日後換成真實遊戲時，只要換一個「用視覺結果推階段」的觀察器，GameRunner 不用改。
"""

from __future__ import annotations

import time
from typing import Any, Callable

from src.common.schemas import ActionType
from src.control.game_profile import state_from_visible_hand
from src.control.game_runner import (
    PHASE_MY_TURN,
    PHASE_OVER,
    PHASE_REACTION,
    PHASE_WAITING,
    Snapshot,
)
from src.control.tile_mapper import TileBox, boxes_from_dom_layout, marker_origin
from src.rules.game_state import GameState, LastDiscard, Meld
from test_interface.live_common import fetch_json, fetch_layout

GAME_VIEW_PATH = "/api/table?scenario=game"


def classify_view(view: dict[str, Any], seat: int = 0) -> str:
    """牌桌 view -> 階段。"""
    if view.get("game_over"):
        return PHASE_OVER

    me = next(p for p in view["players"] if p["seat_id"] == seat)
    hand = me.get("hand") or []

    # 先看是不是輪到自己打牌（自己回合有胡／槓按鈕時，不能被當成反應）
    if view["current_turn"] == seat and len(hand) == 16 - 3 * len(me["melds"]) + 1:
        return PHASE_MY_TURN
    if any(view.get("buttons", {}).values()):
        return PHASE_REACTION
    return PHASE_WAITING


def view_fingerprint(view: dict[str, Any], phase: str, seat: int = 0) -> tuple:
    """能代表這個畫面的指紋：階段、手牌、剩餘牌數、最後打出的牌、全場河牌與副露數。"""
    me = next(p for p in view["players"] if p["seat_id"] == seat)
    last = view.get("last_discard")
    return (
        phase,
        tuple(t["id"] for t in me.get("hand") or []),
        view["wall_count"],
        (last["player_id"], last["tile"]["id"]) if last else None,
        sum(len(p["discards"]) for p in view["players"]),
        sum(len(p["melds"]) for p in view["players"]),
    )


def state_from_view(game_id: str, view: dict[str, Any], seat: int = 0) -> GameState:
    """牌桌 view -> rules.GameState（只填看得到的：自己手牌、四家河牌／副露／花牌、最後打出的牌）。"""
    me = next(p for p in view["players"] if p["seat_id"] == seat)
    hand = [t["id"] for t in me["hand"] or []]

    state = state_from_visible_hand(
        game_id, hand, seat=seat, dealer=view["dealer"], wall_count=view["wall_count"]
    )
    state.current_turn = view["current_turn"]

    for p in view["players"]:
        player = state.players[p["seat_id"]]
        player.discards = [t["id"] for t in p["discards"]]
        player.flowers = [t["id"] for t in p["flowers"]]
        # 畫面看不出吃碰槓來自誰，from_player 先填自己（策略不會用到）
        player.melds = [
            Meld(
                meld_type=ActionType(m["type"]),
                tiles=[t["id"] for t in m["tiles"]],
                from_player=p["seat_id"],
            )
            for m in p["melds"]
        ]

    last = view.get("last_discard")
    if last:
        state.last_discard = LastDiscard(player_id=last["player_id"], tile_id=last["tile"]["id"])
    return state


class WebObserver:
    def __init__(self, base_url: str, *, seat: int = 0) -> None:
        self.base_url = base_url
        self.seat = seat

    def fetch_view(self) -> dict[str, Any]:
        return fetch_json(self.base_url, GAME_VIEW_PATH)

    def snapshot(self) -> Snapshot | None:
        """讀不到網頁時回傳 None（GameRunner 會計為觀察失敗）。"""
        try:
            view = self.fetch_view()
            phase = classify_view(view, self.seat)
            fingerprint = view_fingerprint(view, phase, self.seat)
        except (OSError, KeyError, StopIteration, ValueError):
            return None

        return Snapshot(
            phase=phase,
            fingerprint=fingerprint,
            detail={"wall_count": view["wall_count"], "current_turn": view["current_turn"]},
            data=view,
        )


def fetch_fresh_layout(
    base_url: str,
    version: Any,
    *,
    timeout: float = 3.0,
    interval: float = 0.05,
    fetch: Callable[[str], dict] = fetch_layout,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict | None:
    """等網頁回報「和這次觀察同一版」的牌框；逾時回傳 None。

    為什麼需要：網頁收到新牌局後要重畫、再回報牌框，中間有幾百毫秒。
    如果這時拿舊牌框去點（例如對手打牌後河牌變多、手牌位置往下移），就會點到空白處。
    version 是 None（舊版網頁／非整局模式）時不檢查。
    """
    deadline = clock() + timeout
    while True:
        layout = fetch(base_url)
        if version is None or layout.get("version") == version:
            return layout
        if clock() >= deadline:
            return None
        sleep(interval)


def make_boxes_fn(
    base_url: str,
    seat: int = 0,
    version_fn: Callable[[], Any] | None = None,
    *,
    fetch: Callable[[str], dict] = fetch_layout,
    timeout: float = 3.0,
) -> Callable[[Any], list[TileBox]]:
    """refresh_hand 用的牌框來源：網頁 DOM + 校正標記。

    version_fn：回傳「這次觀察的版本」；牌框不是同一版就回傳空清單（refresh_hand 會當成不一致、重拍）。
    """

    def boxes_fn(frame) -> list[TileBox]:
        layout = fetch_fresh_layout(
            base_url, version_fn() if version_fn else None, fetch=fetch, timeout=timeout
        )
        if layout is None:
            return []
        return boxes_from_dom_layout(layout, seat=seat, zone="hand", origin_px=marker_origin(frame))

    return boxes_fn