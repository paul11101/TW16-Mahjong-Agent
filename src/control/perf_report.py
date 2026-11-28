"""W10 D5：整合性能報告（只讀 logs，輸出 Markdown）。

    python -m src.control.perf_report --batch w10_base w10_bc_v1 --out docs\\integration\\w10_perf_report.md
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from src.control.batch import batch_strategy_version, load_report
from src.control.failure_analysis import analyze, load_game_records

DECISION_BUDGET_MS = 300.0
ACTION_BUDGET_MS = 2000.0
DEFAULT_DECISION_JSON = "data/processed/decision_latency_model.json"


def _ms(value: Any) -> str:
    return "-" if value is None else f"{value:.0f}"


def _ms2(value: Any) -> str:
    return "-" if value is None else f"{value:.2f}"


def _pct(value: Any) -> str:
    return "-" if value is None else f"{value:.2%}"


def build_report(log_dir: str | Path, batch_ids: Sequence[str], *, decision_json: str | Path | None = None) -> str:
    items = []
    for batch_id in batch_ids:
        batch = load_report(Path(log_dir) / f"{batch_id}.batch.json")
        analysis = analyze(batch, load_game_records(log_dir, batch_id))
        items.append((batch_id, batch, analysis, batch_strategy_version(log_dir, batch_id)))

    lines = [
        "# W10 整合性能報告",
        "",
        f"產生日期：{datetime.now():%Y-%m-%d}　資料來源：自製測試網頁（不是正式遊戲），預算依企劃書",
        "",
        "## 1. 批次總覽",
        "",
        "| 批次 | 策略 | 局數 | 無介入 | UI 動作 | 成功率 | 多餘點擊 | 重試 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for batch_id, batch, _, version in items:
        lines.append(
            f"| {batch_id} | {version or '未記錄'} | {batch.get('games')} | "
            f"{batch.get('unattended_games')}/{batch.get('games')} | {batch.get('ui_actions')} | "
            f"{_pct(batch.get('ui_success_rate'))} | {batch.get('extra_clicks')} | {batch.get('retries')} |"
        )

    lines += [
        "",
        f"## 2. 延遲（ms；UI 動作預算 p95 ≤ {ACTION_BUDGET_MS:.0f}、策略決策預算 ≤ {DECISION_BUDGET_MS:.0f}）",
        "",
        "| 批次 | 項目 | n | 平均 | p95 | 最大 | 預算 |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for batch_id, _, analysis, _ in items:
        lat = analysis["latency"]
        rows = [
            ("UI 動作（點擊＋驗證）", lat["all"], ACTION_BUDGET_MS),
            *[(f"　{name}", st, None) for name, st in lat["by_phase"].items()],
            ("整個回合", lat.get("turn") or {"n": 0}, None),
            ("策略決策", lat.get("decision") or {"n": 0}, DECISION_BUDGET_MS),
        ]
        for title, st, budget in rows:
            if not st["n"]:
                continue
            verdict = "" if budget is None else ("✅" if st["p95"] <= budget else "❌")
            lines.append(
                f"| {batch_id} | {title} | {st['n']} | {_ms2(st['mean'])} | {_ms2(st['p95'])} | {_ms(st['max'])} | {verdict} |"
            )

    lines += ["", "## 3. 失敗與介入", ""]
    for batch_id, _, analysis, _ in items:
        lines.append(
            f"- {batch_id}：沒有無介入完成的局 {len(analysis['bad_games'])} 局、失敗步驟 {len(analysis['failed_steps'])} 筆、"
            f"重試過的步驟 {analysis['retried_steps']} 筆；錯誤碼 {analysis['error_counts'] or '無'}"
        )

    if decision_json and Path(decision_json).is_file():
        try:
            data = json.loads(Path(decision_json).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if data:
            lines += ["", "## 4. 離線決策耗時（measure_decision）", "", "| 策略／模式 | 類型 | n | 平均 | p95 | 最大 |", "|---|---|---:|---:|---:|---:|"]
            for label, stats in data.items():
                for key, s in stats.items():
                    lines.append(f"| {label} | {key} | {int(s['n'])} | {s['mean']:.2f} | {s['p95']:.2f} | {s['max']:.2f} |")

    lines += [
        "",
        "## 5. 解讀注意",
        "",
        "- 同一組 seed 的兩批才能比較；W9／W10 的整合驗證批次不計入 W14 的 ≥ 1,000 次 UI 動作分母。",
        "- 牌力（胡牌率、放槍率）以策略端的 1,000 局評測為準；這裡的胡牌／流局只作整合驗證參考。",
        "- 真實遊戲（愛台灣打麻將）的延遲要另外量，測試網頁沒有辨識時間。",
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="整合性能報告（Markdown）")
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--batch", nargs="+", required=True)
    parser.add_argument("--decision-json", default=DEFAULT_DECISION_JSON)
    parser.add_argument("--out", default="docs/integration/w10_perf_report.md")
    args = parser.parse_args(argv)

    try:
        text = build_report(args.log_dir, args.batch, decision_json=args.decision_json)
    except (OSError, ValueError) as exc:
        print(f"❌ 讀不到批次報表：{exc}")
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"✅ 已輸出：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())