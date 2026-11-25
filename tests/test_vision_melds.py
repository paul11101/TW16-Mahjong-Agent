"""測試桌面版反應目標、單一副露與操作後的暗牌驗證。"""

from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from src.common.schemas import ActionType
from src.control.capture import ScreenCapture
from src.control.controller import AgentController
from src.control.game_runner import PHASE_REACTION, GameRunner
from src.control.pipeline import EventIds
from src.control.state_guard import StateGuard
from src.control.tile_mapper import TileMapper
from src.control.vision_adapter import DetectorVision, VisionObserver
from src.control.vision_melds import MeldPrompt, choose_single_meld
from src.control.vision_turns import make_vision_turns
from src.perception.detector import MahjongDetector
from src.strategy.action_policy import ActionPolicy
from test_interface.fakes import FakeMouse
from tests.helpers import FakeClock
from tests.test_strategy_reaction_comparison import CHI_HAND, MING_HAND, PONG_HAND
from tests.test_vision_turns import FRAME_SIZE, OVER, REGION, state


SINGLE_CHI = (0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 27, 3, 4, 28, 30, 33)


def reaction_state(hand, tile, source, button):
    """建立只含畫面可見欄位的反應畫面。"""
    return {
        **state(hand, turn=False),
        "reaction_target": {"tile": tile, "player_id": source},
        "action_buttons": [
            {"name": button, "bbox": (263, 39, 30, 20), "confidence": 0.95},
            {"name": "btn_pass", "bbox": (312, 39, 30, 20), "confidence": 0.95},
        ],
    }


def setup(states, own_melds, **kwargs):
    """以假截圖和滑鼠走真實版回合、驗證及整局流程。"""
    class FrameDetector:
        """依畫面上的記號辨識牌局，重拍同一牌局不會推進狀態。"""

        base_height = 100.0

        def __init__(self):
            self.calls = []

        def detect_full_state(self, image, scan_secondary_rois=False):
            self.calls.append(len(mouse.clicks))
            return states[int(image[75, 30, 0])]

    detector = FrameDetector()
    vision = DetectorVision(detector)
    mouse = FakeMouse()
    grabs = 0

    def grab(_region):
        """在手牌區記下當前畫面，並模擬畫面上方倒數持續變化。"""
        nonlocal grabs
        current = states[min(grabs, len(states) - 1)]
        marker = next(i for i, item in enumerate(states) if item == current)
        grabs += 1
        frame = np.zeros((100, 400, 3), dtype=np.uint8)
        frame[75, 30, 0] = marker
        frame[40, 320, 0] = grabs % 256
        return frame

    controller = AgentController(mouse=mouse, capturer=ScreenCapture(grab_fn=grab))
    controller.start()
    ids = EventIds()
    guard = StateGuard(controller, game_id="meld", next_event_id=ids.next)
    mapper = TileMapper(frame_size=FRAME_SIZE)
    turns = make_vision_turns(
        controller, vision, mapper, guard, REGION, game_id="meld", ids=ids,
        policy=ActionPolicy(include_candidate_scores=False),
        own_melds=own_melds, sleep=lambda _: None, refresh_attempts=2, **kwargs,
    )
    observer = VisionObserver(controller.capture, vision, meld_count_fn=lambda: len(own_melds))
    clock = FakeClock()
    runner = GameRunner(
        controller, game_id="meld", observe_fn=observer.snapshot, turn_fns=turns,
        poll_interval=0.1, pause_timeout=0.2, clock=clock, sleep=clock.sleep,
    )
    return runner, mouse, observer, turns


@pytest.mark.parametrize("hand,target,source,button,used,action_id,kind", [
    (SINGLE_CHI, 5, 3, "btn_chi", (3, 4), "chi_3_4_5", ActionType.CHI),
    (PONG_HAND, 33, 2, "btn_peng", (33, 33), "pong_33", ActionType.PONG),
])
def test_claim_then_discards_with_fourteen_concealed_tiles(
    hand, target, source, button, used, action_id, kind,
):
    """吃、碰都須確認副露，下一回合才可用 14 張暗牌出牌。"""
    before = reaction_state(hand, target, source, button)
    after_hand = list(hand)
    for tile in used:
        after_hand.remove(tile)
    after = state(after_hand)
    own_melds = []
    runner, mouse, observer, _ = setup([before, before, after, after, after, after, OVER], own_melds)

    summary = runner.run()

    assert summary.finished and summary.failed == 0
    assert [step.action_id for step in runner.records][0] == action_id
    assert runner.records[0].state_verified
    assert runner.records[1].action_id.startswith("discard_")
    assert runner.records[1].detail["hand_count"] == 14
    assert runner.records[1].detail.get("meld_hand_reused") is True
    assert observer.vision.detector.calls.count(1) == 1
    assert len(own_melds) == 1 and own_melds[0].meld_type == kind
    assert own_melds[0].from_player == source
    assert mouse.clicks[0] == (283, 56) and len(mouse.clicks) == 2


def test_claim_reuses_new_boxes_when_the_same_hand_moves():
    """交接畫面改變但暗牌相同時，只辨識新畫面一次，並點新位置。"""
    before = reaction_state(SINGLE_CHI, 5, 3, "btn_chi")
    remaining = [tile for tile in SINGLE_CHI if tile not in (3, 4)]
    after = state(remaining)
    moved = state(remaining)
    for card in moved["hand_cards"]:
        x, y, w, h = card["bbox"]
        card["bbox"] = (x + 12, y, w, h)
    runner, mouse, observer, _ = setup([before, before, after, after, moved, moved, OVER], [])

    summary = runner.run()

    assert summary.finished and summary.completed == 2
    discard = runner.records[1]
    assert discard.detail.get("meld_hand_reused") is True
    assert observer.vision.detector.calls.count(1) == 2
    tile = int(discard.action_id.split("_")[1])
    assert mouse.clicks[1] == (34 + 20 * remaining.index(tile), 82)


@pytest.mark.parametrize("change", ["hand", "confidence"])
def test_claim_keeps_normal_refresh_if_new_observation_cannot_reuse(change):
    """牌種不符或信心不足時，照原流程重拍確認。"""
    before = reaction_state(SINGLE_CHI, 5, 3, "btn_chi")
    remaining = [tile for tile in SINGLE_CHI if tile not in (3, 4)]
    after = state(remaining)
    if change == "hand":
        observed = state(remaining[:-1] + [6])
        refreshed = observed
    else:
        observed = state(remaining)
        observed["hand_cards"][0]["confidence"] = 0.8
        refreshed = after
    runner, _, observer, _ = setup(
        [before, before, after, after, observed, refreshed, OVER], [], min_confidence=0.9,
    )

    summary = runner.run()

    assert summary.finished and summary.completed == 2
    assert not runner.records[1].detail.get("meld_hand_reused")
    assert observer.vision.detector.calls.count(1) == 3


def test_ambiguous_chi_passes():
    """有多個合法吃法時，不擅自開啟選牌介面。"""
    before = reaction_state(CHI_HAND, 5, 3, "btn_chi")
    _, mouse, observer, turns = setup([before], [])
    result = turns[PHASE_REACTION](observer.snapshot())

    assert result.success and result.decision.action.action == ActionType.PASS
    assert mouse.clicks == [(332, 56)]


def test_kong_is_not_offered_to_strategy():
    """只有明槓按鈕時，整合層不把槓送入策略評估。"""
    def reject_candidates(_observation, _actions):
        pytest.fail("僅顯示明槓按鈕時應直接略過副露策略")

    policy = SimpleNamespace(decide=reject_candidates)
    prompt = MeldPrompt(33, 1, MING_HAND)
    assert choose_single_meld(prompt, {"kong"}, [], policy, "meld", 0) is None


def test_kong_prompt_clicks_cancel():
    """僅可明槓的提示有取消時，維持單點過牌。"""
    before = reaction_state(MING_HAND, 33, 1, "btn_gang")
    own_melds = []
    _, mouse, observer, turns = setup([before], own_melds)
    result = turns[PHASE_REACTION](observer.snapshot())

    assert result.success and result.decision.action.action == ActionType.PASS
    assert mouse.clicks == [(332, 56)]
    assert own_melds == []


def test_failed_claim_does_not_change_meld_count_or_repeat_click():
    """按鈕動畫不代表成功，偶然一張符合的畫面也不能提交副露。"""
    before = reaction_state(SINGLE_CHI, 5, 3, "btn_chi")
    after = state([tile for tile in SINGLE_CHI if tile not in (3, 4)])
    own_melds = []
    _, mouse, observer, turns = setup([before, before, after, before], own_melds)
    snap = observer.snapshot()
    result = turns[PHASE_REACTION](snap)

    assert not result.success and result.receipt.ui_action_executed
    assert result.error == "ACTION_TIMEOUT"
    assert own_melds == []
    assert not turns[PHASE_REACTION](snap).success
    assert mouse.clicks == [(283, 56)]


def test_changed_view_after_confirmed_claim_drops_cached_hand():
    """若交接時的畫面已經進到別人回合，不點舊的出牌座標。"""
    before = reaction_state(SINGLE_CHI, 5, 3, "btn_chi")
    remaining = [tile for tile in SINGLE_CHI if tile not in (3, 4)]
    after = state(remaining)
    waiting = state(remaining[:-1], turn=False)
    own_melds = []
    runner, mouse, _, _ = setup([before, before, after, after, waiting, OVER], own_melds)

    summary = runner.run()

    assert summary.finished and summary.failed == 0 and len(own_melds) == 1
    assert [record.action_id for record in runner.records] == ["chi_3_4_5"]
    assert mouse.clicks == [(283, 56)]


def test_changed_target_during_confirmation_is_not_clicked():
    """重拍時若提示牌換了，舊決策不能點到下一個提示。"""
    first = reaction_state(PONG_HAND, 33, 2, "btn_peng")
    second = reaction_state(PONG_HAND, 27, 2, "btn_peng")
    _, mouse, observer, turns = setup([first, second], [])

    assert turns[PHASE_REACTION](observer.snapshot()).skipped
    assert mouse.clicks == []


@pytest.mark.needs_data
@pytest.mark.parametrize("name,expected", [
    ("frame_0001", (4, 3)),
    ("frame_0002", (29, 3)),
    ("frame_0003", (29, 2)),
    ("frame_00013", (19, 1)),
    ("frame_00012", None),
])
def test_actual_reaction_target(name, expected, monkeypatch):
    """重播不同視窗尺寸與座位的實機反應提示。"""
    root = Path(__file__).resolve().parents[1]
    path = root / "data/raw/game_stream_02" / f"{name}.png"
    if not path.is_file():
        pytest.skip(f"缺少實機截圖 {path.name}")
    monkeypatch.chdir(root)
    vision = DetectorVision(MahjongDetector("data/samples"), scan_reaction_target=True)
    frame = cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)

    target = vision.detect(frame).get("reaction_target")

    if expected is None:
        assert target is None
    else:
        assert (target["tile"], target["player_id"]) == expected
