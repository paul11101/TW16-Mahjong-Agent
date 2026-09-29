from src.common.schemas import ActionType
from .interfaces import LegalAction, LegalActions

# 固定 Action Space 的總大小
ACTION_SPACE_SIZE = 125

# 各種動作在 Action Space 中的起始位置
DISCARD_OFFSET = 0
CHI_OFFSET = 34
PONG_OFFSET = 55
KONG_OFFSET = 89
WIN_INDEX = 123
PASS_INDEX = 124

# 將單一 LegalAction 轉換成固定 Action Space 中的索引位置
def action_to_index(action: LegalAction) -> int:
    # DISCARD：使用牌 ID 直接對應 0~33
    if action.action == ActionType.DISCARD:
        # 棄牌只能是 0~33 的基本牌，不能是花牌或 None
        if action.tile is None or not 0 <= action.tile < 34:
            raise ValueError("invalid discard tile")

        return DISCARD_OFFSET + action.tile

    # CHI：將 21 種合法順子映射到 34~54
    if action.action == ActionType.CHI:
        # 將吃牌的三張牌排序，方便後續驗證
        tiles = tuple(sorted(action.tiles))

        # 吃牌一定要剛好三張
        if len(tiles) != 3:
            raise ValueError("invalid chi tiles")

        # 取得順子的第一張牌
        start = tiles[0]

        # 吃牌只能由萬、筒、條組成，範圍為 0~26
        if not 0 <= start < 27:
            raise ValueError("invalid chi tiles")

        # 確認三張牌必須是連續數字
        if tiles != (start, start + 1, start + 2):
            raise ValueError("invalid chi sequence")

        # 確認三張牌屬於同一個花色
        if start // 9 != tiles[-1] // 9:
            raise ValueError("chi tiles must be in same suit")

        # 取得順子在該花色中的起始點
        rank = start % 9

        # 每個花色只有 7 種順子起點
        if rank > 6:
            raise ValueError("invalid chi sequence")

        # 計算是哪一個花色：0=萬、1=筒、2=條
        suit = start // 9

        # 將花色和順子起點轉成 0~20 的 CHI 索引
        chi_index = suit * 7 + rank

        return CHI_OFFSET + chi_index

    # PONG：每種基本牌都可以有一個碰牌位置
    if action.action == ActionType.PONG:
        # 碰牌只能使用 0~33 的基本牌
        if action.tile is None or not 0 <= action.tile < 34:
            raise ValueError("invalid pong tile")

        return PONG_OFFSET + action.tile

    # KONG：每種基本牌都可以有一個槓牌位置
    if action.action == ActionType.KONG:
        # 槓牌只能使用 0~33 的基本牌
        if action.tile is None or not 0 <= action.tile < 34:
            raise ValueError("invalid kong tile")

        return KONG_OFFSET + action.tile

    # WIN 固定映射到索引 123
    if action.action == ActionType.WIN:
        return WIN_INDEX

    # PASS 固定映射到索引 124
    if action.action == ActionType.PASS:
        return PASS_INDEX

    # 若遇到目前 Action Space 不支援的動作則報錯
    raise ValueError(f"unsupported action type: {action.action}")


# 根據目前所有合法動作建立固定長度的 Action Mask
def build_action_mask(legal_actions: LegalActions) -> tuple[int, ...]:
    # 先建立 125 個全為 0 的位置，代表全部動作都不可選
    mask = [0] * ACTION_SPACE_SIZE

    # 將每一個合法動作轉換成索引
    for action in legal_actions:
        index = action_to_index(action)

        # 合法動作對應的位置設為 1
        mask[index] = 1

    # 回傳固定長度的 Action Mask
    return tuple(mask)