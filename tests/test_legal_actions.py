import pytest

@pytest.fixture
def rules_config():
    return RulesetConfig()

@pytest.fixture
def action_generator(rules_config):
    return LegalActionGenerator(config=rules_config)


def test_turn_player_discards(action_generator):
    """測試玩家回合打牌動作"""
    hand = [0, 1, 2]
    actions = action_generator.get_turn_player_actions(hand=hand)
    action_types = [a.action_type for a in actions]
    tile_ids = [a.tile_id for a in actions]

    assert all(a_type == ActionType.DISCARD for a_type in action_types)
    assert set(tile_ids) == {0, 1, 2}


def test_turn_player_self_draw_win(action_generator):
    """測試自摸胡牌選單"""
    hand = [0, 1, 2]
    last_drawn_tile = 2
    actions = action_generator.get_turn_player_actions(
        hand=hand, 
        last_drawn_tile=last_drawn_tile, 
        can_win_self_draw=True
    )
    win_actions = [a for a in actions if a.action_type == ActionType.WIN]
    assert len(win_actions) == 1
    assert win_actions[0].tile_id == last_drawn_tile


def test_response_pong_and_pass(action_generator):
    """測試碰牌與過」"""
    hand = [0, 0, 5, 6, 7]
    target_tile = 0
    actions = action_generator.get_response_actions(
        hand=hand, 
        target_tile=target_tile, 
        is_previous_player=False
    )
    action_types = [a.action_type for a in actions]
    assert ActionType.PONG in action_types
    assert ActionType.PASS in action_types
    assert ActionType.CHI not in action_types


def test_response_chi(action_generator):
    """測試正式吃牌邏輯"""
    hand = [0, 1, 10, 11]  # 有 1萬(0)、2萬(1)
    target_tile = 2        # 上家打 3萬(2)
    actions = action_generator.get_response_actions(
        hand=hand, 
        target_tile=target_tile, 
        is_previous_player=True
    )
    chi_actions = [a for a in actions if a.action_type == ActionType.CHI]
    assert len(chi_actions) == 1
    assert chi_actions[0].sequence == [0, 1, 2]