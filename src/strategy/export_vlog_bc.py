import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import torch

from src.control.release import sha256_file
from src.strategy.action_mask import ACTION_SPACE_SIZE
from src.strategy.feature_spec import FEATURE_SIZE
from src.strategy.train_vlog_bc import DEFAULT_RUNS
from src.strategy.training_sample import SCHEMA_VERSION
from src.strategy.vlog_executor import VlogBCExecutor


def export_bc(checkpoint: Path, output_dir: Path) -> Path:
    if output_dir.exists():
        raise FileExistsError(f"輸出目錄已存在：{output_dir}")

    saved = torch.load(checkpoint, map_location="cpu", weights_only=True)
    if saved["source"]["schema_version"] != SCHEMA_VERSION:
        raise ValueError("checkpoint schema mismatch")

    history = saved["history"]
    if not history or history[-1]["epoch"] != saved["epoch"]:
        raise ValueError("checkpoint history mismatch")

    # 載入 Day 4 訓練好的權重，切到推論模式後使用潛在分布的平均值
    model = VlogBCExecutor()
    model.load_state_dict(saved["model_state_dict"], strict=True)
    model.eval()

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output_dir.parent) as tmp:
        stage = Path(tmp) / "release"
        stage.mkdir()
        artifact = stage / "bc_v1.pt"
        torch.jit.save(torch.jit.script(model), str(artifact))

        # 用整合端的方式重新載入，比對單筆與批次推論的分數
        loaded = torch.jit.load(str(artifact), map_location="cpu").eval()
        rng = torch.Generator().manual_seed(42)
        with torch.inference_mode():
            for size in (1, 4):
                features = torch.rand(size, FEATURE_SIZE, generator=rng, dtype=torch.float32)
                logits = loaded(features)
                if logits.shape != (size, ACTION_SPACE_SIZE) or not torch.isfinite(logits).all():
                    raise ValueError("invalid exported logits")
                torch.testing.assert_close(logits, model(features))

        # 保存資料來源、訓練設定及每輪指標，用雜湊核對交付的模型
        report = {
            "model": artifact.name,
            "model_sha256": sha256_file(artifact),
            "epoch": saved["epoch"],
            "config": saved["config"],
            "source": saved["source"],
            "history": history,
        }
        (stage / "training.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        # 模型與紀錄都完成後才建立正式目錄，避免留下半套結果
        stage.rename(output_dir)

    return output_dir / "bc_v1.pt"


def main() -> None:
    parser = argparse.ArgumentParser(description="匯出台麻 VLOG-BC v1 與訓練紀錄")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_RUNS / "bc_v1")
    args = parser.parse_args()

    checkpoint = args.checkpoint
    if checkpoint is None:
        # 只有一份 last.pt 時才自動選取，多次訓練後需指定要匯出的權重。
        runs = sorted(DEFAULT_RUNS.glob("vlog_bc_*/last.pt"))
        if len(runs) != 1:
            parser.error(f"找到 {len(runs)} 份 last.pt，請用 --checkpoint 指定 Day 4 的訓練結果")
        checkpoint = runs[0]

    model_path = export_bc(checkpoint, args.output_dir)
    print(f"正式模型：{model_path.resolve()}")
    print(f"訓練紀錄：{model_path.with_name('training.json').resolve()}")


if __name__ == "__main__":
    main()