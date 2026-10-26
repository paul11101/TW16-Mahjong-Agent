"""胡牌後的零和點數轉移。"""


class SettlementCalculator:
    """依台數與每台點數，計算自摸或放銃的分數變化。"""

    def __init__(self, points_per_fan: int = 100) -> None:
        if (
            not isinstance(points_per_fan, int)
            or isinstance(points_per_fan, bool)
            or points_per_fan <= 0
        ):
            raise ValueError("Points per fan must be a positive integer")
        self.points_per_fan = points_per_fan

    def settle(
        self,
        scores_dict: dict[int, int],
        *,
        winner_seat: int,
        total_fans: int,
        is_self_draw: bool,
        loser_seat: int | None = None,
    ) -> dict[int, int]:
        if (
            set(scores_dict) != {0, 1, 2, 3}
            or any(not isinstance(seat, int) or isinstance(seat, bool) for seat in scores_dict)
        ):
            raise ValueError("Scores must be provided for seats 0, 1, 2, and 3")
        if any(not isinstance(score, int) or isinstance(score, bool) for score in scores_dict.values()):
            raise ValueError("Player scores must be integers")
        if (
            not isinstance(winner_seat, int)
            or isinstance(winner_seat, bool)
            or winner_seat not in scores_dict
        ):
            raise ValueError(f"Unknown winner seat: {winner_seat}")
        if not isinstance(total_fans, int) or isinstance(total_fans, bool) or total_fans < 0:
            raise ValueError("Total fans must be a non-negative integer")

        if is_self_draw:
            if loser_seat is not None:
                raise ValueError("A loser seat must not be provided for self-draw")
            payers = [seat for seat in scores_dict if seat != winner_seat]
        else:
            if (
                not isinstance(loser_seat, int)
                or isinstance(loser_seat, bool)
                or loser_seat not in scores_dict
            ):
                raise ValueError("A valid loser seat is required for discard wins")
            if loser_seat == winner_seat:
                raise ValueError("Winner and loser seats must be different")
            payers = [loser_seat]

        payment = total_fans * self.points_per_fan
        updated_scores = scores_dict.copy()
        for payer in payers:
            updated_scores[payer] -= payment
            updated_scores[winner_seat] += payment
        return updated_scores
