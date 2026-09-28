"""
Сборка единого training-манифеста из двух источников разметки:

1. routing_labels.csv  -- какой файл к какой анатомической области относится
   (study_uid, relative_path, region), заполняется вручную по contact sheet'ам.
2. разметка.xlsx        -- экспертная оценка качества по (study, область):
   бинарные критерии + агрегированный quality_class, вердикт по каждой области.

На выходе -- manifest.csv с одной строкой на РАЗМЕЧЕННЫЙ файл:
    image_path, study_uid, region, quality_class, violation_type, excluded_reason

Строки с пустым region в routing_labels.csv (неразмеченные дубли) пропускаются --
они не входят в обучающую выборку вообще.

Если экспертной оценки по (study, область) нет (например, из-за эндопротеза --
обычные критерии качества к нему неприменимы), строка ВСЁ РАВНО попадает
в манифест, но с заполненным excluded_reason и пустым quality_class -- чтобы
такие случаи не терялись молча, а сознательно фильтровались перед обучением
(df[df.excluded_reason == ""]) и были на виду при описании выборки на защите.

Запуск:
    python tools/build_manifest.py \
        data/raw/routing_labels.csv \
        data/raw/разметка.xlsx \
        data/raw/Исследования \
        data/manifest.csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import openpyxl

# Соответствие между колонками разметка.xlsx и (регион -> критерии).
# Каждый критерий: (буква колонки в листе "Калибровка", человекочитаемый код нарушения)
SPINE_CRITERIA = [
    ("C", "incorrect_positioning"),  # корректная укладка
    ("D", "axis_tilt_over_5deg"),  # ось позвоночника, допустимый наклон 5°
    ("E", "foreign_object_or_artifact"),  # посторонние предметы/артефакты
]
HIP_CRITERIA = [
    ("rotation", "rotation_error"),  # позиционирование/ротация
    ("roi", "roi_incorrect"),  # корректность области интереса
]
# для бедра колонки разные для left/right, задаём отдельно ниже

REGION_TO_ITOG_COL = {
    "spine": "J",
    "hip_right": "K",
    "hip_left": "L",
}

HIP_COLUMN_LETTERS = {
    "hip_right": {"rotation": "F", "roi": "G"},
    "hip_left": {"rotation": "H", "roi": "I"},
}

COL_LETTER_TO_IDX = {chr(ord("A") + i): i for i in range(26)}  # A=0, B=1, ...


def _infer_exclusion_reason(comment: str | None) -> str:
    """Определяет причину отсутствия экспертной метки по комментарию в разметка.xlsx.

    Сейчас распознаём эндопротезирование (меняет анатомию, обычные критерии
    качества неприменимы) -- это основной наблюдаемый в данных случай.
    Всё остальное помечается как "no_expert_label" -- строка сохраняется
    в манифесте, но требует ручной проверки перед использованием в обучении.
    """
    text = (comment or "").lower()
    if "эндопротез" in text:
        return "hip_endoprosthesis"
    return "no_expert_label"


def load_quality_labels(xlsx_path: str) -> dict:
    """Возвращает {study_uid: {region: {quality_class, violation_codes, excluded_reason}}}.

    Если экспертный итог по области отсутствует (клетка J/K/L пустая), запись
    всё равно создаётся, но quality_class=None и заполняется excluded_reason --
    такие строки не выбрасываются молча, а идут в манифест помеченными, чтобы
    осознанно исключить их на этапе обучения и не потерять из виду на защите.
    """
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb["Калибровка"]

    result = {}
    for row in ws.iter_rows(min_row=3, values_only=True):
        study_uid = row[1]
        if not study_uid:
            continue

        comment = row[COL_LETTER_TO_IDX["M"]]
        entry = {}

        # позвоночник
        spine_flags = []
        for col_letter, code in SPINE_CRITERIA:
            idx = COL_LETTER_TO_IDX[col_letter]
            if row[idx] == 1:
                spine_flags.append(code)
        spine_itog = row[COL_LETTER_TO_IDX["J"]]
        if spine_itog is not None:
            entry["spine"] = {
                "quality_class": int(spine_itog),
                "violation_codes": spine_flags,
                "excluded_reason": "",
            }
        else:
            entry["spine"] = {
                "quality_class": None,
                "violation_codes": [],
                "excluded_reason": _infer_exclusion_reason(comment),
            }

        # бедра
        for region in ("hip_right", "hip_left"):
            flags = []
            for crit_key, col_letter in HIP_COLUMN_LETTERS[region].items():
                idx = COL_LETTER_TO_IDX[col_letter]
                code = dict(HIP_CRITERIA)[crit_key]
                if row[idx] == 1:
                    flags.append(code)
            itog_col = REGION_TO_ITOG_COL[region]
            itog_val = row[COL_LETTER_TO_IDX[itog_col]]
            if itog_val is not None:
                entry[region] = {
                    "quality_class": int(itog_val),
                    "violation_codes": flags,
                    "excluded_reason": "",
                }
            else:
                entry[region] = {
                    "quality_class": None,
                    "violation_codes": [],
                    "excluded_reason": _infer_exclusion_reason(comment),
                }

        result[str(study_uid)] = entry

    return result


ALLOWED_REGIONS = {"spine", "hip_left", "hip_right"}


def build_manifest(
    routing_csv: str, xlsx_path: str, studies_root: str, out_csv: str
) -> None:
    quality_labels = load_quality_labels(xlsx_path)
    studies_root = Path(studies_root)

    manifest_rows = []
    skipped_no_region = 0
    skipped_region_not_in_study = 0
    skipped_unrecognized_region = []

    with open(routing_csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            region = row["region"].strip()
            if not region:
                skipped_no_region += 1
                continue

            if region not in ALLOWED_REGIONS:
                # значение вроде "error" -- не опечатка в spine/hip_*, а осознанная
                # пометка проблемного файла человеком. Не молчим и не пытаемся
                # угадать -- откладываем в сторону для ручной проверки.
                skipped_unrecognized_region.append(row)
                continue

            study_uid = row["study_uid"]
            study_labels = quality_labels.get(study_uid, {})
            if region not in study_labels:
                # такого не должно быть при консистентных данных -- значит в
                # разметка.xlsx вообще нет строки для этого study_uid
                skipped_region_not_in_study += 1
                print(f"[WARN] study={study_uid} отсутствует в разметка.xlsx целиком")
                continue

            label = study_labels[region]
            # relative_path приходит из CSV, отредактированного на Windows (разделитель \) --
            # нормализуем в POSIX-стиль (/), иначе путь развалится при запуске в
            # Linux-контейнере, как того требует финальное развёртывание (п.3.2 ТЗ)
            normalized_rel_path = row["relative_path"].replace("\\", "/")
            image_path = studies_root / study_uid / normalized_rel_path

            manifest_rows.append(
                {
                    "image_path": str(image_path),
                    "study_uid": study_uid,
                    "region": region,
                    "quality_class": (
                        label["quality_class"]
                        if label["quality_class"] is not None
                        else ""
                    ),
                    "violation_type": ";".join(label["violation_codes"]),
                    "excluded_reason": label["excluded_reason"],
                }
            )

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "image_path",
                "study_uid",
                "region",
                "quality_class",
                "violation_type",
                "excluded_reason",
            ],
        )
        writer.writeheader()
        writer.writerows(manifest_rows)

    usable = [r for r in manifest_rows if not r["excluded_reason"]]
    excluded = [r for r in manifest_rows if r["excluded_reason"]]

    print(f"\nСобрано строк манифеста всего: {len(manifest_rows)}")
    print(f"  из них пригодны для обучения: {len(usable)}")
    print(f"  из них исключены (excluded_reason заполнен): {len(excluded)}")
    if excluded:
        from collections import Counter

        print(
            "  причины исключения:",
            dict(Counter(r["excluded_reason"] for r in excluded)),
        )
    print(f"Пропущено (region не заполнен в routing_labels.csv): {skipped_no_region}")
    print(f"Пропущено (study_uid нет в разметка.xlsx): {skipped_region_not_in_study}")
    if skipped_unrecognized_region:
        print(
            f"\n[ТРЕБУЕТ ВНИМАНИЯ] Нераспознанные значения region ({len(skipped_unrecognized_region)}):"
        )
        for r in skipped_unrecognized_region:
            print(
                f"  study={r['study_uid']} path={r['relative_path']} region={r['region']!r}"
            )

    n_violations = sum(1 for r in usable if r["quality_class"] == 1)
    print(f"\nИз пригодных строк с нарушением качества: {n_violations} / {len(usable)}")
    print(f"\nМанифест сохранён: {out_csv}")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(
            "Использование: python build_manifest.py "
            "<routing_labels.csv> <разметка.xlsx> <studies_root> <out_manifest.csv>"
        )
        sys.exit(1)
    build_manifest(*sys.argv[1:])
