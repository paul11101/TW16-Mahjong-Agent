from collections import Counter
from random import Random

import pytest

from src.common.schemas import ActionType as A
from src.rules.game_state import GameState, PlayerState
from src.rules.game_result import WinType
from src.rules.rule import RuleMechanics, RulesetConfig
from src.strategy import run_evaluation
from src.strategy.action_policy import ActionPolicy
from src.strategy.evaluation_game import play_round
from src.strategy.evaluation_plan import (
    EvaluationGame, build_evaluation_games, make_game_state, make_table_policies,
)
from src.strategy.interfaces import Decision, LegalAction

WIN_HAND = [0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 24, 25, 26, 31, 31]


# 固定指定手牌與接下來的摸牌，其餘牌仍保持完整 144 張
def fixed_state(hands, draws=()):
    pool = [tile for tile in range(34) for _ in range(4)]
    for tile in [t for hand in hands.values() for t in hand] + list(draws):
        pool.remove(tile)
    Random(10).shuffle(pool)
    players = {}
    for seat in range(4):
        hand = list(hands.get(seat, []))
        while len(hand) < 16 + (seat == 0):
            hand.append(pool.pop())
        players[seat] = PlayerState(seat_id=seat, hand=hand)
    wall = pool + list(range(34, 42)) + list(reversed(draws))
    return GameState(game_id="round-test", dealer=0, players=players, wall=wall, wall_count=len(wall))


# 強制選擇指定動作，觀察模擬器有沒有正確推進回合
class Policy:
    def __init__(self, preferred=(), discard=None):
        self.preferred, self.discard, self.calls = preferred, discard, []

    def decide(self, obs, actions):
        self.calls.append((obs, actions))
        for kind in self.preferred:
            for action in actions:
                if action.action == kind and (kind == A.WIN or action.tile == 27):
                    return Decision(action, 0.0, "test")
        discards = [a for a in actions if a.action == A.DISCARD]
        if discards:
            chosen = next((a for a in discards if a.tile == self.discard), discards[0])
            self.discard = None
        else:
            chosen = next(a for a in actions if a.action == A.PASS)
        return Decision(chosen, 0.0, "test")


def assert_conserved(state):
    tiles = list(state.wall)
    for player in state.players.values():
        tiles += player.hand + player.discards + player.flowers
        tiles += [tile for meld in player.melds for tile in meld.tiles]
    assert Counter(tiles) == Counter([t for t in range(34) for _ in range(4)] + list(range(34, 42)))


# 莊家起手胡與非莊家摸牌胡，結算資料都保留本局原莊家
@pytest.mark.parametrize("winner", [0, 1])
def test_self_draw_and_score_snapshot(winner):
    hands = {0: WIN_HAND} if winner == 0 else {0: [27], 1: WIN_HAND[:-1]}
    state = fixed_state(hands, () if winner == 0 else (31,))
    policies = [Policy(discard=27) for _ in range(4)]
    policies[winner] = Policy((A.WIN,))
    result = play_round(state, policies)
    assert result.win_type == WinType.SELF_DRAW
    assert result.winner_seats == (winner,)
    assert result.dealer_seat == 0
    assert result.loser_seat is None
    assert result.score_delta[winner] > 0
    assert sum(result.score_delta.values()) == 0
    assert state.is_over
    assert_conserved(state)


# 多人可胡時依目前 Rules 的截胡規則，只保留最近的一家
def test_discard_win_uses_rules_priority():
    state = fixed_state({0: [31], 1: WIN_HAND[:-1], 2: WIN_HAND[:-1]})
    result = play_round(state, [Policy(discard=31), Policy((A.WIN,)), Policy((A.WIN,)), Policy()])
    assert result.win_type == WinType.DISCARD_WIN
    assert result.winner_seats == (1,)
    assert result.loser_seat == 0
    assert result.score_delta[0] == -result.score_delta[1] < 0
    assert_conserved(state)


# 有胡卻選碰要記過水；碰後直接出牌，不能多摸或誤判自摸
def test_pong_declining_win_does_not_draw_again():
    ready = [0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 27, 31, 31]
    state = fixed_state({0: [27], 1: ready})
    policies = [Policy(discard=27), Policy((A.PONG,)), Policy(), Policy()]
    wall_size = len(state.wall)
    with pytest.raises(RuntimeError, match="exceeded"):
        play_round(state, policies, max_steps=2)
    obs, actions = next((o, a) for o, a in policies[1].calls if o.melds[1])
    assert len(obs.hand) == 14
    assert all(a.action != A.WIN for a in actions)
    assert len(state.wall) == wall_size
    assert state.players[1].passed_win
    assert_conserved(state)


# 同一手牌分別走自己回合與反應流程，確認兩邊都沿用當局海底規則
@pytest.mark.parametrize("kind", ["an", "ming"])
@pytest.mark.parametrize("wall_count, reserve, expect_kong", [
    (18, 18, False), (15, 14, True), (17, 16, True),
])
def test_kong_uses_round_wall_reserve(kind, wall_count, reserve, expect_kong):
    hand = [0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 27, 27, 33, 33, 33]
    seat = 0 if kind == "an" else 1
    hands = {0: hand + [33]} if kind == "an" else {0: [33], 1: hand}
    state = fixed_state(hands, draws=(22,))
    state.wall = state.wall[-wall_count:]
    state.wall_count = len(state.wall)
    config = RulesetConfig(rule_mechanics=RuleMechanics(reserved_wall_tiles=reserve))

    policies = [Policy(discard=33) for _ in range(4)]
    policies[seat] = ActionPolicy(include_candidate_scores=False)
    play_round(state, policies, config)

    kongs = [m.kong_type for m in state.players[seat].melds if m.meld_type == A.KONG]
    assert kongs == ([kind] if expect_kong else [])


# 暗槓與明槓由 Rules 補一次牌，模擬器不能再補第二次
@pytest.mark.parametrize("kind", ["an", "ming"])
def test_kong_draws_exactly_once(kind):
    hands = {0: [27] * 4} if kind == "an" else {0: [27], 1: [27] * 3}
    state = fixed_state(hands, (32,))
    seat = 0 if kind == "an" else 1
    policies = [Policy(discard=27) for _ in range(4)]
    policies[seat] = Policy((A.KONG,))
    wall_size = len(state.wall)
    with pytest.raises(RuntimeError, match="exceeded"):
        play_round(state, policies, max_steps=2)
    assert state.players[seat].melds[0].kong_type == kind
    obs, _ = next((o, a) for o, a in policies[seat].calls if o.melds[seat])
    assert len(obs.hand) == 14
    assert len(state.wall) == wall_size - 1
    assert_conserved(state)


# 先碰，再摸到第四張加槓；補牌後仍由原玩家出牌
def test_added_kong_reuses_pong_and_replacement_draw():
    state = fixed_state({0: [27], 1: [27, 27]}, (32, 32, 33, 27, 33))
    policies = [Policy(discard=27), Policy((A.KONG, A.PONG)), Policy(), Policy()]
    wall_size = len(state.wall)
    with pytest.raises(RuntimeError, match="exceeded"):
        play_round(state, policies, max_steps=7)
    assert state.players[1].melds[0].kong_type == "jia"
    assert len(state.players[1].melds) == 1
    assert len(state.wall) == wall_size - 5
    assert_conserved(state)


# 固定種子可重現完整結果，流局也保存正確的連莊快照
def test_seeded_round_is_repeatable():
    game = EvaluationGame(0, 0)
    results = []
    for _ in range(2):
        state = make_game_state(game)
        results.append(play_round(state, make_table_policies(game, "random")))
        assert_conserved(state)
    assert results[0] == results[1]
    assert results[0].win_type == WinType.DRAW
    assert results[0].lianzhuang_count == 0


# 非法策略輸出不能被默默替換成其他動作
def test_illegal_decision_is_rejected():
    class BadPolicy:
        def decide(self, obs, actions):
            return Decision(LegalAction("bad", A.DISCARD, 99), 0.0, "bad")
    state = make_game_state(EvaluationGame(0, 0))
    with pytest.raises(ValueError, match="illegal"):
        play_round(state, [BadPolicy()] * 4)


# 發生例外的設定要保留錯誤，不能加入完成局數或流局
def test_batch_records_failures_separately(monkeypatch):
    original = run_evaluation.play_round

    def fail_one(state, policies, config, **kwargs):
        if state.game_id.endswith("seat_0"):
            raise RuntimeError("injected failure")
        return original(state, policies, config, **kwargs)

    monkeypatch.setattr(run_evaluation, "play_round", fail_one)
    report = run_evaluation.evaluate_policy("random", build_evaluation_games([0]))
    assert report["planned"] == 4
    assert report["completed"] == report["summary"]["games"] == 3
    assert report["failed"] == 1
    assert not report["complete"]
    assert report["errors"][0]["game"]["agent_seat"] == 0
    assert "injected failure" in report["errors"][0]["error"]


# 結果轉成 JSON 資料時失敗，也不能同時計為成功與失敗
def test_serialization_failure_is_not_counted_as_completed(monkeypatch):
    from src.rules.game_result import GameResult

    def fail_serialization(self):
        raise RuntimeError("serialization failed")

    monkeypatch.setattr(GameResult, "to_dict", fail_serialization)
    report = run_evaluation.evaluate_policy("random", build_evaluation_games([0]))
    assert report["completed"] == 0
    assert report["failed"] == report["planned"] == 4
    assert report["summary"] is None
    assert report["rounds"] == []