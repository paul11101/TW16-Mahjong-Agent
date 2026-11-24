import json
import os
import cv2
from src.perception.detector import MahjongDetector

def _extract_center(item):
    """從偵測物件中提取中心點擊座標 [center_x, center_y]，相容 bbox 或 x/y/w/h 格式"""
    if "center" in item and isinstance(item["center"], (list, tuple)) and len(item["center"]) == 2:
        return [int(item["center"][0]), int(item["center"][1])]
    if "bbox" in item and isinstance(item["bbox"], (list, tuple)) and len(item["bbox"]) == 4:
        x, y, w, h = item["bbox"]
        return [int(x + w / 2), int(y + h / 2)]
    if all(k in item for k in ("x", "y", "w", "h")):
        return [int(item["x"] + item["w"] / 2), int(item["y"] + item["h"] / 2)]
    return [0, 0]

def format_state_for_agent(full_state):
    """
    將感知模組輸出的狀態，轉化為策略層 (Strategy) 與控制層 (Control) 可以直接使用的標準 JSON
    """
    is_valid = full_state.get("validity", {}).get("is_valid", False)
    is_stable = full_state.get("verification", {}).get("is_stable", True)
    is_animating = full_state.get("is_animating", False)

    hand_cards = full_state.get("hand_cards", [])
    action_buttons = full_state.get("action_buttons", [])

    return {
        "status": {
            "is_my_turn": full_state.get("is_my_turn", False),
            "in_settlement": full_state.get("in_settlement", False),
            "is_animating": is_animating,
            "is_stable": is_stable,
            "can_act": bool(is_valid and is_stable and not is_animating)
        },
        "tiles": {
            "hand": [card["name"] for card in hand_cards],
            "flowers": [card["name"] for card in full_state.get("flower_cards", [])],
            "river": [card["name"] for card in full_state.get("river_cards", [])],
            "melds": [card["name"] for card in full_state.get("melds", [])]
        },
        "actions": [btn["name"] for btn in action_buttons],
        "clickable_targets": {
            "hand": [
                {"tile": card["name"], "center": _extract_center(card)}
                for card in hand_cards
            ],
            "actions": {
                btn["name"]: _extract_center(btn)
                for btn in action_buttons
            }
        },
        "validity": full_state.get("validity", {})
    }

if __name__ == "__main__":
    detector = MahjongDetector(template_dir="data/samples", threshold=0.60)
    test_img_path = os.path.join("data", "raw", "game_stream_02", "frame_0012.png")
    if not os.path.exists(test_img_path):
        test_img_path = os.path.join("data", "raw", "test_05.png")

    if os.path.exists(test_img_path):
        image = cv2.imread(test_img_path)
        full_state = detector.detect_full_state(image)

        # 轉成 Agent 格式並印出漂亮格式的 JSON
        agent_json = format_state_for_agent(full_state)
        print(f"感知介面適配器 (Adapter) 輸出測試 [{os.path.basename(test_img_path)}]：\n")
        print(json.dumps(agent_json, indent=2, ensure_ascii=False))
    else:
        print(f"[Error] 找不到測試圖片: {test_img_path}")