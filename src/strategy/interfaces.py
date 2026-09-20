"""
策略模組共用介面。

負責定義 Observation、LegalAction、Decision 與 Strategy，
讓不同策略實作都使用相同輸入輸出格式。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Sequence


# 台灣 16 張麻將牌編碼：0~41
Tile = int


class ActionType(str, Enum):
    """策略支援的基本動作類型。"""

    DISCARD = "discard"
    CHI = "chi"
    PONG = "pong"
    KONG = "kong"
    WIN = "win"
    PASS = "pass"


@dataclass(frozen = True)
class Observation:
    """策略模型可使用的玩家可見牌局資訊。"""

    hand: tuple[Tile, ...]
    discards: tuple[tuple[Tile, ...], ...]
    melds: tuple[tuple[tuple[Tile, ...], ...], ...]
    flowers: tuple[tuple[Tile, ...], ...]
    current_player: int
    seat: int
    remaining_tiles: int | None = None


@dataclass(frozen = True)
class LegalAction:
    """規則模組確認合法後提供給策略模組的單一動作。"""

    id: str
    action: ActionType
    tile: Tile | None = None
    tiles: tuple[Tile, ...] = ()


LegalActions = Sequence[LegalAction]


@dataclass(frozen = True)
class Decision:
    """策略模組最後輸出的決策。"""

    action: LegalAction
    score: float
    reason: str


class Strategy(Protocol):
    """所有策略實作共同遵守的介面。"""

    def decide(self, observation: Observation, legal_actions: LegalActions,) -> Decision:
        ...
