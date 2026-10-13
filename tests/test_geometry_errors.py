"""整理（geometry / errors）的測試：座標工具行為、舊 import 路徑仍可用。

執行方式（專案根目錄）：
    python -m tests.test_geometry_errors
或
    python -m pytest tests/test_geometry_errors.py -v
"""

import dataclasses

import pytest

from src.control import action_executor, discard_executor, errors, pipeline, verifier
from src.control import button_mapper, tile_mapper
from src.control.geometry import (
    CenterMixin,
    default_viewport_offset,
    dom_origin,
    dom_rect_to_frame,
    ensure_inside,
)
from tests._runner import run_module


def test_center_mixin_keeps_positional_order():
    button = button_mapper.ButtonBox("chi", 162, 888, 75, 45)
    choice = button_mapper.ChoiceBox("chi_1_2_3", 312, 978, 120, 30)
    tile = tile_mapper.TileBox(5, 10, 20, 30, 40)

    assert isinstance(button, CenterMixin)
    assert button.center == (199, 910)
    assert choice.center == (372, 993)
    assert tile.center == (25, 40)
    # 欄位順序沒被 mixin 破壞
    assert [f.name for f in dataclasses.fields(button)][:5] == ["action", "x", "y", "w", "h"]


def test_ensure_inside():
    class Boom(Exception):
        pass

    ensure_inside(None, (999, 999), "x", Boom)  # 沒有 frame_size 不檢查
    ensure_inside((100, 100), (99, 0), "x", Boom)
    with pytest.raises(Boom):
        ensure_inside((100, 100), (100, 50), "x", Boom)
    with pytest.raises(Boom):
        ensure_inside((100, 100), (-1, 50), "x", Boom)


def test_dom_helpers():
    layout = {"dpr": 1.5, "inner": [1264, 700], "outer": [1280, 800]}

    assert default_viewport_offset(layout) == (8.0, 92.0)
    assert default_viewport_offset({}) == (0.0, 0.0)

    dpr, ox, oy = dom_origin(layout)
    assert (dpr, ox, oy) == (1.5, 12.0, 138.0)
    assert dom_origin(layout, origin_px=(37, 91)) == (1.5, 37, 91)
    assert dom_origin(layout, offset=(0, 0), scale=1.0) == (1.0, 0.0, 0.0)

    # x: 12 + 100*1.5 = 162  y: 138 + 600*1.5 = 1038
    assert dom_rect_to_frame({"x": 100, "y": 600, "w": 26, "h": 40}, dpr, ox, oy) == (162, 1038, 39, 60)


def test_old_import_paths_still_work():
    # tile_mapper 仍然匯出 Point / default_viewport_offset（check_mapping 等舊程式在用）
    assert tile_mapper.default_viewport_offset is default_viewport_offset
    assert tile_mapper.Point is not None

    # 同一個 ERR_* 從所有舊路徑拿到的都是同一個值
    for name in (
        "ERR_ACTION_TIMEOUT", "ERR_ACTION_NOT_STABLE", "ERR_FRAME_SIZE_CHANGED", "ERR_CAPTURE_FAILED",
    ):
        assert getattr(verifier, name) == getattr(errors, name)
        assert getattr(action_executor, name) == getattr(errors, name)

    for name in (
        "ERR_UNSUPPORTED_ACTION", "ERR_TILE_NOT_FOUND", "ERR_TILE_OUT_OF_FRAME",
        "ERR_BUTTON_NOT_FOUND", "ERR_BUTTON_DISABLED", "ERR_BUTTON_OUT_OF_FRAME",
        "ERR_CHOICE_NOT_FOUND", "ERR_MAPPING", "ERR_WINDOW_NOT_FOREGROUND",
        "ERR_CONTROLLER_NOT_RUNNING",
    ):
        assert getattr(action_executor, name) == getattr(errors, name)
        assert getattr(discard_executor, name) == getattr(errors, name)

    assert pipeline.ERR_NO_LEGAL_ACTIONS == errors.ERR_NO_LEGAL_ACTIONS == "NO_LEGAL_ACTIONS"
    assert pipeline.ERR_NO_REACTION_TARGET == errors.ERR_NO_REACTION_TARGET == "NO_REACTION_TARGET"


def test_error_codes_are_unique_and_match_notes():
    codes = {n: v for n, v in vars(errors).items() if n.startswith("ERR_")}

    assert len(set(codes.values())) == len(codes)  # 沒有兩個常數撞到同一個字串
    assert codes["ERR_MAPPING"] == "TILE_MAPPING_ERROR"
    assert set(errors.STOP_ON_VERIFY_ERRORS) == {errors.ERR_FRAME_SIZE_CHANGED, errors.ERR_CAPTURE_FAILED}


if __name__ == "__main__":
    run_module(globals(), "test_geometry_errors")