"""W4 D1/D2 按鈕與選牌映射測試（合成資料，不需要瀏覽器）。

執行方式（專案根目錄）：
    python -m tests.test_button_mapper
或
    python -m pytest tests/test_button_mapper.py -v
"""

from src.common.schemas import ActionType
from src.control.button_mapper import (
    ButtonBox,
    ButtonDisabledError,
    ButtonMapper,
    ButtonNotFoundError,
    ButtonOutOfFrameError,
    ChoiceBox,
    ChoiceNotFoundError,
    boxes_from_dom_buttons,
    boxes_from_dom_choices,
    plan_reaction_click,
)
from src.control.capture import CaptureRegion
from src.control.tile_mapper import UnsupportedActionError
from src.strategy.interfaces import Decision, LegalAction

# dpr 1.5、outer 1280x800、inner 1264x700 -> 可視區偏移 (8, 92) CSS px
REGION = CaptureRegion(100, 50, 1920, 1200)
FRAME_SIZE = (1920, 1200)
CHI_IDS = ["chi_0_1_2", "chi_1_2_3", "chi_2_3_4"]


def _raises(exc_type, fn):
    try:
        fn()
    except exc_type:
        return
    raise AssertionError(f"應該拋出 {exc_type.__name__}")


def make_layout(disabled=("kong", "win")):
    names = ["chi", "pong", "kong", "win", "pass"]
    buttons = [
        {"action": n, "enabled": n not in disabled, "x": 100 + i * 60, "y": 500, "w": 50, "h": 30}
        for i, n in enumerate(names)
    ]
    choices = [
        {"id": cid, "x": 100 + i * 100, "y": 560, "w": 80, "h": 20}
        for i, cid in enumerate(CHI_IDS)
    ]
    return {
        "dpr": 1.5,
        "inner": [1264, 700],
        "outer": [1280, 800],
        "buttons": buttons,
        "choices": choices,
    }


def _mapper(layout=None, *, with_choices=True):
    layout = layout or make_layout()
    mapper = ButtonMapper(frame_size=FRAME_SIZE)
    mapper.update(
        boxes_from_dom_buttons(layout),
        boxes_from_dom_choices(layout) if with_choices else (),
    )
    return mapper


def _legal(chi_ids=CHI_IDS):
    actions = [LegalAction(id="pong_2", action=ActionType.PONG, tile=2, tiles=(2, 2, 2))]
    for cid in chi_ids:
        seq = tuple(int(p) for p in cid.split("_")[1:])
        actions.append(LegalAction(id=cid, action=ActionType.CHI, tile=2, tiles=seq))
    actions.append(LegalAction(id="pass", action=ActionType.PASS))
    return actions


def _decision(legal, action_id) -> Decision:
    action = next(a for a in legal if a.id == action_id)
    return Decision(action=action, score=1.0, reason="test")


def test_dom_buttons_to_frame_boxes():
    boxes = boxes_from_dom_buttons(make_layout())

    assert len(boxes) == 5
    # x: (100+8)*1.5=162  y: (500+92)*1.5=888  w: 50*1.5=75  h: 30*1.5=45
    assert boxes[0] == ButtonBox("chi", 162, 888, 75, 45, enabled=True)
    assert boxes[0].center == (199, 910)
    assert boxes[2].action == "kong" and boxes[2].enabled is False

    assert _mapper().enabled_actions() == ("chi", "pong", "pass")


def test_dom_choices_to_frame_boxes():
    boxes = boxes_from_dom_choices(make_layout())

    assert [b.choice_id for b in boxes] == CHI_IDS
    # 第二個：x=(200+8)*1.5=312  y=(560+92)*1.5=978  w=120  h=30
    assert boxes[1] == ChoiceBox("chi_1_2_3", 312, 978, 120, 30)
    assert boxes[1].center == (372, 993)


def test_dom_boxes_use_origin_px():
    layout = make_layout()
    box = boxes_from_dom_buttons(layout, origin_px=(37, 91))[0]
    # x = 37 + 100*1.5 = 187，y = 91 + 500*1.5 = 841
    assert (box.x, box.y, box.w, box.h) == (187, 841, 75, 45)

    # 有給 origin_px 時，不使用 inner/outer 的估計值
    layout["inner"], layout["outer"] = [1, 1], [999, 999]
    assert boxes_from_dom_buttons(layout, origin_px=(37, 91))[0].x == 187


def test_pong_is_single_step():
    legal = _legal()
    plan = plan_reaction_click(_decision(legal, "pong_2"), _mapper(), REGION, legal_actions=legal)

    assert len(plan.steps) == 1 and plan.needs_choice is False
    assert plan.frame_points == ((289, 910),)
    assert plan.screen_points == ((389, 960),)  # 加視窗偏移 (100, 50)


def test_chi_with_several_options_needs_choice():
    legal = _legal()
    plan = plan_reaction_click(_decision(legal, "chi_1_2_3"), _mapper(), REGION, legal_actions=legal)

    assert plan.needs_choice is True
    assert [(s.kind, s.target) for s in plan.steps] == [("button", "chi"), ("choice", "chi_1_2_3")]
    assert plan.screen_points == ((299, 960), (472, 1043))


def test_chi_with_single_option_skips_choice():
    legal = _legal(["chi_1_2_3"])
    plan = plan_reaction_click(_decision(legal, "chi_1_2_3"), _mapper(), REGION, legal_actions=legal)

    assert plan.needs_choice is False
    assert plan.screen_points == ((299, 960),)


def test_pass_click():
    legal = _legal()
    plan = plan_reaction_click(_decision(legal, "pass"), _mapper(), REGION, legal_actions=legal)

    # pass 是第 5 個按鈕：x=(340+8)*1.5=522，中心 (522+37, 910)
    assert plan.frame_points == ((559, 910),)
    assert plan.screen_points == ((659, 960),)


def test_disabled_button_rejected():
    decision = Decision(
        action=LegalAction(id="win_2", action=ActionType.WIN, tile=2), score=1.0, reason="test"
    )
    _raises(ButtonDisabledError, lambda: plan_reaction_click(decision, _mapper(), REGION))


def test_missing_button_and_choice():
    legal = _legal()

    empty = ButtonMapper(frame_size=FRAME_SIZE)
    _raises(
        ButtonNotFoundError,
        lambda: plan_reaction_click(_decision(legal, "pass"), empty, REGION, legal_actions=legal),
    )

    no_choices = _mapper(with_choices=False)
    _raises(
        ChoiceNotFoundError,
        lambda: plan_reaction_click(_decision(legal, "chi_1_2_3"), no_choices, REGION, legal_actions=legal),
    )


def test_unsupported_action_rejected():
    decision = Decision(
        action=LegalAction(id="discard_0", action=ActionType.DISCARD, tile=0), score=0.0, reason="test"
    )
    _raises(UnsupportedActionError, lambda: plan_reaction_click(decision, _mapper(), REGION))


def test_out_of_frame_rejected():
    layout = make_layout()
    mapper = ButtonMapper(frame_size=(100, 100))
    mapper.update(boxes_from_dom_buttons(layout), boxes_from_dom_choices(layout))
    _raises(ButtonOutOfFrameError, lambda: mapper.find_button("chi"))
    _raises(ButtonOutOfFrameError, lambda: mapper.find_choice("chi_0_1_2"))


if __name__ == "__main__":
    test_dom_buttons_to_frame_boxes()
    test_dom_choices_to_frame_boxes()
    test_dom_boxes_use_origin_px()
    test_pong_is_single_step()
    test_chi_with_several_options_needs_choice()
    test_chi_with_single_option_skips_choice()
    test_pass_click()
    test_disabled_button_rejected()
    test_missing_button_and_choice()
    test_unsupported_action_rejected()
    test_out_of_frame_rejected()
    print("✅ test_button_mapper：11 項測試全部通過")