from typing import List, Optional
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict

# ==============================================================================
# 1. 引用你原始提供的資料結構 (完全不變)
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
    "base_tai": 1,
    "dealer_tai": 1,
    "self_draw": 1,
    "in_hand": 1,
    "flower": 1,
    "triplet_dragon": 1,
    "peng_peng_hu": 4,
    "hun_yi_se": 4,
    "qing_yi_se": 8,
    "da_san_yuan": 8,
    "da_si_xi": 16
}


class RulesetConfig(BaseModel):
    ruleset_version: str = "1.0.0"
    rule_name: str = "Taiwan_16_Cards_Standard"
    hand_size: int = 16
    rule_mechanics: RuleMechanics = Field(default_factory=RuleMechanics)
    scoring_tai: dict = Field(default_factory=lambda: DEFAULT_SCORING_TAI.copy())


# ==============================================================================
# 2. LegalActions 核心邏輯產生器
# ==============================================================================

class LegalActionGenerator:
    """根據牌局當前狀態，計算玩家可選擇的合法動作"""

    def __init__(self, config: Optional[RulesetConfig] = None):
        self.config = config or RulesetConfig()

    def get_turn_player_actions(
        self, 
        hand: List[int], 
        last_drawn_tile: Optional[int] = None,
        can_win_self_draw: bool = False
    ) -> List[Action]:
        """
        [情況 A] 輪到該玩家的回合（剛剛摸牌完畢，準備打牌、暗槓/加槓、自摸）
        """
        legal_actions: List[Action] = []

        # 1. 檢查是否可以自摸胡牌
        if can_win_self_draw and last_drawn_tile is not None:
            legal_actions.append(Action(action_type=ActionType.WIN, tile_id=last_drawn_tile))

        # 2. 檢查是否可以暗槓 / 加槓
        # TODO: 未來在此處實作暗槓（手牌有4張相同）與加槓（手牌有1張與碰過的牌相同）的檢查邏輯
        # 範例邏輯 placeholder:
        # for tile in set(hand):
        #     if hand.count(tile) == 4:
        #         legal_actions.append(Action(action_type=ActionType.KONG, tile_id=tile, kong_type="an"))

        # 3. 基本動作：打牌 (DISCARD)
        # 玩家可以從手牌（或剛摸到的牌）中選擇任意一張非花牌打出
        for tile in set(hand):
            if tile < 34:  # 0~33 為可打出的數牌與字牌 (34~41為花牌，預設自動補花)
                legal_actions.append(Action(action_type=ActionType.DISCARD, tile_id=tile))

        return legal_actions

    def get_response_actions(
        self, 
        hand: List[int], 
        target_tile: int, 
        is_previous_player: bool,
        can_win_honin: bool = False
    ) -> List[Action]:
        """
        [情況 B] 其他玩家打出牌時，該玩家可以執行的反應動作（吃、碰、明槓、胡、過）
        
        :param hand: 該玩家當前的手牌 ID 列表
        :param target_tile: 別人打出的牌張 ID (0~41)
        :param is_previous_player: 打出牌的人是否為自己的上家（只有上家打的才可以吃牌）
        :param can_win_honin: 是否符合胡牌條件（可榮和）
        """
        legal_actions: List[Action] = []

        # 1. 檢查是否可以【胡牌】(榮和/砲胡)
        if can_win_honin:
            legal_actions.append(Action(action_type=ActionType.WIN, tile_id=target_tile))

        # 2. 檢查是否可以【明槓】(手牌已有 3 張相同)
        if hand.count(target_tile) == 3:
            legal_actions.append(
                Action(action_type=ActionType.KONG, tile_id=target_tile, kong_type="ming")
            )

        # 3. 檢查是否可以【碰牌】(手牌已有 2 張以上相同)
        if hand.count(target_tile) >= 2:
            legal_actions.append(
                Action(action_type=ActionType.PONG, tile_id=target_tile)
            )

        # 4. 檢查是否可以【吃牌】(只有上家打出的牌且為數牌 0~26 時可吃)
        if is_previous_player and target_tile <= 26:
            # TODO: 未來在此處實作完整的順子組合檢查
            # 例如: 手牌有 0, 1 且目標牌為 2，則形成順子 [0, 1, 2]
            pass

        # 5. 如果有任何吃/碰/槓/胡的選項，就必定可以選擇【Pass/過】
        if len(legal_actions) > 0:
            legal_actions.append(Action(action_type=ActionType.PASS))

        return legal_actions
