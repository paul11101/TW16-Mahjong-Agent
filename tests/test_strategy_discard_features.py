from dataclasses import replace

import pytest

from src.strategy.discard_features import extract_discard_features
from src.strategy.interfaces import Observation

# 建立固定的測試牌局，包含自己的手牌及四位玩家的河牌
def make_observation():
    return Observation(
        hand = (0, 0, 1, 2, 27),
        discards = ((0, 3), (0, 4), (3, 4), (5, 6)),
        melds = ((), (), (), ()),
        flowers = ((), (), (), ()),
        current_player = 1,
        seat = 0,
        remaining_tiles = 80,
    )


# 測試河牌統計與未見牌數上限是否固定為 34 維
def test_discard_features_have_fixed_size():
    result = extract_discard_features(make_observation())

    # 台灣麻將一般牌共有 34 種
    assert len(result.discard_counts) == 34
    assert len(result.unseen_upper_bounds) == 34


# 測試四位玩家打出的河牌是否正確合併統計
def test_discard_counts_combine_four_players():
    result = extract_discard_features(make_observation())

    # 牌 ID 0 分別出現在玩家 0 與玩家 1 的河牌中
    assert result.discard_counts[0] == 2

    # 牌 ID 3 與 4 各出現兩張
    assert result.discard_counts[3] == 2
    assert result.discard_counts[4] == 2

    # 牌 ID 5 出現一張
    assert result.discard_counts[5] == 1

    # 牌 ID 27 沒有出現在河牌中
    assert result.discard_counts[27] == 0


# 測試未見牌數上限是否正確扣除自己的手牌與公開河牌
def test_unseen_upper_bounds_use_only_known_tiles():
    result = extract_discard_features(make_observation())

    # 牌 ID 0：自己兩張、河牌兩張，四張全部已知
    assert result.unseen_upper_bounds[0] == 0

    # 牌 ID 1：自己一張、河牌零張，最多還有三張未見
    assert result.unseen_upper_bounds[1] == 3

    # 牌 ID 3：自己零張、河牌兩張，最多還有兩張未見
    assert result.unseen_upper_bounds[3] == 2

    # 牌 ID 27：自己一張、河牌零張，最多還有三張未見
    assert result.unseen_upper_bounds[27] == 3

    # 牌 ID 9：自己與河牌都沒有，因此未見牌數上限為四張
    assert result.unseen_upper_bounds[9] == 4


# 測試所有玩家河牌為空時是否仍能正常計算
def test_empty_discards_are_supported():
    # 使用 replace 將原本的四組河牌清空
    observation = replace(make_observation(), discards = ((), (), (), ()))
    result = extract_discard_features(observation)

    # 沒有人打出牌，因此河牌數量合計為零
    assert sum(result.discard_counts) == 0

    # 未見牌數仍需扣除自己手上的牌
    assert result.unseen_upper_bounds[0] == 2
    assert result.unseen_upper_bounds[9] == 4


# 測試河牌資料不足四位玩家時，是否會拒絕不完整資料
def test_missing_player_discards_are_rejected():
    # 故意只提供三位玩家的河牌
    observation = replace(make_observation(), discards = ((), (), ()))

    # 應拋出 ValueError，避免使用不完整的河牌資訊
    with pytest.raises(ValueError, match = "four players"):
        extract_discard_features(observation)



# 測試非法河牌 ID 是否會被拒絕
def test_invalid_discard_tile_is_rejected():
    # 牌 ID 34 屬於花牌，不允許出現在基本河牌統計中
    observation = replace(make_observation(), discards = ((34, ), (), (), ()))

    # 預期拋出 ValueError，而不是發生索引錯誤
    with pytest.raises(ValueError, match = "invalid discard tile"):
        extract_discard_features(observation)



# 測試自己手牌中存在非法 ID 時的錯誤處理
def test_invalid_hand_tile_is_rejected():
    # Observation 允許的牌 ID 為 0~41，42 超出合法範圍
    observation = replace(make_observation(), hand = (42, ))

    # 應拒絕不合法的手牌資料
    with pytest.raises(ValueError, match = "invalid hand tile"):
        extract_discard_features(observation)



# 測試同種牌的已知數量超過四張時，是否會拋出錯誤
def test_excessive_visible_tile_count_is_rejected():
    observation = replace(
        make_observation(),
        # 自己持有四張牌 ID 1
        hand = (1, 1, 1, 1),

        # 河牌中又出現一張牌 ID 1，合計變成五張
        discards = ((1, ), (), (), ()),
    )

    # 麻將同種牌最多四張，因此這種情況屬於不合理資料
    with pytest.raises(ValueError, match = "exceeds four copies"):
        extract_discard_features(observation)



# 測試剩餘牌牆張數不會影響河牌特徵計算
def test_remaining_tiles_do_not_change_discard_features():
    observation = make_observation()

    # 將剩餘牌數改成未知，但保持手牌與河牌相同
    unknown = replace(observation, remaining_tiles = None)

    # 河牌特徵只依賴手牌與公開河牌，結果應完全一致
    assert extract_discard_features(observation) == extract_discard_features(unknown)


# 測試提取特徵時，不會修改原本的 Observation
def test_observation_remains_unchanged():
    observation = make_observation()

    # 建立另一個相同內容的 Observation 供測試比較
    before = replace(observation)

    # 執行河牌特徵提取
    extracted = extract_discard_features(observation)

    # 確認提取後，原本的 Observation 沒有被改動
    assert observation == before