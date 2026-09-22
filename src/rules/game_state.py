from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

# 從同目錄下的 rule 模組匯入 Action, ActionType, RulesetConfig
from .rule import Action, ActionType, RulesetConfig


class Meld(BaseModel):
    """玩家亮出的副露（吃、碰、槓）"""
    meld_type: ActionType = Field(..., description="副露類型: CHI, PONG, KONG")
    tiles: List[int] = Field(..., description="組成副露的牌張 ID 列表，例如吃牌 [0, 1, 2]")
    from_player: int = Field(..., description="這組副露是來自哪位玩家的棄牌 (0~3)，暗槓可記自己")
    kong_type: Optional[str] = Field(None, description="若是槓牌，記錄 'ming', 'an', 'jia'")


class PlayerState(BaseModel):
    """台麻單一玩家的私有與公開狀態帳本"""
    seat_id: int = Field(..., ge=0, le=3, description="座位號碼 (0:東, 1:南, 2:西, 3:北)")
    score: int = Field(20000, description="當前籌碼/分數")
    
    # 牌區資訊 (0~41 ID 規範)
    hand: List[int] = Field(default_factory=list, description="手牌 ID 列表（未亮牌部分）")
    discards: List[int] = Field(default_factory=list, description="河牌/牌海（該玩家打出的牌）")
    melds: List[Meld] = Field(default_factory=list, description="副露列表（已吃/碰/槓的牌組）")
    flowers: List[int] = Field(default_factory=list, description="已補的花牌 ID 列表 (34~41)")
    
    # 玩家狀態標記 (台麻規範)
    is_tenpai: bool = Field(False, description="是否已聽牌")
    is_menqing: bool = Field(True, description="是否保持門清（無吃、碰、明槓）")


class LastDiscard(BaseModel):
    """紀錄上一張打出且尚未被處理的棄牌"""
    player_id: int = Field(..., description="打出這張牌的玩家 ID")
    tile_id: int = Field(..., description="打出的牌張 ID (0~41)")


class GameState(BaseModel):
    """整場台麻牌局的完整狀態帳本"""
    game_id: str = Field(..., description="牌局唯一識別碼")
    round_wind: int = Field(0, description="圈風 (0:東風圈, 1:南風圈, 2:西風圈, 3:北風圈)")
    dealer: int = Field(0, description="當前莊家座位號碼 (0~3)")
    lian_zhuang: int = Field(0, description="連莊次數")
    
    current_turn: int = Field(0, description="當前輪到行動的玩家座位 (0~3)")
    wall_count: int = Field(144, description="牌牆剩餘張數（台麻含花牌共 144 張）")
    
    last_discard: Optional[LastDiscard] = Field(None, description="最後一張打出且可被反應的牌")
    pending_players: List[int] = Field(default_factory=list, description="當前等待回應反應（吃碰槓胡）的玩家清單")
    
    players: Dict[int, PlayerState] = Field(..., description="鍵為座位號 (0~3)，值為玩家狀態")
    is_over: bool = Field(False, description="牌局是否已結束")


class EventType(str, Enum):
    """系統事件類型"""
    GAME_START = "game_start"
    DRAW_TILE = "draw_tile"
    DISCARD_TILE = "discard_tile"
    CLAIM_MELD = "claim_meld"
    FLOWER_REPLACEMENT = "flower_replacement"
    WIN_ROUND = "win_round"
    ROUND_DRAW = "round_draw"
    GAME_OVER = "game_over"


class GameEvent(BaseModel):
    """牌局中傳播與記錄的事件結構"""
    step: int = Field(..., description="事件遞增序號")
    event_type: EventType = Field(..., description="事件類型")
    actor_id: Optional[int] = Field(None, description="觸發此事件的玩家號碼 (0~3)")
    
    tile_id: Optional[int] = Field(None, description="涉及的牌張 ID (0~41)")
    action: Optional[Action] = Field(None, description="玩家發出的原始 Action 內容")
    details: Dict[str, Any] = Field(default_factory=dict, description="額外詳細資訊，如台數結算等")

    model_config = ConfigDict(use_enum_values=True)