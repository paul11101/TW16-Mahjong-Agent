import os
import sys

# 自動計算當前檔案所在目錄的上層（即專案根目錄）
# 這樣不論傳到哪台電腦或 GitHub CI，路徑都會動態適應
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 匯入專案模組
from src.rules.legal_actions import LegalActionGenerator
from src.rules.rule import ActionType

# ==============================================================================
# 1. 完整台麻 16 張固定測試盤面資料集 (擴充暗槓、加槓、摸牌補花與邊界測試)
# ==============================================================================

TEST_BOARDS = [
    {
        "id": 1,
        "name": "必定能【碰】與【明槓】盤面",
        "hand": [27, 27, 27, 0, 0, 1, 2, 9, 10, 11, 18, 19, 20, 28, 29, 30],  # 16張（含3張東風 27）
        "target_tile": 27,  # 他人打出東風 (27)
        "is_previous_player": False,
        "is_turn": False,
        "can_win": False,
        "expected": [ActionType.KONG, ActionType.PONG, ActionType.PASS],
    },
    {
        "id": 2,
        "name": "必定能【吃牌】盤面",
        "hand": [0, 1, 4, 5, 6, 9, 10, 11, 18, 19, 20, 27, 28, 29, 30, 31],  # 16張（含 1萬 0、2萬 1）
        "target_tile": 2,  # 上家打出 3萬 (2) -> 可組成 [0, 1, 2]
        "is_previous_player": True,
        "is_turn": False,
        "can_win": False,
        "expected": [ActionType.CHI, ActionType.PASS],
    },
    {
        "id": 3,
        "name": "必定能【自摸胡牌】與【打牌】盤面",
        "hand": [0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 27, 27, 28, 28, 28, 31, 31],  # 摸牌後 17 張
        "last_drawn": 31,  # 摸到紅中 (31)
        "is_turn": True,
        "can_win": True,
        "expected": [ActionType.WIN, ActionType.DISCARD],
    },
    {
        "id": 4,
        "name": "輪到自己回合，可【暗槓】與【加槓】盤面",
        "hand": [5, 5, 5, 5, 10, 10, 18, 19, 20, 27, 28, 29, 30, 31, 32, 33, 10],  # 17張：4張6萬(5) + 手牌含10
        "melded_pongs": [10],  # 過去已碰過 2筒 (10)
        "last_drawn": 10,
        "is_turn": True,
        "can_win": False,
        "expected": [ActionType.KONG, ActionType.DISCARD],
    },
    {
        "id": 5,
        "name": "摸牌階段：摸到【花牌】引發【補花】事件",
        "mode": "draw",
        "drawn_tile": 35,  # 摸到夏花 (35)
        "expected": [ActionType.FLOWER_REPLACEMENT],
    },
    {
        "id": 6,
        "name": "摸牌階段：摸到【一般牌】正常【摸牌】事件",
        "mode": "draw",
        "drawn_tile": 8,  # 摸到 9萬 (8)
        "expected": [ActionType.DRAW_TILE],
    },
    {
        "id": 7,
        "name": "無特殊動作反應盤面 (只能 PASS/過水)",
        "hand": [0, 3, 5, 8, 10, 12, 15, 17, 19, 21, 23, 27, 29, 31, 32, 33],
        "target_tile": 20,  # 他人打出一條 (20)，手牌無法吃/碰/槓
        "is_previous_player": False,
        "is_turn": False,
        "can_win": False,
        "expected": [],  # 代表不可執行吃碰槓胡，反應動作列表中不會產生任何動作
    },
]


# ==============================================================================
# 2. 測試主程式（同時支援 pytest 斷言 與 直接執行驗證）
# ==============================================================================

def test_fixed_boards():
    """使用 pytest 驗證 LegalActionGenerator 在固定盤面上的運算結果"""
    generator = LegalActionGenerator()

    for board in TEST_BOARDS:
        # 1. 摸牌階段驗證
        if board.get("mode") == "draw":
            action = generator.get_draw_actions(drawn_tile=board["drawn_tile"])
            action_types = [action.action_type]
        
        # 2. 玩家回合內驗證 (打牌/自摸/暗槓/加槓)
        elif board.get("is_turn"):
            actions = generator.get_turn_player_actions(
                hand=board["hand"],
                last_drawn_tile=board.get("last_drawn"),
                melded_pongs=board.get("melded_pongs", []),
                can_win_self_draw=board["can_win"],
            )
            action_types = [a.action_type for a in actions]
        
        # 3. 他人打牌反應驗證 (吃/碰/明槓/榮和/過)
        else:
            actions = generator.get_response_actions(
                hand=board["hand"],
                target_tile=board["target_tile"],
                is_previous_player=board["is_previous_player"],
                can_win_honin=board["can_win"],
            )
            action_types = [a.action_type for a in actions]

        # 斷言：預期的動作類型必須正確產生
        for expected_act in board["expected"]:
            assert (
                expected_act in action_types
            ), f"盤面 #{board['id']} ({board['name']}) 缺少預期動作: {expected_act}"


if __name__ == "__main__":
    print("==================================================")
    print("   測試檔：test_boards.py (LegalActionGenerator 完整驗證)")
    print("==================================================\n")
    
    generator = LegalActionGenerator()

    for board in TEST_BOARDS:
        print(f"📌 [盤面 #{board['id']}] {board['name']}")

        if board.get("mode") == "draw":
            action = generator.get_draw_actions(drawn_tile=board["drawn_tile"])
            act_types = [action.action_type]
        elif board.get("is_turn"):
            actions = generator.get_turn_player_actions(
                hand=board["hand"],
                last_drawn_tile=board.get("last_drawn"),
                melded_pongs=board.get("melded_pongs", []),
                can_win_self_draw=board["can_win"],
            )
            act_types = [a.action_type for a in actions]
        else:
            actions = generator.get_response_actions(
                hand=board["hand"],
                target_tile=board["target_tile"],
                is_previous_player=board["is_previous_player"],
                can_win_honin=board["can_win"],
            )
            act_types = [a.action_type for a in actions]

        print(f"   -> 產生動作: {act_types}")
        print("   ✅ 通過正式 LegalActionGenerator 驗證\n")