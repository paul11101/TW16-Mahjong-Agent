"""W7 批次實機：連續打 N 局（每局新牌局、新 controller），統計無介入完成率、操作成功率、重複點擊、p95。

事前準備：
    .\\start_game.ps1 會一次跑一局；批次請手動：
    uvicorn test_interface.app:app
    瀏覽器開 http://127.0.0.1:8000/?scenario=game（Ctrl+F5，不要最小化、不要被擋住），再執行：
    python -m test_interface.run_batch --delay 3 --games 5
    python -m test_interface.run_batch --delay 3 --games 20 --seed-start 100

每打完一局就存一次 logs/<batch_id>.batch.json，中途當機也留得住；Ctrl+Alt+S 停止會結束整批。
儀表板：http://127.0.0.1:8000/dashboard
"""

from __future__ import annotations

import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from src.control.batch import aggregate, failed_start_row, format_report, save_report
from test_interface.live_common import open_session
from test_interface.live_game import build_parser, play_game, post_new_game


def build_batch_parser():
    parser = build_parser()
    parser.add_argument("--games", type=int, default=5, help="要打幾局")
    parser.add_argument("--seed-start", type=int, default=None, help="第一局的種子（之後每局 +1；預設用 --seed）")
    parser.add_argument("--batch-id", default=None)
    parser.add_argument("--gap", type=float, default=1.0, help="兩局之間等待秒數")
    return parser


def main() -> int:
    args = build_batch_parser().parse_args()
    if args.games < 1:
        print("❌ --games 至少為 1")
        return 1

    session = open_session(args, page_hint="/?scenario=game")
    if session is None:
        return 1

    batch_id = args.batch_id or "w7_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    seed_start = args.seed_start if args.seed_start is not None else args.seed
    report_path = Path(args.log_dir) / f"{batch_id}.batch.json"
    rows: list[dict] = []
    report = None

    for i in range(args.games):
        seed = seed_start + i
        game_id = f"{batch_id}_g{i + 1:02d}"
        print(f"\n===== 第 {i + 1}/{args.games} 局（seed {seed}）=====")

        try:
            post_new_game(args.url, seed)
            outcome = play_game(args, session, game_id=game_id)
        except (urllib.error.URLError, OSError, RuntimeError) as exc:
            print(f"❌ 這一局沒有跑起來：{exc}")
            rows.append(failed_start_row(game_id, seed, "START_FAILED"))
            report = aggregate(batch_id, rows, requested=args.games)
            save_report(report_path, report)
            print(f"⚠️ 只跑了 {i + 1}/{args.games} 局就中止（沒跑的局不計入）")
            break

        rows.append(outcome.to_row(seed))
        report = aggregate(batch_id, rows, requested=args.games)
        save_report(report_path, report)

        s = outcome.summary
        print(f"→ 第 {i + 1} 局：{'✅ 無介入完成' if outcome.unattended_ok else '❌ 有介入或未完成'}"
              f"（reason={s.reason} 介入 {s.interventions} UI {s.ui_success}/{s.ui_actions} 多餘點擊 {s.extra_clicks}）")

        if s.reason == "stopped":
            print(f"⏹ 已被手動停止，結束整批（{i + 1}/{args.games} 局）")
            break
        if i + 1 < args.games:
            time.sleep(args.gap)

    print("\n" + "=" * 60)
    print(format_report(report))
    print(f"報表：{report_path}")
    return 0 if report.unattended_games == report.games == args.games else 1


if __name__ == "__main__":
    raise SystemExit(main())