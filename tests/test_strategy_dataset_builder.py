import json
from dataclasses import replace

import pytest

from src.common.schemas import ActionType as A
from src.rules.legal_actions import LegalActionGenerator
from src.rules.rule import RulesetConfig
from src.strategy.action_mask import action_to_index, build_action_mask
from src.strategy.action_policy import ActionPolicy
from src.strategy.adapters import actions_to_legal_actions, game_state_to_observation
from src.strategy.dataset_builder import DecisionRecord, record_to_sample, write_dataset
from src.strategy.encoder import encode_observation
from src.strategy.evaluation_plan import EvaluationGame, make_game_state
from src.strategy.interfaces import Decision, LegalAction
from src.strategy.training_sample import TrainingSample


# 從 Rules 發牌、產生合法動作，再由既有策略選擇教師標籤
@pytest.fixture(scope="module")
def record():
    config = RulesetConfig()
    state = make_game_state(EvaluationGame(4, 0), config)
    observation = game_state_to_observation(state, 0)
    actions = tuple(actions_to_legal_actions(
        LegalActionGenerator(config).get_turn_player_actions(
            hand=state.players[0].hand, last_drawn_tile=state.players[0].hand[-1],
            can_win_self_draw=state.is_basic_win(0),
        )
    ))
    policy = ActionPolicy()
    return DecisionRecord(
        game_id=state.game_id, decision_id="decision_0",
        observation=observation, legal_actions=actions,
        decision=policy.decide(observation, actions),
        strategy_version=policy.strategy_version,
        rule_version=config.ruleset_version, wall_seed=4,
    )


# 轉換後的特徵、標籤與來源資訊必須對應原紀錄
def test_conversion_preserves_features_and_metadata(record):
    sample = record_to_sample(record)
    assert sample.features == encode_observation(record.observation)
    assert sample.action_mask == build_action_mask(record.legal_actions)
    assert sample.action_index == action_to_index(record.decision.action)
    assert sample.game_id == record.game_id
    assert sample.decision_id == record.decision_id
    assert sample.strategy_version == record.strategy_version
    assert sample.rule_version == record.rule_version
    assert sample.wall_seed == 4


# 驗證各類決策的固定索引，動作合法性仍由 Rules 提供
@pytest.mark.parametrize("action,index", [
    (LegalAction("discard", A.DISCARD, 3), 3),
    (LegalAction("chi", A.CHI, 2, (0, 1, 2)), 34),
    (LegalAction("pong", A.PONG, 27, (27, 27, 27)), 82),
    (LegalAction("kong", A.KONG, 27, (27,) * 4, "an"), 116),
    (LegalAction("win", A.WIN), 123),
    (LegalAction("pass", A.PASS), 124),
])
def test_action_types_use_existing_mapping(record, action, index):
    changed = replace(
        record, legal_actions=(action,), decision=Decision(action, 0.0, "test"),
    )
    sample = record_to_sample(changed)
    assert sample.action_index == index
    assert sample.action_mask[index] == sum(sample.action_mask) == 1


# 同 ID 但內容不同，或同索引但不在候選清單，都不能充當正確標籤
@pytest.mark.parametrize("change", ["same_id", "same_index"])
def test_inexact_decision_is_rejected(record, change):
    action = record.decision.action
    bad = replace(action, tile=(action.tile + 1) % 34) if change == "same_id" else (
        replace(action, id="not_in_legal_actions")
    )
    with pytest.raises(ValueError, match="legal_actions"):
        record_to_sample(replace(
            record, decision=replace(record.decision, action=bad),
        ))


# 空候選、重複 ID 或重複索引，都無法建立明確的訓練標籤
@pytest.mark.parametrize("kind", ["empty", "duplicate_id", "duplicate_index"])
def test_ambiguous_candidates_are_rejected(record, kind):
    action = record.decision.action
    actions = () if kind == "empty" else (
        action, action if kind == "duplicate_id" else replace(action, id="alias")
    )
    with pytest.raises(ValueError):
        record_to_sample(replace(record, legal_actions=actions))


# 缺少玩家公開牌面不能以空資料猜補；未知剩餘張數仍保留 -1
def test_observation_validation_and_unknown_values(record):
    broken = replace(record.observation, melds=((),) * 3)
    with pytest.raises(ValueError, match="four players"):
        record_to_sample(replace(record, observation=broken))

    unknown = replace(record.observation, remaining_tiles=None)
    sample = record_to_sample(replace(
        record, observation=unknown, wall_seed=None,
    ))
    assert sample.features[-1] == -1.0
    assert sample.wall_seed is None


# 輸出每行都是 Day 1 的樣本格式，保留順序與同局不同決策
def test_jsonl_round_trip(record, tmp_path):
    records = [record, replace(record, decision_id="decision_1")]
    output = tmp_path / "dataset.jsonl"
    assert write_dataset(iter(records), output) == 2
    samples = [
        TrainingSample.from_dict(json.loads(line))
        for line in output.read_text(encoding="utf-8").splitlines()
    ]
    assert samples == [record_to_sample(item) for item in records]


# 空資料、重複決策或中途轉換失敗，都不能留下半份資料集
@pytest.mark.parametrize("kind", ["empty", "duplicate", "invalid"])
def test_failed_dataset_is_removed(record, tmp_path, kind):
    records = [] if kind == "empty" else [
        record, record if kind == "duplicate" else replace(record, legal_actions=()),
    ]
    output = tmp_path / "failed.jsonl"
    with pytest.raises(ValueError):
        write_dataset(records, output)
    assert not output.exists()


# 已存在的檔案保持原樣，避免誤覆蓋先前資料
def test_existing_dataset_is_preserved(record, tmp_path):
    output = tmp_path / "dataset.jsonl"
    output.write_text("existing data", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_dataset([record], output)
    assert output.read_text(encoding="utf-8") == "existing data"


# 資料來源中途出錯時也要清除新檔，錯誤原因繼續向外回報
def test_source_failure_is_propagated(record, tmp_path):
    def records():
        yield record
        raise RuntimeError("source failed")

    output = tmp_path / "failed.jsonl"
    with pytest.raises(RuntimeError, match="source failed"):
        write_dataset(records(), output)
    assert not output.exists()