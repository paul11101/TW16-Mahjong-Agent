"""正式遊戲（愛台灣打麻將）連續出牌：只靠畫面判斷「輪到我」，自己回合就出牌，直到結算畫面或停止。

事前準備（同 run_real_game）：桌面版遊戲固定視窗、手動模式、不要最小化或被擋住；
遊戲若以系統管理員執行，PowerShell 也要用系統管理員。

用法（專案根目錄）：
    python -m test_interface.run_real_loop --delay 3
    python -m test_interface.run_real_loop --delay 3 --max-steps 5          # 只打 5 張，先小量試
    python -m test_interface.run_real_loop --delay 3 --no-confirm           # 省一次辨識，較快

目前限制：
- 只處理出牌。吃碰槓胡過的按鈕沒有偵測，一律不動作（遊戲會等它自己逾時）。
- 自摸胡牌不會胡（會照常出牌）。
- 熱鍵：Ctrl+Alt+P 暫停、Ctrl+Alt+R 繼續、Ctrl+Alt+S 停止；滑鼠移到螢幕左上角觸發 failsafe。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from src.common.logger import AppLogger
from src.control.game_profile import ITAIWANMJ16
from src.control.game_runner import GameRunner
from src.control.hotkeys import DEFAULT_BINDINGS, HotkeyWatcher
from src.control.pipeline import EventIds
from src.control.state_guard import StateGuard
from src.control.tile_mapper import TileMapper
from src.control.vision_adapter import DetectorVision, VisionObserver
from src.control.vision_turns import make_vision_turns
from src.perception.detector import MahjongDetector
from src.strategy.action_policy import ActionPolicy
from test_interface.live_common import (
    add_action_args,
    add_common_args,
    controller_session,
    make_mouse,
    open_session,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="正式遊戲連續出牌")
    add_common_args(parser)
    add_action_args(parser)
    parser.set_defaults(title=ITAIWANMJ16.title_contains, max_retries=0)
    parser.add_argument("--templates", default="data/samples")
    parser.add_argument("--min-conf", type=float, default=0.6)
    parser.add_argument("--move-duration", type=float, default=0.0)
    parser.add_argument("--clicks", type=int, default=ITAIWANMJ16.discard_clicks, choices=(1, 2))
    parser.add_argument("--click-gap", type=float, default=0.1)
    parser.add_argument("--no-confirm", action="store_true", help="不做第二次辨識確認（較快、較不保險）")
    parser.add_argument("--refresh-attempts", type=int, default=3)
    parser.add_argument("--max-steps", type=int, default=40, help="最多出幾張牌（防止無限迴圈）")
    parser.add_argument("--poll", type=float, default=0.3, help="觀察間隔秒數")
    parser.add_argument("--advance-timeout", type=float, default=8.0, help="出牌後畫面多久沒前進就暫停")
    parser.add_argument("--idle-timeout", type=float, default=90.0, help="多久沒輪到自己就暫停（0 = 不限）")
    parser.add_argument("--pause-timeout", type=float, default=120.0)
    parser.add_argument("--no-hotkeys", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    session = open_session(args)
    if session is None:
        return 1

    game_id = "realloop_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    record_path = f"{args.log_dir}/{game_id}.game.json"
    vision = DetectorVision(MahjongDetector(template_dir=args.templates))
    mouse = make_mouse(duration=args.move_duration, clicks=args.clicks, gap=args.click_gap)

    with AppLogger(log_dir=args.log_dir, game_id=game_id) as logger:
        ids = EventIds()
        with controller_session(args, game_id, session, logger=logger, mouse=mouse) as (
            controller, verifier, retry,
        ):
            mapper = TileMapper(frame_size=(session.width, session.height))
            guard = StateGuard(controller, game_id=game_id, next_event_id=ids.next, logger=logger)
            observer = VisionObserver(controller.capture, vision)
            turns = make_vision_turns(
                controller, vision, mapper, guard, session.region,
                game_id=game_id, ids=ids, logger=logger,
                policy=ActionPolicy(include_candidate_scores=False),
                foreground_check=session.locator.is_foreground,
                verifier=verifier, retry=retry,
                confirm=not args.no_confirm, min_confidence=args.min_conf,
                refresh_attempts=args.refresh_attempts,
            )
            runner = GameRunner(
                controller, game_id=game_id,
                observe_fn=observer.snapshot, turn_fns=turns,
                logger=logger, next_event_id=ids.next, record_path=record_path,
                poll_interval=args.poll, advance_timeout=args.advance_timeout,
                idle_timeout=args.idle_timeout or None, pause_timeout=args.pause_timeout,
                max_steps=args.max_steps,
            )

            watcher = None
            if not args.no_hotkeys:
                watcher = HotkeyWatcher(controller, on_trigger=lambda name: print(f"⌨ 熱鍵：{name}"))
                keys = {k: "+".join(v).upper() for k, v in DEFAULT_BINDINGS.items()}
                print(f"熱鍵：暫停 {keys['pause']}、繼續 {keys['resume']}、停止 {keys['stop']}")
                watcher.start()
            try:
                summary = runner.run()
            finally:
                if watcher is not None:
                    watcher.close()

    s = summary
    rate = "-" if s.ui_success_rate is None else f"{s.ui_success_rate:.1%}"
    print()
    print(f"牌局：finished={s.finished} reason={s.reason} 耗時 {s.duration_s:.1f}s")
    print(f"動作：完成 {s.completed}、略過 {s.skipped}、失敗 {s.failed}、人工介入 {s.interventions}")
    print(f"UI 動作 {s.ui_actions} 次，成功 {s.ui_success}（{rate}），畫面驗證通過 {s.verified_actions}")
    print(f"實際點擊 {s.physical_clicks} 次（每次出牌預期 {args.clicks} 下），多餘點擊 {s.extra_clicks} 次")
    if s.error_codes:
        print(f"錯誤碼：{s.error_codes}")
    if s.latencies_ms:
        print("每次出牌 latency(ms)：" + ", ".join(f"{v:.0f}" for v in s.latencies_ms))
    if s.latency_p95_ms is not None:
        print(f"latency p95：{s.latency_p95_ms:.0f} ms（樣本 {len(s.latencies_ms)}，企劃書要求 ≤ 2000）")
    print(f"JSONL：{args.log_dir}/{game_id}.jsonl")
    print(f"可回放紀錄：{record_path}")
    print(f"  查看：python -m src.control.game_runner {record_path}")
    return 0 if s.finished and s.interventions == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())