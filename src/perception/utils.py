import cv2
import numpy as np

def calculate_dynamic_scale(img_h, base_scale=0.4, base_height=1980.0):
    return base_scale * (float(img_h) / float(base_height))

def nms_1d_x(candidates, overlap_thresh=0.35, margin_thresh=0.03):
    if not candidates:
        return []

    candidates.sort(key=lambda c: c['confidence'], reverse=True)
    keep = []

    for cand in candidates:
        c_x1, c_w = cand['bbox'][0], cand['bbox'][2]
        c_x2 = c_x1 + c_w
        overlap = False

        for k in keep:
            k_x1, k_w = k['bbox'][0], k['bbox'][2]
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

def match_templates_in_crop(image, roi_bbox, small_templates, orig_templates, target_keys, threshold, current_scale, overlap_thresh=0.35):
    """ 
    高效能比對：
    1. 使用 pre-scaled 的 small_templates 記憶體快取 (0 次重複 resize)
    2. 使用單通道灰階 (Grayscale) 進行 cv2.matchTemplate (速度提升 3 倍)
    """
    if image is None or not target_keys:
        return []

    x, y, w, h = roi_bbox['left'], roi_bbox['top'], roi_bbox['width'], roi_bbox['height']
    crop_img = image[y:y+h, x:x+w]

    if crop_img.size == 0:
        return []

    # 1. 將切圖縮小並轉為灰階 (單通道)
    small_crop = cv2.resize(crop_img, (0, 0), fx=current_scale, fy=current_scale, interpolation=cv2.INTER_AREA)
    if len(small_crop.shape) == 3:
        small_crop_gray = cv2.cvtColor(small_crop, cv2.COLOR_BGR2GRAY)
    else:
        small_crop_gray = small_crop

    raw_results = []

    # 2. 進行單通道比對
    for name in target_keys:
        if name not in small_templates:
            continue
        
        small_template_gray = small_templates[name] # 已預先轉為單通道灰階的快取
        t_h, t_w = small_template_gray.shape[:2]

        if small_crop_gray.shape[0] < t_h or small_crop_gray.shape[1] < t_w:
            continue

        res = cv2.matchTemplate(small_crop_gray, small_template_gray, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= threshold)

        orig_t_h, orig_t_w = orig_templates[name].shape[:2]
        for pt in zip(*loc[::-1]):
            confidence = float(res[pt[1], pt[0]])
            global_x = int(pt[0] / current_scale) + x
            global_y = int(pt[1] / current_scale) + y
            raw_results.append({
                'name': name,
                'bbox': (global_x, global_y, orig_t_w, orig_t_h),
                'confidence': confidence
            })

    return nms_1d_x(raw_results, overlap_thresh=overlap_thresh)