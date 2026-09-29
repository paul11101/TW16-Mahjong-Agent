from src.common.schemas import ActionType
from src.rules.game_state import GameState, PlayerState
from src.rules.legal_actions import LegalActionGenerator
from src.strategy.action_mask import (ACTION_SPACE_SIZE, action_to_index, build_action_mask,)
from src.strategy.adapters import (actions_to_legal_actions, game_state_to_observation,)
from src.strategy.baseline import BaselinePolicy
from src.strategy.encoder import encode_observation

# 測試假 GameState 是否能完整串接到 Strategy Decision
def test_fake_game_state_strategy_pipeline():
    # 建立一個固定的假牌局狀態
    state = GameState(
        game_id = "test_game",
        current_turn = 0,
        wall_count = 80,
        players = {
            # 玩家 0 為目前 Agent，並提供固定手牌
            0: PlayerState(
                seat_id = 0,
                hand = [0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 27, 31, 31],
            ),
            # 其他三位玩家先使用空狀態
            1: PlayerState(seat_id = 1),
            2: PlayerState(seat_id = 2),
            3: PlayerState(seat_id = 3),
        },
    )

    # 將 Rules 的 GameState 轉成 Strategy 使用的 Observation
    observation = game_state_to_observation(state, seat = 0,)

    # 將 Observation 編碼成固定長度的模型輸入特徵
    feature = encode_observation(observation)

    # 根據目前手牌產生 Rules 模組判定的合法動作
    rules_actions = LegalActionGenerator().get_turn_player_actions(hand = state.players[0].hand,)

    # 將 Rules Action 轉成 Strategy 使用的 LegalAction
    legal_actions = actions_to_legal_actions(rules_actions)

    # 根據 LegalActions 建立固定長度的 Action Mask
    mask = build_action_mask(legal_actions)

    # 建立目前的 BaselinePolicy
    policy = BaselinePolicy()

    # 使用 Observation 與 LegalActions 產生最終決策
    decision = policy.decide(observation, legal_actions,)

    # 確認 Encoder 輸出的特徵長度固定為 555
    assert len(feature) == 555

    # 確認 Action Mask 長度等於固定 Action Space 大小
    assert len(mask) == ACTION_SPACE_SIZE

    # 確認策略選出的動作一定存在於合法動作清單中
    assert decision.action in legal_actions

    # 此牌局目前沒有胡牌，因此 Baseline 應選擇 DISCARD
    assert decision.action.action == ActionType.DISCARD

    # Baseline 會選第一個合法棄牌，因此預期為 discard_0
    assert decision.action.id == "discard_0"

    # 將策略選出的動作轉成 Action Space 中的索引
    selected_index = action_to_index(decision.action)

    # 確認策略最後選出的動作在 Action Mask 中確實被標記為合法
    assert mask[selected_index] == 1