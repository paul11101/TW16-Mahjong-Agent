"""整合端共用小工具（W7 整理）：p95、原子寫 JSON、等 controller 回到 RUNNING。"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Callable, Sequence


def p95(values: Sequence[float]) -> float | None:
    """最近排名法 p95；沒有資料回傳 None。"""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]


def atomic_write_json(path: str | Path, data: Any, *, indent: int = 2) -> Path:
    """先寫 .tmp 再替換，中途當機不會留下半個檔案。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8")
    tmp.replace(target)
    return target


def wait_until_running(
    controller: Any,
    *,
    poll_interval: float,
    pause_timeout: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> str | None:
    """回傳 None 代表可以繼續；否則回傳結束原因（stopped / not_started / pause_timeout）。"""
    waited = 0.0
    while True:
        if controller.is_stopped:
            return "stopped"
        if controller.is_running:
            return None
        if not controller.is_paused:
            return "not_started"
        if pause_timeout is not None and waited >= pause_timeout:
            controller.stop()
            return "pause_timeout"
        sleep(poll_interval)
        waited += poll_interval