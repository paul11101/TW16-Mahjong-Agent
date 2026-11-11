# 🀄 視覺感知模組規格說明書 (Perception Engine Spec v1.0)

本模組負責 TW16-Mahjong-Agent 的畫面影像解析，將即時遊戲畫面轉換為策略層（Strategy）與規則層（Rules）可直接利用的結構化 JSON 數據。

## 📁 模組架構說明 (Modular Architecture)
* **`detector.py`**：感知主引擎，負責全區域 ROI 劃分與比對邏輯調度。
* **`loader.py`**：靜態模板載入器，管理記憶體快取與單通道灰階轉換。
* **`utils.py`**：OpenCV 底層捲積比對工具庫與 NMS 1D 重疊壓制演算法。
* **`verifier.py`**：多幀穩定度過濾器與牌數合理性檢驗（State Validity）。
* **`adapter.py`**：資料轉譯適配器，輸出符合 Agent 規格之標準 JSON。
* **`pipeline_demo.py`**：模組內部全流程對接與轉譯測試示範進入點。
* **`evaluate_stream.py`**：動態對局連續影格評測與 stability 檢驗工具。

## 🔌 API 使用範例 (Quick Start)

```python
import cv2
from src.perception.detector import MahjongDetector
from src.perception.adapter import format_state_for_agent

# 1. 初始化感知引擎
detector = MahjongDetector(template_dir="data/samples", threshold=0.60)

# 2. 分析影像並轉譯為 JSON
image = cv2.imread("path/to/game_frame.png")
raw_state = detector.detect_full_state(image)
agent_json = format_state_for_agent(raw_state)

print(agent_json)