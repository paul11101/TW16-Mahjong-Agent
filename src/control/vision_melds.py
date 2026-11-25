"""用實機畫面的目標牌決定單一吃、碰，並以暗牌變化驗證結果。"""

from collections import Counter
from dataclasses import dataclass, replace
from typing import NamedTuple

from src.common.schemas import ActionType
from src.control.errors import (
    ERR_ACTION_TIMEOUT,
    ERR_CAPTURE_FAILED,
    ERR_CONTROLLER_NOT_RUNNING,
    ERR_FRAME_SIZE_CHANGED,
    ERR_WINDOW_NOT_FOREGROUND,
)
from src.control.game_profile import HAND_WAITING, classify_hand, state_from_visible_hand
from src.control.state_guard import check_state
from src.control.verifier import VerifyResult
from src.control.vision_adapter import ConfirmedMeldFrame, boxes_from_cards
from src.rules.game_state import Meld
from src.rules.legal_actions import LegalActionGenerator
from src.strategy.adapters import actions_to_legal_actions, game_state_to_observation
from src.strategy.interfaces import LegalAction
from src.strategy.meld_policy import simulate_meld


MELD_ACTIONS = frozenset({ActionType.CHI, ActionType.PONG})


class MeldPrompt(NamedTuple):
    """辨識到的棄牌、出牌者與完整暗牌，兩次觀察須一致。"""

    tile: int
    player_id: int
    hand: tuple[int, ...]


def read_meld_prompt(data, back, seat, meld_count, min_confidence):
    """只接受其他玩家打牌的畫面及可信的暗牌計數。"""
    target = data.get("reaction_target")
    if not target or any(data.get(flag) for flag in ("is_my_turn", "is_animating", "in_settlement")):
        return None
    tile, player = target["tile"], target["player_id"]
    if not 0 <= tile < 34 or not 0 <= player < 4 or player == seat or meld_count >= 5:
        return None

    boxes = boxes_from_cards(data.get("hand_cards", ()), back)
    hand = tuple(sorted(box.tile for box in boxes))
    if any(box.confidence < min_confidence for box in boxes):
        return None
    if classify_hand(hand, meld_count=meld_count) != HAND_WAITING:
        return None
    if not check_state(hand, hand, meld_count=meld_count).ok:
        return None
    return MeldPrompt(tile, player, hand)


def choose_single_meld(prompt, buttons, own_melds, policy, game_id, seat):
    """沿用規則與策略，只提供可見且無須再選組合的副露候選。"""
    observed_copies = prompt.hand.count(prompt.tile) + sum(
        meld.tiles.count(prompt.tile) for meld in own_melds
    )
    if observed_copies >= 4:
        return None
    rules = LegalActionGenerator().get_response_actions(
        list(prompt.hand), prompt.tile, is_previous_player=(prompt.player_id + 1) % 4 == seat,
    )
    legal = actions_to_legal_actions(rules)
    counts = Counter(action.action for action in legal)
    choices = [
        action for action in legal
        if action.action == ActionType.PASS or (
            action.action in MELD_ACTIONS and action.action.value in buttons
            and counts[action.action] == 1
        )
    ]
    if len(choices) == 1:
        return None

    state = state_from_visible_hand(game_id, prompt.hand, seat=seat)
    state.current_turn = prompt.player_id
    state.players[seat].melds = list(own_melds)
    state.players[prompt.player_id].discards = [prompt.tile]
    # 牌牆數字目前未辨識，策略只得到畫面可證實的公共資訊。
    observation = replace(game_state_to_observation(state, seat), remaining_tiles=None)
    decision = policy.decide(observation, choices)
    if decision.action not in choices:
        raise ValueError("反應策略回傳的動作不在當前畫面可執行的候選中")
    return decision


@dataclass(frozen=True)
class ExpectedMeld:
    """成功副露後，自己應保留的暗牌與新增的副露。"""

    meld: Meld
    remaining: tuple[int, ...]

    @classmethod
    def from_action(cls, action: LegalAction, prompt: MeldPrompt):
        """沿用策略的模擬移除吃、碰所需的兩張手牌。"""
        remaining = simulate_meld(prompt.hand, action)
        meld = Meld(
            meld_type=action.action, tiles=list(action.tiles),
            from_player=prompt.player_id,
        )
        return cls(meld, remaining)

    def matches(self, hand):
        """畫面上的牌種及各牌張數須符合預計剩下的暗牌。"""
        return Counter(self.remaining) == Counter(hand)


class MeldVerifier:
    """接到共用動作執行器，連續兩次看見預期暗牌後才確認副露。"""

    def __init__(
        self, expected, controller, vision, frame_size, meld_count, *,
        min_confidence, attempts, poll_interval, sleep, clock, foreground_check, base_verifier,
    ):
        self.expected = expected
        self.controller = controller
        self.vision = vision
        self.frame_size = frame_size
        self.meld_count = meld_count
        self.min_confidence = min_confidence
        self.attempts = max(2, attempts)
        self.poll_interval = poll_interval
        self.sleep = sleep
        self.clock = clock
        self.foreground_check = foreground_check
        self.base_verifier = base_verifier
        self.confirmed_frame: ConfirmedMeldFrame | None = None

    def prepare(self, point):
        """沿用擷取基準影像時的視窗位置／大小檢查。"""
        return self.base_verifier is None or self.base_verifier.prepare(point)

    def wait(self, timeout=None):
        """確認兩幀暗牌；畫面沒變時沿用第一幀的辨識，失焦或逾時則失敗。"""
        start = self.clock()
        self.confirmed_frame = None
        previous: ConfirmedMeldFrame | None = None

        def result(polls, error=None):
            """回傳共用執行器預期的驗證結果。"""
            return VerifyResult(
                error is None, error is None, (self.clock() - start) * 1000,
                polls, 0.0, error,
            )

        polls = 0
        for _ in range(self.attempts):
            self.sleep(self.poll_interval)
            if not self.controller.is_running:
                return result(polls, ERR_CONTROLLER_NOT_RUNNING)
            if self.foreground_check is not None and not self.foreground_check():
                return result(polls, ERR_WINDOW_NOT_FOREGROUND)
            frame = self.controller.capture()
            polls += 1
            if frame is None:
                return result(polls, ERR_CAPTURE_FAILED)
            if self.frame_size is not None and (frame.shape[1], frame.shape[0]) != self.frame_size:
                return result(polls, ERR_FRAME_SIZE_CHANGED)
            if previous is not None and previous.matches(frame):
                self.confirmed_frame = replace(previous, frame=frame)
                return result(polls)

            data = self.vision.detect(frame)
            boxes = boxes_from_cards(data.get("hand_cards", ()), self.vision.last_back)
            hand = tuple(sorted(box.tile for box in boxes))
            matches = (
                data.get("is_my_turn")
                and not (data.get("is_animating") or data.get("in_settlement"))
                and all(box.confidence >= self.min_confidence for box in boxes)
                and check_state(hand, hand, meld_count=self.meld_count).ok
                and self.expected.matches(hand)
            )
            if not matches:
                previous = None
                continue
            current = ConfirmedMeldFrame(frame, data, self.vision.last_back, self.min_confidence)
            if previous is not None:
                self.confirmed_frame = current
                return result(polls)
            previous = current
        return result(polls, ERR_ACTION_TIMEOUT)
