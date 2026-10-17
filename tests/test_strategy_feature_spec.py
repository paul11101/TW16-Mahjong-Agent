from dataclasses import replace

import pytest

from src.rules.game_state import GameState, PlayerState
from src.strategy.adapters import game_state_to_observation
from src.strategy.encoder import encode_observation
from src.strategy.feature_spec import FEATURE_GROUPS, FEATURE_SIZE, feature_slice

# 建立固定測試牌局，包含四位玩家的手牌與公開河牌
# opponent_hand 與 wall 可以替換，用來驗證隱藏資訊不會洩漏
def make_state(opponent_hand = (3, 3, 4), wall = (1, 2, 3)):
    return GameState(
        game_id = "visible_features",
        current_turn = 2,
        wall_count = 80,
        wall = list(wall),
        players = {
            # 玩家 0 是預設的 Agent，持有兩張 0、一張 1 和一張 27
            0: PlayerState(
                seat_id = 0,
                hand = [0, 0, 1, 27],
                discards = [9],
            ),
            # 玩家 1 的暗牌可替換，但只有河牌可以提供給其他玩家
            1: PlayerState(
                seat_id = 1,
                hand = list(opponent_hand),
                discards = [10],
            ),
            # 玩家 2 的暗牌，用來測試切換 Agent 座位
            2: PlayerState(
                seat_id = 2,
                hand = [5, 6, 7],
                discards = [11],
            ),
            # 玩家 3 的暗牌與公開河牌
            3: PlayerState(
                seat_id = 3,
                hand = [18, 19, 20],
                discards = [12],
            ),
        },
    )


# 測試 FeatureSpec 的總維度是否與現有 Encoder 一致
def test_feature_size_matches_encoder():
    state = make_state()
    observation = game_state_to_observation(state, seat = 0)
    features = encode_observation(observation)

    # FeatureSpec 與 Encoder 都必須維持原本的 555 維
    assert FEATURE_SIZE == 555
    assert len(features) == FEATURE_SIZE


# 測試特徵群組是否連續排列，避免索引重疊或遺漏
def test_feature_groups_are_contiguous():
    expected_start = 0

    for group in FEATURE_GROUPS:
        # 每一組的起始位置必須等於上一組的結束位置
        assert group.start == expected_start

        # 每一組特徵都必須具有正確且非零的維度
        assert group.stop > group.start
        assert group.size == group.stop - group.start

        # 更新下一組應該開始的位置
        expected_start = group.stop

    # 最後一組結束的位置必須等於特徵總維度
    assert expected_start == FEATURE_SIZE



# 測試各特徵群組在 555 維向量中的固定索引
def test_feature_group_offset():
    # 自己手牌佔用第 0~41 維
    assert feature_slice("hand") == slice(0, 42)

    # 四位玩家的河牌佔用第 42~209 維
    assert feature_slice("discards_0") == slice(42, 84)
    assert feature_slice("discards_3") == slice(168, 210)

    # 副露資訊從第 210 維開始
    assert feature_slice("melds_0") == slice(210, 252)

    # 花牌資訊從第 378 維開始
    assert feature_slice("flowers_0") == slice(378, 420)

    # 目前玩家與自己的座位各使用 4 維 One-Hot
    assert feature_slice("current_player") == slice(546, 550)
    assert feature_slice("seat") == slice(550, 554)

    # 最後一維保存正規化後的剩餘牌數
    assert feature_slice("remaining_tiles") == slice(554, 555)


# 測試特徵索引是否能正確取得實際 Observation 的資料
def test_feature_values_match_observation():
    state = make_state()
    observation = game_state_to_observation(state, seat = 0)
    features = encode_observation(observation)

    # 使用 FeatureSpec 定義的索引讀取不同特徵
    hand = features[feature_slice("hand")]
    discards = features[feature_slice("discards_1")]
    current_player = features[feature_slice("current_player")]
    seat = features[feature_slice("seat")]

    # 玩家 0 的手牌中，牌 ID 0 有兩張、牌 ID 1 有一張
    assert hand[0] == 2
    assert hand[1] == 1

    # 玩家 1 曾打出一張牌 ID 10
    assert discards[10] == 1

    # 目前輪到玩家 2，因此 One-Hot 的第三個位置為 1
    assert current_player == (0, 0, 1, 0)

    # Agent 的座位是玩家 0，因此 One-Hot 的第一個位置為 1
    assert seat == (1, 0, 0, 0)


# 測試對手暗牌變化不會影響 Agent 可取得的特徵
def test_opponent_hidden_hand_is_not_exposed():
    # 建立兩個公開資訊相同、但對手暗牌不同的牌局
    first_state = make_state(opponent_hand = (3, 3, 4),)
    second_state = make_state(opponent_hand = (15, 16, 17),)
    first = game_state_to_observation(first_state, seat = 0)
    second = game_state_to_observation(second_state, seat = 0)

    # 即使對手的暗牌不同，Agent 取得的 Observation 也必須相同
    assert first == second

    # 編碼後的模型特徵也不能受到對手暗牌影響
    assert encode_observation(first) == encode_observation(second)


# 測試未公開的牌牆排列不會洩漏到 Strategy
def test_hidden_wall_order_is_not_exposed():
    # 使用不同牌牆內容，但維持相同的公開牌牆剩餘數
    first_state = make_state(wall = (1, 2, 3))
    second_state = make_state(wall = (30, 31, 32))
    first = game_state_to_observation(first_state, seat = 0)
    second = game_state_to_observation(second_state, seat = 0)

    # 牌牆內容不屬於 Observation，因此結果必須相同
    assert first == second

    # Encoder 不能因為知道牌牆排列而產生不同特徵
    assert encode_observation(first) == encode_observation(second)


# 測試切換 Agent 座位後，只取得指定玩家自己的暗牌
def test_observation_uses_selected_players_hand():
    state = make_state()
    observation = game_state_to_observation(state, seat = 2)

    # Agent 位於玩家 2，因此自己的手牌應為 5、6、7
    assert observation.hand == (5, 6, 7)
    assert observation.seat == 2

    features = encode_observation(observation)

    # 確認手牌特徵包含玩家 2 的牌 ID 5
    assert features[feature_slice("hand")][5] == 1

    # 確認座位 One-Hot 正確標記玩家 2
    assert features[feature_slice("seat")] == (0, 0, 1, 0)


# 測試剩餘牌數未知時，Encoder 是否使用預設值
def test_unknown_remaining_tiles():
    state = make_state()
    observation = game_state_to_observation(state, seat = 0)

    # 使用 replace 建立新的 Observation，將剩餘牌數設為未知
    observation = replace(observation, remaining_tiles = None)
    features = encode_observation(observation)

    # 剩餘牌數未知時，應使用 -1.0，而不是猜測實際牌牆內容
    assert features[feature_slice("remaining_tiles")] == (-1.0,)


# 測試未定義的特徵名稱是否會被拒絕
def test_unknown_feature_group_is_rejected():
    # 對手暗牌不屬於可用特徵，不應存在對應索引
    with pytest.raises(ValueError, match = "unknown feature group"):
        feature_slice("opponent_hidden_hand")