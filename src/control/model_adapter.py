"""模型推論轉接（W9 D1~D4，W10 加逾時／斷路／暖機／計時）：Observation + LegalActions -> 模型分數 -> Decision。

- ModelBackend：只要有 predict(features, mask) -> 125 個分數即可（測試用假的）。
- TorchScriptBackend：載入 torch.jit 匯出的 checkpoint（torch 延後到真的要用才 import）。
- ModelPolicy：只在合法動作中取最高分；模型例外／長度不對／合法動作分數非有限值／逾時
  -> 自動退回 baseline（ActionPolicy），並記錄次數與原因。
- W10：timeout_s 逾時（模型無回應）；連續失敗 trip_after 次後，接下來 cooldown 次決策直接用 baseline
  （不再等模型），之後再試一次模型。
- TimedPolicy：包住任何策略，記錄每次回合的策略耗時（GameRunner 用來統計 decision_ms）。
- 每個候選分數放進 Decision.candidate_evaluations，pipeline 會寫進 JSONL（dashboard 可用）。
- strategy_version = model_<版本>，pipeline 的 decision_made 事件會記錄。
"""

from __future__ import annotations

import math
import threading
from collections import Counter
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Protocol, Sequence

from src.control.release import sha256_file
from src.control.util import p95
from src.strategy.action_mask import ACTION_SPACE_SIZE, action_to_index
from src.strategy.action_policy import ActionPolicy
from src.strategy.encoder import encode_observation
from src.strategy.interfaces import CandidateEvaluation, Decision, LegalActions, Observation


class ModelBackend(Protocol):
    def predict(self, features: Sequence[float], mask: Sequence[int]) -> Sequence[float]:
        """回傳長度 ACTION_SPACE_SIZE 的分數（不需要自己套 mask，轉接層會只看合法動作）。"""
        ...


class ModelTimeoutError(TimeoutError):
    """模型在時限內沒有回應。"""


def call_with_timeout(fn: Callable[..., Any], timeout: float, *args: Any) -> Any:
    """在 daemon 執行緒跑 fn；超過 timeout 秒沒回來就拋 ModelTimeoutError（卡住的執行緒不會擋住程式結束）。"""
    box: dict[str, Any] = {}
    done = threading.Event()

    def run() -> None:
        try:
            box["value"] = fn(*args)
        except BaseException as exc:  # noqa: BLE001  例外原樣帶回呼叫端
            box["error"] = exc
        finally:
            done.set()

    threading.Thread(target=run, name="model-predict", daemon=True).start()
    if not done.wait(timeout):
        raise ModelTimeoutError(f"model no response within {timeout:g}s")
    if "error" in box:
        raise box["error"]
    return box["value"]


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
        with torch.inference_mode():
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
        timeout: float | None = None,
        trip_after: int = 5,
        cooldown: int = 20,
    ) -> None:
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout 必須大於 0（不限時請傳 None）")
        if trip_after < 1 or cooldown < 0:
            raise ValueError("trip_after 至少為 1，cooldown 不可為負")

        self.backend = backend
        self.fallback = fallback if fallback is not None else ActionPolicy()
        self.model_version = model_version
        self.checkpoint_sha256 = checkpoint_sha256
        self.strategy_version = f"model_{model_version}"
        self.timeout = timeout
        self.trip_after = trip_after
        self.cooldown = cooldown

        self.model_decisions = 0
        self.fallback_decisions = 0
        self.timeouts = 0
        self.trips = 0  # 斷路次數
        self.fallback_reasons: Counter[str] = Counter()
        self.latencies_ms: list[float] = []
        self._consecutive = 0
        self._skip_left = 0

    # ------------------------------------------------------------ 決策

    def decide(self, observation: Observation, legal_actions: LegalActions) -> Decision:
        actions = tuple(legal_actions)
        if not actions:
            raise ValueError("legal_actions cannot be empty")

        start = perf_counter()
        if self._skip_left > 0:
            self._skip_left -= 1
            if self._skip_left == 0:
                self._consecutive = self.trip_after - 1  # 冷卻結束：再試一次，失敗就立刻再斷路
            decision = self._fallback_decide(observation, actions, "model disabled after repeated failures")
        else:
            try:
                decision = self._model_decide(observation, actions)
            except Exception as exc:  # noqa: BLE001  模型任何錯誤都不能讓整局停下
                self._note_failure(exc)
                decision = self._fallback_decide(observation, actions, f"{type(exc).__name__}: {exc}")
            else:
                self.model_decisions += 1
                self._consecutive = 0
        self.latencies_ms.append((perf_counter() - start) * 1000.0)
        return decision

    def _note_failure(self, exc: Exception) -> None:
        if isinstance(exc, ModelTimeoutError):
            self.timeouts += 1
        self._consecutive += 1
        if self._consecutive >= self.trip_after:
            self._skip_left = self.cooldown
            self.trips += 1

    def _predict(self, features, mask):
        if self.timeout is None:
            return self.backend.predict(features, mask)
        return call_with_timeout(self.backend.predict, self.timeout, features, mask)

    def _model_decide(self, observation: Observation, actions: tuple) -> Decision:
        index_to_action: dict[int, Any] = {}
        for action in actions:
            index = action_to_index(action)  # 不支援的動作（摸牌、補花）在這裡拋 ValueError
            if index in index_to_action:
                raise ValueError(f"duplicate action index {index}")
            index_to_action[index] = action

        # 遮罩直接由已算好的索引產生，不再對每個動作重算一次 action_to_index
        mask = [0] * ACTION_SPACE_SIZE
        for index in index_to_action:
            mask[index] = 1

        scores = list(self._predict(encode_observation(observation), mask))
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

    # ------------------------------------------------------------ 暖機與報告

    def warmup(self) -> None:
        """先推論一次，第一次真正的決策才不會包含載入／暖機時間。失敗不拋錯（正式決策時會走 fallback）。"""
        try:
            self.backend.predict([0.0] * 555, [1] * ACTION_SPACE_SIZE)
        except Exception:  # noqa: BLE001
            pass

    def reset_stats(self) -> None:
        """暖機之後呼叫，讓報告只包含正式量測。"""
        self.model_decisions = self.fallback_decisions = 0
        self.timeouts = self.trips = 0
        self._consecutive = self._skip_left = 0
        self.fallback_reasons.clear()
        self.latencies_ms.clear()

    def describe(self) -> str:
        lat = self.latencies_ms
        mean = sum(lat) / len(lat) if lat else None
        stats = "-" if mean is None else f"平均 {mean:.1f} ms、p95 {p95(lat):.1f} ms"
        sha = (self.checkpoint_sha256 or "-")[:12]
        text = (
            f"策略 {self.strategy_version}（sha256 {sha}）：模型決策 {self.model_decisions} 次、"
            f"退回 baseline {self.fallback_decisions} 次（逾時 {self.timeouts}、斷路 {self.trips}）；決策耗時 {stats}"
        )
        if self.fallback_reasons:
            text += f"；退回原因 {dict(self.fallback_reasons)}"
        return text


class TimedPolicy:
    """包住任何策略，記錄策略耗時。一個回合內呼叫 decide 幾次就累加，pop_last_ms() 取走並清空。"""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._last: float | None = None

    def decide(self, observation, legal_actions):
        start = perf_counter()
        try:
            return self._inner.decide(observation, legal_actions)
        finally:
            ms = (perf_counter() - start) * 1000.0
            self._last = ms if self._last is None else self._last + ms

    def pop_last_ms(self) -> float | None:
        value, self._last = self._last, None
        return value

    def __getattr__(self, name: str) -> Any:
        # strategy_version、describe、fallback_decisions 等直接轉給內層策略
        if name.startswith("__") or name == "_inner":
            raise AttributeError(name)
        return getattr(self._inner, name)


# ------------------------------------------------------------------ 切換（D3）

def build_policy(
    kind: str, *, checkpoint: str | Path | None = None,
    model_version: str | None = None, device: str = "cpu",
    timeout: float | None = None, trip_after: int = 5, cooldown: int = 20,
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
    policy = ModelPolicy(
        TorchScriptBackend(path, device),
        model_version=model_version or f"{path.stem}-{sha[:8]}",
        checkpoint_sha256=sha,
        timeout=timeout, trip_after=trip_after, cooldown=cooldown,
    )
    policy.warmup()
    return policy


def add_policy_args(parser) -> None:
    parser.add_argument("--policy", choices=("baseline", "model"), default="baseline",
                        help="出牌策略：規則型 baseline 或模型（失敗時自動退回 baseline）")
    parser.add_argument("--checkpoint", default=None, help="TorchScript checkpoint 路徑（--policy model 必填）")
    parser.add_argument("--model-version", default=None, help="記錄用版本名（預設：檔名-sha256 前 8 碼）")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--model-timeout", type=float, default=0.5,
                        help="模型單次推論時限（秒），超過就退回 baseline；0 = 不限時")
    parser.add_argument("--trip-after", type=int, default=5, help="模型連續失敗幾次後暫停使用")
    parser.add_argument("--cooldown", type=int, default=20, help="暫停使用模型的決策次數，之後再試一次")


def policy_from_args(args):
    try:
        return build_policy(
            args.policy, checkpoint=args.checkpoint,
            model_version=args.model_version, device=args.device,
            timeout=(getattr(args, "model_timeout", 0.0) or None),
            trip_after=getattr(args, "trip_after", 5), cooldown=getattr(args, "cooldown", 20),
        )
    except (ValueError, OSError, ImportError) as exc:
        raise RuntimeError(f"策略載入失敗：{exc}") from exc