from dataclasses import dataclass
from random import Random
from typing import Sequence

from src.rules.game_state import GameState, PlayerState, create_shuffled_wall
from src.rules.rule import RulesetConfig
from .action_policy import ActionPolicy
from .baseline import RandomPolicy
from .interfaces import Strategy

# 25 個固定種子搭配四個受測座位，共建立 100 局設定
DEFAULT_SEEDS = tuple(range(25))
DEFAULT_OPPONENTS = ("random", "random", "random")
POLICY_NAMES = frozenset({"random", "baseline_v1"})


# 單局評測設定；對手依下家、對家、上家的順序排列
@dataclass(frozen = True)
class EvaluationGame:
    wall_seed: int
    agent_seat: int
    opponents: tuple[str, ...] = DEFAULT_OPPONENTS
    dealer: int = 0

    # 檢查種子、座位與對手配置，避免建立無效的評測設定
    def __post_init__(self):
        if type(self.wall_seed) is not int or self.wall_seed < 0:
            raise ValueError("wall_seed must be a non-negative integer")

        for seat in (self.agent_seat, self.dealer):
            if type(seat) is not int or not 0 <= seat < 4:
                raise ValueError("seat must be an integer from 0 to 3")

        object.__setattr__(self, "opponents", tuple(self.opponents))
        if len(self.opponents) != 3 or any (p not in POLICY_NAMES for p in self.opponents):
            raise ValueError("opponents must contain three supported policy names")



# 同一牌山輪換四個受測座位，莊家固定為座位 0
def build_evaluation_games(
        wall_seeds: Sequence[int] = DEFAULT_SEEDS, *,
        opponents: Sequence[str] = DEFAULT_OPPONENTS,
) ->tuple[EvaluationGame, ...]:
    seeds, pool = tuple(wall_seeds), tuple(opponents)
    if not seeds:
        raise ValueError("wall_seeds cannot be empty")

    games = tuple(EvaluationGame(seed, seat, pool) for seed in seeds for seat in range(4))
    if len(set(seeds)) != len(seeds):
        raise ValueError("wall_seeds must be unique")

    return games


# 重用 Rules 的洗牌與發牌流程，每次建立新的牌局狀態
def make_game_state(game: EvaluationGame, config: RulesetConfig | None = None) -> GameState:
    state = GameState(
        game_id = f"eval_{game.wall_seed}_seat_{game.agent_seat}",
        dealer = game.dealer,
        players = {seat: PlayerState(seat_id = seat) for seat in range(4)},
        # 牌山使用獨立亂數源，不受策略決策或全域亂數影響
        wall = create_shuffled_wall(Random(game.wall_seed)),
    )

    state.deal(config or RulesetConfig())
    return state


# 依名稱建立既有策略，避免重複實作隨機與 Baseline 演算法
def make_policy(name: str, *, seed: int) -> Strategy:
    if name == "random":
        return RandomPolicy(seed = seed)

    if name == "baseline_v1":
        return ActionPolicy()

    raise ValueError(f"unknown policy: {name}")


# 將受測策略與三位對手配置到座位 0～3
def make_table_policies(game: EvaluationGame, candidate: str) -> tuple[Strategy, ...]:
    names = [candidate] * 4
    for offset, opponent in enumerate(game.opponents, start = 1):
        names[(game.agent_seat + offset) % 4] = opponent

    # 每個座位使用固定且獨立的策略種子，避免玩家之間互相消耗亂數
    return tuple(
        make_policy(name, seed = game.wall_seed * 4 + seat + 1)
        for seat, name in enumerate(names)
    )


# 直接執行時只顯示評測設定，不啟動整局對戰
if __name__ == "__main__":
    games = build_evaluation_games()
    print(f"固定牌山：{len(DEFAULT_SEEDS)} 個種子")
    print(f"評測設定：{len(games)} 局，每個座位 {len(games) // 4} 局")
    print(f"對手配置（下家、對家、上家）：{DEFAULT_OPPONENTS}")
    print("已建立設定，尚未執行整局對戰。")
