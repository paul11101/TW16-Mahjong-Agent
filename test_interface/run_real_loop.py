"""正式遊戲（愛台灣打麻將）連續出牌：依畫面出牌，反應回合可點胡或取消。

事前準備（同 run_real_game）：桌面版遊戲固定視窗、手動模式、不要最小化或被擋住；
遊戲若以系統管理員執行，PowerShell 也要用系統管理員。

用法（專案根目錄）：
    python -m test_interface.run_real_loop --delay 3
    python -m test_interface.run_real_loop --delay 3 --max-steps 5          # 最多 5 次動作
    python -m test_interface.run_real_loop --delay 3 --no-confirm           # 省一次辨識，較快

目前限制：
- 吃、碰、槓與副露選牌目前由玩家操作。
- 點擊驗證逾時時，將最近一次觀察與暫停畫面存到日誌資料夾。
- 熱鍵：Ctrl+Alt+P 暫停、Ctrl+Alt+R 繼續、Ctrl+Alt+S 停止；滑鼠移到螢幕左上角觸發 failsafe。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from src.common.logger import AppLogger
from src.control.errors import ERR_ACTION_TIMEOUT
from src.control.game_profile import ITAIWANMJ16
from src.control.game_runner import GameRunner, PHASE_REACTION
from src.control.hotkeys import DEFAULT_BINDINGS, HotkeyWatcher
from src.control.mouse import CountingMouse, MouseController, RepeatClickMouse
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
    parser.add_argument("--click-gap", type=float, default=0.25)
    parser.add_argument("--hover-delay", type=float, default=0.15,
                        help="移動到牌上後，等幾秒讓遊戲收到 hover 再點擊（0 = 不等）")
    parser.add_argument("--no-confirm", action="store_true", help="不做第二次辨識確認（較快、較不保險）")
    parser.add_argument("--no-react", action="store_true", help="不點反應按鈕（舊行為：一律略過）")
    parser.add_argument("--refresh-attempts", type=int, default=3)
    parser.add_argument("--max-steps", type=int, default=40, help="最多執行幾次動作（含反應）")
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
    raw_mouse = MouseController(duration=args.move_duration, hover_delay=args.hover_delay)
    raw_mouse.warmup()
    repeat_mouse = RepeatClickMouse(raw_mouse, args.clicks, gap=args.click_gap)
    mouse = CountingMouse(repeat_mouse)

    with AppLogger(log_dir=args.log_dir, game_id=game_id) as logger:
        ids = EventIds()
        with controller_session(args, game_id, session, logger=logger, mouse=mouse) as (
            controller, verifier, retry,
        ):
            mapper = TileMapper(frame_size=(session.width, session.height))
            guard = StateGuard(controller, game_id=game_id, next_event_id=ids.next, logger=logger)
            last_observed_frame = None

            def capture_for_observation():
                """保留最近一次辨識的原始畫面，供逾時前後比對。"""
                nonlocal last_observed_frame
                last_observed_frame = controller.capture()
                return last_observed_frame

            observer = VisionObserver(capture_for_observation, vision)
            turns = make_vision_turns(
                controller, vision, mapper, guard, session.region,
                game_id=game_id, ids=ids, logger=logger,
                policy=ActionPolicy(include_candidate_scores=False),
                foreground_check=session.locator.is_foreground,
                verifier=verifier, retry=retry,
                confirm=not args.no_confirm, min_confidence=args.min_conf,
                refresh_attempts=args.refresh_attempts,
                click_reactions=not args.no_react,
                debug_dir=args.log_dir,
            )
            react = turns[PHASE_REACTION]

            def react_once(snap):
                """反應按鈕一律單點，避免第二下落在剛變化的畫面。"""
                repeat_mouse.times = 1
                try:
                    return react(snap)
                finally:
                    repeat_mouse.times = args.clicks

            turns[PHASE_REACTION] = react_once
            pause_count = 0

            def on_pause(error):
                """儲存暫停畫面，出牌或反應逾時時也保留先前的觀察畫面。"""
                import cv2
                import numpy as np

                nonlocal pause_count
                pause_count += 1
                prefix = Path(args.log_dir) / f"{game_id}_pause_{pause_count}_{error or 'pause'}"
                frame = controller.capture()
                if frame is None:
                    return
                image = np.ascontiguousarray(frame).copy()
                for b in mapper.boxes:
                    cv2.rectangle(image, (b.x, b.y), (b.x + b.w, b.y + b.h), (0, 255, 0), 2)
                if mouse.points:
                    sx, sy = mouse.points[-1]
                    cv2.circle(image, (sx - session.region.left, sy - session.region.top), 14, (0, 0, 255), 3)
                images = [(prefix.with_suffix(".png"), image)]
                if error == ERR_ACTION_TIMEOUT and last_observed_frame is not None:
                    images.append((prefix.with_name(f"{prefix.name}_before.png"), last_observed_frame))
                for path, screenshot in images:
                    encoded, png = cv2.imencode(".png", screenshot)
                    if not encoded:
                        raise OSError(f"無法編碼暫停畫面：{path}")
                    path.write_bytes(png.tobytes())
                    print(f"📷 已存畫面：{path}")

            runner = GameRunner(
                controller, game_id=game_id,
                observe_fn=observer.snapshot, turn_fns=turns,
                logger=logger, next_event_id=ids.next, record_path=record_path,
                poll_interval=args.poll, advance_timeout=args.advance_timeout,
                idle_timeout=args.idle_timeout or None, pause_timeout=args.pause_timeout,
                max_steps=args.max_steps, on_pause=on_pause,
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
    print(f"點擊動作 {s.physical_clicks} 次（出牌 {args.clicks} 下、反應 1 下），多餘動作 {s.extra_clicks} 次")
    if s.error_codes:
        print(f"錯誤碼：{s.error_codes}")
    if s.latencies_ms:
        print("每次動作 latency(ms)：" + ", ".join(f"{v:.0f}" for v in s.latencies_ms))
    if s.latency_p95_ms is not None:
        print(f"latency p95：{s.latency_p95_ms:.0f} ms（樣本 {len(s.latencies_ms)}，企劃書要求 ≤ 2000）")
    print(f"JSONL：{args.log_dir}/{game_id}.jsonl")
    print(f"可回放紀錄：{record_path}")
    print(f"  查看：python -m src.control.game_runner {record_path}")
    return 0 if s.finished and s.interventions == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())