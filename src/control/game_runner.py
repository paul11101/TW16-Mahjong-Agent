"""整局流程（W6 D1~D5）：觀察 -> 判斷階段 -> 出牌／反應 -> 確認畫面前進 -> 直到牌局結束。

和 supervisor 的差別：supervisor 跑「事先排好的回合清單」；真實對局的回合是動態的
（對手打牌、吃碰槓都會改變下一步），所以這裡每一輪都重新觀察，再決定要做什麼。

職責（整合端）：
- D1 串整局：observe_fn 回傳 Snapshot（階段 + 指紋），依階段呼叫對應的回合函式。
- D2 每動作後驗證：動作成功後，指紋沒變就不再動作（不重複點擊）；
     超過 advance_timeout 還沒前進 -> NOT_ADVANCED，暫停等人處理。
     （像素層級的驗證仍在 verifier；這裡是「遊戲層級」的驗證。）
- D3 完整事件日誌：暫停原因、整局摘要（game_finished）都寫進 JSONL。
- D4 防重複點擊／逾時：已點擊卻失敗 -> 一律暫停，不自動重點；沒點擊的失敗才自動重試（有次數上限）。
- D5 可回放：每一步寫進 <game_id>.game.json（每步存檔，中途當機也留得住）。

不做：辨識、規則、策略、實際點擊（這些在回合函式裡，由 pipeline 提供）。
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Hashable, Mapping, Sequence

from src.common.events import EventSource, EventType, create_event
from src.common.logger import AppLogger
from src.control.controller import AgentController
from src.control.errors import (
    ERR_IDLE_TIMEOUT,
    ERR_NOT_ADVANCED,
    ERR_OBSERVE_FAILED,
    ERR_TURN_EXCEPTION,
)
from src.control.supervisor import RETRY_TURN_ERRORS

PHASE_MY_TURN = "my_turn"  # 輪到自己出牌
PHASE_REACTION = "reaction"  # 他家打牌，自己可以吃碰槓胡過
PHASE_WAITING = "waiting"  # 等別人
PHASE_OVER = "over"  # 牌局結束
ACTION_PHASES = (PHASE_MY_TURN, PHASE_REACTION)


@dataclass(frozen=True)
class Snapshot:
    """一次觀察的結果。

    fingerprint：能代表「這個畫面」的可雜湊值；動作之後畫面有前進，指紋一定要改變
        （例如：階段、手牌、剩餘牌數、最後一張打出的牌）。
    detail：要寫進 JSONL 的簡單資訊（可 JSON 序列化）。
    data：給回合函式用的原始資料（不寫進 JSONL、不參與比較）。
    """

    phase: str
    fingerprint: Hashable = None
    detail: dict[str, Any] = field(default_factory=dict)
    data: Any = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class StepRecord:
    index: int
    attempt: int  # 同一個畫面的第幾次嘗試
    phase: str
    action_id: str | None
    success: bool
    skipped: bool
    ui_action_executed: bool
    state_verified: bool
    retry_count: int
    latency_ms: float | None
    error: str | None
    detail: dict[str, Any]
    at: str


@dataclass(frozen=True)
class GameSummary:
    game_id: str
    finished: bool
    reason: str
    steps: int
    completed: int
    skipped: int
    failed: int  # 失敗的「嘗試」次數（重試也各算一次，不從分母刪除）
    interventions: int  # 暫停等人處理的次數
    ui_actions: int  # ui_action_executed=True 的回執數（操作成功率分母）
    ui_success: int
    verified_actions: int
    retries: int
    error_codes: dict[str, int]
    latency_p95_ms: float | None
    duration_s: float

    @property
    def unattended(self) -> bool:
        """整局無人工介入完成。"""
        return self.finished and self.interventions == 0

    @property
    def ui_success_rate(self) -> float | None:
        return self.ui_success / self.ui_actions if self.ui_actions else None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Acted:
    fingerprint: Hashable
    at: float
    expect_change: bool


def _p95(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]


class GameRunner:
    def __init__(
        self,
        controller: AgentController,
        *,
        game_id: str,
        observe_fn: Callable[[], Snapshot | None],
        turn_fns: Mapping[str, Callable[[Snapshot], Any]],
        logger: AppLogger | None = None,
        next_event_id: Callable[[], str] | None = None,
        record_path: str | Path | None = None,
        poll_interval: float = 0.2,
        advance_timeout: float = 5.0,
        idle_timeout: float | None = 60.0,
        pause_timeout: float | None = None,
        max_steps: int = 500,
        max_step_attempts: int = 3,
        max_observe_failures: int = 3,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_step_attempts < 1 or max_steps < 1 or max_observe_failures < 1:
            raise ValueError("max_step_attempts / max_steps / max_observe_failures 至少為 1")

        self.controller = controller
        self.game_id = game_id
        self.observe_fn = observe_fn
        self.turn_fns = dict(turn_fns)
        self.logger = logger
        self._next_event_id = next_event_id
        self.record_path = Path(record_path) if record_path is not None else None
        self.poll_interval = poll_interval
        self.advance_timeout = advance_timeout
        self.idle_timeout = idle_timeout
        self.pause_timeout = pause_timeout
        self.max_steps = max_steps
        self.max_step_attempts = max_step_attempts
        self.max_observe_failures = max_observe_failures
        self._clock = clock
        self._sleep = sleep

        self.records: list[StepRecord] = []
        self.error_counts: Counter[str] = Counter()
        self.interventions = 0
        self._attempts: dict[Hashable, int] = {}
        self._acted: _Acted | None = None
        self._idle_since: float | None = None
        self._observe_failures = 0

    # ------------------------------------------------------------ 內部工具

    def _log(self, kind: str, event_type: EventType = EventType.SYSTEM_INFO, **payload: Any) -> None:
        if self.logger is None or self._next_event_id is None:
            return
        event = create_event(
            event_id=self._next_event_id(),
            game_id=self.game_id,
            event_type=event_type,
            source=EventSource.INTEGRATION,
            payload={"kind": kind, **payload},
        )
        hint = " ".join(
            f"{k}={payload[k]}" for k in ("phase", "action_id", "error", "attempt", "success") if payload.get(k) is not None
        )
        self.logger.log_event(event, console_message=f"GameRunner: {kind} {hint}".rstrip())

    def _pause_for_human(self, error: str | None, *, count: bool = True, **extra: Any) -> None:
        """暫停等人處理。count=False：這個錯誤已經記在某一步的紀錄裡，不要重複計入錯誤碼。"""
        self.interventions += 1
        if error and count:
            self.error_counts[error] += 1
        self._log("runner_paused", error=error, **extra)
        self.controller.pause()  # 不在 RUNNING 時是 no-op

    def _wait_until_running(self) -> str | None:
        """回傳 None 代表可以繼續；否則回傳結束原因。"""
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

    def _safe_observe(self) -> Snapshot | None:
        try:
            return self.observe_fn()
        except Exception as exc:  # noqa: BLE001  讀不到畫面不應讓整個程式當掉
            self._log("observe_error", error=f"{type(exc).__name__}: {exc}")
            return None

    def _act(self, snap: Snapshot, index: int, attempt: int) -> tuple[StepRecord, Any, bool]:
        """呼叫回合函式。回傳 (紀錄, 結果, 是否為例外)。"""
        fn = self.turn_fns.get(snap.phase)
        if fn is None:
            raise KeyError(f"沒有階段 {snap.phase!r} 的回合函式")

        start = time.perf_counter()
        result: Any = None
        raised = False
        message: str | None = None
        try:
            result = fn(snap)
        except Exception as exc:  # noqa: BLE001  策略／規則的錯誤不能讓整局崩潰，記錄後暫停
            raised = True
            message = f"{type(exc).__name__}: {exc}"
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        receipt = getattr(result, "receipt", None)
        decision = getattr(result, "decision", None)
        detail = dict(snap.detail)
        if message:
            detail["exception"] = message

        if raised:
            error: str | None = ERR_TURN_EXCEPTION
        elif receipt is not None:
            error = receipt.error_code
        else:
            error = getattr(result, "error", None)

        record = StepRecord(
            index=index,
            attempt=attempt,
            phase=snap.phase,
            action_id=decision.action.id if decision is not None else None,
            success=bool(getattr(result, "success", False)) and not raised,
            skipped=bool(getattr(result, "skipped", False)) and not raised,
            ui_action_executed=bool(receipt.ui_action_executed) if receipt is not None else False,
            state_verified=bool(receipt.state_verified) if receipt is not None else False,
            retry_count=int(receipt.retry_count) if receipt is not None else 0,
            latency_ms=(
                receipt.latency_ms if receipt is not None and receipt.latency_ms is not None
                else (None if raised else elapsed_ms)
            ),
            error=error,
            detail=detail,
            at=datetime.now(timezone.utc).isoformat(),
        )
        return record, result, raised

    def _summary(self, finished: bool, reason: str, started: float) -> GameSummary:
        records = self.records
        errors = Counter(self.error_counts)
        for r in records:
            if not r.success and not r.skipped and r.error:
                errors[r.error] += 1  # 每一步失敗各計一次；暫停原因（NOT_ADVANCED 等）另計在 error_counts

        ui = [r for r in records if r.ui_action_executed]
        return GameSummary(
            game_id=self.game_id,
            finished=finished,
            reason=reason,
            steps=len(records),
            completed=sum(1 for r in records if r.success),
            skipped=sum(1 for r in records if r.skipped),
            failed=sum(1 for r in records if not r.success and not r.skipped),
            interventions=self.interventions,
            ui_actions=len(ui),
            ui_success=sum(1 for r in ui if r.success),
            verified_actions=sum(1 for r in ui if r.state_verified),
            retries=sum(r.retry_count for r in records),
            error_codes=dict(errors),
            latency_p95_ms=_p95([r.latency_ms for r in ui if r.latency_ms is not None]),
            duration_s=self._clock() - started,
        )

    def _save_record(self, summary: GameSummary | None = None) -> None:
        if self.record_path is None:
            return
        data = {
            "game_id": self.game_id,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "complete": summary is not None,
            "summary": summary.to_dict() if summary is not None else None,
            "steps": [asdict(r) for r in self.records],
        }
        self.record_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.record_path.with_name(self.record_path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.record_path)  # 原子替換，中途當機不會留下半個檔案

    # ------------------------------------------------------------ 主流程

    def run(self) -> GameSummary:
        started = self._clock()
        reason = "unknown"
        finished = False
        self._log("game_runner_started", max_steps=self.max_steps)

        while True:
            gate = self._wait_until_running()
            if gate is not None:
                reason = gate
                break

            if len(self.records) >= self.max_steps:
                reason = "max_steps"
                break

            snap = self._safe_observe()
            if snap is None:
                self._observe_failures += 1
                if self._observe_failures >= self.max_observe_failures:
                    self._observe_failures = 0
                    self._pause_for_human(ERR_OBSERVE_FAILED)
                else:
                    self._sleep(self.poll_interval)
                continue
            self._observe_failures = 0

            if snap.phase == PHASE_OVER:
                finished = True
                reason = "game_over"
                break

            if snap.phase not in ACTION_PHASES:
                self._acted = None  # 畫面已經走到別的階段
                now = self._clock()
                if self._idle_since is None:
                    self._idle_since = now
                elif self.idle_timeout is not None and now - self._idle_since >= self.idle_timeout:
                    self._idle_since = None
                    self._pause_for_human(ERR_IDLE_TIMEOUT)
                    continue
                self._sleep(self.poll_interval)
                continue
            self._idle_since = None

            fp = snap.fingerprint

            # D2：同一個畫面已經動作過 -> 不重複點擊，等畫面前進
            if self._acted is not None and self._acted.fingerprint == fp:
                if self._acted.expect_change and self._clock() - self._acted.at >= self.advance_timeout:
                    self._acted = None  # 人按繼續之後，視為同意再試一次
                    self._pause_for_human(ERR_NOT_ADVANCED, phase=snap.phase)
                else:
                    self._sleep(self.poll_interval)
                continue

            self._attempts[fp] = self._attempts.get(fp, 0) + 1
            attempt = self._attempts[fp]
            if attempt > self.max_step_attempts:
                self.controller.stop()
                reason = "max_attempts"
                self._log("max_attempts", phase=snap.phase, attempts=attempt - 1)
                break

            record, result, raised = self._act(snap, len(self.records), attempt)
            self.records.append(record)
            self._save_record()
            self._log(
                "game_step",
                step=record.index, phase=record.phase, action_id=record.action_id,
                success=record.success, skipped=record.skipped, error=record.error,
                attempt=attempt,
            )

            if record.skipped:
                self._acted = _Acted(fp, self._clock(), expect_change=False)
                continue

            if record.success:
                self._acted = _Acted(fp, self._clock(), expect_change=True)
                continue

            # ---- 失敗
            if self.controller.is_stopped:
                reason = "stopped"
                break

            receipt = getattr(result, "receipt", None)
            must_pause = (
                raised
                or record.ui_action_executed  # D4：已經點過就不自動重點
                or (receipt is not None and receipt.should_stop)
                or record.error in RETRY_TURN_ERRORS
                or self.controller.is_paused
            )
            if must_pause:
                self._pause_for_human(record.error, count=False, phase=record.phase)
            else:
                self._sleep(self.poll_interval)  # 沒有點擊的失敗：重新觀察後自動再試

        summary = self._summary(finished, reason, started)
        self._save_record(summary)
        if finished:
            self._log("game_finished", EventType.GAME_FINISHED, summary=summary.to_dict())
        else:
            self._log("game_runner_stopped", reason=reason, summary=summary.to_dict())
        return summary


# ------------------------------------------------------------------ D5 回放

def load_game_record(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def describe_record(data: Mapping[str, Any]) -> str:
    lines = [f"game_id={data['game_id']}  complete={data['complete']}  steps={len(data['steps'])}"]
    for s in data["steps"]:
        mark = "skip" if s["skipped"] else ("ok  " if s["success"] else "FAIL")
        lines.append(
            f"#{s['index']:03d} [{mark}] {s['phase']:<9} {s['action_id'] or '-':<14}"
            f" attempt={s['attempt']} error={s['error']}"
        )
    summary = data.get("summary")
    if summary:
        lines.append(
            f"結果：finished={summary['finished']} reason={summary['reason']} "
            f"介入={summary['interventions']} UI動作={summary['ui_actions']} 成功={summary['ui_success']}"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="讀取 <game_id>.game.json 並列出每一步")
    parser.add_argument("path")
    args = parser.parse_args(argv)
    print(describe_record(load_game_record(args.path)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())