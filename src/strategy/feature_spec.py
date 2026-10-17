from dataclasses import dataclass
from .encoder import NUM_PLAYERS, NUM_TILE_TYPES

# 定義單一特徵群組的資料結構
# 記錄特徵名稱、索引範圍、資料來源以及可見性
@dataclass(frozen = True)
class FeatureGroup:
    name: str
    start: int
    stop: int
    source: str
    visibility: str

    # 計算這組特徵佔用的維度數量
    @property
    def size(self) -> int:
        return self.stop - self.start



# 建立完整的 Observation 特徵配置
# 依照原本 Encoder 的順序，確保 555 維特徵位置不變
def build_feature_groups() -> tuple[FeatureGroup, ...]:
    groups = []

    # 新增特徵群組，並自動接續上一組的結束位置
    def add_group(name: str, size: int, source: str, visibility: str) -> None:
        start = groups[-1].stop if groups else 0
        groups.append(FeatureGroup(
            name = name,
            start = start,
            stop = start + size,
            source = source,
            visibility = visibility,
        ))

    # 自己的暗牌屬於玩家自身可見資訊，共 42 維
    add_group("hand", NUM_TILE_TYPES, "Observation.hand", "own",)

    # 四位玩家已打出的河牌屬於公開資訊，每位玩家各 42 維
    for player in range(NUM_PLAYERS):
        add_group(f"discards_{player}", NUM_TILE_TYPES, f"Observation.discards[{player}]", "public",)

    # 四位玩家已公開的吃、碰、槓牌組，每位玩家各 42 維
    for player in range(NUM_PLAYERS):
        add_group(f"melds_{player}", NUM_TILE_TYPES, f"Observation.melds[{player}]", "public",)

    # 四位玩家已公開的花牌，每位玩家各 42 維
    for player in range(NUM_PLAYERS):
        add_group(f"flowers_{player}", NUM_TILE_TYPES, f"Observation.flowers[{player}]", "public",)

    # 使用 4 維 One-Hot 表示目前輪到哪位玩家
    add_group("current_player", NUM_PLAYERS, "Observation.current_player", "public",)

    # 使用 4 維 One-Hot 表示 Agent 自己的座位
    add_group("seat", NUM_PLAYERS, "Observation.seat", "own",)

    # 剩餘牌數只有在公開可取得時才能使用，未知時由 Encoder 使用 -1.0
    add_group("remaining_tiles", 1, "Observation.remaining_tiles", "conditional",)

    # 回傳完整特徵配置
    return tuple(groups)


# 在模組載入時建立固定的特徵配置
FEATURE_GROUPS = build_feature_groups()

# 最後一組特徵的結束位置就是總維度數，目前應為 555
FEATURE_SIZE = FEATURE_GROUPS[-1].stop

# 根據特徵名稱取得向量中的切片範圍
def feature_slice(name: str) -> slice:
    for group in FEATURE_GROUPS:
        if group.name == name:
            return slice(group.start, group.stop)

    # 不允許存取未定義的特徵群組
    raise ValueError(f"unknown feature group: {name}")