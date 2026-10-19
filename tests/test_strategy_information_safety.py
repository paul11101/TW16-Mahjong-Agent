from dataclasses import fields, replace

import pytest

from src.common.schemas import ActionType
from src.rules.game_state import GameState, PlayerState
from src.strategy.adapters import game_state_to_observation
from src.strategy.baseline import BaselinePolicy
from src.strategy.danger_features import extract_danger_features
from src.strategy.encoder import encode_observation
from src.strategy.interfaces import LegalAction, Observation
from src.strategy.public_features import extract_public_features
from src.strategy.shanten import Taiwan16ShantenCalculator

# 建立固定的測試牌局
# 包含自己的手牌、其他玩家的暗牌及公開棄牌資訊
# 用來檢查 Strategy 是否會受到隱藏資訊影響
def make_state():
    return GameState(
        game_id = "w5_information_safety",
        current_turn = 0,
        wall_count = 80,
        players = {
            # 玩家 0 是目前的 Agent，具有完整的自身手牌
            0: PlayerState(
                seat_id = 0,
                hand = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 18, 19, 20, 27, 31],
                discards = [12],
            ),
            # 玩家 1 的暗牌應該對 Agent 保持隱藏
            1: PlayerState(
                seat_id = 1,
                hand = [3, 3, 4],
                discards = [13],
            ),
            # 玩家 2 的暗牌也不應進入 Agent 的 Observation
            2: PlayerState(
                seat_id = 2,
                hand = [21 , 22],
                discards = [14],
            ),
            # 玩家 3 的暗牌同樣屬於隱藏資訊
            3: PlayerState(
                seat_id = 3,
                hand = [29, 30],
                discards = [15],
            ),
        },
    )


# 測試危險度特徵是否正確預留 34 個欄位
# 在尚未建立危險度模型時，所有風險分數都應為未知
def test_danger_features_are_unknown():
    # 將完整 GameState 轉換成 Strategy 可使用的 Observation
    observation = game_state_to_observation(make_state(), seat = 0)

    # 提取危險度預留特徵
    result = extract_danger_features(observation)

    # 台灣麻將共有 34 種基本牌，因此需要 34 個風險欄位
    assert len(result.discard_risk_scores) == 34

    # 尚未實作真正的風險評估，所有分數必須為 None
    assert all(score is None for score in result.discard_risk_scores)

    # 確認目前沒有可使用的危險度模型結果
    assert result.risk_available is False


# 測試危險度提取器是否拒絕直接接收完整 GameState
def test_danger_features_reject_private_game_state():
    state = make_state()

    # 完整 GameState 可能包含對手暗牌及其他隱藏資訊
    # 因此應拋出 TypeError，要求使用 Observation
    with pytest.raises(TypeError, match = "Observation"):
        extract_danger_features(state)



# 測試 Observation 是否只包含允許策略使用的欄位
def test_observation_contains_only_allowed_fields():
    # 使用 dataclasses.fields 取得 Observation 定義的所有欄位名稱
    names = {field.name for field in fields(Observation)}

    # Observation 只能保留自己的手牌、公開資訊及可取得的狀態
    # 不應直接包含其他玩家的暗牌或完整牌牆資料
    assert names == {
        "hand",
        "discards",
        "melds",
        "flowers",
        "current_player",
        "seat",
        "remaining_tiles",
    }


# 測試其他玩家的暗牌改變時，不會影響 Strategy 的特徵
def test_opponent_hidden_hand_does_not_change_features():
    # 建立原始牌局
    first_state = make_state()

    # 深度複製一份牌局，避免修改到原始資料
    second_state = first_state.model_copy(deep = True)

    # 只修改玩家 1 的暗牌，不改變公開資訊
    second_state.players[1].hand = [15, 16, 17]

    # 分別從兩個牌局取得玩家 0 的 Observation
    first = game_state_to_observation(first_state, seat = 0)
    second = game_state_to_observation(second_state, seat = 0)

    # 對手暗牌不同，但 Agent 可看到的資訊應完全相同
    assert first == second

    # 原本的 555 維 Encoder 不應受到對手暗牌影響
    assert encode_observation(first) == encode_observation(second)

    # W5 Day 3 的公開特徵也不應受到對手暗牌影響
    assert extract_public_features(first) == extract_public_features(second)

    # Day 4 的危險度預留特徵同樣不應受到影響
    assert extract_danger_features(first) == extract_danger_features(second)


# 測試牌牆內部排列順序改變時，不會影響 Strategy 特徵
def test_hidden_wall_order_does_not_change_features():
    first_state = make_state()
    second_state = first_state.model_copy(deep = True)

    # 改變第二份牌局的牌牆排列順序
    # 不修改公開的剩餘牌數或其他玩家可見資訊
    second_state.wall = second_state.wall[1:] + second_state.wall[:1]

    # 將兩份牌局轉換成 Observation
    first = game_state_to_observation(first_state, seat = 0)
    second = game_state_to_observation(second_state, seat = 0)

    # Strategy 不應得知未公開的牌牆排列順序
    assert first == second

    # 555 維模型輸入不應受到隱藏牌牆順序影響
    assert encode_observation(first) == encode_observation(second)

    # 公開資訊衍生特徵也應保持相同
    assert extract_public_features(first) == extract_public_features(second)


# 測試對手暗牌與牌牆順序改變時，Baseline 決策是否一致
def test_hidden_information_does_not_change_baseline_decision():
    first_state = make_state()
    second_state = first_state.model_copy(deep = True)

    # 修改玩家 1 的暗牌
    second_state.players[1].hand = [15, 16, 17]

    # 修改牌牆內部排列順序
    second_state.wall = second_state.wall[1:] + second_state.wall[:1]

    # 取得相同座位玩家的 Observation
    first = game_state_to_observation(first_state, seat = 0)
    second = game_state_to_observation(second_state, seat = 0)

    # 建立兩個固定的合法出牌動作
    # 兩份 Observation 都使用相同的 LegalActions
    legal_actions = [
        LegalAction(
            id = "discard_27",
            action = ActionType.DISCARD,
            tile = 27,
        ),
        LegalAction(
            id = "discard_31",
            action = ActionType.DISCARD,
            tile = 31,
        ),
    ]

    # 使用目前的 BaselinePolicy 與台麻向聽數計算器
    policy = BaselinePolicy(Taiwan16ShantenCalculator())

    # 分別讓 Baseline 在兩份牌局中進行決策
    first_decision = policy.decide(first, legal_actions)
    second_decision = policy.decide(second, legal_actions)

    # 即使隱藏資訊不同，AI 仍應產生相同的決策
    assert first_decision == second_decision

    # 最後選出的動作必須存在於合法動作清單中
    assert first_decision.action in legal_actions


# 測試公開河牌發生變化時，Strategy 能正確觀察到差異
def test_public_discard_changes_are_visible():
    first_state = make_state()
    second_state = first_state.model_copy(deep = True)

    # 玩家 1 新增一張公開棄牌 ID 16
    # 河牌屬於公開資訊，因此 Agent 應能看見這項變化
    second_state.players[1].discards.append(16)

    # 分別取得修改前後的 Observation
    first = game_state_to_observation(first_state, seat = 0)
    second = game_state_to_observation(second_state, seat = 0)

    # 公開河牌發生變化，Observation 應該不同
    assert first != second

    # 原本的 555 維 Encoder 應反映河牌變化
    assert encode_observation(first) != encode_observation(second)

    # Day 3 的公開資訊特徵也應反映河牌變化
    assert extract_public_features(first) != extract_public_features(second)


# 測試剩餘牌數未知時，不應直接使用牌牆的隱藏資訊
def test_unknown_remaining_tiles_do_not_expose_wall():
    # 從原始牌局取得 Observation
    observation = game_state_to_observation(make_state(), seat = 0)

    # 模擬實際遊戲無法公開取得剩餘牌數的情況
    # 使用 None 表示未知，而不是自行讀取或推測牌牆
    unknown = replace(observation, remaining_tiles = None)

    # 即使剩餘牌數未知，Encoder 仍應保持固定 555 維
    assert len(encode_observation(unknown)) == 555

    # Encoder 使用 -1.0 表示剩餘牌數未知
    assert encode_observation(unknown)[-1] == -1.0

    # 取得 Day 3 定義的公開資訊特徵
    public_features = extract_public_features(unknown)

    # remaining_tiles_known 為 0，表示無法取得剩餘牌數
    assert public_features.remaining_tiles_known == 0

    # 未知的剩餘牌數比例使用 -1.0
    assert public_features.remaining_tiles_ratio == -1.0

    # 危險度模型尚未建立，因此仍然標記為不可用
    assert extract_danger_features(unknown).risk_available is False