import mss
import numpy as np
import cv2

def capture_screen(monitor_number=1):
    """
    使用 MSS 擷取全螢幕即時畫面 (支援全螢幕遊戲與單螢幕作業)
    """
    with mss.MSS() as sct:
        monitors = sct.monitors
        if monitor_number >= len(monitors):
            monitor_number = 1
            
        monitor = monitors[monitor_number]
        sct_img = sct.grab(monitor)
        
        img_np = np.array(sct_img)
        img_bgr = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
        
        return img_bgr

if __name__ == "__main__":
    print("開始測試即時螢幕擷取...")
    img = capture_screen()
    print(f"擷取成功！畫面解析度為：{img.shape[1]}x{img.shape[0]}")
    cv2.imwrite("data/raw/realtime_capture_test.png", img)
    print("已儲存即時截圖至 data/raw/realtime_capture_test.png")