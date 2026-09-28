"""
CLI для пакетной обработки DICOM-исследований через весь пайплайн --
финальная точка входа, вокруг которой строится API/веб-интерфейс.

Формат выходной таблицы -- ровно по п.2.5 ТЗ:
    path_to_study, study_uid, image_uid, anatomical_region,
    quality_class, violation_type, processing_status, time_of_processing

Запуск:
    python tools/run_pipeline.py \
        --input data/raw/Исследования \
        --routing_checkpoint models/routing_best.pt \
        --spine_checkpoint models/quality_spine_best.pt \
        --hip_checkpoint models/quality_hip_best.pt \
        --output results.xlsx

--input может быть:
  - папкой с исследованиями (рекурсивно ищет все .dcm, как build_contact_sheets.py)
  - одним .dcm файлом
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.pipeline.quality_pipeline import QualityPipeline  # noqa: E402


def find_dcm_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    return sorted(input_path.rglob("*.dcm"))


def write_results_xlsx(results: list, out_path: Path) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "results"
    headers = [
        "path_to_study",
        "study_uid",
        "image_uid",
        "anatomical_region",
        "quality_class",
        "violation_type",
        "comment",
        "processing_status",
        "time_of_processing",
    ]
    ws.append(headers)
    for r in results:
        ws.append(
            [
                r.path_to_study,
                r.study_uid,
                r.image_uid,
                r.anatomical_region,
                r.quality_class if r.quality_class is not None else "",
                r.violation_type,
                r.comment,
                r.processing_status,
                round(r.time_of_processing, 3),
            ]
        )
    wb.save(out_path)


def write_results_csv(results: list, out_path: Path) -> None:
    import csv

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "path_to_study",
                "study_uid",
                "image_uid",
                "anatomical_region",
                "quality_class",
                "violation_type",
                "comment",
                "processing_status",
                "time_of_processing",
            ]
        )
        for r in results:
            writer.writerow(
                [
                    r.path_to_study,
                    r.study_uid,
                    r.image_uid,
                    r.anatomical_region,
                    r.quality_class if r.quality_class is not None else "",
                    r.violation_type,
                    r.comment,
                    r.processing_status,
                    round(r.time_of_processing, 3),
                ]
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input", required=True, help="папка с исследованиями или один .dcm файл"
    )
    parser.add_argument("--routing_checkpoint", default="models/routing_best.pt")
    parser.add_argument("--spine_checkpoint", default="models/quality_spine_best.pt")
    parser.add_argument("--hip_checkpoint", default="models/quality_hip_best.pt")
    parser.add_argument("--output", default="results.xlsx")
    parser.add_argument(
        "--nn_threshold_positioning",
        type=float,
        default=None,
        help="порог для incorrect_positioning (по умолчанию -- откалиброванный)",
    )
    parser.add_argument(
        "--nn_threshold_artifact",
        type=float,
        default=None,
        help="порог для foreign_object_or_artifact (по умолчанию -- откалиброванный)",
    )
    parser.add_argument(
        "--nn_threshold_rotation",
        type=float,
        default=None,
        help="порог для rotation_error (по умолчанию -- откалиброванный)",
    )
    parser.add_argument("--axis_tilt_threshold_degrees", type=float, default=None)
    parser.add_argument("--hip_roi_margin_threshold_mm", type=float, default=None)
    args = parser.parse_args()

    input_path = Path(args.input)
    files = find_dcm_files(input_path)
    print(f"Найдено файлов для обработки: {len(files)}")
    if not files:
        print("Нет .dcm файлов по указанному пути -- проверьте --input")
        return

    print("Загружаю модели...")
    nn_thresholds_override = {}
    if args.nn_threshold_positioning is not None:
        nn_thresholds_override["incorrect_positioning"] = args.nn_threshold_positioning
    if args.nn_threshold_artifact is not None:
        nn_thresholds_override["foreign_object_or_artifact"] = (
            args.nn_threshold_artifact
        )
    if args.nn_threshold_rotation is not None:
        nn_thresholds_override["rotation_error"] = args.nn_threshold_rotation

    pipeline_kwargs = dict(
        routing_checkpoint=args.routing_checkpoint,
        spine_quality_checkpoint=args.spine_checkpoint,
        hip_quality_checkpoint=args.hip_checkpoint,
    )
    if nn_thresholds_override:
        # частичное переопределение -- остальные берутся из откалиброванных по умолчанию
        from backend.pipeline.quality_pipeline import DEFAULT_NN_THRESHOLDS

        merged = dict(DEFAULT_NN_THRESHOLDS)
        merged.update(nn_thresholds_override)
        pipeline_kwargs["nn_thresholds"] = merged
    if args.axis_tilt_threshold_degrees is not None:
        pipeline_kwargs["axis_tilt_threshold_degrees"] = (
            args.axis_tilt_threshold_degrees
        )
    if args.hip_roi_margin_threshold_mm is not None:
        pipeline_kwargs["hip_roi_margin_threshold_mm"] = (
            args.hip_roi_margin_threshold_mm
        )

    pipeline = QualityPipeline(**pipeline_kwargs)

    results = []
    t0 = time.monotonic()
    for i, f in enumerate(files, 1):
        result = pipeline.process_file(str(f))
        results.append(result)
        status_marker = "OK" if result.processing_status == "Success" else "FAIL"
        print(
            f"[{i}/{len(files)}] {status_marker} {f.name} "
            f"region={result.anatomical_region} quality_class={result.quality_class} "
            f"violations={result.violation_type} ({result.time_of_processing:.2f}s)"
        )
        if result.processing_status == "Failure":
            print(f"    ошибка: {result.error_message}")

    total_time = time.monotonic() - t0
    n_success = sum(1 for r in results if r.processing_status == "Success")
    n_failure = len(results) - n_success
    n_violations = sum(1 for r in results if r.quality_class == 1)

    print(f"\nОбработано: {len(results)} | успешно: {n_success} | ошибок: {n_failure}")
    print(f"С нарушениями качества: {n_violations}/{n_success}")
    print(
        f"Общее время: {total_time:.1f}с | среднее на файл: {total_time / len(results):.2f}с"
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix == ".csv":
        write_results_csv(results, out_path)
    else:
        write_results_xlsx(results, out_path)
    print(f"\nРезультаты сохранены: {out_path}")


if __name__ == "__main__":
    main()
