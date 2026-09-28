"""
Геометрическое измерение отступов области интереса (ROI) для бедра --
без обучения модели, аналогично axis_geometry.py для позвоночника.

Критерий из ТЗ (п.2.3.2): "правильной считается визуализация по 3 см сверху
и снизу от области интереса, 2 см от края правого и левого". Это тоже
измерение расстояния, а не распознавание образа -- сегментируем кость по
яркости, находим её контур/bounding box, и меряем расстояние от границ
кости до краёв кадра в физических единицах (мм), используя pixel_spacing,
восстановленный в dicom_loader.py именно для таких измерений.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class HipRoiResult:
    margin_top_mm: float | None
    margin_bottom_mm: float | None
    margin_left_mm: float | None
    margin_right_mm: float | None
    is_violation: bool  # по всем 4 сторонам (исходная версия критерия)
    is_violation_horizontal_only: bool  # только лево/право, по всей кости
    is_violation_joint_region_only: bool  # лево/право, но только по верхней
    # части кости (условно -- область сустава), см. docstring ниже
    reason: str


REQUIRED_TOP_BOTTOM_MM = 30.0  # 3 см
REQUIRED_LEFT_RIGHT_MM = 20.0  # 2 см


def estimate_hip_roi_margins(
    pixel_array: np.ndarray,
    pixel_spacing_mm: tuple[float, float] | None,
) -> HipRoiResult:
    """Оценивает отступы от кости до краёв кадра в миллиметрах.

    pixel_array: float32 массив в [0, 1], MONOCHROME2 (кость -- ярко)
    pixel_spacing_mm: (row_spacing, col_spacing) из dicom_loader.LoadedStudy;
                       если None -- физические единицы недоступны, критерий
                       оценить нельзя (см. reason в результате)
    """
    if pixel_spacing_mm is None:
        return HipRoiResult(
            None, None, None, None, False, False, False, "физический масштаб недоступен"
        )

    row_spacing, col_spacing = pixel_spacing_mm
    h, w = pixel_array.shape

    img_u8 = (np.clip(pixel_array, 0, 1) * 255).astype(np.uint8)
    _, binary = cv2.threshold(img_u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    binary = (binary > 0).astype(np.uint8)

    kernel = np.ones((7, 7), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return HipRoiResult(
            None, None, None, None, False, False, False, "кость не сегментирована"
        )

    largest = max(contours, key=cv2.contourArea)
    x, y, bw, bh = cv2.boundingRect(largest)

    margin_top_px = y
    margin_bottom_px = h - (y + bh)
    margin_left_px = x
    margin_right_px = w - (x + bw)

    margin_top_mm = margin_top_px * row_spacing
    margin_bottom_mm = margin_bottom_px * row_spacing
    margin_left_mm = margin_left_px * col_spacing
    margin_right_mm = margin_right_px * col_spacing

    violations = []
    horizontal_violations = []
    if margin_top_mm < REQUIRED_TOP_BOTTOM_MM:
        violations.append(
            f"верх {margin_top_mm:.1f}мм < {REQUIRED_TOP_BOTTOM_MM:.0f}мм"
        )
    if margin_bottom_mm < REQUIRED_TOP_BOTTOM_MM:
        violations.append(
            f"низ {margin_bottom_mm:.1f}мм < {REQUIRED_TOP_BOTTOM_MM:.0f}мм"
        )
    if margin_left_mm < REQUIRED_LEFT_RIGHT_MM:
        msg = f"лево {margin_left_mm:.1f}мм < {REQUIRED_LEFT_RIGHT_MM:.0f}мм"
        violations.append(msg)
        horizontal_violations.append(msg)
    if margin_right_mm < REQUIRED_LEFT_RIGHT_MM:
        msg = f"право {margin_right_mm:.1f}мм < {REQUIRED_LEFT_RIGHT_MM:.0f}мм"
        violations.append(msg)
        horizontal_violations.append(msg)

    is_violation = len(violations) > 0
    # отдельная версия критерия: только лево/право. Гипотеза (проверяется
    # эмпирически в validate_geometry.py): верх/низ у DXA-снимков бедра почти
    # всегда близки к нулю по конструкции самого сканера/экспорта -- это не
    # варьируется с качеством позиционирования и не несёт различающего сигнала,
    # в отличие от лево/право, где технолог реально может сместить кадр
    is_violation_horizontal_only = len(horizontal_violations) > 0

    # уточнение: bounding box ВСЕЙ кости включает длинную диафизу, которая на
    # снимке идёт по диагонали -- это искусственно расширяет box и портит
    # оценку лево/право отступов, даже когда сустав (та самая "область
    # интереса") расположен нормально. Меряем лево/право только по верхней
    # половине bounding box кости -- там, где сустав (головка/шейка бедра),
    # а не по всей диафизе
    joint_region_cutoff = y + bh // 2
    joint_mask = binary.copy()
    joint_mask[joint_region_cutoff:, :] = 0
    joint_cols = np.where(joint_mask.any(axis=0))[0]

    is_violation_joint_region_only = False
    if len(joint_cols) > 0:
        joint_left_px = int(joint_cols.min())
        joint_right_px = w - int(joint_cols.max()) - 1
        joint_left_mm = joint_left_px * col_spacing
        joint_right_mm = joint_right_px * col_spacing
        is_violation_joint_region_only = (
            joint_left_mm < REQUIRED_LEFT_RIGHT_MM
            or joint_right_mm < REQUIRED_LEFT_RIGHT_MM
        )

    reason = "; ".join(violations) if violations else "все отступы в норме"

    return HipRoiResult(
        margin_top_mm=margin_top_mm,
        margin_bottom_mm=margin_bottom_mm,
        margin_left_mm=margin_left_mm,
        margin_right_mm=margin_right_mm,
        is_violation=is_violation,
        is_violation_horizontal_only=is_violation_horizontal_only,
        is_violation_joint_region_only=is_violation_joint_region_only,
        reason=reason,
    )
