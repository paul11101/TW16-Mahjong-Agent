from dataclasses import replace

import pytest

from src.common.schemas import ActionType, CandidateScore
from src.strategy import candidate_scoring as scoring
from src.strategy.action_policy import ActionPolicy
from src.strategy.interfaces import LegalAction, Observation
from src.strategy.kong_policy import simulate_kong
from src.strategy.meld_policy import (
    MeldShantenCalculator,
    evaluate_meld,
    evaluate_meld_details,
)
from src.strategy.public_features import extract_public_features
from src.strategy.tile_efficiency import evaluate_discard


HAND = (
    0, 1, 2, 3, 4, 5, 6, 7, 8,
    9, 10, 11, 18, 19, 20, 27, 33,
)

CHI_HAND = (
    0, 1, 2, 9, 10, 11, 18, 19,
    20, 27, 27, 3, 4, 6, 7, 33,
)

PONG_HAND = (
    0, 1, 2, 9, 10, 11, 18, 19,
    20, 27, 27, 33, 33, 6, 7, 24,
)

MING_HAND = (
    0, 1, 2, 3, 4, 5, 9, 10,
    11, 18, 19, 27, 27, 33, 33, 33,
)

AN_HAND = (
    0, 1, 2, 3, 4, 5, 9, 10, 11,
    18, 19, 20, 27, 33, 33, 33, 33,
)

JIA_HAND = (
    0, 1, 2, 3, 4, 5, 9,
    10, 11, 18, 19, 20, 27, 33,
)


# 建立只有玩家可見資訊的測試觀測
def make_observation(
    hand=HAND,
    own_melds=(),
    remaining_tiles=80,
):
    return Observation(
        hand=hand,
        discards=((), (), (), ()),
        melds=(own_melds, (), (), ()),
        flowers=((), (), (), ()),
        current_player=0,
        seat=0,
        remaining_tiles=remaining_tiles,
    )


# 所有棄牌候選都必須有結果，包括向聽較差的候選
def test_all_discard_candidates_are_scored():
    observation = make_observation()

    actions = [
        LegalAction(
            id=f"discard_{tile}",
            action=ActionType.DISCARD,
            tile=tile,
        )
        for tile in (0, 33)
    ]

    results = ActionPolicy().score_candidates(
        observation,
        actions,
    )

    unseen = extract_public_features(
        observation
    ).unseen_upper_bounds

    calculator = MeldShantenCalculator(0)

    assert [item.action_id for item in results] == [
        action.id for action in actions
    ]
    assert results[0].shanten > results[1].shanten

    for action, result in zip(actions, results):
        shanten, draws = evaluate_discard(
            observation.hand,
            action.tile,
            calculator,
        )

        available = [
            tile for tile in draws
            if unseen[tile] > 0
        ]

        assert result.scorable
        assert result.score == float(-shanten)
        assert result.effective_draws == len(available)
        assert result.unseen_upper_bound == sum(
            unseen[tile] for tile in available
        )
        assert result.next_discard == action.tile
        assert isinstance(
            result.to_candidate_score(),
            CandidateScore,
        )


# 吃碰保留原介面，評分直接重用進張明細
@pytest.mark.parametrize(
    "kind, hand, tile, tiles",
    [
        (ActionType.CHI, CHI_HAND, 5, (3, 4, 5)),
        (ActionType.PONG, PONG_HAND, 33, (33, 33, 33)),
    ],
)
def test_meld_details_keep_existing_results(
    kind,
    hand,
    tile,
    tiles,
):
    observation = replace(
        make_observation(hand),
        discards=((), (), (), (tile,)),
    )

    action = LegalAction(
        id="meld",
        action=kind,
        tile=tile,
        tiles=tiles,
    )

    shanten, draws, discard = evaluate_meld_details(
        hand,
        action,
        0,
    )

    assert evaluate_meld(hand, action, 0) == (
        shanten,
        len(draws),
        discard,
    )

    result = scoring.score_candidates(
        observation,
        [action],
    )[0]

    unseen = extract_public_features(
        observation
    ).unseen_upper_bounds

    assert result.shanten == shanten
    assert result.next_discard == discard
    assert result.effective_draws == sum(
        unseen[tile] > 0 for tile in draws
    )


# 三種槓都只評估補牌前的已知牌形
@pytest.mark.parametrize(
    "kind, hand, melds",
    [
        ("ming", MING_HAND, ()),
        ("an", AN_HAND, ()),
        ("jia", JIA_HAND, ((33, 33, 33),)),
    ],
)
def test_kong_does_not_guess_replacement_draw(
    kind,
    hand,
    melds,
):
    observation = make_observation(
        hand,
        melds,
        remaining_tiles=None,
    )

    if kind == "ming":
        observation = replace(
            observation,
            discards=((), (), (), (33,)),
        )

    action = LegalAction(
        id="kong",
        action=ActionType.KONG,
        tile=33,
        kong_type=kind,
    )

    result = scoring.score_candidates(
        observation,
        [action],
    )[0]

    remaining, increase = simulate_kong(
        hand,
        action,
        melds,
    )

    expected = MeldShantenCalculator(
        len(melds) + increase
    ).calculate(remaining)

    assert result.scorable
    assert result.shanten == expected
    assert result.score == float(-expected)
    assert result.next_discard is None
    assert "replacement_draw = pending" in result.reason


# 胡牌與 PASS 使用相同結果格式
def test_win_and_pass():
    observation = make_observation(CHI_HAND)

    actions = [
        LegalAction(id="win", action=ActionType.WIN),
        LegalAction(id="pass", action=ActionType.PASS),
    ]

    win, passed = scoring.score_candidates(
        observation,
        actions,
    )

    assert win.score == 1.0
    assert win.shanten is None
    assert win.effective_draws is None
    assert win.next_discard is None

    assert passed.shanten == MeldShantenCalculator(
        0
    ).calculate(CHI_HAND)

    assert passed.next_discard is None
    assert win.scorable and passed.scorable


# 個別候選出錯時，不影響其他候選，也不填入假的零分
@pytest.mark.parametrize(
    "bad",
    [
        LegalAction(
            id="bad",
            action=ActionType.DISCARD,
            tile=42,
        ),
        LegalAction(
            id="bad",
            action=ActionType.DISCARD,
            tile=32,
        ),
        LegalAction(
            id="bad",
            action=ActionType.KONG,
            tile=33,
        ),
        LegalAction(
            id="bad",
            action=ActionType.DRAW_TILE,
            tile=1,
        ),
    ],
)
def test_unscorable_candidates_are_preserved(bad):
    good = LegalAction(
        id="good",
        action=ActionType.DISCARD,
        tile=33,
    )

    invalid, valid = scoring.score_candidates(
        make_observation(),
        [bad, good],
    )

    assert not invalid.scorable
    assert invalid.score is None
    assert invalid.shanten is None
    assert invalid.effective_draws is None
    assert invalid.unseen_upper_bound is None
    assert invalid.to_candidate_score() is None
    assert invalid.reason
    assert valid.scorable


# 評分不改變決策、不修改輸入，相同輸入結果一致
def test_scoring_keeps_decision_and_inputs():
    observation = make_observation()

    actions = [
        LegalAction(
            id=f"d_{tile}",
            action=ActionType.DISCARD,
            tile=tile,
        )
        for tile in (0, 27, 33)
    ]

    original = tuple(actions)
    policy = ActionPolicy()

    before = policy.decide(observation, actions)
    first = policy.score_candidates(observation, actions)

    assert policy.decide(observation, actions) == before
    assert policy.score_candidates(
        observation,
        actions,
    ) == first

    assert tuple(actions) == original
    assert observation == make_observation()


# 同內容候選只評估一次，快取不能跨次呼叫沿用
def test_cache_and_public_features_are_local(monkeypatch):
    calls = {"score": 0, "public": 0}

    original_score = scoring._score_action
    original_public = scoring.extract_public_features

    def counted_score(*args):
        calls["score"] += 1
        return original_score(*args)

    def counted_public(*args):
        calls["public"] += 1
        return original_public(*args)

    monkeypatch.setattr(
        scoring,
        "_score_action",
        counted_score,
    )
    monkeypatch.setattr(
        scoring,
        "extract_public_features",
        counted_public,
    )

    first = LegalAction(
        id="first",
        action=ActionType.DISCARD,
        tile=33,
    )
    second = replace(first, id="second")

    results = scoring.score_candidates(
        make_observation(),
        [first, second],
    )

    assert [item.action_id for item in results] == [
        "first",
        "second",
    ]
    assert calls == {"score": 1, "public": 1}

    scoring.score_candidates(
        make_observation(),
        [first, second],
    )

    assert calls == {"score": 2, "public": 2}


# 槓牌種類不同時，不得共用同一份快取結果
def test_cache_distinguishes_kong_types():
    an = LegalAction(
        id="an",
        action=ActionType.KONG,
        tile=33,
        kong_type="an",
    )
    jia = replace(
        an,
        id="jia",
        kong_type="jia",
    )

    valid, invalid = scoring.score_candidates(
        make_observation(AN_HAND),
        [an, jia],
    )

    assert valid.scorable
    assert not invalid.scorable


# 已經全部公開的進張應記為零，而不是未知
def test_exhausted_draws_and_fresh_public_information(
    monkeypatch,
):
    monkeypatch.setattr(
        scoring,
        "evaluate_discard",
        lambda *args: (1, (2,)),
    )

    observation = make_observation((0, 1))

    action = LegalAction(
        id="discard",
        action=ActionType.DISCARD,
        tile=0,
    )

    available = scoring.score_candidates(
        observation,
        [action],
    )[0]

    exhausted = scoring.score_candidates(
        replace(
            observation,
            discards=((2, 2, 2, 2), (), (), ()),
        ),
        [action],
    )[0]

    assert available.unseen_upper_bound == 4
    assert exhausted.scorable
    assert exhausted.effective_draws == 0
    assert exhausted.unseen_upper_bound == 0


# 錯誤觀測與重複 ID 直接回報，不掩蓋整批資料問題
def test_invalid_batch_is_rejected():
    observation = make_observation()

    action = LegalAction(
        id="discard",
        action=ActionType.DISCARD,
        tile=33,
    )

    with pytest.raises(ValueError, match="empty"):
        scoring.score_candidates(observation, [])

    with pytest.raises(ValueError, match="unique"):
        scoring.score_candidates(
            observation,
            [action, action],
        )

    with pytest.raises(ValueError, match="four players"):
        scoring.score_candidates(
            replace(observation, melds=()),
            [action],
        )

    with pytest.raises(TypeError, match="Observation"):
        scoring.score_candidates(object(), [action])