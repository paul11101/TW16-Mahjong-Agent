import cv2
import numpy as np
import mss
import os
import glob

class MahjongDetector:
    def __init__(self, template_dir="data/samples", threshold=0.8):
        """
        初始化 MahjongDetector
        :param template_dir: 存放麻將牌模板圖片的資料夾路徑
        :param threshold: 模板比對的信心度門檻 (0.0 ~ 1.0)
        """
        self.sct = mss.mss()
        self.threshold = threshold
        self.template_dir = template_dir
        self.templates = {}
        
        # 載入所有麻將牌模板
        self.load_templates()

    def load_templates(self):
        """
        從指定資料夾載入所有麻將牌模板檔 (例如 1t.png, 5w.png, white.png 等)
        """
        if not os.path.exists(self.template_dir):
            os.makedirs(self.template_dir)
            print(f"[Warning] 模板資料夾 '{self.template_dir}' 不存在，已自動建立。請放入麻將模板圖片。")
            return

        types = ('*.png', '*.jpg', '*.jpeg')
        files_grabbed = []
        for ext in types:
            files_grabbed.extend(glob.glob(os.path.join(self.template_dir, ext)))

        for file_path in files_grabbed:
            # 以檔名作為牌名 (例如 "templates/1w.png" -> card_name = "1w")
            card_name = os.path.splitext(os.path.basename(file_path))[0]
            template_img = cv2.imread(file_path, cv2.IMREAD_COLOR)
            if template_img is not None:
                self.templates[card_name] = template_img
            else:
                print(f"[Error] 無法讀取模板檔案: {file_path}")

        print(f"[Info] 成功載入 {len(self.templates)} 個麻將牌模板。")

    def capture_roi(self, roi_bbox):
        """
        擷取指定的螢幕 ROI 區域
        :param roi_bbox: dict, 例如 {'top': 100, 'left': 200, 'width': 800, 'height': 150}
        :return: BGR 格式的 numpy array 影像
        """
        sct_img = self.sct.grab(roi_bbox)
        # mss 抓取的影像預設為 BGRA，需轉為 BGR
        frame = np.array(sct_img)
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    def detect_cards(self, image):
        """
        在給定的影像區域中，比對所有模板並回傳辨識到的牌種與座標
        :param image: BGR 格式的 numpy array
        :return: list of dict, 例如 [{'card': '1w', 'bbox': (x, y, w, h), 'confidence': 0.85}, ...]
        """
        if not self.templates:
            return []

        detected_results = []

        for card_name, template in self.templates.items():
            t_h, t_w = template.shape[:2]
            
            # 使用 TM_CCOEFF_NORMED 進行歸一化相關係數比對
            res = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= self.threshold)

            for pt in zip(*loc[::-1]):  # pt 為 (x, y)
                confidence = float(res[pt[1], pt[0]])
                detected_results.append({
                    'card': card_name,
                    'bbox': (pt[0], pt[1], t_w, t_h),
                    'confidence': confidence
                })

        # 消除重複重疊的 Bounding Box (Non-Maximum Suppression)
        final_results = self._suppress_overlaps(detected_results)
        
        # 依據 X 軸座標排序（從左至右排序玩家手牌）
        final_results.sort(key=lambda item: item['bbox'][0])
        
        return final_results

    def _suppress_overlaps(self, results, iou_threshold=0.3):
        """
        非極大值抑制 (NMS)，防止同張牌被重複框選
        """
        if not results:
            return []

        boxes = np.array([r['bbox'] for r in results])
        scores = np.array([r['confidence'] for r in results])

        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 0] + boxes[:, 2]
        y2 = boxes[:, 1] + boxes[:, 3]

        areas = (x2 - x1) * (y2 - y1)
        order = scores.argsort()[::-1]

        keep = []
        while order.size > 0:
            i = order[0]
            keep.append(i)

            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])

            w = np.maximum(0.0, xx2 - xx1)
            h = np.maximum(0.0, yy2 - yy1)
            inter = w * h

            ovr = inter / (areas[i] + areas[order[1:]] - inter)
            inds = np.where(ovr <= iou_threshold)[0]
            order = order[inds + 1]

        return [results[k] for k in keep]

    def draw_detections(self, image, detections):
        """
        將辨識結果繪製在影像上以供實時 Debug
        """
        debug_img = image.copy()
        for item in detections:
            x, y, w, h = item['bbox']
            label = f"{item['card']} ({item['confidence']:.2f})"
            
            # 畫框
            cv2.rectangle(debug_img, (x, y), (x + w, y + h), (0, 255, 0), 2)
            # 標註標籤
            cv2.putText(debug_img, label, (x, max(y - 5, 15)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        return debug_img


# ==========================================
# 測試與除錯模組 (Direct Execution Setup)
# ==========================================
if __name__ == "__main__":
    # 初始化辨識器
    detector = MahjongDetector(template_dir="data/samples", threshold=0.8)

    # 範例 ROI 座標（請根據你實際畫面的比例進行調整）
    # 例如：玩家手牌區域
    HAND_CARD_ROI = {
        'top': 800,
        'left': 400,
        'width': 1100,
        'height': 180
    }

    print("開始實時偵測... 按下 'q' 可結束測試。")

    while True:
        # 1. 擷取手牌 ROI 區域
        frame = detector.capture_roi(HAND_CARD_ROI)

        # 2. 進行麻將牌辨識
        detections = detector.detect_cards(frame)

        # 3. 印出目前偵測到的手牌列表（按 X 座標排序）
        current_hand = [item['card'] for item in detections]
        print(f"\r目前手牌: {current_hand} (共 {len(current_hand)} 張)", end="")

        # 4. 繪製 Debug 框並顯示
        debug_frame = detector.draw_detections(frame, detections)
        cv2.imshow("Hand Cards ROI Debug", debug_frame)

        # 按 'q' 鍵退出測試
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cv2.destroyAllWindows()