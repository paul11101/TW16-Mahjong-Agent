import cv2
import numpy as np
import mss
import os
import time
from collections import deque, Counter

class MultiFrameVerifier:
    """ 多幀確認器，用於過濾單幀閃爍與雜訊 """
    def __init__(self, history_size=3, match_threshold=2):
        self.history_size = history_size
        self.match_threshold = match_threshold
        self.history = deque(maxlen=history_size)

    def update(self, current_hand_cards):
        hand_key = tuple(sorted([card['name'] for card in current_hand_cards]))
        self.history.append(hand_key)

        counts = Counter(self.history)
        most_common_hand, count = counts.most_common(1)[0]
        is_stable = (count >= self.match_threshold)
        
        return {
            'is_stable': is_stable,
            'verified_hand_names': list(most_common_hand),
            'confidence_ratio': count / len(self.history)
        }

class MahjongDetector:
    def __init__(self, template_dir="data/samples", threshold=0.68):
        self.sct = mss.MSS()
        self.default_threshold = threshold
        self.template_dir = template_dir
        self.templates = {}
        self.small_templates = {}
        self.scale = 0.4  # 極速 0.4x 降採樣
        self.load_templates()
        self.verifier = MultiFrameVerifier(history_size=3, match_threshold=2)

    def load_templates(self):
        """ 載入模板，自動校正尺寸並建置 0.4x 快取 """
        if not os.path.exists(self.template_dir):
            os.makedirs(self.template_dir)
            return

        valid_exts = ('.png', '.jpg', '.jpeg')
        raw_templates = {}

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

        card_shapes = [img.shape[:2] for k, img in raw_templates.items() if not (k.startswith('btn_') or k.startswith('anim_'))]
        if card_shapes:
            from collections import Counter
            standard_h, standard_w = Counter(card_shapes).most_common(1)[0][0]

            for name, img in raw_templates.items():
                if not (name.startswith('btn_') or name.startswith('anim_')):
                    h, w = img.shape[:2]
                    if (h, w) != (standard_h, standard_w):
                        img = cv2.resize(img, (standard_w, standard_h), interpolation=cv2.INTER_AREA)
                self.templates[name] = img
        else:
            self.templates = raw_templates

        # 建立 0.4x 極速縮放快取
        self.small_templates = {
            k: cv2.resize(v, (0, 0), fx=self.scale, fy=self.scale, interpolation=cv2.INTER_AREA)
            for k, v in self.templates.items()
        }

        print(f"[Info] 成功載入 {len(self.templates)} 個模板（已裝載 1D X-NMS 物理抑制引擎）。")

    def _nms_1d_x(self, candidates, overlap_thresh=0.35, margin_thresh=0.03):
        """
        1D X-Axis 物理重疊 Suppression (專治手牌橫向排列問題)
        只要兩張候選牌在 X 軸上的重疊比例 > 35%，強迫判定為同一個實體槽位，剔除低分者。
        """
        if not candidates:
            return []

        # 按信心度高至低排序
        candidates.sort(key=lambda c: c['confidence'], reverse=True)

        keep = []
        for cand in candidates:
            c_x1 = cand['bbox'][0]
            c_w = cand['bbox'][2]
            c_x2 = c_x1 + c_w

            overlap = False
            for k in keep:
                k_x1 = k['bbox'][0]
                k_w = k['bbox'][2]
                k_x2 = k_x1 + k_w

                # 計算 X 軸交集長度
                inter_x = max(0, min(c_x2, k_x2) - max(c_x1, k_x1))
                min_w = min(c_w, k_w)

                if min_w > 0 and (inter_x / min_w) > overlap_thresh:
                    overlap = True
                    break

            if not overlap:
                # 計算 Top 1 與次高得分的 Margin 差距
                top2_score = 0.0
                for other in candidates:
                    if other != cand and abs(other['bbox'][0] - cand['bbox'][0]) < c_w * 0.5:
                        if other['name'] != cand['name']:
                            top2_score = max(top2_score, other['confidence'])

                cand['margin'] = round(cand['confidence'] - top2_score, 3)
                cand['low_confidence'] = cand['margin'] < margin_thresh
                keep.append(cand)

        # 最終依畫面由左至右排序
        keep.sort(key=lambda c: c['bbox'][0])
        return keep

    def detect_cards_by_slots(self, image, roi_bbox, card_templates_keys, threshold=0.68):
        """ 使用 1D X-NMS 精準識別手牌 """
        x, y, w, h = roi_bbox['left'], roi_bbox['top'], roi_bbox['width'], roi_bbox['height']
        roi_img = image[y:y+h, x:x+w]
        
        if roi_img.size == 0 or not card_templates_keys:
            return []

        small_roi = cv2.resize(roi_img, (0, 0), fx=self.scale, fy=self.scale, interpolation=cv2.INTER_AREA)

        raw_results = []
        for name in card_templates_keys:
            small_template = self.small_templates[name]
            t_h, t_w = small_template.shape[:2]

            if small_roi.shape[0] < t_h or small_roi.shape[1] < t_w:
                continue

            res = cv2.matchTemplate(small_roi, small_template, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= threshold)

            orig_t_h, orig_t_w = self.templates[name].shape[:2]
            for pt in zip(*loc[::-1]):
                confidence = float(res[pt[1], pt[0]])
                global_x = int(pt[0] / self.scale) + x
                global_y = int(pt[1] / self.scale) + y
                
                raw_results.append({
                    'name': name,
                    'bbox': (global_x, global_y, orig_t_w, orig_t_h),
                    'confidence': confidence
                })

        # 使用 1D X 軸物理壓制，一槍清掉所有重複假框
        final_cards = self._nms_1d_x(raw_results, overlap_thresh=0.35)
        return final_cards

    def detect_cards_in_roi(self, image, roi_bbox, threshold=0.72, templates_subset_keys=None):
        """ 用於副露區與河牌區的快速偵測 """
        if image is None:
            return []

        target_keys = templates_subset_keys if templates_subset_keys is not None else list(self.templates.keys())
        x, y, w, h = roi_bbox['left'], roi_bbox['top'], roi_bbox['width'], roi_bbox['height']
        crop_img = image[y:y+h, x:x+w]

        if crop_img.size == 0:
            return []

        detected_results = []
        small_crop = cv2.resize(crop_img, (0, 0), fx=self.scale, fy=self.scale, interpolation=cv2.INTER_AREA)

        for name in target_keys:
            small_template = self.small_templates[name]
            t_h, t_w = small_template.shape[:2]

            if small_crop.shape[0] < t_h or small_crop.shape[1] < t_w:
                continue

            res = cv2.matchTemplate(small_crop, small_template, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= threshold)

            orig_t_h, orig_t_w = self.templates[name].shape[:2]
            for pt in zip(*loc[::-1]):
                confidence = float(res[pt[1], pt[0]])
                global_x = int(pt[0] / self.scale) + x
                global_y = int(pt[1] / self.scale) + y
                detected_results.append({
                    'name': name,
                    'bbox': (global_x, global_y, orig_t_w, orig_t_h),
                    'confidence': confidence
                })

        return self._nms_1d_x(detected_results, overlap_thresh=0.35)

    def detect_full_state(self, image):
        start_time = time.time()
        img_h, img_w = image.shape[:2]

        ROIS = {
            'hand': {'top': int(img_h * 0.70), 'left': 0, 'width': img_w, 'height': int(img_h * 0.30)},
            'river': {'top': int(img_h * 0.20), 'left': int(img_w * 0.20), 'width': int(img_w * 0.60), 'height': int(img_h * 0.45)},
            'melds': {'top': int(img_h * 0.65), 'left': int(img_w * 0.78), 'width': int(img_w * 0.22), 'height': int(img_h * 0.20)},
            'buttons': {'top': int(img_h * 0.55), 'left': int(img_w * 0.30), 'width': int(img_w * 0.40), 'height': int(img_h * 0.25)}
        }

        card_keys = [k for k in self.templates.keys() if not (k.startswith('btn_') or k.startswith('anim_'))]
        button_keys = [k for k in self.templates.keys() if k.startswith('btn_')]

        hand_cards = self.detect_cards_by_slots(image, ROIS['hand'], card_keys, threshold=0.68)
        verification = self.verifier.update(hand_cards)

        state = {
            'hand_cards': hand_cards,
            'river_cards': self.detect_cards_in_roi(image, ROIS['river'], threshold=0.72, templates_subset_keys=card_keys),
            'melds': self.detect_cards_in_roi(image, ROIS['melds'], threshold=0.72, templates_subset_keys=card_keys),
            'action_buttons': self.detect_cards_in_roi(image, ROIS['buttons'], threshold=0.72, templates_subset_keys=button_keys),
            'verification': verification
        }

        cost_time = (time.time() - start_time) * 1000
        fps = 1000.0 / cost_time if cost_time > 0 else 0
        state['performance'] = {'cost_time_ms': round(cost_time, 2), 'fps': round(fps, 1)}

        return state

if __name__ == "__main__":
    detector = MahjongDetector(template_dir="data/samples", threshold=0.68)
    test_img_path = os.path.join("data", "raw", "test_01.png")

    if os.path.exists(test_img_path):
        print(f"正在執行 1D X-NMS 物理壓制測試: {test_img_path}")
        image = cv2.imread(test_img_path)
        full_state = detector.detect_full_state(image)
        
        print("\n【全盤感知結果】")
        print(f"1. 手牌區 ({len(full_state['hand_cards'])} 張): {[i['name'] for i in full_state['hand_cards']]}")
        print(f"2. 辨識效能: {full_state['performance']['cost_time_ms']} ms ({full_state['performance']['fps']} FPS)")
    else:
        print(f"[Error] 找不到測試圖片: {test_img_path}")