from src.strategy.encoder import count_tiles, encode_observation
from src.strategy.interfaces import Observation

# 測試 count_tiles 是否能正確統計每種牌出現的數量
def test_count_tiles():
    # 測試牌組：0 出現 2 次，1 與 27 各出現 1 次
    result = count_tiles((0, 0, 1, 27,))

    # 確認輸出固定為 42 種牌
    assert len(result) == 42
    # 確認牌 ID 0 出現 2 次
    assert result[0] == 2
    # 確認牌 ID 1 出現 1 次
    assert result[1] == 1
    # 確認牌 ID 27 出現 1 次
    assert result[27] == 1
    # 確認沒有出現的牌 ID 2 數量為 0
    assert result[2] == 0


# 測試 Observation 是否能正確編碼成固定長度的模型輸入特徵
def test_encode_observation():
    # 建立固定的測試牌局狀態
    observation = Observation(
        hand = (0, 1, 2, 27, 27,),
        discards = ((), (), (), ()),
        melds = ((), (), (), ()),
        flowers = ((), (), (), ()),
        current_player = 1,
        seat = 0,
        remaining_tiles = 80,
    )

    # 將 Observation 轉換成模型使用的特徵向量
    result = encode_observation(observation)

    # 確認最後輸出的特徵長度固定為 555
    assert len(result) == 555
    # 確認手牌中的牌 ID 0 出現 1 次
    assert result[0] == 1
    # 確認手牌中的牌 ID 1 出現 1 次
    assert result[1] == 1
    # 確認手牌中的牌 ID 2 出現 1 次
    assert result[2] == 1
    # 確認手牌中的牌 ID 27 出現 2 次
    assert result[27] == 2
    # 確認最後一個特徵是剩餘牌數正規化後的結果
    assert result[-1] == 80 / 144