import os
import cv2

class TemplateLoader:
    """ 專門負責從資料夾載入與管理原始模板 """
    def __init__(self, template_dir="data/samples"):
        self.template_dir = template_dir

    def load(self):
        if not os.path.exists(self.template_dir):
            os.makedirs(self.template_dir)
            return {}

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
            return {}

        print(f"[Info] 成功載入 {len(raw_templates)} 個模板。")
        return raw_templates