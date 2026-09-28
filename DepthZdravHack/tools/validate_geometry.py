"""
Проверка геометрических эвристик (axis_geometry.py, roi_geometry.py) против
реальной экспертной разметки -- без всякого обучения модели, просто честный
прогон "что посчитала геометрия" vs "что сказал эксперт" на всём датасете.

Это ключевой шаг: сами по себе эвристики выглядят разумно (мы проверили их
визуально на паре образцов), но единственный способ узнать, действительно ли
они соответствуют тому, что эксперт понимал под "наклон оси > 5 градусов" или
"некорректный ROI" -- сравнить с реальными метками на большом числе примеров.

Запуск:
    python tools/validate_geometry.py --manifest data/manifest.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sklearn.metrics import confusion_matrix, f1_score

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.hip.roi_geometry import estimate_hip_roi_margins  # noqa: E402
from backend.analysis.spine.axis_geometry import estimate_spine_axis_angle  # noqa: E402
from backend.data.manifest_dataset import load_manifest  # noqa: E402
from backend.io.dicom_loader import DicomLoadError, load_dicom  # noqa: E402


def validate_spine(rows: list[dict]) -> None:
    print("=" * 60)
    print("SPINE: axis_tilt_over_5deg -- геометрия vs эксперт")
    print("=" * 60)

    y_true, y_pred = [], []
    low_confidence_count = 0

    for row in rows:
        if row["region"] != "spine" or row["excluded_reason"].strip():
            continue

        true_violation = "axis_tilt_over_5deg" in row["violation_type"].split(";")

        try:
            study = load_dicom(row["image_path"])
        except DicomLoadError as exc:
            print(f"[SKIP] {row['image_path']}: {exc}")
            continue

        result = estimate_spine_axis_angle(study.pixel_array)
        if result.confidence < 0.5:
            low_confidence_count += 1

        y_true.append(int(true_violation))
        y_pred.append(int(result.is_violation))

    _print_report("axis_tilt_over_5deg", y_true, y_pred)
    print(
        f"Снимков с низкой уверенностью сегментации (<50% строк): {low_confidence_count}/{len(y_true)}"
    )


def validate_hip(rows: list[dict]) -> None:
    print("\n" + "=" * 60)
    print("HIP: roi_incorrect -- геометрия vs эксперт")
    print("=" * 60)

    y_true, y_pred_full, y_pred_horizontal, y_pred_joint = [], [], [], []
    no_spacing_count = 0

    for row in rows:
        if (
            row["region"] not in ("hip_left", "hip_right")
            or row["excluded_reason"].strip()
        ):
            continue

        true_violation = "roi_incorrect" in row["violation_type"].split(";")

        try:
            study = load_dicom(row["image_path"])
        except DicomLoadError as exc:
            print(f"[SKIP] {row['image_path']}: {exc}")
            continue

        result = estimate_hip_roi_margins(study.pixel_array, study.pixel_spacing_mm)
        if study.pixel_spacing_mm is None:
            no_spacing_count += 1
            continue

        y_true.append(int(true_violation))
        y_pred_full.append(int(result.is_violation))
        y_pred_horizontal.append(int(result.is_violation_horizontal_only))
        y_pred_joint.append(int(result.is_violation_joint_region_only))

    print("\n--- Вариант A: все 4 стороны (верх/низ/лево/право) ---")
    _print_report("roi_incorrect (4 стороны)", y_true, y_pred_full)

    print("\n--- Вариант B: только лево/право, по всей кости ---")
    _print_report("roi_incorrect (лево/право)", y_true, y_pred_horizontal)

    print(
        "\n--- Вариант C: только лево/право, только по верхней половине (область сустава) ---"
    )
    _print_report("roi_incorrect (лево/право, сустав)", y_true, y_pred_joint)

    print(f"\nСнимков без восстановленного масштаба (пропущены): {no_spacing_count}")


def _print_report(label: str, y_true: list[int], y_pred: list[int]) -> None:
    if not y_true:
        print(f"Нет данных для оценки {label}")
        return

    f1 = f1_score(y_true, y_pred, zero_division=0)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    accuracy = (tp + tn) / len(y_true)
    sensitivity = tp / (tp + fn) if (tp + fn) > 0 else None
    specificity = tn / (tn + fp) if (tn + fp) > 0 else None

    print(f"\nВсего примеров: {len(y_true)} (нарушений по эксперту: {sum(y_true)})")
    print(f"F1: {f1:.3f} | Accuracy: {accuracy:.3f}")
    print(f"Sensitivity (нашли нарушение, когда оно есть): {sensitivity}")
    print(f"Specificity (не поднимаем ложную тревогу на норме): {specificity}")
    print(f"Confusion matrix: TP={tp} FN={fn} TN={tn} FP={fp}")
    print(
        "\nДля сравнения: тот же принцип, но эвристика оценивается на ВСЕХ размеченных\n"
        "примерах сразу (train+val), не только на отложенной выборке -- это честно, потому\n"
        "что эвристика ничему не обучалась ни на одном из этих примеров."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="data/manifest.csv")
    args = parser.parse_args()

    rows = load_manifest(args.manifest)
    validate_spine(rows)
    validate_hip(rows)


if __name__ == "__main__":
    main()
