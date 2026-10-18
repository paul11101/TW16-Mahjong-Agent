"""W5 實機：測試網頁 + 熱鍵 + 狀態檢查 + 重拍 + 監督者（暫停／停止／恢復）。

每個回合：重拍手牌（DOM 牌框，與規則狀態比對）-> 通過才出牌（點一張不同的牌）-> 畫面驗證。
第 N 回合點牌 N（依序 0, 1, 2...），所以每回合都是新的牌，不用每回合重設網頁。

事前準備（兩個 PowerShell 視窗，專案根目錄）：
    uvicorn test_interface.app:app --reload
瀏覽器開 http://127.0.0.1:8000（不要最小化、不要被擋住），**先按網頁「重設」**，再執行。

情境（回合編號從 0 起算）：
    # 1. 正常跑 3 回合（回合間隔 1 秒，方便手動按熱鍵）
    python -m test_interface.run_w5_live --delay 3
    # 2. 手動暫停／繼續／停止：跑的時候按 Ctrl+Alt+P 暫停、Ctrl+Alt+R 繼續、Ctrl+Alt+S 停止
    python -m test_interface.run_w5_live --delay 3 --turns 6 --turn-delay 2
    # 3. 狀態不一致：第 1 回合第一次檢查故意用錯的手牌 -> 自動暫停，3 秒後自動繼續
    python -m test_interface.run_w5_live --delay 3 --corrupt-turn 1 --auto-resume 3
    # 4. 低信心：第 1 回合第一次辨識有一張牌信心 0.3 -> 重拍後通過
    python -m test_interface.run_w5_live --delay 3 --low-conf-turn 1
    # 5. 中途停止後恢復：跑的時候按 Ctrl+Alt+S，再用 --resume 接著跑（網頁不要重設）
    python -m test_interface.run_w5_live --delay 3 --turns 6 --turn-delay 2
    python -m test_interface.run_w5_live --delay 3 --turns 6 --resume

安全：視窗不在前景不點、手牌不一致不點、滑鼠移到螢幕左上角可觸發 PyAutoGUI failsafe。
"""

from __future__ import annotations

import argparse
import dataclasses
import time
import urllib.error
from datetime import datetime, timezone

from src.common.logger import AppLogger
from src.control.controller import AgentController
from src.control.errors import ERR_LOW_CONFIDENCE, ERR_STATE_MISMATCH
from src.control.hotkeys import DEFAULT_BINDINGS, HotkeyWatcher
from src.control.pipeline import EventIds, TurnResult, run_discard_turn
from src.control.refresh import log_refresh_result, refresh_hand
from src.control.replay import check_order, load_events, summarize
from src.control.state_guard import StateGuard
from src.control.supervisor import RunSupervisor, start_index_from_checkpoint
from src.control.tile_mapper import TileMapper, boxes_from_dom_layout, find_calibration_marker
from test_interface.agent_runner import SEAT, make_fake_game_state
from test_interface.live_common import (
    add_action_args,
    add_common_args,
    fetch_clicks,
    fetch_layout,
    make_mouse,
    make_verifier_and_retry,
    open_session,
    print_receipt,
)
from test_interface.scripted_policy import ScriptedPolicy


def main() -> int:
    parser = argparse.ArgumentParser(description="W5 實機：監督者 + 狀態檢查 + 重拍 + 熱鍵")
    add_common_args(parser)
    add_action_args(parser)
    parser.add_argument("--turns", type=int, default=3, help="回合數（每回合點不同的牌）")
    parser.add_argument("--turn-delay", type=float, default=1.0, help="每回合開始前等待秒數（方便按熱鍵）")
    parser.add_argument("--corrupt-turn", type=int, default=None, help="這個回合第一次檢查故意用錯的手牌")
    parser.add_argument("--low-conf-turn", type=int, default=None, help="這個回合第一次辨識故意降低一張牌的信心")
    parser.add_argument("--auto-resume", type=float, default=0.0, help="暫停多少秒後自動繼續（0 = 只靠熱鍵）")
    parser.add_argument("--pause-timeout", type=float, default=60.0, help="暫停超過幾秒就停止")
    parser.add_argument("--refresh-attempts", type=int, default=3)
    parser.add_argument("--checkpoint", default="logs/w5_live.checkpoint.json")
    parser.add_argument("--resume", action="store_true", help="從 checkpoint 接著跑")
    parser.add_argument("--no-hotkeys", action="store_true")
    args = parser.parse_args()

    session = open_session(args)
    if session is None:
        return 1

    try:
        layout = fetch_layout(args.url)
        clicks_before = len(fetch_clicks(args.url))
    except (urllib.error.URLError, OSError) as exc:
        print(f"❌ 讀不到測試介面：{exc}")
        return 1
    if not layout.get("tiles"):
        print("❌ 網頁還沒回報牌框，請確認瀏覽器已載入首頁（Ctrl+F5）")
        return 1

    game_id = "w5_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    state = make_fake_game_state(game_id)
    hand = list(state.players[SEAT].hand)
    tiles = sorted(set(hand))[: args.turns]
    if len(tiles) < args.turns:
        print(f"❌ 手牌只有 {len(tiles)} 種牌，--turns 不能超過")
        return 1

    start_at = start_index_from_checkpoint(args.checkpoint) if args.resume else 0
    print(f"回合：{args.turns}，從第 {start_at} 回合開始；點的牌 {tiles}")
    if args.resume and start_at == 0:
        print("（沒有可接續的 checkpoint，從頭開始）")

    summary = None
    with AppLogger(log_dir=args.log_dir, game_id=game_id) as logger:
        ids = EventIds()
        controller = AgentController(
            game_id=game_id, mouse=make_mouse(), capturer=session.capturer, logger=logger
        )
        controller.start()
        verifier, retry = make_verifier_and_retry(args, controller, session)
        mapper = TileMapper(frame_size=(session.width, session.height))
        guard = StateGuard(controller, game_id=game_id, next_event_id=ids.next, logger=logger)

        current = {"turn": 0}
        once = {"corrupt": args.corrupt_turn, "low": args.low_conf_turn}

        def boxes_fn(frame):
            fresh = fetch_layout(args.url)
            marker = find_calibration_marker(frame)
            origin = (marker[0], marker[1]) if marker is not None else None
            boxes = boxes_from_dom_layout(fresh, seat=SEAT, zone="hand", origin_px=origin)
            if once["low"] == current["turn"] and boxes:
                once["low"] = None  # 只降低第一次
                boxes[0] = dataclasses.replace(boxes[0], confidence=0.3)
            return boxes

        def make_turn(index: int, tile: int):
            def turn() -> TurnResult:
                current["turn"] = index
                time.sleep(args.turn_delay)

                expected = list(hand)
                if once["corrupt"] == index:
                    once["corrupt"] = None  # 只錯第一次
                    expected = expected + [7]

                result = refresh_hand(
                    controller.capture, boxes_fn, expected, mapper=mapper,
                    max_attempts=args.refresh_attempts, retry_delay=0.2,
                )
                log_refresh_result(logger, game_id, ids.next(), result)
                for entry in result.attempt_log:
                    print(f"  [回合 {index}] 重拍 {entry}")

                if not result.ok:
                    if result.check is not None and not result.check.ok:
                        guard.verify([b.tile for b in result.boxes], expected,
                                     context={"turn": index, "error": result.error})
                    controller.pause()
                    print(f"⏸ 回合 {index} 暫停：{result.error}（Ctrl+Alt+R 繼續）")
                    return TurnResult(legal_count=0, error=result.error or ERR_STATE_MISMATCH)

                return run_discard_turn(
                    state, SEAT, mapper, session.region, controller,
                    game_id=game_id, ids=ids, logger=logger,
                    policy=ScriptedPolicy(f"discard_{tile}"),
                    foreground_check=session.locator.is_foreground,
                    verifier=verifier, retry=retry,
                )

            return turn

        paused_for = {"t": 0.0}

        def sleep(seconds: float) -> None:
            time.sleep(seconds)
            if controller.is_paused and args.auto_resume > 0:
                paused_for["t"] += seconds
                if paused_for["t"] >= args.auto_resume:
                    paused_for["t"] = 0.0
                    print("▶ 自動繼續")
                    controller.resume()
            else:
                paused_for["t"] = 0.0

        supervisor = RunSupervisor(
            controller, game_id=game_id, checkpoint_path=args.checkpoint,
            logger=logger, next_event_id=ids.next, pause_timeout=args.pause_timeout, sleep=sleep,
        )
        turns = [make_turn(i, t) for i, t in enumerate(tiles)]

        watcher = None if args.no_hotkeys else HotkeyWatcher(
            controller, on_trigger=lambda name: print(f"⌨ 熱鍵：{name}")
        )
        if watcher is not None:
            keys = {k: "+".join(v).upper() for k, v in DEFAULT_BINDINGS.items()}
            print(f"熱鍵：暫停 {keys['pause']}、繼續 {keys['resume']}、停止 {keys['stop']}")
            watcher.start()
        try:
            summary = supervisor.run(turns, start_at=start_at)
        finally:
            if watcher is not None:
                watcher.close()
            controller.stop()

    # ---- 結果
    print()
    for i, result in enumerate(summary.results):
        if result.receipt is not None:
            print(f"[結果 {i}] ", end="")
            print_receipt(result.receipt, None)
        else:
            print(f"[結果 {i}] 沒有回執：error={result.error}")
    if verifier is not None and verifier.history:
        print(f"驗證次數 {len(verifier.history)}，最後一次：{verifier.history[-1].describe()}")

    print(
        f"\n監督者：finished={summary.finished} reason={summary.reason} next_turn={summary.next_turn} "
        f"completed={summary.completed} failed={summary.failed} skipped={summary.skipped}"
    )

    expected_clicks = sum(
        (1 + r.receipt.retry_count) for r in summary.results
        if r.receipt is not None and r.receipt.ui_action_executed
    )
    time.sleep(0.5)
    new_clicks = fetch_clicks(args.url)[clicks_before:]
    page_ack = len(new_clicks) == expected_clicks
    print(f"網頁收到點擊 {len(new_clicks)} 次（預期 {expected_clicks}）：{[c.get('tile') for c in new_clicks]}")

    log_path = f"{args.log_dir}/{game_id}.jsonl"
    events = load_events(log_path)
    replay = summarize(events)
    problems = check_order(events)
    print(f"JSONL：{log_path}（{replay.total_events} 筆，暫停 {replay.pauses}、繼續 {replay.resumes}、"
          f"狀態不一致 {replay.mismatches}、停止 {replay.stops}）")
    print("順序檢查：" + ("通過" if not problems else f"{len(problems)} 項問題 {problems[:3]}"))
    print(f"checkpoint：{args.checkpoint}")

    if not summary.finished:
        print("⏹ 沒有跑完；要接著跑請加 --resume（網頁不要重設）")
    if page_ack and not problems:
        print("✅ W5 實機流程完成" if summary.finished else "✅ 已停止（網頁點擊數與回執一致）")
        return 0
    print("❌ 網頁點擊數與回執不一致或事件順序有問題，請看上方輸出")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())