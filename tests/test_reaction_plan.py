"""W4 D1/D2 反應回合測試：假牌局 -> 反應決策 -> 假滑鼠點擊（1~2 次）-> 回執 -> JSONL。

不需要瀏覽器。執行方式（專案根目錄）：
    python -m tests.test_reaction_plan
或
    python -m pytest tests/test_reaction_plan.py -v
"""

import json
import tempfile
from pathlib import Path

from src.common.logger import AppLogger
from src.control.button_mapper import ButtonMapper, boxes_from_dom_buttons, boxes_from_dom_choices
from src.control.capture import CaptureRegion
from src.control.controller import AgentController
from src.control.pipeline import EventIds, run_reaction_turn
from src.rules.game_state import LastDiscard
from test_interface import app as app_module
from test_interface.agent_runner import SEAT
from test_interface.scripted_policy import ScriptedPolicy
from test_interface.table_view import make_reaction_table_state, preview_reaction_table

REGION = CaptureRegion(100, 50, 1920, 1200)
CHI_IDS = ["chi_0_1_2", "chi_1_2_3", "chi_2_3_4"]


class FakeMouse:
    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []

    def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))


class PauseAfterFirstClickMouse(FakeMouse):
    """第一次點擊後把 controller 暫停，模擬「兩步驟做到一半被暫停」。"""

    controller = None

    def click(self, x: int, y: int) -> None:
        super().click(x, y)
        if len(self.clicks) == 1 and self.controller is not None:
            self.controller.pause()


def make_layout(disabled=("kong", "win")):
    names = ["chi", "pong", "kong", "win", "pass"]
    return {
        "dpr": 1.5,
        "inner": [1264, 700],
        "outer": [1280, 800],
        "buttons": [
            {"action": n, "enabled": n not in disabled, "x": 100 + i * 60, "y": 500, "w": 50, "h": 30}
            for i, n in enumerate(names)
        ],
        "choices": [
            {"id": cid, "x": 100 + i * 100, "y": 560, "w": 80, "h": 20}
            for i, cid in enumerate(CHI_IDS)
        ],
    }


def _mapper(disabled=("kong", "win")) -> ButtonMapper:
    layout = make_layout(disabled)
    mapper = ButtonMapper(frame_size=(1920, 1200))
    mapper.update(boxes_from_dom_buttons(layout), boxes_from_dom_choices(layout))
    return mapper


def _run(state, action_id, log_dir, game_id, mouse, *, mapper=None, foreground=None):
    with AppLogger(log_dir=str(log_dir), game_id=game_id) as logger:
        controller = AgentController(game_id=game_id, mouse=mouse, logger=logger)
        controller.start()
        if isinstance(mouse, PauseAfterFirstClickMouse):
            mouse.controller = controller
        try:
            return run_reaction_turn(
                state, SEAT, mapper or _mapper(), REGION, controller,
                game_id=game_id, ids=EventIds(), logger=logger,
                policy=ScriptedPolicy(action_id), foreground_check=foreground,
            )
        finally:
            controller.stop()


def _types(log_dir, game_id):
    lines = (Path(log_dir) / f"{game_id}.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["event_type"] for line in lines]


def _pass_only_state():
    state = make_reaction_table_state("t")
    state.last_discard = LastDiscard(player_id=3, tile_id=15)  # 手上沒有能吃碰 15 的牌
    return state


def test_chi_two_step_click(tmp_path):
    mouse = FakeMouse()
    result = _run(make_reaction_table_state("t"), "chi_1_2_3", tmp_path, "t_chi", mouse)

    assert result.success is True
    assert result.decision.action.id == "chi_1_2_3"
    assert result.plan.needs_choice is True
    assert mouse.clicks == [(299, 960), (472, 1043)]  # 先點「吃」，再點組合
    assert result.receipt.ui_action_executed is True
    assert result.receipt.state_verified is False
    assert _types(tmp_path, "t_chi") == [
        "game_started", "state_updated", "legal_actions_generated", "decision_made",
        "action_started", "action_completed", "game_stopped",
    ]


def test_pong_single_click(tmp_path):
    mouse = FakeMouse()
    result = _run(make_reaction_table_state("t"), "pong_2", tmp_path, "t_pong", mouse)

    assert result.success is True
    assert mouse.clicks == [(389, 960)]


def test_pass_only_is_skipped(tmp_path):
    mouse = FakeMouse()
    result = _run(_pass_only_state(), "pass", tmp_path, "t_skip", mouse)

    assert result.skipped is True
    assert result.receipt is None and result.error is None
    assert mouse.clicks == []
    types = _types(tmp_path, "t_skip")
    assert "reaction_skipped" in types
    assert "action_started" not in types and "action_failed" not in types


def test_pause_between_steps_requests_stop(tmp_path):
    mouse = PauseAfterFirstClickMouse()
    result = _run(make_reaction_table_state("t"), "chi_1_2_3", tmp_path, "t_pause", mouse)

    assert mouse.clicks == [(299, 960)]  # 第二次點擊被擋下
    assert result.success is False
    assert result.receipt.ui_action_executed is True
    assert result.receipt.error_code == "CONTROLLER_NOT_RUNNING"
    assert result.receipt.should_stop is True
    assert "action_failed" in _types(tmp_path, "t_pause")


def test_not_foreground_requests_stop(tmp_path):
    mouse = FakeMouse()
    result = _run(make_reaction_table_state("t"), "pong_2", tmp_path, "t_bg", mouse,
                  foreground=lambda: False)

    assert mouse.clicks == []
    assert result.error == "WINDOW_NOT_FOREGROUND"
    assert result.receipt.should_stop is True


def test_no_reaction_target(tmp_path):
    state = make_reaction_table_state("t")
    state.last_discard = None
    mouse = FakeMouse()
    result = _run(state, "pass", tmp_path, "t_none", mouse)

    assert result.error == "NO_REACTION_TARGET"
    assert result.receipt is None and mouse.clicks == []


def test_disabled_button_does_not_click(tmp_path):
    mouse = FakeMouse()
    result = _run(make_reaction_table_state("t"), "pong_2", tmp_path, "t_dis", mouse,
                  mapper=_mapper(disabled=("kong", "win", "pong")))

    assert mouse.clicks == []
    assert result.error == "BUTTON_DISABLED"
    assert result.receipt.success is False


def test_reaction_table_view():
    view = preview_reaction_table()

    assert view["buttons"] == {"chi": True, "pong": True, "kong": False, "win": False, "pass": True}
    assert [a["id"] for a in view["actions"]] == ["pong_2", *CHI_IDS, "pass"]
    assert view["last_discard"]["player_id"] == 3
    assert view["last_discard"]["tile"]["id"] == 2


def test_react_endpoint_roundtrip(tmp_path):
    app_module.LOG_DIR = str(tmp_path)
    app_module.reset_agent()

    assert app_module.get_reactions() == {"reactions": []}
    app_module.record_reaction({"kind": "button", "action": "chi"})
    app_module.record_reaction({"kind": "choice", "id": "chi_1_2_3"})
    assert app_module.get_reactions()["reactions"] == [
        {"kind": "button", "action": "chi", "id": None},
        {"kind": "choice", "action": None, "id": "chi_1_2_3"},
    ]

    assert app_module.get_table("reaction")["buttons"]["chi"] is True
    app_module.reset_agent()
    assert app_module.get_reactions() == {"reactions": []}


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        test_chi_two_step_click(base / "a")
        test_pong_single_click(base / "b")
        test_pass_only_is_skipped(base / "c")
        test_pause_between_steps_requests_stop(base / "d")
        test_not_foreground_requests_stop(base / "e")
        test_no_reaction_target(base / "f")
        test_disabled_button_does_not_click(base / "g")
        test_reaction_table_view()
        test_react_endpoint_roundtrip(base / "h")
    print("✅ test_reaction_plan：9 項測試全部通過")