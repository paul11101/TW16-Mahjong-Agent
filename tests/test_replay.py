"""W5 D4 事件回放骨架測試：用真的 pipeline 產生 JSONL，再讀回來檢查／統計／回放。

執行方式（專案根目錄）：
    python -m tests.test_replay
或
    python -m pytest tests/test_replay.py -v
"""

import pytest

from src.common.logger import AppLogger
from src.control.capture import CaptureRegion
from src.control.controller import AgentController
from src.control.pipeline import EventIds, run_discard_turn
from src.control.replay import (
    EventReplayer,
    ReplayError,
    check_order,
    load_events,
    main,
    split_turns,
    summarize,
)
from test_interface.agent_runner import SEAT, make_fake_game_state
from test_interface.fakes import FakeMouse
from tests._runner import run_module
from tests.helpers import make_hand_mapper

REGION = CaptureRegion(100, 50, 1920, 1200)


def make_log(tmp_path, game_id="t_replay"):
    """第 1 回合成功；第 2 回合畫面缺牌（TILE_NOT_FOUND，沒有點擊）。"""
    state = make_fake_game_state(game_id)
    hand = state.players[SEAT].hand

    with AppLogger(log_dir=str(tmp_path), game_id=game_id) as logger:
        controller = AgentController(game_id=game_id, mouse=FakeMouse(), logger=logger)
        controller.start()
        ids = EventIds()
        try:
            run_discard_turn(state, SEAT, make_hand_mapper(hand), REGION, controller,
                             game_id=game_id, ids=ids, logger=logger)
            run_discard_turn(state, SEAT, make_hand_mapper([5, 6, 7]), REGION, controller,
                             game_id=game_id, ids=ids, logger=logger)
        finally:
            controller.stop()

    return tmp_path / f"{game_id}.jsonl"


def ev(event_id, event_type, second, parent=None, payload=None):
    return {
        "event_id": event_id,
        "event_type": event_type,
        "timestamp": f"2026-10-17T00:00:{second:02d}+00:00",
        "parent_event_id": parent,
        "payload": payload or {},
    }


def test_load_and_check_real_log(tmp_path):
    events = load_events(make_log(tmp_path))

    assert len(events) == 12
    assert events[0]["event_type"] == "game_started"
    assert events[-1]["event_type"] == "game_stopped"
    assert check_order(events) == []


def test_split_turns(tmp_path):
    turns = split_turns(load_events(make_log(tmp_path)))

    assert len(turns) == 2
    assert turns[0][0]["event_type"] == "game_started"
    assert turns[0][-1]["event_type"] == "action_completed"
    assert turns[1][-1]["event_type"] == "game_stopped"


def test_summarize_real_log(tmp_path):
    summary = summarize(load_events(make_log(tmp_path)))

    assert summary.total_events == 12 and summary.turns == 2
    assert summary.actions_completed == 1 and summary.actions_failed == 1
    assert summary.ui_actions == 1 and summary.ui_success == 1  # 缺牌那次沒有點擊，不進分母
    assert summary.ui_success_rate == 1.0
    assert summary.error_codes == {"TILE_NOT_FOUND": 1}
    assert summary.stops == 1 and summary.retries == 0
    assert summary.latency_p95_ms is not None


def test_summarize_counts_pause_resume_mismatch():
    events = [
        ev("a1", "game_started", 0),
        ev("a2", "state_mismatch", 1),
        ev("a3", "game_paused", 2),
        ev("a4", "game_resumed", 3),
        ev("a5", "action_failed", 4, payload={
            "ui_action_executed": True, "success": False, "error_code": "ACTION_TIMEOUT",
            "retry_count": 1, "latency_ms": 900.0,
        }),
    ]
    summary = summarize(events)

    assert (summary.mismatches, summary.pauses, summary.resumes) == (1, 1, 1)
    assert summary.ui_actions == 1 and summary.ui_success == 0 and summary.ui_success_rate == 0.0
    assert summary.retries == 1 and summary.latency_p95_ms == 900.0


def test_check_order_finds_problems():
    events = [
        ev("a1", "game_started", 5),
        ev("a1", "state_updated", 6),  # 重複 id
        ev("a3", "decision_made", 4, parent="zzz"),  # 時間倒退、parent 不存在
    ]
    problems = check_order(events)

    assert any("重複" in p for p in problems)
    assert any("時間倒退" in p for p in problems)
    assert any("parent_event_id" in p for p in problems)


def test_load_events_strict_and_lenient(tmp_path):
    path = tmp_path / "bad.jsonl"
    good = '{"event_id":"a","event_type":"game_started"}'
    path.write_text(good + "\n{壞掉的一行\n\n" + good.replace('"a"', '"b"') + "\n", encoding="utf-8")

    with pytest.raises(ReplayError):
        load_events(path)
    assert [e["event_id"] for e in load_events(path, strict=False)] == ["a", "b"]


def test_replayer_step_seek_play():
    events = [ev(f"e{i}", t, i) for i, t in enumerate(["game_started", "state_updated", "decision_made", "game_stopped"])]
    replayer = EventReplayer(events)

    assert len(replayer) == 4 and replayer.position == 0 and not replayer.done
    assert replayer.step()["event_id"] == "e0"

    seen = []
    assert replayer.play(seen.append, until_type="decision_made") == 2
    assert [e["event_id"] for e in seen] == ["e1", "e2"]

    assert replayer.play(seen.append) == 1 and replayer.done
    assert replayer.step() is None

    replayer.seek(2)
    assert replayer.step()["event_id"] == "e2"
    replayer.reset()
    assert replayer.position == 0
    with pytest.raises(IndexError):
        replayer.seek(9)


def test_cli_main_returns_zero_for_clean_log(tmp_path):
    path = make_log(tmp_path)

    assert main([str(path)]) == 0
    assert main([str(path), "--events", "--turns"]) == 0


def test_cli_main_returns_one_for_bad_order(tmp_path):
    path = tmp_path / "dup.jsonl"
    line = '{"event_id":"a","event_type":"game_started","timestamp":"2026-10-17T00:00:00+00:00"}\n'
    path.write_text(line * 2, encoding="utf-8")

    assert main([str(path)]) == 1


if __name__ == "__main__":
    run_module(globals(), "test_replay")