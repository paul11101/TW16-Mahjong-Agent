# 整合 W2 筆記（盧冠宇）

## 1. 環境與執行方式（專案根目錄，PowerShell）

```powershell
python -m venv .venv
.venv\Scripts\Activate
pip install -r requirements.txt
```

| 用途 | 指令 |
|---|---|
| 整合串接測試（假資料→決策→點擊→回執） | `python -m tests.test_agent_runner` |
| 控制器 pause/stop 測試 | `python -m tests.test_control` |
| 擷取骨架測試 | `python -m tests.test_capture` |
| 事件/JSONL 測試 | `python -m tests.test_pipeline` |
| 測試介面控制閘門 | `python -m tests.test_app` |
| 全部 pytest | `python -m pytest -v` |
| 啟動測試介面 | `uvicorn test_interface.app:app --reload` |

注意：請用 `python -m ...` 或 `python -m pytest`，不要用 `python tests/xxx.py`，否則找不到 `src`。

## 2. W2 整合交付狀態

- control：`capture.py`、`mouse.py`、`controller.py`（start/pause/resume/stop 閘門）已完成。
- common：`events.py`、`schemas.py`、`logger.py`（JSONL）已完成。
- 測試介面：`test_interface/` 已改為串接真實模組，輸出 `ActionReceipt` 與 JSONL。
- 尚未做（W3 之後）：牌→座標映射、點擊後重新擷取驗證（`state_verified` 目前固定 False）、視窗定位、熱鍵停止。

## 3. 待其他成員處理／確認的缺口

### 規則
- `rules.GameState`/`PlayerState` 與 `common.schemas.GameState`/`PlayerState` 是兩套結構（`players` 一個是 dict、一個是 list），尚無轉換，事件流程目前只能用摘要 payload。
- `rules/game_state.py` 另外定義了 `EventType`，與 `common/events.py` 同名，容易混用。
- `get_response_actions` 在沒有可反應動作時回傳空列表（不含 PASS），整合端會拿到「沒有合法動作」。請確認是否為預期行為。

### 策略
- `adapters.py` 的 kong 動作 id 為 `kong_{tile}`，明槓／暗槓／加槓會撞成同一 id 與同一個 mask 索引。
- `FLOWER_REPLACEMENT`、`DRAW_TILE` 進入 `action_to_index` 會拋 `ValueError`。

### 視覺
- `perception/capture.py` 每種牌只取 `minMaxLoc` 一個最佳位置，手牌有重複牌時只會回一個 bbox，W3 座標映射會卡住。
- 門檻不一致：`roi_spec.md` 寫 0.2，程式用 0.6。
- `perception/screen_capture.py` 與 `control/capture.py` 功能重複，需決定只留一個。
- 視覺 Observation（`detected_cards`）與策略 `Observation` 之間尚無轉換。

## 4. 已知的整合側小事項

- `tests/` 底下的 `test_boards.py`、`test_strategy*.py`、`test_legal_actions.py` 為其他成員檔案，尚未加成功提示，由各自負責人處理。
- `test_interface/mock_data.py`、`mock_strategy.py`、`mock_controller.py` 已不再被使用，確認後可刪除。
- `requirements.txt` 的 `pydantic` 重複一次，且沒有版本號。