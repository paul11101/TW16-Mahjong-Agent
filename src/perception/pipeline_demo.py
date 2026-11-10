import os
import cv2
import json
from src.perception.detector import MahjongDetector
from src.perception.adapter import format_state_for_agent

def run_perception_pipeline():
    print("=" * 60)
    print("🚀 執行 Perception 模組內部全流程轉譯測試 (Detector -> Adapter)")
    print("=" * 60)

    # 1. 初始化感知引擎
    detector = MahjongDetector(template_dir="data/samples", threshold=0.60)
    
    # 2. 載入測試圖片
    raw_dir = os.path.join("data", "raw")
    test_img_path = os.path.join(raw_dir, "test_05.png")

    if not os.path.exists(test_img_path):
        print(f"[Error] 找不到測試圖片: {test_img_path}")
        return

    image = cv2.imread(test_img_path)
    
    # 3. 執行全區域感知辨識
    print(f"正在分析影格: {test_img_path} ...")
    raw_state = detector.detect_full_state(image)

    # 4. 透過 Adapter 轉譯為 Agent 標準 JSON 格式
    agent_input_json = format_state_for_agent(raw_state)

    print("\n✅ 成功生成傳遞予 Agent 策略層與規則層之標準數據 (JSON Input)：\n")
    print(json.dumps(agent_input_json, indent=2, ensure_ascii=False))
    print("=" * 60)
    print(f"⚡ 單幀感知總耗時: {raw_state['performance']['cost_time_ms']} ms ({raw_state['performance']['fps']} FPS)")
    print("=" * 60)

if __name__ == "__main__":
    run_perception_pipeline()