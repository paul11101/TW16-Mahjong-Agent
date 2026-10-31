# 整合 W7 筆記（盧冠宇）

## 1. 指令（專案根目錄，PowerShell）

| 用途 | 指令 |
|---|---|
| 工具／事件日誌測試 | `python -m tests.test_util` |
| 滑鼠包裝測試 | `python -m tests.test_mouse_wrappers` |
| 回合前準備測試 | `python -m tests.test_turn_prep` |
| 批次統計／點擊計數／儀表板測試 | `python -m tests.test_batch` |
| 全部 pytest | `python -m pytest -v` |
| **批次實機（5 局）** | `python -m test_interface.run_batch --delay 3 --games 5` |
| 批次實機（20 局、指定種子） | `python -m test_interface.run_batch --delay 3 --games 20 --seed-start 100` |
| 單局實機 | `python -m test_interface.run_full_game --delay 3 --seed 1` |
| 儀表板 | 瀏覽器開 `http://127.0.0.1:8000/dashboard` |

批次實機前：`uvicorn test_interface.app:app`，瀏覽器開 `http://127.0.0.1:8000/?scenario=game`（Ctrl+F5，不要最小化）。
Ctrl+Alt+S 會結束整批；每局結束就存一次 `logs/<batch_id>.batch.json`。

## 2. W7 交付

| 項目 | 位置 |
|---|---|
| 共用小工具（p95、原子寫 JSON、等 RUNNING） | `src/control/util.py` |
| 整合端事件寫 JSONL | `src/control/event_log.py` |
| 回合前準備（重拍、記錄、暫停） | `src/control/turn_prep.py` |
| 批次統計與目標對照 | `src/control/batch.py` |
| 單局／批次共用流程 | `test_interface/live_game.py` |
| 批次 runner | `test_interface/run_batch.py` |
| dashboard 基本頁 | `test_interface/dashboard_page.py`、`app.py` 的 `/dashboard`、`/api/dashboard` |
| 實際點擊計數 | `CountingMouse`（`mouse.py`）、`StepRecord.clicks / planned_clicks` |

整理：`RETRY_TURN_ERRORS` 搬進 `errors.py`；`GameSummary` 改名 `GameRunSummary`（避免與 `rules.game_result.GameSummary` 同名）；
`execute_action` 回傳 `ActionOutcome`（NamedTuple，舊的拆法仍可用）；`RepeatClickMouse` 搬進 `mouse.py`。

## 3. 統計口徑（定稿）

- **無介入完成率** = 整局無介入完成的局數 / 全部局數。無介入 = 牌局真的結束、`interventions == 0`、
  評測器的「牌局結束」與 Agent 看到的一致、JSONL 順序檢查通過。沒跑起來的局算失敗（`START_FAILED`），不從分母刪除。
- **操作成功率** = `ui_success / ui_actions`；分母是 `ui_action_executed=True` 的回執，重試不另算一筆（`retry_count` 另計）。
  點擊前就被拒絕的動作沒有 UI 動作，不進這個分母，但列在錯誤碼計數。
- **重複點擊** = 各步驟 `max(0, 實際點擊 - (計畫點擊 + 重試))` 的總和；另外比對「網頁收到的點擊數」與「滑鼠實際點擊數」，
  不一致的局數記在 `page_mismatch_games`。有 `retry_count` 記錄的重試不算重複。
- **p95** = 所有局的 UI 動作 latency 合併後再算。
- `failed` 計的是「失敗的嘗試」，同一個畫面重試失敗兩次就是兩次，不從分母刪除。

## 4. 尚未做

- 視覺接入（`VisionObserver`，等視覺定案只留 `detector.py` 的輸出格式）。
- 重試前重新擷取並重新映射牌框（真實遊戲打牌後手牌會左移才需要）。
- `run_w5_live.py` 沒有改成 `controller_session`（W5 已驗收）。