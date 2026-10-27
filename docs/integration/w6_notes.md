# 整合 W6 筆記（盧冠宇）

## 1. 指令（專案根目錄，PowerShell）

| 用途 | 指令 |
|---|---|
| 整局流程（GameRunner）測試 | `python -m tests.test_game_runner` |
| 測試牌桌／觀察器／整局整合測試 | `python -m tests.test_sim_table` |
| 實機入口參數測試 | `python -m tests.test_run_full_game` |
| 全部 pytest | `python -m pytest -v` |
| **一鍵啟動：打完一局** | `.\start_game.ps1`（可加 `-Seed 5 -Delay 3 -NoVerify`） |
| 手動：伺服器 | `uvicorn test_interface.app:app` |
| 手動：開網頁 | `http://127.0.0.1:8000/?scenario=game`（Ctrl+F5） |
| 手動：打一局 | `python -m test_interface.run_full_game --delay 3 --seed 1` |
| 查看可回放紀錄 | `python -m src.control.game_runner logs\<game_id>.game.json` |
| 查看 JSONL 統計 | `python -m src.control.replay logs\<game_id>.jsonl --turns` |

## 2. W6 交付

| 日 | 項目 | 檔案 |
|---|---|---|
| D1 | 整局流程（觀察→階段→出牌／反應→等畫面前進） | `src/control/game_runner.py` |
| D1 | 可打完整局的測試牌桌（對手自動打） | `test_interface/sim_table.py` |
| D1 | 網頁觀察器（階段由可見資訊推出） | `test_interface/web_observer.py` |
| D2 | 動作後遊戲層級驗證（同畫面不重點、未前進→NOT_ADVANCED 暫停） | `game_runner.py` |
| D3 | 完整事件日誌（game_step／runner_paused／game_finished）＋一鍵啟動 | `game_runner.py`、`start_game.ps1` |
| D4 | 實機入口、重複點擊防護 | `test_interface/run_full_game.py` |
| D5 | 每步存檔的可回放紀錄 `<game_id>.game.json` | `game_runner.py` |

修改：`errors.py`（新增 TURN_EXCEPTION／NOT_ADVANCED／OBSERVE_FAILED／IDLE_TIMEOUT）、
`test_interface/app.py`（/api/game/new、/api/game/state、scenario=game）、`table_page.py`（整局模式輪詢）。

## 3. 規則

- 已經點擊卻失敗：一律暫停，不自動重點；沒點擊的失敗（TILE_NOT_FOUND 等）自動重試，同畫面最多 3 次。
- 動作成功後同一畫面不再動作；超過 `--advance-timeout` 沒前進 → 暫停（人按繼續視為同意再試）。
- 回合函式拋例外 → 記 TURN_EXCEPTION 並暫停，不讓整局崩潰。
- 「無人工介入」= `summary.interventions == 0` 且牌局結束。

## 4. 尚未做／限制

- 自摸胡牌：`run_discard_turn` 的合法動作不含 WIN，Agent 自摸時不會胡（SimTable 也沒提供按鈕）。
- 過水狀態：畫面看不到自己是否過水，`get_reaction_rules_actions` 不帶 passed_win，可能提供已被規則禁止的胡。
- 對手很簡單（摸打、只碰／胡），不代表真實牌力。
- 批次連跑多局、p95 統計：W7。
- 真實遊戲的階段判斷（視覺）：待視覺提供。

## 5. 待其他成員確認

### 規則
- 請提供 `get_reaction_actions(state, seat)`（含 passed_win、可否榮和），整合端換掉暫時轉接。
- 請提供整局狀態機介面（W6 規則 D3）：誰該行動、是否結束、結果。

### 視覺
- 真實畫面要能判斷：輪到自己、反應按鈕、牌局結束；手牌重複牌每張都要有 bbox。