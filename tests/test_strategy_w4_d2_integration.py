import json

from src.common.schemas import ActionType
from src.common.logger import AppLogger
from src.control.button_mapper import ButtonBox, ButtonMapper
from src.control.capture import CaptureRegion
from src.control.controller import AgentController
from src.control.pipeline import EventIds, get_reaction_rules_actions, run_reaction_turn
from src.rules.game_state import GameState, LastDiscard, PlayerState
from src.strategy.adapters import actions_to_legal_actions

# 測試中的 Agent 座位固定為玩家 0；上家為玩家 3
SEAT = 0
# 測試胡牌反應：等待上家打出 3 後可以組成一般胡牌牌型
WIN_HAND = [0, 1, 2, 3, 3, 4, 5, 6, 9, 10, 11, 18, 19, 20, 27, 27]
# 測試過牌反應：即使可以吃或碰，目前 Baseline 仍會選擇 PASS
PASS_HAND = [0, 1, 2, 3, 3, 4, 5, 6, 9, 10, 11, 18, 19, 20, 27, 30]

# 只記錄點擊座標，不操作真實滑鼠，避免測試影響桌面
class FakeMouse:
    def __init__(self):
        self.clicks = []

    def click(self, x, y):
        self.clicks.append((x, y))


# 建立模擬的 Rules GameState，並指定上家最新打出的牌
def make_state(hand, target_tile, game_id):
    return GameState(
        game_id = game_id,
        current_turn = SEAT,
        wall_count = 80,
        last_discard = LastDiscard(player_id = 3, tile_id = target_tile),
        players = {
            i: PlayerState(seat_id = i, hand = list(hand) if i == SEAT else [])
            for i in range(4)
        },
    )


# 建立假按鈕的位置，讓 Integration 能把策略動作轉成點擊座標
def make_mapper():
    mapper = ButtonMapper(frame_size = (800, 600))
    mapper.update(buttons = [
        ButtonBox("win", 100, 100, 40, 20),
        ButtonBox("pass", 200, 100, 40, 20),
    ])

    return mapper


# 透過真正的整合入口測試 Rules -> Strategy -> Integration
def run_pipeline(state, tmp_path):
    mouse = FakeMouse()

    # 啟用事件日誌，測試結束後確認是否完成決策與動作
    with AppLogger(log_dir = str(tmp_path), game_id = state.game_id) as logger:
        controller = AgentController(game_id = state.game_id, mouse = mouse, logger = logger,)
        controller.start()

        # 不傳入 policy，直接驗證 Integration 預設的 BaselinePolicy
        try:
            result = run_reaction_turn(
                state,
                SEAT,
                make_mapper(),
                CaptureRegion(0, 0, 800, 600),
                controller,
                game_id = state.game_id,
                ids = EventIds(),
                logger = logger,
            )

        # 無論測試成功或失敗，都關閉控制器
        finally:
            controller.stop()

    # 從 JSONL 取出事件類型，確認完整執行流程
    log_path = tmp_path / f"{state.game_id}.jsonl"
    events = [json.loads(line)["event_type"] for line in log_path.read_text(encoding = "utf-8").splitlines()]

    return result, mouse.clicks, events


# 案例一：Rules 同時允許吃、碰、胡時，Strategy 必須優先胡牌
def test_rules_to_baseline_win(tmp_path):
    state = make_state(WIN_HAND, 3, "w4_d2_win")
    rules_actions = get_reaction_rules_actions(state, SEAT)
    legal = actions_to_legal_actions(rules_actions)
    action_types = {a.action for a in legal}

    # 確認 Rules 真正提供合法反應，並非測試自行指定 WIN
    assert {ActionType.WIN, ActionType.CHI, ActionType.PONG, ActionType.PASS,} <= action_types

    # 執行反應回合並取得決策、點擊與事件紀錄
    result, clicks, events = run_pipeline(state, tmp_path)

    assert result.success is True
    assert result.decision.action.action == ActionType.WIN
    assert result.decision.action in legal
    assert result.receipt.success is True
    assert clicks == [(120, 110)]
    assert "legal_actions_generated" in events
    assert "action_completed" in events


# 案例二：可以吃碰但不能胡牌時，目前 Baseline 應選擇 PASS
def test_rules_to_baseline_pass(tmp_path):
    state = make_state(PASS_HAND, 3, "w4_d2_pass")
    rules_actions = get_reaction_rules_actions(state, SEAT)
    legal = actions_to_legal_actions(rules_actions)
    action_types = {a.action for a in legal}

    # 先確認 Rules 產生 CHI、PONG、PASS，且沒有 WIN
    assert ActionType.CHI in action_types
    assert ActionType.PONG in action_types
    assert ActionType.PASS in action_types
    assert ActionType.WIN not in action_types

    # 執行反應回合並取得決策、點擊與事件紀錄
    result, clicks, events = run_pipeline(state, tmp_path)

    assert result.success is True
    assert result.decision.action.action == ActionType.PASS
    assert result.decision.action in legal
    assert  clicks == [(220, 110)]
    assert "decision_made" in events
    assert "action_completed" in events


# 案例三：只有 PASS 一個合法反應時，Integration 應直接略過點擊
def test_only_pass_skips_click(tmp_path):
    state = make_state(PASS_HAND, 33, "w4_d2_skip")
    legal = actions_to_legal_actions(get_reaction_rules_actions(state, SEAT))

    assert len(legal) == 1
    assert legal[0].action == ActionType.PASS

    # 執行反應回合並取得決策、點擊與事件紀錄
    result, clicks, events = run_pipeline(state, tmp_path)

    # 確認沒有實際動作或回執，僅記錄 reaction_skipped 事件
    assert result.skipped is True
    assert result.decision is None
    assert result.receipt is None
    assert clicks == []
    assert "reaction_skipped" in events
    assert "action_started" not in events