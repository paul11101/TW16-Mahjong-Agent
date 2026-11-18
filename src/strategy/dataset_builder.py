import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .action_mask import action_to_index, build_action_mask
from .encoder import encode_observation
from .interfaces import Decision, LegalAction, Observation
from .public_features import extract_public_features
from .training_sample import TrainingSample

# 保留策略做決定時的牌面、合法動作與選擇結果
@dataclass(frozen=True)
class DecisionRecord:
    game_id: str
    decision_id: str
    observation: Observation
    legal_actions: tuple[LegalAction, ...]
    decision: Decision
    strategy_version: str
    rule_version: str
    wall_seed: int | None = None

    def __post_init__(self):
        # 轉成 tuple，避免外部修改原清單後連帶改變決策紀錄
        object.__setattr__(self, "legal_actions", tuple(self.legal_actions))


def record_to_sample(record: DecisionRecord) -> TrainingSample:
    if not isinstance(record, DecisionRecord):
        raise TypeError("record must be a DecisionRecord")

    if not isinstance(record.observation, Observation) or not isinstance(record.decision, Decision):
        raise TypeError("record must contain Strategy Observation and Decision")

    actions = record.legal_actions
    if not actions or any(not isinstance(action, LegalAction) for action in actions):
        raise ValueError("legal_actions must contain Strategy LegalAction objects")

    if len({action.id for action in actions}) != len(actions):
        raise ValueError("action ids must be unique")

    # 比對完整動作，避免把 ID 相同但內容不同的動作當成訓練標籤
    if record.decision.action not in actions:
        raise ValueError("decision must select an action from legal_actions")

    # 每個候選動作都要對應不同索引，動作遮罩才能區分它們
    indices = tuple(action_to_index(action) for action in actions)
    if len(set(indices)) != len(indices):
        raise ValueError("action indices must be unique within a decision")

    # 沿用公開資訊的檢查，先確認副露、花牌與剩餘牌數等資料有效
    extract_public_features(record.observation)
    # 用當下的牌面作為輸入，策略選中動作的索引作為標籤
    return TrainingSample(
        game_id=record.game_id,
        decision_id=record.decision_id,
        strategy_version=record.strategy_version,
        rule_version=record.rule_version,
        features=encode_observation(record.observation),
        action_mask=build_action_mask(actions),
        action_index=action_to_index(record.decision.action),
        wall_seed=record.wall_seed,
    )

def write_dataset(records: Iterable[DecisionRecord], output: str | Path) -> int:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    # 每筆樣本寫成一行 JSON；檔案已存在時會拒絕覆寫
    stream = output.open("x", encoding="utf-8", newline="\n")
    count, seen = 0, set()
    try:
        with stream:
            for record in records:
                sample = record_to_sample(record)
                # 同一局內的決策編號必須唯一，不同局可以使用相同編號
                key = (sample.game_id, sample.decision_id)
                if key in seen:
                    raise ValueError(f"duplicate decision: {key}")

                seen.add(key)
                stream.write(json.dumps(
                    sample.to_dict(), ensure_ascii=False, allow_nan=False, separators=(",", ":"),) + "\n"
                )
                count += 1
            if count == 0:
                raise ValueError("records cannot be empty")
    except BaseException:
        # 轉換或寫入中斷時，刪除這次建立的不完整資料集
        output.unlink(missing_ok=True)
        raise
    return count

