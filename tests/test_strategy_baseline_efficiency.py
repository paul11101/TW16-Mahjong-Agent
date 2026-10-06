from src.common.schemas import ActionType
from src.strategy.baseline import BaselinePolicy
from src.strategy.interfaces import Observation, LegalAction

class FakeShantenCalculator:
    def calculate(self, hand: tuple[int, ...]) -> int:
        if hand == (0,):
            return 1

        if hand == (1,):
            return 2

        return 2


def make_observation() -> Observation:
    return Observation(
        hand = (0, 1,),
        discards = ((), (), (), (),),
        melds = ((), (), (), (),),
        flowers = ((), (), (), (),),
        current_player = 0,
        seat = 0,
        remaining_tiles = 80,
    )


def test_baseline_prefers_lower_shanten():
    observation = make_observation()
    legal_actions = [
        LegalAction(
            id = "discard_0",
            action = ActionType.DISCARD,
            tile = 0,
        ),
        LegalAction(
            id = "discard_1",
            action = ActionType.DISCARD,
            tile = 1,
        ),
    ]

    calculator = FakeShantenCalculator()
    policy = BaselinePolicy(calculator)
    decision = policy.decide(observation, legal_actions,)

    assert decision.action.id == "discard_1"
    assert "shanten = 1" in decision.reason


class FakeEffectiveDrawCalculator:
    def calculate(self, hand: tuple[int, ...]) -> int:
        if hand == (0,) or hand == (1,):
            return 1

        if len(hand) == 2 and hand[0] == 0:
            if hand[1] == 2:
                return 0
            return 1

        if len(hand) == 2 and hand[0] == 1:
            if hand[1] in (2, 3):
                return 0
            return 1

        return 1


def test_baseline_prefers_more_effective_draws():
    observation = make_observation()
    legal_actions = [
        LegalAction(
            id = "discard_0",
            action = ActionType.DISCARD,
            tile = 0,
        ),
        LegalAction(
            id = "discard_1",
            action = ActionType.DISCARD,
            tile = 1,
        )
    ]

    calculator = FakeEffectiveDrawCalculator()
    policy = BaselinePolicy(calculator)
    decision = policy.decide(observation, legal_actions,)

    assert decision.action.id == "discard_0"
    assert "effective_draws = 2" in decision.reason