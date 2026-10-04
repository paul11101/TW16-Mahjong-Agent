import os
import cv2
import numpy as np


class CardRecognizer:
    def __init__(self, samples_dir="samples", match_threshold=0.8):
        """
        初始化牌面辨識器
        :param samples_dir: 存放範本圖片的資料夾路徑
        :param match_threshold: 比對門檻值 (0.0 ~ 1.0)，高於此值才視為有效辨識
        """
        self.samples_dir = samples_dir
        self.match_threshold = match_threshold
        self.templates = {}  # 格式: {card_id: template_gray_image}
        self.load_samples()

    def load_samples(self):
        """載入 samples/ 目錄下的 0.png ~ 41.png 範本圖片"""
        if not os.path.exists(self.samples_dir):
            raise FileNotFoundError(f"找不到範本資料夾: {self.samples_dir}")

        loaded_count = 0
        for card_id in range(42):  # 0 到 41
            file_name = f"{card_id}.png"
            file_path = os.path.join(self.samples_dir, file_name)

            if os.path.exists(file_path):
                # 讀取圖片並轉為灰階
                img = cv2.imread(file_path, cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    self.templates[card_id] = img
                    loaded_count += 1
                else:
                    print(f"[警告] 無法讀取範本圖片: {file_path}")
            else:
                print(f"[提示] 缺少範本圖片: {file_path}")

        print(f"[CardRecognizer] 成功載入 {loaded_count}/42 張牌面範本。")

    def recognize(self, card_img):
        """
        辨識單張麻將圖片
        :param card_img: BGR 或灰階的麻將 ROI 影像 (numpy.ndarray)
        :return: (best_card_id, confidence)
                 若低於 threshold 則 best_card_id 回傳 None
        """
        if card_img is None or card_img.size == 0:
            return None, 0.0

        # 若輸入為彩色影像則轉為灰階
        if len(card_img.shape) == 3:
            gray_card = cv2.cvtColor(card_img, cv2.COLOR_BGR2GRAY)
        else:
            gray_card = card_img

        best_card_id = None
        best_val = -1.0

        for card_id, tmpl in self.templates.items():
            # 確保待測圖與範本尺寸一致，若不同則自動 resize 待測圖至範本大小
            if gray_card.shape != tmpl.shape:
                resized_card = cv2.resize(gray_card, (tmpl.shape[1], tmpl.shape[0]))
            else:
                resized_card = gray_card

            # 使用歸一化相關係數匹配法 (TM_CCOEFF_NORMED)
            res = cv2.matchTemplate(resized_card, tmpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)

            if max_val > best_val:
                best_val = max_val
                best_card_id = card_id

        if best_val >= self.match_threshold:
            return best_card_id, float(best_val)
        else:
            return None, float(best_val)


# ----------------------------------------------------
# 測試模組用主程式
# ----------------------------------------------------
if __name__ == "__main__":
    recognizer = CardRecognizer(samples_dir="data/samples", match_threshold=0.75)

    # 測試讀入 0.png 進行自比對驗證
    test_img_path = os.path.join("data", "samples", "0.png")
    if os.path.exists(test_img_path):
        test_crop = cv2.imread(test_img_path)
        card_id, confidence = recognizer.recognize(test_crop)
        print(f"測試比對結果: Card ID = {card_id}, 置信度 = {confidence:.4f}")
    else:
        print("未找到測試圖片 0.png")