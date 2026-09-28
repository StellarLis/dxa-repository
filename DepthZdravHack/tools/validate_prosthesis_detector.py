"""
Проверка детектора эндопротеза на реальных данных.

Положительные примеры (протез) -- строки манифеста с excluded_reason ==
"hip_endoprosthesis" (их обнаружил build_manifest.py по комментарию эксперта
в разметка.xlsx). Отрицательные -- все остальные размеченные снимки бедра.

Важная оговорка: положительных примеров всего 3 на весь датасет -- любые
метрики на такой выборке крайне грубые (одна ошибка = 33% п.п.). Это скорее
дымовой тест "не полная ли это ерунда", а не надёжная статистика.

Запуск:
    python tools/validate_prosthesis_detector.py --manifest data/manifest.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.hip.prosthesis_detector import estimate_prosthesis_likelihood  # noqa: E402
from backend.data.manifest_dataset import load_manifest  # noqa: E402
from backend.io.dicom_loader import DicomLoadError, load_dicom  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="data/manifest.csv")
    args = parser.parse_args()

    rows = load_manifest(args.manifest)
    hip_rows = [r for r in rows if r["region"] in ("hip_left", "hip_right")]

    tp = fn = tn = fp = 0
    print("Известные случаи протеза (excluded_reason=hip_endoprosthesis):")
    for row in hip_rows:
        is_true_prosthesis = row["excluded_reason"].strip() == "hip_endoprosthesis"
        if not is_true_prosthesis and row["excluded_reason"].strip():
            continue  # прочие исключения (если появятся) -- не участвуют в проверке

        try:
            study = load_dicom(row["image_path"])
        except DicomLoadError as exc:
            print(f"[SKIP] {row['image_path']}: {exc}")
            continue

        result = estimate_prosthesis_likelihood(study.pixel_array)

        if is_true_prosthesis:
            marker = "OK " if result.is_likely_prosthesis else "MISS"
            print(
                f"  [{marker}] {row['image_path']} -- "
                f"saturation={result.saturation_fraction:.3f} texture={result.texture_score:.5f} "
                f"predicted={result.is_likely_prosthesis}"
            )
            if result.is_likely_prosthesis:
                tp += 1
            else:
                fn += 1
        else:
            if result.is_likely_prosthesis:
                fp += 1
            else:
                tn += 1

    print(f"\nПротезы (n={tp + fn}): поймано {tp}, пропущено {fn}")
    print(f"Обычные снимки бедра (n={tn + fp}): верно {tn}, ложных срабатываний {fp}")
    if fp > 0:
        print("\n[ВНИМАНИЕ] есть ложные срабатывания на обычных снимках -- разберите ниже, какие именно.")


if __name__ == "__main__":
    main()
