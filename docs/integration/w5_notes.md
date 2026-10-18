# 整合 W5 筆記（盧冠宇）

## 1. 指令（專案根目錄，PowerShell）

| 用途 | 指令 |
|---|---|
| 狀態一致性／暫停測試 | `python -m tests.test_state_guard` |
| 重新擷取／低信心／狀態重建測試 | `python -m tests.test_refresh` |
| 監督者（暫停／停止／恢復）測試 | `python -m tests.test_supervisor` |
| 熱鍵測試（假按鍵） | `python -m tests.test_hotkeys` |
| 事件回放測試 | `python -m tests.test_replay` |
| 全部 pytest | `python -m pytest -v` |
| 回放／統計一個 JSONL | `python -m src.control.replay logs\<檔名>.jsonl --turns` |
| 逐筆印出事件 | `python -m src.control.replay logs\<檔名>.jsonl --events` |

## 2. W5 交付

| 日 | 項目 | 檔案 |
|---|---|---|
| D1 | pause/resume/stop 熱鍵（Ctrl+Alt+P / R / S） | `src/control/hotkeys.py` |
| D1 | 多回合監督：暫停等待、停止、逾時 | `src/control/supervisor.py` |
| D2 | 狀態不一致 -> 記錄 `state_mismatch` -> 暫停 | `src/control/state_guard.py` |
| D3 | 重新擷取流程 | `src/control/refresh.py`（`refresh_hand`） |
| D3 | 狀態重建入口（只重建自己的手牌） | `src/control/refresh.py`（`rebuild_own_hand`） |
| D4 | 事件回放骨架 | `src/control/replay.py` |
| D4 | 低信心處理：低信心 -> 重拍，用完次數就失敗並清空牌框 | `src/control/refresh.py` |
| D5 | 中途停止與恢復：checkpoint + 從中斷的回合接著跑 | `src/control/supervisor.py` |

新增錯誤碼（`src/control/errors.py`）：`STATE_MISMATCH`、`LOW_CONFIDENCE`。

## 3. 行為規則

- 暫停 = 不能點擊但可以擷取；停止 = 不能點擊也不能擷取，且 controller 不能重啟。
- 「恢復」有兩種：
  - 暫停後恢復：同一個 controller `resume()`（網頁按鈕、熱鍵、或 supervisor 等待）。
  - 停止後恢復：建新 controller，用 `start_index_from_checkpoint()` 從 checkpoint 接著跑。
- 回合失敗需要人介入（`should_stop`、`STATE_MISMATCH`、`LOW_CONFIDENCE`、回合中被暫停）：
  暫停、不前進、恢復後重跑同一回合；每回合最多 `max_turn_attempts`（預設 3）次，超過就停止。
  失敗的嘗試每次都計入 `failed`，不從分母刪除。
- 重跑回合時，回合函式必須重新擷取、重新檢查，不能重用舊畫面。
- 接續同一個 game_id 的 JSONL 時，`EventIds` 要用新前綴，否則 `event_id` 會重複（`check_order` 會報）。
- `refresh_hand` 失敗時會清空 `TileMapper`：寧可 `TILE_NOT_FOUND`，也不要點到過期位置。

## 4. 尚未做

- 重試前重新擷取並重新映射牌框（`action_executor` 重試目前仍用同一組座標）。
- 回放只交出事件，還不會重現畫面或重送動作。
- 狀態重建只有自己的手牌；河牌、副露、花牌、分數要等視覺能辨識。
- 把 `StateGuard` + `refresh_hand` + `run_discard_turn` 串成真正的「回合函式」給 supervisor 用（W6 D1 一局流程）。

## 5. 待其他成員確認

### 視覺
- 目前有三種輸出格式：`perception/capture.py`（`detected_cards`：`card`/`bbox`/`confidence`）、
  `perception/detector.py`（`hand_cards`：`name`/`bbox`/`confidence`）、`card_recognizer.py`（`(id, confidence)`）。
  整合端 `boxes_from_observation` 只吃第一種，而且 `card` 必須是 0~41 的數字字串。請確定最終只用一種。
- 低信心重拍需要每張牌都有 `confidence`；手牌有重複牌時要回傳每一張的 bbox（見 w4_notes 第 8 節）。

### 規則
- 希望提供 `GameState` 的一致性檢查（牌數守恆：手牌 + 副露 + 河牌 + 牌牆 + 花牌 = 144），
  整合端的 `StateGuard` 目前只比對「畫面手牌 vs 規則手牌」。
- `get_reaction_actions(state, seat)` 仍未提供（整合端暫用 `pipeline.get_reaction_rules_actions`）。