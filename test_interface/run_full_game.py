"""W6 實機：在測試網頁上自動打完「一整局」（真的移動滑鼠點擊）。

流程：每一輪重新觀察網頁 -> 判斷階段 -> 輪到自己就出牌／有反應按鈕就吃碰槓胡過 ->
      點擊 -> 畫面驗證 -> 等牌局前進 -> 直到牌局結束；全程寫 JSONL，並存成可回放的 .game.json。

事前準備：
    建議直接用專案根目錄的 start_game.ps1（一鍵啟動伺服器、開網頁、跑一局）。
    手動的話（兩個 PowerShell 視窗，專案根目錄）：
        uvicorn test_interface.app:app
    瀏覽器開 http://127.0.0.1:8000/?scenario=game（Ctrl+F5，不要最小化、不要被擋住），再執行：
        python -m test_interface.run_full_game --delay 3 --seed 1

安全：視窗不在前景不點、畫面與狀態不一致不點、已點擊卻沒確認不會自動重點（暫停等你處理）、
      Ctrl+Alt+P 暫停、Ctrl+Alt+R 繼續、Ctrl+Alt+S 停止、滑鼠移到螢幕左上角觸發 failsafe。
"""

from __future__ import annotations

import argparse
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from src.common.logger import AppLogger
from src.control.button_mapper import ButtonMapper, boxes_from_dom_buttons, boxes_from_dom_choices
from src.control.controller import AgentController
from src.control.game_runner import PHASE_MY_TURN, PHASE_REACTION, GameRunner
from src.control.hotkeys import DEFAULT_BINDINGS, HotkeyWatcher
from src.control.pipeline import EventIds, TurnResult, run_discard_turn, run_reaction_turn
from src.control.refresh import log_refresh_result, refresh_hand
from src.control.replay import check_order, load_events, summarize
from src.control.state_guard import StateGuard
from src.control.tile_mapper import TileMapper, find_calibration_marker
from src.strategy.action_policy import ActionPolicy
from test_interface.agent_runner import SEAT
from test_interface.live_common import (
    add_action_args,
    add_common_args,
    fetch_clicks,
    fetch_json,
    fetch_layout,
    make_mouse,
    make_verifier_and_retry,
    open_session,
)
from src.control.errors import ERR_LAYOUT_STALE
from test_interface.web_observer import WebObserver, fetch_fresh_layout, make_boxes_fn, state_from_view


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="W6 實機：自動打完一整局")
    add_common_args(parser)
    add_action_args(parser)
    parser.add_argument("--seed", type=int, default=1, help="牌局種子（同一個種子洗出同一副牌）")
    parser.add_argument("--keep-game", action="store_true", help="不要開新局，接著網頁現有的牌局打")
    parser.add_argument("--max-steps", type=int, default=300, help="最多執行幾次動作（防止無限迴圈）")
    parser.add_argument("--poll", type=float, default=0.2, help="觀察間隔秒數")
    parser.add_argument("--advance-timeout", type=float, default=5.0, help="動作後畫面多久沒前進就暫停")
    parser.add_argument("--idle-timeout", type=float, default=60.0, help="多久沒輪到自己就暫停（0 = 不限）")
    parser.add_argument("--pause-timeout", type=float, default=120.0, help="暫停超過幾秒就停止")
    parser.add_argument("--step-delay", type=float, default=0.3, help="吃／槓兩步驟點擊之間的等待秒數")
    parser.add_argument("--refresh-attempts", type=int, default=3)
    parser.add_argument("--no-hotkeys", action="store_true")
    return parser


def _post(base_url: str, path: str) -> None:
    request = urllib.request.Request(base_url.rstrip("/") + path, data=b"", method="POST")
    urllib.request.urlopen(request, timeout=3.0).read()


def main() -> int:
    args = build_parser().parse_args()

    if not args.keep_game:
        try:
            _post(args.url, f"/api/game/new?seed={args.seed}")
        except (urllib.error.URLError, OSError) as exc:
            print(f"❌ 連不到測試介面 {args.url}：{exc}（請先啟動 uvicorn）")
            return 1

    session = open_session(args, page_hint="/?scenario=game")
    if session is None:
        return 1

    # 等網頁載入整局畫面（要有自己的手牌牌框）
    for _ in range(25):
        try:
            tiles = fetch_layout(args.url).get("tiles", [])
        except (urllib.error.URLError, OSError):
            tiles = []
        if any(t.get("seat") == SEAT and t.get("zone") == "hand" for t in tiles):
            break
        time.sleep(0.2)
    else:
        print("❌ 網頁還沒回報手牌牌框：請確認瀏覽器開的是 /?scenario=game 並按 Ctrl+F5")
        return 1

    game_id = "w6_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    clicks_before = len(fetch_clicks(args.url))
    frame_size = (session.width, session.height)
    summary = None

    with AppLogger(log_dir=args.log_dir, game_id=game_id) as logger:
        ids = EventIds()
        controller = AgentController(
            game_id=game_id, mouse=make_mouse(), capturer=session.capturer, logger=logger
        )
        controller.start()
        verifier, retry = make_verifier_and_retry(args, controller, session)

        policy = ActionPolicy()
        tile_mapper = TileMapper(frame_size=frame_size)
        button_mapper = ButtonMapper(frame_size=frame_size)
        guard = StateGuard(controller, game_id=game_id, next_event_id=ids.next, logger=logger)
        observer = WebObserver(args.url, seat=SEAT)
        current = {"version": None}  # 這次觀察的牌桌版本；牌框要同一版才可以用
        boxes_fn = make_boxes_fn(args.url, seat=SEAT, version_fn=lambda: current["version"])

        def prepare(snap):
            """重拍手牌並與畫面狀態比對；通過回傳 (state, None)，失敗回傳 (None, TurnResult)。"""
            current["version"] = snap.data.get("version")
            state = state_from_view(game_id, snap.data, SEAT)
            expected = list(state.players[SEAT].hand)
            melds = len(state.players[SEAT].melds)

            result = refresh_hand(
                controller.capture, boxes_fn, expected, mapper=tile_mapper, meld_count=melds,
                max_attempts=args.refresh_attempts, retry_delay=0.2,
            )
            log_refresh_result(logger, game_id, ids.next(), result)
            if result.ok:
                return state, None

            if result.check is not None and not result.check.ok:
                guard.verify([b.tile for b in result.boxes], expected, meld_count=melds,
                             context={"phase": snap.phase, "error": result.error})
            controller.pause()
            print(f"⏸ 暫停：{result.error}（Ctrl+Alt+R 繼續）")
            return None, TurnResult(legal_count=0, error=result.error)

        def advanced_since(snap):
            """遊戲層級確認：重新觀察，畫面指紋已經不是這次的 -> 動作其實生效了（不要重複點擊）。"""

            def check() -> bool:
                now = observer.snapshot()
                return now is not None and now.fingerprint != snap.fingerprint

            return check

        def discard_turn(snap):
            state, failed = prepare(snap)
            if failed is not None:
                return failed
            return run_discard_turn(
                state, SEAT, tile_mapper, session.region, controller,
                game_id=game_id, ids=ids, logger=logger, policy=policy,
                foreground_check=session.locator.is_foreground, verifier=verifier, retry=retry,
                already_done=advanced_since(snap),
            )

        def reaction_turn(snap):
            state, failed = prepare(snap)
            if failed is not None:
                return failed

            layout = fetch_fresh_layout(args.url, current["version"])
            if layout is None:
                return TurnResult(legal_count=0, error=ERR_LAYOUT_STALE)
            frame = controller.capture()
            marker = find_calibration_marker(frame) if frame is not None else None
            origin = (marker[0], marker[1]) if marker is not None else None
            button_mapper.update(
                boxes_from_dom_buttons(layout, origin_px=origin),
                boxes_from_dom_choices(layout, origin_px=origin),
                frame_size=frame_size,
            )
            return run_reaction_turn(
                state, SEAT, button_mapper, session.region, controller,
                game_id=game_id, ids=ids, logger=logger, policy=policy,
                foreground_check=session.locator.is_foreground, step_delay=args.step_delay,
                verifier=verifier, retry=retry, already_done=advanced_since(snap),
            )

        runner = GameRunner(
            controller, game_id=game_id,
            observe_fn=observer.snapshot,
            turn_fns={PHASE_MY_TURN: discard_turn, PHASE_REACTION: reaction_turn},
            logger=logger, next_event_id=ids.next,
            record_path=f"{args.log_dir}/{game_id}.game.json",
            poll_interval=args.poll, advance_timeout=args.advance_timeout,
            idle_timeout=args.idle_timeout or None, pause_timeout=args.pause_timeout,
            max_steps=args.max_steps,
        )

        watcher = None if args.no_hotkeys else HotkeyWatcher(
            controller, on_trigger=lambda name: print(f"⌨ 熱鍵：{name}")
        )
        if watcher is not None:
            keys = {k: "+".join(v).upper() for k, v in DEFAULT_BINDINGS.items()}
            print(f"熱鍵：暫停 {keys['pause']}、繼續 {keys['resume']}、停止 {keys['stop']}")
            watcher.start()
        try:
            summary = runner.run()
        finally:
            if watcher is not None:
                watcher.close()
            controller.stop()

    # ---- 結果
    print()
    rate = "-" if summary.ui_success_rate is None else f"{summary.ui_success_rate:.1%}"
    print(f"牌局：finished={summary.finished} reason={summary.reason} 耗時 {summary.duration_s:.1f}s")
    print(f"動作：完成 {summary.completed}、略過 {summary.skipped}、失敗 {summary.failed}、人工介入 {summary.interventions}")
    print(f"UI 動作 {summary.ui_actions} 次，成功 {summary.ui_success}（{rate}），畫面驗證通過 {summary.verified_actions}，重試 {summary.retries}")
    if summary.error_codes:
        print(f"錯誤碼：{summary.error_codes}")
    if summary.latency_p95_ms is not None:
        print(f"latency p95：{summary.latency_p95_ms:.1f} ms")

    try:
        truth = fetch_json(args.url, "/api/game/state")
        print(f"評測器對照：牌局結束={truth['is_over']} 結果={truth['result']} 贏家={truth['winner']} 剩餘牌 {truth['wall_count']}")
        truth_ok = truth["is_over"] == summary.finished
    except (urllib.error.URLError, OSError, KeyError):
        truth_ok = True
        print("（讀不到評測器狀態，略過對照）")

    time.sleep(0.5)
    page_clicks = len(fetch_clicks(args.url)) - clicks_before
    print(f"網頁收到出牌點擊 {page_clicks} 次")

    log_path = f"{args.log_dir}/{game_id}.jsonl"
    events = load_events(log_path)
    replay = summarize(events)
    problems = check_order(events)
    print(f"JSONL：{log_path}（{replay.total_events} 筆）；順序檢查：" + ("通過" if not problems else f"{len(problems)} 項問題 {problems[:3]}"))
    print(f"可回放紀錄：{args.log_dir}/{game_id}.game.json")
    print(f"  查看：python -m src.control.game_runner {args.log_dir}\\{game_id}.game.json")

    if summary.unattended and truth_ok and not problems:
        print("✅ 整局無人工介入完成")
        return 0
    if summary.finished:
        print("⚠️ 牌局打完了，但有人工介入或檢查沒過，請看上方輸出")
        return 1
    print("❌ 牌局沒有打完，請看上方輸出與 JSONL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())