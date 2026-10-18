from dataclasses import dataclass
from .discard_features import NUM_BASIC_TILES, extract_discard_features
from .encoder import NUM_PLAYERS, NUM_TILE_TYPES, encode_player
from .interfaces import Observation

# 台灣 16 張麻將共有 144 張牌，包含 136 張基本牌與 8 張花牌
TOTAL_TILES = 144

# 計算花牌種類數：42 種牌扣除 34 種基本牌，共 8 種花牌
NUM_FLOWER_TYPES = NUM_TILE_TYPES - NUM_BASIC_TILES

# 定義公開資訊特徵的資料結構
# 包含副露、花牌、未見牌數、玩家回合及剩餘牌牆資訊
@dataclass(frozen = True)
class PublicFeatures:
    meld_counts: tuple[int, ...]
    meld_tile_counts: tuple[int, ...]
    flower_counts: tuple[int, ...]
    flower_tile_counts: tuple[int, ...]
    unseen_upper_bounds: tuple[int, ...]
    current_player_one_hot: tuple[int, ...]
    relative_turn: int
    is_my_turn: int
    public_discard_count: int
    remaining_tiles_ratio: float
    remaining_tiles_known: int


# 從 Observation 提取公開資訊特徵
# 只使用自己手牌、公開河牌、副露、花牌及可取得的回合資訊
def extract_public_features(observation: Observation) -> PublicFeatures:
    # 確認副露資料包含四位玩家
    if len(observation.melds) != NUM_PLAYERS:
        raise ValueError("melds must contain four players")

    # 確認花牌資料包含四位玩家
    if len(observation.flowers) != NUM_PLAYERS:
        raise ValueError("flowers must contain four players")

    # 將目前行動玩家轉換成 4 維 One-Hot 特徵
    current_player_one_hot = encode_player(observation.current_player)

    # 確認 Agent 自己的座位編號位於 0~3
    encode_player(observation.seat)

    # 剩餘牌數若已知，必須介於 0~144
    # None 代表目前無法取得公開的剩餘牌數
    if observation.remaining_tiles is not None and not 0 <= observation.remaining_tiles <= TOTAL_TILES:
        raise ValueError("remaining tiles must be between 0 and 144")

    # 沿用 Day 2 的河牌特徵
    # 取得河牌統計與尚未扣除公開副露的未見牌數上限
    discard_features = extract_discard_features(observation)

    # 儲存四位玩家各自的副露組數
    meld_counts = []

    # 建立 34 維副露牌數量統計
    meld_tile_counts =  [0] * NUM_BASIC_TILES

    # 遍歷四位玩家的副露
    for player_melds in observation.melds:
        # 台麻一般胡牌結構最多包含五組面子
        if len(player_melds) > 5:
            raise ValueError("too many melds")

        # 記錄目前玩家已完成的副露組數
        meld_counts.append(len(player_melds))

        # 逐一檢查玩家的吃、碰、槓牌組
        for meld in player_melds:
            # 吃、碰為三張，槓牌為四張
            # 這裡只檢查張數，牌型合法性由 Rules 負責
            if len(meld) not in (3, 4):
                raise ValueError("invalid meld size")

            # 統計副露中每一種基本牌的公開張數
            for tile in meld:
                # 副露不可包含花牌或非法牌 ID
                if not 0 <= tile < NUM_BASIC_TILES:
                    raise ValueError(f"invalid meld tile: {tile}")

                meld_tile_counts[tile] += 1



    # 儲存四位玩家各自的花牌數量
    flower_counts = []

    # 建立 8 維花牌計數器，分別對應牌 ID 34~41
    flower_tile_counts = [0] * NUM_FLOWER_TYPES

    # 遍歷四位玩家公開的花牌
    for player_flowers in observation.flowers:
        # 記錄該玩家目前持有的公開花牌數量
        flower_counts.append(len(player_flowers))

        for tile in player_flowers:
            # 花牌 ID 必須位於 34~41
            if not NUM_BASIC_TILES <= tile < NUM_TILE_TYPES:
                raise ValueError(f"invalid flower tile: {tile}")

            # 將花牌 ID 34~41 轉成索引 0~7
            flower_index = tile - NUM_BASIC_TILES

            # 對應花牌出現的數量加一
            flower_tile_counts[flower_index] += 1

            # 每種花牌只有一張，不能在不同玩家之間重複出現
            if flower_tile_counts[flower_index] > 1:
                raise ValueError(f"duplicate flower tile: {tile}")


    # 儲存扣除公開副露後的未見牌數上限
    unseen_upper_bounds = []

    # 逐一處理 34 種基本牌
    for tile in range(NUM_BASIC_TILES):
        # Day 2 的未見牌數上限，再減去已公開副露的張數
        unseen = discard_features.unseen_upper_bounds[tile] - meld_tile_counts[tile]

        # 若結果小於零，代表已知同種牌超過四張
        if unseen < 0:
            raise ValueError(f"visible tile count exceeds four copies: {tile}")

        # 記錄目前尚未被看見的張數上限
        # 不代表這些牌一定存在於牌牆中
        unseen_upper_bounds.append(unseen)


    # 紀錄剩餘牌數是否已知
    # 1 代表已知，0 代表未知
    remaining_tiles_known = int(observation.remaining_tiles is not None)

    # 將已知剩餘牌數除以 144，轉換成 0~1 的比例
    # 若剩餘牌數未知，使用 -1.0 表示
    remaining_tiles_ratio = (
        observation.remaining_tiles / TOTAL_TILES
        if observation.remaining_tiles is not None
        else -1.0
    )

    # 回傳整理完成的公開資訊特徵
    return PublicFeatures(
        # 四名玩家的副露組數
        meld_counts = tuple(meld_counts),

        # 34 種基本牌在公開副露中的數量
        meld_tile_counts = tuple(meld_tile_counts),

        # 四名玩家各自公開的花牌數量
        flower_counts = tuple(flower_counts),

        # 8 種花牌的公開數量
        flower_tile_counts = tuple(flower_tile_counts),

        # 扣除自己手牌、河牌及副露後的未見牌數上限
        unseen_upper_bounds = tuple(unseen_upper_bounds),

        # 目前行動玩家的 One-Hot 特徵
        current_player_one_hot = tuple(current_player_one_hot),

        # 相對回合位置：0 自己、1 下家、2 對家、3 上家
        relative_turn = (observation.current_player - observation.seat) % NUM_PLAYERS,

        # 如果目前輪到自己，回傳 1，否則為 0
        is_my_turn = int(observation.current_player == observation.seat),

        # 四位玩家河牌中的總張數
        public_discard_count = sum(discard_features.discard_counts),

        # 剩餘牌數正規化結果
        remaining_tiles_ratio = remaining_tiles_ratio,

        # 剩餘牌數是否已知
        remaining_tiles_known = remaining_tiles_known,
    )