# W3 Strategy Review

## 已完成

- 基本出牌策略需求
- 向聽數計算介面
- 台灣 16 張一般牌型向聽計算
- 有效進張判斷
- Baseline v0
- 固定牌型測試
- RandomPolicy 與 BaselinePolicy 比較
- 邊界與錯誤輸入測試

## Baseline v0 決策順序

1. 優先選擇較低向聽數
2. 向聽相同時選擇有效進張種類較多的棄牌
3. 條件仍相同時維持合法動作原本順序

## W3 測試範圍

目前測試包含：

- 完成牌型
- 聽牌
- 一向聽
- 有效進張
- 孤張字牌
- 保留對子
- 混合牌型
- Random vs Baseline
- 非法牌 ID
- 同種牌超過四張
- 花牌不參與向聽
- 不允許第五張牌成為有效進張
- Baseline 只選 LegalActions
- Baseline 決策可重現

## 目前限制

### 有效進張數量

目前使用：

effective_count = len(effective_draws)

因此計算的是「有效進張種類數」，
尚未根據河牌、副露與自己手牌計算實際剩餘張數。

### 副露牌型

目前 Taiwan16ShantenCalculator 固定以：

5 組面子 + 1 組眼睛

作為目標。

尚未把已經完成的吃、碰、槓副露數量加入向聽計算。

此部分在後續反應策略與副露處理時調整。

### 特殊牌型

Baseline v0 目前只處理一般牌型，
尚未加入特殊胡牌牌型。

## W3 結論

Baseline v0 已能根據合法 DISCARD：

LegalActions
→ 模擬棄牌
→ 計算向聽
→ 計算有效進張
→ 比較候選動作
→ Decision

可作為後續 W4 吃、碰、槓、胡、PASS 策略的基礎。