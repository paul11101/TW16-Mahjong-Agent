"""測試網頁不能被自動連點選取文字或拖曳（會讓 click 沒觸發，整局卡在 NOT_ADVANCED）。

執行方式（專案根目錄）：
    python -m tests.test_page_no_select
或
    python -m pytest tests/test_page_no_select.py -v
"""

from test_interface.table_page import INDEX_HTML
from tests._runner import run_module


def test_text_selection_is_disabled_except_system_message():
    assert "body { user-select: none;" in INDEX_HTML
    assert "pre { user-select: text;" in INDEX_HTML


def test_dragging_tiles_is_blocked():
    assert "-webkit-user-drag: none" in INDEX_HTML
    assert "addEventListener('dragstart'" in INDEX_HTML


if __name__ == "__main__":
    run_module(globals(), "test_page_no_select")