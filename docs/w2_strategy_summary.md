# W2 Strategy Progress

## 本週完成

- 完成 Rules GameState → Strategy Observation Adapter
- 完成 Rules Action → Strategy LegalAction Adapter
- 建立 Observation Encoder
- 將牌局狀態編碼成固定 555 維特徵
- 建立固定 125 維 Action Space
- 建立 Action Mask
- 完成 GameState → Strategy → Decision 最小串接測試

## 目前策略流程

Rules GameState
→ Adapter
→ Strategy Observation
→ Encoder
→ 555 維 Features

Rules Action
→ Adapter
→ LegalActions
→ Action Mask
→ 125 維 Mask

Observation + LegalActions
→ BaselinePolicy
→ Decision

## 待處理

- 等待 common schemas 共用介面正式統一
- Strategy Adapter 配合 common 欄位調整
- W3 加入牌效率與向聽相關特徵
- 建立更完整的固定牌型測試