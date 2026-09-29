"""
PyTorch Dataset'ы поверх manifest.csv (см. tools/build_manifest.py).

Два разных набора:
- RoutingDataset  -- задача "какая это область" (spine / hip_left / hip_right).
                     Использует ВСЕ размеченные строки, включая исключённые из
                     quality-обучения (эндопротез всё равно физически бедро --
                     для роутинга это валидный пример).
- QualityDataset  -- задача "есть ли нарушение качества" + какие именно, отдельно
                     для группы "spine" и группы "hip". Использует только строки
                     с excluded_reason == "" (эндопротезы и подобные случаи
                     исключены -- обычные критерии к ним неприменимы).

Особенность QualityDataset для group="hip": левое и правое бедро объединяются
в одну обучающую выборку -- критерии качества (ротация, ROI) симметричны,
поэтому hip_left зеркалится по горизонтали, чтобы визуально соответствовать
ориентации hip_right. Это увеличивает эффективный размер выборки вдвое, что
существенно при исходном дисбалансе классов (нарушения ~19-22% на сторону).
Сторона (region) сохраняется в возвращаемом sample как метаданные -- она не
участвует в обучении, но нужна на этапе формирования итогового отчёта
(anatomical_region в выходной таблице, п.2.5 ТЗ).
"""

from __future__ import annotations

import csv
import random
from collections import defaultdict
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
import torch
from torch.utils.data import Dataset

from backend.io.dicom_loader import DicomLoadError, load_dicom

REGION_TO_IDX = {"spine": 0, "hip_left": 1, "hip_right": 2}
IDX_TO_REGION = {v: k for k, v in REGION_TO_IDX.items()}

# словари нарушений -- порядок фиксирован, определяет позиции в multi-hot векторе
SPINE_VIOLATION_CODES = [
    "incorrect_positioning",
    "axis_tilt_over_5deg",
    "foreign_object_or_artifact",
]
HIP_VIOLATION_CODES = [
    "rotation_error",
    "roi_incorrect",
]


def load_manifest(manifest_csv: str | Path) -> list[dict]:
    with open(manifest_csv, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def split_by_study(
    rows: list[dict],
    val_frac: float = 0.15,
    test_frac: float = 0.15,
    seed: int = 42,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Разбивает строки манифеста на train/val/test по study_uid, а не по строкам.

    Критично: снимки одного пациента (включая пары left/right бедра) не должны
    попадать в разные выборки -- иначе модель на валидации будет частично видеть
    анатомию уже знакомого ей человека, что завышает метрики и является утечкой
    данных (именно это прямо проверяется в п.8.1 ТЗ).
    """
    studies = sorted({r["study_uid"] for r in rows})
    rng = random.Random(seed)
    rng.shuffle(studies)

    n = len(studies)
    n_val = max(1, int(n * val_frac)) if val_frac > 0 else 0
    n_test = max(1, int(n * test_frac)) if test_frac > 0 else 0

    val_studies = set(studies[:n_val])
    test_studies = set(studies[n_val : n_val + n_test])
    train_studies = set(studies[n_val + n_test :])

    train = [r for r in rows if r["study_uid"] in train_studies]
    val = [r for r in rows if r["study_uid"] in val_studies]
    test = [r for r in rows if r["study_uid"] in test_studies]
    return train, val, test


def _load_and_resize(image_path: str, size: int) -> np.ndarray:
    """Читает DICOM через общий Input Layer лоадер и приводит к квадрату size x size.

    cv2.resize применяется напрямую к float32-массиву в [0,1] -- без промежуточного
    round-trip через uint8, чтобы не терять точность на тонких градациях яркости,
    важных для мелких нарушений (лёгкий наклон оси и т.п.).
    """
    study = load_dicom(image_path)
    resized = cv2.resize(study.pixel_array, (size, size), interpolation=cv2.INTER_AREA)
    return resized


def _augment_brightness_contrast(
    arr: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    """Безопасная аугментация для малых датасетов: только яркость/контраст.

    Сознательно НЕ включает повороты, сдвиги или обрезку -- для критериев вроде
    "наклон оси > 5 градусов" или "отступ ROI 3см" геометрия изображения И ЕСТЬ
    метка. Случайный поворот на 3 градуса при аугментации может превратить
    "корректный" пример в визуально похожий на "нарушение", а метка останется
    прежней -- модель будет учиться на противоречивых примерах. Яркость и
    контраст на geometry не влияют, поэтому безопасны для всех критериев.
    """
    gain = rng.uniform(0.85, 1.15)
    bias = rng.uniform(-0.05, 0.05)
    return np.clip(arr * gain + bias, 0.0, 1.0).astype(np.float32)


def _to_tensor_3ch(arr: np.ndarray) -> torch.Tensor:
    """[H,W] float32 в [0,1] -> [3,H,W] тензор (повтор канала под ImageNet-претрейн бэкбоны)."""
    t = torch.from_numpy(arr).float()
    t = t.unsqueeze(0).repeat(3, 1, 1)
    # простая нормализация к [-1, 1]; при первом реальном обучении стоит
    # пересчитать mean/std по факту собранного датасета и подставить сюда
    t = (t - 0.5) / 0.5
    return t


class RoutingDataset(Dataset):
    """Классификация анатомической области: spine / hip_left / hip_right.

    Использует все размеченные строки манифеста, включая excluded_reason != ""
    (эндопротез не мешает понять, что на снимке бедро).
    """

    def __init__(self, rows: list[dict], image_size: int = 224):
        self.rows = rows
        self.image_size = image_size

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, idx: int) -> dict:
        row = self.rows[idx]
        try:
            arr = _load_and_resize(row["image_path"], self.image_size)
        except DicomLoadError as exc:
            raise RuntimeError(
                f"Не удалось загрузить {row['image_path']}: {exc}"
            ) from exc

        return {
            "image": _to_tensor_3ch(arr),
            "label": torch.tensor(REGION_TO_IDX[row["region"]], dtype=torch.long),
            "study_uid": row["study_uid"],
            "image_path": row["image_path"],
        }


class QualityDataset(Dataset):
    """Бинарная классификация качества + multi-label нарушения для одной группы.

    group="spine": только region == "spine".
    group="hip":   region in {"hip_left", "hip_right"}; hip_left зеркалится
                   по горизонтали, чтобы обучаться на объединённой выборке
                   с hip_right (см. docstring модуля).

    Строки с excluded_reason != "" отфильтровываются на этапе построения --
    для них quality_class не определён экспертом.
    """

    def __init__(
        self,
        rows: list[dict],
        group: Literal["spine", "hip"],
        image_size: int = 224,
        augment: bool = False,
    ):
        if group not in ("spine", "hip"):
            raise ValueError(
                f"group должен быть 'spine' или 'hip', получено: {group!r}"
            )

        self.group = group
        self.image_size = image_size
        self.augment = augment
        self._rng = np.random.default_rng()
        self.violation_codes = (
            SPINE_VIOLATION_CODES if group == "spine" else HIP_VIOLATION_CODES
        )

        if group == "spine":
            wanted_regions = {"spine"}
        else:
            wanted_regions = {"hip_left", "hip_right"}

        self.rows = [
            r
            for r in rows
            if r["region"] in wanted_regions and not r["excluded_reason"].strip()
        ]

    def __len__(self) -> int:
        return len(self.rows)

    def _violation_multihot(self, violation_type: str) -> torch.Tensor:
        present = set(violation_type.split(";")) if violation_type else set()
        vec = [1.0 if code in present else 0.0 for code in self.violation_codes]
        return torch.tensor(vec, dtype=torch.float32)

    def __getitem__(self, idx: int) -> dict:
        row = self.rows[idx]
        try:
            arr = _load_and_resize(row["image_path"], self.image_size)
        except DicomLoadError as exc:
            raise RuntimeError(
                f"Не удалось загрузить {row['image_path']}: {exc}"
            ) from exc

        mirrored = False
        if self.group == "hip" and row["region"] == "hip_left":
            arr = np.ascontiguousarray(arr[:, ::-1])
            mirrored = True

        if self.augment:
            arr = _augment_brightness_contrast(arr, self._rng)

        return {
            "image": _to_tensor_3ch(arr),
            "quality_class": torch.tensor(int(row["quality_class"]), dtype=torch.long),
            "violations": self._violation_multihot(row["violation_type"]),
            # метаданные, не участвуют в обучении, нужны для сборки отчёта/отладки
            "study_uid": row["study_uid"],
            "region": row["region"],  # исходная сторона, ДО зеркалирования
            "mirrored": mirrored,
            "image_path": row["image_path"],
        }


def class_balance_report(rows: list[dict], group: Literal["spine", "hip"]) -> dict:
    """Быстрая сводка по балансу классов -- пригодится и для отчёта на защите
    (п.8.1 ТЗ явно спрашивает про работу с дисбалансом классов), и для того,
    чтобы прикинуть class weights перед обучением."""
    wanted_regions = {"spine"} if group == "spine" else {"hip_left", "hip_right"}
    subset = [
        r
        for r in rows
        if r["region"] in wanted_regions and not r["excluded_reason"].strip()
    ]
    n_total = len(subset)
    n_pos = sum(1 for r in subset if r["quality_class"] == "1")
    return {
        "group": group,
        "n_total": n_total,
        "n_violation": n_pos,
        "n_ok": n_total - n_pos,
        "violation_rate": round(n_pos / n_total, 3) if n_total else None,
    }
