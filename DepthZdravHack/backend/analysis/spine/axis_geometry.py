"""
Геометрическое измерение наклона оси позвоночника -- без обучения модели.

Критерий из ТЗ (п.2.3.1): "правильно выровненная ось позвоночника
(допустимый наклон до 5 градусов)". Это буквально измерение угла, а не
распознавание образа -- поэтому вместо обучения классификатора на скудных
бинарных метках считаем угол напрямую по контуру кости через классическое
компьютерное зрение (сегментация по яркости + линейная регрессия по центрам
масс строк). Не требует ни одного размеченного координатами примера --
можно сразу проверить точность против уже имеющихся бинарных меток
(violation_type содержит axis_tilt_over_5deg).

Идея алгоритма:
1. Кость -- самая яркая область снимка (см. все реальные образцы).
2. Для каждой строки изображения находим x-координату "центра масс"
   яркости -- то есть примерное положение позвоночника на этой высоте.
3. Собираем все такие точки (по одной на строку) и подгоняем к ним
   прямую линию (МНК).
4. Угол этой прямой относительно вертикали -- и есть наклон оси.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class SpineAxisResult:
    angle_degrees: float  # угол наклона относительно вертикали, >=0
    is_violation: bool  # angle_degrees > threshold_degrees
    n_valid_rows: int  # сколько строк реально участвовало в подгонке прямой
    confidence: float  # доля строк с уверенно найденным центром масс (0..1)


def _row_centroids(binary_mask: np.ndarray, min_bright_pixels: int) -> list[tuple[float, int]]:
    """Для каждой строки маски находит x-координату центра масс ярких пикселей.

    Строки, где ярких пикселей слишком мало (min_bright_pixels) -- пропускаются,
    это обычно верх/низ снимка за пределами тела или сильно обрезанные края.
    """
    h, w = binary_mask.shape
    xs = np.arange(w)
    points = []
    for y in range(h):
        row = binary_mask[y]
        n_bright = int(row.sum())
        if n_bright < min_bright_pixels:
            continue
        centroid_x = float((xs * row).sum() / n_bright)
        points.append((centroid_x, y))
    return points


def estimate_spine_axis_angle(
    pixel_array: np.ndarray,
    threshold_degrees: float = 5.0,
    min_row_fraction: float = 0.15,
) -> SpineAxisResult:
    """Оценивает угол наклона оси позвоночника по изображению.

    pixel_array: float32 массив в [0, 1], MONOCHROME2 (кость -- ярко),
                 как возвращает dicom_loader.load_dicom(...).pixel_array
    threshold_degrees: порог нарушения (5 градусов по ТЗ)
    min_row_fraction: минимальная доля ширины изображения, которая должна
                       быть "яркой" в строке, чтобы включить её в подгонку
                       (отсекает шум и случайные яркие пятна по краям)
    """
    h, w = pixel_array.shape

    # Otsu -- автоматически находит порог, отделяющий кость (ярко) от фона (темно),
    # адаптируясь под конкретный снимок вместо фиксированного глобального порога
    img_u8 = (np.clip(pixel_array, 0, 1) * 255).astype(np.uint8)
    _, binary = cv2.threshold(img_u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    binary = (binary > 0).astype(np.uint8)

    # морфологическое "закрытие" убирает мелкий шум и дырки внутри кости,
    # не меняя общую форму/ось объекта
    kernel = np.ones((5, 5), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    min_bright_pixels = int(w * min_row_fraction)
    points = _row_centroids(binary, min_bright_pixels)

    if len(points) < 10:
        # недостаточно данных для надёжной подгонки прямой -- возвращаем
        # низкую уверенность, а не гадаем на шуме
        return SpineAxisResult(
            angle_degrees=0.0, is_violation=False, n_valid_rows=len(points), confidence=0.0
        )

    xs = np.array([p[0] for p in points], dtype=np.float32)
    ys = np.array([p[1] for p in points], dtype=np.float32)

    # МНК: x = a*y + b. Угол наклона от вертикали = arctan(a),
    # потому что при a=0 линия строго вертикальна (x не меняется с y)
    a, b = np.polyfit(ys, xs, deg=1)
    angle_rad = np.arctan(a)
    angle_degrees = float(abs(np.degrees(angle_rad)))

    confidence = len(points) / h

    return SpineAxisResult(
        angle_degrees=angle_degrees,
        is_violation=angle_degrees > threshold_degrees,
        n_valid_rows=len(points),
        confidence=confidence,
    )
