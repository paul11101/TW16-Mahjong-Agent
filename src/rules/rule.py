from enum import Enum
from typing import List, Optional, Dict
from pydantic import BaseModel, Field, ConfigDict
from src.common.schemas import ActionType

# 2. 定義單次動作結構
class Action(BaseModel):
    action_type: ActionType = Field(..., description="動作類型")
    tile_id: Optional[int] = Field(None, description="要打出或反應的牌張 ID (0~41)")
    sequence: Optional[List[int]] = Field(None, description="吃牌時組成的順子 ID 列表，例如 [0, 1, 2]")
    kong_type: Optional[str] = Field(None, description="槓牌種類: 'ming'(明槓), 'an'(暗槓), 'jia'(加槓)")

    model_config = ConfigDict(use_enum_values=True)

# 3. 規則設定結構
class RuleMechanics(BaseModel):
    strict_pass_rule: bool = Field(True, description="嚴格過水規則")
    multi_winner: bool = Field(False, description="是否允許一砲多響")
    winner_priority: str = Field("seat_order", description="多人爭胡時依座號優先")
    reserved_wall_tiles: int = Field(16, description="海底保留牌數（台麻留16張）")
    auto_flower_replacement: bool = Field(True, description="摸到花牌自動補花")

# 預設台數對照表
DEFAULT_SCORING_TAI = {
    "base_tai": 1,          # 底台
    "dealer_tai": 1,        # 莊家
    "self_draw": 1,         # 自摸
    "in_hand": 1,           # 門清
    "flower": 1,            # 花牌
    "triplet_dragon": 1,    # 三元牌刻子
    "peng_peng_hu": 4,      # 碰碰胡
    "hun_yi_se": 4,         # 混一色
    "qing_yi_se": 8,        # 清一色
    "da_san_yuan": 8,       # 大三元
    "da_si_xi": 16          # 大四喜
}

class RulesetConfig(BaseModel):
    ruleset_version: str = "1.0.0"
    rule_name: str = "Taiwan_16_Cards_Standard"
    hand_size: int = 16
    rule_mechanics: RuleMechanics = Field(default_factory=RuleMechanics)
    scoring_tai: Dict[str, int] = Field(default_factory=lambda: DEFAULT_SCORING_TAI.copy())

if __name__ == "__main__":
    config = RulesetConfig()
    print("規則設定格式驗證成功！")
    print(config.model_dump_json(indent=2))