from dataclasses import asdict, dataclass
from math import isfinite

from .action_mask import ACTION_SPACE_SIZE
from .feature_spec import FEATURE_SIZE

# 訓練格式版本，變更特徵或動作索引定義時需更新
SCHEMA_VERSION = "tw16_bc_v1"

# 保存一筆教師決策的訓練資料，建立後不可重新指派欄位
@dataclass(frozen=True)
class TrainingSample:
    game_id: str
    decision_id: str
    strategy_version: str
    rule_version: str
    features: tuple[float, ...]
    action_mask: tuple[int, ...]
    # 教師選擇的動作索引，作為訓練標籤
    action_index: int
    wall_seed: int | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self):
        # 來源識別與版本必須完整，方便追查資料
        for name in ("game_id", "decision_id", "strategy_version", "rule_version"):
            value = getattr(self, name)

            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")

        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported schema_version")

        # 未知牌山種子保留 None；已知種子只接受非負整數
        if self.wall_seed is not None and (type(self.wall_seed) is not int or self.wall_seed < 0):
            raise ValueError("wall_seed must be a non-negative integer or None")

        # 將 JSON 陣列轉成 tuple，隔離外部清單的後續修改
        try:
            features, mask = tuple(self.features), tuple(self.action_mask)
        except TypeError as error:
            raise ValueError("features and action_mask must be sequences") from error

        # 沿用既有特徵維度，拒絕布林值、字串與非有限數值
        if len(features) != FEATURE_SIZE:
            raise ValueError(f"features must contain {FEATURE_SIZE} values")

        if any(type(value) not in (int, float) for value in features):
            raise ValueError("features must contain finite numbers")

        try:
            features = tuple(float(value) for value in features)
        except OverflowError as error:
            raise ValueError("features must contain finite numbers") from error

        if not all(isfinite(value) for value in features):
            raise ValueError("features must contain finite numbers")


        # 遮罩沿用既有動作空間，只允許整數 0、1
        if len(mask) != ACTION_SPACE_SIZE:
            raise ValueError(f"action_mask must contain {ACTION_SPACE_SIZE} values")

        if any(type(value) is not int or value not in (0, 1) for value in mask):
            raise ValueError("action_mask must contain only integer 0 or 1")

        # 標籤除了不能越界，也必須指向遮罩允許的動作
        if type(self.action_index) is not int or not 0 <= self.action_index < ACTION_SPACE_SIZE:
            raise ValueError("action_index is out of range")

        if mask[self.action_index] != 1:
            raise ValueError("action_index must select a legal action")


        # frozen 類別在初始化時，透過此方式保存驗證後的 tuple
        object.__setattr__(self, "features", features)
        object.__setattr__(self, "action_mask", mask)


    # 轉成可交給 JSON 編碼器的字典
    def to_dict(self) -> dict:
        return asdict(self)

    # 讀回時要求明確版本，重新建構也會執行欄位驗證
    @classmethod
    def from_dict(cls, data: dict) -> "TrainingSample":
        if not isinstance(data, dict) or "schema_version" not in data:
            raise ValueError("schema_version is required")

        try:
            return cls(**data)
        except TypeError as error:
            raise ValueError("invalid training sample fields") from error