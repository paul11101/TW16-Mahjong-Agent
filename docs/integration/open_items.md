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
已完成：只用 `detector.py`（輸出含 `confidence`／`margin`／`low_confidence`），整合端以 `src/control/vision_adapter.py` 轉接，視覺輸出與策略 `Observation` 的轉換由整合端負責。

- `perception/capture.py`、`card_recognizer.py`、`screen_capture.py` 已不使用，請標記廢棄或刪除（刪之前通知整合端：`check_mapping --vision`、`tile_mapper.boxes_from_observation`、`tests/test_perception_frame.py` 要一起改）
- `roi_spec.md`、`observation_spec.md` 仍是舊格式與舊門檻（0.2），請改成 `detector.py` 的實際輸出與門檻
- 真實畫面反應按鈕：`action_buttons` 要能穩定偵測，並提供可不可點（整合端轉成 `ButtonBox`）