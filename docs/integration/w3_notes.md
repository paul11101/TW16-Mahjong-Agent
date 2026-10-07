# 整合 W3 筆記（盧冠宇）

## 1. 指令（專案根目錄，PowerShell）

| 用途 | 指令 |
|---|---|
| 視窗定位測試 | `python -m tests.test_window` |
| 牌框座標映射測試 | `python -m tests.test_tile_mapper` |
| 出牌執行器測試 | `python -m tests.test_discard_executor` |
| 整回合管線測試 | `python -m tests.test_turn_pipeline` |
| 全部 pytest | `python -m pytest -v` |
| 啟動測試介面 | `uvicorn test_interface.app:app --reload` |
| 視窗擷取實機 | `python -m src.control.window --delay 3` |
| 牌框映射實機（只算座標，不點擊） | `python -m test_interface.check_mapping --delay 3` |
| 自動丟牌實機（真的點一次） | `python -m test_interface.run_auto_discard --delay 3` |

實機測試前：瀏覽器開 http://127.0.0.1:8000、按 Ctrl+F5、不要最小化或被擋住。
再跑一次實機前，先在網頁按「重設」清掉紅框與點擊紀錄。

## 2. W3 交付

- D1 測試牌桌顯示：`test_interface/table_view.py`、`table_page.py`
- D2 固定視窗擷取：`src/control/window.py`
- D3 牌框座標映射：`src/control/tile_mapper.py`
- D4 自動丟牌與回執：`src/control/discard_executor.py`
- D5 整回合管線：`src/control/pipeline.py`；實機入口 `test_interface/run_auto_discard.py`

## 3. 座標規則

- TileBox 一律是擷取畫面（frame）座標；只有點擊那一刻才用 `frame_to_screen()` 換成螢幕座標。
- 測試介面的牌框來源是網頁回報的 DOM；可視區原點優先用洋紅校正標記（`#calib`）。

## 4. 一回合 JSONL 事件順序

game_started -> state_updated -> legal_actions_generated -> decision_made
-> action_started -> action_completed（或 action_failed）-> game_stopped

## 5. ActionReceipt 錯誤碼（目前）

| error_code | 意義 | should_stop |
|---|---|---|
| UNSUPPORTED_ACTION | 目前只支援出牌 | False |
| TILE_NOT_FOUND | 畫面上找不到要點的牌（不盲點） | False |
| TILE_OUT_OF_FRAME | 牌框中心不在畫面內 | False |
| WINDOW_NOT_FOREGROUND | 目標視窗不在前景 | True |
| CONTROLLER_NOT_RUNNING | controller 暫停或已停止 | False |
| TILE_MAPPING_ERROR | 其他映射錯誤 | False |
| NO_LEGAL_ACTIONS | 沒有合法動作（TurnResult.error，無回執） | - |

## 5. 尚未做（W4 之後）

- 點擊後重新擷取驗證（`state_verified` 目前固定 False，W4 D3）、等待畫面變化、逾時與有限重試。
- 反應按鈕（吃碰槓胡過）點擊映射與副露選牌（W4 D1、D2）。
- 反應動作現在一律包含 PASS，所以不會再出現空列表。W4 D1 要處理的是「只有 PASS 一個選項」的情況，也就是沒有任何牌可以反應時，要不要自動點過，還是直接略過。

## 6. 待其他成員確認

### 規則
- `get_turn_player_actions` 沒有可打的牌時會拋 ValueError，整合端已在 run_discard_turn 轉成 NO_LEGAL_ACTIONS。

### 視覺
- `perception/capture.py` 每種牌只取一個最佳位置，手牌有重複牌時只回一個 bbox；接入真實遊戲畫面前需要處理（W3 視覺 D3 已列為處理「相同牌多實例位置」）。
- 門檻不一致：`roi_spec.md` 寫 0.2，程式用 0.6。
- `perception/screen_capture.py` 與 `control/capture.py` 功能重複，需決定只留一個。