# VLOGMahjong 架構查核

> W1 Day 2｜模型與策略  
> 查核日期：2026-09-18

## 1. 查核目的

本文件用來確認 Agony5757/mahjong 專案中的 VLOGMahjong 是否適合作為本專題「台灣 16 張麻將 Agent」的模型架構基底，並區分哪些部分可以沿用、哪些部分必須重新設計。

本專題不直接套用日本立直麻將的規則、Observation、Action Space 或既有模型權重。

## 2. 專案來源

VLOGMahjong 來自 Agony5757/mahjong。

原專案主要是一套日本立直麻將 AI 研究環境，包含：

- 日本立直麻將遊戲環境
- 單人與多人 Agent 環境
- VLOGMahjong 模型
- BC（Behavior Cloning）
- DDQN（Double DQN）
- Oracle Observation
- 預訓練對手模型
- Gymnasium 風格介面

專案採 Apache-2.0 授權。

## 3. VLOGMahjong 基本架構

VLOGMahjong 的核心概念是把「正式推論時玩家能看到的資訊」與「訓練時模擬器知道的完整資訊」分開。

### Executor

Executor 代表正式對局時真正使用的模型。

正式推論時只能使用玩家可以取得的公開資訊，例如自己的手牌、公開牌河、副露與其他可見狀態，不應取得對手暗牌或未知牌山內容。

### Oracle

Oracle 只在訓練階段使用。

模擬器在訓練時知道完整牌局真值，因此 Oracle 可以讀取比 Executor 更多的資訊，協助模型學習。

正式部署時不能讓 Executor 取得這些隱藏資訊。

### 原版資料尺寸

目前 VLOGMahjong 舊版 V1 encoding 的主要尺寸為：

- Executor Observation：93 × 34
- Oracle 額外資訊：18 × 34
- Oracle 完整 Observation：111 × 34
- VLOGMahjong Action Size：47

其中 34 對應日本立直麻將的 34 種基本牌型。

### 模型流程

概念流程如下：

```text
Observation
    ↓
Encoder
    ↓
Latent Representation
    ↓
Policy Network / Q Network
    ↓
Action Mask
    ↓
Action
```

訓練時則另外加入 Oracle 分支，利用完整狀態輔助學習。

## 4. 支援的訓練方法

### BC（Behavior Cloning）

VLOGMahjong 支援 BC。

BC 可以先讓模型模仿既有策略或示範資料。本專題可先用台麻規則型 baseline 產生決策資料，再讓模型學習這些決策。

BC 適合作為正式強化學習之前的第一階段，因為可以先驗證：

- Observation 是否正確
- Action 編碼是否正確
- Action Mask 是否正確
- Dataset pipeline 是否能正常運作
- 模型能否學會基本合法決策

台麻版本必須使用台灣 16 張麻將資料重新訓練，不能直接把日麻資料或權重當成台麻模型。

### DDQN（Double DQN）

VLOGMahjong 也支援 DDQN。

本專題可以在 BC 模型可正常運作後，再評估使用 DDQN 進行有限度的強化學習。

但是 DDQN 所使用的環境、reward、Observation、Action Space 和合法動作判定都必須按照台灣 16 張麻將重新設計。

如果後續實驗沒有穩定優於規則型 baseline，則保留 baseline 或 BC 模型作為正式策略。

## 5. 可沿用部分

### 5.1 Executor / Oracle 架構

可以沿用。

台灣 16 張麻將同樣屬於不完全資訊遊戲。正式 Agent 只能使用玩家可見資訊，而模擬器在訓練階段可以取得完整牌局真值。

因此可以保留「Executor 只讀公開資訊、Oracle 只在訓練端使用完整資訊」的設計。

### 5.2 Action Mask

可以沿用概念。

模型可以先產生所有 Action 的分數，再利用 LegalActions 建立 Action Mask，把目前不合法的動作遮蔽。

因此最終實際執行的 Decision 必須存在於 LegalActions 中。

### 5.3 Encoder → Latent → Action Head

可以沿用架構概念。

VLOGMahjong 先將 Observation 經過 Encoder，再轉成 latent representation，最後交給 Policy Network 或 Q Network 產生決策。

台麻版本可以保留這種模型分層方式，但輸入與輸出維度必須重新設計。

### 5.4 BC / DDQN 訓練流程

可以沿用方法與部分程式設計概念。

本專題預計先做：

```text
台麻規則型 baseline
        ↓
產生台麻決策資料
        ↓
BC 預訓練
        ↓
固定測試集評估
        ↓
選做 DDQN / VLOG 強化學習
```

### 5.5 合法動作後再做決策的設計

可以沿用。

策略模型不負責判斷台麻規則是否合法，而是接收規則模組提供的 LegalActions，再從合法候選中選擇 Decision。

這可以讓規則與模型彼此分離，之後更換模型時不需要重新實作台麻合法性判定。

## 6. 台灣 16 張需要修改部分

### 6.1 Observation

原版 Executor Observation 為 93 × 34，Oracle 完整 Observation 為 111 × 34。

93 與 111 的特徵設計是依照日本立直麻將環境建立，包含日麻特有的狀態，因此不能直接套用到台灣 16 張麻將。

台麻版本需要重新定義 Observation，至少考慮：

- 自己的 16 / 17 張手牌
- 各玩家牌河
- 吃、碰、槓等公開副露
- 公開花牌
- 當前玩家
- 自己的座位
- 輪次
- 剩餘牌數等可見資訊
- 後續策略需要的其他公開特徵

Observation 的最終 tensor 維度等到 GameState 與牌編碼介面確定後再固定。

### 6.2 Action Space

VLOGMahjong legacy model 目前將 Action Size 設為 47。

台灣 16 張麻將與日本立直麻將的合法動作與流程不同，因此不能直接沿用原本 47 個 Action 的編碼。

台麻版本需要重新定義：

- discard
- chi
- pong
- kong
- win
- pass

並視規則介面決定是否需要把不同牌、不同吃法或不同槓型編成獨立 action index。

最後由 LegalActions 產生與新 Action Space 對應的 Action Mask。

### 6.3 日本立直麻將環境

原專案環境完整實作的是日本立直麻將，不是台灣 16 張麻將。

因此不能直接把原環境作為正式台麻訓練環境。

本專題應使用團隊自行建立的台麻 GameState、LegalActions 與模擬器；VLOGMahjong 只作為模型架構與訓練方法的基底。

### 6.4 原版預訓練權重

原模型權重是在日本立直麻將 Observation、Action Space、規則與資料分布上訓練。

台麻在手牌張數、規則、動作空間與策略目標上都不同，因此不能直接把原本日麻權重當成台麻模型。

台麻版本需要重新訓練。

如果後續要研究部分參數初始化或 transfer learning，也必須獨立做實驗驗證，不能預設原權重一定有幫助。

### 6.5 Encoder 輸入尺寸與 Action Head

原模型的 Encoder 與 Action Head 都依原本 Observation 與 Action Size 建立。

當台麻 Observation 與 Action Space 改變後：

- Encoder 的輸入通道數可能需要修改
- Action Head 的輸出維度需要修改
- Action Mask 的長度需要跟新 Action Space 一致
- 舊 checkpoint 很可能無法直接載入

因此模型結構必須配合台麻介面重新建立。

## 7. 查核時發現的相容性注意事項

目前 upstream 程式中，legacy `VLOGMahjong` 的 `action_size` 設定為 47。

但是 V1 encoding 的 `collate_fn` 中，缺少 action mask 時建立的預設 mask 長度為 54。

這代表目前 upstream 不同模組之間可能存在版本演進或 legacy 相容性差異。

本專題不應依賴這些數字直接定義台麻 Action Space，而應自行建立唯一的台麻 action schema，並讓：

```text
Action Space
LegalActions
Action Mask
Model Action Head
Dataset label
```

全部使用同一份版本化定義。

## 8. 與本專題策略介面的關係

本專題的策略介面維持：

```text
GameState / Observation
        +
LegalActions
        ↓
Strategy / Model
        ↓
Decision
```

VLOGMahjong 位於 Strategy / Model 這一層。

它不負責：

- 畫面辨識
- 台麻規則合法性判定
- 滑鼠操作
- UI
- 狀態真值維護

這些工作由其他模組提供。

## 9. 結論

VLOGMahjong 不適合直接套用到台灣 16 張麻將，但適合作為本專題的模型架構與訓練方法基底。

目前判定可沿用的部分包括：

- Executor / Oracle 架構
- Action Mask 概念
- Encoder → Latent → Action Head 架構
- BC 訓練方法
- DDQN 訓練方法
- 合法候選後再做策略選擇的設計

必須重新設計的部分包括：

- 台麻 Observation
- 台麻 Action Space
- LegalActions 對應方式
- 台麻遊戲環境
- 訓練資料
- Reward
- Encoder 輸入尺寸
- Action Head 輸出尺寸

原本日本立直麻將的預訓練權重不直接沿用。

因此本專題採用 VLOGMahjong 作為「架構基底」，而不是直接使用既有日本立直麻將模型。

## 10. 查核來源

- Agony5757/mahjong README
- `pymahjong/models.py`
- `pymahjong/rl/encodings/v1.py`
- 本專題《台灣 16 張麻將 Agent 技術實踐》規劃文件
