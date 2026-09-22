import os
import sys
import pytest

# 動態將專案根目錄納入 Python 模組搜尋路徑，確保能正確 import 到 src 套件
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 從正式的核心規則模組匯入
from src.rules.legal_actions import (
    ActionType,
    Action,
    RulesetConfig,
    LegalActionGenerator,
)


@pytest.fixture
def rules_config():
    return RulesetConfig()


@pytest.fixture
def action_generator(rules_config):
    return LegalActionGenerator(config=rules_config)


def test_turn_player_discards(action_generator):
    """測試玩家摸牌/回合內的棄牌動作生成"""
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
    """測試非玩家回合對他人棄牌的【碰牌】與【過水/Pass】選單"""
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
    """測試對上家棄牌的【吃牌】選單邏輯"""
    hand = [0, 1, 10, 11]  # 手牌有 1萬(0)、2萬(1)
    target_tile = 2        # 上家打 3萬(2)
    actions = action_generator.get_response_actions(
        hand=hand, 
        target_tile=target_tile, 
        is_previous_player=True
    )
    chi_actions = [a for a in actions if a.action_type == ActionType.CHI]
    assert len(chi_actions) == 1
    assert chi_actions[0].sequence == [0, 1, 2]