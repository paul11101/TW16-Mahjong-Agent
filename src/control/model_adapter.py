"""模型推論轉接（W9 D1~D4）：Observation + LegalActions -> 模型分數 -> Decision。

- ModelBackend：只要有 predict(features, mask) -> 125 個分數即可（測試用假的）。
- TorchScriptBackend：載入 torch.jit 匯出的 checkpoint（torch 延後到真的要用才 import）。
- ModelPolicy：只在合法動作中取最高分；模型例外／長度不對／合法動作分數非有限值
  -> 自動退回 baseline（ActionPolicy），並記錄次數與原因。
- 每個候選分數放進 Decision.candidate_evaluations，pipeline 會寫進 JSONL（dashboard 之後可用）。
- strategy_version = model_<版本>，pipeline 的 decision_made 事件會記錄（D4）。
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol, Sequence

from src.control.release import sha256_file
from src.control.util import p95
from src.strategy.action_mask import ACTION_SPACE_SIZE, action_to_index, build_action_mask
from src.strategy.action_policy import ActionPolicy
from src.strategy.encoder import encode_observation
from src.strategy.interfaces import CandidateEvaluation, Decision, LegalActions, Observation


class ModelBackend(Protocol):
    def predict(self, features: Sequence[float], mask: Sequence[int]) -> Sequence[float]:
        """回傳長度 ACTION_SPACE_SIZE 的分數（不需要自己套 mask，轉接層會只看合法動作）。"""
        ...


class TorchScriptBackend:
    """載入 TorchScript checkpoint：輸入 [1, 555] float，輸出 [1, 125]。"""

    def __init__(self, path: str | Path, device: str = "cpu") -> None:
        import torch

        self._torch = torch
        self.device = device
        self.model = torch.jit.load(str(path), map_location=device)
        self.model.eval()

    def predict(self, features: Sequence[float], mask: Sequence[int]) -> Sequence[float]:
        torch = self._torch
        with torch.no_grad():
            x = torch.tensor([list(features)], dtype=torch.float32, device=self.device)
            return self.model(x).reshape(-1).tolist()


class ModelPolicy:
    def __init__(
        self,
        backend: ModelBackend,
        *,
        fallback: Any | None = None,
        model_version: str = "model",
        checkpoint_sha256: str | None = None,
    ) -> None:
        self.backend = backend
        self.fallback = fallback if fallback is not None else ActionPolicy()
        self.model_version = model_version
        self.checkpoint_sha256 = checkpoint_sha256
        self.strategy_version = f"model_{model_version}"

        self.model_decisions = 0
        self.fallback_decisions = 0
        self.fallback_reasons: Counter[str] = Counter()
        self.latencies_ms: list[float] = []

    # ------------------------------------------------------------ 決策

    def decide(self, observation: Observation, legal_actions: LegalActions) -> Decision:
        actions = tuple(legal_actions)
        if not actions:
            raise ValueError("legal_actions cannot be empty")

        start = perf_counter()
        try:
            decision = self._model_decide(observation, actions)
        except Exception as exc:  # noqa: BLE001  模型任何錯誤都不能讓整局停下
            why = f"{type(exc).__name__}: {exc}"
            decision = self._fallback_decide(observation, actions, why)
        else:
            self.model_decisions += 1
        self.latencies_ms.append((perf_counter() - start) * 1000.0)
        return decision

    def _model_decide(self, observation: Observation, actions: tuple) -> Decision:
        index_to_action: dict[int, Any] = {}
        for action in actions:
            index = action_to_index(action)  # 不支援的動作（摸牌、補花）在這裡拋 ValueError
            if index in index_to_action:
                raise ValueError(f"duplicate action index {index}")
            index_to_action[index] = action

        scores = list(self.backend.predict(encode_observation(observation), build_action_mask(actions)))
        if len(scores) != ACTION_SPACE_SIZE:
            raise ValueError(f"model returned {len(scores)} scores, expected {ACTION_SPACE_SIZE}")

        legal_scores = {i: float(scores[i]) for i in index_to_action}
        bad = [i for i, s in legal_scores.items() if not math.isfinite(s)]
        if bad:
            raise ValueError(f"non-finite scores at legal indices {bad}")

        best = max(index_to_action, key=lambda i: legal_scores[i])  # 平手取合法動作順序中的第一個
        top = legal_scores[best]
        # 只在合法動作間做 softmax（減掉最大值，不會溢位）；score 放機率，候選分數保留原始 logit
        probability = 1.0 / sum(math.exp(s - top) for s in legal_scores.values())
        evaluations = tuple(
            CandidateEvaluation(
                action_id=action.id, score=legal_scores[i], scorable=True,
                reason=f"model logit = {legal_scores[i]:.4f}",
            )
            for i, action in index_to_action.items()
        )
        return Decision(
            action=index_to_action[best],
            score=probability,
            reason=f"model {self.model_version}: logit = {top:.4f}, p = {probability:.3f}",
            candidate_evaluations=evaluations,
        )

    def _fallback_decide(self, observation: Observation, actions: tuple, why: str) -> Decision:
        self.fallback_decisions += 1
        self.fallback_reasons[why] += 1
        decision = self.fallback.decide(observation, actions)  # baseline 也失敗就往外拋，由 GameRunner 記 TURN_EXCEPTION
        return replace(decision, reason=f"fallback ({why}): {decision.reason}")

    # ------------------------------------------------------------ 報告
    def reset_stats(self) -> None:
        """暖機之後呼叫，讓報告只包含正式量測。"""
        self.model_decisions = self.fallback_decisions = 0
        self.fallback_reasons.clear()
        self.latencies_ms.clear()

    def describe(self) -> str:
        lat = self.latencies_ms
        mean = sum(lat) / len(lat) if lat else None
        stats = "-" if mean is None else f"平均 {mean:.1f} ms、p95 {p95(lat):.1f} ms"
        sha = (self.checkpoint_sha256 or "-")[:12]
        text = (
            f"策略 {self.strategy_version}（sha256 {sha}）：模型決策 {self.model_decisions} 次、"
            f"退回 baseline {self.fallback_decisions} 次；決策耗時 {stats}"
        )
        if self.fallback_reasons:
            text += f"；退回原因 {dict(self.fallback_reasons)}"
        return text


# ------------------------------------------------------------------ 切換（D3）

def build_policy(
    kind: str, *, checkpoint: str | Path | None = None,
    model_version: str | None = None, device: str = "cpu",
):
    """baseline -> ActionPolicy；model -> ModelPolicy（啟動時載入失敗就直接報錯，不悄悄換成 baseline）。"""
    if kind == "baseline":
        return ActionPolicy()
    if kind != "model":
        raise ValueError(f"unknown policy: {kind}")
    if not checkpoint:
        raise ValueError("--policy model 需要 --checkpoint")

    path = Path(checkpoint)
    if not path.is_file():
        raise FileNotFoundError(f"找不到 checkpoint：{path}")

    sha = sha256_file(path)
    return ModelPolicy(
        TorchScriptBackend(path, device),
        model_version=model_version or f"{path.stem}-{sha[:8]}",
        checkpoint_sha256=sha,
    )


def add_policy_args(parser) -> None:
    parser.add_argument("--policy", choices=("baseline", "model"), default="baseline",
                        help="出牌策略：規則型 baseline 或模型（失敗時自動退回 baseline）")
    parser.add_argument("--checkpoint", default=None, help="TorchScript checkpoint 路徑（--policy model 必填）")
    parser.add_argument("--model-version", default=None, help="記錄用版本名（預設：檔名-sha256 前 8 碼）")
    parser.add_argument("--device", default="cpu")


def policy_from_args(args):
    try:
        return build_policy(
            args.policy, checkpoint=args.checkpoint,
            model_version=args.model_version, device=args.device,
        )
    except (ValueError, OSError, ImportError) as exc:
        raise RuntimeError(f"策略載入失敗：{exc}") from exc