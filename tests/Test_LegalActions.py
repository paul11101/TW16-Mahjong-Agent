import pytest
from legal_actions import (
    ActionType, 
    Action, 
    RulesetConfig, 
    LegalActionGenerator
)

# ==============================================================================
# Pytest Fixtures (測試用基礎物件)
# ==============================================================================

@pytest.fixture
def rules_config():
    """提供標準的台灣十六張麻將規則設定"""
    return RulesetConfig()

@pytest.fixture
def action_generator(rules_config):
    """初始化 LegalActionGenerator 實例"""
    return LegalActionGenerator(config=rules_config)


# ==============================================================================
# 測試案例 1: 輪到自己回合 (Turn Actions)
# ==============================================================================

def test_turn_player_discards(action_generator):
    """測試：玩家回合時，應正確回傳可打出的牌張清單"""
    # 假設手牌有 1萬(ID:0), 2萬(ID:1), 3萬(ID:2)
    hand = [0, 1, 2]
    
    actions = action_generator.get_turn_player_actions(hand=hand)
    action_types = [a.action_type for a in actions]
    tile_ids = [a.tile_id for a in actions]

    # 驗證：動作類型全部都應該是 DISCARD
    assert all(a_type == ActionType.DISCARD for a_type in action_types)
    # 驗證：可打出的牌張 ID 應包含手牌中的所有不重複牌張
    assert set(tile_ids) == {0, 1, 2}


def test_turn_player_self_draw_win(action_generator):
    """測試：當滿足自摸條件時，應包含 WIN (胡牌) 動作"""
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


# ==============================================================================
# 測試案例 2: 他人打牌後的反應 (Response Actions)
# ==============================================================================

def test_response_pong_and_pass(action_generator):
    """測試：當手牌有 2 張相同且別人打出第 3 張時，應產生 PONG 與 PASS 動作"""
    # 手牌有兩張 1萬(ID:0)
    hand = [0, 0, 5, 6, 7]
    target_tile = 0 # 別人打出 1萬
    
    actions = action_generator.get_response_actions(
        hand=hand, 
        target_tile=target_tile, 
        is_previous_player=False
    )
    
    action_types = [a.action_type for a in actions]
    
    # 驗證：應包含 PONG 與 PASS
    assert ActionType.PONG in action_types
    assert ActionType.PASS in action_types
    # 不應該包含 CHI (因為不是上家打的)
    assert ActionType.CHI not in action_types


def test_response_ming_kong(action_generator):
    """測試：當手牌有 3 張相同且別人打出第 4 張時，應產生明槓 (KONG) 動作"""
    # 手牌有三張 東風(ID:27)
    hand = [27, 27, 27, 10, 11]
    target_tile = 27 # 別人打出 東風
    
    actions = action_generator.get_response_actions(
        hand=hand, 
        target_tile=target_tile, 
        is_previous_player=False
    )
    
    kong_actions = [a for a in actions if a.action_type == ActionType.KONG]
    assert len(kong_actions) == 1
    assert kong_actions[0].kong_type == "ming"
    assert kong_actions[0].tile_id == 27


def test_response_no_action_available(action_generator):
    """測試：當無法吃碰槓胡時，應該傳回空列表 (無需填過)"""
    hand = [0, 1, 2, 3, 4]
    target_tile = 20 # 別人打出一條(ID:20)，無法做出任何反應
    
    actions = action_generator.get_response_actions(
        hand=hand, 
        target_tile=target_tile, 
        is_previous_player=False
    )
    
    assert len(actions) == 0