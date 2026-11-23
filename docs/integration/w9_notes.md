# 整合 W9 筆記（盧冠宇）

## 1. 指令（專案根目錄，PowerShell）

| 用途 | 指令 |
|---|---|
| 模型轉接層測試 | `python -m tests.test_model_adapter` |
| 候選分數／策略版本／延遲量測函式測試 | `python -m tests.test_dashboard_candidates` |
| 全部 pytest | `python -m pytest -v` |
| 產生假 TorchScript 模型（流程驗證用） | `python -c "import torch; m=torch.nn.Linear(555,125); torch.jit.trace(m, torch.zeros(1,555)).save('models/fake.pt')"` |
| 檢查 checkpoint 形狀 | `python -c "import torch; m=torch.jit.load('models/bc_v1.pt', map_location='cpu').eval(); o=m(torch.zeros(1,555)); print(o.shape, o.dtype)"`（必須印出 `torch.Size([1, 125]) torch.float32`） |
| 決策耗時（baseline） | `python -m test_interface.measure_decision --games 20` |
| 決策耗時（模型） | `python -m test_interface.measure_decision --games 20 --policy model --checkpoint models\bc_v1.pt` |
| 批次實機（baseline，預設） | `python -m test_interface.run_batch --delay 3 --games 20 --seed-start 2000 --batch-id w9_base --policy baseline` |
| 批次實機（模型） | `python -m test_interface.run_batch --delay 3 --games 20 --seed-start 2000 --batch-id w9_bc_v1 --policy model --checkpoint models\bc_v1.pt` |
| dashboard | 瀏覽器開 `http://127.0.0.1:8000/dashboard`，點「最近對局」任一列看每步候選分數與策略版本 |

批次實機前：`uvicorn test_interface.app:app`，瀏覽器開 `http://127.0.0.1:8000/?scenario=game`（Ctrl+F5，不要最小化）。
`models/` 在 `.gitignore` 內，`bc_v1.pt` 要由李品劭直接傳檔，不會跟著 Git 同步。

## 2. W9 交付

| 日 | 項目 | 位置 |
|---|---|---|
| D1 | 模型推論 adapter（Observation + LegalActions -> logits -> Decision） | `src/control/model_adapter.py` |
| D2 | Bot 接入 TorchScript checkpoint | `TorchScriptBackend`；真 `bc_v1.pt` 已驗證 |
| D3 | baseline／模型切換；dashboard 顯示候選分數與策略版本 | `--policy`、`--checkpoint`（`live_game.py`）；`/api/game_record/{game_id}`（`app.py`）；`dashboard_page.py` |
| D4 | 記錄模型版本 | `strategy_version = model_<檔名>-<sha256 前 8 碼>`，寫進 JSONL `decision_made` 與每步 detail |
| D5 | 本機推論流程與延遲 | `measure_decision.py --policy model`，另存 `data/processed/decision_latency_model.json` |

修改既有檔案：`test_interface/live_game.py`、`test_interface/app.py`、`test_interface/dashboard_page.py`、`test_interface/measure_decision.py`、`src/control/game_runner.py`。
新增測試：`tests/test_model_adapter.py`（11 項）、`tests/test_dashboard_candidates.py`。

## 3. 設計規則

- 載入只走 `torch.jit.load(path, map_location="cpu").eval()`。`last.pt` 是訓練 checkpoint，不可載入。
- 輸入 `float32 [1, 555]`（`encode_observation()` 一次），輸出 `float32 [1, 125]` 原始 logits（模型內沒有 mask、softmax、log_softmax）。
- mask 由整合端處理一次：只看合法動作 index 的分數取最高，等同 mask 後 argmax。重複 index、長度不對、合法動作分數非有限值、不支援的動作，一律退回 baseline 並記錄次數與原因。
- `Decision.score` 放合法動作間的 softmax 機率（pipeline 會夾到 0~1 當 confidence）；候選分數保留原始 logit。baseline 分數是負向聽數，兩者尺度不同，dashboard 以「策略」欄區分。
- 三種槓共用 `89 + tile`，執行時用選中的 index 回查合法動作取得 `kong_type`。
- 啟動時載入失敗直接報錯，不悄悄換成 baseline，避免比較失真。只有推論當下出錯才退回 baseline。
- 摸牌、補花（`DRAW_TILE`、`FLOWER_REPLACEMENT`）不進策略，也不進 `action_to_index`。

## 4. 實測結果（自製測試網頁）

| 項目 | 結果 |
|---|---|
| 全部 pytest | 921 項通過（約 10 分 34 秒） |
| 假模型（隨機 Linear）決策 p95 | 0.4 ms |
| 假模型 `w9_fake`，2 局 | 無介入 2/2、UI 36/36、退回 baseline 0 次 |
| 真模型 `bc_v1` 決策 p95（421 次） | 0.3 ms（預算 300 ms），退回 baseline 0 次 |

### 20 局對照（seed 2000 起，兩批牌山相同）

| 項目 | w9_base（baseline） | w9_bc_v1（模型） |
|---|---|---|
| 無介入完成 | 20/20（待補） | 20/20 |
| UI 動作／成功 | （待補） | 435／435 |
| 重複點擊 | （待補） | 0 |
| 同步動作確認 p95 | （待補） | 409 ms（預算 2000 ms） |
| Agent 胡牌 | 13 | 1 |
| 流局 | 7 | 19 |

baseline 那批目前只貼了「胡牌／流局」那一行；其餘欄位請從 `logs\w9_base.batch.json` 補上（`Get-Content logs\w9_base.batch.json -Raw | ConvertFrom-Json | Select-Object batch_id, games, unattended_games, ui_actions, ui_success, extra_clicks, latency_p95_ms`）。

## 5. 發現：bc_v1 棄牌弱（非整合問題）

李品劭用種子 0~19 重現：

| 四家怎麼打 | 流局 |
|---|---|
| 全部 `bc_v1` | 19／20 |
| `bc_v1`，只有棄牌改由 baseline 選 | 1／20 |
| 全部 baseline | 0／20 |

- 有 20 次「只要打對一張就能進入或維持聽牌」，模型其中 14 次打完沒聽；整批只出現 1 次可胡的機會，模型當下就胡了。
- 結論：吃、碰、槓、胡沒問題，**棄牌是主要缺口**。整合端路徑（同一個 `ModelPolicy`）只換棄牌就恢復，排除整合問題。
- 整合報告寫「bc_v1 可接入、流程穩定」；牌力引用李品劭 W10 的 1,000 局評測，不拿這 20 局當證據。
- 建議策略端 W10 補向聽類特徵或加重聽牌局面的樣本權重，並把「聽牌維持率」列為評測指標。

## 6. 踩到的坑

| 問題 | 說明 |
|---|---|
| `torch.jit` 棄用警告 | 目前 torch 仍支援，只是 `FutureWarning`。若策略端改用 `torch.export` 或 ONNX，要先通知，整合端只需新增一個 backend 類別。 |
| 每局重建 policy | `run_batch` 每局都重新載入模型，第一次推論含暖機（w9_fake 第 1 局 p95 122.5 ms、第 2 局 2.4 ms）。正式 p95 看 `measure_decision` 暖機後的數字。 |
| 驗證 logits 的方法 | 對 `zeros(1,555)` 看最小值、最大值、總和無法判斷輸出格式，已作廢；以策略端的交付說明與匯出比對結果為準。 |

## 7. 統計口徑

- W9 這兩批只算整合驗證，**不計入** W14 的 ≥ 1,000 次 UI 動作分母；W14 要用最終正式策略重跑。
- 其餘口徑不變（見 `w7_notes.md` 第 3 節）。

## 8. 尚未做／限制

- W8 的凍結清單（`mvp_manifest.json`）已對不上現在的程式，`python -m src.control.release verify` 會報「改動」。策略端交付說明已收齊，是否凍結 `mvp-v1.1` 待決定。
- 「混合策略」（棄牌用 baseline、反應用模型）先不做，避免掩蓋模型真實表現、讓 W10 比較失真。
- W10 D3 的策略比較頁面：建議做成 dashboard 分頁，並排讀兩批 `.batch.json`。
- 真實遊戲的反應按鈕偵測與可否點擊資訊仍待視覺（見 `open_items.md`）。

## 9. 待其他成員確認

### 策略（李品劭）
已完成（W9）：`bc_v1.pt` 交付說明——輸出為 `float32 [B, 125]` 原始 logits（最後一層 Linear，無 softmax／log_softmax）；`torch.jit.load(map_location="cpu").eval()` 回讀與 `last.pt` 還原的模型比對，`B=1`、`B=4` 最大絕對誤差都是 0.0；匯出環境 PyTorch 2.14.0+cpu（事後依 `.venv` 與安裝紀錄核對，`training.json` 未記錄）。

- 匯出程式請直接把 `torch.__version__` 寫進 `training.json`。
- 若之後改匯出格式（`torch.export`、ONNX），要先通知。
- 下一版若把最後棄牌餵給模型，須同步更新訓練資料與推論編碼；整合端可提供反應事件裡的 `last_discard.player_id`、`tile_id`。
- 若要三種槓各自有分數，動作表、資料標籤、模型輸出要一起更新。