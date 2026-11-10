import random
from collections import Counter
from dataclasses import replace

import pytest

from src.common.schemas import ActionType
from src.strategy.action_policy import ActionPolicy
from src.strategy.baseline import RandomPolicy
from src.strategy.evaluation_plan import (
    EvaluationGame, build_evaluation_games, make_game_state, make_table_policies,
)
from src.strategy.interfaces import LegalAction, Observation

OBS = Observation((0, 1, 2), ((),) * 4, ((),) * 4, ((),) * 4, 0, 0, 80)
ACTIONS = tuple(LegalAction(f"discard_{tile}", ActionType.DISCARD, tile) for tile in OBS.hand)


# 100 局設定由 25 個牌山及四個座位構成，重建結果固定
def test_plan_is_balanced_and_repeatable():
    games = build_evaluation_games()
    assert games == build_evaluation_games()
    assert len(games) == 100
    assert Counter(game.agent_seat for game in games) == {0: 25, 1: 25, 2: 25, 3: 25}
    assert Counter(game.wall_seed for game in games) == dict.fromkeys(range(25), 4)
    assert all(game.dealer == 0 for game in games)


# 輪換受測座位不改變發牌；修改其中一局不會污染重建結果
def test_same_seed_recreates_initial_state():
    games = build_evaluation_games([7])
    original = make_game_state(games[0])
    expected = original.model_dump(exclude={"game_id"})
    for game in games:
        state = make_game_state(game)
        assert state.model_dump(exclude={"game_id"}) == expected
        assert state.current_turn == state.dealer == 0
        assert [len(state.players[i].hand) for i in range(4)] == [17, 16, 16, 16]
    original.players[0].hand.clear()
    assert make_game_state(games[0]).model_dump(exclude={"game_id"}) == expected
    assert make_game_state(replace(games[0], wall_seed=8)).wall != expected["wall"]


# 比較兩個候選策略時，對手名單、亂數序列與全域亂數都保持隔離
def test_candidate_does_not_change_opponent_random_streams():
    before = random.getstate()
    for game in build_evaluation_games([9]):
        random_team = make_table_policies(game, "random")
        baseline_team = make_table_policies(game, "baseline_v1")
        assert isinstance(baseline_team[game.agent_seat], ActionPolicy)
        for _ in range(50):
            random_team[game.agent_seat].decide(OBS, ACTIONS)
        for seat in range(4):
            if seat != game.agent_seat:
                left = [random_team[seat].decide(OBS, ACTIONS) for _ in range(20)]
                right = [baseline_team[seat].decide(OBS, ACTIONS) for _ in range(20)]
                assert left == right
                assert all(item.action in ACTIONS for item in left)
        make_game_state(game)
    assert random.getstate() == before


# 混合對手按相對位置排列，每局重新建立策略實例
def test_custom_opponents_and_fresh_policy_instances():
    game = EvaluationGame(3, 2, ("baseline_v1", "random", "baseline_v1"))
    first, second = make_table_policies(game, "random"), make_table_policies(game, "random")
    assert tuple(type(p) for p in first) == (RandomPolicy, ActionPolicy, RandomPolicy, ActionPolicy)
    assert all(a is not b for a, b in zip(first, second))
    for seat in (0, 2):
        assert [first[seat].decide(OBS, ACTIONS) for _ in range(20)] == [
            second[seat].decide(OBS, ACTIONS) for _ in range(20)
        ]


# 拒絕空集合、重複種子與無效的種子型別或數值
@pytest.mark.parametrize("seeds", [[], [1, 1], [-1], [True], [1.5]])
def test_invalid_seed_sets_are_rejected(seeds):
    with pytest.raises(ValueError):
        build_evaluation_games(seeds)


# 拒絕超出範圍的座位、錯誤的對手數量與未知策略
@pytest.mark.parametrize("changes", [
    {"agent_seat": 4}, {"dealer": -1}, {"opponents": ("random",)},
    {"opponents": ("random", "missing", "random")},
])
def test_invalid_game_settings_are_rejected(changes):
    with pytest.raises(ValueError):
        replace(EvaluationGame(0, 0), **changes)


# 受測策略名稱也必須在支援清單內
def test_unknown_candidate_is_rejected():
    with pytest.raises(ValueError):
        make_table_policies(EvaluationGame(0, 0), "missing")
