from enum import Enum
from typing import List, Optional, Dict
from pydantic import BaseModel, Field, ConfigDict

# ==============================================================================
# 1. 核心資料結構與 Enum 定義 (保持原架構不變)
# ==============================================================================

class ActionType(str, Enum):
    DISCARD = "discard"  # 棄牌：打出一張牌
    CHI = "chi"          # chi：吃牌
    PONG = "pong"        # pong：碰牌
    KONG = "kong"        # kong：槓牌
    WIN = "win"          # win：胡牌
    PASS = "pass"        # pass：放棄目前可執行的反應動作


class Action(BaseModel):
    action_type: ActionType = Field(..., description="動作類型")
    tile_id: Optional[int] = Field(None, description="要打出或反應的牌張 ID (0~41)")
    sequence: Optional[List[int]] = Field(None, description="吃牌時組成的順子 ID 列表，例如 [0, 1, 2]")
    kong_type: Optional[str] = Field(None, description="槓牌種類: 'ming'(明槓), 'an'(暗槓), 'jia'(加槓)")

    model_config = ConfigDict(use_enum_values=True)


class RuleMechanics(BaseModel):
    strict_pass_rule: bool = Field(True, description="嚴格過水規則")
    multi_winner: bool = Field(False, description="是否允許一砲多響")
    winner_priority: str = Field("seat_order", description="多人爭胡時依座號優先")
    reserved_wall_tiles: int = Field(16, description="海底保留牌數（台麻留16張）")
    auto_flower_replacement: bool = Field(True, description="摸到花牌自動補花")


DEFAULT_SCORING_TAI = {
    "base_tai": 1, "dealer_tai": 1, "self_draw": 1, "in_hand": 1, "flower": 1,
    "triplet_dragon": 1, "peng_peng_hu": 4, "hun_yi_se": 4, "qing_yi_se": 8,
    "da_san_yuan": 8, "da_si_xi": 16
}


class RulesetConfig(BaseModel):
    ruleset_version: str = "1.0.0"
    rule_name: str = "Taiwan_16_Cards_Standard"
    hand_size: int = 16
    rule_mechanics: RuleMechanics = Field(default_factory=RuleMechanics)
    scoring_tai: Dict[str, int] = Field(default_factory=lambda: DEFAULT_SCORING_TAI.copy())


# ==============================================================================
# 2. 合法動作計算核心類別
# ==============================================================================

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
        """輪到該玩家的回合（摸牌後打牌/自摸）"""
        legal_actions: List[Action] = []

        # 1. 自摸胡牌
        if can_win_self_draw and last_drawn_tile is not None:
            legal_actions.append(Action(action_type=ActionType.WIN, tile_id=last_drawn_tile))

        # 2. 打牌 (排除花牌 34~41)
        for tile in sorted(list(set(hand))):
            if tile < 34:
                legal_actions.append(Action(action_type=ActionType.DISCARD, tile_id=tile))

        return legal_actions

    def get_response_actions(
        self, 
        hand: List[int], 
        target_tile: int, 
        is_previous_player: bool,
        can_win_honin: bool = False
    ) -> List[Action]:
        """其他玩家打牌時的反應動作（吃/碰/槓/胡/過）"""
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
        if is_previous_player and target_tile <= 26:
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

        # 5. 放棄 (PASS)
        if len(legal_actions) > 0:
            legal_actions.append(Action(action_type=ActionType.PASS))

        return legal_actions