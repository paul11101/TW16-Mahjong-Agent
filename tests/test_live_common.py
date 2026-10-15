"""實機 runner 共用流程（live_common）測試：假視窗、假擷取、本機假伺服器，不需要瀏覽器。

執行方式（專案根目錄）：
    python -m tests.test_live_common
或
    python -m pytest tests/test_live_common.py -v
"""

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np

from src.control.action_executor import RetryPolicy
from src.control.capture import ScreenCapture
from src.control.controller import AgentController
from src.control.verifier import ActionVerifier
from src.control.window import DEFAULT_TITLE, WindowInfo, WindowLocator
from test_interface import live_common as lc
from tests._runner import run_module


def _parse(argv):
    parser = argparse.ArgumentParser()
    lc.add_common_args(parser)
    lc.add_action_args(parser)
    return parser.parse_args(argv)


def _fake_locator(windows, focus_calls=None):
    def focus(hwnd):
        if focus_calls is not None:
            focus_calls.append(hwnd)
        return True

    return WindowLocator(DEFAULT_TITLE, list_fn=lambda: windows, focus_fn=focus)


def _grab(region):
    return np.zeros((region.height, region.width, 4), dtype=np.uint8)


def test_arg_defaults():
    args = _parse([])

    assert args.title == DEFAULT_TITLE
    assert args.url == "http://127.0.0.1:8000"
    assert args.delay == 0.0 and args.no_focus is False
    assert args.log_dir == "logs" and args.no_verify is False
    assert args.verify_timeout == 1.0 and args.min_change == 0.005
    assert args.max_retries == 1 and args.grace == 0.5
    assert args.full_verify is False  # 預設用 ROI 驗證，--full-verify 才改整窗


def test_make_verifier_and_retry():
    controller = AgentController(capturer=ScreenCapture(grab_fn=lambda r: np.zeros((10, 10, 4), dtype=np.uint8)))

    assert lc.make_verifier_and_retry(_parse(["--no-verify"]), controller) == (None, None)

    verifier, retry = lc.make_verifier_and_retry(
        _parse(["--verify-timeout", "2.5", "--min-change", "0.01", "--max-retries", "0", "--grace", "0.2"]),
        controller,
    )
    assert isinstance(verifier, ActionVerifier) and isinstance(retry, RetryPolicy)
    assert verifier.timeout == 2.5 and verifier.min_change_ratio == 0.01
    assert retry.max_retries == 0 and retry.grace_wait == 0.2


def test_roi_verify_is_default():
    windows = [WindowInfo(hwnd=7, title=DEFAULT_TITLE, left=100, top=50, width=320, height=240)]
    locator = _fake_locator(windows)
    session = lc.open_session(_parse(["--no-focus"]), locator=locator, grab_fn=_grab)
    controller = AgentController(capturer=session.capturer)
    controller.start()

    # 沒有 session：退回整窗模式
    no_session, _ = lc.make_verifier_and_retry(_parse([]), controller)
    assert no_session.roi_mode is False

    # --full-verify：整窗模式
    full, _ = lc.make_verifier_and_retry(_parse(["--full-verify"]), controller, session)
    assert full.roi_mode is False

    # 預設（以及舊參數 --roi-verify）：ROI 模式
    for argv in ([], ["--roi-verify"]):
        verifier, _ = lc.make_verifier_and_retry(_parse(argv), controller, session)
        assert verifier.roi_mode is True
        assert verifier.frame_size == (320, 240)
        assert verifier.region_guard() is True  # 視窗位置沒變
        assert verifier.prepare((100, 100)) is True  # 真的走 controller.capture_roi

    # 視窗被移動後，region_guard 要回報 False，prepare 要拒絕
    windows[0] = WindowInfo(hwnd=7, title=DEFAULT_TITLE, left=0, top=0, width=320, height=240)
    assert verifier.region_guard() is False
    assert verifier.prepare((100, 100)) is False


def test_calibration_origin():
    frame = np.zeros((1200, 1920, 3), dtype=np.uint8)
    assert lc.calibration_origin(frame, {"inner": [1264, 700], "outer": [1280, 800]}) is None

    frame[91:107, 37:53] = (255, 0, 255)
    assert lc.calibration_origin(frame) == (37, 91)


def test_open_session_finds_window_and_captures():
    focus_calls = []
    windows = [WindowInfo(hwnd=42, title=DEFAULT_TITLE, left=100, top=50, width=320, height=240)]

    session = lc.open_session(_parse([]), locator=_fake_locator(windows, focus_calls), grab_fn=_grab)

    assert session is not None
    assert (session.width, session.height) == (320, 240)
    assert (session.region.left, session.region.top) == (100, 50)
    assert focus_calls == [42]  # 預設會自動拉到前景


def test_open_session_no_focus_and_window_missing():
    focus_calls = []
    windows = [WindowInfo(hwnd=1, title=DEFAULT_TITLE, left=0, top=0, width=64, height=48)]

    session = lc.open_session(
        _parse(["--no-focus"]), locator=_fake_locator(windows, focus_calls), grab_fn=_grab
    )
    assert session is not None and focus_calls == []

    assert lc.open_session(_parse([]), locator=_fake_locator([]), grab_fn=_grab) is None


class _Handler(BaseHTTPRequestHandler):
    routes = {
        "/api/layout": {"dpr": 1.0, "tiles": []},
        "/api/clicks": {"clicks": [{"tile": 1, "seat": 0}]},
        "/api/reactions": {"reactions": [{"kind": "button", "action": "pass", "id": None}]},
    }

    def do_GET(self):
        body = self.routes.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        data = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # 不要把每個請求印到畫面
        pass


def test_fetch_helpers_against_local_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"

        assert lc.fetch_layout(url) == {"dpr": 1.0, "tiles": []}
        assert lc.fetch_clicks(url) == [{"tile": 1, "seat": 0}]
        assert lc.fetch_reactions(url) == [{"kind": "button", "action": "pass", "id": None}]
        assert lc.fetch_layout(url + "/") == {"dpr": 1.0, "tiles": []}  # 結尾斜線也可以
    finally:
        server.shutdown()
        server.server_close()


def test_check_mapping_still_exports_fetch_layout():
    from test_interface import check_mapping

    assert check_mapping.fetch_layout is lc.fetch_layout


if __name__ == "__main__":
    run_module(globals(), "test_live_common")