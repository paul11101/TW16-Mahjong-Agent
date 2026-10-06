from functools import lru_cache
from .interfaces import Tile


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

        # 使用快取避免相同牌型重複計算
        @lru_cache(maxsize=None)
        def search(state: tuple[int, ...], melds: int, pair: int, taatsu: int) -> int:
            # tuple 不能直接修改，因此轉成 list
            cards = list(state)
            current = None

            # 找出目前第一張還沒有處理的牌
            for i, count in enumerate(cards):
                if count > 0:
                    current = i
                    break

            # 如果所有牌都處理完成，就計算目前的向聽數
            if current is None:
                # 搭子數不能超過剩餘需要的面子數
                usable_taatsu = min(taatsu, max(0, self.MAX_MELDS - melds))

                # 一般牌型向聽數公式
                return self.MAX_MELDS * 2 - melds * 2 - usable_taatsu - pair

            # 目前正在處理的牌 ID
            tile = current

            # 先設定一個很大的值，之後尋找最小向聽數
            best = 99

            # 情況 1：目前這張牌不組成任何牌型，直接略過
            cards[tile] -= 1
            best = min(best, search(tuple(cards), melds, pair, taatsu))
            cards[tile] += 1

            # 情況 2：三張相同的牌可以組成刻子
            if cards[tile] >= 3:
                # 暫時移除三張相同牌
                cards[tile] -= 3

                # 完成一組面子後繼續搜尋
                best = min(best, search(tuple(cards), melds + 1, pair, taatsu))

                # 搜尋完成後恢復牌數
                cards[tile] += 3

            # 情況 3：同花色連續三張牌可以組成順子
            if (tile < 27 and tile % 9 <= 6 and cards[tile + 1] > 0 and cards[tile + 2] > 0):
                # 暫時移除順子的三張牌
                cards[tile] -= 1
                cards[tile + 1] -= 1
                cards[tile + 2] -= 1

                # 完成一組面子後繼續搜尋
                best = min(best, search(tuple(cards), melds + 1, pair, taatsu))

                # 搜尋完成後恢復牌數
                cards[tile] += 1
                cards[tile + 1] += 1
                cards[tile + 2] += 1

            # 情況 4：兩張相同的牌可以作為眼睛或搭子
            if cards[tile] >= 2:
                # 暫時移除這一對牌
                cards[tile] -= 2

                # 如果目前還沒有眼睛，可以把這一對當成眼睛
                if pair == 0:
                    best = min(best, search(tuple(cards), melds, 1, taatsu))

                # 也可以把這一對當成未完成的搭子
                best =  min(best, search(tuple(cards), melds, pair, taatsu + 1))

                # 搜尋完成後恢復牌數
                cards[tile] += 2

            # 情況 5：兩張相鄰的同花色牌可以形成搭子
            if (tile < 27 and tile % 9 <= 7 and cards[tile + 1] > 0):
                # 暫時移除兩張相鄰牌
                cards[tile] -= 1
                cards[tile + 1] -= 1

                # 搭子數增加一組後繼續搜尋
                best = min(best, search(tuple(cards), melds, pair, taatsu + 1))

                # 搜尋完成後恢復牌數
                cards[tile] += 1
                cards[tile + 1] += 1

            # 情況 6：中間差一張的同花色牌可以形成嵌張搭子
            if (tile < 27 and tile % 9 <= 6 and cards[tile + 2] > 0):
                # 暫時移除這兩張牌
                cards[tile] -= 1
                cards[tile + 2] -= 1

                # 搭子數增加一組後繼續搜尋
                best = min(best, search(tuple(cards), melds, pair, taatsu + 1))

                # 搜尋完成後恢復牌數
                cards[tile] += 1
                cards[tile + 2] += 1

            # 回傳所有組合中最低的向聽數
            return best

        # 從沒有面子、沒有眼睛、沒有搭子的狀態開始搜尋
        return search(tuple(counts), 0, 0, 0)