"""W6 實機：在測試網頁上自動打完「一整局」（真的移動滑鼠點擊）。

流程：每一輪重新觀察網頁 -> 判斷階段 -> 輪到自己就出牌／有反應按鈕就吃碰槓胡過 ->
      點擊 -> 畫面驗證 -> 等牌局前進 -> 直到牌局結束；全程寫 JSONL，並存成可回放的 .game.json。

W7 起實際流程在 test_interface/live_game.py（批次 runner 共用），這裡只負責單局入口。

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

import urllib.error
from datetime import datetime, timezone

from test_interface.live_common import open_session
from test_interface.live_game import (  # noqa: F401  (build_parser 供 tests/test_run_full_game 使用)
    build_parser,
    play_game,
    post_new_game,
    print_outcome,
)


def main() -> int:
    args = build_parser().parse_args()

    if not args.keep_game:
        try:
            post_new_game(args.url, args.seed)
        except (urllib.error.URLError, OSError) as exc:
            print(f"❌ 連不到測試介面 {args.url}：{exc}（請先啟動 uvicorn）")
            return 1

    session = open_session(args, page_hint="/?scenario=game")
    if session is None:
        return 1

    game_id = "w6_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    try:
        outcome = play_game(args, session, game_id=game_id)
    except RuntimeError as exc:
        print(f"❌ {exc}")
        return 1

    print_outcome(outcome, log_dir=args.log_dir)

    if outcome.unattended_ok:
        print("✅ 整局無人工介入完成")
        return 0
    if outcome.summary.finished:
        print("⚠️ 牌局打完了，但有人工介入或檢查沒過，請看上方輸出")
        return 1
    print("❌ 牌局沒有打完，請看上方輸出與 JSONL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())