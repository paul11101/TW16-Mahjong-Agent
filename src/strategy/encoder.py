from .interfaces import Observation

# 台灣 16 張麻將總共有 42 種牌型（34 種基本牌 + 8 種花牌）
NUM_TILE_TYPES = 42

# 固定為 4 位玩家
NUM_PLAYERS = 4


# 將牌 ID 序列轉換成 42 維的牌數量特徵
def count_tiles(tiles) -> tuple[int, ...]:
    # 建立 42 個位置，預設每種牌的數量都是 0
    counts = [0] * NUM_TILE_TYPES

    # 逐張統計牌的數量
    for tile in tiles:
        # 檢查牌 ID 是否在合法的 0~41 範圍內
        if not 0 <= tile < NUM_TILE_TYPES:
            raise ValueError(f"invalid tile id: {tile}")

        # 對應牌 ID 的數量加 1
        counts[tile] += 1

    # 轉成 tuple，作為固定的特徵格式
    return tuple(counts)


# 將玩家編號轉換成 4 維 one-hot 特徵
def encode_player(player: int) -> tuple[int, ...]:
    # 檢查玩家編號是否在合法的 0~3 範圍內
    if not 0 <= player < NUM_PLAYERS:
        raise ValueError(f"invalid player id: {player}")

    # 建立 4 維全為 0 的玩家特徵
    result = [0] * NUM_PLAYERS

    # 將目前玩家對應的位置設為 1
    result[player] = 1

    # 轉成 tuple 回傳
    return tuple(result)


# 將完整 Observation 轉換成模型可以使用的固定長度特徵向量
def encode_observation(observation: Observation) -> tuple[float, ...]:
    # 儲存最後所有牌局特徵
    features = []

    # 編碼自己的手牌，產生 42 維牌數量特徵
    features.extend(count_tiles(observation.hand))

    # 編碼四位玩家各自的棄牌
    for player_discards in observation.discards:
        features.extend(count_tiles(player_discards))

    # 編碼四位玩家的副露資訊
    for player_melds in observation.melds:
        # 將吃、碰、槓等多組副露攤平成單一牌 ID 列表
        meld_tiles = [
            tile
            for meld in player_melds
            for tile in meld
        ]

        # 將副露牌轉換成 42 維牌數量特徵
        features.extend(count_tiles(meld_tiles))

    # 編碼四位玩家目前已經取得的花牌
    for player_flowers in observation.flowers:
        features.extend(count_tiles(player_flowers))

    # 將目前輪到的玩家轉換成 4 維 one-hot
    features.extend(encode_player(observation.current_player))

    # 將 Agent 自己的座位轉換成 4 維 one-hot
    features.extend(encode_player(observation.seat))

    # 若無法取得剩餘牌數，使用 -1.0 表示未知
    if observation.remaining_tiles is None:
        features.append(-1.0)

    # 若有剩餘牌數，除以台麻總牌數 144 進行簡單正規化
    else:
        features.append(observation.remaining_tiles / 144.0)

    # 將所有特徵轉成固定不可變的 tuple 回傳
    return tuple(features)