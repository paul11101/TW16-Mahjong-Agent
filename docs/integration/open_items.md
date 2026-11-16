# 整合端等隊友確認的缺口（W8 快照）

隊友改好後刪除對應的行。整合端已有暫時轉接的，標在括號裡。

## 規則（沈世翔）
- `rules.GameState` 與 `common.schemas.GameState` 是兩套結構、沒有轉換；`game_state.EventType` 與 `common.events.EventType` 同名（建議 MVP 凍結後再一起討論）

已完成（W8，已由規則端套用）：`GameState.get_reaction_actions`（含過水與可否榮和）、`action_phase`／`seats_to_act`／`result`／`winner_seats`、`check_card_conservation`。整合端 `pipeline.get_reaction_rules_actions` 已優先使用，找不到才退回舊版。
注意：Agent 端的階段判斷仍用畫面（`web_observer.classify_view`／`VisionObserver`），`action_phase` 只給評測器與 SimTable 對照真值，不屬於缺口。

## 策略（李品劭）
- 三種槓在 `action_mask.py` 共用同一個 index（同一次決策不會同時出現，但模型 action space 要分開，見 `docs/vlog_review.md`）；整合端已在 JSONL 補 `parameters.kong_type`
- `FLOWER_REPLACEMENT`、`DRAW_TILE` 進 `action_to_index` 會拋 `ValueError`（玩家決策不會出現，轉資料集時要先濾掉）

## 視覺（李佳興）
- `perception/capture.py` 每種牌只回一個 bbox（重複牌會漏），每次呼叫都重讀 42 張模板並寫 debug 圖；建議整合端改接 `detector.py`
- 三種輸出格式（`capture.py` 的 `detected_cards`、`detector.py` 的 `hand_cards`、`card_recognizer.py`）請定最終只用一種，且每張牌都要有 `confidence`
- 門檻不一致：`roi_spec.md` 寫 0.2，`capture.py` 用 0.6，`detector.py` 手牌 0.60、花牌 0.48
- `perception/screen_capture.py` 與 `control/capture.py` 功能重複，只留一個
- 視覺輸出與策略 `Observation` 之間沒有轉換（整合端暫以 `vision_adapter.py` 轉接）
- 真實畫面要能判斷：輪到自己、反應按鈕位置（提供 `ButtonBox`）、牌局結束