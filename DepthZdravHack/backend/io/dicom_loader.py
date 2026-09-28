"""
DICOM loader и sanitizer для сервиса контроля качества денситометрии.

Отвечает за:
- безопасное чтение DICOM-файлов (устойчиво к невалидным UID и пр.)
- извлечение и нормализацию пиксельного массива
- восстановление физического масштаба (мм/пиксель), если PixelSpacing отсутствует
- извлечение только технических метаданных, без персональных данных (PHI)

Наблюдение по реальным данным (Lunar Prodigy Advance, GE Healthcare):
- изображения уже 8-битные MONOCHROME2 (готовый рендер, не сырой density map)
- PixelSpacing и RescaleSlope/Intercept отсутствуют
- BodyPartExamined / ViewPosition / Laterality пустые -> область и сторону
  нельзя определить из метаданных, только по пикселям (см. routing layer)
- физический масштаб можно восстановить из ExposedArea (мм) и Rows/Columns (px)
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pydicom
from pydicom.errors import InvalidDicomError

logger = logging.getLogger(__name__)

# Теги, которые разрешено читать. Всё остальное из датасета игнорируется,
# даже если по факту уже анонимизировано организатором -- решение не должно
# зависеть от наличия персональных данных (п.2.4 ТЗ) и не должно полагаться
# на то, что PHI-поля будут пустыми во всех случаях.
ALLOWED_TECHNICAL_TAGS = (
    "Modality",
    "SeriesDescription",
    "StudyDescription",
    "BodyPartExamined",
    "ViewPosition",
    "Laterality",
    "Rows",
    "Columns",
    "BitsAllocated",
    "BitsStored",
    "PhotometricInterpretation",
    "PixelSpacing",
    "ImagerPixelSpacing",
    "RescaleSlope",
    "RescaleIntercept",
    "ExposedArea",
    "TotalNumberOfExposures",
    "Manufacturer",
    "ManufacturerModelName",
    "PatientOrientation",
)


class DicomLoadError(Exception):
    """Ошибка чтения/валидации DICOM-файла -- должна попадать в processing_status=Failure,
    а не ронять весь батч."""


@dataclass
class LoadedStudy:
    """Результат загрузки одного DICOM-изображения, готовый для routing/analysis слоёв."""

    path_to_study: str
    study_uid: str
    image_uid: str
    pixel_array: np.ndarray  # float32, нормализован в [0, 1]
    rows: int
    columns: int
    pixel_spacing_mm: tuple[float, float] | None  # (row_spacing, col_spacing) или None
    technical_meta: dict = field(default_factory=dict)


def _safe_read(path: str | Path) -> pydicom.Dataset:
    """Читает DICOM, не падая и не шумя в лог на невалидных (но не критичных) полях.

    В реальных данных встречаются UID длиннее спецификации -- это предупреждение,
    а не повод браковать файл. В pydicom 3.x такие сообщения о валидации VR идут
    через встроенный логгер (pydicom.config), а не через модуль warnings -- поэтому
    одного warnings.simplefilter здесь недостаточно, глушим оба канала.
    Настоящие ошибки чтения (битый файл, не DICOM) должны быть пойманы вызывающим
    кодом и превращены в processing_status=Failure.
    """
    previous_mode = pydicom.config.settings.reading_validation_mode
    pydicom.config.settings.reading_validation_mode = pydicom.config.IGNORE
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ds = pydicom.dcmread(str(path), force=False)
    except (InvalidDicomError, FileNotFoundError, PermissionError) as exc:
        raise DicomLoadError(f"Не удалось прочитать DICOM {path}: {exc}") from exc
    finally:
        pydicom.config.settings.reading_validation_mode = previous_mode
    return ds


def _extract_uid(ds: pydicom.Dataset, tag: str, path: str | Path) -> str:
    value = getattr(ds, tag, None)
    if not value:
        raise DicomLoadError(f"Отсутствует обязательный тег {tag} в {path}")
    return str(value)


def _recover_pixel_spacing(ds: pydicom.Dataset) -> tuple[float, float] | None:
    """Пытается получить физический масштаб (мм/пиксель) несколькими способами,
    по убыванию приоритета:
    1. PixelSpacing / ImagerPixelSpacing -- стандартный путь, если есть.
    2. ExposedArea (мм) / Rows,Columns (px) -- восстановление по площади экспозиции,
       характерно для экспортов Lunar Prodigy, где сам тег PixelSpacing не заполнен.
    Возвращает None, если ни один способ не сработал -- вызывающий код должен
    считать, что критерии в физических единицах (см. отступы ROI) недоступны.
    """
    for tag in ("PixelSpacing", "ImagerPixelSpacing"):
        value = getattr(ds, tag, None)
        if value and len(value) == 2:
            try:
                return float(value[0]), float(value[1])
            except (TypeError, ValueError):
                pass

    exposed_area = getattr(ds, "ExposedArea", None)
    rows, cols = getattr(ds, "Rows", None), getattr(ds, "Columns", None)
    if exposed_area and len(exposed_area) == 2 and rows and cols:
        try:
            area_h_mm, area_w_mm = float(exposed_area[0]), float(exposed_area[1])
            row_spacing = area_h_mm / rows
            col_spacing = area_w_mm / cols
            return row_spacing, col_spacing
        except (TypeError, ValueError, ZeroDivisionError):
            pass

    return None


def _normalize_pixels(ds: pydicom.Dataset) -> np.ndarray:
    """Приводит пиксельный массив к float32 в диапазоне [0, 1].

    Учитывает RescaleSlope/Intercept, если они заданы (для этого датасета -- нет,
    но универсальный DICOM-загрузчик обязан их поддерживать).
    """
    arr = ds.pixel_array.astype(np.float32)

    slope = float(getattr(ds, "RescaleSlope", 1.0) or 1.0)
    intercept = float(getattr(ds, "RescaleIntercept", 0.0) or 0.0)
    arr = arr * slope + intercept

    bits_stored = int(getattr(ds, "BitsStored", 8) or 8)
    max_val = float(2**bits_stored - 1)
    if max_val <= 0:
        max_val = arr.max() if arr.max() > 0 else 1.0

    arr = np.clip(arr / max_val, 0.0, 1.0)

    # MONOCHROME1 инвертирован относительно MONOCHROME2 (яркость <-> плотность)
    if getattr(ds, "PhotometricInterpretation", "MONOCHROME2") == "MONOCHROME1":
        arr = 1.0 - arr

    return arr


def load_dicom(path: str | Path) -> LoadedStudy:
    """Основная точка входа для Input Layer.

    Бросает DicomLoadError на любой проблеме чтения/валидации -- этот
    вызов оборачивается в pipeline manager, который пишет
    processing_status=Failure и не роняет обработку остального батча.

    Подавление warning'ов оборачивает ВСЮ функцию, а не только сам dcmread():
    часть проверок VR в pydicom ленивая и срабатывает при первом обращении
    к атрибуту (study_uid, technical_meta и т.п.), а не в момент чтения файла.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return _load_dicom_impl(path)


def _load_dicom_impl(path: str | Path) -> LoadedStudy:
    path = Path(path)
    ds = _safe_read(path)

    study_uid = _extract_uid(ds, "StudyInstanceUID", path)
    image_uid = _extract_uid(ds, "SOPInstanceUID", path)

    if "PixelData" not in ds:
        raise DicomLoadError(f"В файле {path} отсутствует PixelData")

    try:
        pixel_array = _normalize_pixels(ds)
    except Exception as exc:  # noqa: BLE001 -- любая ошибка декодирования пикселей -> Failure
        raise DicomLoadError(f"Не удалось декодировать пиксели {path}: {exc}") from exc

    pixel_spacing = _recover_pixel_spacing(ds)
    if pixel_spacing is None:
        logger.warning(
            "Не удалось восстановить физический масштаб для %s -- "
            "критерии в мм/см будут недоступны для этого изображения",
            path,
        )

    technical_meta = {
        tag: str(getattr(ds, tag)) for tag in ALLOWED_TECHNICAL_TAGS if getattr(ds, tag, None)
    }

    return LoadedStudy(
        path_to_study=str(path),
        study_uid=study_uid,
        image_uid=image_uid,
        pixel_array=pixel_array,
        rows=int(ds.Rows),
        columns=int(ds.Columns),
        pixel_spacing_mm=pixel_spacing,
        technical_meta=technical_meta,
    )
