"""批次統計（W7）：把多局的 GameRunSummary 合成一份報表，並對照企劃書目標。

統計口徑（定稿，見 docs/integration/w7_notes.md 第 3 節）：
- 無介入完成率 = 「整局無介入完成」的局數 / 全部局數；沒跑起來的局也算失敗，不從分母刪除。
- 操作成功率 = UI 動作成功數 / UI 動作數（ui_action_executed=True 的回執，重試不另算一筆）。
- 重複點擊 = 各步驟 (實際點擊數 - (計畫點擊數 + 重試數)) 的正值總和；另外比對網頁收到的點擊數。
- p95 = 所有局的 UI 動作 latency 合併後再算（不能對各局 p95 再取 p95）。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.control.util import atomic_write_json, p95

TARGET_UNATTENDED_RATE = 0.95
TARGET_UI_SUCCESS_RATE = 0.995
TARGET_P95_MS = 2000.0
MIN_UI_ACTIONS = 1000


def row_unattended(row: Mapping[str, Any]) -> bool:
    """這一局是否「整局無人工介入完成」（牌局真的結束、沒暫停過、評測器對得上、事件順序正常）。"""
    return (
        bool(row.get("finished"))
        and int(row.get("interventions", 0) or 0) == 0
        and bool(row.get("truth_ok", True))
        and bool(row.get("order_ok", True))
    )


def failed_start_row(game_id: str, seed: int | None, reason: str) -> dict[str, Any]:
    """局根本沒跑起來（連不到網頁等）：算一局失敗、一次人工介入。"""
    return {
        "game_id": game_id, "seed": seed, "finished": False, "reason": reason,
        "steps": 0, "completed": 0, "skipped": 0, "failed": 0, "interventions": 1,
        "ui_actions": 0, "ui_success": 0, "verified_actions": 0, "retries": 0,
        "physical_clicks": 0, "extra_clicks": 0, "error_codes": {reason: 1},
        "latencies_ms": [], "duration_s": 0.0, "truth_ok": True, "order_ok": True,
        "page_match": True,
    }


@dataclass(frozen=True)
class BatchReport:
    batch_id: str
    requested_games: int | None
    games: int
    finished_games: int
    unattended_games: int
    unattended_rate: float | None
    interventions: int
    ui_actions: int
    ui_success: int
    ui_success_rate: float | None
    verified_actions: int
    retries: int
    failed_attempts: int
    physical_clicks: int
    extra_clicks: int
    page_mismatch_games: int
    error_codes: dict[str, int]
    latency_count: int
    latency_p95_ms: float | None
    duration_s: float
    rows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def aggregate(batch_id: str, rows: Sequence[Mapping[str, Any]], *, requested: int | None = None) -> BatchReport:
    data = [dict(r) for r in rows]
    errors: Counter[str] = Counter()
    latencies: list[float] = []
    for r in data:
        errors.update(r.get("error_codes") or {})
        latencies.extend(r.get("latencies_ms") or [])

    def total(key: str) -> int:
        return sum(int(r.get(key, 0) or 0) for r in data)

    games = len(data)
    ui_actions, ui_success = total("ui_actions"), total("ui_success")
    unattended = sum(1 for r in data if row_unattended(r))

    return BatchReport(
        batch_id=batch_id,
        requested_games=requested,
        games=games,
        finished_games=sum(1 for r in data if r.get("finished")),
        unattended_games=unattended,
        unattended_rate=unattended / games if games else None,
        interventions=total("interventions"),
        ui_actions=ui_actions,
        ui_success=ui_success,
        ui_success_rate=ui_success / ui_actions if ui_actions else None,
        verified_actions=total("verified_actions"),
        retries=total("retries"),
        failed_attempts=total("failed"),
        physical_clicks=total("physical_clicks"),
        extra_clicks=total("extra_clicks"),
        page_mismatch_games=sum(1 for r in data if not r.get("page_match", True)),
        error_codes=dict(errors),
        latency_count=len(latencies),
        latency_p95_ms=p95(latencies),
        duration_s=sum(float(r.get("duration_s", 0.0) or 0.0) for r in data),
        rows=[{k: v for k, v in r.items() if k != "latencies_ms"} for r in data],
    )


def check_targets(report: "BatchReport | Mapping[str, Any]") -> list[dict[str, Any]]:
    """對照企劃書驗收指標。ok：True 達標、False 未達標、None 沒有資料。"""
    d = report.to_dict() if hasattr(report, "to_dict") else dict(report)
    checks: list[dict[str, Any]] = []

    def add(name: str, value: Any, unit: str, target: str, ok: bool | None, note: str = "") -> None:
        checks.append({"name": name, "value": value, "unit": unit, "target": target, "ok": ok, "note": note})

    rate = d.get("unattended_rate")
    add("無介入完成率", rate, "ratio", "≥ 95%",
        None if rate is None else rate >= TARGET_UNATTENDED_RATE,
        f"{d.get('unattended_games', 0)}/{d.get('games', 0)} 局")

    success = d.get("ui_success_rate")
    actions = int(d.get("ui_actions", 0) or 0)
    add("操作成功率", success, "ratio", "≥ 99.5%",
        None if success is None else success >= TARGET_UI_SUCCESS_RATE,
        f"樣本 {actions} 次，企劃書要求 ≥ {MIN_UI_ACTIONS:,} 次" if actions < MIN_UI_ACTIONS else f"樣本 {actions} 次")

    extra = int(d.get("extra_clicks", 0) or 0)
    games = int(d.get("games", 0) or 0)
    add("重複點擊", extra, "count", "0 次", None if games == 0 else extra == 0)

    mismatch = int(d.get("page_mismatch_games", 0) or 0)
    add("點擊送達（網頁收到數 = 滑鼠點擊數）", mismatch, "count", "0 局",
        None if games == 0 else mismatch == 0,
        "不一致 = 點擊沒送到網頁，或網頁多收；請看該局的暫停畫面")

    p = d.get("latency_p95_ms")
    add("同步動作確認 p95", p, "ms", "≤ 2000 ms",
        None if p is None else p <= TARGET_P95_MS, f"{d.get('latency_count', 0)} 筆")

    return checks


def _fmt(value: Any, unit: str) -> str:
    if value is None:
        return "-"
    if unit == "ratio":
        return f"{value:.2%}"
    if unit == "ms":
        return f"{value:.0f} ms"
    return str(value)


def format_report(report: BatchReport) -> str:
    requested = f"/{report.requested_games}" if report.requested_games is not None else ""
    lines = [
        f"批次 {report.batch_id}：{report.games}{requested} 局，牌局打完 {report.finished_games} 局，"
        f"無介入 {report.unattended_games} 局，人工介入 {report.interventions} 次",
        f"UI 動作 {report.ui_actions} 次，成功 {report.ui_success}，重試 {report.retries}，"
        f"實際點擊 {report.physical_clicks} 次，多餘點擊 {report.extra_clicks} 次",
    ]
    if report.error_codes:
        lines.append(f"錯誤碼：{report.error_codes}")
    for c in check_targets(report):
        mark = "—" if c["ok"] is None else ("✅" if c["ok"] else "❌")
        note = f"（{c['note']}）" if c["note"] else ""
        lines.append(f"{mark} {c['name']}：{_fmt(c['value'], c['unit'])}，目標 {c['target']}{note}")
    return "\n".join(lines)


def save_report(path: str | Path, report: BatchReport) -> Path:
    return atomic_write_json(path, report.to_dict())


def load_report(path: str | Path) -> dict[str, Any]:
    import json

    return json.loads(Path(path).read_text(encoding="utf-8"))


def _newest(log_dir: str | Path, pattern: str) -> list[Path]:
    folder = Path(log_dir)
    if not folder.is_dir():
        return []
    return sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)


def list_reports(log_dir: str | Path, limit: int = 5) -> list[dict[str, Any]]:
    """最近的批次報表（新到舊），附上目標對照；壞掉的檔案略過。"""
    out: list[dict[str, Any]] = []
    for path in _newest(log_dir, "*.batch.json"):
        try:
            data = load_report(path)
        except (OSError, ValueError):
            continue
        data["targets"] = check_targets(data)
        out.append(data)
        if len(out) >= limit:
            break
    return out


def list_game_records(log_dir: str | Path, limit: int = 30) -> list[dict[str, Any]]:
    """最近的 <game_id>.game.json 摘要（新到舊）。"""
    out: list[dict[str, Any]] = []
    for path in _newest(log_dir, "*.game.json"):
        try:
            data = load_report(path)
        except (OSError, ValueError):
            continue
        summary = data.get("summary") or {}
        out.append({
            "game_id": data.get("game_id"),
            "complete": data.get("complete"),
            "saved_at": data.get("saved_at"),
            "steps": len(data.get("steps", [])),
            "finished": summary.get("finished"),
            "reason": summary.get("reason"),
            "interventions": summary.get("interventions"),
            "ui_actions": summary.get("ui_actions"),
            "ui_success": summary.get("ui_success"),
            "latency_p95_ms": summary.get("latency_p95_ms"),
        })
        if len(out) >= limit:
            break
    return out