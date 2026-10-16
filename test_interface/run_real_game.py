"""正式遊戲（愛台灣打麻將）實機：擷取視窗 -> 視覺辨識手牌 -> 牌框 -> 決策 -> 懸停／點擊。

三種模式（由安全到危險）：
    （預設）乾跑：只擷取、辨識、畫 debug 圖、印出手牌狀態，不動滑鼠。
    --hover  ：把滑鼠移到 baseline 要打的牌上，不點擊（確認座標有沒有落在牌上）。
    --click  ：真的點一次（只在「輪到自己、17 張、沒有花牌」時才會點）。

事前準備（專案根目錄）：
    1. 開啟桌面版「愛台灣打麻將」（視窗標題含「愛台灣打麻將 [版本號]」），固定視窗大小
       （視覺模板依畫面「寬度」縮放，視窗大小一變，牌的大小比例就可能不對）。
    2. 遊戲維持「手動」模式（不要開代打），不要最小化、不要被其他視窗擋住。
    3. 如果遊戲是以系統管理員身分執行，PowerShell 也要用系統管理員開，否則點擊會被 Windows 擋掉。
    4. python -m test_interface.run_real_game --delay 3

安全：
- 手牌張數不是 17、或有花牌時，--click 一律不點。
- 預設不重試（--max-retries 0）：重試用舊座標，打牌後手牌會左移，重點可能打到別張牌。
- 滑鼠移到螢幕左上角可觸發 PyAutoGUI failsafe。
- --clicks 2 會在同一個座標連點兩次（給「第一下選牌、第二下打出」的遊戲）；
  兩次都算同一個動作，不計入重複點擊。確認遊戲行為後，之後要改成正式的兩步驟計畫。
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

from src.common.logger import AppLogger
from src.control.controller import AgentController
from src.control.game_profile import (
    HAND_MY_TURN,
    ITAIWANMJ16,
    check_hand_row,
    classify_hand,
    state_from_visible_hand,
)
from src.control.mouse import MouseController
from src.control.pipeline import EventIds, run_discard_turn
from src.control.window import WindowLocator
from src.control.tile_mapper import (
    TileMapper,
    TileMappingError,
    boxes_from_observation,
    plan_discard_click,
)
from src.rules.legal_actions import LegalActionGenerator
from src.strategy.adapters import actions_to_legal_actions, game_state_to_observation
from src.strategy.baseline import BaselinePolicy
from test_interface.live_common import (
    add_action_args,
    add_common_args,
    make_verifier_and_retry,
    open_session,
    print_receipt,
)

SEAT = 0
DEBUG_PATH = Path("data/processed/real_game_debug.png")


class RepeatClickMouse:
    """同一個座標連點 times 次（click 一次 = 實體點 times 次）。"""

    def __init__(self, inner, times: int = 2, gap: float = 0.25, sleep=time.sleep) -> None:
        if times < 1:
            raise ValueError("times 必須 >= 1")
        self._inner = inner
        self.times = times
        self.gap = gap
        self._sleep = sleep

    def click(self, x: int, y: int) -> None:
        for i in range(self.times):
            if i:
                self._sleep(self.gap)
            self._inner.click(x, y)


def _make_policy(use_shanten: bool):
    if not use_shanten:
        return BaselinePolicy()
    from src.strategy.shanten import Taiwan16ShantenCalculator

    return BaselinePolicy(Taiwan16ShantenCalculator())


def _save_capture(frame, observation_dict) -> None:
    """存下這一幀與視覺輸出，給視覺同學重現問題用。"""
    import json

    import cv2

    out = Path("data/processed")
    out.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out / "real_game_frame.png"), frame)
    (out / "real_game_observation.json").write_text(
        json.dumps(observation_dict, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("已儲存原始畫面與視覺輸出：data/processed/real_game_frame.png、real_game_observation.json")


def _save_debug(frame, boxes, plan) -> None:
    import cv2

    debug = frame.copy()
    for box in boxes:
        cv2.rectangle(debug, (box.x, box.y), (box.x + box.w, box.y + box.h), (0, 255, 0), 2)
        cv2.putText(debug, str(box.tile), (box.x, max(box.y - 4, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    if plan is not None:
        cv2.circle(debug, plan.frame_point, 10, (0, 0, 255), -1)

    DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(DEBUG_PATH), debug)


def main() -> int:
    parser = argparse.ArgumentParser(description="正式遊戲（愛台灣打麻將）實機測試")
    add_common_args(parser)
    add_action_args(parser)
    parser.set_defaults(title=ITAIWANMJ16.title_contains, max_retries=0)
    parser.add_argument("--move-duration", type=float, default=0.15,
                        help="滑鼠移動到目標的秒數（桌面遊戲常需要先 hover 才吃得到點擊；0 = 瞬間移動）")
    parser.add_argument("--templates", default="data/samples", help="視覺模板資料夾")
    parser.add_argument("--min-conf", type=float, default=0.6, help="視覺信心門檻")
    parser.add_argument("--dealer", type=int, default=0, help="莊家的內部座位（0=自己 1=右 2=上 3=左）")
    parser.add_argument("--melds", type=int, default=0, help="自己已副露幾組")
    parser.add_argument("--hover", action="store_true", help="滑鼠移到要打的牌上，不點擊")
    parser.add_argument("--click", action="store_true", help="真的點擊")
    parser.add_argument("--clicks", type=int, default=1, choices=(1, 2), help="每次點擊連點幾下")
    parser.add_argument("--shanten", action="store_true", help="用向聽數策略（預設打第一張，先降低變數）")
    args = parser.parse_args()

    if WindowLocator(args.title).find() is None:
        print(f"❌ 找不到遊戲視窗（標題含「{args.title}」）：請先開啟桌面版愛台灣打麻將，不要最小化")
        return 1

    session = open_session(args)
    if session is None:
        return 1

    frame, region = session.frame, session.region

    # 1. 視覺：手牌偵測（視覺模組的程式，這裡只讀它的輸出）
    from src.perception.capture import run_perception_matching

    observation_dict = run_perception_matching(frame=frame, templates_dir=args.templates)
    if observation_dict is None:
        print("❌ 視覺模組沒有回傳結果")
        return 1

    boxes = boxes_from_observation(observation_dict, min_confidence=args.min_conf)
    hand = [b.tile for b in boxes]
    status = classify_hand(hand, hand_size=ITAIWANMJ16.hand_size, meld_count=args.melds)

    print(f"畫面 {session.width}x{session.height}；偵測到 {len(boxes)} 張手牌：{hand}")
    if boxes:
        widths = sorted(b.w for b in boxes)
        print(f"牌框寬度中位數 {widths[len(widths) // 2]}px；y 範圍 {min(b.y for b in boxes)}~{max(b.y for b in boxes)}")
    print(f"手牌狀態：{status}（my_turn=可出牌 waiting=非自己回合 has_flower=有花牌 incomplete=張數不對）")
    if len(boxes) < ITAIWANMJ16.hand_size:
        print("⚠️ 偵測張數偏少：視覺目前每種牌只回一個位置，有重複牌（對子、刻子）時會漏掉")
    if len(boxes) > ITAIWANMJ16.hand_size + 1:
        print("⚠️ 偵測張數超過 17：視覺有誤判（例如萬字牌下半部相同，被別張萬字模板誤認）")

    row_problems = check_hand_row(boxes)
    for problem in row_problems:
        print(f"⚠️ 手牌排列檢查：{problem}")
    _save_capture(frame, observation_dict)

    mapper = TileMapper(frame_size=(session.width, session.height))
    mapper.update(boxes)
    state = state_from_visible_hand(
        "real_preview", hand, seat=SEAT, dealer=args.dealer
    )

    # 2. 決策與座標（乾跑與懸停都需要）
    policy = _make_policy(args.shanten)
    plan = None
    decision = None
    if boxes:
        try:
            legal = actions_to_legal_actions(
                LegalActionGenerator().get_turn_player_actions(hand=list(hand))
            )
            decision = policy.decide(game_state_to_observation(state, seat=SEAT), legal)
            plan = plan_discard_click(decision, mapper, region)
            print(f"策略選擇：{decision.action.id}（{decision.reason}）")
            print(f"  frame {plan.frame_point} -> 螢幕 {plan.screen_point}")
        except (ValueError, TileMappingError) as exc:
            print(f"❌ 算不出點擊座標：{exc}")

    _save_debug(frame, boxes, plan)
    print(f"已儲存 debug 圖：{DEBUG_PATH}（綠框=偵測到的牌，紅點=要點的位置）")

    if not args.hover and not args.click:
        print("✅ 乾跑完成（沒有動滑鼠）。確認綠框都在牌上、張數正確，再加 --hover。")
        return 0

    if plan is None:
        return 1

    # 3. 懸停：只移動，不點擊
    if args.hover and not args.click:
        import pyautogui

        x, y = plan.screen_point
        pyautogui.moveTo(x, y, duration=0.4)
        print(f"✅ 滑鼠已移到 {plan.screen_point}（沒有點擊）。請確認它停在牌上。")
        return 0

    # 4. 點擊：只有「輪到自己、17 張、沒有花牌」才點
    if status != HAND_MY_TURN:
        print(f"❌ 手牌狀態是 {status}，不點擊")
        return 1
    if row_problems:
        print("❌ 手牌排列檢查沒通過（視覺可能漏牌或誤判），不點擊")
        return 1

    game_id = "real_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    state = state_from_visible_hand(game_id, hand, seat=SEAT, dealer=args.dealer)

    mouse = MouseController(duration=args.move_duration)
    mouse.warmup()  # 先載入 pyautogui，第一次點擊的 latency 才不含 import 時間
    if args.clicks > 1:
        mouse = RepeatClickMouse(mouse, args.clicks)

    with AppLogger(log_dir=args.log_dir, game_id=game_id) as logger:
        controller = AgentController(
            game_id=game_id, mouse=mouse, capturer=session.capturer, logger=logger
        )
        controller.start()
        verifier, retry = make_verifier_and_retry(args, controller, session)
        try:
            result = run_discard_turn(
                state, SEAT, mapper, region, controller,
                game_id=game_id, ids=EventIds(), logger=logger, policy=policy,
                foreground_check=session.locator.is_foreground,
                verifier=verifier, retry=retry,
            )
        finally:
            controller.stop()

    if result.receipt is None:
        print(f"❌ 沒有執行動作：{result.error}")
        return 1

    print_receipt(result.receipt, verifier)
    print(f"JSONL：{args.log_dir}/{game_id}.jsonl")

    if result.receipt.success:
        print("✅ 點擊完成。請看遊戲：牌是否真的打出？")
        if args.clicks == 1:
            print("   若牌只是被「選起」沒有打出去，下次改用 --clicks 2。")
        return 0

    print("❌ 未完成，請看上方回執與 error_code")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())