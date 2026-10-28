"""整合端事件寫 JSONL 的共用函式（取代各模組自己的 _log）。"""

from __future__ import annotations

from typing import Any, Callable

from src.common.events import EventSource, EventType, create_event
from src.common.logger import AppLogger


def log_info(
    logger: AppLogger | None,
    next_event_id: Callable[[], str] | None,
    game_id: str,
    kind: str,
    *,
    event_type: EventType = EventType.SYSTEM_INFO,
    console_message: str | None = None,
    **payload: Any,
) -> None:
    """寫一筆整合端事件，payload 會帶 kind。沒有 logger 或 id 產生器時什麼都不做（不消耗 id）。"""
    if logger is None or next_event_id is None:
        return

    event = create_event(
        event_id=next_event_id(),
        game_id=game_id,
        event_type=event_type,
        source=EventSource.INTEGRATION,
        payload={"kind": kind, **payload},
    )
    logger.log_event(event, console_message=console_message or kind)