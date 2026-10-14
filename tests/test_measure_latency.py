"""延遲量測腳本的統計函式測試（不需要視窗與實機）。

執行方式（專案根目錄）：
    python -m tests.test_measure_latency
或
    python -m pytest tests/test_measure_latency.py -v
"""

import pytest

from src.control.capture import CaptureRegion
from test_interface.measure_latency import _center_roi, stats_ms, time_ms
from tests._runner import run_module


def test_stats_ms():
    s = stats_ms([float(i) for i in range(1, 101)])  # 1..100

    assert s["n"] == 100
    assert s["median"] == 50.5 and s["mean"] == 50.5
    assert s["p95"] == 95.0
    assert s["min"] == 1.0 and s["max"] == 100.0

    single = stats_ms([7.0])
    assert single["p95"] == 7.0 and single["median"] == 7.0

    with pytest.raises(ValueError):
        stats_ms([])


def test_time_ms_runs_warmup_and_samples():
    calls = []
    samples = time_ms(lambda: calls.append(1), 5, warmup=2)

    assert len(samples) == 5 and all(s >= 0 for s in samples)
    assert len(calls) == 7  # 暖機 2 次 + 量測 5 次


def test_center_roi():
    roi = _center_roi(CaptureRegion(100, 50, 1000, 800))
    assert (roi.width, roi.height) == (300, 300)
    assert (roi.left, roi.top) == (100 + 350, 50 + 250)

    small = _center_roi(CaptureRegion(10, 20, 200, 100))  # 視窗比 300 小，就用整個視窗
    assert (small.left, small.top, small.width, small.height) == (10, 20, 200, 100)


if __name__ == "__main__":
    run_module(globals(), "test_measure_latency")