# 整合 W8 筆記（盧冠宇）

## 1. 指令（專案根目錄，PowerShell）

| 用途 | 指令 |
|---|---|
| 失敗分析工具測試 | `python -m tests.test_failure_analysis` |
| 凍結／備份工具測試 | `python -m tests.test_release` |
| 反應動作轉接測試 | `python -m tests.test_reaction_adapter` |
| 規則端查詢介面測試（沈世翔） | `python -m tests.test_boards_w8_queries` |
| 暫停診斷文字測試 | `python -m tests.test_pause_diagnosis` |
| 舊紀錄改名測試 | `python -m tests.test_archive_logs` |
| 測試網頁防選取文字測試 | `python -m tests.test_page_no_select` |
| 全部 pytest | `python -m pytest -v` |
| **批次實機（20 局）** | `python -m test_interface.run_batch --delay 3 --games 20 --seed-start 2000 --batch-id w8_run1` |
| 失敗分析（可多批） | `python -m src.control.failure_analysis logs --batch w8_run1 w8_run2 w8_run3 --out logs\w8_analysis_all.txt` |
| 凍結 MVP | `python -m src.control.release freeze --version mvp-v1` |
| 驗證與凍結版一致 | `python -m src.control.release verify` |
| 備份可執行版本 | `python -m src.control.release backup --version mvp-v1 --with-data` |
| 備份原始紀錄 | `Compress-Archive -Path logs\w8_run*.* -DestinationPath exports\w8_logs.zip -Force` |

批次實機前：`uvicorn test_interface.app:app`，瀏覽器開 `http://127.0.0.1:8000/?scenario=game`（Ctrl+F5，不要最小化）。
修改 `table_page.py` 後要重啟 uvicorn 並重新整理（HTML 寫在 Python 裡）。

## 2. W8 交付

| 日 | 項目 | 位置 |
|---|---|---|
| D1 | 連續 20 局測試（共 3 批） | `test_interface/run_batch.py`（沿用 W7） |
| D2 | 失敗事件分析 | `src/control/failure_analysis.py` |
| D3 | 再次跑 20 局；暫停時印出診斷 | `test_interface/live_game.py`（`pause_diagnosis`） |
| D4 | p95 延遲整理（分階段）、凍結 MVP | `failure_analysis.py`、`src/control/release.py` |
| D5 | 備份可執行版本與原始紀錄 | `release.py backup`、`exports/` |

其他修改：

- 規則端（沈世翔已套用）：`GameState.get_reaction_actions`（含過水與可否榮和）、`action_phase`、`seats_to_act`、`result`、`winner_seats`、`check_card_conservation`；測試 `tests/test_boards_w8_queries.py`。
- `src/control/pipeline.py`：`get_reaction_rules_actions` 優先用規則端的新方法，沒有才退回舊的暫代版本；測試 `tests/test_reaction_adapter.py`。
- `test_interface/live_game.py`：`archive_old_logs`（同一個 game_id 的舊紀錄自動改名成 `.bak`）、`pause_diagnosis`（暫停時對照滑鼠點擊數、網頁收到數、評測器狀態）；`on_pause` 改成印診斷並存畫面（橘圈 = 前一次點擊，紅圈 = 最後一次）。
- `test_interface/table_page.py`：`user-select: none` 與 `dragstart` 阻擋（見第 4 節）。
- `.gitignore`：新增 `logs/*.bak`。
- `docs/integration/open_items.md`：規則區已完成的三項刪除；視覺區「改接 detector.py」與「輸出格式只留一種」改為已完成，只留還沒做的項目。

## 3. 實機結果（自製測試網頁）

| 批次 | seed 起點 | 局數 | 無介入完成 | 失敗步驟 | 重試 | UI 動作 | p95（ms） | 最大（ms） |
|---|---|---|---|---|---|---|---|---|
| w8_run1 | 2000 | 20 | 20 | 0 | 0 | 349 | 1139 | 1215 |
| w8_run2 | 3000 | 20 | 20 | 0 | 0 | 341 | 632 | 1210 |
| w8_run3 | 4000 | 20 | 20 | 0 | 0 | 346 | 1133 | 1213 |
| **合計** | — | **60** | **60** | **0** | **0** | **1,036** | 各批 ≤ 1139 | 1215 |

- 操作樣本 1,036 次，超過企劃書要求的 1,000 次；全部成功，失敗為 0。
- 三批合併的 p95 不會超過各批 p95 的最大值（1139 ms），預算為 2000 ms。
- 分階段：`my_turn`（單一點擊）p95 1144／404／1152 ms，`reaction` p95 628／645／636 ms。
- 重複點擊、點擊送達（網頁收到數 = 滑鼠點擊數）、評測器對照三項，以各批 `logs/<batch_id>.batch.json` 為準（**待核對**）：

```powershell
$r = "w8_run1","w8_run2","w8_run3" | ForEach-Object { Get-Content "logs\$_.batch.json" -Raw | ConvertFrom-Json }
$r | Select-Object batch_id, games, unattended_games, ui_actions, ui_success, extra_clicks, page_mismatch_games, truth_unchecked_games, latency_p95_ms
```

## 4. 遇到的問題與處理

| 問題 | 原因 | 處理 |
|---|---|---|
| 批次中途 `NOT_ADVANCED` 暫停 | 診斷顯示滑鼠點 15 次、網頁只收到 14 次，最後一次（牌 7）沒送到。測試網頁的牌是文字，連續快速點擊被瀏覽器當成選取文字，`click` 沒觸發 | 測試網頁加 `user-select: none` 與 `dragstart` 阻擋；Agent 與規則都沒有問題。真實遊戲是 canvas，不會發生 |
| 畫面驗證給了「假成功」 | 文字被選取會讓 ROI 內像素變化，驗證誤以為點擊有效 | 由遊戲層級的 `NOT_ADVANCED` 檢查攔下，沒有重複點擊；這道檢查保留 |
| 重跑同一個 `--batch-id` 時，原本正常的局被標成「有介入或未完成」 | JSONL 是 append 模式，舊檔被接續寫入，`event_id` 重複，`check_order` 報錯。（當時未另外確認是這個原因，但這是會發生的問題） | `archive_old_logs` 自動把舊的 `.jsonl`、`.game.json`、暫停截圖改名成 `.bak` |

統計口徑沒有改（見 `w7_notes.md` 第 3 節）。失敗一律留在分母，沒有用重試或放寬驗證去掩蓋。

## 5. 觀察（不影響達標）

- 最慢的動作幾乎都是 `my_turn`，且集中在 1190～1215 ms，像是固定的等待上限，不像偶發卡住。
- w8_run2 的 `my_turn` p95 只有 404 ms，w8_run1 與 w8_run3 卻是 1144／1152 ms，原因還沒查。
- 若要壓低延遲，可考慮縮小驗證 ROI 或降低 `--stable-frames`，要在真實遊戲上重新量過再決定。

## 6. 凍結與備份（待執行）

建議順序：

```powershell
python -m pytest -v
git add -A
git commit -m "W8: MVP freeze"
python -m src.control.release freeze --version mvp-v1
python -m src.control.release verify
python -m src.control.release backup --version mvp-v1 --with-data
git add docs/integration/mvp_manifest.json
git commit -m "W8: add mvp manifest"
```

- 凍結清單：`docs/integration/mvp_manifest.json`（版本、時間、git commit、套件版本、每個檔案 sha256、模板雜湊）。
- 備份 zip：`exports/mvp-v1.zip`；`exports/` 被 gitignore，不會進 Git。
- 清單的雜湊是逐位元組計算，Windows 若啟用 git autocrlf，`verify` 可能誤報「改動」，遇到時再改成忽略換行差異。

## 7. 尚未做／限制

- 以上結果都是自製測試網頁，不是真實遊戲；W14 的正式驗收要在固定環境重跑（≥ 1,000 次 UI 動作、20 局 × 3 批、p95 ≤ 2 秒）。
- 真實遊戲的反應按鈕偵測、可否點擊資訊還沒有（視覺待提供，見 `open_items.md`）。
- 重試前重新擷取並重新映射牌框：測試網頁用不到，真實遊戲打牌後手牌會左移才需要。
- 過水狀態 Agent 仍看不到，只能靠畫面上按鈕有沒有亮（`only_visible_buttons`）。
- `rules.GameState` 與 `common.schemas.GameState` 兩套結構沒有轉換，建議 MVP 凍結後與規則端一起討論。
- 失敗分析工具一批一批各自列出，不會自動合併多批的總操作數。

## 8. 待其他成員確認

見 `docs/integration/open_items.md`（W8 版）。W9 開始前建議先問策略：checkpoint 格式、三種槓在 action space 是否分開。