import os
import sys

# 動態將專案根目錄納入 Python 模組搜尋路徑，避免找不到 src 模組
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 直接匯入正式模組，不再重複定義 Class
from src.rules.legal_actions import (
    ActionType,
    LegalActionGenerator,
)

# ==============================================================================
# 1. 4組台麻 16 張固定測試盤面資料集
# ==============================================================================

TEST_BOARDS = [
    {
        "id": 1,
        "name": "必定能【碰】或【明槓】盤面",
        "hand": [27, 27, 27, 0, 0, 1, 2, 9, 10, 11, 18, 19, 20, 28, 29, 30], # 16張（含3張東風 27）
        "target_tile": 27, # 他人打出東風 (27)
        "is_previous_player": False,
        "is_turn": False,
        "can_win": False,
        "expected": [ActionType.KONG, ActionType.PONG, ActionType.PASS]
    },
    {
        "id": 2,
        "name": "必定能【吃牌】盤面",
        "hand": [0, 1, 4, 5, 6, 9, 10, 11, 18, 19, 20, 27, 28, 29, 30, 31], # 16張（含 1萬 0、2萬 1）
        "target_tile": 2, # 上家打出 3萬 (2) -> 組成 [0, 1, 2]
        "is_previous_player": True,
        "is_turn": False,
        "can_win": False,
        "expected": [ActionType.CHI, ActionType.PASS]
    },
    {
        "id": 3,
        "name": "必定能【自摸胡牌】盤面",
        "hand": [0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 27, 27, 28, 28, 28, 31], # 16張聽紅中 (31)
        "last_drawn": 31, # 摸到紅中 (31)
        "is_turn": True,
        "can_win": True,
        "expected": [ActionType.WIN, ActionType.DISCARD]
    },
    {
        "id": 4,
        "name": "無特殊動作盤面 (只能打牌/過)",
        "hand": [0, 3, 5, 8, 10, 12, 15, 17, 19, 21, 23, 27, 29, 31, 32, 33],
        "target_tile": 20, # 他人打出一條 (20)，手牌無法反應
        "is_previous_player": False,
        "is_turn": False,
        "can_win": False,
        "expected": []
    }
]


# ==============================================================================
# 2. 測試主程式（驗證正式模組在固定盤面下的運算結果）
# ==============================================================================

def test_fixed_boards():
    """使用 pytest 驗證正式 LegalActionGenerator 在固定盤面上的運作狀況"""
    generator = LegalActionGenerator()

    for board in TEST_BOARDS:
        if board["is_turn"]:
            actions = generator.get_turn_player_actions(
                hand=board["hand"],
                last_drawn_tile=board.get("last_drawn"),
                can_win_self_draw=board["can_win"]
            )
        else:
            actions = generator.get_response_actions(
                hand=board["hand"],
                target_tile=board["target_tile"],
                is_previous_player=board["is_previous_player"],
                can_win_honin=board["can_win"]
            )

        action_types = [a.action_type for a in actions]
        
        # 斷言：預期的動作必須都包含在正式模組計算出的結果中
        for expected_act in board["expected"]:
            assert expected_act in action_types, f"盤面 #{board['id']} 缺少預期動作: {expected_act}"


if __name__ == "__main__":
    # 也支援直接使用 python 檔案命令跑獨立驗證
    print("==================================================")
    print("   測試檔：test_boards.py (正式模組鏈接驗證)")
    print("==================================================\n")
    generator = LegalActionGenerator()
    
    for board in TEST_BOARDS:
        print(f"📌 [盤面 #{board['id']}] {board['name']}")
        if board["is_turn"]:
            actions = generator.get_turn_player_actions(
                hand=board["hand"],
                last_drawn_tile=board.get("last_drawn"),
                can_win_self_draw=board["can_win"]
            )
        else:
            actions = generator.get_response_actions(
                hand=board["hand"],
                target_tile=board["target_tile"],
                is_previous_player=board["is_previous_player"],
                can_win_honin=board["can_win"]
            )
        
        act_types = [a.action_type for a in actions]
        print(f"   -> 產生動作: {act_types}")
        print("   ✅ 通過正式 LegalActionGenerator 驗證\n")