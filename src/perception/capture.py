import os
import cv2
import json

def run_perception_matching(image_path="data/raw/test_01.png", templates_dir="data/samples"):
    """
    執行 OpenCV 模板比對並輸出 Observation JSON 結構
    """
    if not os.path.exists(image_path):
        print(f"找不到測試圖片：{image_path}")
        return

    img_rgb = cv2.imread(image_path)
    detected_cards = []

    if os.path.exists(templates_dir):
        for template_name in os.listdir(templates_dir):
            template_path = os.path.join(templates_dir, template_name)
            template = cv2.imread(template_path)
            if template is None:
                continue
            
            h, w = template.shape[:2]
            res = cv2.matchTemplate(img_rgb, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            
            # 使用固定門檻過濾 (max_val > 0.2)
            if max_val > 0.2:
                card_name = os.path.splitext(template_name)[0]
                detected_cards.append({
                    "card": card_name,
                    "bbox": [max_loc[0], max_loc[1], w, h],
                    "confidence": round(float(max_val), 4)
                })

    observation = {
        "window_size": [img_rgb.shape[1], img_rgb.shape[0]],
        "detected_cards": detected_cards
    }
    
    return observation

if __name__ == "__main__":
    result = run_perception_matching()
    print(json.dumps(result, indent=2, ensure_ascii=False))