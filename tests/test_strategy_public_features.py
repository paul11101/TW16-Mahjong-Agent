from dataclasses import replace

import pytest

from src.strategy.discard_features import extract_discard_features
from src.strategy.interfaces import Observation
from src.strategy.public_features import extract_public_features

# 建立固定的測試牌局
# 包含自己的手牌、四名玩家河牌、副露、花牌與剩餘牌數
def make_observation():
    return Observation(
        hand = (0, 0, 1, 27),
        discards = ((0, ), (0, 4), (5, ), (9, )),
        melds = (((2, 3, 4), ), ((11, 11, 11), ), (), ((28, 28, 28, 28), )),
        flowers = ((34, ), (35, 37), (), (36, )),
        current_player = 3,
        seat = 0,
        remaining_tiles = 72,
    )


# 測試公開資訊特徵的各項維度是否正確
def test_public_feature_sizes():
    result = extract_public_features(make_observation())

    # 每位玩家各有一個副露組數，因此為 4 維
    assert len(result.meld_counts) == 4

    # 34 種基本牌各有一個副露張數統計
    assert len(result.meld_tile_counts) == 34

    # 四位玩家各有一個花牌數量統計
    assert len(result.flower_counts) == 4

    # 台灣麻將共有 8 種花牌
    assert len(result.flower_tile_counts) == 8

    # 34 種基本牌的未見牌數上限
    assert len(result.unseen_upper_bounds) == 34

    # 四位玩家使用 4 維 One-Hot 編碼
    assert len(result.current_player_one_hot) == 4


# 測試副露組數與各種牌的公開副露張數是否正確
def test_melds_are_counted_by_player_and_tile():
    result = extract_public_features(make_observation())

    # 玩家 0、1、3 各有一組副露，玩家 2 沒有
    assert result.meld_counts == (1, 1, 0, 1)

    # 玩家 0 的副露為牌 ID 2、3、4
    assert result.meld_tile_counts[2] == 1
    assert result.meld_tile_counts[4] == 1

    # 玩家 1 公開碰出三張牌 ID 11
    assert result.meld_tile_counts[11] == 3

    # 玩家 3 公開槓出四張牌 ID 28
    assert result.meld_tile_counts[28] == 4


# 測試公開副露是否能進一步縮小未見牌數上限
def test_meld_refine_discard_unseen_bounds():
    observation = make_observation()

    # Day 2 只扣除自己的手牌與公開河牌
    base = extract_discard_features(observation)

    # Day 3 再扣除公開副露
    result = extract_public_features(observation)

    # 牌 ID 11 沒有出現在自己手牌與河牌中
    assert base.unseen_upper_bounds[11] == 4

    # 玩家 1 已公開碰出三張牌 ID 11，因此最多剩一張未見
    assert result.unseen_upper_bounds[11] == 1

    # 牌 ID 28 已經公開槓出四張，因此沒有剩餘未見牌
    assert result.unseen_upper_bounds[28] == 0


# 測試花牌是否能依照玩家及牌 ID 正確統計
def test_flowers_are_counted_by_player_and_tile():
    result = extract_public_features(make_observation())

    # 玩家 0 有一張、玩家 1 有兩張、玩家 2 沒有、玩家 3 有一張
    assert result.flower_counts == (1, 2, 0, 1)

    # 花牌 ID 34、35、36、37 各出現一次
    # 其他四種花牌尚未出現
    assert result.flower_tile_counts == (1, 1, 1, 1, 0, 0, 0, 0)


# 測試玩家回合、相對位置、河牌數量及剩餘牌數
def test_return_and_remaining_features():
    result = extract_public_features(make_observation())

    # 目前輪到玩家 3，因此 One-Hot 最後一個位置為 1
    assert result.current_player_one_hot == (0, 0, 0, 1)

    # Agent 位於玩家 0，目前玩家 3 的相對位置為 3
    assert result.relative_turn == 3

    # 目前不是 Agent 的回合
    assert result.is_my_turn == 0

    # 四位玩家目前總共打出五張牌
    assert result.public_discard_count == 5

    # 剩餘牌數為 72，除以 144 得到 0.5
    assert result.remaining_tiles_ratio == 0.5

    # 剩餘牌數已知，因此標記為 1
    assert result.remaining_tiles_known == 1


# 測試目前輪到自己且剩餘牌數未知的情況
def test_own_turn_and_unknown_remaining():
    observation = replace(
        make_observation(),
        # 設定目前輪到玩家 0，也就是 Agent 自己
        current_player = 0,

        # 剩餘牌數無法公開取得
        remaining_tiles = None,
    )

    result = extract_public_features(observation)

    # 玩家 0 的 One-Hot 編碼
    assert result.current_player_one_hot == (1, 0, 0, 0)

    # 目前行動玩家就是自己，因此相對位置為 0
    assert result.relative_turn == 0

    # 確認現在是自己的回合
    assert result.is_my_turn == 1

    # 未知的剩餘牌數使用 -1.0 表示
    assert result.remaining_tiles_ratio == -1.0

    # 剩餘牌數未知，因此標記為 0
    assert result.remaining_tiles_known == 0


# 測試剩餘牌數為零時，不會被誤判成未知
def test_zero_remaining_tiles_is_known():
    observation = replace(make_observation(), remaining_tiles = 0)
    result = extract_public_features(observation)

    # 剩餘零張的正規化結果為 0.0
    assert result.remaining_tiles_ratio == 0.0

    # 即使剩餘零張，這個數值仍然是已知資訊
    assert result.remaining_tiles_known == 1


# 使用參數化測試驗證不同種類的非法牌局資訊
# field：需要替換的 Observation 欄位
# replacement：故意建立的不合法資料
# message：預期 ValueError 包含的錯誤訊息
@pytest.mark.parametrize("field, replacement, message", [
    # 副露與花牌資料必須包含四位玩家
    ("melds", ((), (), ()), "melds must contain four players"),
    ("flowers", ((), (), ()), "flowers must contain four players"),

    # 吃碰槓的副露張數必須是三張或四張
    ("melds", (((2, 3),), (), (), ()), "invalid meld size"),

    # 公開副露不能包含花牌 ID 34
    ("melds", (((2, 3, 34), ), (), (), ()), "invalid meld tile"),

    # 花牌 ID 必須介於 34~41
    ("flowers", ((33, ), (), (), ()), "invalid flower tile"),

    # 同一種花牌不能出現兩次
    ("flowers", ((34, ), (34, ), (), ()), "duplicate flower tile"),

    # 目前行動玩家只能是 0~3
    ("current_player", 4, "invalid player id"),

    # Agent 自己的座位也只能是 0~3
    ("seat", -1, "invalid player id"),

    # 剩餘牌數不得超過台麻總牌數 144
    ("remaining_tiles", 145, "remaining tiles"),

    # 自己手牌、河牌與副露合計不能超過同種牌四張
    ("melds", (((0, 0, 0), ), (), (), ()), "exceeds four copies"),
])
def test_invalid_visible_state_is_rejected(field, replacement, message):
    # 使用 replace 建立帶有非法資料的 Observation
    observation = replace(make_observation(), **{field: replacement})

    # 確認程式能針對各種非法資料拋出 ValueError
    with pytest.raises(ValueError, match = message):
        extract_public_features(observation)



# 測試公開資訊特徵提取不會修改原本的 Observation
def test_extraction_does_not_mutate_observation():
    observation = make_observation()

    # 建立一份相同內容的 Observation 供比較
    before = replace(observation)

    # 執行公開資訊特徵提取
    extract_public_features(observation)

    # 確認提取前後 Observation 的內容保持一致
    assert observation == before