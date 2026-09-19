# 資料夾與標註規格 (Data Spec)

## 1. 專案目錄結構
```text
TW16-Mahjong-Agent/
├── configs/          # 設定檔目錄
├── data/             # 資料目錄
│   ├── templates/    # 存放 42 張數字化命名之牌面模板小圖 (0.png ~ 41.png)
│   └── test/         # 存放測試用全螢幕遊戲截圖 (test_01.png)
├── docs/             # 專案文檔目錄
│   └── perception/   # 視覺模組規格文檔與圖片
├── src/              # 主程式碼目錄
└── main.py           # 專案入口點