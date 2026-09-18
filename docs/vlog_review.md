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

### Observation

原版 Executor Observation 為 93 × 34，
Oracle Observation 為 111 × 34。

這些特徵是按照日本立直麻將的狀態設計，
因此不能直接套用到台灣 16 張麻將。

台麻版本需要重新定義 Observation。

預計需要包含：

- 自己的手牌
- 各玩家已打出的牌
- 公開的吃、碰、槓
- 公開花牌
- 當前玩家
- 自己的座位
- 輪次
- 剩餘牌數等玩家可見資訊

最終 Observation 的 tensor 大小，
等 GameState 與牌編碼格式確定後再固定。

### Action Space

原版 VLOGMahjong 使用固定的 Action Size 47。

台灣 16 張麻將與日本立直麻將在動作及規則上有所差異，
因此不能直接使用原本的 47 個 Action。

目前台麻策略至少需要支援：

- discard
- chi
- pong
- kong
- win
- pass

之後還需要決定：

- 不同出牌是否各自對應 action index
- 不同吃牌組合如何表示
- 明槓、暗槓、加槓是否分開
- Action Mask 的最終長度

這些都需要與 LegalActions 的格式統一。

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