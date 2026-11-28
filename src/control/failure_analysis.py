"""W8 D2/D4：批次失敗分析與延遲整理（只讀 logs，不動滑鼠、不連網頁）。

輸入：logs/<batch_id>.batch.json 與 logs/<batch_id>_gNN.game.json（run_batch 產生）。
輸出：
- 沒有「無介入完成」的局（原因、介入次數、錯誤碼）
- 失敗步驟（階段 + 錯誤碼分組、逐筆明細）
- UI 動作 latency：整體與分階段（my_turn / reaction）的 mean / p50 / p95 / max，對照 2 秒預算
- 最慢的 5 個動作、重試次數、缺少 .game.json 的局

指令：
    python -m src.control.failure_analysis logs --batch w8_xxx
    python -m src.control.failure_analysis logs                      # 最新一批
    python -m src.control.failure_analysis logs --batch a b --out logs\\w8_analysis.txt
"""

from __future__ import annotations

import argparse
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.control.batch import TARGET_P95_MS, list_reports, load_report, row_unattended
from src.control.util import p95


def latency_stats(values: Sequence[float | None]) -> dict[str, Any]:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return {"n": 0, "mean": None, "p50": None, "p95": None, "max": None}
    return {
        "n": len(vals),
        "mean": statistics.fmean(vals),
        "p50": statistics.median(vals),
        "p95": p95(vals),
        "max": max(vals),
    }


def load_game_records(log_dir: str | Path, batch_id: str) -> list[dict[str, Any]]:
    """讀這一批所有局的 .game.json（壞檔略過）。"""
    records: list[dict[str, Any]] = []
    for path in sorted(Path(log_dir).glob(f"{batch_id}_g*.game.json")):
        try:
            records.append(load_report(path))
        except (OSError, ValueError):
            continue
    return records


def analyze(batch: Mapping[str, Any], records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(batch.get("rows", []))

    bad_games = [
        {
            "game_id": r.get("game_id"), "seed": r.get("seed"), "finished": r.get("finished"),
            "reason": r.get("reason"), "interventions": r.get("interventions"),
            "error_codes": r.get("error_codes") or {},
        }
        for r in rows if not row_unattended(r)
    ]

    by_error: Counter[str] = Counter()
    by_phase_error: Counter[str] = Counter()
    failed_steps: list[dict[str, Any]] = []
    per_phase: dict[str, list[float]] = defaultdict(list)
    all_latency: list[float] = []
    slowest: list[dict[str, Any]] = []
    retried = 0
    turn_all: list[float] = []
    decision_all: list[float] = []

    for rec in records:
        game_id = rec.get("game_id")
        for s in rec.get("steps", []):
            if s.get("retry_count"):
                retried += 1

            if not s.get("skipped"):
                if s.get("turn_ms") is not None:
                    turn_all.append(s["turn_ms"])
                if s.get("decision_ms") is not None:
                    decision_all.append(s["decision_ms"])

            latency = s.get("latency_ms")
            if s.get("ui_action_executed") and latency is not None:
                per_phase[str(s.get("phase"))].append(latency)
                all_latency.append(latency)
                slowest.append({
                    "game_id": game_id, "index": s.get("index"), "phase": s.get("phase"),
                    "action_id": s.get("action_id"), "latency_ms": latency,
                })

            if not s.get("success") and not s.get("skipped"):
                error = s.get("error") or "UNKNOWN"
                by_error[error] += 1
                by_phase_error[f"{s.get('phase')}:{error}"] += 1
                failed_steps.append({
                    "game_id": game_id, "index": s.get("index"), "phase": s.get("phase"),
                    "action_id": s.get("action_id"), "error": error, "attempt": s.get("attempt"),
                    "ui_action_executed": s.get("ui_action_executed"),
                    "retry_count": s.get("retry_count"),
                })

    slowest.sort(key=lambda x: x["latency_ms"], reverse=True)
    overall = latency_stats(all_latency)
    have_records = {r.get("game_id") for r in records}

    return {
        "batch_id": batch.get("batch_id"),
        "games": len(rows),
        "bad_games": bad_games,
        "missing_records": [r.get("game_id") for r in rows if r.get("game_id") not in have_records],
        "error_counts": dict(by_error),
        "phase_error_counts": dict(by_phase_error),
        "failed_steps": failed_steps,
        "retried_steps": retried,
        "latency": {
            "all": overall,
            "by_phase": {k: latency_stats(v) for k, v in sorted(per_phase.items())},
            "turn": latency_stats(turn_all),
            "decision": latency_stats(decision_all),
        },
        "slowest": slowest[:5],
        "p95_budget_ms": TARGET_P95_MS,
        "p95_ok": None if overall["p95"] is None else overall["p95"] <= TARGET_P95_MS,
    }


def _ms(value: Any) -> str:
    return "-" if value is None else f"{value:.0f}"


def format_analysis(result: Mapping[str, Any]) -> str:
    lines = [f"===== 批次 {result['batch_id']}：{result['games']} 局 ====="]

    bad = result["bad_games"]
    lines.append(f"沒有無介入完成的局：{len(bad)} 局")
    for g in bad:
        lines.append(
            f"  - {g['game_id']} seed={g['seed']} finished={g['finished']} reason={g['reason']} "
            f"介入={g['interventions']} 錯誤碼={g['error_codes']}"
        )

    lines.append(f"失敗步驟：{len(result['failed_steps'])} 筆；重試過的步驟：{result['retried_steps']} 筆")
    for key, n in sorted(result["phase_error_counts"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {key}：{n}")
    for s in result["failed_steps"][:20]:
        lines.append(
            f"  · {s['game_id']} #{s['index']} {s['phase']} {s['action_id']} {s['error']} "
            f"attempt={s['attempt']} 已點擊={s['ui_action_executed']} 重試={s['retry_count']}"
        )

    lat = result["latency"]
    lines.append("UI 動作 latency（ms）：")
    lines.append(f"  {'階段':<10}{'n':>6}{'平均':>8}{'p50':>8}{'p95':>8}{'最大':>8}")
    for name, st in [("全部", lat["all"]), *lat["by_phase"].items()]:
        lines.append(f"  {name:<10}{st['n']:>6}{_ms(st['mean']):>8}{_ms(st['p50']):>8}{_ms(st['p95']):>8}{_ms(st['max']):>8}")
    verdict = {None: "沒有資料", True: "✅ 達標", False: "❌ 未達標"}[result["p95_ok"]]
    lines.append(f"p95 預算 {result['p95_budget_ms']:.0f} ms：{verdict}")
    for key, title in (("turn", "整個回合（重拍＋決策＋點擊＋驗證）"), ("decision", "其中策略決策")):
        st = lat.get(key) or {"n": 0}
        if st["n"]:
            lines.append(f"{title}：n={st['n']} 平均 {_ms(st['mean'])}、p95 {_ms(st['p95'])}、最大 {_ms(st['max'])} ms")

    if result["slowest"]:
        lines.append("最慢的動作：")
        for s in result["slowest"]:
            lines.append(f"  {s['latency_ms']:.0f} ms  {s['game_id']} #{s['index']} {s['phase']} {s['action_id']}")

    if result["missing_records"]:
        lines.append(f"找不到 .game.json 的局（沒跑起來或檔案被刪）：{result['missing_records']}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="批次失敗分析與延遲整理")
    parser.add_argument("log_dir", nargs="?", default="logs")
    parser.add_argument("--batch", nargs="*", default=None, help="batch_id（可多個）；不給就用最新一批")
    parser.add_argument("--out", default=None, help="把結果另存成文字檔")
    args = parser.parse_args(argv)

    batch_ids = args.batch
    if not batch_ids:
        latest = list_reports(args.log_dir, limit=1)
        if not latest:
            print(f"❌ {args.log_dir} 裡沒有 *.batch.json，請先跑 run_batch")
            return 1
        batch_ids = [latest[0]["batch_id"]]

    texts: list[str] = []
    for batch_id in batch_ids:
        path = Path(args.log_dir) / f"{batch_id}.batch.json"
        try:
            batch = load_report(path)
        except (OSError, ValueError) as exc:
            print(f"❌ 讀不到 {path}：{exc}")
            return 1
        texts.append(format_analysis(analyze(batch, load_game_records(args.log_dir, batch_id))))

    output = "\n\n".join(texts)
    print(output)
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(output + "\n", encoding="utf-8")
        print(f"\n已儲存：{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())