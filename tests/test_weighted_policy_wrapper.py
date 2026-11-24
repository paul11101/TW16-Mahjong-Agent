import pytest

from src.common.schemas import ActionType
from src.strategy.baseline import BaselinePolicy
from src.strategy.interfaces import LegalAction, Observation
from src.weighted_policy import (
    BALANCED,
    BOT_STYLE_PRESETS,
    MENZEN_DEFENSIVE,
    BotStyleConfig,
    WeightedPolicyWrapper,
    get_bot_style,
)


def make_observation(*, discards=((), (), (), ())) -> Observation:
    return Observation(
        hand=(0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 27, 31, 31, 32),
        discards=discards,
        melds=((), (), (), ()),
        flowers=((), (), (), ()),
        current_player=0,
        seat=0,
        remaining_tiles=80,
    )


def test_style_presets_and_configuration_validation():
    assert set(BOT_STYLE_PRESETS) == {"aggressive", "menzen_defensive", "balanced"}
    assert get_bot_style("balanced") == BALANCED
    assert MENZEN_DEFENSIVE.chi_bias < 0
    with pytest.raises(ValueError, match="unknown bot style"):
        get_bot_style("unknown")
    with pytest.raises(ValueError, match="finite"):
        BotStyleConfig(kong_bias=float("inf"))


def test_aggressive_and_defensive_meld_choices_are_always_legal():
    observation = make_observation()
    chi = LegalAction(id="chi_2_3_4", action=ActionType.CHI, tile=3, tiles=(2, 3, 4))
    pong = LegalAction(id="pong_27", action=ActionType.PONG, tile=27, tiles=(27, 27, 27))
    passed = LegalAction(id="pass", action=ActionType.PASS)
    legal = [chi, pong, passed]

    aggressive = WeightedPolicyWrapper(BotStyleConfig(
        baseline_weight=0,
        chi_bias=10,
        pong_bias=10,
    ))
    defensive = WeightedPolicyWrapper("menzen_defensive")

    assert aggressive.decide(observation, legal).action in legal
    assert aggressive.decide(observation, legal).action.action in {
        ActionType.CHI,
        ActionType.PONG,
    }
    assert defensive.decide(observation, legal).action == passed


def test_defensive_style_prefers_publicly_safe_discard_and_keeps_baseline_untouched():
    observation = make_observation(discards=((), (0,), (0,), (0,)))
    first = LegalAction(id="discard_1", action=ActionType.DISCARD, tile=1)
    safe = LegalAction(id="discard_0", action=ActionType.DISCARD, tile=0)
    legal = [first, safe]
    original = BaselinePolicy().decide(observation, legal)

    decision = WeightedPolicyWrapper(BotStyleConfig(
        baseline_weight=0,
        safe_tile_weight=2,
    )).decide(observation, legal)

    assert original.action == first
    assert decision.action == safe
    assert decision.action in legal


def test_every_style_returns_only_an_action_from_current_legal_list():
    observation = make_observation()
    legal = [
        LegalAction(id="discard_31", action=ActionType.DISCARD, tile=31),
        LegalAction(id="discard_32", action=ActionType.DISCARD, tile=32),
    ]

    for style in BOT_STYLE_PRESETS:
        assert WeightedPolicyWrapper(style).decide(observation, legal).action in legal


def test_rejects_empty_legal_actions():
    with pytest.raises(ValueError, match="cannot be empty"):
        WeightedPolicyWrapper().decide(make_observation(), [])
