from typing import List, Optional

# 從同目錄下的 rule 模組匯入基礎型別與設定
from .rule import Action, RulesetConfig
from src.common.schemas import ActionType


class LegalActionGenerator:
    """根據當前牌局狀況計算合法動作"""

    def __init__(self, config: Optional[RulesetConfig] = None):
        self.config = config or RulesetConfig()

    def get_turn_player_actions(
        self, 
        hand: List[int], 
        last_drawn_tile: Optional[int] = None,
        can_win_self_draw: bool = False
    ) -> List[Action]:
        """輪到該玩家的回合（摸牌後打牌/自模）"""
        legal_actions: List[Action] = []

        # 1. 自摸胡牌
        if can_win_self_draw and last_drawn_tile is not None:
            legal_actions.append(Action(action_type=ActionType.WIN, tile_id=last_drawn_tile))

        # 2. 打牌 (限定數牌與字牌 0~33，排除負數與花牌 34~41)
        for tile in sorted(list(set(hand))):
            if 0 <= tile < 34:
                legal_actions.append(Action(action_type=ActionType.DISCARD, tile_id=tile))

        return legal_actions

    def get_response_actions(
        self, 
        hand: List[int], 
        target_tile: int, 
        is_previous_player: bool,
        can_win_honin: bool = False
    ) -> List[Action]:
        """其他玩家打牌時的反應動作（吃/碰/槓/胡/過水）"""
        legal_actions: List[Action] = []

        # 1. 胡牌 (榮和/砲胡)
        if can_win_honin:
            legal_actions.append(Action(action_type=ActionType.WIN, tile_id=target_tile))

        # 2. 明槓 (手牌已有 3 張相同)
        if hand.count(target_tile) == 3:
            legal_actions.append(
                Action(action_type=ActionType.KONG, tile_id=target_tile, kong_type="ming")
            )

        # 3. 碰牌 (手牌已有 2 張以上相同)
        if hand.count(target_tile) >= 2:
            legal_actions.append(
                Action(action_type=ActionType.PONG, tile_id=target_tile)
            )

        # 4. 吃牌 (必須是上家打出且為數牌 0~26)
        if is_previous_player and 0 <= target_tile <= 26:
            suit_start = (target_tile // 9) * 9
            suit_end = suit_start + 8
            
            # 探索 3 種組順子可能：[target-2, target-1, target], [target-1, target, target+1], [target, target+1, target+2]
            possible_combos = [
                (target_tile - 2, target_tile - 1),
                (target_tile - 1, target_tile + 1),
                (target_tile + 1, target_tile + 2)
            ]
            
            for t1, t2 in possible_combos:
                if suit_start <= t1 <= suit_end and suit_start <= t2 <= suit_end:
                    if t1 in hand and t2 in hand:
                        seq = sorted([t1, t2, target_tile])
                        legal_actions.append(
                            Action(action_type=ActionType.CHI, tile_id=target_tile, sequence=seq)
                        )

        # 5. 放棄/過水 (PASS)
        if len(legal_actions) > 0:
            legal_actions.append(Action(action_type=ActionType.PASS))

        return legal_actions