from src.common.schemas import ActionType
from src.rules.game_state import GameState
from src.rules.rule import Action
from .interfaces import LegalAction, Observation

# 將 Rules 模組的 GameState 轉換成 Strategy 模組使用的 Observation
def game_state_to_observation(state: GameState, seat: int,) -> Observation:
    # 取得目前 Agent 自己的玩家狀態
    player = state.players[seat]

    # 將 Rules 的資料整理成策略模組所需要的格式
    return Observation(
        # 自己目前的手牌
        hand = tuple(player.hand),

        # 四位玩家各自的棄牌紀錄
        discards = tuple(
            tuple(state.players[i].discards)
            for i in range(4)
        ),

        # 四位玩家目前的副露資訊，例如吃、碰、槓
        melds= tuple(
            tuple(
                tuple(meld.tiles)
                for meld in state.players[i].melds
            )

            for i in range(4)
        ),

        # 四位玩家目前的花牌資訊
        flowers = tuple(
            tuple(state.players[i].flowers)
            for i in range(4)
        ),

        # 目前輪到哪位玩家行動
        current_player = state.current_turn,

        # Agent 自己的座位
        seat = seat,

        # 牌牆剩餘牌數
        remaining_tiles = state.wall_count,
    )


# 將 Rules 模組產生的 Action 轉成 Strategy 模組使用的 LegalAction
def action_to_legal_action(action: Action) -> LegalAction:
    # 統一使用共用的 ActionType
    action_type = ActionType(action.action_type)

    # PASS 不需要指定牌
    if action_type == ActionType.PASS:
        return LegalAction(id = "pass", action = action_type,)

    # CHI 需要保存完整的順子組合
    if action_type == ActionType.CHI:
        tiles = tuple(action.sequence or ())

        # 例如 [0, 1, 2] 會產生 chi_0_1_2
        action_id = "chi_" + "_".join(map(str, tiles))

        return LegalAction(id = action_id, action = action_type, tile = action.tile_id, tiles = tiles,)

    # PONG 使用目標牌建立三張相同牌
    if action_type == ActionType.PONG:
        return LegalAction(id = f"pong_{action.tile_id}", action = action_type, tile = action.tile_id, tiles = (action.tile_id,) * 3,)

    # KONG 使用目標牌建立四張相同牌
    if action_type == ActionType.KONG:
        return LegalAction(id = f"kong_{action.tile_id}", action = action_type, tile = action.tile_id, tiles = (action.tile_id,) * 4,)

    # 其他動作，例如 DISCARD、WIN，使用動作類型與牌 ID 建立唯一 ID
    return LegalAction(id = f"{action_type.value}_{action.tile_id}", action = action_type, tile = action.tile_id,)


# 將一整組 Rules Action 批次轉換成 Strategy LegalAction
def actions_to_legal_actions(actions: list[Action],) -> list[LegalAction]:
    return [
        action_to_legal_action(action)
        for action in actions
    ]