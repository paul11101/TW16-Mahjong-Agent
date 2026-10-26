"""結構化單局結果與終端摘要呈現。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from .game_state import GameState


class WinType(str, Enum):
    SELF_DRAW = "self_draw"
    DISCARD_WIN = "discard_win"
    DRAW = "draw"


@dataclass(frozen=True)
class WinnerFanResult:
    seat: int
    total_fans: int
    fan_details: tuple[tuple[str, int], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "seat": self.seat,
            "total_fans": self.total_fans,
            "fan_details": [
                {"name": name, "fans": fans}
                for name, fans in self.fan_details
            ],
        }


@dataclass(frozen=True)
class GameResult:
    round_number: int
    round_wind: int
    dealer_seat: int
    lianzhuang_count: int
    winner_seats: tuple[int, ...]
    loser_seat: int | None
    win_type: WinType
    winner_fan_results: Mapping[int, WinnerFanResult]
    score_delta: Mapping[int, int]
    scores_dict: Mapping[int, int]

    @property
    def total_fans(self) -> int | None:
        """回傳單一胡家的台數；多響時各家台數見 winner_fan_results。"""
        if len(self.winner_seats) != 1:
            return None
        return self.winner_fan_results[self.winner_seats[0]].total_fans

    @property
    def fan_details(self) -> tuple[tuple[str, int], ...]:
        """回傳單一胡家的台數明細；多響時見 winner_fan_results。"""
        if len(self.winner_seats) != 1:
            return ()
        return self.winner_fan_results[self.winner_seats[0]].fan_details

    @property
    def round_label(self) -> str:
        wind_name = ("東", "南", "西", "北")[self.round_wind]
        return f"{wind_name}風場第 {self.round_number} 局"

    def to_dict(self) -> dict[str, object]:
        return {
            "round_number": self.round_number,
            "round_label": self.round_label,
            "round_wind": self.round_wind,
            "dealer_seat": self.dealer_seat,
            "lianzhuang_count": self.lianzhuang_count,
            "winner_seats": list(self.winner_seats),
            "loser_seat": self.loser_seat,
            "win_type": self.win_type.value,
            "total_fans": self.total_fans,
            "fan_details": [
                {"name": name, "fans": fans} for name, fans in self.fan_details
            ],
            "winner_fan_results": {
                str(seat): result.to_dict()
                for seat, result in self.winner_fan_results.items()
            },
            "score_delta": {
                str(seat): delta for seat, delta in self.score_delta.items()
            },
            "scores_dict": {
                str(seat): score for seat, score in self.scores_dict.items()
            },
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


@dataclass(frozen=True)
class GameSummary:
    rounds: tuple[GameResult, ...]
    winner_counts: Mapping[int, int]
    draw_count: int
    final_scores: Mapping[int, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "round_count": len(self.rounds),
            "winner_counts": {
                str(seat): wins for seat, wins in self.winner_counts.items()
            },
            "draw_count": self.draw_count,
            "final_scores": {
                str(seat): score for seat, score in self.final_scores.items()
            },
            "rounds": [result.to_dict() for result in self.rounds],
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class GameResultPresenter:
    """從結算後、莊家更新前的 GameState 建立單局結果快照。"""

    @staticmethod
    def create_result(
        state: GameState,
        *,
        round_number: int,
        scores_before: Mapping[int, int],
        winner_seats: Sequence[int] = (),
        loser_seat: int | None = None,
        win_type: WinType,
        total_fans: int | None = None,
        fan_details: Sequence[tuple[str, int]] = (),
        winner_fan_results: Mapping[
            int, WinnerFanResult | tuple[int, Sequence[tuple[str, int]]]
        ]
        | None = None,
    ) -> GameResult:
        if (
            not isinstance(round_number, int)
            or isinstance(round_number, bool)
            or round_number < 1
        ):
            raise ValueError("Round number must be at least 1")
        if state.round_wind not in range(4):
            raise ValueError("Round wind must be between 0 and 3")
        if state.dealer not in range(4):
            raise ValueError("Dealer seat must be between 0 and 3")
        if set(state.players) != {0, 1, 2, 3} or set(scores_before) != {0, 1, 2, 3}:
            raise ValueError("Game result requires scores and players for seats 0-3")

        winners = tuple(winner_seats)
        if len(set(winners)) != len(winners) or any(
            not isinstance(seat, int)
            or isinstance(seat, bool)
            or seat not in range(4)
            for seat in winners
        ):
            raise ValueError("Winner seats must be unique seats between 0 and 3")
        if not isinstance(win_type, WinType):
            raise ValueError("win_type must be a WinType")
        if win_type == WinType.DRAW:
            if winners or loser_seat is not None:
                raise ValueError("A drawn round cannot have winners or a loser")
        elif not winners:
            raise ValueError("A winning result must include at least one winner")
        if win_type == WinType.DISCARD_WIN:
            if (
                not isinstance(loser_seat, int)
                or isinstance(loser_seat, bool)
                or loser_seat not in range(4)
                or loser_seat in winners
            ):
                raise ValueError("Discard wins require a valid non-winning loser seat")
        elif loser_seat is not None:
            raise ValueError("Only a discard win can have a loser seat")

        fan_results: dict[int, WinnerFanResult] = {}
        provided_fan_results = winner_fan_results or {}
        if win_type == WinType.DRAW:
            if total_fans not in (None, 0) or fan_details or provided_fan_results:
                raise ValueError("A drawn round cannot include fan results")
        elif len(winners) == 1 and not provided_fan_results:
            if (
                not isinstance(total_fans, int)
                or isinstance(total_fans, bool)
                or total_fans < 0
            ):
                raise ValueError("A non-negative total_fans value is required")
            fan_results[winners[0]] = WinnerFanResult(
                winners[0],
                total_fans,
                tuple(fan_details),
            )
        else:
            if total_fans is not None or fan_details:
                raise ValueError(
                    "Use winner_fan_results to provide per-winner fans for multiple winners"
                )
            if set(provided_fan_results) != set(winners):
                raise ValueError("Fan results must be provided for every winner")
            for seat in winners:
                result = provided_fan_results[seat]
                if isinstance(result, WinnerFanResult):
                    fan_result = result
                    if fan_result.seat != seat:
                        raise ValueError("Fan result seat must match its winner seat")
                else:
                    fans, details = result
                    fan_result = WinnerFanResult(seat, fans, tuple(details))
                if (
                    not isinstance(fan_result.total_fans, int)
                    or isinstance(fan_result.total_fans, bool)
                    or fan_result.total_fans < 0
                ):
                    raise ValueError("Total fans must be a non-negative integer")
                fan_results[seat] = fan_result

        for fan_result in fan_results.values():
            if any(
                not isinstance(name, str)
                or not isinstance(fans, int)
                or isinstance(fans, bool)
                or fans < 0
                for name, fans in fan_result.fan_details
            ):
                raise ValueError("Fan details require names and non-negative integers")
            if sum(fans for _, fans in fan_result.fan_details) != fan_result.total_fans:
                raise ValueError("Fan details must sum to the winner's total fans")

        scores_after = {seat: player.score for seat, player in state.players.items()}
        if any(
            not isinstance(score, int) or isinstance(score, bool)
            for score in (*scores_before.values(), *scores_after.values())
        ):
            raise ValueError("Scores must be integers")
        score_delta = {
            seat: scores_after[seat] - scores_before[seat] for seat in range(4)
        }
        if sum(score_delta.values()) != 0:
            raise ValueError("Score changes must be zero-sum")

        return GameResult(
            round_number=round_number,
            round_wind=state.round_wind,
            dealer_seat=state.dealer,
            lianzhuang_count=state.lian_zhuang,
            winner_seats=winners,
            loser_seat=loser_seat,
            win_type=win_type,
            winner_fan_results=fan_results,
            score_delta=score_delta,
            scores_dict=scores_after,
        )

    @staticmethod
    def create_game_summary(results: Sequence[GameResult]) -> GameSummary:
        if not results:
            raise ValueError("At least one round result is required")
        winner_counts = {seat: 0 for seat in range(4)}
        draw_count = 0
        for result in results:
            if result.win_type == WinType.DRAW:
                draw_count += 1
            for seat in result.winner_seats:
                winner_counts[seat] += 1
        return GameSummary(
            rounds=tuple(results),
            winner_counts=winner_counts,
            draw_count=draw_count,
            final_scores=dict(results[-1].scores_dict),
        )


def print_round_summary(result: GameResult) -> None:
    """以繁體中文摘要輸出一局的胡牌、台數與分數變化。"""
    win_type_names = {
        WinType.SELF_DRAW: "自摸",
        WinType.DISCARD_WIN: "截胡／放銃",
        WinType.DRAW: "荒牌流局",
    }
    print("=" * 48)
    print(f"對局結果：{result.round_label}")
    print(
        f"莊家座位：{result.dealer_seat}  |  "
        f"連莊：{result.lianzhuang_count}"
    )
    print(f"結果類型：{win_type_names[result.win_type]}")
    if result.winner_seats:
        print(f"胡牌座位：{', '.join(map(str, result.winner_seats))}")
        if result.loser_seat is not None:
            print(f"放銃座位：{result.loser_seat}")
        for seat in result.winner_seats:
            fan_result = result.winner_fan_results[seat]
            detail_text = "、".join(
                f"{name} {fans} 台" for name, fans in fan_result.fan_details
            ) or "無台數明細"
            print(
                f"玩家 {seat}：{fan_result.total_fans} 台"
                f"（{detail_text}）"
            )

    print("分數變化 / 結算後總分：")
    for seat in range(4):
        delta = result.score_delta[seat]
        print(
            f"  座位 {seat}：{delta:+d} "
            f"→ {result.scores_dict[seat]}"
        )
    print("=" * 48)


def print_game_summary(summary: GameSummary) -> None:
    """輸出整場遊戲的局數、勝場、流局與最終積分。"""
    print("=" * 48)
    print(f"整場摘要：共 {len(summary.rounds)} 局，流局 {summary.draw_count} 局")
    print("胡牌局數：")
    for seat, wins in summary.winner_counts.items():
        print(f"  座位 {seat}：{wins} 勝")
    print("最終積分：")
    for seat, score in summary.final_scores.items():
        print(f"  座位 {seat}：{score}")
    print("=" * 48)
