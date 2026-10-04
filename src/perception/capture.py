import os
import cv2
import json
import numpy as np
from src.perception.screen_capture import capture_screen

# 模板是從這個寬度的畫面裁切的（見 docs/perception/capture_spec.md：3543 x 1981）
BASE_WIDTH = 3543


def run_perception_matching(image_path=None, templates_dir="data/samples", frame=None, scale_templates=True):
    """
    執行 OpenCV 模板比對並輸出 Observation JSON 結構

    影像來源優先順序：
      1. frame：呼叫端直接傳入的 BGR 影像（例如整合端 ScreenCapture.grab() 的結果）
      2. image_path：圖檔路徑
      3. 以上都沒有 -> 用 MSS 擷取整個螢幕

    scale_templates：
      模板是 BASE_WIDTH 寬的畫面裁切的，matchTemplate 不具縮放不變性。
      畫面寬度不同（例如 2880）時，自動把模板依寬度比例縮放後再比對。
      輸出的 bbox 座標與 window_size 都是「傳入畫面」的座標。
    """
    # 1. 取得影像來源 (傳入畫面 / 檔案 / 即時螢幕)
    if frame is not None:
        # ScreenCapture.grab() 去掉 alpha 後不是連續記憶體，統一轉成連續陣列
        img_rgb = np.ascontiguousarray(frame)
    elif image_path and os.path.exists(image_path):
        img_rgb = cv2.imread(image_path)
    else:
        print("未指定圖片或找不到檔案，開啟 MSS 即時螢幕擷取...")
        img_rgb = capture_screen()

    if img_rgb is None:
        print("無法取得畫面來源！")
        return

    h_img, w_img, _ = img_rgb.shape

    # 模板縮放比例（畫面寬度與基準寬度差 1% 以內就不縮放）
    scale = w_img / BASE_WIDTH if scale_templates else 1.0
    need_resize = abs(scale - 1.0) > 0.01

    # 2. 定義 ROI 區域 (座標比例)
    # 手牌區 (完全完美，保持原樣)
    hand_y1, hand_y2 = int(h_img * 0.73), int(h_img * 0.95)
    hand_x1, hand_x2 = int(w_img * 0.00), int(w_img * 0.93)
    hand_roi = img_rgb[hand_y1:hand_y2, hand_x1:hand_x2]

    # 河牌區 (往上拉高 5%，避免切掉頂部，並往上收 3% 避開手牌干擾)
    river_y1, river_y2 = int(h_img * 0.15), int(h_img * 0.67)
    river_x1, river_x2 = int(w_img * 0.10), int(w_img * 0.90)
    river_roi = img_rgb[river_y1:river_y2, river_x1:river_x2]

    # 儲存除錯圖片
    os.makedirs("data/processed", exist_ok=True)
    cv2.imwrite("data/processed/hand_roi_debug.png", hand_roi)
    cv2.imwrite("data/processed/river_roi_debug.png", river_roi)

    detected_cards = []

    # 3. 模板比對
    if os.path.exists(templates_dir):
        for template_name in os.listdir(templates_dir):
            template_path = os.path.join(templates_dir, template_name)
            template = cv2.imread(template_path)
            if template is None:
                continue

            if need_resize:
                template = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

            h, w = template.shape[:2]

            if hand_roi.shape[0] < h or hand_roi.shape[1] < w:
                continue

            res = cv2.matchTemplate(hand_roi, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)

            if max_val > 0.6:
                card_name = os.path.splitext(template_name)[0]
                real_x = max_loc[0] + hand_x1
                real_y = max_loc[1] + hand_y1

                detected_cards.append({
                    "card": card_name,
                    "bbox": [real_x, real_y, w, h],
                    "confidence": round(float(max_val), 4)
                })

    observation = {
        "window_size": [w_img, h_img],
        "detected_cards": detected_cards
    }

    return observation


if __name__ == "__main__":
    result = run_perception_matching()
    print(json.dumps(result, indent=2, ensure_ascii=False))