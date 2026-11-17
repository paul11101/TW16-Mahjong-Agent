"""暫停診斷文字（點擊數對照）測試。

執行方式（專案根目錄）：
    python -m tests.test_pause_diagnosis
或
    python -m pytest tests/test_pause_diagnosis.py -v
"""

from test_interface.live_game import pause_diagnosis
from tests._runner import run_module

TRUTH = {"phase": "agent_turn", "is_over": False, "wall_count": 80, "agent_discards": 3}


def _text(**kw):
    base = dict(error="NOT_ADVANCED", mouse_clicks=4, page_discards=4, page_reactions=0, truth=TRUTH)
    base.update(kw)
    return "\n".join(pause_diagnosis(base.pop("error"), **base))


def test_page_received_but_table_not_advanced():
    text = _text()
    assert "網頁有收到點擊但牌局沒前進" in text and "Agent 已出牌 3 張" in text


def test_click_did_not_reach_page():
    assert "沒送到網頁" in _text(page_discards=3)


def test_page_received_more_than_mouse():
    assert "比滑鼠多" in _text(page_discards=5)


def test_page_unreachable_and_no_truth():
    text = _text(page_discards=None, page_reactions=None, truth=None)
    assert "讀不到測試網頁" in text and "評測器：" not in text


def test_other_error_has_no_advance_hint():
    assert "牌局沒前進" not in _text(error="ACTION_TIMEOUT")


if __name__ == "__main__":
    run_module(globals(), "test_pause_diagnosis")