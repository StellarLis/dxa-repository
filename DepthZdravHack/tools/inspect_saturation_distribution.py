"""
Смотрим на полное распределение saturation_fraction по всем снимкам бедра --
и обычным, и 3 известным протезам -- чтобы выбрать порог осознанно, а не
проверять только "проходит/не проходит" при одном фиксированном значении.

Запуск:
    python tools/inspect_saturation_distribution.py --manifest data/manifest.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.hip.prosthesis_detector import (
    estimate_prosthesis_likelihood,
)  # noqa: E402
from backend.data.manifest_dataset import load_manifest  # noqa: E402
from backend.io.dicom_loader import DicomLoadError, load_dicom  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="data/manifest.csv")
    args = parser.parse_args()

    rows = load_manifest(args.manifest)
    hip_rows = [r for r in rows if r["region"] in ("hip_left", "hip_right")]

    normal_values = []
    prosthesis_values = []

    for row in hip_rows:
        try:
            study = load_dicom(row["image_path"])
        except DicomLoadError:
            continue
        result = estimate_prosthesis_likelihood(study.pixel_array)
        is_prosthesis = row["excluded_reason"].strip() == "hip_endoprosthesis"
        if is_prosthesis:
            prosthesis_values.append(result.saturation_fraction)
        elif not row["excluded_reason"].strip():
            normal_values.append(result.saturation_fraction)

    normal_values.sort()
    n = len(normal_values)

    print(f"Обычные снимки бедра (n={n}):")
    print(f"  min={normal_values[0]:.3f}  max={normal_values[-1]:.3f}")
    print(
        f"  перцентили: 50%={normal_values[n // 2]:.3f}  90%={normal_values[int(n * 0.9)]:.3f}  "
        f"95%={normal_values[int(n * 0.95)]:.3f}  99%={normal_values[min(n - 1, int(n * 0.99))]:.3f}"
    )
    print(f"  топ-10 самых высоких значений (ближе всего к протезу по этому признаку):")
    for v in normal_values[-10:]:
        print(f"    {v:.3f}")

    print(f"\nИзвестные протезы (n={len(prosthesis_values)}):")
    for v in sorted(prosthesis_values):
        print(f"  {v:.3f}")

    print(
        "\nВыбирайте порог между верхним хвостом обычных снимков и нижним "
        "значением протезов -- если они не пересекаются, порог очевиден; "
        "если пересекаются, идеального порога нет, придётся выбирать компромисс."
    )


if __name__ == "__main__":
    main()
