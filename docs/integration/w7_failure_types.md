# 整合 W7 D5：失敗類型整理（盧冠宇）

依據 `src/control/errors.py`、`action_executor.py`、`game_runner.py`、`batch.py` 的實際行為整理。
統計口徑見 `w7_notes.md` 第 3 節：失敗一律留在分母，不刪除。

## 1. 分類總表

| 類別 | error_code / reason | 有點擊 | 進 UI 成功率分母 | 系統反應 | 需人工介入 |
|---|---|---|---|---|---|
| A 映射失敗（點擊前） | TILE_NOT_FOUND、TILE_OUT_OF_FRAME、BUTTON_NOT_FOUND、BUTTON_DISABLED、BUTTON_OUT_OF_FRAME、CHOICE_NOT_FOUND、TILE_MAPPING_ERROR、UNSUPPORTED_ACTION | 否 | 否（只計錯誤碼） | 重新觀察，同畫面最多再試 3 次 | 否（用完次數才停止） |
| A2 沒有可做的事 | NO_LEGAL_ACTIONS、NO_REACTION_TARGET、LAYOUT_STALE | 否 | 否 | 同上，自動重試 | 否 |
| B 畫面／狀態不可信 | STATE_MISMATCH、LOW_CONFIDENCE、CAPTURE_FAILED | 否 | 否 | 重拍 → 仍失敗則暫停，恢復後重跑同一回合 | 是 |
| C 點擊後驗證失敗 | ACTION_TIMEOUT、ACTION_NOT_STABLE、FRAME_SIZE_CHANGED、NOT_ADVANCED | 是 | 是（失敗留在分母） | 單一點擊逾時：多等 grace → 重點 1 次；其餘暫停，不自動重點 | 是 |
| D 安全閘門 | WINDOW_NOT_FOREGROUND、CONTROLLER_NOT_RUNNING | 視情況 | 視情況 | 拒絕點擊；前景遺失 should_stop=True | 是 |
| E 流程層 | TURN_EXCEPTION、OBSERVE_FAILED、IDLE_TIMEOUT | 否 | 否 | 暫停 | 是 |
| F 整局中止 | max_attempts、pause_timeout、max_steps、stopped | — | — | 整局未完成 | 是 |
| G 批次層 | START_FAILED（`failed_start_row`） | 否 | 否 | 算 1 局失敗、1 次介入，整批中止 | 是 |

## 2. 各類原因與負責方

| 類別 | 常見原因 | 責任方 | 處理方向 |
|---|---|---|---|
| A | 牌框舊了、手牌被蓋住、視覺漏牌（重複牌只回一個 bbox） | 整合／視覺 | 重拍；視覺要回傳每張牌 bbox |
| A（BUTTON_DISABLED） | 過水後「胡」按鈕停用，但規則提供了胡 | 規則／整合 | 已用 `only_visible_buttons` 規避；規則提供含 passed_win 的 `get_reaction_actions` 後可移除轉接 |
| B | 畫面動畫中、信心不足、手牌張數不合理 | 視覺／整合 | 多幀確認與低信心重拍 |
| C | 點擊沒生效、動畫未結束、視窗被縮放或移動 | 整合 | 調 timeout／min-change／stable_frames；視窗移動需重新定位 |
| D | 視窗被其他程式蓋住、人按了暫停 | 操作環境 | 實機時不要最小化或被擋住 |
| E | 策略／規則丟例外、測試網頁沒回應 | 策略／規則／整合 | 看 JSONL 的 TURN_EXCEPTION 與 detail.exception |

## 3. W7 實機已遇到並處理的失敗

| 問題 | 類別 | 處理 |
|---|---|---|
| 自己回合暗槓沒有點擊映射 | A（UNSUPPORTED） | 補自己回合的胡／槓按鈕映射（`button_mapper` 傳入 `run_discard_turn`） |
| 手牌被反應按鈕列蓋住，點到按鈕 | B／C | 測試網頁手牌與按鈕包成 dock；DOM 牌框加 `visible` 檢查，被蓋住視為狀態不一致，不盲點 |
| seed 1018 過水後 win_22 按鈕停用 | A（BUTTON_DISABLED） | 反應只從畫面可點按鈕選 |

## 4. 重點判讀規則

- 「已點擊卻失敗」一律暫停，不自動重點（避免重複點擊）。
- 「沒點擊的失敗」自動重試，不算人工介入，但每次都計入 `failed` 與錯誤碼。
- 無介入完成率只看：局真的結束、`interventions == 0`、評測器對得上、JSONL 順序檢查通過。

## 5. 下一步

- 操作成功率要滿 1,000 次 UI 動作：目前 20 局約 369 次，約需 55～60 局（`--games 60 --seed-start 2000`）。
- 視覺接入後新增類別：辨識信心不足的比例（LOW_CONFIDENCE 觸發率）。