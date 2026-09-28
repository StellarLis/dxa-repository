"""
Чистка routing_labels.csv перед сборкой манифеста.

Убирает две категории строк:
1. Пустой region -- неразмеченные дубли (тот же снимок, что уже размечен
   под другим relative_path в этом же study). Они физически не нужны:
   один представитель на область в исследовании достаточно.
2. Нераспознанные пометки (например "error") -- аномальные файлы, которые
   человек открыл и не смог отнести ни к одной анатомической области
   (не читается нормально / изображено не то, что ожидалось). Такие файлы
   не участвуют ни в routing, ни в quality-обучении -- в датасете им не место,
   а не "по ошибке забыли разметить".

Запуск:
    python tools/clean_routing_labels.py \
        data/raw/routing_labels.csv \
        data/raw/routing_labels_clean.csv
"""

from __future__ import annotations

import csv
import sys

ALLOWED_REGIONS = {"spine", "hip_left", "hip_right"}


def clean(in_csv: str, out_csv: str) -> None:
    with open(in_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    kept = []
    dropped_empty = 0
    dropped_anomalous = []

    for row in rows:
        region = row["region"].strip()
        if not region:
            dropped_empty += 1
            continue
        if region not in ALLOWED_REGIONS:
            dropped_anomalous.append(row)
            continue
        kept.append(row)

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["study_uid", "relative_path", "region"])
        writer.writeheader()
        writer.writerows(kept)

    print(f"Исходных строк: {len(rows)}")
    print(f"Оставлено (валидная разметка): {len(kept)}")
    print(f"Убрано (пустой region, неразмеченные дубли): {dropped_empty}")
    print(f"Убрано (аномальные/нераспознанные пометки): {len(dropped_anomalous)}")
    for r in dropped_anomalous:
        print(
            f"  study={r['study_uid']} path={r['relative_path']} region={r['region']!r}"
        )
    print(f"\nСохранено: {out_csv}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Использование: python clean_routing_labels.py <in.csv> <out.csv>")
        sys.exit(1)
    clean(sys.argv[1], sys.argv[2])
