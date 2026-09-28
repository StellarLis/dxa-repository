"""
Детектор эндопротеза бедра -- классическая геометрия/CV, без обучения модели.

Данных с протезами катастрофически мало (3 известных случая на весь датасет,
см. разметка.xlsx, где эксперт сознательно оставлял критерии качества
неоценёнными для таких пациентов) -- обучать на этом нейросеть бессмысленно
и даже вредно (см. обсуждение в чате). Вместо этого -- два признака, которые
физически отличают металл от кости на рентгене, оба считаются без единого
обучающего примера:

1. saturation_fraction -- доля пикселей кости с яркостью около предела
   датчика. Металл на CR-снимках часто засвечен сильнее, чем костная ткань.
2. uniformity -- насколько гладкая/однородная internal структура кости.
   У естественной кости видна губчатая (трабекулярная) текстура, у металла --
   ровная заливка почти без внутренней структуры.

Назначение: pre-filter ПЕРЕД rotation_error/roi_incorrect -- если протез
обнаружен, эти критерии неприменимы к данному пациенту вообще (не "снимок
плохой", а "критерий не про этот случай"), и их не нужно применять.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class ProsthesisResult:
    saturation_fraction: float  # доля пикселей кости у предела яркости
    texture_score: float  # мера внутренней текстуры (выше = более "костная")
    is_likely_prosthesis: bool
    confidence: float  # 0..1, насколько уверенно сработали оба признака вместе


def estimate_prosthesis_likelihood(
    pixel_array: np.ndarray,
    saturation_threshold: float = 0.95,
    saturation_fraction_cutoff: float = 0.10,
) -> ProsthesisResult:
    """Оценивает вероятность того, что на снимке эндопротез, а не естественная кость.

    pixel_array: float32 массив в [0, 1], как возвращает dicom_loader.load_dicom

    ИСТОРИЯ РЕШЕНИЯ (важно не потерять на защите): первая версия использовала
    два признака через И -- высокую засветку И низкую текстуру, предполагая,
    что металл выглядит "гладко". Проверка на 3 реальных случаях протеза из
    датасета опровергла это: у реальных протезов текстура ОКАЗАЛАСЬ ВЫШЕ, чем
    у нормальной кости (вероятно, из-за резьбы/граней конструкции импланта --
    резкие рукотворные грани дают больше высокочастотных перепадов яркости,
    чем губчатая структура кости). Из-за требования И по обоим признакам
    детектор пропустил все 3 реальных случая, включая два с явной, сильной
    засветкой (0.51 и 0.58 против нормы 0.06-0.07).

    Текущая версия использует ТОЛЬКО saturation_fraction -- это единственный
    признак, показавший большой, физически объяснимый и подтверждённый на
    реальных данных разрыв между протезом и нормальной костью. texture_score
    по-прежнему считается и возвращается (для диагностики/дальнейшего
    анализа), но не участвует в решении.

    Порог 0.10 выбран по факту измерения на всём датасете (см.
    tools/inspect_saturation_distribution.py): у 149 нормальных снимков
    бедра saturation_fraction лежит в диапазоне [0.041, 0.088], у всех 3
    известных протезов -- в диапазоне [0.112, 0.579]. Зазор между ними НЕ
    пересекается, 0.10 стоит ровно посередине с симметричным запасом. При
    n=3 положительных примеров нет гарантии, что этот зазор сохранится на
    скрытом тестовом наборе организатора -- честное ограничение, которое
    стоит явно упомянуть в описании решения (п.7 ТЗ).
    """
    img_u8 = (np.clip(pixel_array, 0, 1) * 255).astype(np.uint8)
    _, bone_mask = cv2.threshold(img_u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bone_mask = (bone_mask > 0).astype(np.uint8)

    kernel = np.ones((5, 5), np.uint8)
    bone_mask = cv2.morphologyEx(bone_mask, cv2.MORPH_CLOSE, kernel)

    bone_pixels = pixel_array[bone_mask > 0]
    if bone_pixels.size < 100:
        return ProsthesisResult(0.0, 1.0, False, 0.0)

    saturation_fraction = float((bone_pixels >= saturation_threshold).mean())

    laplacian = cv2.Laplacian(pixel_array.astype(np.float32), cv2.CV_32F, ksize=3)
    texture_score = float(
        np.var(laplacian[bone_mask > 0])
    )  # информационно, не в решении

    is_likely_prosthesis = saturation_fraction >= saturation_fraction_cutoff

    margin = abs(saturation_fraction - saturation_fraction_cutoff) / max(
        saturation_fraction_cutoff, 1e-6
    )
    confidence = float(min(1.0, margin))

    return ProsthesisResult(
        saturation_fraction=saturation_fraction,
        texture_score=texture_score,
        is_likely_prosthesis=is_likely_prosthesis,
        confidence=confidence,
    )
