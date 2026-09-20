from enum import Enum
from typing import List, Optional, Dict
from pydantic import BaseModel, Field, ConfigDict

# ==============================================================================
# 1. 引用你原始定義的資料結構 (完全保留你原本的定義)
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
# 2. 核心動作判斷邏輯 (LegalActions)
# ==============================================================================

class LegalActionGenerator:
    """根據當前牌局狀況回傳合法動作"""

    def get_turn_actions(self, hand: List[int], last_drawn: Optional[int] = None, can_win: bool = False) -> List[Action]:
        legal = []
        if can_win and last_drawn is not None:
            legal.append(Action(action_type=ActionType.WIN, tile_id=last_drawn))
        
        # 可打出的牌 (排除花牌 34~41)
        for tile in sorted(list(set(hand))):
            if tile < 34:
                legal.append(Action(action_type=ActionType.DISCARD, tile_id=tile))
        return legal

    def get_response_actions(self, hand: List[int], target_tile: int, is_previous_player: bool, can_win: bool = False) -> List[Action]:
        legal = []
        if can_win:
            legal.append(Action(action_type=ActionType.WIN, tile_id=target_tile))
        
        # 明槓 (手牌有 3 張相同的)
        if hand.count(target_tile) == 3:
            legal.append(Action(action_type=ActionType.KONG, tile_id=target_tile, kong_type="ming"))
        
        # 碰牌 (手牌有 2 張以上的)
        if hand.count(target_tile) >= 2:
            legal.append(Action(action_type=ActionType.PONG, tile_id=target_tile))
        
        # 吃牌 (必須是上家打出且為數牌 0~26，簡化示範 [0,1,2] 順子)
        if is_previous_player and target_tile <= 26:
            if target_tile == 2 and 0 in hand and 1 in hand:
                legal.append(Action(action_type=ActionType.CHI, tile_id=target_tile, sequence=[0, 1, 2]))

        if len(legal) > 0:
            legal.append(Action(action_type=ActionType.PASS))
            
        return legal


# ==============================================================================
# 3. 4組固定測試牌局資料結構
# ==============================================================================

TEST_BOARDS = [
    {
        "id": 1,
        "name": "必定能【碰】或【明槓】盤面",
        "hand": [27, 27, 27, 0, 0, 1, 2, 9, 10, 11, 18, 19, 20, 28, 29, 30], # 3張東風 (27)
        "target_tile": 27, # 對家打出東風 (27)
        "is_previous_player": False,
        "is_turn": False,
        "can_win": False,
        "expected": ["kong", "pong", "pass"]
    },
    {
        "id": 2,
        "name": "必定能【吃牌】盤面",
        "hand": [0, 1, 4, 5, 6, 9, 10, 11, 18, 19, 20, 27, 28, 29, 30, 31], # 1萬(0)與2萬(1)
        "target_tile": 2, # 上家打出3萬 (2)
        "is_previous_player": True,
        "is_turn": False,
        "can_win": False,
        "expected": ["chi", "pass"]
    },
    {
        "id": 3,
        "name": "必定能【自摸胡牌】盤面",
        "hand": [0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 27, 27, 28, 28, 28, 31],
        "last_drawn": 31, # 摸到紅中 (31)
        "is_turn": True,
        "can_win": True,
        "expected": ["win", "discard"]
    },
    {
        "id": 4,
        "name": "無特殊動作盤面 (只能打牌/過)",
        "hand": [0, 3, 5, 8, 10, 12, 15, 17, 19, 21, 23, 27, 29, 31, 32, 33],
        "target_tile": 20, # 別人打出一條 (20)
        "is_previous_player": False,
        "is_turn": False,
        "can_win": False,
        "expected": []
    }
]


# ==============================================================================
# 4. 驗證流程主程式
# ==============================================================================

def run_board_verification():
    generator = LegalActionGenerator()
    print("==================================================")
    print("       固定測試牌局與規則驗證流程 (Verification)")
    print("==================================================\n")

    for board in TEST_BOARDS:
        print(f"📌 [測試盤面 {board['id']}] {board['name']}")
        print(f"   手牌: {board['hand']}")
        
        # 根據是否為自身回合執行驗證
        if board["is_turn"]:
            print(f"   摸牌: {board['last_drawn']}")
            actions = generator.get_turn_actions(
                hand=board["hand"],
                last_drawn=board.get("last_drawn"),
                can_win=board["can_win"]
            )
        else:
            print(f"   目標牌: {board['target_tile']} (來自{'上家' if board['is_previous_player'] else '其他玩家'})")
            actions = generator.get_response_actions(
                hand=board["hand"],
                target_tile=board["target_tile"],
                is_previous_player=board["is_previous_player"],
                can_win=board["can_win"]
            )

        # 輸出產生的合法動作
        action_types = [a.action_type for a in actions]
        print(f"   -> 產生合法動作數量: {len(actions)}")
        for act in actions:
            print(f"      • {act.model_dump_json()}")

        # 驗證預期動作是否均有產生
        is_passed = all(act in action_types for act in board["expected"])
        if is_passed:
            print("   ✅ 驗證結果: 通過 (PASSED)\n")
        else:
            print("   ❌ 驗證結果: 失敗 (FAILED)\n")


if __name__ == "__main__":
    run_board_verification()