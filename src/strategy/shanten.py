from functools import lru_cache
from .interfaces import Tile


# 跨 calculate() 共用遞迴結果，限制快取容量避免長時間模擬耗盡記憶體
# max_melds 必須納入快取鍵，確保一般牌型與不同副露數量不會共用錯誤結果
@lru_cache(maxsize=200_000)
def _search(state: tuple[int, ...], melds: int, pair: int, taatsu: int, max_melds: int) -> int:
    # 優先找出第一張尚未處理的牌，牌用盡時直接回傳向聽數
    for tile, count in enumerate(state):
        if count > 0:
            break
    else:
        usable_taatsu = min(taatsu, max(0, max_melds - melds))
        return max_melds * 2 - melds * 2 - usable_taatsu - pair

    # 每一條分支修改前後都還原牌數，避免影響其他拆牌方式
    cards = list(state)
    best = 99

    # 情況 1：把目前這張牌當成孤張
    cards[tile] -= 1
    best = min(best, _search(tuple(cards), melds, pair, taatsu, max_melds))
    cards[tile] += 1

    # 情況 2：刻子
    if cards[tile] >= 3:
        cards[tile] -= 3
        best = min(best, _search(tuple(cards), melds + 1, pair, taatsu, max_melds))
        cards[tile] += 3

    # 情況 3：順子（僅適用 0~26 的三種數牌）
    if tile < 27 and tile % 9 <= 6 and cards[tile + 1] > 0 and cards[tile + 2] > 0:
        cards[tile] -= 1
        cards[tile + 1] -= 1
        cards[tile + 2] -= 1
        best = min(best, _search(tuple(cards), melds + 1, pair, taatsu, max_melds))
        cards[tile] += 1
        cards[tile + 1] += 1
        cards[tile + 2] += 1

    # 情況 4：對子，分別嘗試眼睛與搭子
    if cards[tile] >= 2:
        cards[tile] -= 2
        if pair == 0:
            best = min(best, _search(tuple(cards), melds, 1, taatsu, max_melds))
        best = min(best, _search(tuple(cards), melds, pair, taatsu + 1, max_melds))
        cards[tile] += 2

    # 情況 5：相鄰搭子
    if tile < 27 and tile % 9 <= 7 and cards[tile + 1] > 0:
        cards[tile] -= 1
        cards[tile + 1] -= 1
        best = min(best, _search(tuple(cards), melds, pair, taatsu + 1, max_melds))
        cards[tile] += 1
        cards[tile + 1] += 1

    # 情況 6：嵌張搭子
    if tile < 27 and tile % 9 <= 6 and cards[tile + 2] > 0:
        cards[tile] -= 1
        cards[tile + 2] -= 1
        best = min(best, _search(tuple(cards), melds, pair, taatsu + 1, max_melds))
        cards[tile] += 1
        cards[tile + 2] += 1

    return best


# 台灣 16 張麻將一般牌型的向聽數計算器
class Taiwan16ShantenCalculator:
    # 台灣 16 張胡牌需要 5 組面子
    MAX_MELDS = 5

    # 計算目前手牌的向聽數
    def calculate(self,hand: tuple[Tile, ...]) -> int:
        # 建立 34 種基本牌的數量表
        counts = [0] * 34

        # 統計目前手牌中每種牌的數量
        for tile in hand:
            # 牌 ID 合法範圍為 0~41
            if not 0 <= tile <= 41:
                raise ValueError(f"invalid tile id: {tile}")

            # 花牌 34~41 不參與一般牌型的向聽計算
            if tile >= 34:
                continue

            # 對應牌的數量加一
            counts[tile] += 1

            # 一種普通牌最多只能有四張
            if counts[tile] > 4:
                raise ValueError(f"too many copies of tile:  {tile}")

        # 現在重複呼叫 calculate() 也能命中先前拆牌時的搜尋結果
        return _search(tuple(counts), 0, 0, 0, self.MAX_MELDS)
