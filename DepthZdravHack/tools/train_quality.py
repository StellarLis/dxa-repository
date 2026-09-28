"""
Обучение Quality-модели: multi-label классификация нарушений качества
для одной группы (spine ИЛИ hip) -- ResNet18 с transfer learning.

В отличие от routing (один снимок -> один из 3 классов), здесь у снимка
может быть 0, 1 или несколько нарушений одновременно -- поэтому на выходе
не softmax по классам, а НЕЗАВИСИМАЯ вероятность для КАЖДОГО типа нарушения
(сигмоида на каждом выходном нейроне, а не softmax на всех сразу).

Агрегированный quality_class (используется для sensitivity/specificity,
как того требует п.8.4 ТЗ) вычисляется как "есть хотя бы одно предсказанное
нарушение" -- ровно так же, как в разметка.xlsx колонка "Итог" получается
из под-критериев через ИЛИ.

Запуск:
    python tools/train_quality.py --manifest data/manifest.csv --group spine
    python tools/train_quality.py --manifest data/manifest.csv --group hip

Результат:
    models/quality_<group>_best.pt   -- веса лучшей по val macro-F1 модели
    в консоль -- метрики по эпохам, per-label отчёт, sensitivity/specificity
    итогового quality_class
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import f1_score, roc_auc_score
from torch.utils.data import DataLoader
from torchvision.models import ResNet18_Weights, resnet18

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.data.manifest_dataset import (  # noqa: E402
    HIP_VIOLATION_CODES,
    SPINE_VIOLATION_CODES,
    QualityDataset,
    load_manifest,
    split_by_study,
)


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def build_model(num_labels: int, pretrained: bool = True) -> nn.Module:
    """ResNet18 с заменённым последним слоем под multi-label выход.

    Важно: активация (сигмоида) НЕ добавляется внутрь модели -- на выходе
    остаются "сырые" логиты, а сигмоида и порог 0.5 применяются отдельно,
    при подсчёте метрик. Это стандартная практика: функция потерь
    BCEWithLogitsLoss математически стабильнее, если сама включает
    сигмоиду внутри себя, а не получает уже применённые вероятности.
    """
    weights = ResNet18_Weights.IMAGENET1K_V1 if pretrained else None
    model = resnet18(weights=weights)
    model.fc = nn.Linear(model.fc.in_features, num_labels)
    return model


def run_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
    optimizer: torch.optim.Optimizer | None = None,
) -> tuple[float, np.ndarray, np.ndarray]:
    """Один проход по данным. Возвращает средний loss и все предсказания/метки
    (сырые вероятности после сигмоиды, ещё без порога 0.5 -- порог применяется
    снаружи, при расчёте метрик, чтобы его можно было менять не переобучая)."""
    is_train = optimizer is not None
    model.train(is_train)

    total_loss = 0.0
    all_probs = []
    all_targets = []

    torch.set_grad_enabled(is_train)
    for batch in loader:
        images = batch["image"].to(device)
        targets = batch["violations"].to(device)

        if is_train:
            optimizer.zero_grad()

        logits = model(images)
        loss = criterion(logits, targets)

        if is_train:
            loss.backward()
            optimizer.step()

        total_loss += loss.item() * images.size(0)
        all_probs.append(torch.sigmoid(logits).detach().cpu().numpy())
        all_targets.append(targets.detach().cpu().numpy())

    avg_loss = total_loss / len(loader.dataset)
    return avg_loss, np.concatenate(all_probs), np.concatenate(all_targets)


def compute_metrics(probs: np.ndarray, targets: np.ndarray, codes: list[str]) -> dict:
    """Per-label и агрегированные метрики.

    per_label: F1 и ROC-AUC для каждого типа нарушения отдельно (п.8.4 ТЗ
    просит метрики отдельно по каждому типу нарушения). ROC-AUC пропускается,
    если в текущей выборке нет примеров обоих классов для этого лейбла --
    на маленьком val это реальный случай, а не баг.

    quality_class: агрегированная бинарная метрика "есть хоть одно нарушение"
    -- sensitivity (чувствительность выявления исследований с нарушениями)
    и specificity (для качественно выполненных), обе явно требуются в п.8.4.
    """
    preds = (probs >= 0.5).astype(int)

    per_label = {}
    for i, code in enumerate(codes):
        f1 = f1_score(targets[:, i], preds[:, i], zero_division=0)
        if len(set(targets[:, i].tolist())) > 1:
            auc = roc_auc_score(targets[:, i], probs[:, i])
        else:
            auc = None
        per_label[code] = {"f1": f1, "roc_auc": auc}

    macro_f1 = f1_score(targets, preds, average="macro", zero_division=0)

    # агрегированный quality_class = "есть хоть одно нарушение"
    quality_pred = (preds.sum(axis=1) > 0).astype(int)
    quality_true = (targets.sum(axis=1) > 0).astype(int)

    tp = int(((quality_pred == 1) & (quality_true == 1)).sum())
    fn = int(((quality_pred == 0) & (quality_true == 1)).sum())
    tn = int(((quality_pred == 0) & (quality_true == 0)).sum())
    fp = int(((quality_pred == 1) & (quality_true == 0)).sum())

    sensitivity = tp / (tp + fn) if (tp + fn) > 0 else None  # recall по нарушениям
    specificity = tn / (tn + fp) if (tn + fp) > 0 else None  # recall по норме

    return {
        "macro_f1": macro_f1,
        "per_label": per_label,
        "quality_sensitivity": sensitivity,
        "quality_specificity": specificity,
        "quality_tp": tp,
        "quality_fn": fn,
        "quality_tn": tn,
        "quality_fp": fp,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="data/manifest.csv")
    parser.add_argument("--group", choices=["spine", "hip"], required=True)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch_size", type=int, default=8)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--val_frac", type=float, default=0.2)
    parser.add_argument("--test_frac", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--image_size", type=int, default=224)
    parser.add_argument("--out", default=None)
    parser.add_argument("--num_workers", type=int, default=0)
    parser.add_argument("--no_pretrained", action="store_true")
    args = parser.parse_args()

    out_path = (
        Path(args.out) if args.out else Path(f"models/quality_{args.group}_best.pt")
    )
    codes = SPINE_VIOLATION_CODES if args.group == "spine" else HIP_VIOLATION_CODES

    set_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Устройство: {device}")
    print(f"Группа: {args.group} | коды нарушений: {codes}")

    rows = load_manifest(args.manifest)
    train_rows, val_rows, test_rows = split_by_study(
        rows, val_frac=args.val_frac, test_frac=args.test_frac, seed=args.seed
    )

    train_ds = QualityDataset(
        train_rows, group=args.group, image_size=args.image_size, augment=True
    )
    val_ds = QualityDataset(
        val_rows, group=args.group, image_size=args.image_size, augment=False
    )
    print(
        f"Аугментация (яркость/контраст) train_ds: {train_ds.augment}"
    )  # должно быть True
    print(f"train={len(train_ds)} val={len(val_ds)} (после фильтрации excluded_reason)")

    if len(val_ds) == 0 or len(train_ds) == 0:
        raise SystemExit(
            "Пустая train или val выборка для этой группы -- увеличьте val_frac "
            "или проверьте, что в манифесте достаточно строк с region для этой группы."
        )

    n_pos_train = sum(int(r["quality_class"]) for r in train_ds.rows)
    n_pos_val = sum(int(r["quality_class"]) for r in val_ds.rows)
    print(
        f"Нарушений в train: {n_pos_train}/{len(train_ds)} "
        f"({100 * n_pos_train / len(train_ds):.0f}%) | "
        f"в val: {n_pos_val}/{len(val_ds)} ({100 * n_pos_val / len(val_ds):.0f}%)"
    )

    train_loader = DataLoader(
        train_ds, batch_size=args.batch_size, shuffle=True, num_workers=args.num_workers
    )
    val_loader = DataLoader(
        val_ds, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers
    )

    model = build_model(num_labels=len(codes), pretrained=not args.no_pretrained).to(
        device
    )

    # pos_weight по каждому лейблу отдельно -- ключевая мера борьбы с дисбалансом
    # классов (п.8.1 ТЗ прямо просит объяснить, как обрабатывается дисбаланс).
    # Считается ТОЛЬКО по train, чтобы не заглядывать в val.
    train_targets = np.stack(
        [train_ds[i]["violations"].numpy() for i in range(len(train_ds))]
    )
    pos_counts = train_targets.sum(axis=0)
    neg_counts = len(train_ds) - pos_counts
    pos_weight = torch.tensor(
        [neg / pos if pos > 0 else 1.0 for pos, neg in zip(pos_counts, neg_counts)],
        dtype=torch.float32,
    ).to(device)
    print(f"pos_weight по лейблам {codes}: {pos_weight.tolist()}")

    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)

    best_val_f1 = -1.0
    out_path.parent.mkdir(parents=True, exist_ok=True)

    for epoch in range(1, args.epochs + 1):
        train_loss, train_probs, train_targets_ep = run_epoch(
            model, train_loader, criterion, device, optimizer
        )
        val_loss, val_probs, val_targets = run_epoch(
            model, val_loader, criterion, device
        )

        val_metrics = compute_metrics(val_probs, val_targets, codes)

        print(
            f"[{epoch:02d}/{args.epochs}] "
            f"train_loss={train_loss:.4f} | val_loss={val_loss:.4f} "
            f"val_macroF1={val_metrics['macro_f1']:.3f}"
        )

        if val_metrics["macro_f1"] > best_val_f1:
            best_val_f1 = val_metrics["macro_f1"]
            torch.save(
                {
                    "model_state_dict": model.state_dict(),
                    "val_macro_f1": best_val_f1,
                    "epoch": epoch,
                    "group": args.group,
                    "violation_codes": codes,
                },
                out_path,
            )
            print(
                f"  -> новый лучший чекпоинт: {out_path} (val_macroF1={best_val_f1:.3f})"
            )

    print(f"\nЛучший val_macroF1: {best_val_f1:.3f}")
    print("\nФинальные per-label метрики (последняя эпоха, val):")
    final_metrics = compute_metrics(val_probs, val_targets, codes)
    for code, m in final_metrics["per_label"].items():
        auc_str = (
            f"{m['roc_auc']:.3f}"
            if m["roc_auc"] is not None
            else "н/д (один класс в val)"
        )
        print(f"  {code}: F1={m['f1']:.3f} ROC-AUC={auc_str}")

    print(f"\nАгрегированный quality_class (есть хоть одно нарушение):")
    print(
        f"  sensitivity (чувствительность к нарушениям): {final_metrics['quality_sensitivity']}"
    )
    print(
        f"  specificity (для качественных снимков): {final_metrics['quality_specificity']}"
    )
    print(
        f"  TP={final_metrics['quality_tp']} FN={final_metrics['quality_fn']} "
        f"TN={final_metrics['quality_tn']} FP={final_metrics['quality_fp']}"
    )


if __name__ == "__main__":
    main()
