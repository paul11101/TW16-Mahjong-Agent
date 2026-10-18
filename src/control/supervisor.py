"""回合監督者（W5 D1、D5）：依序跑多個回合，處理 pause / resume / stop 與中途恢復。

行為：
- 每個回合開始前檢查 controller：
    PAUSED  -> 等待（poll_interval 輪詢）；有人 resume 才繼續；pause_timeout 到了就 stop。
    STOPPED -> 結束，存 checkpoint。
    IDLE    -> 視為沒啟動，結束。
- 回合失敗且需要人介入（receipt.should_stop、狀態不一致、低信心、或回合中被暫停）：
    暫停，並且「不前進」，恢復後重跑同一回合。每回合最多 max_turn_attempts 次，超過就 stop。
- 回合中被 stop 且該回合沒完成：不前進，checkpoint 記下這一回合，之後可從這裡接著跑。
- 每個回合結束都寫 checkpoint（logs/<game_id>.checkpoint.json）。
  STOPPED 之後 controller 不能重啟，要「恢復」就建新的 controller，從 checkpoint 的 next_turn 接著跑。

注意：重跑同一回合代表呼叫端的回合函式每次都要「重新擷取、重新檢查」，不能重用舊畫面。
接續執行同一個 game_id 的 JSONL 時，請用新的 EventIds 前綴（例如 run2），否則 event_id 會重複。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from src.common.events import EventSource, EventType, create_event
from src.common.logger import AppLogger
from src.control.controller import AgentController
from src.control.errors import ERR_LOW_CONFIDENCE, ERR_STATE_MISMATCH

# 這些 TurnResult.error 代表「畫面或狀態不可信」，暫停後重跑同一回合
RETRY_TURN_ERRORS = frozenset({ERR_STATE_MISMATCH, ERR_LOW_CONFIDENCE})


# ------------------------------------------------------------------ checkpoint

@dataclass(frozen=True)
class Checkpoint:
    game_id: str
    next_turn: int  # 下一個要跑的回合索引（0 起算）
    reason: str  # turn_done / paused_retry / stopped / pause_timeout / max_attempts / finished ...
    updated_at: str


def save_checkpoint(path: str | Path, game_id: str, next_turn: int, reason: str) -> Checkpoint:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    checkpoint = Checkpoint(game_id, next_turn, reason, datetime.now(timezone.utc).isoformat())
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(
        json.dumps(checkpoint.__dict__, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tmp.replace(target)  # 原子替換，中途當機不會留下半個檔案
    return checkpoint


def load_checkpoint(path: str | Path) -> Checkpoint | None:
    target = Path(path)
    if not target.exists():
        return None

    data = json.loads(target.read_text(encoding="utf-8"))
    return Checkpoint(
        game_id=str(data["game_id"]),
        next_turn=int(data["next_turn"]),
        reason=str(data["reason"]),
        updated_at=str(data["updated_at"]),
    )


def start_index_from_checkpoint(path: str | Path) -> int:
    """從 checkpoint 決定要從第幾個回合開始；沒有檔案或已 finished 就從 0。"""
    checkpoint = load_checkpoint(path)
    if checkpoint is None or checkpoint.reason == "finished":
        return 0
    return checkpoint.next_turn


# ------------------------------------------------------------------ supervisor

@dataclass(frozen=True)
class RunSummary:
    game_id: str
    total_turns: int
    next_turn: int
    completed: int
    skipped: int
    failed: int  # 失敗的「嘗試」次數（重跑也各算一次，不從分母刪除）
    finished: bool
    reason: str
    results: tuple[Any, ...] = field(default=())

    @property
    def stopped(self) -> bool:
        return not self.finished


class RunSupervisor:
    def __init__(
        self,
        controller: AgentController,
        *,
        game_id: str,
        checkpoint_path: str | Path | None = None,
        logger: AppLogger | None = None,
        next_event_id: Callable[[], str] | None = None,
        poll_interval: float = 0.1,
        pause_timeout: float | None = None,
        max_turn_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_turn_attempts < 1:
            raise ValueError("max_turn_attempts 至少為 1")

        self.controller = controller
        self.game_id = game_id
        self.checkpoint_path = Path(checkpoint_path) if checkpoint_path is not None else None
        self.logger = logger
        self._next_event_id = next_event_id
        self.poll_interval = poll_interval
        self.pause_timeout = pause_timeout
        self.max_turn_attempts = max_turn_attempts
        self._sleep = sleep

    # -- 內部工具

    def _save(self, next_turn: int, reason: str) -> None:
        if self.checkpoint_path is not None:
            save_checkpoint(self.checkpoint_path, self.game_id, next_turn, reason)

    def _log(self, kind: str, **payload: Any) -> None:
        if self.logger is None or self._next_event_id is None:
            return
        event = create_event(
            event_id=self._next_event_id(),
            game_id=self.game_id,
            event_type=EventType.SYSTEM_INFO,
            source=EventSource.INTEGRATION,
            payload={"kind": kind, **payload},
        )
        self.logger.log_event(event, console_message=f"Supervisor: {kind}")

    def _wait_until_running(self) -> str | None:
        """回傳 None 代表可以跑；否則回傳結束原因。"""
        waited = 0.0
        while True:
            if self.controller.is_stopped:
                return "stopped"
            if self.controller.is_running:
                return None
            if not self.controller.is_paused:
                return "not_started"
            if self.pause_timeout is not None and waited >= self.pause_timeout:
                self.controller.stop()
                return "pause_timeout"
            self._sleep(self.poll_interval)
            waited += self.poll_interval

    # -- 主流程

    def run(self, turns: Sequence[Callable[[], Any]], *, start_at: int = 0) -> RunSummary:
        total = len(turns)
        i = max(0, start_at)
        attempts: dict[int, int] = {}
        completed = skipped = failed = 0
        results: list[Any] = []
        reason: str | None = None

        while i < total:
            gate = self._wait_until_running()
            if gate is not None:
                reason = gate
                break

            attempts[i] = attempts.get(i, 0) + 1
            if attempts[i] > self.max_turn_attempts:
                self.controller.stop()
                reason = "max_attempts"
                self._log("max_attempts", turn=i, attempts=attempts[i] - 1)
                break

            result = turns[i]()
            results.append(result)

            if getattr(result, "skipped", False):
                skipped += 1
            elif getattr(result, "success", False):
                completed += 1
            else:
                failed += 1

                if self.controller.is_stopped:
                    reason = "stopped"  # 回合中被停止，這一回合沒完成，不前進
                    break

                receipt = getattr(result, "receipt", None)
                must_retry = (
                    (receipt is not None and receipt.should_stop)
                    or getattr(result, "error", None) in RETRY_TURN_ERRORS
                    or self.controller.is_paused  # 回合中被暫停
                )
                if must_retry:
                    self.controller.pause()
                    self._log(
                        "turn_paused_for_retry",
                        turn=i,
                        attempt=attempts[i],
                        error=getattr(result, "error", None),
                    )
                    self._save(i, "paused_retry")
                    continue  # 回到迴圈開頭：等 resume，再重跑同一回合

            i += 1
            self._save(i, "turn_done")

        finished = reason is None and i >= total
        if reason is None:
            reason = "finished"
        self._save(i, reason)

        return RunSummary(
            game_id=self.game_id,
            total_turns=total,
            next_turn=i,
            completed=completed,
            skipped=skipped,
            failed=failed,
            finished=finished,
            reason=reason,
            results=tuple(results),
        )