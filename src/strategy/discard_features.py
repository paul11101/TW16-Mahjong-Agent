from dataclasses import dataclass
from .encoder import NUM_PLAYERS, NUM_TILE_TYPES
from .interfaces import Observation

# 台灣麻將共有 34 種基本牌，不包含花牌
NUM_BASIC_TILES = 34

# 每種基本牌最多四張
MAX_COPIES = 4

# 定義河牌特徵的資料結構
# discard_counts：各種牌已經出現在河牌中的數量
# unseen_upper_bounds：各種牌尚未被看見的張數上限
@dataclass(frozen = True)
class DiscardFeatures:
    discard_counts: tuple[int, ...]
    unseen_upper_bounds: tuple[int, ...]


# 從 Observation 提取河牌特徵
# 只使用自己的手牌與四位玩家公開的河牌資訊
def extract_discard_features(observation: Observation) -> DiscardFeatures:
    # 確認河牌資料包含四位玩家
    if len(observation.discards) != NUM_PLAYERS:
        raise ValueError("discards must contain four players")

    # 建立 34 維河牌計數器，記錄所有玩家打出的牌
    discard_counts = [0] * NUM_BASIC_TILES

    # 建立 34 維手牌計數器，只記錄自己的手牌
    own_hand_counts = [0] * NUM_BASIC_TILES

    # 統計自己持有的基本牌數量
    for tile in observation.hand:
        # 確認牌 ID 位於 0~41 的合法範圍
        if not 0 <= tile < NUM_TILE_TYPES:
            raise ValueError(f"invalid hand tile: {tile}")

        # 花牌不參與一般牌型的未見牌數計算
        if tile < NUM_BASIC_TILES:
            own_hand_counts[tile] += 1


    # 遍歷四位玩家的河牌，統計各種牌已經被打出的數量
    for player_discards in observation.discards:
        for tile in player_discards:
            # 河牌只接受 0~33 的基本牌，避免索引超出範圍
            if not 0 <= tile < NUM_BASIC_TILES:
                raise ValueError(f"invalid discard tile: {tile}")

            # 將指定牌的公開棄牌數量加一
            discard_counts[tile] += 1


    # 儲存每種基本牌尚未被看見的張數上限
    unseen_upper_bounds = []

    # 逐一計算 34 種基本牌的未見牌數
    for tile in range(NUM_BASIC_TILES):
        # 已知張數 = 自己持有的張數 + 四位玩家河牌中的張數
        visible_count = own_hand_counts[tile] + discard_counts[tile]

        # 同種牌最多四張，超過代表觀測資料不合理
        if visible_count > MAX_COPIES:
            raise ValueError(f"visible tile count exceeds four copies: {tile}")

        # 從四張中扣除已知張數，得到未見牌數上限
        # 此處尚未扣除公開副露，留待 W5 Day 3 處理
        unseen_upper_bounds.append(MAX_COPIES - visible_count)

    # 將統計結果轉成不可變的 tuple，回傳給後續策略使用
    return DiscardFeatures(
        discard_counts=tuple(discard_counts),
        unseen_upper_bounds=tuple(unseen_upper_bounds),
    )