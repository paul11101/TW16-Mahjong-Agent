"""整局實機的共用流程（W7）：run_full_game（單局）與 run_batch（批次）都用這裡。

play_game() 打一局並回傳 GameOutcome；開新局（POST /api/game/new）由呼叫端負責。
"""

from __future__ import annotations

import argparse
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from src.common.logger import AppLogger
from src.control.button_mapper import ButtonMapper, boxes_from_dom_buttons, boxes_from_dom_choices
from src.control.errors import ERR_LAYOUT_STALE
from src.control.game_runner import PHASE_MY_TURN, PHASE_REACTION, GameRunner, GameRunSummary
from src.control.hotkeys import DEFAULT_BINDINGS, HotkeyWatcher
from src.control.pipeline import EventIds, TurnResult, run_discard_turn, run_reaction_turn
from src.control.replay import check_order, load_events, summarize
from src.control.state_guard import StateGuard
from src.control.tile_mapper import TileMapper, marker_origin
from src.control.turn_prep import prepare_turn
from src.strategy.action_policy import ActionPolicy
from test_interface.agent_runner import SEAT
from test_interface.live_common import (
    add_action_args,
    add_common_args,
    controller_session,
    fetch_clicks,
    fetch_json,
    fetch_reactions,
    make_mouse,
)
from test_interface.web_observer import (
    GAME_VIEW_PATH,
    WebObserver,
    fetch_fresh_layout,
    make_boxes_fn,
    state_from_view,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="整局實機（單局／批次共用參數）")
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


def post_new_game(base_url: str, seed: int) -> None:
    request = urllib.request.Request(
        base_url.rstrip("/") + f"/api/game/new?seed={seed}", data=b"", method="POST"
    )
    urllib.request.urlopen(request, timeout=3.0).read()


def wait_for_game_layout(base_url: str, *, timeout: float = 5.0) -> dict | None:
    """等網頁回報「和目前牌桌同一版」且有自己手牌的牌框；逾時回傳 None。

    開新局後網頁還保留上一局的牌框，所以要比對版本，不能只看有沒有手牌。
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            view = fetch_json(base_url, GAME_VIEW_PATH)
            layout = fetch_fresh_layout(base_url, view.get("version"), timeout=1.0)
            if layout is not None and any(
                t.get("seat") == SEAT and t.get("zone") == "hand" for t in layout.get("tiles", [])
            ):
                return layout
        except (OSError, ValueError):
            pass
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.2)


@dataclass
class GameOutcome:
    game_id: str
    summary: GameRunSummary
    truth: dict | None
    truth_ok: bool
    page_discards: int
    page_reactions: int
    mouse_clicks: int
    log_path: str
    record_path: str
    total_events: int
    order_problems: list[str] = field(default_factory=list)

    @property
    def page_match(self) -> bool:
        """網頁收到的點擊數 = 滑鼠實際點擊數（少了代表點到空白處，多了代表有重複）。"""
        return self.page_discards + self.page_reactions == self.mouse_clicks

    @property
    def unattended_ok(self) -> bool:
        return self.summary.unattended and self.truth_ok and not self.order_problems

    def to_row(self, seed: int | None = None) -> dict[str, Any]:
        row = self.summary.to_dict()
        row.update(
            seed=seed, truth_ok=self.truth_ok, order_ok=not self.order_problems,
            page_match=self.page_match, page_discards=self.page_discards,
            page_reactions=self.page_reactions,
        )
        return row


def play_game(args: argparse.Namespace, session: Any, *, game_id: str, hotkeys: bool = True) -> GameOutcome:
    """打完一局。網頁沒有準備好時拋 RuntimeError。"""
    if wait_for_game_layout(args.url) is None:
        raise RuntimeError("網頁還沒回報手牌牌框：請確認瀏覽器開的是 /?scenario=game 並按 Ctrl+F5")

    clicks_before = len(fetch_clicks(args.url))
    reactions_before = len(fetch_reactions(args.url))
    frame_size = (session.width, session.height)
    mouse = make_mouse()
    summary: GameRunSummary | None = None

    with AppLogger(log_dir=args.log_dir, game_id=game_id) as logger:
        ids = EventIds()
        with controller_session(args, game_id, session, logger=logger, mouse=mouse) as (
            controller, verifier, retry,
        ):
            policy = ActionPolicy()
            tile_mapper = TileMapper(frame_size=frame_size)
            button_mapper = ButtonMapper(frame_size=frame_size)
            guard = StateGuard(controller, game_id=game_id, next_event_id=ids.next, logger=logger)
            observer = WebObserver(args.url, seat=SEAT)
            current: dict[str, Any] = {"version": None}  # 這次觀察的牌桌版本；牌框要同一版才可以用
            boxes_fn = make_boxes_fn(args.url, seat=SEAT, version_fn=lambda: current["version"])

            def prepare(snap):
                """重拍手牌並與畫面狀態比對；通過回傳 (state, None)，失敗回傳 (None, TurnResult)。"""
                current["version"] = snap.data.get("version")
                state = state_from_view(game_id, snap.data, SEAT)
                prepared = prepare_turn(
                    controller, guard, tile_mapper, controller.capture, boxes_fn,
                    state.players[SEAT].hand,
                    game_id=game_id, next_event_id=ids.next, logger=logger,
                    meld_count=len(state.players[SEAT].melds),
                    max_attempts=args.refresh_attempts, retry_delay=0.2,
                    context={"phase": snap.phase},
                )
                if prepared.failure is not None:
                    print(f"⏸ 暫停：{prepared.failure.error}（Ctrl+Alt+R 繼續）")
                    return None, prepared.failure
                return state, None

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
                origin = marker_origin(frame) if frame is not None else None
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

            record_path = f"{args.log_dir}/{game_id}.game.json"
            runner = GameRunner(
                controller, game_id=game_id,
                observe_fn=observer.snapshot,
                turn_fns={PHASE_MY_TURN: discard_turn, PHASE_REACTION: reaction_turn},
                logger=logger, next_event_id=ids.next, record_path=record_path,
                poll_interval=args.poll, advance_timeout=args.advance_timeout,
                idle_timeout=args.idle_timeout or None, pause_timeout=args.pause_timeout,
                max_steps=args.max_steps,
            )

            watcher = None
            if hotkeys and not args.no_hotkeys:
                watcher = HotkeyWatcher(controller, on_trigger=lambda name: print(f"⌨ 熱鍵：{name}"))
                keys = {k: "+".join(v).upper() for k, v in DEFAULT_BINDINGS.items()}
                print(f"熱鍵：暫停 {keys['pause']}、繼續 {keys['resume']}、停止 {keys['stop']}")
                watcher.start()
            try:
                summary = runner.run()
            finally:
                if watcher is not None:
                    watcher.close()

    try:
        truth = fetch_json(args.url, "/api/game/state")
        truth_ok = truth["is_over"] == summary.finished
    except (OSError, KeyError, ValueError):
        truth, truth_ok = None, True  # 讀不到評測器狀態就略過對照

    time.sleep(0.5)
    page_discards = len(fetch_clicks(args.url)) - clicks_before
    page_reactions = len(fetch_reactions(args.url)) - reactions_before

    log_path = f"{args.log_dir}/{game_id}.jsonl"
    events = load_events(log_path)
    return GameOutcome(
        game_id=game_id, summary=summary, truth=truth, truth_ok=truth_ok,
        page_discards=page_discards, page_reactions=page_reactions,
        mouse_clicks=int(getattr(mouse, "count", 0)),
        log_path=log_path, record_path=record_path,
        total_events=summarize(events).total_events,
        order_problems=check_order(events),
    )


def print_outcome(outcome: GameOutcome, *, log_dir: str) -> None:
    s = outcome.summary
    rate = "-" if s.ui_success_rate is None else f"{s.ui_success_rate:.1%}"
    print()
    print(f"牌局：finished={s.finished} reason={s.reason} 耗時 {s.duration_s:.1f}s")
    print(f"動作：完成 {s.completed}、略過 {s.skipped}、失敗 {s.failed}、人工介入 {s.interventions}")
    print(f"UI 動作 {s.ui_actions} 次，成功 {s.ui_success}（{rate}），畫面驗證通過 {s.verified_actions}，重試 {s.retries}")
    print(f"實際點擊 {s.physical_clicks} 次，多餘點擊 {s.extra_clicks} 次；網頁收到 出牌 {outcome.page_discards}＋反應 {outcome.page_reactions} 次"
          + ("" if outcome.page_match else "  ⚠️ 與滑鼠點擊數不一致"))
    if s.error_codes:
        print(f"錯誤碼：{s.error_codes}")
    if s.latency_p95_ms is not None:
        print(f"latency p95：{s.latency_p95_ms:.1f} ms")
    if outcome.truth is not None:
        t = outcome.truth
        print(f"評測器對照：牌局結束={t['is_over']} 結果={t['result']} 贏家={t['winner']} 剩餘牌 {t['wall_count']}")
    problems = outcome.order_problems
    print(f"JSONL：{outcome.log_path}（{outcome.total_events} 筆）；順序檢查：" + ("通過" if not problems else f"{len(problems)} 項問題 {problems[:3]}"))
    print(f"可回放紀錄：{outcome.record_path}")
    print(f"  查看：python -m src.control.game_runner {log_dir}\\{outcome.game_id}.game.json")