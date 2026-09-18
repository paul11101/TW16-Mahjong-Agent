"""
events.py

定義系統事件格式。

所有模組都使用同一種事件結構，方便：
1. JSONL 紀錄
2. Debug
3. 回放
4. 整合測試
5. 未來接 SQLite 或 Web Dashboard
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    """取得目前 UTC 時間。"""
    return datetime.now(timezone.utc)


class EventType(str, Enum):
    """系統中可能出現的事件類型。"""

    GAME_STARTED = "game_started"
    GAME_FINISHED = "game_finished"

    OBSERVATION_CREATED = "observation_created"
    STATE_UPDATED = "state_updated"
    LEGAL_ACTIONS_GENERATED = "legal_actions_generated"

    DECISION_MADE = "decision_made"

    ACTION_STARTED = "action_started"
    ACTION_COMPLETED = "action_completed"
    ACTION_FAILED = "action_failed"

    STATE_MISMATCH = "state_mismatch"

    GAME_PAUSED = "game_paused"
    GAME_RESUMED = "game_resumed"
    GAME_STOPPED = "game_stopped"

    ERROR = "error"
    WARNING = "warning"
    SYSTEM_INFO = "system_info"


class EventSource(str, Enum):
    """事件發生來源模組。"""

    SYSTEM = "system"
    VISION = "vision"
    RULES = "rules"
    STRATEGY = "strategy"
    INTEGRATION = "integration"


class Event(BaseModel):
    """
    所有事件的共同格式。

    JSONL 中每一行就是一個 Event。
    """

    model_config = ConfigDict(
        use_enum_values=True,
        validate_assignment=True,
        extra="forbid",
    )

    event_id: str

    game_id: str

    timestamp: datetime = Field(default_factory=utc_now)

    event_type: EventType

    source: EventSource

    # 相關事件，例如 decision_made 對應前一個 legal_actions event
    parent_event_id: str | None = None

    # 事件內容
    payload: dict[str, Any] = Field(default_factory=dict)

    # 方便追蹤同一個流程
    trace_id: str | None = None

    # 額外標籤，例如 player_id、module_version
    metadata: dict[str, Any] = Field(default_factory=dict)


def create_event(
    *,
    event_id: str,
    game_id: str,
    event_type: EventType,
    source: EventSource,
    payload: dict[str, Any] | None = None,
    parent_event_id: str | None = None,
    trace_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Event:
    """
    建立一個統一格式的事件。

    範例：

        event = create_event(
            event_id="evt_001",
            game_id="game_001",
            event_type=EventType.GAME_STARTED,
            source=EventSource.SYSTEM,
            payload={"rule_version": "taiwan_16_tiles_v1"},
        )
    """

    return Event(
        event_id=event_id,
        game_id=game_id,
        event_type=event_type,
        source=source,
        parent_event_id=parent_event_id,
        payload=payload or {},
        trace_id=trace_id,
        metadata=metadata or {},
    )


def event_from_model(
    *,
    event_id: str,
    game_id: str,
    event_type: EventType,
    source: EventSource,
    model: BaseModel,
    parent_event_id: str | None = None,
    trace_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Event:
    """
    將 Pydantic model 包裝成 Event。

    例如把 Observation 包成 observation_created 事件。
    """

    return create_event(
        event_id=event_id,
        game_id=game_id,
        event_type=event_type,
        source=source,
        payload=model.model_dump(mode="json"),
        parent_event_id=parent_event_id,
        trace_id=trace_id,
        metadata=metadata,
    )