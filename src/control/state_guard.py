"""狀態一致性檢查（W5 D2）：畫面看到的手牌 vs 規則狀態的手牌，不一致就暫停。

企劃書：狀態不一致 -> 暫停；由當前畫面與已確認事件重建。

本模組只做兩件事：
1. check_state()：純函式，比對「畫面手牌」與「規則狀態手牌」，並做牌數合理性檢查。
2. StateGuard：檢查不過時，寫一筆 state_mismatch 事件，再呼叫 controller.pause()。
   暫停之後誰來恢復？人按「繼續」或熱鍵，或由 supervisor 等待（見 supervisor.py）。

不做辨識、不做決策、不點擊。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from src.common.events import EventSource, EventType, create_event
from src.common.logger import AppLogger
from src.control.controller import AgentController


@dataclass(frozen=True)
class StateCheck:
    """一次檢查的結果。ok=False 時 problems 說明原因。"""

    ok: bool
    problems: tuple[str, ...] = ()
    missing: tuple[int, ...] = ()  # 規則狀態有、畫面沒看到
    extra: tuple[int, ...] = ()  # 畫面有、規則狀態沒有


def valid_hand_sizes(meld_count: int) -> tuple[int, int]:
    """暗牌合理張數：台麻 16 張，每組副露（含槓）暗牌少 3 張；剛摸牌多 1 張。"""
    base = 16 - 3 * meld_count
    return base, base + 1


def check_state(
    visible_tiles: Iterable[int],
    expected_hand: Iterable[int],
    *,
    meld_count: int = 0,
) -> StateCheck:
    """畫面手牌（牌 ID 列表）與規則狀態手牌比對。"""
    visible = list(visible_tiles)
    expected = list(expected_hand)
    seen = Counter(visible)
    want = Counter(expected)

    missing = tuple(sorted((want - seen).elements()))
    extra = tuple(sorted((seen - want).elements()))

    problems: list[str] = []
    sizes = valid_hand_sizes(meld_count)

    if not 0 <= meld_count <= 5:
        problems.append(f"副露數 {meld_count} 超出 0~5")
    if len(visible) not in sizes:
        problems.append(f"畫面手牌 {len(visible)} 張，合理張數為 {sizes[0]} 或 {sizes[1]}")
    if len(expected) not in sizes:
        problems.append(f"規則狀態手牌 {len(expected)} 張，合理張數為 {sizes[0]} 或 {sizes[1]}")

    bad = sorted(t for t in visible if not 0 <= t < 34)
    if bad:
        problems.append(f"畫面手牌區出現花牌或無效牌 {bad}")

    for tile, count in sorted(seen.items()):
        if 0 <= tile < 34 and count > 4:
            problems.append(f"牌 {tile} 出現 {count} 張（超過 4 張）")

    if missing:
        problems.append(f"規則狀態有但畫面沒看到 {missing}")
    if extra:
        problems.append(f"畫面有但規則狀態沒有 {extra}")

    return StateCheck(not problems, tuple(problems), missing, extra)


class StateGuard:
    """檢查不過就記錄並暫停。"""

    def __init__(
        self,
        controller: AgentController,
        *,
        game_id: str,
        next_event_id: Callable[[], str] | None = None,
        logger: AppLogger | None = None,
        pause_on_mismatch: bool = True,
    ) -> None:
        self.controller = controller
        self.game_id = game_id
        self._next_event_id = next_event_id
        self.logger = logger
        self.pause_on_mismatch = pause_on_mismatch
        self.mismatch_count = 0
        self.history: list[StateCheck] = []

    def verify(
        self,
        visible_tiles: Iterable[int],
        expected_hand: Iterable[int],
        *,
        meld_count: int = 0,
        context: dict[str, Any] | None = None,
    ) -> StateCheck:
        check = check_state(visible_tiles, expected_hand, meld_count=meld_count)
        self.history.append(check)
        if check.ok:
            return check

        self.mismatch_count += 1
        self._log_mismatch(check, context)
        if self.pause_on_mismatch:
            self.controller.pause()  # 不在 RUNNING 時是 no-op
        return check

    def verify_mapper(
        self,
        mapper: Any,
        expected_hand: Iterable[int],
        *,
        meld_count: int = 0,
        context: dict[str, Any] | None = None,
    ) -> StateCheck:
        """用 TileMapper 目前的牌框當作畫面手牌。"""
        return self.verify(mapper.tiles(), expected_hand, meld_count=meld_count, context=context)

    def _log_mismatch(self, check: StateCheck, context: dict[str, Any] | None) -> None:
        if self.logger is None or self._next_event_id is None:
            return

        event = create_event(
            event_id=self._next_event_id(),
            game_id=self.game_id,
            event_type=EventType.STATE_MISMATCH,
            source=EventSource.INTEGRATION,
            payload={
                "problems": list(check.problems),
                "missing": list(check.missing),
                "extra": list(check.extra),
                "context": context or {},
            },
        )
        self.logger.log_event(event, console_message="State mismatch: " + "; ".join(check.problems))