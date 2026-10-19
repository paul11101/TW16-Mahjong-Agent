from dataclasses import dataclass
from .discard_features import NUM_BASIC_TILES
from .interfaces import Observation

# 定義出牌危險度特徵的資料結構
# discard_risk_scores：34 種基本牌各自的出牌風險分數
# risk_available：目前是否已有可使用的危險度評估結果
@dataclass(frozen = True)
class DangerFeatures:
    discard_risk_scores: tuple[float | None, ...]
    risk_available: bool


# 從 Observation 取得危險度預留特徵
# W5 Day 4 尚未實作真正的放槍風險計算
def extract_danger_features(observation: Observation) -> DangerFeatures:
    # 確認輸入是 Strategy 定義的 Observation
    # 避免直接傳入可能包含隱藏資訊的完整 GameState
    if not isinstance(observation, Observation):
        raise TypeError("observation must be an Observation")

    # 為 34 種基本牌建立固定長度的危險度欄位
    # None 表示尚未計算，而不是風險等於零
    discard_risk_scores = (None, ) * NUM_BASIC_TILES

    # 回傳危險度特徵
    # 目前所有風險分數都未知，因此 risk_available 設為 False
    return DangerFeatures(
        discard_risk_scores= discard_risk_scores,
        risk_available = False,
    )