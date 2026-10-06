import random
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from .rule import Action, RulesetConfig
from .legal_actions import LegalActionGenerator
from src.common.schemas import ActionType


def create_shuffled_wall(rng: Optional[random.Random] = None) -> List[int]:
    """建立洗好的完整台麻牌牆：一般牌各四張，花牌各一張。"""
    wall = [tile_id for tile_id in range(34) for _ in range(4)]
    wall.extend(range(34, 42))
    if rng is None:
        rng = random.Random()
    rng.shuffle(wall)
    return wall


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


class GameState(BaseModel):
    """整場台麻牌局的完整狀態帳本"""
    game_id: str = Field(..., description="牌局唯一識別碼")
    round_wind: int = Field(0, description="圈風 (0:東風圈, 1:南風圈, 2:西風圈, 3:北風圈)")
    dealer: int = Field(0, description="當前莊家座位號碼 (0~3)")
    lian_zhuang: int = Field(0, description="連莊次數")
    
    current_turn: int = Field(0, description="當前輪到行動的玩家座位 (0~3)")
    wall: List[int] = Field(default_factory=create_shuffled_wall, description="尚未摸取的牌牆")
    wall_count: int = Field(144, description="牌牆剩餘張數（台麻含花牌共 144 張）")
    
    last_discard: Optional[LastDiscard] = Field(None, description="最後一張打出且可被反應的牌")
    pending_players: List[int] = Field(default_factory=list, description="當前等待回應反應（吃碰槓胡）的玩家清單")
    
    players: Dict[int, PlayerState] = Field(..., description="鍵為座位號 (0~3)，值為玩家狀態")
    is_over: bool = Field(False, description="牌局是否已結束")

    def deal(self, config: Optional[RulesetConfig] = None) -> None:
        """開局發牌；每位玩家取得設定張數，莊家額外取得一張。"""
        config = config or RulesetConfig()
        seats = range(4)

        if set(self.players) != set(seats):
            raise ValueError("Dealing requires players for all four seats (0-3)")
        if self.dealer not in self.players:
            raise ValueError(f"Unknown dealer seat: {self.dealer}")
        if any(player.hand or player.flowers for player in self.players.values()):
            raise ValueError("Cannot deal into a game with existing hands or flowers")

        reserved_tiles = config.rule_mechanics.reserved_wall_tiles
        if reserved_tiles < 0:
            raise ValueError("Reserved wall tile count cannot be negative")

        remaining_wall = list(self.wall)
        dealt_hands = {seat: [] for seat in seats}
        dealt_flowers = {seat: [] for seat in seats}

        def deal_one_tile(seat: int) -> None:
            while len(remaining_wall) > reserved_tiles:
                tile_id = remaining_wall.pop()
                if 34 <= tile_id <= 41:
                    dealt_flowers[seat].append(tile_id)
                    continue
                dealt_hands[seat].append(tile_id)
                return
            raise ValueError("Not enough drawable tiles to complete the deal")

        for _ in range(config.hand_size):
            for seat in seats:
                deal_one_tile(seat)
        deal_one_tile(self.dealer)

        for seat in seats:
            self.players[seat].hand = dealt_hands[seat]
            self.players[seat].flowers = dealt_flowers[seat]
        self.wall = remaining_wall
        self.wall_count = len(remaining_wall)
        self.current_turn = self.dealer

    def apply_flower_replacement(self, player_id: int, flower_tile: int) -> None:
        """將花牌移入玩家花牌區；牌牆扣減由摸牌流程負責。"""
        player = self.players.get(player_id)
        if not player:
            return

        # 1. 冪等性檢查：若花牌已在 flowers 列表中，代表該事件已處理過，直接忽略以避免重複扣減牌牆
        if flower_tile in player.flowers:
            return

        # 2. 首次處理：將花牌納入玩家 flowers 區
        player.flowers.append(flower_tile)

        # 3. 如果花牌還在手牌中，將其移出
        if flower_tile in player.hand:
            player.hand.remove(flower_tile)

    def draw_tile(
        self,
        player_id: Optional[int] = None,
        config: Optional[RulesetConfig] = None,
    ) -> Optional[Action]:
        """由牌牆摸牌；依規則自動補花，牌牆不足時回傳 None。"""
        player_id = self.current_turn if player_id is None else player_id
        player = self.players.get(player_id)
        if player is None:
            raise ValueError(f"Unknown player seat: {player_id}")

        config = config or RulesetConfig()
        action_generator = LegalActionGenerator(config=config)
        reserved_tiles = config.rule_mechanics.reserved_wall_tiles

        while len(self.wall) > reserved_tiles:
            drawn_tile = self.wall.pop()
            self.wall_count = len(self.wall)
            action = action_generator.get_draw_actions(drawn_tile)

            if action.action_type == ActionType.FLOWER_REPLACEMENT:
                if config.rule_mechanics.auto_flower_replacement:
                    self.apply_flower_replacement(player_id, drawn_tile)
                    continue

            player.hand.append(drawn_tile)
            return action

        self.wall_count = len(self.wall)
        return None

    def apply_action(self, player_id: int, action: Action) -> None:
        """根據玩家傳入的 Action 來更新 GameState"""
        if action.action_type == ActionType.FLOWER_REPLACEMENT:
            if action.tile_id is not None:
                self.apply_flower_replacement(player_id, action.tile_id)
        # 可依專案需求繼續補充其他動作類型的更新邏輯（如 DISCARD, CHI, PONG...）