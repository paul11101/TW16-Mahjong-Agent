"""模型決策延遲拆解（W10 D1/D3）：只量時間，用 SimTable 打真實對局，不開視窗、不點擊。

把一次 ModelPolicy.decide 拆成 編碼 / 推論 / 其餘（索引、遮罩、softmax、候選分數），
看時間花在哪，再決定值不值得優化。

    python -m test_interface.measure_model_latency --checkpoint models\\bc_v1.pt --games 20
    python -m test_interface.measure_model_latency --fake --games 5     # 沒有 checkpoint 時驗證流程

輸出：終端機表格＋ data/processed/model_latency_breakdown.json
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from time import perf_counter

import src.control.model_adapter as ma
from src.control.model_adapter import ModelPolicy, build_policy
from src.strategy.action_mask import ACTION_SPACE_SIZE
from test_interface import measure_decision as md
from test_interface.measure_latency import stats_ms

OUT_PATH = Path("data/processed/model_latency_breakdown.json")
BUDGET_MS = 300.0


class _RandomBackend:
    def __init__(self, seed: int = 1) -> None:
        self.rng = random.Random(seed)

    def predict(self, features, mask):
        return [self.rng.random() for _ in range(ACTION_SPACE_SIZE)]


class TimedBackend:
    def __init__(self, inner, record: dict[str, list[float]]) -> None:
        self.inner, self.record = inner, record

    def predict(self, features, mask):
        start = perf_counter()
        try:
            return self.inner.predict(features, mask)
        finally:
            self.record["predict"].append((perf_counter() - start) * 1000.0)


def timed(record: dict[str, list[float]], name: str, fn):
    def wrapper(*args, **kwargs):
        start = perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            record[name].append((perf_counter() - start) * 1000.0)

    return wrapper


def breakdown(total: list[float], record: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    n = min(len(total), len(record["encode"]), len(record["predict"]))
    if n == 0:
        raise ValueError("沒有量到任何一次模型決策")
    encode, predict = record["encode"][:n], record["predict"][:n]
    whole = total[:n]
    other = [t - e - p for t, e, p in zip(whole, encode, predict)]
    return {
        "encode": stats_ms(encode),
        "predict": stats_ms(predict),
        "other": stats_ms(other),
        "total": stats_ms(whole),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="模型決策延遲拆解")
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument("--checkpoint", default=None)
    parser.add_argument("--fake", action="store_true", help="用隨機分數的假模型（不需要 torch／checkpoint）")
    parser.add_argument("--out", default=str(OUT_PATH))
    args = parser.parse_args()

    if args.fake:
        policy = ModelPolicy(_RandomBackend(), model_version="fake")
    else:
        try:
            policy = build_policy("model", checkpoint=args.checkpoint)
        except (ValueError, OSError, ImportError) as exc:
            print(f"❌ 策略載入失敗：{exc}")
            return 1

    record: dict[str, list[float]] = {"encode": [], "predict": []}
    original_encode = ma.encode_observation
    ma.encode_observation = timed(record, "encode", original_encode)
    policy.backend = TimedBackend(policy.backend, record)
    seeds = list(range(args.seed_start, args.seed_start + args.games))
    try:
        md.measure_policy(seeds[:3], policy)  # 暖機，不計
        policy.reset_stats()
        for values in record.values():
            values.clear()
        md.measure_policy(seeds, policy)
    finally:
        ma.encode_observation = original_encode

    if policy.fallback_decisions:
        print(f"⚠️ 有 {policy.fallback_decisions} 次退回 baseline，拆解只取兩邊都有量到的前面幾筆：{dict(policy.fallback_reasons)}")
    result = breakdown(policy.latencies_ms, record)

    print(f"策略 {policy.strategy_version}")
    print(f"{'階段':<10}{'n':>7}{'平均':>9}{'p95':>9}{'最大':>9}   (ms)")
    labels = {"encode": "特徵編碼", "predict": "模型推論", "other": "其餘轉換", "total": "整次決策"}
    for key, label in labels.items():
        s = result[key]
        print(f"{label:<9}{int(s['n']):>7}{s['mean']:>9.3f}{s['p95']:>9.3f}{s['max']:>9.3f}")
    share = result["other"]["mean"] / result["total"]["mean"] if result["total"]["mean"] else 0.0
    print(f"\n其餘轉換佔平均決策時間 {share:.0%}；整次決策 p95 {result['total']['p95']:.2f} ms，預算 {BUDGET_MS:.0f} ms："
          f"{'✅ 在預算內' if result['total']['p95'] <= BUDGET_MS else '❌ 超過預算'}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({policy.strategy_version: result}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 量測完成，已儲存：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())