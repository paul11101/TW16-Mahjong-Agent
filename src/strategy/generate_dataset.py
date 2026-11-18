import argparse
from itertools import count
from pathlib import Path
from typing import Iterator

from src.rules.rule import RulesetConfig
from src.strategy.action_policy import ActionPolicy
from src.strategy.dataset_builder import DecisionRecord, write_dataset
from src.strategy.evaluation_game import play_round
from src.strategy.evaluation_plan import EvaluationGame, make_game_state
from src.strategy.interfaces import Decision, LegalActions,Observation

# 用 Baseline v1 當教師，把每次選牌或回應記成一筆訓練資料
class RecordingPolicy:
    def __init__(self, game_id: str, seed: int, rule_version: str):
        # 訓練標籤只需要最後選定的動作，可省去逐一計算候選分數
        self.teacher = ActionPolicy(include_candidate_scores=False)
        self.game_id = game_id
        self.seed = seed
        self.rule_version = rule_version
        self.records: list[DecisionRecord] = []

    def decide(self, observation: Observation, legal_actions: LegalActions) -> Decision:
        actions = tuple(legal_actions)
        decision = self.teacher.decide(observation, actions)
        # 保存做決定當下的觀測與合法動作，牌山種子用於重現這一局
        self.records.append(DecisionRecord(
            game_id=self.game_id,
            decision_id=str(len(self.records)),
            observation=observation,
            legal_actions=actions,
            decision=decision,
            strategy_version=self.teacher.strategy_version,
            rule_version=self.rule_version,
            wall_seed=self.seed,
        ))

        return decision

def generate_records(limit: int = 10000, start_seed: int = 10000) -> Iterator[DecisionRecord]:
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer")

    if type(start_seed) is not int or start_seed < 0:
        raise ValueError("start_seed must be a non-negative integer")

    config = RulesetConfig()
    remaining = limit
    # 每局換一個種子洗牌，相同起始種子可重現同一批決策
    for seed in count(start_seed):
        state = make_game_state(EvaluationGame(seed, 0), config)
        recorder = RecordingPolicy(state.game_id, seed, config.ruleset_version)
        # 四個座位共用紀錄器，決策編號依整局的行動順序排列
        play_round(state, [recorder] * 4, config)

        # 最後一局只取還缺的筆數，讓輸出剛好達到指定數量
        batch = recorder.records[:remaining]
        yield from batch
        remaining -= len(batch)
        if remaining == 0:
            return


def main():
    parser = argparse.ArgumentParser(description="產生台麻教師決策資料集")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--start-seed", type=int, default=10000)
    args = parser.parse_args()

    folder = Path(__file__).resolve().parents[2] / "data" / "strategy"
    output = args.output or folder / f"decisions_{args.start_seed}_{args.limit}.jsonl"
    # 沿用資料集寫入流程，每筆決策轉成一行 JSON
    written = write_dataset(generate_records(args.limit, args.start_seed), output)
    print(f"已寫入 {written:,} 筆決策: {output.resolve()}")


if __name__ == "__main__":
    main()