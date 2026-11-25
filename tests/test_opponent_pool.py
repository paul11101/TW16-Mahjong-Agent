import pytest

from src.rules.opponent_pool import OpponentPool


def test_opponent_pool_draws_four_seats_reproducibly():
    pool = OpponentPool({"aggressive": 0, "balanced": 1})

    assert pool.sample_styles(42) == ("balanced",) * 4
    assert pool.sample_styles(42) == pool.sample_styles(42)
    styles, policies = pool.create_policies(42)
    assert styles == ("balanced",) * 4
    assert len(policies) == 4
    assert all(
        policy.strategy_version == "baseline_style_wrapper_v1"
        for policy in policies
    )


@pytest.mark.parametrize("weights", [
    {},
    {"unknown": 1},
    {"aggressive": -1},
    {"balanced": float("inf")},
    {"balanced": 0},
])
def test_opponent_pool_rejects_invalid_weights(weights):
    with pytest.raises(ValueError):
        OpponentPool(weights)
