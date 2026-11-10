# Data Directory

- raw/: 原始測試集資料（包含 test_01 ~ test_05 等獨立 Ground Truth 測試影格）
- processed/: 前處理後資料
- samples/: 少量測試用範例與 55 個靜態 UI/牌面模板資料庫

---

## 🀄 視覺感知資料庫與標註規範 (Perception Spec)

> 註：標準麻將牌型代碼 (ID 0 - 41) 請參閱 `docs/tile_classes.md`[cite: 17]。

### 1. 擴充模板標註類別 (Extended Templates)
* **狀態與按鈕 (`btn_*`)**：`btn_ready.png` (準備)、`btn_leave.png` (離開/結算)
* **動態特效 (`anim_*`)**：`anim_chi.png` / `anim_pon.png` / `anim_kan.png` / `anim_ron.png` (吃碰槓胡動畫特徵)

### 2. 評測集與驗證規範 (Evaluation Benchmark Split)
* **測試集中選**：`data/raw/test_*.png` 涵蓋全手牌 (16張)、花牌、摸牌狀態 (15張) 及胡牌結算畫面[cite: 1, 2]。
* **載入協定**：由 `src.perception.loader.TemplateLoader` 進行自動化灰階矩陣預載入與快取管理。