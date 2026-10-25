import json
import os
import cv2
from src.perception.detector import MahjongDetector

def format_state_for_agent(full_state):
    """
    將感知模組輸出的狀態，轉化為策略層（Strategy）與規則層（Rules）可以直接使用的標準 JSON
    """
    return {
        "status": {
            "is_my_turn": full_state.get("is_my_turn", False),
            "in_settlement": full_state.get("in_settlement", False),
            "is_animating": full_state.get("is_animating", False),
            "is_stable": full_state.get("verification", {}).get("is_stable", True)
        },
        "tiles": {
            "hand": [card["name"] for card in full_state.get("hand_cards", [])],
            "flowers": [card["name"] for card in full_state.get("flower_cards", [])],
            "river": [card["name"] for card in full_state.get("river_cards", [])],
            "melds": [card["name"] for card in full_state.get("melds", [])]
        },
        "actions": [btn["name"] for btn in full_state.get("action_buttons", [])],
        "validity": full_state.get("validity", {})
    }

if __name__ == "__main__":
    detector = MahjongDetector(template_dir="data/samples", threshold=0.60)
    test_img_path = os.path.join("data", "raw", "test_05.png")

    if os.path.exists(test_img_path):
        image = cv2.imread(test_img_path)
        full_state = detector.detect_full_state(image)
        
        # 轉成 Agent 格式並印出漂亮格式的 JSON
        agent_json = format_state_for_agent(full_state)
        print("🚀 感知介面適配器 (Adapter) 輸出測試：\n")
        print(json.dumps(agent_json, indent=2, ensure_ascii=False))
    else:
        print(f"[Error] 找不到測試圖片: {test_img_path}")