import cv2
import numpy as np
import mss
import os
import glob
import time

class MahjongDetector:
    def __init__(self, template_dir="data/samples", threshold=0.8):
        self.sct = mss.MSS()
        self.default_threshold = threshold
        self.template_dir = template_dir
        self.templates = {}
        self.load_templates()

    def load_templates(self):
        if not os.path.exists(self.template_dir):
            os.makedirs(self.template_dir)
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

        print(f"[Info] 成功載入 {len(self.templates)} 個模板（含牌面與 UI 元素）。")

    def detect_cards_in_roi(self, image, roi_bbox=None, threshold=None, templates_subset=None):
        if image is None:
            return []

        th = threshold if threshold is not None else self.default_threshold
        target_templates = templates_subset if templates_subset is not None else self.templates

        if not target_templates:
            return []

        if roi_bbox:
            x, y, w, h = roi_bbox['left'], roi_bbox['top'], roi_bbox['width'], roi_bbox['height']
            crop_img = image[y:y+h, x:x+w]
        else:
            crop_img = image
            x, y = 0, 0

        detected_results = []
        scale = 0.5
        small_crop = cv2.resize(crop_img, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

        for name, template in target_templates.items():
            small_template = cv2.resize(template, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            t_h, t_w = small_template.shape[:2]

            if small_crop.shape[0] < t_h or small_crop.shape[1] < t_w:
                continue

            res = cv2.matchTemplate(small_crop, small_template, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= th)

            orig_t_h, orig_t_w = template.shape[:2]
            for pt in zip(*loc[::-1]):
                confidence = float(res[pt[1], pt[0]])
                global_x = int(pt[0] / scale) + x
                global_y = int(pt[1] / scale) + y
                detected_results.append({
                    'name': name,
                    'bbox': (global_x, global_y, orig_t_w, orig_t_h),
                    'confidence': confidence
                })

        final_results = self._suppress_overlaps(detected_results)
        final_results.sort(key=lambda item: item['bbox'][0])
        return final_results

    def detect_full_state(self, image):
        start_time = time.time()
        img_h, img_w = image.shape[:2]

        ROIS = {
            'hand': {'top': int(img_h * 0.70), 'left': int(img_w * 0.05), 'width': int(img_w * 0.90), 'height': int(img_h * 0.30)},
            'river': {'top': int(img_h * 0.20), 'left': int(img_w * 0.20), 'width': int(img_w * 0.60), 'height': int(img_h * 0.45)},
            'melds': {'top': int(img_h * 0.65), 'left': int(img_w * 0.75), 'width': int(img_w * 0.25), 'height': int(img_h * 0.20)},
            'buttons': {'top': int(img_h * 0.55), 'left': int(img_w * 0.30), 'width': int(img_w * 0.40), 'height': int(img_h * 0.25)}
        }

        card_templates = {k: v for k, v in self.templates.items() if not (k.startswith('btn_') or k.startswith('anim_'))}
        button_templates = {k: v for k, v in self.templates.items() if k.startswith('btn_') or k.startswith('anim_')}

        state = {
            'hand_cards': self.detect_cards_in_roi(image, ROIS['hand'], threshold=0.65, templates_subset=card_templates),
            'river_cards': self.detect_cards_in_roi(image, ROIS['river'], threshold=0.70, templates_subset=card_templates),
            'melds': self.detect_cards_in_roi(image, ROIS['melds'], threshold=0.70, templates_subset=card_templates),
            'action_buttons': self.detect_cards_in_roi(image, ROIS['buttons'], threshold=0.75, templates_subset=button_templates)
        }

        cost_time = (time.time() - start_time) * 1000
        fps = 1000.0 / cost_time if cost_time > 0 else 0
        state['performance'] = {'cost_time_ms': round(cost_time, 2), 'fps': round(fps, 1)}

        return state

    def draw_full_state(self, image, full_state):
        """ 視覺化繪製 Bounding Box 於影像上 """
        canvas = image.copy()
        
        # 繪製各區域標籤與框 (手牌:綠, 河牌:橘, 副露:紫, 按鈕:紅)
        colors = {
            'hand_cards': (0, 255, 0),
            'river_cards': (0, 165, 255),
            'melds': (255, 0, 255),
            'action_buttons': (0, 0, 255)
        }

        for category, items in full_state.items():
            if category == 'performance' or not isinstance(items, list):
                continue
            color = colors.get(category, (255, 255, 0))
            for item in items:
                x, y, w, h = item['bbox']
                label = f"{item['name']} ({item['confidence']:.2f})"
                cv2.rectangle(canvas, (x, y), (x + w, y + h), color, 2)
                cv2.putText(canvas, label, (x, max(15, y - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

        return canvas

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

# 注意：以下區塊必須靠最左邊（完全不縮排）
if __name__ == "__main__":
    detector = MahjongDetector(template_dir="data/samples", threshold=0.8)
    test_img_path = os.path.join("data", "raw", "test_01.png")

    if os.path.exists(test_img_path):
        print(f"正在執行 Week 4 多區域全盤測試: {test_img_path}")
        image = cv2.imread(test_img_path)
        
        full_state = detector.detect_full_state(image)
        
        print("\n【Week 4 全盤感知結果】")
        print(f"1. 手牌區 ({len(full_state['hand_cards'])} 張): {[i['name'] for i in full_state['hand_cards']]}")
        print(f"2. 河牌區 ({len(full_state['river_cards'])} 張): {[i['name'] for i in full_state['river_cards']]}")
        print(f"3. 副露區 ({len(full_state['melds'])} 張): {[i['name'] for i in full_state['melds']]}")
        print(f"4. 出現按鈕: {[i['name'] for i in full_state['action_buttons']]}")
        if 'performance' in full_state:
            print(f"5. 辨識效能: {full_state['performance']['cost_time_ms']} ms ({full_state['performance']['fps']} FPS)")

        debug_frame = detector.draw_full_state(image, full_state)
        cv2.imshow("Week 4 Full State Perception", debug_frame)
        print("\n請點擊圖片視窗並按任意鍵關閉...")
        cv2.waitKey(0)
        cv2.destroyAllWindows()
    else:
        print(f"[Error] 找不到測試圖片: {test_img_path}")