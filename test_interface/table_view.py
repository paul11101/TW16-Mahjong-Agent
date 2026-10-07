"""測試牌桌顯示的資料層（W3 D1）。

把 rules.GameState 轉成前端可以直接渲染的 JSON（view model）：
四位玩家的手牌／河牌／副露／花牌、剩餘牌數、輪到誰、合法動作按鈕、策略決策與分數。

重點規則：
- 只有「自己的座位」會輸出手牌；其他玩家只輸出手牌張數（不洩漏暗牌）。
- 這裡只做「顯示用資料整理」，不判斷規則、不選動作、不點擊。
- 牌桌上的牌都帶 data-tile / data-seat（見 table_page.py），W3 D3 做座標映射時可直接使用。

資料來源目前是假牌局（make_demo_table_state）。
規則模組的洗牌／發牌完成後，只要換掉 state 來源即可，build_table_view 不用改。
"""

from __future__ import annotations

from typing import Any, Sequence

from src.common.schemas import ActionType
from src.control.pipeline import get_reaction_rules_actions
from src.rules.game_state import GameState, LastDiscard, Meld
from src.rules.legal_actions import LegalActionGenerator
from src.strategy.adapters import actions_to_legal_actions, game_state_to_observation
from src.strategy.baseline import BaselinePolicy
from src.strategy.interfaces import Decision, LegalAction
from test_interface.agent_runner import SEAT, make_fake_game_state

WINDS = ["東", "南", "西", "北"]

# 以「自己」為基準的相對位置：自己在下方，順時針（座位 +1 在右側）
POSITIONS = ["bottom", "right", "top", "left"]

# 反應按鈕的固定顯示順序
REACTION_BUTTONS = ("chi", "pong", "kong", "win", "pass")

ACTION_NAMES = {
    "discard": "打",
    "chi": "吃",
    "pong": "碰",
    "kong": "槓",
    "win": "胡",
    "pass": "過",
}

_HONORS = {
    27: "東", 28: "南", 29: "西", 30: "北",
    31: "中", 32: "發", 33: "白",
}
_FLOWERS = {
    34: "春", 35: "夏", 36: "秋", 37: "冬",
    38: "梅", 39: "蘭", 40: "菊", 41: "竹",
}
_NUMS = "一二三四五六七八九"


def tile_label(tile_id: int) -> str:
    """牌 ID -> 中文名稱（僅供介面顯示）。"""
    if 0 <= tile_id <= 8:
        return _NUMS[tile_id] + "萬"
    if 9 <= tile_id <= 17:
        return _NUMS[tile_id - 9] + "筒"
    if 18 <= tile_id <= 26:
        return _NUMS[tile_id - 18] + "條"
    if tile_id in _HONORS:
        return _HONORS[tile_id]
    if tile_id in _FLOWERS:
        return _FLOWERS[tile_id]
    return f"牌{tile_id}"


def _tile(tile_id: int) -> dict[str, Any]:
    return {"id": tile_id, "name": tile_label(tile_id)}


def _action_label(action: LegalAction) -> str:
    kind = ActionType(action.action).value
    name = ACTION_NAMES.get(kind, kind)

    if kind == "chi" and action.tiles:
        return name + " " + "".join(tile_label(t) for t in action.tiles)
    if action.tile is not None:
        return f"{name} {tile_label(action.tile)}"
    return name


def build_table_view(
    state: GameState,
    seat: int,
    *,
    legal_actions: Sequence[LegalAction] | None = None,
    decision: Decision | None = None,
) -> dict[str, Any]:
    """把牌局狀態整理成牌桌顯示用的 dict（可直接 json.dumps）。"""
    actions = list(legal_actions or [])
    selected_id = decision.action.id if decision is not None else None

    players: list[dict[str, Any]] = []
    for seat_id in sorted(state.players):
        p = state.players[seat_id]
        is_self = seat_id == seat

        players.append(
            {
                "seat_id": seat_id,
                "position": POSITIONS[(seat_id - seat) % 4],
                "wind": WINDS[(seat_id - state.dealer) % 4],
                "is_self": is_self,
                "is_dealer": seat_id == state.dealer,
                "is_current": seat_id == state.current_turn,
                "score": p.score,
                # 只有自己看得到手牌；其他玩家只給張數
                "hand": [_tile(t) for t in sorted(p.hand)] if is_self else None,
                "hand_count": len(p.hand),
                "discards": [_tile(t) for t in p.discards],
                "melds": [
                    {
                        "type": ActionType(m.meld_type).value,
                        "label": ACTION_NAMES.get(
                            ActionType(m.meld_type).value,
                            ActionType(m.meld_type).value,
                        ),
                        "tiles": [_tile(t) for t in m.tiles],
                    }
                    for m in p.melds
                ],
                "flowers": [_tile(t) for t in p.flowers],
            }
        )

    last_discard = None
    if state.last_discard is not None:
        last_discard = {
            "player_id": state.last_discard.player_id,
            "tile": _tile(state.last_discard.tile_id),
        }

    available = {ActionType(a.action).value for a in actions}

    return {
        "game_id": state.game_id,
        "seat": seat,
        "round_wind": WINDS[state.round_wind % 4],
        "dealer": state.dealer,
        "current_turn": state.current_turn,
        "wall_count": state.wall_count,
        "last_discard": last_discard,
        "players": players,
        "buttons": {name: name in available for name in REACTION_BUTTONS},
        "actions": [
            {
                "id": a.id,
                "type": ActionType(a.action).value,
                "label": _action_label(a),
                "selected": a.id == selected_id,
            }
            for a in actions
        ],
        "decision": (
            {
                "action_id": decision.action.id,
                "label": _action_label(decision.action),
                "score": decision.score,
                "reason": decision.reason,
            }
            if decision is not None
            else None
        ),
    }


def make_demo_table_state(game_id: str = "preview") -> GameState:
    """測試牌桌用的假牌局：四位玩家都有河牌，部分有副露與花牌。

    玩家 0 沿用 agent_runner 的假手牌（17 張，剛摸牌），
    其他玩家的手牌只用來算張數，不會顯示在畫面上。
    """
    state = make_fake_game_state(game_id)
    players = state.players

    players[0].discards = [29, 30, 5, 22]

    players[1].hand = [0, 2, 4, 6, 10, 12, 14, 19, 21, 23, 25, 28, 30]  # 13 張 + 1 組碰
    players[1].melds = [Meld(meld_type=ActionType.PONG, tiles=[27, 27, 27], from_player=2)]
    players[1].discards = [13, 14, 28, 1, 33, 22]
    players[1].flowers = [35]

    players[2].hand = [1, 3, 5, 7, 9, 11, 13, 15, 17, 18, 20, 22, 24, 26, 29, 32]  # 16 張
    players[2].discards = [4, 26, 29, 15, 8, 31, 20]

    players[3].hand = [0, 1, 4, 5, 8, 10, 12, 16, 19, 23, 25, 27, 31]  # 13 張 + 1 組吃
    players[3].melds = [Meld(meld_type=ActionType.CHI, tiles=[9, 10, 11], from_player=2)]
    players[3].discards = [30, 6, 17, 24, 32]
    players[3].flowers = [34, 38]

    return state


def preview_table(game_id: str = "preview") -> dict[str, Any]:
    """假牌局 → 合法動作 → baseline 決策 → 牌桌 view（不點擊、不寫 log）。"""
    state = make_demo_table_state(game_id)
    hand = list(state.players[SEAT].hand)

    observation = game_state_to_observation(state, seat=SEAT)
    legal_actions = actions_to_legal_actions(
        LegalActionGenerator().get_turn_player_actions(hand=hand)
    )
    decision = BaselinePolicy().decide(observation, legal_actions)

    return build_table_view(
        state, SEAT, legal_actions=legal_actions, decision=decision
    )

# 反應情境：玩家 3（我的上家）打出二萬，我手上有 0 1 3 4 與一對二萬
# -> 可以碰，也可以吃三種組合（一二三、二三四、一二三 以二萬為中心的三種）
REACTION_HAND = [0, 1, 2, 2, 3, 4, 9, 10, 11, 18, 19, 20, 27, 27, 31, 31]  # 16 張
REACTION_TARGET = 2
REACTION_FROM = 3


def make_reaction_table_state(game_id: str = "preview") -> GameState:
    """反應情境假牌局：上家剛打出一張牌，輪到我決定 吃／碰／過。"""
    state = make_demo_table_state(game_id)
    state.players[SEAT].hand = list(REACTION_HAND)
    state.players[REACTION_FROM].discards.append(REACTION_TARGET)
    state.last_discard = LastDiscard(player_id=REACTION_FROM, tile_id=REACTION_TARGET)
    state.current_turn = SEAT
    return state


def preview_reaction_table(game_id: str = "preview") -> dict[str, Any]:
    """反應情境 -> 反應動作 -> baseline 決策 -> 牌桌 view（不點擊、不寫 log）。"""
    state = make_reaction_table_state(game_id)

    observation = game_state_to_observation(state, seat=SEAT)
    legal_actions = actions_to_legal_actions(get_reaction_rules_actions(state, SEAT))
    decision = BaselinePolicy().decide(observation, legal_actions)

    return build_table_view(
        state, SEAT, legal_actions=legal_actions, decision=decision
    )