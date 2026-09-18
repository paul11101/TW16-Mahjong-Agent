"""
logger.py

提供結構化 JSONL Logger。

每一行代表一個 Event，例如：

{"event_id":"evt_001","game_id":"game_001", ...}
{"event_id":"evt_002","game_id":"game_001", ...}
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .events import Event


class JsonlEventLogger:
    """
    將事件寫入 JSONL 檔案。

    預設格式：

        logs/<game_id>.jsonl

    使用方式：

        logger = JsonlEventLogger("logs")

        logger.log(event)

        logger.close()
    """

    def __init__(
        self,
        log_dir: str | Path = "logs",
        *,
        game_id: str | None = None,
        filename: str | None = None,
        encoding: str = "utf-8",
    ) -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.encoding = encoding
        self._file = None

        if filename is not None:
            self.file_path = self.log_dir / filename
        elif game_id is not None:
            self.file_path = self.log_dir / f"{game_id}.jsonl"
        else:
            self.file_path = self.log_dir / "system.jsonl"

        self._file = self.file_path.open(
            mode="a",
            encoding=self.encoding,
        )

    def log(self, event: Event) -> None:
        """
        寫入一個 Event。

        每次寫入後立即 flush，
        避免程式突然中斷時資料全部留在 buffer。
        """

        if self._file is None:
            raise RuntimeError("Logger is already closed.")

        data = event.model_dump(mode="json")

        json_line = json.dumps(
            data,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        self._file.write(json_line + "\n")
        self._file.flush()

    def log_many(self, events: list[Event]) -> None:
        """連續寫入多個事件。"""

        for event in events:
            self.log(event)

    def close(self) -> None:
        """關閉 log 檔案。"""

        if self._file is not None:
            self._file.close()
            self._file = None

    def __enter__(self) -> "JsonlEventLogger":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


class AppLogger:
    """
    同時提供：
    1. JSONL 結構化事件紀錄
    2. 一般 Python logging console 輸出

    JSONL 適合回放與分析。
    Console 適合開發時即時看狀態。
    """

    def __init__(
        self,
        log_dir: str | Path = "logs",
        *,
        game_id: str | None = None,
        filename: str | None = None,
        console_level: int = logging.INFO,
    ) -> None:
        self.event_logger = JsonlEventLogger(
            log_dir=log_dir,
            game_id=game_id,
            filename=filename,
        )

        self.console_logger = logging.getLogger(
            f"mahjong_agent.{game_id or 'system'}"
        )

        self.console_logger.setLevel(console_level)

        # 避免重複添加 Handler
        if not self.console_logger.handlers:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(console_level)

            formatter = logging.Formatter(
                fmt="%(asctime)s | %(levelname)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

            console_handler.setFormatter(formatter)
            self.console_logger.addHandler(console_handler)

    def log_event(
        self,
        event: Event,
        *,
        console_message: str | None = None,
        console_level: int = logging.INFO,
    ) -> None:
        """
        同時寫入 JSONL 與 console。
        """

        self.event_logger.log(event)

        if console_message is not None:
            self.console_logger.log(
                console_level,
                console_message,
            )

    def info(self, message: str) -> None:
        """輸出一般資訊。"""
        self.console_logger.info(message)

    def warning(self, message: str) -> None:
        """輸出警告。"""
        self.console_logger.warning(message)

    def error(self, message: str) -> None:
        """輸出錯誤。"""
        self.console_logger.error(message)

    def close(self) -> None:
        """關閉 logger。"""
        self.event_logger.close()

    def __enter__(self) -> "AppLogger":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()