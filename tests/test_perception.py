import os
import sys
import glob
import cv2

# 將專案根目錄加入 Python 搜尋路徑
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.perception.detector import MahjongDetector



def test_batch_detection():
    detector = MahjongDetector(template_dir="data/samples", threshold=0.8)
    
    # 抓取 data/raw/ 底下的所有圖片
    raw_dir = os.path.join("data", "raw")
    types = ('*.png', '*.jpg', '*.jpeg')
    test_files = []
    for ext in types:
        test_files.extend(glob.glob(os.path.join(raw_dir, ext)))

    assert len(test_files) > 0, "測試集中未找到任何圖片！"

    print(f"\n[Batch Test] 開始批次測試，共找到 {len(test_files)} 張測試圖片：")

    for file_path in test_files:
        image = cv2.imread(file_path)
        assert image is not None, f"無法讀取圖片: {file_path}"

        # 執行全盤感知
        state = detector.detect_full_state(image)

        # 斷言基本欄位結構完整
        assert 'hand_cards' in state
        assert 'river_cards' in state
        assert 'melds' in state
        assert 'action_buttons' in state
        assert 'performance' in state

        file_name = os.path.basename(file_path)
        perf = state['performance']
        print(f" -> 圖片 [{file_name}] 通過！耗時: {perf['cost_time_ms']} ms ({perf['fps']} FPS)")

if __name__ == "__main__":
    test_batch_detection()