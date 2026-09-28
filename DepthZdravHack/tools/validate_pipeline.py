"""
Честная проверка ИТОГОВОГО quality_class всего пайплайна (routing + geometry +
neural nets + агрегация через ИЛИ) против реальной экспертной разметки.

Важная оговорка при интерпретации результата: часть критериев (нейросети)
обучались НА ЧАСТИ этих же файлов (train split) -- то есть для них эта проверка
не полностью честная (учитель немного "подсматривал" ответы). А вот для
геометрических критериев (axis_tilt, roi_incorrect) это полностью честная
проверка -- они не обучались вообще ни на одном примере. Тем не менее, эта
проверка -- лучшее, что у нас есть для оценки ЦЕЛОГО пайплайна как системы, а
не отдельных компонентов по кускам.

Запуск:
    python tools/validate_pipeline.py \
        --manifest data/manifest.csv \
        --routing_checkpoint models/routing_best.pt \
        --spine_checkpoint models/quality_spine_best.pt \
        --hip_checkpoint models/quality_hip_best.pt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import confusion_matrix, f1_score

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.data.manifest_dataset import load_manifest  # noqa: E402
from backend.pipeline.quality_pipeline import QualityPipeline  # noqa: E402


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% доверительный интервал Уилсона для доли k/n.

    Обычное приближение (p +/- z*sqrt(p(1-p)/n)) плохо работает на малых n
    и ломается на вырожденных случаях (p=0 или p=1, что у нас реально
    встречается -- например, sensitivity=1.0 при 19 примерах). Интервал
    Уилсона устойчив в обоих случаях и рекомендован для именно такого рода
    клинических метрик (sensitivity/specificity на некрупных выборках).
    """
    if n == 0:
        return None
    p = k / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def bootstrap_f1_ci(
    y_true: list[int], y_pred: list[int], n_boot: int = 2000, seed: int = 42
) -> tuple[float, float] | None:
    """95% доверительный интервал для F1 через бутстрэп (перцентильный метод).

    F1 не имеет простой аналитической формулы для доверительного интервала --
    вместо этого много раз пересэмплируем пары (true, pred) со случайным
    повторением (сохраняя связь между true и pred для каждого примера) и
    смотрим на разброс F1 по этим пересэмплированным версиям выборки.
    """
    if not y_true:
        return None
    rng = np.random.default_rng(seed)
    y_true_arr = np.array(y_true)
    y_pred_arr = np.array(y_pred)
    n = len(y_true_arr)

    scores = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        f1 = f1_score(y_true_arr[idx], y_pred_arr[idx], zero_division=0)
        scores.append(f1)

    return float(np.percentile(scores, 2.5)), float(np.percentile(scores, 97.5))


def _fmt_ci(ci: tuple[float, float] | None) -> str:
    if ci is None:
        return "н/д"
    return f"[{ci[0]:.3f}, {ci[1]:.3f}]"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="data/manifest.csv")
    parser.add_argument("--routing_checkpoint", default="models/routing_best.pt")
    parser.add_argument("--spine_checkpoint", default="models/quality_spine_best.pt")
    parser.add_argument("--hip_checkpoint", default="models/quality_hip_best.pt")
    args = parser.parse_args()

    rows = load_manifest(args.manifest)
    rows = [r for r in rows if not r["excluded_reason"].strip()]
    print(f"Примеров для проверки (после исключения эндопротезов): {len(rows)}")

    pipeline = QualityPipeline(
        routing_checkpoint=args.routing_checkpoint,
        spine_quality_checkpoint=args.spine_checkpoint,
        hip_quality_checkpoint=args.hip_checkpoint,
    )

    y_true, y_pred = [], []
    region_correct = 0
    per_region_true = {"spine": [], "hip_left": [], "hip_right": []}
    per_region_pred = {"spine": [], "hip_left": [], "hip_right": []}

    for row in rows:
        result = pipeline.process_file(row["image_path"])
        if result.processing_status != "Success":
            print(
                f"[SKIP, ошибка обработки] {row['image_path']}: {result.error_message}"
            )
            continue

        true_region = row["region"]
        if result.anatomical_region == true_region:
            region_correct += 1

        true_quality = int(row["quality_class"])
        pred_quality = result.quality_class if result.quality_class is not None else 0

        y_true.append(true_quality)
        y_pred.append(pred_quality)

        if true_region in per_region_true:
            per_region_true[true_region].append(true_quality)
            per_region_pred[true_region].append(pred_quality)

    print(
        f"\nRouting-точность (region совпал с разметкой): {region_correct}/{len(rows)}"
    )

    print("\n" + "=" * 60)
    print("ИТОГОВЫЙ quality_class -- пайплайн целиком vs эксперт")
    print("=" * 60)
    _report("ВСЕ ОБЛАСТИ", y_true, y_pred)

    for region in ("spine", "hip_left", "hip_right"):
        print(f"\n--- отдельно {region} ---")
        _report(region, per_region_true[region], per_region_pred[region])


def _report(label: str, y_true: list[int], y_pred: list[int]) -> None:
    if not y_true:
        print(f"{label}: нет данных")
        return
    f1 = f1_score(y_true, y_pred, zero_division=0)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    accuracy = (tp + tn) / len(y_true)
    sensitivity = tp / (tp + fn) if (tp + fn) > 0 else None
    specificity = tn / (tn + fp) if (tn + fp) > 0 else None

    sens_ci = wilson_ci(tp, tp + fn) if (tp + fn) > 0 else None
    spec_ci = wilson_ci(tn, tn + fp) if (tn + fp) > 0 else None
    acc_ci = wilson_ci(tp + tn, len(y_true))
    f1_ci = bootstrap_f1_ci(y_true, y_pred)

    print(f"n={len(y_true)} (нарушений по эксперту: {sum(y_true)})")
    print(f"F1={f1:.3f} 95%CI={_fmt_ci(f1_ci)}")
    print(f"Accuracy={accuracy:.3f} 95%CI={_fmt_ci(acc_ci)}")
    print(
        f"Sensitivity={sensitivity:.3f} 95%CI={_fmt_ci(sens_ci)}"
        if sensitivity is not None
        else "Sensitivity=н/д"
    )
    print(
        f"Specificity={specificity:.3f} 95%CI={_fmt_ci(spec_ci)}"
        if specificity is not None
        else "Specificity=н/д"
    )
    print(f"TP={tp} FN={fn} TN={tn} FP={fp}")


if __name__ == "__main__":
    main()
