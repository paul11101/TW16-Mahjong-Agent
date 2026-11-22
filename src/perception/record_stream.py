import os
import time
import cv2
from src.perception.screen_capture import capture_screen

def record_frames(save_dir="data/raw/game_stream_02", count=45, interval=0.6):
    os.makedirs(save_dir, exist_ok=True)
    print(f"=== 準備開始連拍採樣（共 {count} 張，間隔 {interval} 秒）===")
    print("請在 3 秒內切換到遊戲視窗...")
    time.sleep(3)

    for i in range(1, count + 1):
        frame = capture_screen(monitor_number=1)
        filename = os.path.join(save_dir, f"frame_{i:04d}.png")
        cv2.imwrite(filename, frame)
        print(f"[{i}/{count}] 已儲存：{filename}")
        time.sleep(interval)

    print(f"\n=== 採樣完成！共 {count} 張影像已存入 {save_dir} ===")

if __name__ == "__main__":
    record_frames(count=45, interval=0.6)