# 整合 W4 筆記（盧冠宇）

## 1. 指令（專案根目錄，PowerShell）

| 用途 | 指令 |
|---|---|
| 按鈕／選牌映射測試 | `python -m tests.test_button_mapper` |
| 反應回合測試 | `python -m tests.test_reaction_plan` |
| 點擊後畫面驗證測試 | `python -m tests.test_verifier` |
| 有限重試測試 | `python -m tests.test_retry` |
| 出牌執行器測試 | `python -m tests.test_discard_executor` |
| 全部 pytest | `python -m pytest -v` |
| 啟動測試介面 | `uvicorn test_interface.app:app --reload` |
| 自動丟牌實機 | `python -m test_interface.run_auto_discard --delay 3` |
| 自動反應實機 | `python -m test_interface.run_auto_react --delay 3` |

實機前：瀏覽器開 http://127.0.0.1:8000（反應用 `/?scenario=reaction`）、按 Ctrl+F5、不要最小化或被擋住。
**每次實機前先按網頁「重設」**，否則牌／按鈕已有紅框，畫面不會再變化，會得到 ACTION_TIMEOUT（這是預期行為）。

常用參數：`--no-verify`（不驗證，也不重試）、`--verify-timeout 1.0`、`--min-change 0.005`、
`--max-retries 1`、`--grace 0.5`。

## 2. W4 交付

- D1 反應按鈕點擊映射：`src/control/button_mapper.py`
- D2 副露選牌（吃／槓兩步驟點擊）：`button_mapper.plan_reaction_click`、`src/control/action_executor.py`
- D3 點擊後驗證：`src/control/verifier.py`（基準幀 -> 點擊 -> 等變化 -> 等穩定 -> 逾時）
- D4 有限重試：`action_executor.RetryPolicy`
- D5 錯誤碼整理：本文件第 4 節

## 3. 驗證與重試流程

1. 點擊前 `prepare()` 擷取基準幀，以點擊點為中心取 ROI。
2. 點擊後 `wait()`：ROI 內變化比例 >= `min_change_ratio` 才算有變化，之後連續 `stable_frames` 幀穩定才算成功。
3. 逾時（ACTION_TIMEOUT）且動作只有 1 次點擊時：
   - 先多觀察 `grace_wait`（預設 0.5 秒），只看不點；這段時間才變化 = 晚到成功，不重點。
   - 仍沒變化且 `retry_count < max_retries`（預設 1），重新檢查前景與 controller，再點一次。
4. 兩步驟動作、ACTION_NOT_STABLE、FRAME_SIZE_CHANGED、CAPTURE_FAILED、WINDOW_NOT_FOREGROUND 一律不重試。
5. `execute_action(retry=None)` 是不重試（舊測試相容）；實機 runner 預設帶 `RetryPolicy()`。

JSONL `action_completed` / `action_failed` 的 metadata：

- `verification`：每次觀察一筆，含 `phase`（initial / grace / retry）、`step`、`change_ratio`、`error`。
- `retry`：`{max_retries, retry_count, late_success}`（有 verifier 且有 retry 才有）。

一回合事件順序不變：game_started -> state_updated -> legal_actions_generated -> decision_made
-> action_started -> action_completed（或 action_failed）-> game_stopped。
只有 PASS 可選時：... -> legal_actions_generated -> reaction_skipped（不點擊）。

## 4. ActionReceipt 錯誤碼

| error_code | 意義 | should_stop | 重試 | 有點擊 |
|---|---|---|---|---|
| UNSUPPORTED_ACTION | 動作類型不支援（出牌／反應以外） | False | 否 | 否 |
| TILE_NOT_FOUND | 畫面上找不到要點的牌（不盲點） | False | 否 | 否 |
| TILE_OUT_OF_FRAME | 牌框中心不在畫面內 | False | 否 | 否 |
| BUTTON_NOT_FOUND | 畫面上找不到反應按鈕 | False | 否 | 否 |
| BUTTON_DISABLED | 按鈕存在但不可點 | False | 否 | 否 |
| BUTTON_OUT_OF_FRAME | 按鈕或組合中心不在畫面內 | False | 否 | 否 |
| CHOICE_NOT_FOUND | 找不到要選的吃／槓組合 | False | 否 | 否 |
| TILE_MAPPING_ERROR | 其他映射錯誤 | False | 否 | 否 |
| WINDOW_NOT_FOREGROUND | 目標視窗不在前景 | **True** | 否 | 視情況 |
| CONTROLLER_NOT_RUNNING | controller 暫停或已停止 | False（兩步驟做到一半為 True） | 否 | 視情況 |
| ACTION_TIMEOUT | 點擊後畫面一直沒變化 | False（兩步驟第一步為 True） | 僅單一點擊 | 是 |
| ACTION_NOT_STABLE | 有變化但沒穩定（動畫未結束） | False（兩步驟第一步為 True） | 否 | 是 |
| FRAME_SIZE_CHANGED | 擷取大小變了（視窗縮放／移動） | **True** | 否 | 是 |
| CAPTURE_FAILED | 擷取不到畫面 | **True** | 否 | 否（點擊前）／是（點擊後） |

TurnResult 層級（沒有回執）：

| error | 意義 |
|---|---|
| NO_LEGAL_ACTIONS | 規則模組沒有可打的牌／合法動作 |
| NO_REACTION_TARGET | 沒有他家打出的牌可以反應 |

兩步驟動作「做到一半」失敗（已點第一步、第二步沒完成）一律 `should_stop=True`，因為畫面可能停在選單中間。

## 5. 實機結果（2026-10-12）

| 情境 | 結果 |
|---|---|
| discard，已重設 | 通過；latency 671.3ms；change_ratio 0.0230；retry_count=0 |
| discard，未重設 | 逾時 -> 多等 -> 重點 -> 再多等，共約 3.8 秒後 ACTION_TIMEOUT；retry_count=1；網頁收到 2 次點擊 |
| react（吃 chi_1_2_3），已重設 | 通過；兩步驟 latency 1360.4ms；change_ratio 0.0247 / 0.0374 |
| react，未重設 | 第一步（按鈕）逾時；不重試、不點第二步；網頁只收到 1 次點擊 |

觀察：

- 實際輪詢間隔約 140ms（擷取約 90ms + sleep 50ms），所以驗證成功約 3 次輪詢、約 420ms。
- 失敗路徑約 3.8 秒（initial 1.1 + grace 0.55 + retry 1.1 + grace 0.53），比原先估計的 2.5 秒長，
  原因是 timeout 預設 1.0 秒再加輪詢粒度。正常路徑不受影響。
- react 兩步驟 1.36 秒，略高於企劃書「操作與確認 1.2 秒」的預算；W7 量 p95 時要決定是否調整。

## 6. 統計口徑（提議，待確認）

企劃書：失敗／人工介入／重試都要記錄，不可從分母刪除。

- 「操作成功率」分母 = `ui_action_executed=True` 的回執（每個動作一筆，重試不另算一筆，但 `retry_count` 要保留）。
- 點擊前就被拒絕（映射錯誤、不在前景等）沒有 UI 動作，不進這個分母，但要列在各錯誤碼的失敗計數，
  並計入「無介入完成率」。
- 「重複點擊 0 次」指非預期的重複；有 `retry_count` 記錄的重試不算。

## 7. 尚未做（W5 之後）

- 重試目前用同一組座標；W5 要在重試前重新擷取並重新映射牌框。
- 狀態不一致暫停、狀態重建、事件回放骨架。
- 熱鍵停止。
- 延遲調整（timeout、stable_frames、擷取成本）留到 W7 量完 p95 再決定。

## 8. 待其他成員確認

### 策略
- `adapters.py` 的 kong 動作 id 為 `kong_{tile}`，明槓／暗槓／加槓會撞成同一個 id。
- `FLOWER_REPLACEMENT`、`DRAW_TILE` 進入 `action_to_index` 會拋 `ValueError`。

### 視覺
- `perception/capture.py` 每種牌只取一個最佳位置，手牌有重複牌時只回一個 bbox；接真實畫面前需要處理。
- 門檻不一致：`roi_spec.md` 寫 0.2，程式用 0.6。
- `perception/screen_capture.py` 與 `control/capture.py` 功能重複，需決定只留一個。
- 視覺 `detected_cards` 與策略 `Observation` 之間尚無轉換。
- 反應按鈕辨識（視覺 W4 D3）完成後，改由它提供 `ButtonBox`，`button_mapper` 不用改。

### 規則
- `rules.GameState` 與 `common.schemas.GameState` 是兩套結構，尚無轉換。
- 沒有 `get_reaction_actions(state, seat)`；整合端暫用 `pipeline.get_reaction_rules_actions`，規則提供後換掉。