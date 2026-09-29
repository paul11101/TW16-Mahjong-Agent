import os
import cv2
import json
from src.perception.screen_capture import capture_screen

def run_perception_matching(image_path=None, templates_dir="data/samples"):
    """
    執行 OpenCV 模板比對並輸出 Observation JSON 結構
    """
    # 1. 取得影像來源 (檔案 或 即時螢幕)
    if image_path and os.path.exists(image_path):
        img_rgb = cv2.imread(image_path)
    else:
        print("未指定圖片或找不到檔案，開啟 MSS 即時螢幕擷取...")
        img_rgb = capture_screen()

    if img_rgb is None:
        print("無法取得畫面來源！")
        return

    h_img, w_img, _ = img_rgb.shape

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

            h, w = template.shape[:2]

            if hand_roi.shape[0] < h or hand_roi.shape[1] < w:
                continue

            res = cv2.matchTemplate(hand_roi, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)

            if max_val > 0.2:
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