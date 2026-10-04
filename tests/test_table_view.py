"""W3 D1 測試牌桌顯示：view model 與頁面的最小測試。

執行方式（專案根目錄）：
    python -m tests.test_table_view
或
    python -m pytest tests/test_table_view.py -v
"""

import json

from test_interface import app as app_module
from test_interface.agent_runner import SEAT
from test_interface.table_view import (
    build_table_view,
    make_demo_table_state,
    preview_table,
    tile_label,
)


def test_tile_label_includes_flowers():
    assert tile_label(0) == "一萬"
    assert tile_label(27) == "東"
    assert tile_label(34) == "春"
    assert tile_label(41) == "竹"


def test_four_players_and_positions():
    view = preview_table()

    assert [p["seat_id"] for p in view["players"]] == [0, 1, 2, 3]
    # 自己在下方，座位 +1 在右側
    assert [p["position"] for p in view["players"]] == ["bottom", "right", "top", "left"]
    assert view["wall_count"] == 80
    assert view["round_wind"] == "東"
    assert [p["is_current"] for p in view["players"]] == [True, False, False, False]
    assert [p["is_dealer"] for p in view["players"]] == [True, False, False, False]


def test_only_self_hand_is_visible():
    state = make_demo_table_state()
    view = build_table_view(state, SEAT)

    for p in view["players"]:
        expected_count = len(state.players[p["seat_id"]].hand)
        assert p["hand_count"] == expected_count
        if p["is_self"]:
            ids = [t["id"] for t in p["hand"]]
            assert len(ids) == 17
            assert ids == sorted(ids)
        else:
            # 其他玩家的牌面不能出現在輸出中
            assert p["hand"] is None


def test_melds_flowers_and_discards_are_shown():
    players = {p["seat_id"]: p for p in preview_table()["players"]}

    assert players[1]["melds"][0]["label"] == "碰"
    assert [t["id"] for t in players[1]["melds"][0]["tiles"]] == [27, 27, 27]
    assert players[3]["melds"][0]["label"] == "吃"
    assert [t["name"] for t in players[3]["flowers"]] == ["春", "梅"]
    assert len(players[2]["discards"]) == 7


def test_buttons_and_selected_action():
    view = preview_table()

    # 自己摸牌後的回合：只有打牌，沒有吃碰槓胡過
    assert view["buttons"] == {
        "chi": False,
        "pong": False,
        "kong": False,
        "win": False,
        "pass": False,
    }
    selected = [a for a in view["actions"] if a["selected"]]
    assert len(selected) == 1
    assert selected[0]["id"] == "discard_0"
    assert view["decision"]["action_id"] == "discard_0"
    assert view["decision"]["score"] == 0.0


def test_other_seat_perspective():
    state = make_demo_table_state()
    view = build_table_view(state, 2)

    assert [p["position"] for p in view["players"]] == ["top", "left", "bottom", "right"]
    assert view["players"][2]["hand"] is not None
    assert view["players"][0]["hand"] is None
    # 沒給合法動作時，按鈕全部不可用
    assert not any(view["buttons"].values())
    assert view["decision"] is None


def test_view_is_json_serializable():
    json.dumps(preview_table(), ensure_ascii=False)


def test_api_table_and_index_page():
    view = app_module.get_table()
    assert len(view["players"]) == 4

    html = app_module.index()
    assert 'id="table"' in html
    assert "/api/table" in html


if __name__ == "__main__":
    test_tile_label_includes_flowers()
    test_four_players_and_positions()
    test_only_self_hand_is_visible()
    test_melds_flowers_and_discards_are_shown()
    test_buttons_and_selected_action()
    test_other_seat_perspective()
    test_view_is_json_serializable()
    test_api_table_and_index_page()
    print("✅ test_table_view：8 項測試全部通過")