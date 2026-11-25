# 視覺感知模組交接規格書 (`Perception -> Strategy & Control`)

本模組負責從《愛台灣打麻將》畫面擷取盤面牌型、可用動作按鈕與螢幕點擊像素座標，輸出標準 JSON 供策略層（劭）與自動化點擊控制層（宇）調用。

## 1. 呼叫方式

```python
import cv2
from src.perception.detector import MahjongDetector
from src.perception.adapter import format_state_for_agent

detector = MahjongDetector(template_dir="data/samples", threshold=0.60)
raw_state = detector.detect_full_state(frame_bgr)
agent_state = format_state_for_agent(raw_state)
```

*(建議搭配 `MultiFrameVerifier` 進行連續影格驗證，確保 `status.can_act == True` 後再觸發點擊。)*

## 2. 交接核心欄位說明

| 欄位路徑 | 型別 | 說明與使用規範 |
| :--- | :--- | :--- |
| `status.can_act` | `bool` | **點擊安全鎖**。僅在通過多幀穩定驗證（非發牌／過渡動畫幀）時為 `true`，控制層必須檢查此旗標為 `true` 才允許操作滑鼠。 |
| `validity.is_valid` | `bool` | 盤面手牌張數符合台灣 16 張麻將合法規則（$3n+1$ 或 $3n+2$）。 |
| `tiles.hand` | `list[str]` | 目前手牌編號陣列（由左至右排序），供決策層判斷出牌或吃碰槓邏輯。 |
| `actions` | `list[str]` | 當前畫面偵測到的可執行動作按鈕（支援 `btn_chi`、`btn_peng`、`btn_gang`、`btn_ting`、`btn_hu`、`btn_zimo`、`btn_pass`）。 |
| `clickable_targets.hand` | `list[dict]` | 每張手牌對應的螢幕中心像素座標 `{"tile": "1", "center": [145, 1593]}`，決策層選定出牌對象後直接讀取 `center` 點擊。 |
| `clickable_targets.actions` | `dict` | 每顆動作按鈕的螢幕中心像素座標（例如 `{"btn_zimo": [2407, 1179], "btn_pass": [2798, 1224]}`），點擊模組直接查表執行點擊。 |

## 3. 實戰輸出範例（`game_stream_02/frame_00012.png` 自摸＋取消）

```json
{
  "status": {
    "is_my_turn": true,
    "in_settlement": false,
    "is_animating": false,
    "is_stable": false,
    "can_act": false
  },
  "tiles": {
    "hand": ["1", "2", "3", "8", "19", "20", "10", "6"],
    "flowers": [],
    "river": [],
    "melds": []
  },
  "actions": [
    "btn_zimo",
    "btn_pass"
  ],
  "clickable_targets": {
    "hand": [
      {"tile": "1", "center": [145, 1593]},
      {"tile": "2", "center": [327, 1591]},
      {"tile": "3", "center": [516, 1591]},
      {"tile": "8", "center": [878, 1591]},
      {"tile": "19", "center": [1264, 1591]},
      {"tile": "20", "center": [1445, 1590]},
      {"tile": "10", "center": [2176, 1580]},
      {"tile": "6", "center": [3116, 1590]}
    ],
    "actions": {
      "btn_zimo": [2407, 1179],
      "btn_pass": [2798, 1224]
    }
  },
  "validity": {
    "is_valid": true,
    "need_recap": false,
    "reasons": ["OK"]
  }
}
```