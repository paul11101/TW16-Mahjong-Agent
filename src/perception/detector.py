import cv2
import numpy as np
import os
import time
from src.perception.loader import TemplateLoader
from src.perception.verifier import MultiFrameVerifier
from src.perception.utils import match_templates_in_crop, calculate_dynamic_scale, nms_1d_x

class MahjongDetector:
    def __init__(self, template_dir="data/samples", threshold=0.60):
        self.default_threshold = threshold
        self.loader = TemplateLoader(template_dir)
        self.templates = self.loader.load()
        self.verifier = MultiFrameVerifier(history_size=3, match_threshold=2)

        # ⚡ 效能核心：灰階與縮放快取
        self.cached_scale = None
        self.small_templates_gray = {}
        self.enlarged_pass_templates = {}
        self.enlarged_pass_gray = {}
        self.base_height = 1980.0
        self.base_scale = 0.4

    @staticmethod
    def _small_gray(template, scale):
        """縮小模板並轉成比對使用的灰階影像。"""
        resized = cv2.resize(template, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY) if resized.ndim == 3 else resized

    def _update_template_cache(self, current_scale):
        """ 當解析度比例不變時，100% 重用記憶體快取，並預先轉為單通道灰階 """
        if self.cached_scale != current_scale:
            self.small_templates_gray = {
                name: self._small_gray(template, current_scale)
                for name, template in self.templates.items()
            }
            # 2880×1575 日誌截圖中的取消按鈕比原模板大約 10%。
            cancel = self.templates.get("btn_pass")
            if cancel is not None:
                large = cv2.resize(cancel, (0, 0), fx=1.1, fy=1.1, interpolation=cv2.INTER_LINEAR)
                self.enlarged_pass_templates = {"btn_pass": large}
                self.enlarged_pass_gray = {"btn_pass": self._small_gray(large, current_scale)}
            self.cached_scale = current_scale

    def _detect_buttons(self, image, roi, button_keys, current_scale):
        """比對原始按鈕模板，並用較大的取消模板補查漏判。"""
        buttons = match_templates_in_crop(
            image, roi, self.small_templates_gray, self.templates, button_keys, 0.55, current_scale
        )
        if not self.enlarged_pass_templates:
            return buttons
        if any(b["name"] == "btn_pass" and b["confidence"] >= 0.75 for b in buttons):
            return buttons
        larger_matches = match_templates_in_crop(
            image, roi, self.enlarged_pass_gray, self.enlarged_pass_templates,
            ["btn_pass"], 0.75, current_scale,
        )
        if not larger_matches:
            return buttons
        return nms_1d_x([b for b in buttons if b["name"] != "btn_pass"] + larger_matches)
    
    def detect_animation(self, image, anim_keys, threshold=0.70, current_scale=0.4):
        if not anim_keys:
            return False, []
        img_h, img_w = image.shape[:2]
        center_roi = {'top': int(img_h * 0.30), 'left': int(img_w * 0.25), 'width': int(img_w * 0.50), 'height': int(img_h * 0.40)}
        anims = match_templates_in_crop(image, center_roi, self.small_templates_gray, self.templates, anim_keys, threshold, current_scale)
        return len(anims) > 0, [a['name'] for a in anims]

    def detect_turn_and_settlement(self, image, current_scale=0.4):
        img_h, img_w = image.shape[:2]
        indicator_roi = {'top': int(img_h * 0.60), 'left': int(img_w * 0.42), 'width': int(img_w * 0.16), 'height': int(img_h * 0.08)}
        crop_indicator = image[indicator_roi['top']:indicator_roi['top']+indicator_roi['height'], indicator_roi['left']:indicator_roi['left']+indicator_roi['width']]

        is_my_turn = False
        if crop_indicator.size > 0:
            hsv = cv2.cvtColor(crop_indicator, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array([90, 80, 80]), np.array([130, 255, 255]))
            is_my_turn = cv2.countNonZero(mask) > 150

        bottom_roi = {'top': int(img_h * 0.85), 'left': int(img_w * 0.02), 'width': int(img_w * 0.96), 'height': int(img_h * 0.15)}
        btn_keys = [k for k in self.templates.keys() if 'ready' in k or 'leave' in k]
        settlement_btns = match_templates_in_crop(image, bottom_roi, self.small_templates_gray, self.templates, btn_keys, self.default_threshold, current_scale)

        return is_my_turn, len(settlement_btns) > 0

    def detect_full_state(self, image, scan_secondary_rois=False):
        start_time = time.time()
        if image is None:
            return {}

        img_h, img_w = image.shape[:2]

        current_scale = calculate_dynamic_scale(img_h, self.base_scale, self.base_height)
        self._update_template_cache(current_scale)

        # 🎯 精準 ROI（buttons 對齊愛台灣麻將右側操作區 top:0.50~0.88, left:0.45~0.92）
        ROIS = {
            'hand': {'top': int(img_h * 0.68), 'left': 0, 'width': img_w, 'height': int(img_h * 0.32)},
            'flower': {'top': int(img_h * 0.45), 'left': 0, 'width': img_w, 'height': int(img_h * 0.55)},
            'river': {'top': int(img_h * 0.20), 'left': int(img_w * 0.20), 'width': int(img_w * 0.60), 'height': int(img_h * 0.45)},
            'melds': {'top': int(img_h * 0.65), 'left': int(img_w * 0.78), 'width': int(img_w * 0.22), 'height': int(img_h * 0.20)},
            'buttons': {'top': int(img_h * 0.50), 'left': int(img_w * 0.45), 'width': int(img_w * 0.47), 'height': int(img_h * 0.38)}
        }

        normal_card_keys = [k for k in self.templates.keys() if k.isdigit() and int(k) < 34]
        flower_card_keys = [k for k in self.templates.keys() if (k.isdigit() and 34 <= int(k) < 42) or str(k).startswith(('34', '35', '36', '37', '38', '39', '40', '41'))]
        button_keys = [k for k in self.templates.keys() if k.startswith('btn_')]
        anim_keys = [k for k in self.templates.keys() if k.startswith('anim_')]

        is_animating, active_animations = self.detect_animation(image, anim_keys, threshold=0.70, current_scale=current_scale)
        is_my_turn, in_settlement = self.detect_turn_and_settlement(image, current_scale=current_scale)

        hand_cards = match_templates_in_crop(image, ROIS['hand'], self.small_templates_gray, self.templates, normal_card_keys, self.default_threshold, current_scale)
        flower_cards = match_templates_in_crop(image, ROIS['flower'], self.small_templates_gray, self.templates, flower_card_keys, self.default_threshold, current_scale)

        # ⚡ 動作按鈕每幀必測，閾值 0.55 兼顧半透明底色按鈕（如 btn_chi）
        buttons = self._detect_buttons(image, ROIS['buttons'], button_keys, current_scale)

        verification = self.verifier.update(hand_cards)
        validity = self.verifier.validate_state(hand_cards, in_settlement=in_settlement)

        river_cards, melds = [], []
        if scan_secondary_rois:
            river_cards = match_templates_in_crop(image, ROIS['river'], self.small_templates_gray, self.templates, normal_card_keys, self.default_threshold, current_scale)
            melds = match_templates_in_crop(image, ROIS['melds'], self.small_templates_gray, self.templates, normal_card_keys, self.default_threshold, current_scale)

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