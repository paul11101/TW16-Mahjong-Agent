"""Agent 控制骨架：負責執行狀態與 pause/stop 安全控制。"""

from __future__ import annotations

from enum import Enum

from src.common.events import EventSource, EventType, create_event
from src.common.logger import AppLogger
from src.control.mouse import MouseController


class ControlState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


class AgentController:
    """W1 最小控制器。

    目前只提供：
    - start()
    - pause()
    - resume()
    - stop()
    - click()

    真正的「辨識 -> 決策 -> 點擊 -> 驗證」流程留到後續週次。
    """

    def __init__(
        self,
        *,
        game_id: str = "test_game",
        mouse: MouseController | None = None,
        logger: AppLogger | None = None,
    ) -> None:
        self.game_id = game_id
        self.mouse = mouse or MouseController()
        self.logger = logger
        self.state = ControlState.IDLE
        self._event_counter = 0

    @property
    def is_running(self) -> bool:
        return self.state == ControlState.RUNNING

    @property
    def is_paused(self) -> bool:
        return self.state == ControlState.PAUSED

    @property
    def is_stopped(self) -> bool:
        return self.state == ControlState.STOPPED

    def _next_event_id(self, prefix: str) -> str:
        self._event_counter += 1
        return f"{prefix}_{self._event_counter:04d}"

    def _log_state_event(self, event_type: EventType, message: str) -> None:
        if self.logger is None:
            return

        event = create_event(
            event_id=self._next_event_id("evt"),
            game_id=self.game_id,
            event_type=event_type,
            source=EventSource.INTEGRATION,
            payload={"control_state": self.state.value},
        )
        self.logger.log_event(event, console_message=message)

    def start(self) -> None:
        """啟動控制器；STOPPED 後不可直接重新啟動。"""
        if self.state == ControlState.STOPPED:
            raise RuntimeError("Controller is stopped; create a new controller to restart.")

        self.state = ControlState.RUNNING
        self._log_state_event(EventType.GAME_STARTED, "Agent controller started.")

    def pause(self) -> None:
        """暫停後禁止新的 UI 點擊。"""
        if self.state != ControlState.RUNNING:
            return

        self.state = ControlState.PAUSED
        self._log_state_event(EventType.GAME_PAUSED, "Agent controller paused.")

    def resume(self) -> None:
        """從 PAUSED 回到 RUNNING。"""
        if self.state != ControlState.PAUSED:
            return

        self.state = ControlState.RUNNING
        self._log_state_event(EventType.GAME_RESUMED, "Agent controller resumed.")

    def stop(self) -> None:
        """立即進入 STOPPED；後續 click() 一律拒絕。"""
        if self.state == ControlState.STOPPED:
            return

        self.state = ControlState.STOPPED
        self._log_state_event(EventType.GAME_STOPPED, "Agent controller stopped.")

    def click(self, x: int, y: int) -> bool:
        """執行一次滑鼠點擊。

        W1 只做安全閘門，不處理牌面座標映射或 ActionReceipt。
        """
        if not self.is_running:
            return False

        self.mouse.click(x, y)
        return True
