from src.common.schemas import ActionType
from src.strategy.action_mask import (ACTION_SPACE_SIZE, build_action_mask,)
from src.strategy.interfaces import LegalAction

# 測試多個合法動作是否能正確轉換成 Action Mask
def test_build_action_mask():
    # 建立三個目前允許的合法動作：
    # 打出牌 ID 3、碰牌 ID 27、以及 PASS
    legal_actions = [
        LegalAction(
            id = "discard_3",
            action = ActionType.DISCARD,
            tile = 3,
        ),
        LegalAction(
            id = "pong_27",
            action = ActionType.PONG,
            tile = 27,
            tiles = (27, 27, 27),
        ),
        LegalAction(
            id = "pass",
            action = ActionType.PASS,
        ),
    ]

    # 將 LegalActions 轉換成固定長度的 Action Mask
    mask = build_action_mask(legal_actions)

    # 確認 Action Mask 的總長度等於固定 Action Space 大小
    assert len(mask) == ACTION_SPACE_SIZE

    # DISCARD 3 對應索引 3，所以該位置必須為 1
    assert mask[3] == 1

    # PONG 27 對應 PONG_OFFSET 55 + 27 = 82
    assert mask[82] == 1

    # PASS 固定對應索引 124
    assert mask[124] == 1

    # 確認總共只有三個合法動作被標記為 1
    assert sum(mask) == 3


# 測試 CHI 動作是否能正確映射到 Action Mask
def test_chi_action_mask():
    # 建立吃 0、1、2 的合法動作
    legal_actions = [
        LegalAction(
            id = "chi_0_1_2",
            action = ActionType.CHI,
            tile = 2,
            tiles = (0, 1, 2),
        )
    ]

    # 將 CHI 動作轉換成 Action Mask
    mask = build_action_mask(legal_actions)

    # chi_0_1_2 是第一種 CHI，因此對應索引 34
    assert mask[34] == 1

    # 確認只有這一個合法動作被標記為 1
    assert sum(mask) == 1