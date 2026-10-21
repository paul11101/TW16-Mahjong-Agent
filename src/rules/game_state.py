import random
from enum import Enum
from functools import lru_cache
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from .rule import Action, RulesetConfig
from .legal_actions import LegalActionGenerator
from src.common.schemas import ActionType


@lru_cache(maxsize=None)
def has_only_melds(state: tuple[int, ...]) -> bool:
    try:
        tile_id = next(i for i, count in enumerate(state) if count)
    except StopIteration:
        return True

    remaining = list(state)
    if remaining[tile_id] >= 3:
        remaining[tile_id] -= 3
        if has_only_melds(tuple(remaining)):
            return True
        remaining[tile_id] += 3

    if (
        tile_id < 27
        and tile_id % 9 <= 6
        and remaining[tile_id + 1]
        and remaining[tile_id + 2]
    ):
        remaining[tile_id] -= 1
        remaining[tile_id + 1] -= 1
        remaining[tile_id + 2] -= 1
        if has_only_melds(tuple(remaining)):
            return True

    return False


def is_basic_win(hand: List[int], meld_count: int = 0) -> bool:
    """判斷手牌是否符合五組面子加一對眼的基本胡牌結構。"""
    if not 0 <= meld_count <= 5:
        raise ValueError("Meld count must be between 0 and 5")

    counts = [0] * 34
    for tile_id in hand:
        if not 0 <= tile_id < 34:
            raise ValueError(f"Invalid concealed hand tile ID: {tile_id}")
        counts[tile_id] += 1
        if counts[tile_id] > 4:
            raise ValueError(f"Too many copies of tile: {tile_id}")

    if len(hand) != (5 - meld_count) * 3 + 2:
        return False

    for tile_id, count in enumerate(counts):
        if count >= 2:
            counts[tile_id] -= 2
            if has_only_melds(tuple(counts)):
                return True
            counts[tile_id] += 2

    return False


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
    passed_win: bool = Field(False, description="是否處於過水狀態")
    has_drawn_since_pass: bool = Field(
        False,
        description="過水後是否已摸牌，需再打出非胡牌手牌才能解除",
    )
    
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

    def is_basic_win(self, player_id: int) -> bool:
        """判斷指定玩家目前手牌是否符合基本胡牌結構。"""
        player = self.players.get(player_id)
        if player is None:
            raise ValueError(f"Unknown player seat: {player_id}")
        return is_basic_win(player.hand, meld_count=len(player.melds))

    def complete_round(self, winner_id: Optional[int] = None) -> None:
        """結算本局：莊家胡牌或流局連莊，閒家胡牌則由下一家接莊。"""
        if self.is_over:
            raise ValueError("The round has already been completed")
        if winner_id is not None and winner_id not in self.players:
            raise ValueError(f"Unknown winner seat: {winner_id}")

        if winner_id is None or winner_id == self.dealer:
            self.lian_zhuang += 1
        else:
            self.dealer = (self.dealer + 1) % 4
            self.lian_zhuang = 0

        self.is_over = True

    def resolve_reaction_priority(
        self,
        reactions: Dict[int, Action],
        config: Optional[RulesetConfig] = None,
    ) -> Dict[int, Action]:
        """從同一張棄牌的玩家反應中，選出優先成立的動作。"""
        if self.last_discard is None:
            raise ValueError("There is no opponent discard available to resolve")

        config = config or RulesetConfig()
        discarder_id = self.last_discard.player_id
        target_tile = self.last_discard.tile_id
        reaction_priorities = {
            ActionType.CHI: 1,
            ActionType.PONG: 2,
            ActionType.KONG: 2,
            ActionType.WIN: 3,
        }
        valid_reactions: List[tuple[int, Action, int]] = []

        for player_id, action in reactions.items():
            if player_id not in self.players:
                raise ValueError(f"Unknown player seat: {player_id}")
            if player_id == discarder_id:
                raise ValueError("The player who discarded cannot react to their own discard")

            action_type = ActionType(action.action_type)
            if action_type == ActionType.PASS:
                continue
            if action_type not in reaction_priorities:
                raise ValueError(f"Unsupported reaction action: {action_type}")
            if (
                action_type == ActionType.WIN
                and config.rule_mechanics.strict_pass_rule
                and self.players[player_id].passed_win
            ):
                raise ValueError("False win: player is in a passed-win state")
            if action.tile_id != target_tile:
                raise ValueError("Reaction action must target the last discarded tile")
            if action_type == ActionType.KONG and action.kong_type != "ming":
                raise ValueError("Only an exposed kong can claim a discard")
            if action_type == ActionType.CHI and player_id != (discarder_id + 1) % 4:
                raise ValueError("Only the next player can claim a discard with chi")

            valid_reactions.append((reaction_priorities[action_type], action, player_id))

        if not valid_reactions:
            return {}

        winning_reactions = [
            reaction for reaction in valid_reactions
            if reaction[0] == reaction_priorities[ActionType.WIN]
        ]
        if winning_reactions:
            winning_reactions.sort(key=lambda reaction: (reaction[2] - discarder_id) % 4)
            if (
                config.rule_mechanics.multi_winner
                and config.rule_mechanics.winner_priority != "seat_order"
            ):
                raise ValueError(
                    f"Unsupported winner priority: {config.rule_mechanics.winner_priority}"
                )
            if config.rule_mechanics.multi_winner:
                return {
                    player_id: action
                    for _, action, player_id in winning_reactions
                }
            _, action, player_id = winning_reactions[0]
            return {player_id: action}

        highest_priority = max(priority for priority, _, _ in valid_reactions)
        highest_reactions = [
            reaction for reaction in valid_reactions
            if reaction[0] == highest_priority
        ]
        _, action, player_id = min(
            highest_reactions,
            key=lambda reaction: (reaction[2] - discarder_id) % 4,
        )
        return {player_id: action}

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
            self.players[seat].passed_win = False
            self.players[seat].has_drawn_since_pass = False
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
        if player_id != self.current_turn:
            raise ValueError(f"It is player {self.current_turn}'s turn, not player {player_id}'s")

        self.last_discard = None
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
            if player.passed_win:
                player.has_drawn_since_pass = True
            return action

        self.wall_count = len(self.wall)
        if not self.is_over:
            self.complete_round()
        return None

    def apply_action(
        self,
        player_id: int,
        action: Action,
        config: Optional[RulesetConfig] = None,
    ) -> Optional[Action]:
        """根據玩家傳入的 Action 來更新 GameState"""
        config = config or RulesetConfig()
        action_type = ActionType(action.action_type)
        player = self.players.get(player_id)
        if player is None:
            raise ValueError(f"Unknown player seat: {player_id}")

        if action_type == ActionType.FLOWER_REPLACEMENT:
            if player_id != self.current_turn:
                raise ValueError(f"It is player {self.current_turn}'s turn, not player {player_id}'s")
            if action.tile_id is None or not 34 <= action.tile_id <= 41:
                raise ValueError("Flower replacement requires a flower tile ID between 34 and 41")
            if action.tile_id not in player.hand:
                raise ValueError(f"Player {player_id} does not have flower tile {action.tile_id}")

            self.apply_flower_replacement(player_id, action.tile_id)
            return self.draw_tile(player_id=player_id, config=config)
        elif action_type == ActionType.DISCARD:
            if player_id != self.current_turn:
                raise ValueError(f"It is player {self.current_turn}'s turn, not player {player_id}'s")
            if action.tile_id is None or not 0 <= action.tile_id < 34:
                raise ValueError("Discard action requires a non-flower tile ID between 0 and 33")
            if action.tile_id not in player.hand:
                raise ValueError(f"Player {player_id} does not have tile {action.tile_id}")

            can_win_self_draw = (
                len(player.hand) == (5 - len(player.melds)) * 3 + 2
                and self.is_basic_win(player_id)
            )
            player.hand.remove(action.tile_id)
            player.discards.append(action.tile_id)
            self.record_discard_after_pass(
                player_id,
                can_win_self_draw=can_win_self_draw,
                config=config,
            )
            self.last_discard = LastDiscard(
                player_id=player_id,
                tile_id=action.tile_id,
            )
            self.current_turn = (player_id + 1) % 4
        elif action_type == ActionType.PASS:
            last_discard = self.last_discard
            if last_discard is None or player_id == last_discard.player_id:
                raise ValueError("There is no opponent discard to pass")

            if (
                config.rule_mechanics.strict_pass_rule
                and not player.passed_win
                and is_basic_win(
                    player.hand + [last_discard.tile_id],
                    meld_count=len(player.melds),
                )
            ):
                player.passed_win = True
                player.has_drawn_since_pass = False
        elif action_type in (ActionType.CHI, ActionType.PONG) or (
            action_type == ActionType.KONG and action.kong_type == "ming"
        ):
            last_discard = self.last_discard
            if last_discard is None or player_id == last_discard.player_id:
                raise ValueError("There is no opponent discard available to claim")

            source_player = self.players.get(last_discard.player_id)
            if (
                source_player is None
                or not source_player.discards
                or source_player.discards[-1] != last_discard.tile_id
            ):
                raise ValueError("The last discard is not available in the discard pile")

            is_previous_player = player_id == (last_discard.player_id + 1) % 4
            legal_actions = LegalActionGenerator().get_response_actions(
                hand=player.hand,
                target_tile=last_discard.tile_id,
                is_previous_player=is_previous_player,
                passed_win=player.passed_win,
            )
            if action not in legal_actions:
                raise ValueError("Illegal meld action for the last discard")

            if action_type == ActionType.CHI:
                meld_tiles = list(action.sequence or [])
                for tile_id in meld_tiles:
                    if tile_id != last_discard.tile_id:
                        player.hand.remove(tile_id)
                meld = Meld(
                    meld_type=ActionType.CHI,
                    tiles=meld_tiles,
                    from_player=last_discard.player_id,
                )
            elif action_type == ActionType.PONG:
                for _ in range(2):
                    player.hand.remove(last_discard.tile_id)
                meld = Meld(
                    meld_type=ActionType.PONG,
                    tiles=[last_discard.tile_id] * 3,
                    from_player=last_discard.player_id,
                )
            else:
                for _ in range(3):
                    player.hand.remove(last_discard.tile_id)
                meld = Meld(
                    meld_type=ActionType.KONG,
                    tiles=[last_discard.tile_id] * 4,
                    from_player=last_discard.player_id,
                    kong_type="ming",
                )

            source_player.discards.pop()
            player.melds.append(meld)
            player.is_menqing = False
            self.last_discard = None
            self.current_turn = player_id
        elif action_type == ActionType.KONG:
            if player_id != self.current_turn:
                raise ValueError(f"It is player {self.current_turn}'s turn, not player {player_id}'s")
            if action.tile_id is None or not 0 <= action.tile_id < 34:
                raise ValueError("Kong action requires a tile ID between 0 and 33")

            tile_id = action.tile_id
            if action.kong_type == "an":
                if player.hand.count(tile_id) != 4:
                    raise ValueError("Concealed kong requires four matching tiles in hand")
                for _ in range(4):
                    player.hand.remove(tile_id)
                player.melds.append(
                    Meld(
                        meld_type=ActionType.KONG,
                        tiles=[tile_id] * 4,
                        from_player=player_id,
                        kong_type="an",
                    )
                )
            elif action.kong_type == "jia":
                pong = next(
                    (
                        meld
                        for meld in player.melds
                        if meld.meld_type == ActionType.PONG
                        and meld.tiles == [tile_id] * 3
                    ),
                    None,
                )
                if pong is None or tile_id not in player.hand:
                    raise ValueError("Added kong requires a matching pong and fourth tile")
                player.hand.remove(tile_id)
                pong_index = player.melds.index(pong)
                player.melds[pong_index] = Meld(
                    meld_type=ActionType.KONG,
                    tiles=[tile_id] * 4,
                    from_player=pong.from_player,
                    kong_type="jia",
                )
            else:
                raise ValueError("Kong type must be 'an', 'ming', or 'jia'")
        else:
            raise ValueError(f"Unsupported action type: {action_type}")

        if action_type == ActionType.KONG:
            return self.draw_tile(player_id=player_id, config=config)
        return None

    def mark_player_drawn(self, player_id: int) -> None:
        """記錄玩家在過水後完成摸牌；須等棄出非胡牌手牌才解除。"""
        player = self.players.get(player_id)
        if player is None:
            raise ValueError(f"Unknown player seat: {player_id}")
        if player.passed_win:
            player.has_drawn_since_pass = True

    def record_discard_after_pass(
        self,
        player_id: int,
        *,
        can_win_self_draw: bool,
        config: Optional[RulesetConfig] = None,
    ) -> None:
        """根據成功的棄牌，更新自摸漏胡及過水解除狀態。"""
        player = self.players.get(player_id)
        if player is None:
            raise ValueError(f"Unknown player seat: {player_id}")

        config = config or RulesetConfig()
        if not config.rule_mechanics.strict_pass_rule:
            player.passed_win = False
            player.has_drawn_since_pass = False
        elif can_win_self_draw:
            player.passed_win = True
            player.has_drawn_since_pass = False
        elif player.passed_win and player.has_drawn_since_pass:
            player.passed_win = False
            player.has_drawn_since_pass = False