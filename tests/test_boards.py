from src.rules.legal_actions import (
    ActionType,
    LegalActionGenerator
)

# 4 組固定測試盤面
TEST_BOARDS = [
    {
        "id": 1,
        "name": "必定能【碰】或【明槓】盤面",
        "hand": [27, 27, 27, 0, 0, 1, 2, 9, 10, 11, 18, 19, 20, 28, 29, 30],
        "target_tile": 27,
        "is_previous_player": False,
        "is_turn": False,
        "can_win": False,
        "expected": [ActionType.KONG, ActionType.PONG, ActionType.PASS]
    },
    {
        "id": 2,
        "name": "必定能【吃牌】盤面",
        "hand": [0, 1, 4, 5, 6, 9, 10, 11, 18, 19, 20, 27, 28, 29, 30, 31],
        "target_tile": 2,  # 上家打 3萬(2)，與手牌 1萬(0)、2萬(1) 組成 [0, 1, 2]
        "is_previous_player": True,
        "is_turn": False,
        "can_win": False,
        "expected": [ActionType.CHI, ActionType.PASS]
    },
    {
        "id": 3,
        "name": "必定能【自摸胡牌】盤面",
        "hand": [0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 27, 27, 28, 28, 28, 31],
        "last_drawn": 31,
        "is_turn": True,
        "can_win": True,
        "expected": [ActionType.WIN, ActionType.DISCARD]
    },
    {
        "id": 4,
        "name": "無特殊動作盤面 (只能打牌/過)",
        "hand": [0, 3, 5, 8, 10, 12, 15, 17, 19, 21, 23, 27, 29, 31, 32, 33],
        "target_tile": 20,
        "is_previous_player": False,
        "is_turn": False,
        "can_win": False,
        "expected": []
    }
]


def test_fixed_boards():
    """使用 pytest 驗證正式的 src/rules/legal_actions 模組於固定盤面的判定結果"""
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
        
        # 驗證預期動作是否有出現在正式模組算出的結果中
        for expected_act in board["expected"]:
            assert expected_act in action_types, f"盤面 {board['id']} 缺少預期動作: {expected_act}"