"""反應按鈕與選牌映射（W4 D1、D2）：反應決策 -> 按鈕框 -> 點擊座標。

座標規則與 tile_mapper 相同：ButtonBox / ChoiceBox 都是「擷取畫面（frame）」像素座標，
只有真的要點擊時才換成螢幕座標。

兩步驟點擊（D2）：
- 吃／槓如果合法選項有 2 個以上，要先點按鈕、再點組合（choice）。
- 只有 1 個選項時只點按鈕。
- 目前兩個座標由「同一幀」算出；點完第一步後重新擷取是 W4 D3。

按鈕與組合的來源目前是測試介面 DOM（/api/layout 的 buttons / choices）。
真實遊戲接入後，改由視覺模組的按鈕辨識（視覺 W4 D3）提供 ButtonBox 即可，本模組不用改。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from src.common.schemas import ActionType
from src.control.capture import CaptureRegion
from src.control.tile_mapper import (
    Point,
    TileMappingError,
    UnsupportedActionError,
    default_viewport_offset,
)
from src.control.window import frame_to_screen

REACTION_ACTIONS = (
    ActionType.CHI,
    ActionType.PONG,
    ActionType.KONG,
    ActionType.WIN,
    ActionType.PASS,
)
# 合法選項有多個時，需要第二步選組合的動作
CHOICE_ACTIONS = (ActionType.CHI, ActionType.KONG)


class ButtonMappingError(TileMappingError):
    """按鈕映射失敗（沿用 TileMappingError，執行器只需要 catch 一種）。"""


class ButtonNotFoundError(ButtonMappingError):
    """畫面上找不到按鈕。"""


class ButtonDisabledError(ButtonMappingError):
    """按鈕存在但目前不可點（不要盲點）。"""


class ButtonOutOfFrameError(ButtonMappingError):
    """按鈕或組合的中心不在擷取畫面內。"""


class ChoiceNotFoundError(ButtonMappingError):
    """畫面上找不到要選的組合（例如吃的某個順子）。"""


@dataclass(frozen=True)
class ButtonBox:
    action: str  # chi / pong / kong / win / pass
    x: int
    y: int
    w: int
    h: int
    enabled: bool = True

    @property
    def center(self) -> Point:
        return self.x + self.w // 2, self.y + self.h // 2


@dataclass(frozen=True)
class ChoiceBox:
    choice_id: str  # 對應策略 LegalAction.id，例如 chi_1_2_3
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> Point:
        return self.x + self.w // 2, self.y + self.h // 2


@dataclass(frozen=True)
class ClickStep:
    kind: str  # "button" | "choice"
    target: str  # 按鈕 action 或 choice id
    frame_point: Point
    screen_point: Point


@dataclass(frozen=True)
class ReactionPlan:
    action_id: str
    steps: tuple[ClickStep, ...]

    @property
    def frame_points(self) -> tuple[Point, ...]:
        return tuple(s.frame_point for s in self.steps)

    @property
    def screen_points(self) -> tuple[Point, ...]:
        return tuple(s.screen_point for s in self.steps)

    @property
    def needs_choice(self) -> bool:
        return any(s.kind == "choice" for s in self.steps)


# ---------------------------------------------------------------- Provider

def _origin(
    layout: dict[str, Any],
    offset: tuple[float, float] | None,
    scale: float | None,
    origin_px: tuple[float, float] | None,
) -> tuple[float, float, float]:
    """回傳 (dpr, 可視區原點 x_px, y_px)；規則與 tile_mapper.boxes_from_dom_layout 相同。"""
    dpr = float(scale if scale is not None else layout.get("dpr", 1.0))
    if origin_px is not None:
        return dpr, origin_px[0], origin_px[1]

    ox, oy = offset if offset is not None else default_viewport_offset(layout)
    return dpr, ox * dpr, oy * dpr


def _rect(item: dict[str, Any], dpr: float, ox: float, oy: float) -> tuple[int, int, int, int]:
    return (
        round(ox + item["x"] * dpr),
        round(oy + item["y"] * dpr),
        round(item["w"] * dpr),
        round(item["h"] * dpr),
    )


def boxes_from_dom_buttons(
    layout: dict[str, Any],
    *,
    offset: tuple[float, float] | None = None,
    scale: float | None = None,
    origin_px: tuple[float, float] | None = None,
) -> list[ButtonBox]:
    """/api/layout 的 buttons -> frame 座標 ButtonBox（欄位缺漏的項目略過）。"""
    dpr, ox, oy = _origin(layout, offset, scale, origin_px)

    boxes: list[ButtonBox] = []
    for item in layout.get("buttons", []):
        try:
            x, y, w, h = _rect(item, dpr, ox, oy)
            boxes.append(
                ButtonBox(str(item["action"]), x, y, w, h, enabled=bool(item.get("enabled", True)))
            )
        except (KeyError, TypeError, ValueError):
            continue
    return boxes


def boxes_from_dom_choices(
    layout: dict[str, Any],
    *,
    offset: tuple[float, float] | None = None,
    scale: float | None = None,
    origin_px: tuple[float, float] | None = None,
) -> list[ChoiceBox]:
    """/api/layout 的 choices（吃／槓的組合）-> frame 座標 ChoiceBox。"""
    dpr, ox, oy = _origin(layout, offset, scale, origin_px)

    boxes: list[ChoiceBox] = []
    for item in layout.get("choices", []):
        try:
            x, y, w, h = _rect(item, dpr, ox, oy)
            boxes.append(ChoiceBox(str(item["id"]), x, y, w, h))
        except (KeyError, TypeError, ValueError):
            continue
    return boxes


# ------------------------------------------------------------------ Mapper

class ButtonMapper:
    """保存「最新一幀」的按鈕與組合框；每次重新擷取後呼叫 update()。"""

    def __init__(self, frame_size: tuple[int, int] | None = None) -> None:
        self.frame_size = frame_size  # (寬, 高)
        self._buttons: tuple[ButtonBox, ...] = ()
        self._choices: tuple[ChoiceBox, ...] = ()

    def update(
        self,
        buttons: Sequence[ButtonBox] = (),
        choices: Sequence[ChoiceBox] = (),
        *,
        frame_size: tuple[int, int] | None = None,
    ) -> None:
        if frame_size is not None:
            self.frame_size = frame_size
        self._buttons = tuple(buttons)
        self._choices = tuple(choices)

    @property
    def buttons(self) -> tuple[ButtonBox, ...]:
        return self._buttons

    @property
    def choices(self) -> tuple[ChoiceBox, ...]:
        return self._choices

    def enabled_actions(self) -> tuple[str, ...]:
        """目前可點的按鈕。"""
        return tuple(b.action for b in self._buttons if b.enabled)

    def find_button(self, action: str) -> ButtonBox:
        for button in self._buttons:
            if button.action != action:
                continue
            if not button.enabled:
                raise ButtonDisabledError(f"按鈕「{action}」目前不可點")
            self._ensure_inside(f"按鈕「{action}」", button.center, ButtonOutOfFrameError)
            return button
        raise ButtonNotFoundError(f"畫面上找不到按鈕「{action}」")

    def find_choice(self, choice_id: str) -> ChoiceBox:
        for choice in self._choices:
            if choice.choice_id == choice_id:
                self._ensure_inside(f"組合「{choice_id}」", choice.center, ButtonOutOfFrameError)
                return choice
        raise ChoiceNotFoundError(f"畫面上找不到組合「{choice_id}」")

    def _ensure_inside(self, name: str, center: Point, exc_type: type[ButtonMappingError]) -> None:
        if self.frame_size is None:
            return

        width, height = self.frame_size
        cx, cy = center
        if not (0 <= cx < width and 0 <= cy < height):
            raise exc_type(f"{name}的中心 {center} 不在畫面 {width}x{height} 內")


# ---------------------------------------------------------------- 決策

def _step(kind: str, target: str, frame_point: Point, region: CaptureRegion) -> ClickStep:
    return ClickStep(kind, target, frame_point, frame_to_screen(region, *frame_point))


def plan_reaction_click(
    decision: Any,
    mapper: ButtonMapper,
    region: CaptureRegion,
    *,
    legal_actions: Sequence[Any] = (),
) -> ReactionPlan:
    """策略 Decision（吃碰槓胡過）-> 點擊計畫。只算座標，不點擊。

    legal_actions 用來判斷「同類動作有幾個」：吃／槓有 2 個以上才需要第二步選組合。
    """
    action = decision.action
    kind = ActionType(action.action)
    if kind not in REACTION_ACTIONS:
        raise UnsupportedActionError(f"反應映射不支援 {action.id}")

    button = mapper.find_button(kind.value)
    steps = [_step("button", kind.value, button.center, region)]

    siblings = [a for a in legal_actions if ActionType(a.action) == kind]
    if kind in CHOICE_ACTIONS and len(siblings) > 1:
        choice = mapper.find_choice(action.id)
        steps.append(_step("choice", action.id, choice.center, region))

    return ReactionPlan(action_id=action.id, steps=tuple(steps))