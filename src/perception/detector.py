import cv2
import numpy as np
import mss
import os
import glob

class MahjongDetector:
    def __init__(self, template_dir="data/samples", threshold=0.8):
        """
        初始化 MahjongDetector
        :param template_dir: 存放麻將牌與 UI 按鈕模板圖片的資料夾路徑
        :param threshold: 預設比對門檻 (0.0 ~ 1.0)
        """
        self.sct = mss.MSS()
        self.default_threshold = threshold
        self.template_dir = template_dir
        self.templates = {}
        
        # 載入所有麻將牌與 UI 按鈕模板
        self.load_templates()

    def load_templates(self):
        """
        載入所有範本（包含牌面與 UI 按鈕）
        """
        if not os.path.exists(self.template_dir):
            os.makedirs(self.template_dir)
            print(f"[Warning] 模板資料夾 '{self.template_dir}' 不存在。")
            return

        types = ('*.png', '*.jpg', '*.jpeg')
        files_grabbed = []
        for ext in types:
            files_grabbed.extend(glob.glob(os.path.join(self.template_dir, ext)))

        for file_path in files_grabbed:
            name = os.path.splitext(os.path.basename(file_path))[0]
            template_img = cv2.imread(file_path, cv2.IMREAD_COLOR)
            if template_img is not None:
                self.templates[name] = template_img
            else:
                print(f"[Error] 無法讀取模板檔案: {file_path}")

        print(f"[Info] 成功載入 {len(self.templates)} 個模板（含牌面與 UI 元素）。")

    def detect_cards_in_roi(self, image, roi_bbox=None, threshold=None):
        """
        在指定的 ROI 區域中進行模板比對 (通用函式)
        """
        if not self.templates or image is None:
            return []

        th = threshold if threshold is not None else self.default_threshold

        # 如果有指定 ROI，進行裁切
        if roi_bbox:
            x, y, w, h = roi_bbox['left'], roi_bbox['top'], roi_bbox['width'], roi_bbox['height']
            crop_img = image[y:y+h, x:x+w]
        else:
            crop_img = image
            x, y = 0, 0

        img_h, img_w = crop_img.shape[:2]
        detected_results = []

        for name, template in self.templates.items():
            t_h, t_w = template.shape[:2]
            
            # 尺寸防護：截圖小於模板時跳過
            if img_h < t_h or img_w < t_w:
                continue

            res = cv2.matchTemplate(crop_img, template, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= th)

            for pt in zip(*loc[::-1]):
                confidence = float(res[pt[1], pt[0]])
                # 座標還原回全圖的全局座標
                global_x = pt[0] + x
                global_y = pt[1] + y
                detected_results.append({
                    'name': name,
                    'bbox': (global_x, global_y, t_w, t_h),
                    'confidence': confidence
                })

        # NMS 抑制重疊
        final_results = self._suppress_overlaps(detected_results)
        final_results.sort(key=lambda item: item['bbox'][0])  # 預設按 X 座標排序
        return final_results

    def detect_full_state(self, image):
        """
        全盤感知：同時偵測手牌、河牌、副露與 UI 按鈕
        """
        img_h, img_w = image.shape[:2]

        # 針對全畫面的 ROI 範圍設定
        ROIS = {
            # 手牌區：覆蓋整個下半部，門檻 0.68 確保能抓到左側被圖示稍微遮擋的牌
            'hand': {'top': int(img_h * 0.65), 'left': 0, 'width': img_w, 'height': int(img_h * 0.35)},
            # 河牌區：中央牌桌丟牌處
            'river': {'top': int(img_h * 0.20), 'left': int(img_w * 0.20), 'width': int(img_w * 0.60), 'height': int(img_h * 0.45)},
            # 副露區：右下角吃碰槓區
            'melds': {'top': int(img_h * 0.65), 'left': int(img_w * 0.75), 'width': int(img_w * 0.25), 'height': int(img_h * 0.20)},
            # 按鈕區：畫面中央偏下跳出吃碰槓胡按鈕區
            'buttons': {'top': int(img_h * 0.55), 'left': int(img_w * 0.30), 'width': int(img_w * 0.40), 'height': int(img_h * 0.25)}
        }

        state = {
            'hand_cards': self.detect_cards_in_roi(image, ROIS['hand'], threshold=0.68),
            'river_cards': self.detect_cards_in_roi(image, ROIS['river'], threshold=0.75),
            'melds': self.detect_cards_in_roi(image, ROIS['melds'], threshold=0.75),
            'action_buttons': self.detect_cards_in_roi(image, ROIS['buttons'], threshold=0.80)
        }
        return state

    def _suppress_overlaps(self, results, iou_threshold=0.3):
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

    def draw_full_state(self, image, state):
        """
        繪製全盤感知的視覺化 Bounding Box (除錯用)
        """
        debug_img = image.copy()
        colors = {
            'hand_cards': (0, 255, 0),       # 綠色
            'river_cards': (255, 165, 0),    # 橘色
            'melds': (255, 255, 0),          # 黃色
            'action_buttons': (0, 0, 255)    # 紅色
        }

        for category, items in state.items():
            color = colors.get(category, (255, 255, 255))
            for item in items:
                x, y, w, h = item['bbox']
                label = f"{item['name']} ({item['confidence']:.2f})"
                cv2.rectangle(debug_img, (x, y), (x + w, y + h), color, 2)
                cv2.putText(debug_img, label, (x, max(y - 5, 15)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
        return debug_img


if __name__ == "__main__":
    detector = MahjongDetector(template_dir="data/samples", threshold=0.8)
    test_img_path = os.path.join("data", "raw", "test_01.png")

    if os.path.exists(test_img_path):
        print(f"正在執行 Week 4 多區域全盤測試: {test_img_path}")
        image = cv2.imread(test_img_path)
        
        # 進行全盤辨識
        full_state = detector.detect_full_state(image)
        
        print("\n【Week 4 全盤感知結果】")
        print(f"1. 手牌區 ({len(full_state['hand_cards'])} 張): {[i['name'] for i in full_state['hand_cards']]}")
        print(f"2. 河牌區 ({len(full_state['river_cards'])} 張): {[i['name'] for i in full_state['river_cards']]}")
        print(f"3. 副露區 ({len(full_state['melds'])} 張): {[i['name'] for i in full_state['melds']]}")
        print(f"4. 出現按鈕: {[i['name'] for i in full_state['action_buttons']]}")

        debug_frame = detector.draw_full_state(image, full_state)
        cv2.imshow("Week 4 Full State Perception", debug_frame)
        print("\n請點擊圖片視窗並按任意鍵關閉...")
        cv2.waitKey(0)
        cv2.destroyAllWindows()