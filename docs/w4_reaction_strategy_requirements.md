# W4 Reaction Strategy Requirements

## 1. 本週目標

在 W3 Baseline v0 的基礎上，擴充台灣 16 張麻將的反應策略，支援：

- CHI：吃牌
- PONG：碰牌
- KONG：槓牌
- WIN：胡牌
- PASS：放棄反應

Strategy 只負責選擇動作，動作是否合法由 Rules 模組決定。

## 2. 策略輸入

沿用 `src/strategy/interfaces.py` 的介面：

```python
def decide(
    self,
    observation: Observation,
    legal_actions: LegalActions,
) -> Decision:
```

`Observation` 提供自己手牌、河牌、副露、花牌、座位與剩餘牌數等資訊。

`LegalActions` 提供 Rules 已經確認合法的候選動作。

### 自己回合

可能出現 WIN、KONG、DISCARD。

### 其他玩家出牌後

可能出現 WIN、CHI、PONG、KONG、PASS。

策略不得選擇 LegalActions 以外的動作。

## 3. 基本決策規則

1. **WIN**：只要 Rules 提供合法 WIN，優先胡牌。
2. **CHI**：評估吃牌後的手牌結構及向聽變化。
3. **PONG**：評估碰牌後的牌型改善程度。
4. **KONG**：區分明槓、暗槓、加槓，評估槓牌後的影響。
5. **PASS**：當吃、碰、槓沒有足夠收益時，可以選擇 PASS。

CHI、PONG、KONG 不應只按固定優先順序決定，後續應比較牌型收益。

## 4. 策略輸出

沿用原本的 `Decision`：

- `action`：最終選擇的合法動作
- `score`：策略評估分數
- `reason`：選擇此動作的原因

## 5. 目前需要處理的介面問題

### 槓牌類型

Rules 已提供 `kong_type`：

- `ming`：明槓
- `an`：暗槓
- `jia`：加槓

但 Strategy Adapter 目前沒有完整保留這個資訊，後續需要調整。

### 副露向聽

W3 向聽計算器目前以未副露的「5 面子 + 1 對眼睛」為目標。

W4 評估吃、碰、槓時，需要考慮已經完成的副露面子數。

### 反應資訊

後續若需判斷出牌來源與反應情境，應確認 Observation 或反應上下文能提供必要資訊。

## 6. W4 後續安排

- D2：實作基本反應策略
- D3：加入吃、碰後牌型評估
- D4：加入槓牌與 PASS 的評估及測試
- D5：比較反應策略結果並修正問題

## 7. Day 1 完成標準

- 定義五種反應動作的輸入與輸出
- 確認沿用現有 Strategy 介面
- 整理需要與 Rules、Integration 對接的欄位
- 記錄目前缺少的副露評估能力