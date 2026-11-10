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

## 3. 已知的整合側小事項

- `tests/` 底下的 `test_boards.py`、`test_strategy*.py`、`test_legal_actions.py` 為其他成員檔案，尚未加成功提示，由各自負責人處理。
- `test_interface/mock_data.py`、`mock_strategy.py`、`mock_controller.py` 已不再被使用，確認後可刪除。
- `requirements.txt` 的 `pydantic` 重複一次，且沒有版本號。