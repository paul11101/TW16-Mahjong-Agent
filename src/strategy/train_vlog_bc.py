import argparse
import math
from pathlib import Path
from tempfile import mkdtemp

import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.data import DataLoader

from src.control.release import sha256_file
from src.strategy.dataset_loader import DecisionDataset
from src.strategy.dataset_split import split_v1_by_game
from src.strategy.freeze_dataset import DATA_DIR, DATA_FILE, VERSION
from src.strategy.training_sample import SCHEMA_VERSION
from src.strategy.vlog_executor import VlogBCExecutor

DEFAULT_DATASET = DATA_DIR / VERSION / DATA_FILE
DEFAULT_RUNS = DATA_DIR.parents[1] / "exports" / "strategy"

def run_epoch(model: nn.Module, loader: DataLoader, optimizer=None) -> dict:
    # 訓練時計算梯度並更新權重，驗證時使用評估模式
    training = optimizer is not None
    model.train(training)
    total = correct = choices = choice_correct = 0
    raw_illegal = masked_illegal = 0
    loss_sum = 0.0

    with torch.set_grad_enabled(training):
        for batch in loader:
            mask = batch["action_mask"]
            target = batch["action_index"]
            logits = model(batch["features"])

            if not torch.isfinite(logits).all():
                raise ValueError("non-finite logits")

            # 只在當下合法的動作中計算教師答案的交叉熵
            masked = logits.masked_fill(~mask, float("-inf"))
            loss = F.cross_entropy(masked, target)
            if not torch.isfinite(loss):
                raise ValueError("non-finite loss")

            if training:
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()

            pred = masked.argmax(dim=1)
            hit = pred == target
            # 另外統計至少有兩種合法動作的決策，避免只能過牌的樣本拉高準確率
            choice = mask.sum(dim=1) > 1

            # 比較遮罩前後的首選動作，分別累計模型原始與實際選擇的非法次數
            raw_pred = logits.argmax(dim=1, keepdim=True)
            raw_illegal += (~mask.gather(1, raw_pred)).sum().item()
            masked_illegal += (~mask.gather(1, pred.unsqueeze(1))).sum().item()

            total += target.numel()
            correct += hit.sum().item()
            choices += choice.sum().item()
            choice_correct += (hit & choice).sum().item()

            # 依批次的實際筆數加權，讓最後一個小批次也按相同比例計入平均
            loss_sum += loss.item() * target.numel()

    if total == 0:
        raise ValueError("empty epoch")

    return {
        "samples": total,
        "loss": loss_sum / total,
        "accuracy": correct / total,
        "choice_samples": choices,
        "choice_accuracy": choice_correct / choices if choices else None,
        "raw_illegal_rate": raw_illegal / total,
        "illegal_rate": masked_illegal / total,
    }


def train_bc(
        dataset: Path,
        runs_dir: Path,
        *,
        epochs: int = 3,
        batch_size: int = 128,
        lr: float = 0.001,
        seed: int = 42,
) -> Path:
    if epochs < 1 or batch_size < 1 or not math.isfinite(lr) or lr <= 0:
        raise ValueError("epochs, batch_size and lr must be positive")

    dataset = Path(dataset).resolve()
    # 依完整對局切分資料，保留測試集供後續評測
    split = split_v1_by_game(DecisionDataset(dataset), seed=seed)
    sizes = {
        "train": len(split.train),
        "val": len(split.val),
        "test": len(split.test),
    }
    print(f"決策筆數 {sizes}，排除的殘局 {split.excluded_game}")

    shuffle_rng = torch.Generator().manual_seed(seed)
    train_loader = DataLoader(split.train, batch_size=batch_size, shuffle=True, generator=shuffle_rng)
    val_loader = DataLoader(split.val, batch_size=batch_size)

    torch.manual_seed(seed)
    model = VlogBCExecutor()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    config = {"epochs": epochs, "batch_size": batch_size, "lr": lr, "seed": seed}
    # 記下資料檔雜湊與切分筆數，日後可核對這組權重的訓練來源
    source = {
        "path": str(dataset),
        "sha256": sha256_file(dataset),
        "schema_version": SCHEMA_VERSION,
        "split_samples": sizes,
        "excluded_game": split.excluded_game,
    }

    runs_dir = Path(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    folder = Path(mkdtemp(prefix="vlog_bc_", dir=runs_dir))
    checkpoint = folder / "last.pt"
    history = []

    for epoch in range(1, epochs + 1):
        train = run_epoch(model, train_loader, optimizer)
        val = run_epoch(model, val_loader)
        history.append({"epoch": epoch, "train": train, "val": val})

        for phase, metrics in (("train", train), ("val", val)):
            accuracy = metrics["choice_accuracy"]
            choice_text = "無樣本" if accuracy is None else f"{accuracy:.2%}"
            print(
                f"epoch {epoch} {phase}  loss={metrics['loss']:.4f}  "
                f"acc={metrics['accuracy']:.2%}  choice_acc={choice_text}  "
                f"raw_illegal={metrics['raw_illegal_rate']:.2%}  "
                f"illegal={metrics['illegal_rate']:.2%}"
            )

        # 先寫完本輪權重與指標，再取代上一輪的 checkpoint
        pending = folder / "last.tmp"
        torch.save({
            "epoch": epoch,
            "config": config,
            "source": source,
            "history": history,
            "model_state_dict": model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),

        }, pending)
        pending.replace(checkpoint)

    return checkpoint


def main() -> None:
    parser = argparse.ArgumentParser(description="台麻 VLOG 行為複製訓練")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--lr", type=float, default=0.001)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if not args.dataset.is_file():
        parser.error(f"找不到資料集 {args.dataset}，請用 --dataset 指定 W8 決策 JSONL")

    checkpoint = train_bc(
        args.dataset, args.runs_dir, epochs=args.epochs,
        batch_size=args.batch_size, lr=args.lr, seed=args.seed,
    )
    print(f"訓練結果已保存：{checkpoint.resolve()}")


if __name__ == "__main__":
    main()