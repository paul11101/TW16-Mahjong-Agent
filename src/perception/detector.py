import cv2
import numpy as np
import os
import time
from src.perception.loader import TemplateLoader
from src.perception.verifier import MultiFrameVerifier
from src.perception.utils import match_templates_in_crop, calculate_dynamic_scale

class MahjongDetector:
    def __init__(self, template_dir="data/samples", threshold=0.60):
        self.default_threshold = threshold
        self.loader = TemplateLoader(template_dir)
        self.templates = self.loader.load()
        self.verifier = MultiFrameVerifier(history_size=3, match_threshold=2)
        
        # ⚡ 效能核心：灰階與縮放快取
        self.cached_scale = None
        self.small_templates_gray = {}
        self.base_height = 1980.0
        self.base_scale = 0.4

    def _update_template_cache(self, current_scale):
        """ 當解析度比例不變時，100% 重用記憶體快取，並預先轉為單通道灰階 """
        if self.cached_scale != current_scale:
            cache = {}
            for k, v in self.templates.items():
                resized = cv2.resize(v, (0, 0), fx=current_scale, fy=current_scale, interpolation=cv2.INTER_AREA)
                if len(resized.shape) == 3:
                    cache[k] = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
                else:
                    cache[k] = resized
            self.small_templates_gray = cache
            self.cached_scale = current_scale

    def detect_animation(self, image, anim_keys, threshold=0.70, current_scale=0.4):
        if not anim_keys:
            return False, []
        img_h, img_w = image.shape[:2]
        center_roi = {'top': int(img_h * 0.30), 'left': int(img_w * 0.25), 'width': int(img_w * 0.50), 'height': int(img_h * 0.40)}
        anims = match_templates_in_crop(image, center_roi, self.small_templates_gray, self.templates, anim_keys, threshold, current_scale)
        return len(anims) > 0, [a['name'] for a in anims]

    def detect_turn_and_settlement(self, image, current_scale=0.4):
        img_h, img_w = image.shape[:2]
        indicator_roi = {'top': int(img_h * 0.60), 'left': int(img_w * 0.42), 'width': int(img_w * 0.16), 'height': int(img_h * 0.12)}
        crop_indicator = image[indicator_roi['top']:indicator_roi['top']+indicator_roi['height'], indicator_roi['left']:indicator_roi['left']+indicator_roi['width']]
        
        is_my_turn = False
        if crop_indicator.size > 0:
            hsv = cv2.cvtColor(crop_indicator, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array([90, 80, 80]), np.array([130, 255, 255]))
            is_my_turn = cv2.countNonZero(mask) > 150

        bottom_roi = {'top': int(img_h * 0.85), 'left': int(img_w * 0.02), 'width': int(img_w * 0.96), 'height': int(img_h * 0.15)}
        btn_keys = [k for k in self.templates.keys() if 'ready' in k or 'leave' in k]
        settlement_btns = match_templates_in_crop(image, bottom_roi, self.small_templates_gray, self.templates, btn_keys, threshold=0.70, current_scale=current_scale) if btn_keys else []
        
        return is_my_turn, len(settlement_btns) > 0

    def detect_full_state(self, image, scan_secondary_rois=False):
        start_time = time.time()
        if image is None:
            return {}

        img_h, img_w = image.shape[:2]

        current_scale = calculate_dynamic_scale(img_h, self.base_scale, self.base_height)
        self._update_template_cache(current_scale)

        # 🎯 精準 ROI (微調手牌區域左 3% 至右 97%，避開兩側無關區域)
        ROIS = {
            'hand': {'top': int(img_h * 0.68), 'left': int(img_w * 0.03), 'width': int(img_w * 0.94), 'height': int(img_h * 0.32)},
            'flower': {'top': int(img_h * 0.45), 'left': 0, 'width': img_w, 'height': int(img_h * 0.55)},
            'river': {'top': int(img_h * 0.20), 'left': int(img_w * 0.20), 'width': int(img_w * 0.60), 'height': int(img_h * 0.45)},
            'melds': {'top': int(img_h * 0.65), 'left': int(img_w * 0.78), 'width': int(img_w * 0.22), 'height': int(img_h * 0.20)},
            'buttons': {'top': int(img_h * 0.55), 'left': int(img_w * 0.30), 'width': int(img_w * 0.40), 'height': int(img_h * 0.25)}
        }

        normal_card_keys = [k for k in self.templates.keys() if k.isdigit() and int(k) < 34]
        flower_card_keys = [k for k in self.templates.keys() if (k.isdigit() and 34 <= int(k) < 42) or str(k).startswith(('34','35','36','37','38','39','40','41'))]
        button_keys = [k for k in self.templates.keys() if k.startswith('btn_')]
        anim_keys = [k for k in self.templates.keys() if k.startswith('anim_')]

        is_animating, active_animations = self.detect_animation(image, anim_keys, threshold=0.70, current_scale=current_scale)
        is_my_turn, in_settlement = self.detect_turn_and_settlement(image, current_scale=current_scale)

        hand_cards = match_templates_in_crop(image, ROIS['hand'], self.small_templates_gray, self.templates, normal_card_keys, threshold=0.60, current_scale=current_scale, overlap_thresh=0.35)
        flower_cards = match_templates_in_crop(image, ROIS['flower'], self.small_templates_gray, self.templates, flower_card_keys, threshold=0.48, current_scale=current_scale, overlap_thresh=0.30)

        verification = self.verifier.update(hand_cards)
        validity = self.verifier.validate_state(hand_cards, in_settlement=in_settlement)

        river_cards, melds, buttons = [], [], []
        if scan_secondary_rois:
            river_cards = match_templates_in_crop(image, ROIS['river'], self.small_templates_gray, self.templates, normal_card_keys, threshold=0.75, current_scale=current_scale)
            melds = match_templates_in_crop(image, ROIS['melds'], self.small_templates_gray, self.templates, normal_card_keys, threshold=0.75, current_scale=current_scale)
            buttons = match_templates_in_crop(image, ROIS['buttons'], self.small_templates_gray, self.templates, button_keys, threshold=0.75, current_scale=current_scale)

        cost_time = (time.time() - start_time) * 1000
        return {
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
            'performance': {'cost_time_ms': round(cost_time, 2), 'fps': round(1000.0 / cost_time if cost_time > 0 else 0, 1)}
        }

if __name__ == "__main__":
    detector = MahjongDetector(template_dir="data/samples", threshold=0.60)
    raw_dir = os.path.join("data", "raw")
    
    test_img_path = None
    if os.path.exists(raw_dir):
        for f in sorted(os.listdir(raw_dir)):
            if f.startswith("test_") and f.lower().endswith(('.png', '.jpg', '.jpeg')):
                if "test_05" in f:
                    test_img_path = os.path.join(raw_dir, f)
                    break
                elif test_img_path is None:
                    test_img_path = os.path.join(raw_dir, f)

    if test_img_path and os.path.exists(test_img_path):
        print(f"正在執行純程式碼優化測試: {test_img_path}")
        image = cv2.imread(test_img_path)
        full_state = detector.detect_full_state(image)
        print(f"手牌 ({len(full_state['hand_cards'])} 張): {[i['name'] for i in full_state['hand_cards']]}")
        print(f"花牌 ({len(full_state['flower_cards'])} 張): {[i['name'] for i in full_state['flower_cards']]}")
        print(f"單幀耗時: {full_state['performance']['cost_time_ms']} ms ({full_state['performance']['fps']} FPS)")
    else:
        print("[Error] 找不到可用的測試圖片！")