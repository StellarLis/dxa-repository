"""
Генератор contact sheet'ов (сеток миниатюр) по каждому исследованию.

Проблема: разметка.xlsx даёт метки на уровне (study, анатомическая область),
но НЕ говорит, какой конкретно .dcm-файл внутри папки исследования относится
к какой области. Количество файлов в разных исследованиях разное (1, 3, 6, ...),
порядок файлов не гарантирует порядок областей -- значит, сопоставление
"файл -> область" нужно проставить вручную, глядя на изображения.

Реальная структура папок неоднородна и вложена на разную глубину, например:
    <study_uid>/series_00.../<номер>/DXA/CR DXA/CR000000.dcm
Скрипт ищет .dcm-файлы рекурсивно на любой глубине внутри папки исследования,
поэтому промежуточные служебные папки (series_XX, DXA, CR DXA и т.п.) не имеют
значения -- их не нужно разворачивать руками.

Этот скрипт готовит материал для быстрой ручной разметки: по каждой папке
исследования собирает все .dcm в одну PNG-сетку с подписанными именами файлов,
плюс пишет CSV-шаблон, куда останется проставить region руками (или через
простую веб-форму позже).

Запуск:
    python tools/build_contact_sheets.py data/raw/Исследования data/contact_sheets

Результат:
    data/contact_sheets/<study_uid>.png       -- сетка миниатюр
    data/routing_labels_template.csv           -- шаблон для разметки
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pydicom
import warnings


def load_thumbnail(path: Path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds = pydicom.dcmread(str(path))
    return ds.pixel_array


def find_dcm_files(study_dir: Path) -> list[Path]:
    """Рекурсивный поиск .dcm на любой глубине внутри папки исследования --
    структура вложенности (series_XX/.../DXA/CR DXA/...) не важна и может
    отличаться от исследования к исследованию."""
    return sorted(study_dir.rglob("*.dcm"))


def build_contact_sheet(study_dir: Path, out_path: Path) -> list[str]:
    files = find_dcm_files(study_dir)
    if not files:
        return []

    # относительный путь от папки исследования -- на случай если в разных
    # вложенных подпапках встретятся файлы с одинаковым именем (CR000000.dcm
    # в разных series), чтобы подписи на сетке и строки в CSV не схлопнулись
    rel_paths = [f.relative_to(study_dir) for f in files]

    n = len(files)
    cols = min(n, 4)
    rows = (n + cols - 1) // cols

    fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 4 * rows))
    axes = axes.flatten() if n > 1 else [axes]

    for ax, f, rel in zip(axes, files, rel_paths):
        try:
            arr = load_thumbnail(f)
            ax.imshow(arr, cmap="gray")
        except Exception as exc:  # noqa: BLE001
            ax.text(0.5, 0.5, f"ошибка чтения:\n{exc}", ha="center", va="center")
        ax.set_title(str(rel), fontsize=8)
        ax.axis("off")

    for ax in axes[n:]:
        ax.axis("off")

    fig.suptitle(study_dir.name, fontsize=12)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)

    return [str(rel) for rel in rel_paths]


def main(studies_root: str, out_dir: str, template_csv: str) -> None:
    studies_root = Path(studies_root)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    study_dirs = sorted(p for p in studies_root.iterdir() if p.is_dir())
    print(f"Найдено {len(study_dirs)} исследований")

    rows = []
    for study_dir in study_dirs:
        out_png = out_dir / f"{study_dir.name}.png"
        rel_paths = build_contact_sheet(study_dir, out_png)
        if not rel_paths:
            print(
                f"  {study_dir.name}: .dcm не найдены (проверьте вложенность) -- пропущено"
            )
            continue
        print(f"  {study_dir.name}: {len(rel_paths)} файлов -> {out_png.name}")
        for rel_path in rel_paths:
            rows.append(
                {
                    "study_uid": study_dir.name,
                    # путь относительно папки исследования, включая все
                    # промежуточные подпапки -- нужен, чтобы потом однозначно
                    # найти файл на диске (study_dir / relative_path)
                    "relative_path": rel_path,
                    # заполняется руками: spine / hip_left / hip_right / other
                    "region": "",
                }
            )

    with open(template_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["study_uid", "relative_path", "region"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nШаблон для разметки: {template_csv} ({len(rows)} строк)")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "Использование: python build_contact_sheets.py <studies_root> <out_dir> [template_csv]"
        )
        sys.exit(1)

    studies_root = sys.argv[1]
    out_dir = sys.argv[2]
    template_csv = (
        sys.argv[3]
        if len(sys.argv) > 3
        else str(Path(out_dir) / "routing_labels_template.csv")
    )
    main(studies_root, out_dir, template_csv)
