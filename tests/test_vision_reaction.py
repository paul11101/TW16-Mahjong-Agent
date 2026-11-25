"""W8 真實遊戲反應回合：有胡點胡，否則點過；多幀確認、胡的信心門檻、冷卻、除錯圖。

執行方式（專案根目錄）：
    python -m tests.test_vision_reaction
"""

from src.common.schemas import ActionType
from src.control.game_runner import PHASE_OVER, PHASE_REACTION, PHASE_WAITING, Snapshot
from src.control.vision_turns import pick_reaction_button
from tests._runner import run_module
from tests.test_game_runner import make, result, seq, snap
from tests.test_vision_turns import S16, build


def btn(name, x, conf=0.9):
    return {"name": name, "bbox": (x, 40, 30, 20), "confidence": conf}


def setup(*buttons, **kw):
    """偵測器每次都回傳同樣的按鈕（確認那一次也看得到）。"""
    state = {**S16, "action_buttons": list(buttons)}
    _, mouse, detector, turns = build([state], **kw)
    return mouse, turns, state, detector


def react(turns, state):
    return turns[PHASE_REACTION](Snapshot(phase=PHASE_REACTION, data=state))


def test_pick_reaction_button():
    assert pick_reaction_button(["chi", "pong", "pass"]) == "pass"
    assert pick_reaction_button(["win", "pass"]) == "win"
    assert pick_reaction_button(["chi", "pong"]) is None
    assert pick_reaction_button([]) is None


def test_clicks_pass_when_no_win():
    mouse, turns, state, _ = setup(btn("btn_chi", 200), btn("btn_pass", 300))
    out = react(turns, state)

    assert out.success is True and out.decision.action.action == ActionType.PASS
    assert mouse.clicks == [(320, 57)]  # 中心 (315,50) + 視窗偏移 (5,7)


def test_clicks_win_first():
    mouse, turns, state, _ = setup(btn("btn_pass", 300), btn("btn_hu", 250))
    out = react(turns, state)

    assert out.decision.action.action == ActionType.WIN
    assert mouse.clicks == [(270, 57)]


def test_low_confidence_win_is_ignored():
    mouse, turns, state, _ = setup(btn("btn_hu", 250, 0.6), btn("btn_pass", 300))
    out = react(turns, state)

    assert out.decision.action.action == ActionType.PASS  # 胡信心 0.6 < 0.75，當作沒看到
    assert mouse.clicks == [(320, 57)]

    mouse2, turns2, state2, _ = setup(btn("btn_hu", 250, 0.6))
    assert react(turns2, state2).skipped is True and mouse2.clicks == []


def test_unknown_or_missing_pass_is_skipped():
    mouse, turns, state, _ = setup(btn("btn_chi", 200), btn("btn_peng", 240))
    assert react(turns, state).skipped is True

    mouse2, turns2, state2, _ = setup(btn("btn_ting", 200))
    assert react(turns2, state2).skipped is True  # 聽牌按鈕不處理
    assert mouse.clicks == [] and mouse2.clicks == []


def test_transient_button_is_not_clicked():
    # 第一次辨識有按鈕，重拍確認時已經消失（動畫一閃而過）
    _, mouse, _, turns = build([S16])  # 偵測器重拍只看到沒有按鈕的畫面
    state = {**S16, "action_buttons": [btn("btn_hu", 250)]}
    out = react(turns, state)

    assert out.skipped is True and mouse.clicks == []


def test_confirm_off_skips_second_detection():
    mouse, turns, state, detector = setup(btn("btn_pass", 300), confirm=False)
    out = react(turns, state)

    assert out.success is True and mouse.clicks == [(320, 57)]
    assert detector.calls == 0


def test_win_cooldown_then_win_again():
    t = {"now": 100.0}
    mouse, turns, state, _ = setup(btn("btn_hu", 250), btn("btn_pass", 300), clock=lambda: t["now"])

    assert react(turns, state).decision.action.action == ActionType.WIN
    assert react(turns, state).decision.action.action == ActionType.PASS  # 冷卻中改點過
    t["now"] += 25.0
    assert react(turns, state).decision.action.action == ActionType.WIN
    assert mouse.clicks == [(270, 57), (320, 57), (270, 57)]


def test_cooldown_without_pass_button_skips():
    t = {"now": 0.0}
    mouse, turns, state, _ = setup(btn("btn_hu", 250), clock=lambda: t["now"])

    assert react(turns, state).success is True
    assert react(turns, state).skipped is True  # 只剩胡、又在冷卻：不點
    assert mouse.clicks == [(270, 57)]


def test_debug_image_is_saved(tmp_path):
    _, turns, state, _ = setup(btn("btn_hu", 250), btn("btn_pass", 300), debug_dir=str(tmp_path))
    react(turns, state)

    assert len(list(tmp_path.glob("g_react_1_win.png"))) == 1


def test_skipped_screen_saves_debug_image(tmp_path):
    # 只看到吃／碰、沒有過：略過，但要留下畫面方便查原因
    _, turns, state, _ = setup(btn("btn_chi", 200), btn("btn_peng", 240), debug_dir=str(tmp_path))
    out = react(turns, state)

    assert out.skipped is True
    assert len(list(tmp_path.glob("g_react_1_skip.png"))) == 1


def test_button_on_left_side_is_ignored():
    # 牌桌空白處的誤判（位置在畫面左半邊）不能當按鈕，即使信心很高
    mouse, turns, state, _ = setup(btn("btn_hu", 100, 0.95), btn("btn_pass", 300))
    out = react(turns, state)

    assert out.decision.action.action == ActionType.PASS
    assert mouse.clicks == [(320, 57)]


def test_cancel_button_counts_as_pass():
    from src.control.vision_adapter import button_action

    assert button_action("btn_cancel") == "pass" and button_action("btn_quxiao") == "pass"

    mouse, turns, state, _ = setup(btn("btn_chi", 250), btn("btn_cancel", 300))
    out = react(turns, state)

    assert out.decision.action.action == ActionType.PASS
    assert mouse.clicks == [(320, 57)]


def test_same_reaction_screen_repeated_does_not_hit_max_attempts():
    # 我沒動手牌時，三家連續打牌會出現指紋相同的反應畫面
    items = []
    for _ in range(5):
        items += [snap(PHASE_REACTION, "same"), snap(PHASE_WAITING)]
    runner, _ = make(seq(items + [snap(PHASE_OVER)]), lambda s: result())
    summary = runner.run()

    assert summary.finished and summary.reason == "game_over"
    assert summary.completed == 5 and summary.interventions == 0


if __name__ == "__main__":
    run_module(globals(), "test_vision_reaction")