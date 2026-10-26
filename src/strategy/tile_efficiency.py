from typing import Iterable, Iterator, Protocol

from .interfaces import Tile


# 定義向聽計算器需要遵守的介面
class ShantenCalculator(Protocol):
    def calculate(self, hand: tuple[Tile, ...]) -> int:
        ...


# 模擬從手牌中打出指定的一張牌
def remove_discard(
    hand: tuple[Tile, ...],
    tile: Tile,
) -> tuple[Tile, ...]:
    # 轉成 list，避免修改原本的手牌
    cards = list(hand)

    if tile not in cards:
        raise ValueError(f"discard tile not in hand: {tile}")

    # 只移除一張相同的牌
    cards.remove(tile)

    return tuple(cards)


# 計算打出指定牌之後的向聽數
def shanten_after_discard(
    hand: tuple[Tile, ...],
    tile: Tile,
    calculator: ShantenCalculator,
) -> int:
    remaining_hand = remove_discard(hand, tile)

    return calculator.calculate(remaining_hand)


# 找出目前手牌的所有有效進張
def effective_draws(
    hand: tuple[Tile, ...],
    calculator: ShantenCalculator,
    current_shanten: int | None = None,
) -> tuple[Tile, ...]:
    # 已經計算過向聽數時，直接沿用結果
    if current_shanten is None:
        current_shanten = calculator.calculate(hand)

    effective_tiles = []

    # 只檢查 34 種基本牌，花牌不參與一般牌型組合
    for tile in range(34):
        # 同種牌最多四張，不模擬摸到第五張
        if hand.count(tile) >= 4:
            continue

        # 模擬摸入一張牌
        next_hand = hand + (tile,)
        next_shanten = calculator.calculate(next_hand)

        # 向聽數下降，代表這張牌是有效進張
        if next_shanten < current_shanten:
            effective_tiles.append(tile)

    return tuple(effective_tiles)


# 共用棄牌評估，先比較向聽數，再計算有效進張
def iter_best_discard_evaluations(
    hand: tuple[Tile, ...],
    discard_tiles: Iterable[Tile],
    calculator: ShantenCalculator,
) -> Iterator[tuple[Tile, int, tuple[Tile, ...]]]:
    # 保存棄牌後的手牌與向聽數，並保留候選順序
    candidates = {}

    for tile in discard_tiles:
        # 相同牌種只計算一次
        if tile not in candidates:
            remaining = remove_discard(hand, tile)

            candidates[tile] = (
                remaining,
                calculator.calculate(remaining),
            )

    # 沒有候選時直接結束
    if not candidates:
        return

    # 找出所有候選中最低的向聽數
    best_shanten = min(
        shanten for _, shanten in candidates.values()
    )

    # 只對最低向聽的候選計算有效進張
    for tile, (remaining, shanten) in candidates.items():
        if shanten == best_shanten:
            draws = effective_draws(
                remaining,
                calculator,
                current_shanten=shanten,
            )

            # 回傳棄牌、向聽數與有效進張
            yield tile, shanten, draws


# 評估打出指定牌後的向聽數與有效進張
def evaluate_discard(
    hand: tuple[Tile, ...],
    tile: Tile,
    calculator: ShantenCalculator,
) -> tuple[int, tuple[Tile, ...]]:
    # 單一棄牌也沿用共用評估流程
    _, shanten, draws = next(
        iter_best_discard_evaluations(
            hand,
            (tile,),
            calculator,
        )
    )

    return shanten, draws