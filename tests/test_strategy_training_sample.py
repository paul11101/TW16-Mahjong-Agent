import json
from dataclasses import FrozenInstanceError, replace

import pytest

from src.common.schemas import ActionType
from src.rules.rule import RulesetConfig
from src.strategy.action_mask import ACTION_SPACE_SIZE, action_to_index, build_action_mask
from src.strategy.action_policy import ActionPolicy
from src.strategy.encoder import encode_observation
from src.strategy.feature_spec import FEATURE_SIZE
from src.strategy.interfaces import LegalAction, Observation
from src.strategy.training_sample import TrainingSample

OBS = Observation(
    hand=(0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 24, 25, 26, 31, 32),
    discards=((),) * 4, melds=((),) * 4, flowers=((),) * 4,
    current_player=0, seat=0, remaining_tiles=None,
)
ACTIONS = tuple(
    LegalAction(f"discard_{tile}", ActionType.DISCARD, tile)
    for tile in (31, 32)
)


# 共用既有策略產生的樣本，避免在測試內重寫決策與編碼
@pytest.fixture(scope="module")
def sample():
    policy = ActionPolicy()
    decision = policy.decide(OBS, ACTIONS)
    return TrainingSample(
        game_id="game_0", decision_id="decision_0",
        strategy_version=policy.strategy_version,
        rule_version=RulesetConfig().ruleset_version,
        features=encode_observation(OBS), action_mask=build_action_mask(ACTIONS),
        action_index=action_to_index(decision.action), wall_seed=0,
    )


# 使用既有 Encoder、Mask 與教師決策，JSON 往返後內容一致
def test_existing_interfaces_and_json_round_trip(sample):
    assert len(sample.features) == FEATURE_SIZE == 555
    assert len(sample.action_mask) == ACTION_SPACE_SIZE == 125
    assert sample.action_mask[sample.action_index] == 1
    assert sample.features[-1] == -1.0
    encoded = json.dumps(sample.to_dict(), allow_nan=False)
    assert TrainingSample.from_dict(json.loads(encoded)) == sample


# 外部清單的修改不會污染樣本，欄位也不能重新指派
def test_sample_is_immutable(sample):
    features, mask = list(sample.features), list(sample.action_mask)
    copied = replace(sample, features=features, action_mask=mask)
    features[0] = 99
    mask[sample.action_index] = 0
    assert copied == sample
    with pytest.raises(FrozenInstanceError):
        setattr(copied, "action_index", 0)


# 局號、決策編號與來源版本不能只包含空白
@pytest.mark.parametrize("field", [
    "game_id", "decision_id", "strategy_version", "rule_version",
])
def test_empty_metadata_is_rejected(sample, field):
    with pytest.raises(ValueError, match=field):
        replace(sample, **{field: " "})


# 拒絕非數字與會污染訓練的 NaN／Infinity
@pytest.mark.parametrize("value", [
    float("nan"), float("inf"), True, "1", 10 ** 400,
])
def test_invalid_feature_values_are_rejected(sample, value):
    with pytest.raises(ValueError, match="features"):
        replace(sample, features=(value,) + sample.features[1:])


# 特徵與遮罩長度必須符合既有介面
@pytest.mark.parametrize("field", ["features", "action_mask"])
def test_incorrect_dimensions_are_rejected(sample, field):
    with pytest.raises(ValueError, match=field):
        replace(sample, **{field: getattr(sample, field)[:-1]})


# 即使 True 與 1.0 等於 1，也不接受為整數遮罩
@pytest.mark.parametrize("value", [2, -1, True, 1.0])
def test_invalid_mask_values_are_rejected(sample, value):
    with pytest.raises(ValueError, match="action_mask"):
        replace(sample, action_mask=(value,) + sample.action_mask[1:])


# 動作標籤必須是範圍內的整數索引
@pytest.mark.parametrize("value", [-1, ACTION_SPACE_SIZE, True, 31.0])
def test_invalid_action_index_is_rejected(sample, value):
    with pytest.raises(ValueError, match="action_index"):
        replace(sample, action_index=value)


# 索引在範圍內，仍必須是這筆樣本允許的動作
def test_masked_label_is_rejected(sample):
    with pytest.raises(ValueError, match="legal"):
        replace(sample, action_index=0)


# 已知牌山種子不能是負數、布林值或小數
@pytest.mark.parametrize("value", [-1, True, 1.5])
def test_invalid_wall_seed_is_rejected(sample, value):
    with pytest.raises(ValueError, match="wall_seed"):
        replace(sample, wall_seed=value)


# 未知種子在序列化前後保留 None，不補成零
def test_unknown_wall_seed_remains_none(sample):
    restored = TrainingSample.from_dict(replace(sample, wall_seed=None).to_dict())
    assert restored.wall_seed is None


# 拒絕缺少版本、未知版本與額外欄位，避免混入不同格式
@pytest.mark.parametrize("change", [
    "missing_version", "unknown_version", "extra_field",
])
def test_invalid_serialized_schema_is_rejected(sample, change):
    data = sample.to_dict()
    if change == "missing_version":
        del data["schema_version"]
    elif change == "unknown_version":
        data["schema_version"] = "unknown"
    else:
        data["opponent_hands"] = [[1, 2, 3]]
    with pytest.raises(ValueError):
        TrainingSample.from_dict(data)