import os
import cv2
import time
from src.perception.detector import MahjongDetector
from src.perception.adapter import format_state_for_agent

def evaluate_game_stream(stream_dir="data/raw/game_stream_01"):
    print("=" * 60)
    print(f"🎬 執行動態對局影格串流測試: {stream_dir}")
    print("=" * 60)

    if not os.path.exists(stream_dir):
        print(f"[Notice] 尚未找到資料夾: {stream_dir}")
        print("請建立資料夾並放入連續截圖影格（如 frame_001.png, frame_002.png...）")
        return

    img_files = sorted([f for f in os.listdir(stream_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
    
    if not img_files:
        print(f"[Notice] {stream_dir} 資料夾內目前尚無影格圖片。")
        return

    detector = MahjongDetector(template_dir="data/samples", threshold=0.60)
    
    total_frames = len(img_files)
    valid_count = 0
    stable_count = 0
    total_time_ms = 0.0

    for idx, fname in enumerate(img_files, start=1):
        fpath = os.path.join(stream_dir, fname)
        img = cv2.imread(fpath)
        
        raw_state = detector.detect_full_state(img)
        agent_json = format_state_for_agent(raw_state)
        
        cost_ms = raw_state['performance']['cost_time_ms']
        total_time_ms += cost_ms
        
        is_stable = agent_json['status']['is_stable']
        is_valid = agent_json['validity']['is_valid']

        if is_stable:
            stable_count += 1
        if is_valid:
            valid_count += 1

        print(f"影格 [{idx}/{total_frames}] {fname} | 耗時: {cost_ms:.1f}ms | 穩定: {is_stable} | 合法: {is_valid}")

    avg_latency = total_time_ms / total_frames if total_frames > 0 else 0
    print("=" * 60)
    print(f"📊 連續影格評測總結:")
    print(f"  * 總分析影格數: {total_frames}")
    print(f"  * 平均單幀延遲: {avg_latency:.2f} ms ({1000/avg_latency:.1f} FPS)")
    print(f"  * 影格穩定率: {stable_count / total_frames * 100:.1f}% ({stable_count}/{total_frames})")
    print(f"  * 狀態合法率: {valid_count / total_frames * 100:.1f}% ({valid_count}/{total_frames})")
    print("=" * 60)

if __name__ == "__main__":
    evaluate_game_stream()