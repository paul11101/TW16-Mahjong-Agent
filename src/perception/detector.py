import cv2
import numpy as np
import mss
import os
import glob
import time

class MahjongDetector:
    def __init__(self, template_dir="data/samples", threshold=0.68):
        self.sct = mss.MSS()
        self.default_threshold = threshold
        self.template_dir = template_dir
        self.templates = {}
        self.load_templates()

    def load_templates(self):
        """ 載入模板，並自動將尺寸校正為標準手牌大小 """
        if not os.path.exists(self.template_dir):
            os.makedirs(self.template_dir)
            return

        valid_exts = ('.png', '.jpg', '.jpeg')
        raw_templates = {}

        # 1. 讀取所有有效圖片檔案 (排除 failed)
        for root, dirs, files in os.walk(self.template_dir):
            if "failed" in root:
                continue
            for file in files:
                if file.lower().endswith(valid_exts):
                    file_path = os.path.join(root, file)
                    if os.path.isfile(file_path):
                        name = os.path.splitext(file)[0]
                        template_img = cv2.imread(file_path, cv2.IMREAD_COLOR)
                        if template_img is not None:
                            raw_templates[name] = template_img

        if not raw_templates:
            print("[Warning] 未找到任何有效模板！")
            return

        # 2. 自動計算標準手牌尺寸 (取眾數)
        card_shapes = [img.shape[:2] for k, img in raw_templates.items() if not (k.startswith('btn_') or k.startswith('anim_'))]
        if card_shapes:
            from collections import Counter
            standard_h, standard_w = Counter(card_shapes).most_common(1)[0][0]

            # 3. 統一範本尺寸，消除因尺寸落差導致的誤判與爆速
            for name, img in raw_templates.items():
                if not (name.startswith('btn_') or name.startswith('anim_')):
                    h, w = img.shape[:2]
                    if (h, w) != (standard_h, standard_w):
                        img = cv2.resize(img, (standard_w, standard_h), interpolation=cv2.INTER_AREA)
                self.templates[name] = img
        else:
            self.templates = raw_templates

        print(f"[Info] 成功載入 {len(self.templates)} 個模板（已完成尺寸自動校正）。")

    def detect_cards_by_slots(self, image, roi_bbox, card_templates, threshold=0.68, iou_thresh=0.35, margin_threshold=0.03):
        """
        高效能 Slot NMS 演算法 (< 200ms)
        """
        x, y, w, h = roi_bbox['left'], roi_bbox['top'], roi_bbox['width'], roi_bbox['height']
        roi_img = image[y:y+h, x:x+w]
        
        if roi_img.size == 0 or not card_templates:
            return []

        scale = 0.5
        small_roi = cv2.resize(roi_img, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

        # 1. 全模板降採樣匹配
        raw_results = []
        for name, template in card_templates.items():
            small_template = cv2.resize(template, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            t_h, t_w = small_template.shape[:2]

            if small_roi.shape[0] < t_h or small_roi.shape[1] < t_w:
                continue

            res = cv2.matchTemplate(small_roi, small_template, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= threshold)

            orig_t_h, orig_t_w = template.shape[:2]
            for pt in zip(*loc[::-1]):
                confidence = float(res[pt[1], pt[0]])
                global_x = int(pt[0] / scale) + x
                global_y = int(pt[1] / scale) + y
                raw_results.append({
                    'name': name,
                    'bbox': (global_x, global_y, orig_t_w, orig_t_h),
                    'confidence': confidence
                })

        if not raw_results:
            return []

        # 2. IoU 空間壓制 (NMS)
        boxes = np.array([r['bbox'] for r in raw_results])
        scores = np.array([r['confidence'] for r in raw_results])

        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 0] + boxes[:, 2]
        y2 = boxes[:, 1] + boxes[:, 3]

        areas = (x2 - x1) * (y2 - y1)
        order = scores.argsort()[::-1]

        slots = []
        visited = set()

        for i in range(len(order)):
            idx = order[i]
            if idx in visited:
                continue

            slot_top1 = raw_results[idx]
            slot_top2 = None
            visited.add(idx)

            xx1 = np.maximum(x1[idx], x1[order[i+1:]])
            yy1 = np.maximum(y1[idx], y1[order[i+1:]])
            xx2 = np.minimum(x2[idx], x2[order[i+1:]])  # 已修正切片索引
            yy2 = np.minimum(y2[idx], y2[order[i+1:]])  # 已修正切片索引

            w_inter = np.maximum(0.0, xx2 - xx1)
            h_inter = np.maximum(0.0, yy2 - yy1)
            inter = w_inter * h_inter
            iou = inter / (areas[idx] + areas[order[i+1:]] - inter)

            overlapping_indices = np.where(iou > iou_thresh)[0]
            
            for overlap_idx in overlapping_indices:
                real_idx = order[i + 1 + overlap_idx]
                visited.add(real_idx)
                if slot_top2 is None and raw_results[real_idx]['name'] != slot_top1['name']:
                    slot_top2 = raw_results[real_idx]

            # 3. 計算 Top1 與 Top2 Margin 差距
            top1_score = slot_top1['confidence']
            top2_score = slot_top2['confidence'] if slot_top2 else 0.0
            margin = top1_score - top2_score

            slot_top1['margin'] = round(margin, 3)
            slot_top1['low_confidence'] = margin < margin_threshold
            slots.append(slot_top1)

        # 4. 依照畫面由左至右排序
        slots.sort(key=lambda item: item['bbox'][0])
        return slots

    def detect_cards_in_roi(self, image, roi_bbox, threshold=0.75, templates_subset=None):
        """ 用於副露區與河牌區的標準偵測 """
        if image is None:
            return []

        target_templates = templates_subset if templates_subset is not None else self.templates
        x, y, w, h = roi_bbox['left'], roi_bbox['top'], roi_bbox['width'], roi_bbox['height']
        crop_img = image[y:y+h, x:x+w]

        detected_results = []
        scale = 0.5
        small_crop = cv2.resize(crop_img, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

        for name, template in target_templates.items():
            small_template = cv2.resize(template, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            t_h, t_w = small_template.shape[:2]

            if small_crop.shape[0] < t_h or small_crop.shape[1] < t_w:
                continue

            res = cv2.matchTemplate(small_crop, small_template, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= threshold)

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
        return final_results

    def detect_full_state(self, image):
        start_time = time.time()
        img_h, img_w = image.shape[:2]

        ROIS = {
            'hand': {'top': int(img_h * 0.70), 'left': 0, 'width': img_w, 'height': int(img_h * 0.30)},
            'river': {'top': int(img_h * 0.20), 'left': int(img_w * 0.20), 'width': int(img_w * 0.60), 'height': int(img_h * 0.45)},
            'melds': {'top': int(img_h * 0.65), 'left': int(img_w * 0.78), 'width': int(img_w * 0.22), 'height': int(img_h * 0.20)},
            'buttons': {'top': int(img_h * 0.55), 'left': int(img_w * 0.30), 'width': int(img_w * 0.40), 'height': int(img_h * 0.25)}
        }

        card_templates = {k: v for k, v in self.templates.items() if not (k.startswith('btn_') or k.startswith('anim_'))}
        button_templates = {k: v for k, v in self.templates.items() if k.startswith('btn_') or k.startswith('anim_')}

        hand_cards = self.detect_cards_by_slots(image, ROIS['hand'], card_templates, threshold=0.68)

        state = {
            'hand_cards': hand_cards,
            'river_cards': self.detect_cards_in_roi(image, ROIS['river'], threshold=0.75, templates_subset=card_templates),
            'melds': self.detect_cards_in_roi(image, ROIS['melds'], threshold=0.75, templates_subset=card_templates),
            'action_buttons': self.detect_cards_in_roi(image, ROIS['buttons'], threshold=0.75, templates_subset=button_templates)
        }

        cost_time = (time.time() - start_time) * 1000
        fps = 1000.0 / cost_time if cost_time > 0 else 0
        state['performance'] = {'cost_time_ms': round(cost_time, 2), 'fps': round(fps, 1)}

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

if __name__ == "__main__":
    detector = MahjongDetector(template_dir="data/samples", threshold=0.68)
    test_img_path = os.path.join("data", "raw", "test_01.png")

    if os.path.exists(test_img_path):
        print(f"正在執行高效能感知測試: {test_img_path}")
        image = cv2.imread(test_img_path)
        full_state = detector.detect_full_state(image)
        
        print("\n【全盤感知結果】")
        print(f"1. 手牌區 ({len(full_state['hand_cards'])} 張): {[i['name'] for i in full_state['hand_cards']]}")
        print(f"2. 辨識效能: {full_state['performance']['cost_time_ms']} ms ({full_state['performance']['fps']} FPS)")
    else:
        print(f"[Error] 找不到測試圖片: {test_img_path}")