from itertools import groupby

import pytest

from src.common.schemas import ActionType
from src.rules.game_state import Meld
from src.rules.legal_actions import LegalActionGenerator
from src.rules.rule import RulesetConfig
from src.strategy.adapters import actions_to_legal_actions, game_state_to_observation
from src.strategy.dataset_builder import record_to_sample
from src.strategy.evaluation_plan import EvaluationGame, make_game_state
from src.strategy.generate_dataset import RecordingPolicy, generate_records


# 讓同一個教師從座位 0 做出決策，再比較實際送去訓練的樣本
def opening_sample(state):
    view = game_state_to_observation(state, 0)
    actions = LegalActionGenerator().get_turn_player_actions(
        hand=list(view.hand), last_drawn_tile=view.hand[-1],
        can_win_self_draw=state.is_basic_win(0),
    )
    recorder = RecordingPolicy(state.game_id, 7, RulesetConfig().ruleset_version)
    recorder.decide(view, actions_to_legal_actions(actions))
    return record_to_sample(recorder.records[0])


# 對手暗牌、暗槓牌面及牌牆順序改變時，玩家的訓練樣本應保持相同
def test_private_tiles_do_not_change_sample():
    state = make_game_state(EvaluationGame(7, 0))
    state.players[1].melds.append(Meld(
        meld_type=ActionType.KONG, tiles=[27] * 4, from_player=1, kong_type="an",
    ))
    changed = state.model_copy(deep=True)
    changed.players[1].hand, changed.players[2].hand = (
        changed.players[2].hand, changed.players[1].hand,
    )
    changed.wall.reverse()
    changed.players[1].melds[0].tiles = [28] * 4

    assert opening_sample(state) == opening_sample(changed)
    assert game_state_to_observation(state, 1).melds[1] == ((27,) * 4,)
    # 改成明槓後，其他座位也應看得見這組牌
    state.players[1].melds[0].kong_type = "ming"
    assert game_state_to_observation(state, 0).melds[1] == ((27,) * 4,)


# 固定種子可重現，跨局後決策編號重新起算
def test_generation_is_reproducible_across_rounds():
    records = list(generate_records(350, start_seed=7))
    assert len(records) == 350
    assert len({r.game_id for r in records}) > 1
    assert records == list(generate_records(350, start_seed=7))
    for _, group in groupby(records, key=lambda r: r.game_id):
        assert all(r.decision_id == str(i) for i, r in enumerate(group))


# 產生筆數必須大於零，起始牌山種子可從零開始
@pytest.mark.parametrize("limit, seed", [(0, 0), (1, -1)])
def test_invalid_settings(limit, seed):
    with pytest.raises(ValueError):
        list(generate_records(limit, seed))