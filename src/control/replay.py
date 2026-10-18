"""事件回放骨架（W5 D4）：讀 JSONL -> 檢查順序 -> 統計 -> 逐筆回放。

目前是「骨架」：
- load_events：讀 logs/<game_id>.jsonl（每行一個 Event）。
- check_order：event_id 不重複、parent_event_id 指向更早的事件、時間不倒退。
- split_turns / summarize：依 state_updated 切回合，統計操作成功率、重試、暫停、延遲 p95。
- EventReplayer：step / seek / play，把事件一筆一筆交給 handler（之後 dashboard 可接這裡）。
還不會「重現畫面」或「重新送動作」，那要等視覺與規則的回放資料格式確定。

統計口徑（docs/integration/w4_notes.md 第 6 節）：
操作成功率分母 = ui_action_executed=True 的回執；點擊前被拒絕的只列在 error_codes。

指令列：
    python -m src.control.replay logs/<game_id>.jsonl [--events] [--turns]
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

Event = dict[str, Any]


class ReplayError(ValueError):
    """JSONL 內容無法解析。"""


def load_events(path: str | Path, *, strict: bool = True) -> list[Event]:
    """讀 JSONL。strict=False 時略過壞行（例如程式當機留下的半行）。"""
    events: list[Event] = []
    with open(path, encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                if strict:
                    raise ReplayError(f"{path}:{number} 不是合法 JSON：{exc}") from exc
                continue

            if not isinstance(event, dict) or "event_id" not in event or "event_type" not in event:
                if strict:
                    raise ReplayError(f"{path}:{number} 缺少 event_id 或 event_type")
                continue
            events.append(event)
    return events


def _parse_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def check_order(events: Sequence[Event]) -> list[str]:
    """回傳問題清單；空清單代表順序正常。"""
    problems: list[str] = []
    seen_ids: set[str] = set()
    last_time: datetime | None = None

    for index, event in enumerate(events):
        event_id = str(event["event_id"])
        if event_id in seen_ids:
            problems.append(f"#{index} 重複的 event_id：{event_id}")

        parent = event.get("parent_event_id")
        if parent is not None and parent not in seen_ids:
            problems.append(f"#{index} {event_id} 的 parent_event_id {parent} 找不到或在它之後")

        stamp = _parse_time(event.get("timestamp"))
        if stamp is not None:
            if last_time is not None and stamp < last_time:
                problems.append(f"#{index} {event_id} 時間倒退")
            last_time = stamp

        seen_ids.add(event_id)

    return problems


def split_turns(events: Sequence[Event]) -> list[list[Event]]:
    """依 state_updated 切回合；第一個回合含開頭的 game_started。"""
    turns: list[list[Event]] = []
    current: list[Event] = []
    started = False

    for event in events:
        if event["event_type"] == "state_updated":
            if started:
                turns.append(current)
                current = []
            started = True
        current.append(event)

    if current:
        turns.append(current)
    return turns


def _p95(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]


@dataclass(frozen=True)
class ReplaySummary:
    total_events: int
    turns: int
    by_type: dict[str, int]
    actions_completed: int
    actions_failed: int
    ui_actions: int  # ui_action_executed=True 的回執數（成功率分母）
    ui_success: int
    verified_actions: int
    retries: int
    skipped_reactions: int
    mismatches: int
    pauses: int
    resumes: int
    stops: int
    error_codes: dict[str, int]
    latency_p95_ms: float | None

    @property
    def ui_success_rate(self) -> float | None:
        return self.ui_success / self.ui_actions if self.ui_actions else None


def summarize(events: Sequence[Event]) -> ReplaySummary:
    by_type = Counter(str(e["event_type"]) for e in events)
    errors: Counter[str] = Counter()
    latencies: list[float] = []
    ui_actions = ui_success = verified = retries = 0

    for event in events:
        if event["event_type"] not in ("action_completed", "action_failed"):
            continue

        payload = event.get("payload") or {}
        retries += int(payload.get("retry_count") or 0)
        if payload.get("error_code"):
            errors[str(payload["error_code"])] += 1

        if payload.get("ui_action_executed"):
            ui_actions += 1
            if payload.get("success"):
                ui_success += 1
            if payload.get("state_verified"):
                verified += 1
            if payload.get("latency_ms") is not None:
                latencies.append(float(payload["latency_ms"]))

    return ReplaySummary(
        total_events=len(events),
        turns=len(split_turns(events)),
        by_type=dict(by_type),
        actions_completed=by_type.get("action_completed", 0),
        actions_failed=by_type.get("action_failed", 0),
        ui_actions=ui_actions,
        ui_success=ui_success,
        verified_actions=verified,
        retries=retries,
        skipped_reactions=by_type.get("reaction_skipped", 0),
        mismatches=by_type.get("state_mismatch", 0),
        pauses=by_type.get("game_paused", 0),
        resumes=by_type.get("game_resumed", 0),
        stops=by_type.get("game_stopped", 0),
        error_codes=dict(errors),
        latency_p95_ms=_p95(latencies),
    )


class EventReplayer:
    """把事件一筆一筆交出去（不重現畫面、不送動作）。"""

    def __init__(self, events: Iterable[Event]) -> None:
        self._events = list(events)
        self._pos = 0

    def __len__(self) -> int:
        return len(self._events)

    @property
    def position(self) -> int:
        return self._pos

    @property
    def done(self) -> bool:
        return self._pos >= len(self._events)

    def step(self) -> Event | None:
        if self.done:
            return None
        event = self._events[self._pos]
        self._pos += 1
        return event

    def seek(self, position: int) -> None:
        if not 0 <= position <= len(self._events):
            raise IndexError(f"position {position} 超出 0~{len(self._events)}")
        self._pos = position

    def reset(self) -> None:
        self._pos = 0

    def play(
        self,
        handler: Callable[[Event], None],
        *,
        until_type: str | None = None,
    ) -> int:
        """從目前位置開始交給 handler；遇到 until_type 時（該筆已交出）停下。回傳交出幾筆。"""
        count = 0
        while True:
            event = self.step()
            if event is None:
                return count
            handler(event)
            count += 1
            if until_type is not None and event["event_type"] == until_type:
                return count


def _brief(event: Event) -> str:
    payload = event.get("payload") or {}
    extra = ""
    if "error_code" in payload and payload["error_code"]:
        extra = f" error={payload['error_code']}"
    elif "action_id" in payload:
        extra = f" action={payload['action_id']}"
    return f"{event.get('timestamp', '')}  {event['event_type']:<24}{event['event_id']}{extra}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JSONL 事件回放／統計")
    parser.add_argument("path")
    parser.add_argument("--events", action="store_true", help="逐筆印出事件")
    parser.add_argument("--turns", action="store_true", help="印出每個回合的事件數")
    parser.add_argument("--lenient", action="store_true", help="略過壞行")
    args = parser.parse_args(argv)

    events = load_events(args.path, strict=not args.lenient)

    if args.events:
        EventReplayer(events).play(lambda e: print(_brief(e)))
        print()

    if args.turns:
        for number, turn in enumerate(split_turns(events), 1):
            print(f"回合 {number}：{len(turn)} 筆 -> {[e['event_type'] for e in turn]}")
        print()

    summary = summarize(events)
    rate = summary.ui_success_rate
    print(f"事件 {summary.total_events} 筆，回合 {summary.turns} 個")
    print(f"動作：完成 {summary.actions_completed}、失敗 {summary.actions_failed}、略過反應 {summary.skipped_reactions}")
    print(
        f"UI 動作 {summary.ui_actions} 次，成功 {summary.ui_success}"
        f"（{'-' if rate is None else f'{rate:.1%}'}），畫面驗證通過 {summary.verified_actions}，重試 {summary.retries}"
    )
    print(f"暫停 {summary.pauses}、繼續 {summary.resumes}、停止 {summary.stops}、狀態不一致 {summary.mismatches}")
    if summary.error_codes:
        print(f"錯誤碼：{summary.error_codes}")
    if summary.latency_p95_ms is not None:
        print(f"latency p95：{summary.latency_p95_ms:.1f} ms")

    problems = check_order(events)
    if problems:
        print(f"❌ 順序檢查：{len(problems)} 項問題")
        for problem in problems[:20]:
            print("  -", problem)
        return 1

    print("✅ 順序檢查通過")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())