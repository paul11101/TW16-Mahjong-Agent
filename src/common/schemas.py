"""
schemas.py

定義台灣16張麻將 Agent 各模組之間共用的資料格式。

資料流程：
Observation
    -> GameState
    -> LegalActions
    -> Decision
    -> ActionReceipt
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    """取得目前 UTC 時間。"""
    return datetime.now(timezone.utc)


class ActionType(str, Enum):
    """Agent 可能執行的動作類型。"""

    DISCARD = "discard"
    CHI = "chi"
    PENG = "peng"
    GANG = "gang"
    HU = "hu"
    PASS = "pass"
    WAIT = "wait"
    START_GAME = "start_game"
    STOP_GAME = "stop_game"


class GamePhase(str, Enum):
    """目前牌局階段。"""

    WAITING = "waiting"
    DRAWING = "drawing"
    PLAYING = "playing"
    CLAIMING = "claiming"
    FINISHED = "finished"
    ERROR = "error"


class SourceType(str, Enum):
    """資料來源。"""

    VISION = "vision"
    RULES = "rules"
    STRATEGY = "strategy"
    INTEGRATION = "integration"
    SYSTEM = "system"


class BaseSchema(BaseModel):
    """所有共用資料模型的基底類別。"""

    model_config = ConfigDict(
        use_enum_values=True,
        validate_assignment=True,
        extra="forbid",
    )


class Tile(BaseSchema):
    """
    一張麻將牌。

    tile_id:
        系統內部使用的唯一牌編號，例如 1~42 或其他自訂編碼。

    name:
        牌的文字名稱，例如「一萬」、「東」、「紅中」。

    code:
        可選的標準化代碼，例如 1m、5p、E。
    """

    tile_id: int = Field(ge=0)
    name: str
    code: str | None = None


class Observation(BaseSchema):
    """
    視覺辨識模組輸出的結果。

    這一層只描述「畫面看到了什麼」，
    不負責判斷規則是否合法。
    """

    observation_id: str
    game_id: str
    event_id: str

    timestamp: datetime = Field(default_factory=utc_now)

    source: SourceType = SourceType.VISION

    screenshot_path: str | None = None

    # 辨識到的手牌、桌面牌、吃碰槓胡按鈕等資訊
    visible_tiles: list[Tile] = Field(default_factory=list)

    # 原始辨識結果，方便除錯與日後重新處理
    raw_data: dict[str, Any] = Field(default_factory=dict)

    # 整體辨識信心度，範圍 0~1
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # 畫面是否足夠穩定，可以交給下一個模組
    is_stable: bool = False

    # 目前畫面是否可能正在動畫或轉場
    is_animating: bool = False

    # 辨識錯誤訊息
    errors: list[str] = Field(default_factory=list)


class PlayerState(BaseSchema):
    """單一玩家的牌局狀態。"""

    player_id: int = Field(ge=0)

    hand_tiles: list[Tile] = Field(default_factory=list)

    discarded_tiles: list[Tile] = Field(default_factory=list)

    exposed_melds: list[list[Tile]] = Field(default_factory=list)

    score: int = 0


class GameState(BaseSchema):
    """
    規則模組整理後的完整牌局狀態。

    這一層是「系統理解的牌局」，
    不只是畫面辨識結果。
    """

    game_id: str
    event_id: str

    timestamp: datetime = Field(default_factory=utc_now)

    rule_version: str = "taiwan_16_tiles_v1"

    phase: GamePhase = GamePhase.WAITING

    current_player_id: int = Field(default=0, ge=0)

    self_player_id: int = Field(default=0, ge=0)

    players: list[PlayerState] = Field(default_factory=list)

    # 輪到自己時摸到的牌，若沒有則為 None
    drawn_tile: Tile | None = None

    # 桌面目前最後一張打出的牌
    last_discarded_tile: Tile | None = None

    # 是否輪到 Agent 行動
    is_our_turn: bool = False

    # 是否正在等待其他玩家動作
    waiting_for_opponent: bool = False

    # 其他規則狀態
    extra_state: dict[str, Any] = Field(default_factory=dict)

    # 狀態是否通過基本一致性檢查
    is_valid: bool = True

    validation_errors: list[str] = Field(default_factory=list)


class LegalAction(BaseSchema):
    """一個合法候選動作。"""

    action_id: str

    action_type: ActionType

    # 例如打出哪張牌、吃哪三張牌等
    tile_ids: list[int] = Field(default_factory=list)

    # 動作所需的額外參數
    parameters: dict[str, Any] = Field(default_factory=dict)

    # 規則模組提供的說明
    reason: str | None = None


class LegalActions(BaseSchema):
    """
    規則模組輸出的合法動作集合。
    """

    game_id: str
    event_id: str

    timestamp: datetime = Field(default_factory=utc_now)

    state_event_id: str

    actions: list[LegalAction] = Field(default_factory=list)

    # 產生合法動作時使用的規則版本
    rule_version: str = "taiwan_16_tiles_v1"

    # 是否成功產生
    is_valid: bool = True

    errors: list[str] = Field(default_factory=list)


class CandidateScore(BaseSchema):
    """策略模型對單一候選動作的評分。"""

    action_id: str

    score: float

    reason: str | None = None


class Decision(BaseSchema):
    """
    策略模組的決策結果。

    策略模組不應直接操作滑鼠，
    只負責選擇要做什麼。
    """

    decision_id: str
    game_id: str
    event_id: str

    timestamp: datetime = Field(default_factory=utc_now)

    legal_actions_event_id: str

    selected_action: LegalAction | None = None

    candidate_scores: list[CandidateScore] = Field(default_factory=list)

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    reason: str | None = None

    strategy_version: str = "rule_based_v1"

    # 是否允許整合模組執行此決策
    approved_for_execution: bool = False

    # 若不執行，記錄原因
    rejection_reason: str | None = None


class ActionReceipt(BaseSchema):
    """
    自動操作模組執行後的結果。

    這個模型用來回答：
    - 有沒有真的點擊？
    - 點擊是否成功？
    - 畫面有沒有正確變化？
    - 是否需要停止或重試？
    """

    receipt_id: str
    game_id: str
    event_id: str

    timestamp: datetime = Field(default_factory=utc_now)

    decision_id: str

    action: LegalAction | None = None

    started_at: datetime | None = None
    finished_at: datetime | None = None

    success: bool = False

    # UI 操作是否有實際執行
    ui_action_executed: bool = False

    # 操作後是否重新辨識並確認狀態改變
    state_verified: bool = False

    # 執行耗時，單位毫秒
    latency_ms: float | None = Field(default=None, ge=0.0)

    retry_count: int = Field(default=0, ge=0)

    error_code: str | None = None
    error_message: str | None = None

    # 操作後重新觀察得到的 event_id
    verification_observation_event_id: str | None = None

    # 是否應該停止整個 Agent
    should_stop: bool = False