"""台灣十六張麻將的基礎台數計算。"""

from typing import Sequence

from src.common.schemas import ActionType

from .game_state import Meld, is_basic_win
from .rule import DEFAULT_SCORING_TAI, RulesetConfig


def _is_all_sequences(hand: Sequence[int], meld_count: int) -> bool:
    if not is_basic_win(list(hand), meld_count=meld_count):
        return False

    counts = [0] * 34
    for tile_id in hand:
        if not 0 <= tile_id < 34:
            return False
        counts[tile_id] += 1

    def remove_sequences(remaining: list[int]) -> bool:
        try:
            tile_id = next(index for index, count in enumerate(remaining) if count)
        except StopIteration:
            return True

        if (
            tile_id < 27
            and tile_id % 9 <= 6
            and remaining[tile_id + 1]
            and remaining[tile_id + 2]
        ):
            remaining[tile_id] -= 1
            remaining[tile_id + 1] -= 1
            remaining[tile_id + 2] -= 1
            if remove_sequences(remaining):
                return True
            remaining[tile_id] += 1
            remaining[tile_id + 1] += 1
            remaining[tile_id + 2] += 1
        return False

    for tile_id, count in enumerate(counts):
        if count >= 2:
            counts[tile_id] -= 2
            if remove_sequences(counts):
                return True
            counts[tile_id] += 2
    return False


def _is_sequence_meld(meld: Meld) -> bool:
    tiles = sorted(meld.tiles)
    return (
        meld.meld_type == ActionType.CHI
        and len(tiles) == 3
        and all(0 <= tile_id < 27 for tile_id in tiles)
        and tiles[0] // 9 == tiles[1] // 9 == tiles[2] // 9
        and tiles[1] == tiles[0] + 1
        and tiles[2] == tiles[1] + 1
    )


class FanCalculator:
    """計算底台、自摸、莊家連莊、門清與平胡台數。"""

    def calculate(
        self,
        hand: Sequence[int],
        *,
        winner_seat: int,
        dealer_seat: int,
        lian_zhuang: int = 0,
        is_self_draw: bool = False,
        melds: Sequence[Meld] = (),
        flowers: Sequence[int] = (),
        config: RulesetConfig | None = None,
    ) -> tuple[int, list[tuple[str, int]]]:
        if (
            not isinstance(winner_seat, int)
            or isinstance(winner_seat, bool)
            or not isinstance(dealer_seat, int)
            or isinstance(dealer_seat, bool)
            or not 0 <= winner_seat <= 3
            or not 0 <= dealer_seat <= 3
        ):
            raise ValueError("Winner and dealer seats must be between 0 and 3")
        if (
            not isinstance(lian_zhuang, int)
            or isinstance(lian_zhuang, bool)
            or lian_zhuang < 0
        ):
            raise ValueError("Consecutive dealer count must be a non-negative integer")

        scoring_tai = (config or RulesetConfig()).scoring_tai

        def tai(key: str) -> int:
            value = scoring_tai.get(key, DEFAULT_SCORING_TAI[key])
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"Tai value for {key!r} must be a non-negative integer")
            return value

        details: list[tuple[str, int]] = []

        def add_detail(name: str, value: int) -> None:
            if value:
                details.append((name, value))

        add_detail("底台", tai("base_tai"))
        if is_self_draw:
            add_detail("自摸", tai("self_draw"))
        if winner_seat == dealer_seat:
            add_detail("莊家台", tai("dealer_tai"))
            add_detail("連莊台", lian_zhuang)

        is_menqing = all(
            meld.meld_type == ActionType.CHI
            or (
                meld.meld_type == ActionType.KONG
                and meld.kong_type == "an"
            )
            for meld in melds
        ) and not any(
            meld.meld_type in (ActionType.CHI, ActionType.PONG)
            or (
                meld.meld_type == ActionType.KONG
                and meld.kong_type != "an"
            )
            for meld in melds
        )
        if is_menqing:
            add_detail("門清", tai("in_hand"))

        if (
            not flowers
            and all(0 <= tile_id < 27 for tile_id in hand)
            and all(_is_sequence_meld(meld) for meld in melds)
            and _is_all_sequences(hand, len(melds))
        ):
            add_detail("平胡", tai("ping_hu"))

        return sum(value for _, value in details), details
