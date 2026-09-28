"""
Обучение Routing-модели: классификация анатомической области снимка
(spine / hip_left / hip_right) -- ResNet18 с transfer learning от ImageNet.

Использует ВСЕ строки манифеста (включая excluded_reason != "" -- эндопротез
не мешает понять, что на снимке бедро, см. docstring RoutingDataset).

Запуск:
    python tools/train_routing.py --manifest data/manifest.csv --epochs 15

Результат:
    models/routing_best.pt              -- веса лучшей по val macro-F1 модели
    в консоль -- метрики по эпохам, финальный classification report
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import classification_report, f1_score
from torch.utils.data import DataLoader
from torchvision.models import ResNet18_Weights, resnet18

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.data.manifest_dataset import (  # noqa: E402
    IDX_TO_REGION,
    RoutingDataset,
    load_manifest,
    split_by_study,
)


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def build_model(num_classes: int = 3, pretrained: bool = True) -> nn.Module:
    """ResNet18, по умолчанию с ImageNet-претрейном; последний слой заменён под наши классы.

    Учитывая небольшой размер датасета (сотни, не тысячи изображений),
    transfer learning от ImageNet -- разумный выбор: ранние слои уже умеют
    выделять края и текстуры, дообучать нужно в основном последние слои.
    Веса скачиваются один раз при первом запуске (нужен интернет); на итоговый
    инференс это не влияет -- обученные веса сохраняются в чекпоинт целиком
    и дальше сервис работает полностью локально (п.3.2 ТЗ).
    """
    weights = ResNet18_Weights.IMAGENET1K_V1 if pretrained else None
    model = resnet18(weights=weights)
    model.fc = nn.Linear(model.fc.in_features, num_classes)
    return model


def run_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
    optimizer: torch.optim.Optimizer | None = None,
) -> tuple[float, list[int], list[int]]:
    """Один проход по данным. Если optimizer передан -- обучение, иначе -- валидация."""
    is_train = optimizer is not None
    model.train(is_train)

    total_loss = 0.0
    all_preds: list[int] = []
    all_labels: list[int] = []

    torch.set_grad_enabled(is_train)
    for batch in loader:
        images = batch["image"].to(device)
        labels = batch["label"].to(device)

        if is_train:
            optimizer.zero_grad()

        logits = model(images)
        loss = criterion(logits, labels)

        if is_train:
            loss.backward()
            optimizer.step()

        total_loss += loss.item() * images.size(0)
        preds = logits.argmax(dim=1)
        all_preds.extend(preds.cpu().tolist())
        all_labels.extend(labels.cpu().tolist())

    avg_loss = total_loss / len(loader.dataset)
    return avg_loss, all_preds, all_labels


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="data/manifest.csv")
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch_size", type=int, default=8)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--val_frac", type=float, default=0.2)
    parser.add_argument("--test_frac", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--image_size", type=int, default=224)
    parser.add_argument("--out", default="models/routing_best.pt")
    parser.add_argument("--num_workers", type=int, default=0)
    parser.add_argument(
        "--no_pretrained",
        action="store_true",
        help="не скачивать ImageNet-веса (для оффлайн-среды/отладки; для реального обучения не использовать)",
    )
    args = parser.parse_args()

    set_seed(args.seed)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Устройство: {device}")

    rows = load_manifest(args.manifest)
    print(f"Строк в манифесте: {len(rows)}")

    train_rows, val_rows, test_rows = split_by_study(
        rows, val_frac=args.val_frac, test_frac=args.test_frac, seed=args.seed
    )
    print(f"train={len(train_rows)} val={len(val_rows)} test={len(test_rows)}")

    if len(val_rows) == 0:
        raise SystemExit(
            "Валидационная выборка пустая -- слишком мало исследований для текущего val_frac. "
            "Увеличьте val_frac или добавьте больше размеченных данных."
        )

    train_ds = RoutingDataset(train_rows, image_size=args.image_size)
    val_ds = RoutingDataset(val_rows, image_size=args.image_size)

    train_loader = DataLoader(
        train_ds, batch_size=args.batch_size, shuffle=True, num_workers=args.num_workers
    )
    val_loader = DataLoader(
        val_ds, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers
    )

    model = build_model(num_classes=3, pretrained=not args.no_pretrained).to(device)

    # веса классов -- на случай перекоса в распределении регионов
    from collections import Counter

    label_counts = Counter(r["region"] for r in train_rows)
    total = sum(label_counts.values())
    weights = torch.tensor(
        [
            total / (3 * label_counts.get(region, 1))
            for region in ["spine", "hip_left", "hip_right"]
        ],
        dtype=torch.float32,
    ).to(device)
    print(f"Class weights (spine, hip_left, hip_right): {weights.tolist()}")

    criterion = nn.CrossEntropyLoss(weight=weights)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)

    best_val_f1 = -1.0
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    for epoch in range(1, args.epochs + 1):
        train_loss, train_preds, train_labels = run_epoch(
            model, train_loader, criterion, device, optimizer
        )
        val_loss, val_preds, val_labels = run_epoch(
            model, val_loader, criterion, device
        )

        train_f1 = f1_score(train_labels, train_preds, average="macro", zero_division=0)
        val_f1 = f1_score(val_labels, val_preds, average="macro", zero_division=0)

        print(
            f"[{epoch:02d}/{args.epochs}] "
            f"train_loss={train_loss:.4f} train_macroF1={train_f1:.3f} | "
            f"val_loss={val_loss:.4f} val_macroF1={val_f1:.3f}"
        )

        if val_f1 > best_val_f1:
            best_val_f1 = val_f1
            torch.save(
                {
                    "model_state_dict": model.state_dict(),
                    "val_macro_f1": val_f1,
                    "epoch": epoch,
                },
                out_path,
            )
            print(
                f"  -> новый лучший чекпоинт сохранён: {out_path} (val_macroF1={val_f1:.3f})"
            )

    print(f"\nЛучший val_macroF1: {best_val_f1:.3f}")
    print("\nФинальный classification report (последняя эпоха, val):")
    target_names = [IDX_TO_REGION[i] for i in range(3)]
    print(
        classification_report(
            val_labels, val_preds, target_names=target_names, zero_division=0
        )
    )


if __name__ == "__main__":
    main()
