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
        self.sct = mss.MSS()
        self.threshold = threshold
        self.template_dir = template_dir
        self.templates = {}
        
        # 載入所有麻將牌模板
        self.load_templates()

    def load_templates(self):
        """
        從指定資料夾載入所有麻將牌模板檔
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
        """
        sct_img = self.sct.grab(roi_bbox)
        frame = np.array(sct_img)
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    def detect_cards(self, image):
        """
        在給定的影像區域中，比對所有模板並回傳辨識到的牌種與座標
        """
        if not self.templates or image is None:
            return []

        img_h, img_w = image.shape[:2]
        detected_results = []

        for card_name, template in self.templates.items():
            t_h, t_w = template.shape[:2]
            
            # 尺寸防護：如果截圖區域小於模板，自動跳過避免崩潰
            if img_h < t_h or img_w < t_w:
                continue

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
            
            cv2.rectangle(debug_img, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(debug_img, label, (x, max(y - 5, 15)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        return debug_img


if __name__ == "__main__":
    detector = MahjongDetector(template_dir="data/samples", threshold=0.8)

    # ----------------------------------------------------
    # 做法 A：先用靜態圖片驗證辨識準確率（推薦！）
    # ----------------------------------------------------
    test_img_path = os.path.join("data", "raw", "test_01.png")
    
    if os.path.exists(test_img_path):
        print(f"正在測試靜態圖片: {test_img_path}")
        image = cv2.imread(test_img_path)
        
        # 進行辨識
        detections = detector.detect_cards(image)
        current_hand = [item['card'] for item in detections]
        print(f"\n辨識結果手牌: {current_hand} (共 {len(current_hand)} 張)")

        # 繪製結果並顯示
        debug_frame = detector.draw_detections(image, detections)
        cv2.imshow("Static Test Result", debug_frame)
        print("按任意鍵可關閉測試視窗...")
        cv2.waitKey(0)
        cv2.destroyAllWindows()

    # ----------------------------------------------------
    # 做法 B：如要測試動態螢幕擷取
    # ----------------------------------------------------
    else:
        print("未找到靜態測試圖，開啟動態螢幕偵測...")
        
        # 設定廣域 ROI (避免座標太偏)
        HAND_CARD_ROI = {
            'top': 700,
            'left': 0,
            'width': 1920,
            'height': 380
        }

        window_name = "Hand Cards ROI Debug"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

        while True:
            frame = detector.capture_roi(HAND_CARD_ROI)
            detections = detector.detect_cards(frame)

            current_hand = [item['card'] for item in detections]
            print(f"\r目前手牌: {current_hand} (共 {len(current_hand)} 張)", end="")

            debug_frame = detector.draw_detections(frame, detections)
            cv2.imshow(window_name, debug_frame)

            # 按 'q' 鍵 或 點擊右上角 'X' 關閉視窗皆可停止程式
            key = cv2.waitKey(30) & 0xFF
            if key == ord('q') or cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                break

        cv2.destroyAllWindows()