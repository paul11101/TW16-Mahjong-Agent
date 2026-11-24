# VLOG-BC 批次資料生成 v1

本流程以固定 seed、對手池權重、規則版本及資料生成版本產生 JSONL 分片，並逐片驗證。相同程式版本、相同設定與 seed 可重現相同對局流程。

## 版本與設定

- `DATA_GEN_VERSION`: `1.0.0`，由生成器與驗證器共用，並寫入每筆決策紀錄。
- `RULESET_VERSION`: `1.0.0`，需與凍結的台麻規則一致。
- 對手池設定：[configs/opponent_pool_v1.json](../configs/opponent_pool_v1.json)。數值是相對抽樣權重，不要求加總為 1；每個座位各自依比例抽選。
- 每局使用 `base_seed + 局序號` 作為種子，四個座位的風格由該局 seed 決定並記錄在 `game_metadata.bot_styles`。

| 風格 | 對手池權重 | baseline | 向聽推進 | 吃偏好 | 碰偏好 | 槓偏好 | 保留字牌 | 保留安全牌 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `aggressive` | 1.0 | 0.25 | 1.0 | 2.0 | 2.0 | 1.5 | 0.0 | 0.0 |
| `menzen_defensive` | 1.0 | 0.5 | 0.5 | -2.0 | -1.5 | -0.5 | 1.0 | 2.0 |
| `balanced` | 1.0 | 1.0 | 0.25 | 0.25 | 0.25 | 0.25 | 0.1 | 0.25 |

「對手池權重」控制該風格被抽中的相對機率；其餘策略權重是 `BotStyleConfig` 的行為偏好。負的鳴牌偏好降低該動作排序，並不會產生或放行非法動作。

## 標準生成

從 repository 根目錄執行。輸出目錄必須尚不存在同名分片；生成器不覆寫既有檔案，建議每批使用新的輸出目錄。

```powershell
python .\scripts\generate_batch_data.py `
  --num-games 10000 `
  --batch-size 100 `
  --base-seed 20261125 `
  --output-dir .\data\batch_vlog_bc_v1 `
  --opponent-pool-config .\configs\opponent_pool_v1.json
```

每個 `.jsonl` 分片最多包含 `batch-size` 局；不足一批的最後分片仍會寫出。要確認腳本版本可執行：

```powershell
python .\scripts\generate_batch_data.py --version
python .\scripts\validate_dataset.py --version
```

若要重跑相同資料，保留相同的 generator 版本、規則版本、權重設定檔內容、局數、批次大小與 `base_seed`，並使用乾淨的輸出目錄。JSONL 會記錄每筆決策所用的規則／資料生成版本、seed、策略版本、Bot 風格、Observation、legal actions 與 action；每局最後一筆另含終局結算摘要。

## 一致性驗證

逐片執行 validator；只要任一分片回傳非零狀態碼，就應阻擋該批資料進入訓練：

```powershell
$files = @(Get-ChildItem .\data\batch_vlog_bc_v1 -Filter 'vlog_bc_batch_*.jsonl' | Sort-Object Name)
if ($files.Count -eq 0) { throw '找不到 JSONL 分片' }
foreach ($file in $files) {
    python .\scripts\validate_dataset.py $file.FullName
    if ($LASTEXITCODE -ne 0) { throw "資料驗證失敗：$($file.Name)" }
}
```

通過標準為 **0 個錯誤**。驗證器逐筆檢查：

1. `data_gen_version` 與 `ruleset_version` 均存在且符合目前版本。
2. `action` 與 `legal_actions` 欄位形狀正確，且所選 action 與清單中項目完全相同。
3. Observation 僅包含模型 `Observation` schema 的可見欄位，沒有牌牆或他家暗手牌等額外欄位；特徵編碼維度為 555。
4. 每局紀錄連續且 `decision_id` 由 0 遞增；終局摘要只在最後一筆，決策數、WIN 座位、四家分數與結算資料一致。
5. JSONL 每列均可作為 UTF-8 JSON 讀取，並符合欄位與型別規範。

## JSONL 紀錄範例

以下為單筆紀錄形狀範例；實際資料每局會有多筆決策，只有最後一筆包含 `game_metadata.terminal`。

```json
{
  "data_gen_version": "1.0.0",
  "game_id": "evaluation_20261125_0",
  "decision_id": "0",
  "base_seed": 20261125,
  "bot_style": "aggressive",
  "game_metadata": {
    "seat_names": ["east", "south", "west", "north"],
    "bot_styles": ["aggressive", "balanced", "menzen_defensive", "aggressive"],
    "terminal": {
      "completed": true,
      "decision_count": 1,
      "result": {
        "round_number": 1,
        "round_label": "東風場第 1 局",
        "round_wind": 0,
        "dealer_seat": 0,
        "lianzhuang_count": 0,
        "winner_seats": [],
        "loser_seat": null,
        "win_type": "draw",
        "total_fans": null,
        "fan_details": [],
        "winner_fan_results": {},
        "score_delta": {"0": 0, "1": 0, "2": 0, "3": 0},
        "scores_dict": {"0": 20000, "1": 20000, "2": 20000, "3": 20000}
      }
    }
  },
  "observation": {
    "hand": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    "melds": [[], [], [], []],
    "flowers": [[], [], [], []],
    "discards": [[], [], [], []],
    "remaining_tiles": 50,
    "current_player": 0,
    "seat": 0,
    "round_wind": 0,
    "seat_wind": 0
  },
  "legal_actions": [
    {"id": "discard-0", "action": "discard", "tile": 0, "tiles": [], "kong_type": null}
  ],
  "action": {
    "id": "discard-0",
    "action": "discard",
    "tile": 0,
    "tiles": [],
    "kong_type": null
  },
  "ruleset_version": "1.0.0",
  "strategy_version": "baseline_style_wrapper_v1"
}
```
