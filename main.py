import cv2
import json
import time
from src.perception.detector import MahjongDetector
from src.perception.screen_capture import capture_screen

def build_action_payload(raw_state):
    """
    [W8 Day 5 跨模組標準介面]
    將底層視覺結果過濾並轉換為決策與自動點擊模組（宇）可直接讀取的乾淨 JSON 格式
    """
    validity = raw_state.get("validity", {})
    verification = raw_state.get("verification", {})
    
    is_valid = validity.get("is_valid", False)
    is_stable = verification.get("is_stable", False)
    is_my_turn = raw_state.get("is_my_turn", False)
    is_animating = raw_state.get("is_animating", False)
    
    # 安全閘門：手牌張數合法 + 輪到自己 + 無特效動畫遮擋
    can_act = is_valid and is_my_turn and (not is_animating)
    
    return {
        "can_act": can_act,
        "is_stable": is_stable,
        "hand": verification.get("verified_hand_names", []),
        "melds": [m["name"] for m in raw_state.get("melds", [])],
        "action_buttons": [b["name"] for b in raw_state.get("action_buttons", [])],
        "status_reasons": validity.get("reasons", [])
    }

def run_agent(mode="mock", max_ticks=3, interval=0.3):
    print("=== 台灣16張麻將自動對局 Agent 啟動 ===")
    detector = MahjongDetector(template_dir="data/samples", threshold=0.60)
    
    for tick in range(1, max_ticks + 1):
        # 1. 取得影像來源（即時螢幕擷取 vs 離線測試串流）
        if mode == "live":
            frame = capture_screen(monitor_number=1)
        else:
            # 模擬連續 3 幀讀取同一回合畫面，驗證滑動視窗穩定度
            frame = cv2.imread("data/raw/game_stream_01/frame_0018.png")
            
        if frame is None:
            print("[Error] 無法取得影像幀")
            break
            
        # 2. 視覺感知與狀態驗證
        raw_state = detector.detect_full_state(frame)
        payload = build_action_payload(raw_state)
        
        print(f"\n--- Tick [{tick}/{max_ticks}] (模式: {mode}) ---")
        print(json.dumps(payload, ensure_ascii=False))
        
        # 3. 預留給下游模組的串接點（決策與自動點擊）
        if payload["can_act"] and payload["is_stable"]:
            print(f"-> [Ready for Action] 狀態已鎖定，可交由決策與點擊模組執行！手牌數: {len(payload['hand'])}")
            
        time.sleep(interval)

if __name__ == "__main__":
    # 預設用 mock 模式驗證 3 幀滑動視窗與 JSON 輸出；開遊戲時可改為 mode="live"
    run_agent(mode="mock", max_ticks=3, interval=0.3)