# VLOGMahjong 架構查核

## 1. 專案來源

VLOGMahjong 來自 Agony5757/mahjong 專案。

原專案主要支援日本立直麻將，本專題不直接套用原本的日麻規則，
而是將 VLOGMahjong 作為模型架構與訓練方法的參考基底。

## 2. VLOGMahjong 基本架構

VLOGMahjong 將模型分成玩家可見資訊與訓練用 Oracle 資訊。

正式推論時，Executor 只使用玩家可以看到的資訊。
訓練時，Oracle 可以使用模擬器提供的完整牌局資訊來輔助模型學習。

原版主要資料尺寸：

- Executor Observation：93 × 34
- Oracle Observation：111 × 34
- Action Size：47

其中 34 對應麻將的 34 種基本牌型。

模型主要支援：

- BC（Behavior Cloning）
- DDQN（Double DQN）

VLOGMahjong 的模型流程可以簡化為：

Observation
→ Encoder
→ Latent Representation
→ Policy Network / Q Network
→ Action Mask
→ Action

訓練時則另外加入 Oracle 分支，
利用完整牌局資訊協助 Executor 學習。

---

## 3. 可沿用部分

### Executor / Oracle 架構

可以沿用。

正式 Agent 的 Executor 只使用玩家可見資訊，
訓練階段可以讓 Oracle 使用模擬器的完整狀態輔助學習。

此設計符合本專題避免隱藏資訊外洩的需求。

正式執行時不得讓 Executor 取得：

- 對手暗牌
- 未知牌山內容
- 其他玩家無法取得的隱藏資訊

這也符合本專題原本「正式 Agent 只使用公開資訊」的設計。 

### Action Mask

可以沿用概念。

模型先產生所有候選動作的分數，
再利用 LegalActions 建立 Action Mask，
遮蔽目前不合法的動作。

因此策略最後實際輸出的 Decision
必須存在於 LegalActions 中。

### BC（Behavior Cloning）

可以沿用。

BC 可以先讓模型模仿規則型 baseline 或既有的決策資料，
讓模型在進入強化學習之前先學會基本策略。

本專題預計先使用台灣 16 張麻將模擬器產生決策資料，
再讓模型學習規則型 baseline 的選擇。

BC 也可以先驗證：

- Observation 是否正確
- Action 編碼是否正確
- Action Mask 是否正確
- 訓練資料是否可以正常讀取
- 模型是否能學會基本決策

台麻版本必須使用台灣 16 張資料重新訓練，
不能直接使用原本的日麻訓練資料與權重。

### DDQN（Double DQN）

可以沿用訓練方法與部分程式架構。

DDQN 可以在 BC 模型可以正常運作後，
再透過模擬對局進行強化學習。

但是以下內容必須改成台灣 16 張麻將版本：

- Observation
- Action Space
- Reward
- 遊戲環境
- 合法動作判定

如果後續 DDQN / VLOG 的實驗結果沒有穩定優於 baseline，
則可以繼續使用規則型策略或 BC 模型。

### Encoder / Latent / Action Head

可以沿用架構概念。

原版 VLOGMahjong 會先將 Observation 經過 Encoder，
轉換成 latent representation，
最後交給 Policy Network 或 Q Network 產生動作分數。

台麻版本可以繼續採用：

Observation
→ Encoder
→ Latent
→ Action Head

但是輸入與輸出的維度需要重新設計。

---

## 4. 台灣 16 張需要修改部分

### Observation 對應（W9 Day 1）

VLOG V1 的 Executor 用 `93 × 34` 的矩陣表示玩家可見資訊，每欄代表一種基本牌。
台麻沿用「從決策玩家的視角編碼」的做法，每筆決策使用固定的 555 維向量。
下表的切片均包含起點、不含終點。

| 牌局資訊 | VLOG V1 | 台麻 `tw16_bc_v1` |
|---|---|---|
| 自己的手牌 | 第 0–3 列逐張標記同種牌 | `[0:42]` 直接存張數。例如有兩張牌 ID 0，`features[0]` 就是 2 |
| 四家河牌 | 第 30–69 列，從自己起算相對座位 | `[42:210]` 依固定座位 0–3，各用 42 格統計牌數，不保留出牌順序 |
| 四家副露 | 第 6–29 列，依相對座位記錄副露牌 | `[210:378]` 依固定座位統計可見牌數，不保留每組吃碰槓的分組；對手暗槓牌面不編入 |
| 四家花牌 | 34 種基本牌以外沒有花牌欄位 | `[378:546]` 每家 42 格，記錄已補出的花牌 |
| 輪到誰、我是誰 | 第 78–79 列記錄場風與自風，意義與玩家編號不同 | `[546:550]` 表示輪到誰，`[550:554]` 表示決策者是誰，各用 4 格標記 |
| 剩餘牌數 | 玩家矩陣沒有獨立的剩餘張數欄位 | `[554:555]` 存剩餘張數除以 144，未知時填 `-1.0` |

555 維的算法是 `（1 組手牌 + 4 家河牌 + 4 家副露 + 4 家花牌）× 42 + 4 + 4 + 1`。
每組 42 格對應 34 種基本牌與 8 種花牌。

VLOG 第 80 列會標記當次動作的目標牌。台麻 v1 沒有獨立的 `last_discard` 特徵。
例如同一人先打三萬再打五萬，或先打五萬再打三萬，兩者的河牌計數完全相同。
因此模型單看河牌無法判斷剛打的是哪張。對手手牌、未開牌山、日麻寶牌與立直資訊也不納入台麻輸入。

### Action Space

VLOG V1 在第 81–92 列標記可執行的動作。台麻由規則端提供當下的 `LegalActions`，
策略端另建 125 格 `action_mask`。模型介面規格為每筆輸入 555 個特徵、輸出 125 個動作分數，
選擇時只比較當下合法的動作。

動作索引為出牌 `0–33`、吃 `34–54`、碰 `55–88`、槓 `89–122`、胡 `123`、過 `124`。
同一種牌的明槓、暗槓、加槓共用索引，實際槓別由合法動作的 `kong_type` 保留。

### 日本立直麻將環境

原專案的遊戲環境實作日本立直麻將規則，
不能直接作為本專題正式的台灣 16 張訓練環境。

本專題需要使用自行建立的：

- GameState
- LegalActions
- 台麻模擬器
- 台麻計分與流程

VLOGMahjong 只作為策略模型架構使用。

### 原版預訓練權重

原本的模型權重是在日本立直麻將的：

- Observation
- Action Space
- 規則
- 訓練資料

上訓練而成。

台灣 16 張麻將在手牌數量、規則、動作空間及策略上都有差異，
所以不能直接把原本日麻權重當成台麻模型使用。

本專題需要重新使用台麻資料訓練模型。

如果未來要嘗試 transfer learning，
也只能作為額外實驗，
不能預設原本日麻權重一定有效。

### Encoder 與 Action Head

原模型的 Encoder 是按照原本 Observation 大小建立，
Action Head 也是按照原本 Action Space 建立。

台麻 Observation 與 Action Space 修改後：

- Encoder 的輸入通道可能需要改
- Action Head 的輸出維度需要改
- Action Mask 長度需要改
- 原本 checkpoint 很可能不能直接載入

因此台麻版本需要重新建立符合新介面的模型。

---

## 5. 額外查核發現

目前查核到的 upstream 程式中：

VLOGMahjong legacy model 內的：

Action Size = 47

但是 V1 encoding 的部分程式，
在建立預設 action mask 時出現長度 54 的設定。

這可能是原專案不同版本或 legacy 相容設計所造成的差異。

因此本專題不應直接依照原專案的 47 或 54
來決定台麻 Action Space。

我們應自行建立統一的台麻 action 定義，確保：

Action Space
LegalActions
Action Mask
Model Action Head
Dataset Action Label

全部使用相同版本與相同編碼。

---

## 6. 與本專題模型介面的關係

本專題策略模型維持以下介面：

GameState / Observation
+
LegalActions
↓
Strategy / Model
↓
Decision

VLOGMahjong 位於 Strategy / Model 這一層。

它不負責：

- 畫面辨識
- 台麻規則合法性判定
- 滑鼠點擊
- UI
- 遊戲狀態真值維護

模型只負責從合法候選動作中選擇決策。

---

## 7. 結論

VLOGMahjong 不適合直接套用到台灣 16 張麻將，
但適合作為本專題的模型架構與訓練方法基底。

可以沿用的部分：

- Executor / Oracle 架構
- Action Mask 概念
- Encoder → Latent → Action Head 架構
- BC 訓練方法
- DDQN 訓練方法
- 從 LegalActions 中選擇 Decision 的設計

需要重新設計的部分：

- 台麻 Observation
- 台麻 Action Space
- LegalActions 對應方式
- 台麻遊戲環境
- 訓練資料
- Reward
- Encoder 輸入尺寸
- Action Head 輸出尺寸

原本日本立直麻將的預訓練權重不直接沿用。

因此本專題採用 VLOGMahjong 作為「模型架構基底」，
而不是直接使用既有的日本立直麻將模型。