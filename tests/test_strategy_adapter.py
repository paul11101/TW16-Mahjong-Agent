from src.common.schemas import ActionType
from src.rules.rule import Action
from src.rules.game_state import GameState, PlayerState
from src.strategy.adapters import action_to_legal_action, game_state_to_observation

# 測試 PONG 動作是否能正確轉換成 Strategy 使用的 LegalAction
def test_pong_action_adapter():
    # 建立一個碰牌動作，27 代表東風
    action = Action(action_type = ActionType.PONG, tile_id = 27,)

    # 將 Rules 的 Action 轉換成 Strategy 的 LegalAction
    result = action_to_legal_action(action)

    # 確認轉換後的唯一動作 ID
    assert result.id == "pong_27"
    # 確認動作類型仍然是 PONG
    assert result.action == ActionType.PONG
    # 確認目標牌 ID 為 27
    assert result.tile == 27
    # 確認碰牌由三張相同的牌組成
    assert result.tiles == (27, 27, 27)

# 測試 DISCARD 動作是否能正確轉換成 Strategy 使用的 LegalAction
def test_discard_action_adapter():
    # 建立一個打出牌 ID 3 的動作
    action = Action(action_type=ActionType.DISCARD, tile_id=3,)

    # 將 Rules 的 Action 轉換成 Strategy 的 LegalAction
    result = action_to_legal_action(action)

    # 確認轉換後的唯一動作 ID
    assert result.id == "discard_3"
    # 確認動作類型仍然是 DISCARD
    assert result.action == ActionType.DISCARD
    # 確認要打出的牌 ID 為 3
    assert result.tile == 3

# 測試 Rules 的 GameState 是否能正確轉換成 Strategy 的 Observation
def test_game_state_to_observation():
    # 建立四位玩家的固定測試牌局
    state = GameState(
        game_id = "test",
        current_turn = 1,
        wall_count = 80,
        players = {
            0: PlayerState(seat_id = 0, hand = [0, 1, 2]),
            1: PlayerState(seat_id = 1),
            2: PlayerState(seat_id = 2),
            3: PlayerState(seat_id = 3),
        },
    )

    # 將玩家 0 的牌局資訊轉換成 Strategy Observation
    result = game_state_to_observation(state, seat = 0)

    # 確認自己的手牌正確轉換成 tuple
    assert result.hand == (0, 1, 2)
    # 確認目前輪到玩家 1
    assert result.current_player == 1
    # 確認 Agent 自己的座位為 0
    assert result.seat == 0
    # 確認剩餘牌數正確
    assert result.remaining_tiles == 80