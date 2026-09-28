"""
Калибровка порогов принятия решения по каждому критерию отдельно.

Сейчас пайплайн использует "круглые" пороги: 0.5 для вероятности нейросети,
5.0 градусов и 20мм -- как буквально написано в ТЗ. Но эти числа не обязательно
оптимальны именно для НАШИХ конкретных детекторов -- особенно для геометрии
ROI, которая измеряет не точную "область интереса" из софта денситометра, а её
приближение (bounding box кости), так что "20мм" на этом приближении может не
соответствовать "20мм" в исходном определении критерия.

ВАЖНО про честность: пороги подбираются ТОЛЬКО на train-части (тот же
train/val split, что и при обучении моделей, seed=42) -- чтобы не настраивать
решающее правило на тех же данных, на которых потом будем его проверять.
Финальную проверку с новыми порогами нужно делать на val/на всём датасете
через validate_pipeline.py отдельно.

Запуск:
    python tools/tune_thresholds.py \
        --manifest data/manifest.csv \
        --spine_checkpoint models/quality_spine_best.pt \
        --hip_checkpoint models/quality_hip_best.pt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import f1_score

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.hip.roi_geometry import estimate_hip_roi_margins  # noqa: E402
from backend.analysis.spine.axis_geometry import estimate_spine_axis_angle  # noqa: E402
from backend.data.manifest_dataset import load_manifest, split_by_study  # noqa: E402
from backend.io.dicom_loader import DicomLoadError, load_dicom  # noqa: E402
from backend.pipeline.quality_pipeline import QualityPredictor  # noqa: E402


def sweep_thresholds_above(
    y_true: list[int], score: list[float], min_sensitivity: float = 0.0
) -> list[dict]:
    """Перебирает пороги для критерия вида 'нарушение, если score >= T'
    (вероятность нейросети, угол наклона). Возвращает таблицу метрик по
    кандидатам-порогам, отсортированную по F1 (лучшие сверху)."""
    y_true_arr = np.array(y_true)
    score_arr = np.array(score)
    candidates = sorted(set(score_arr.tolist()))

    rows = []
    for t in candidates:
        pred = (score_arr >= t).astype(int)
        tp = int(((pred == 1) & (y_true_arr == 1)).sum())
        fn = int(((pred == 0) & (y_true_arr == 1)).sum())
        tn = int(((pred == 0) & (y_true_arr == 0)).sum())
        fp = int(((pred == 1) & (y_true_arr == 0)).sum())
        sens = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        spec = tn / (tn + fp) if (tn + fp) > 0 else 0.0
        f1 = f1_score(y_true_arr, pred, zero_division=0)
        rows.append({"threshold": t, "sensitivity": sens, "specificity": spec, "f1": f1})

    rows.sort(key=lambda r: r["f1"], reverse=True)
    qualifying = [r for r in rows if r["sensitivity"] >= min_sensitivity]
    best = qualifying[0] if qualifying else rows[0]
    return rows, best


def sweep_thresholds_below(
    y_true: list[int], score: list[float], min_sensitivity: float = 0.0
) -> tuple[list[dict], dict]:
    """То же самое, но для критерия вида 'нарушение, если score < T' (отступ в мм:
    чем меньше отступ, тем вероятнее нарушение)."""
    y_true_arr = np.array(y_true)
    score_arr = np.array(score)
    candidates = sorted(set(score_arr.tolist()))

    rows = []
    for t in candidates:
        pred = (score_arr < t).astype(int)
        tp = int(((pred == 1) & (y_true_arr == 1)).sum())
        fn = int(((pred == 0) & (y_true_arr == 1)).sum())
        tn = int(((pred == 0) & (y_true_arr == 0)).sum())
        fp = int(((pred == 1) & (y_true_arr == 0)).sum())
        sens = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        spec = tn / (tn + fp) if (tn + fp) > 0 else 0.0
        f1 = f1_score(y_true_arr, pred, zero_division=0)
        rows.append({"threshold": t, "sensitivity": sens, "specificity": spec, "f1": f1})

    rows.sort(key=lambda r: r["f1"], reverse=True)
    qualifying = [r for r in rows if r["sensitivity"] >= min_sensitivity]
    best = qualifying[0] if qualifying else rows[0]
    return rows, best


def print_top(label: str, rows: list[dict], best: dict, default_threshold: float) -> None:
    print(f"\n--- {label} ---")
    print(f"Топ-5 порогов по F1 (из перебора на train):")
    for r in rows[:5]:
        print(
            f"  T={r['threshold']:.3f}  F1={r['f1']:.3f}  "
            f"sensitivity={r['sensitivity']:.3f}  specificity={r['specificity']:.3f}"
        )
    print(f"РЕКОМЕНДОВАННЫЙ порог (F1 при sensitivity >= 0.8): T={best['threshold']:.3f}")
    print(f"  (текущий порог по умолчанию: {default_threshold})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="data/manifest.csv")
    parser.add_argument("--spine_checkpoint", default="models/quality_spine_best.pt")
    parser.add_argument("--hip_checkpoint", default="models/quality_hip_best.pt")
    parser.add_argument("--val_frac", type=float, default=0.2)
    parser.add_argument("--test_frac", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min_sensitivity", type=float, default=0.8)
    args = parser.parse_args()

    rows = load_manifest(args.manifest)
    rows = [r for r in rows if not r["excluded_reason"].strip()]
    train_rows, val_rows, _ = split_by_study(
        rows, val_frac=args.val_frac, test_frac=args.test_frac, seed=args.seed
    )
    print(f"Калибровка на train={len(train_rows)} (val={len(val_rows)} отложен для честной проверки)")

    import torch

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    spine_model = QualityPredictor(args.spine_checkpoint, device)
    hip_model = QualityPredictor(args.hip_checkpoint, device)

    # --- сбор continuous-скоров на train ---
    spine_true = {"incorrect_positioning": [], "foreign_object_or_artifact": [], "axis_tilt": []}
    spine_score = {"incorrect_positioning": [], "foreign_object_or_artifact": [], "axis_tilt": []}
    hip_true = {"rotation_error": [], "roi": []}
    hip_score = {"rotation_error": [], "roi": []}

    for row in train_rows:
        try:
            study = load_dicom(row["image_path"])
        except DicomLoadError:
            continue
        codes_present = set(row["violation_type"].split(";")) if row["violation_type"] else set()

        if row["region"] == "spine":
            probs = spine_model.predict(study.pixel_array)
            spine_true["incorrect_positioning"].append(int("incorrect_positioning" in codes_present))
            spine_score["incorrect_positioning"].append(probs["incorrect_positioning"])
            spine_true["foreign_object_or_artifact"].append(
                int("foreign_object_or_artifact" in codes_present)
            )
            spine_score["foreign_object_or_artifact"].append(probs["foreign_object_or_artifact"])

            axis_result = estimate_spine_axis_angle(study.pixel_array)
            spine_true["axis_tilt"].append(int("axis_tilt_over_5deg" in codes_present))
            spine_score["axis_tilt"].append(axis_result.angle_degrees)

        elif row["region"] in ("hip_left", "hip_right"):
            mirror = row["region"] == "hip_left"
            probs = hip_model.predict(study.pixel_array, mirror=mirror)
            hip_true["rotation_error"].append(int("rotation_error" in codes_present))
            hip_score["rotation_error"].append(probs["rotation_error"])

            roi_result = estimate_hip_roi_margins(study.pixel_array, study.pixel_spacing_mm)
            min_margin = min(roi_result.margin_left_mm, roi_result.margin_right_mm)
            hip_true["roi"].append(int("roi_incorrect" in codes_present))
            hip_score["roi"].append(min_margin)

    print("\n" + "=" * 60)
    print("SPINE")
    print("=" * 60)
    for code in ("incorrect_positioning", "foreign_object_or_artifact"):
        table, best = sweep_thresholds_above(
            spine_true[code], spine_score[code], args.min_sensitivity
        )
        print_top(code, table, best, default_threshold=0.5)

    table, best = sweep_thresholds_above(
        spine_true["axis_tilt"], spine_score["axis_tilt"], args.min_sensitivity
    )
    print_top("axis_tilt_over_5deg (геометрия, градусы)", table, best, default_threshold=5.0)

    print("\n" + "=" * 60)
    print("HIP")
    print("=" * 60)
    table, best = sweep_thresholds_above(
        hip_true["rotation_error"], hip_score["rotation_error"], args.min_sensitivity
    )
    print_top("rotation_error", table, best, default_threshold=0.5)

    table, best = sweep_thresholds_below(hip_true["roi"], hip_score["roi"], args.min_sensitivity)
    print_top("roi_incorrect (геометрия, min(лево,право) в мм)", table, best, default_threshold=20.0)


if __name__ == "__main__":
    main()
