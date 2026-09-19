# ROI 與模板比對說明 (ROI & Matching Spec)

## 1. 演算法機制
* **比對核心**：使用 OpenCV `cv2.matchTemplate` 演算法。
* **計算方式**：對全螢幕遊戲畫面與模板圖進行矩陣滑動比對。
* **門檻設定**：計算相似度分數 `max_val`，並以固定門檻 (`max_val > 0.2`) 進行牌型過濾與定位。

## 2. 視覺比對程式碼骨架
```python
import os
import cv2
import json

# 1. 讀取固定測試截圖與模板目錄
img_rgb = cv2.imread('data/raw/test_01.png')
templates_dir = 'data/samples'

detected_cards = []

for template_name in os.listdir(templates_dir):
    template_path = os.path.join(templates_dir, template_name)
    template = cv2.imread(template_path)
    if template is None:
        continue
    h, w = template.shape[:2]
    
    res = cv2.matchTemplate(img_rgb, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    
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
print(json.dumps(observation, indent=2))
```

## 3. 比對過程驗證
可在 Terminal 輸出各模板之最高相似度數值與座標位置。

![Day 4 比對測試](./images/day4.png)