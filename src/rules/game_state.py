from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

# ==============================================================================
# 0. 引用你原本定義的模組結構 (Action, ActionType, RulesetConfig)
# ==============================================================================

class ActionType(str, Enum):
    DISCARD = "discard"  # 棄牌：打出一張牌
    CHI = "chi"          # chi：吃牌
    PONG = "pong"        # pong：碰牌
    KONG = "kong"        # kong：槓牌
    WIN = "win"          # win：胡牌
    PASS = "pass"        # pass：放棄目前可執行的反應動作

class Action(BaseModel):
    action_type: ActionType = Field(..., description="動作類型")
    tile_id: Optional[int] = Field(None, description="要打出或反應的牌張 ID (0~41)")
    sequence: Optional[List[int]] = Field(None, description="吃牌時組成的順子 ID 列表，例如 [0, 1, 2]")
    kong_type: Optional[str] = Field(None, description="槓牌種類: 'ming'(明槓), 'an'(暗槓), 'jia'(加槓)")

    model_config = ConfigDict(use_enum_values=True)


# ==============================================================================
# 1. 玩家狀態與副露結構 (Player State & Melds)
# ==============================================================================

class Meld(BaseModel):
    """玩家亮出的副露（吃、碰、槓）"""
    meld_type: ActionType = Field(..., description="副露類型: CHI, PONG, KONG")
    tiles: List[int] = Field(..., description="組成副露的牌張 ID 列表，例如吃牌 [0, 1, 2]")
    from_player: int = Field(..., description="這組副露是來自哪位玩家的棄牌 (0~3)，暗槓可記自己")
    kong_type: Optional[str] = Field(None, description="若是槓牌，記錄 'ming', 'an', 'jia'")


class PlayerState(BaseModel):
    """單一玩家的私有與公開狀態帳本"""
    seat_id: int = Field(..., ge=0, le=3, description="座位號碼 (0:東, 1:南, 2:西, 3:北)")
    score: int = Field(20000, description="當前籌碼/分數")
    
    # 牌區資訊 (使用你原本定義的 0~41 ID)
    hand: List[int] = Field(default_factory=list, description="手牌 ID 列表（未亮牌部分）")
    discards: List[int] = Field(default_factory=list, description="河牌/牌海（該玩家打出的牌）")
    melds: List[Meld] = Field(default_factory=list, description="副露列表（已吃/碰/槓的牌組）")
    flowers: List[int] = Field(default_factory=list, description="已補的花牌 ID 列表 (34~41)")
    
    # 玩家狀態標記
    is_riichi: bool = Field(False, description="是否已聽牌/立直（適用於特定規則）")
    is_menqing: bool = Field(True, description="是否保持門清（無吃、碰、明槓）")


# ==============================================================================
# 2. 牌局狀態帳本 (GameState)
# ==============================================================================

class LastDiscard(BaseModel):
    """紀錄上一張打出且尚未被處理的棄牌（供其他人反應吃碰槓胡）"""
    player_id: int = Field(..., description="打出這張牌的玩家 ID")
    tile_id: int = Field(..., description="打出的牌張 ID (0~41)")


class GameState(BaseModel):
    """整場麻將牌局的完整狀態帳本"""
    # 牌局基本資訊
    game_id: str = Field(..., description="牌局唯一識別碼")
    round_wind: int = Field(0, description="圈風 (0:東風圈, 1:南風圈, 2:西風圈, 3:北風圈)")
    dealer: int = Field(0, description="當前莊家座位號碼 (0~3)")
    lian_zhuang: int = Field(0, description="連莊次數")
    
    # 當前進度狀態
    current_turn: int = Field(0, description="當前輪到行動的玩家座位 (0~3)")
    wall_count: int = Field(144, description="牌牆剩餘張數（摸牌堆）")
    
    # 待反應區域
    last_discard: Optional[LastDiscard] = Field(None, description="最後一張打出且可被反應的牌")
    pending_players: List[int] = Field(default_factory=list, description="當前等待回應反應（吃碰槓胡）的玩家清單")
    
    # 4 位玩家的詳細狀態
    players: Dict[int, PlayerState] = Field(..., description="鍵為座位號 (0~3)，值為玩家狀態")
    
    # 遊戲階段控制
    is_over: bool = Field(False, description="牌局是否已結束")


# ==============================================================================
# 3. 事件資料結構 (Event Protocol)
# ==============================================================================

class EventType(str, Enum):
    """系統事件類型"""
    GAME_START = "game_start"      # 開局發牌
    DRAW_TILE = "draw_tile"        # 摸牌
    DISCARD_TILE = "discard_tile"  # 打牌
    CLAIM_MELD = "claim_meld"      # 執行吃、碰、槓
    FLOWER_REPLACEMENT = "flower_replacement" # 補花
    WIN_ROUND = "win_round"        # 胡牌/自摸
    ROUND_DRAW = "round_draw"      # 流局
    GAME_OVER = "game_over"        # 遊戲結束


class GameEvent(BaseModel):
    """牌局中傳播與記錄的事件結構（用於廣播給玩家、繪製畫面、記錄 Log）"""
    step: int = Field(..., description="事件遞增序號")
    event_type: EventType = Field(..., description="事件類型")
    actor_id: Optional[int] = Field(None, description="觸發此事件的玩家號碼 (0~3)")
    
    # 事件夾帶的數據 (視 event_type 動態使用)
    tile_id: Optional[int] = Field(None, description="涉及的牌張 ID (0~41)")
    action: Optional[Action] = Field(None, description="玩家發出的原始 Action 內容")
    details: Dict[str, Any] = Field(default_factory=dict, description="額外詳細資訊，如勝負台數結算、得分變動等")

    model_config = ConfigDict(use_enum_values=True)


# ==============================================================================
# 4. 測試與驗證範例
# ==============================================================================

if __name__ == "__main__":
    # 1. 初始化一位玩家狀態
    p0 = PlayerState(
        seat_id=0,
        score=20000,
        hand=[0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 27, 28, 28, 31, 31, 32], # 16 張手牌 ID
        flowers=[34] # 已補一張春花
    )
    
    # 2. 初始化全局遊戲帳本 GameState
    game_state = GameState(
        game_id="GAME_20231025_001",
        round_wind=0,
        dealer=0,
        lian_zhuang=0,
        current_turn=0,
        wall_count=84, # 發完牌後的剩餘牌數
        players={0: p0, 1: PlayerState(seat_id=1), 2: PlayerState(seat_id=2), 3: PlayerState(seat_id=3)}
    )

    # 3. 建立一個「玩家 0 打出 1 萬 (ID: 0)」的事件紀錄
    discard_event = GameEvent(
        step=1,
        event_type=EventType.DISCARD_TILE,
        actor_id=0,
        tile_id=0,
        action=Action(action_type=ActionType.DISCARD, tile_id=0)
    )

    print("=== GameState JSON 輸出展示 ===")
    print(game_state.model_dump_json(indent=2))

    print("\n=== GameEvent (打牌紀錄) JSON 輸出展示 ===")
    print(discard_event.model_dump_json(indent=2))