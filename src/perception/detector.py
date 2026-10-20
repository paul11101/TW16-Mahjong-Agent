import cv2
import numpy as np
import mss
import os
import glob
import time
from collections import deque, Counter

class MultiFrameVerifier:
    """ Week 5 Day 1: 多幀確認器 """
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
            'confidence_ratio': round(count / len(self.history), 2)
        }

class MahjongDetector:
    def __init__(self, template_dir="data/samples", threshold=0.60):
        self.sct = mss.MSS()
        self.default_threshold = threshold
        self.template_dir = template_dir
        self.templates = {}
        self.base_height = 1980.0  # 對應 3500x1980 標準基準
        self.base_scale = 0.4
        self.load_templates()
        self.verifier = MultiFrameVerifier(history_size=3, match_threshold=2)

    def load_templates(self):
        """ 載入原始模板 """
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

        self.templates = raw_templates
        print(f"[Info] 成功載入 {len(self.templates)} 個模板。")

    def _nms_1d_x(self, candidates, overlap_thresh=0.35, margin_thresh=0.03):
        """ 1D X-Axis 物理重疊壓制演算法 """
        if not candidates:
            return []

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

                inter_x = max(0, min(c_x2, k_x2) - max(c_x1, k_x1))
                min_w = min(c_w, k_w)

                if min_w > 0 and (inter_x / min_w) > overlap_thresh:
                    overlap = True
                    break

            if not overlap:
                top2_score = 0.0
                for other in candidates:
                    if other != cand and abs(other['bbox'][0] - cand['bbox'][0]) < c_w * 0.5:
                        if other['name'] != cand['name']:
                            top2_score = max(top2_score, other['confidence'])

                cand['margin'] = round(cand['confidence'] - top2_score, 3)
                cand['low_confidence'] = cand['margin'] < margin_thresh
                keep.append(cand)

        keep.sort(key=lambda c: c['bbox'][0])
        return keep

    def detect_cards_by_slots(self, image, roi_bbox, card_templates_keys, threshold=0.60):
        img_h = image.shape[0]
        current_scale = self.base_scale * (img_h / self.base_height)

        x, y, w, h = roi_bbox['left'], roi_bbox['top'], roi_bbox['width'], roi_bbox['height']
        roi_img = image[y:y+h, x:x+w]
        
        if roi_img.size == 0 or not card_templates_keys:
            return []

        small_roi = cv2.resize(roi_img, (0, 0), fx=current_scale, fy=current_scale, interpolation=cv2.INTER_AREA)
        raw_results = []

        for name in card_templates_keys:
            if name not in self.templates:
                continue
            orig_template = self.templates[name]
            small_template = cv2.resize(orig_template, (0, 0), fx=current_scale, fy=current_scale, interpolation=cv2.INTER_AREA)
            t_h, t_w = small_template.shape[:2]

            if small_roi.shape[0] < t_h or small_roi.shape[1] < t_w:
                continue

            res = cv2.matchTemplate(small_roi, small_template, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= threshold)

            orig_t_h, orig_t_w = orig_template.shape[:2]
            for pt in zip(*loc[::-1]):
                confidence = float(res[pt[1], pt[0]])
                global_x = int(pt[0] / current_scale) + x
                global_y = int(pt[1] / current_scale) + y
                
                raw_results.append({
                    'name': name,
                    'bbox': (global_x, global_y, orig_t_w, orig_t_h),
                    'confidence': confidence
                })

        return self._nms_1d_x(raw_results, overlap_thresh=0.35)

    def detect_flower_cards_dedicated(self, image, roi_bbox, flower_keys, threshold=0.48):
        """ 🌸 花牌專屬檢測器：避免與普通手牌競爭 NMS，獨立計數與壓制 """
        if image is None or not flower_keys:
            return []

        img_h = image.shape[0]
        current_scale = self.base_scale * (img_h / self.base_height)

        x, y, w, h = roi_bbox['left'], roi_bbox['top'], roi_bbox['width'], roi_bbox['height']
        crop_img = image[y:y+h, x:x+w]

        if crop_img.size == 0:
            return []

        small_crop = cv2.resize(crop_img, (0, 0), fx=current_scale, fy=current_scale, interpolation=cv2.INTER_AREA)
        raw_results = []

        for name in flower_keys:
            if name not in self.templates:
                continue
            orig_template = self.templates[name]
            small_template = cv2.resize(orig_template, (0, 0), fx=current_scale, fy=current_scale, interpolation=cv2.INTER_AREA)
            t_h, t_w = small_template.shape[:2]

            if small_crop.shape[0] < t_h or small_crop.shape[1] < t_w:
                continue

            res = cv2.matchTemplate(small_crop, small_template, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= threshold)

            orig_t_h, orig_t_w = orig_template.shape[:2]
            for pt in zip(*loc[::-1]):
                confidence = float(res[pt[1], pt[0]])
                global_x = int(pt[0] / current_scale) + x
                global_y = int(pt[1] / current_scale) + y
                
                raw_results.append({
                    'name': name,
                    'bbox': (global_x, global_y, orig_t_w, orig_t_h),
                    'confidence': confidence
                })

        # 花牌專用獨立 NMS 壓制
        return self._nms_1d_x(raw_results, overlap_thresh=0.30)

    def detect_cards_in_roi(self, image, roi_bbox, threshold=0.70, templates_subset_keys=None):
        if image is None:
            return []

        img_h = image.shape[0]
        current_scale = self.base_scale * (img_h / self.base_height)

        x, y, w, h = roi_bbox['left'], roi_bbox['top'], roi_bbox['width'], roi_bbox['height']
        crop_img = image[y:y+h, x:x+w]

        if crop_img.size == 0:
            return []

        target_keys = templates_subset_keys if templates_subset_keys is not None else list(self.templates.keys())
        detected_results = []
        small_crop = cv2.resize(crop_img, (0, 0), fx=current_scale, fy=current_scale, interpolation=cv2.INTER_AREA)

        for name in target_keys:
            if name not in self.templates:
                continue
            orig_template = self.templates[name]
            small_template = cv2.resize(orig_template, (0, 0), fx=current_scale, fy=current_scale, interpolation=cv2.INTER_AREA)
            t_h, t_w = small_template.shape[:2]

            if small_crop.shape[0] < t_h or small_crop.shape[1] < t_w:
                continue

            res = cv2.matchTemplate(small_crop, small_template, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= threshold)

            orig_t_h, orig_t_w = orig_template.shape[:2]
            for pt in zip(*loc[::-1]):
                confidence = float(res[pt[1], pt[0]])
                global_x = int(pt[0] / current_scale) + x
                global_y = int(pt[1] / current_scale) + y
                detected_results.append({
                    'name': name,
                    'bbox': (global_x, global_y, orig_t_w, orig_t_h),
                    'confidence': confidence
                })

        return self._nms_1d_x(detected_results, overlap_thresh=0.35)

    def detect_animation(self, image, anim_keys, threshold=0.70):
        if not anim_keys:
            return False, []

        img_h, img_w = image.shape[:2]
        center_roi = {
            'top': int(img_h * 0.30),
            'left': int(img_w * 0.25),
            'width': int(img_w * 0.50),
            'height': int(img_h * 0.40)
        }
        
        detected_anims = self.detect_cards_in_roi(image, center_roi, threshold=threshold, templates_subset_keys=anim_keys)
        is_animating = len(detected_anims) > 0
        return is_animating, [a['name'] for a in detected_anims]

    def detect_turn_and_settlement(self, image):
        img_h, img_w = image.shape[:2]
        
        indicator_roi = {
            'top': int(img_h * 0.60),
            'left': int(img_w * 0.42),
            'width': int(img_w * 0.16),
            'height': int(img_h * 0.12)
        }
        crop_indicator = image[indicator_roi['top']:indicator_roi['top']+indicator_roi['height'],
                               indicator_roi['left']:indicator_roi['left']+indicator_roi['width']]
        
        is_my_turn = False
        if crop_indicator.size > 0:
            hsv = cv2.cvtColor(crop_indicator, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array([90, 80, 80]), np.array([130, 255, 255]))
            is_my_turn = cv2.countNonZero(mask) > 150

        bottom_roi = {
            'top': int(img_h * 0.85),
            'left': int(img_w * 0.02),
            'width': int(img_w * 0.96),
            'height': int(img_h * 0.15)
        }
        settlement_btn_keys = [k for k in self.templates.keys() if 'ready' in k or 'leave' in k]
        in_settlement = False
        if settlement_btn_keys:
            settlement_btns = self.detect_cards_in_roi(image, bottom_roi, threshold=0.70, templates_subset_keys=settlement_btn_keys)
            in_settlement = len(settlement_btns) > 0

        return is_my_turn, in_settlement

    def validate_state(self, hand_cards, in_settlement=False):
        if in_settlement:
            return {'is_valid': True, 'need_recap': False, 'reasons': ["In Settlement"]}

        hand_count = len(hand_cards)
        has_low_confidence = any(card.get('low_confidence', False) for card in hand_cards)

        count_valid = hand_count in (16, 17)
        need_recap = (not count_valid) or has_low_confidence

        reasons = []
        if not count_valid:
            reasons.append(f"Invalid hand count: {hand_count}")
        if has_low_confidence:
            reasons.append("Low confidence detected in hand slots")

        return {
            'is_valid': count_valid and not has_low_confidence,
            'need_recap': need_recap,
            'reasons': reasons if reasons else ["OK"]
        }

    def detect_full_state(self, image, scan_secondary_rois=False):
        start_time = time.time()
        img_h, img_w = image.shape[:2]

        # 🎯 全域手牌與花牌自適應 ROI 涵蓋
        ROIS = {
            # 手牌區涵蓋下方 32% 全寬度
            'hand': {'top': int(img_h * 0.68), 'left': 0, 'width': img_w, 'height': int(img_h * 0.32)},
            # 🌸 花牌區直接擴大至包含全手牌區 + 左側/右側所有可能立牌與平放區
            'flower': {'top': int(img_h * 0.50), 'left': 0, 'width': img_w, 'height': int(img_h * 0.50)},
            'river': {'top': int(img_h * 0.20), 'left': int(img_w * 0.20), 'width': int(img_w * 0.60), 'height': int(img_h * 0.45)},
            'melds': {'top': int(img_h * 0.65), 'left': int(img_w * 0.78), 'width': int(img_w * 0.22), 'height': int(img_h * 0.20)},
            'buttons': {'top': int(img_h * 0.55), 'left': int(img_w * 0.30), 'width': int(img_w * 0.40), 'height': int(img_h * 0.25)}
        }

        # 1. 普通手牌 (0~33)
        normal_card_keys = [k for k in self.templates.keys() if k.isdigit() and int(k) < 34]
        
        # 2. 花牌 Key 嚴格抓取所有 34~41 的模板
        flower_card_keys = [k for k in self.templates.keys() if (k.isdigit() and 34 <= int(k) < 42) or str(k).startswith(('34','35','36','37','38','39','40','41'))]

        button_keys = [k for k in self.templates.keys() if k.startswith('btn_')]
        anim_keys = [k for k in self.templates.keys() if k.startswith('anim_')]

        is_animating, active_animations = self.detect_animation(image, anim_keys, threshold=0.70)
        is_my_turn, in_settlement = self.detect_turn_and_settlement(image)

        # 1. 手牌區識別 (門檻 0.60)
        hand_cards = self.detect_cards_by_slots(image, ROIS['hand'], normal_card_keys, threshold=0.60)
        
        # 2. 花牌專屬通道識別 (門檻調降至 0.48，不干擾手牌，防壓制)
        flower_cards = self.detect_flower_cards_dedicated(image, ROIS['flower'], flower_card_keys, threshold=0.48)

        verification = self.verifier.update(hand_cards)
        validity = self.validate_state(hand_cards, in_settlement=in_settlement)

        river_cards, melds, buttons = [], [], []
        if scan_secondary_rois:
            river_cards = self.detect_cards_in_roi(image, ROIS['river'], threshold=0.75, templates_subset_keys=normal_card_keys)
            melds = self.detect_cards_in_roi(image, ROIS['melds'], threshold=0.75, templates_subset_keys=normal_card_keys)
            buttons = self.detect_cards_in_roi(image, ROIS['buttons'], threshold=0.75, templates_subset_keys=button_keys)

        cost_time = (time.time() - start_time) * 1000
        fps = 1000.0 / cost_time if cost_time > 0 else 0

        state = {
            'hand_cards': hand_cards,
            'flower_cards': flower_cards,
            'river_cards': river_cards,
            'melds': melds,
            'action_buttons': buttons,
            'verification': verification,
            'is_animating': is_animating,
            'active_animations': active_animations,
            'is_my_turn': is_my_turn,
            'in_settlement': in_settlement,
            'validity': validity,
            'performance': {
                'cost_time_ms': round(cost_time, 2),
                'fps': round(fps, 1)
            }
        }

        return state

if __name__ == "__main__":
    detector = MahjongDetector(template_dir="data/samples", threshold=0.60)
    test_img_path = os.path.join("data", "raw", "test_05.png")

    if os.path.exists(test_img_path):
        print(f"正在執行獨立花牌通道測試: {test_img_path}")
        image = cv2.imread(test_img_path)
        
        for frame_idx in range(1, 4):
            full_state = detector.detect_full_state(image, scan_secondary_rois=False)
            print(f"\n--- 第 {frame_idx} 幀感知結果 ---")
            print(f"1. 手牌區 ({len(full_state['hand_cards'])} 張): {[i['name'] for i in full_state['hand_cards']]}")
            print(f"2. 花牌區 ({len(full_state['flower_cards'])} 張): {[i['name'] for i in full_state['flower_cards']]}")
            print(f"3. 輪次與結算: IsMyTurn={full_state['is_my_turn']} | InSettlement={full_state['in_settlement']}")
            print(f"4. 多幀與動畫: Stable={full_state['verification']['is_stable']} | Animating={full_state['is_animating']}")
            print(f"5. 辨識效能: {full_state['performance']['cost_time_ms']} ms ({full_state['performance']['fps']} FPS)")
    else:
        print(f"[Error] 找不到測試圖片: {test_img_path}")