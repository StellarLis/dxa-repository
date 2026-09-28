"""
Aggregation Layer -- собирает воедино всё, что было построено по отдельности:

    DICOM-файл
        -> Input Layer (dicom_loader.load_dicom)
        -> Routing (обученная модель: spine / hip_left / hip_right)
        -> Analysis, метод выбирается ПО КРИТЕРИЮ, а не по области целиком:
             - axis_tilt_over_5deg   -> геометрия (axis_geometry) -- лучше нейросети
             - roi_incorrect         -> геометрия (roi_geometry, вариант "лево/право") -- лучше нейросети
             - incorrect_positioning -> нейросеть (quality-модель spine)
             - foreign_object_or_artifact -> нейросеть (quality-модель spine)
             - rotation_error        -> нейросеть (quality-модель hip)
        -> Aggregation: quality_class = ИЛИ по всем сработавшим критериям
        -> строка результата в формате п.2.5 ТЗ

Модели-нейросети сами по себе выдают предсказания по ВСЕМ меткам, на которых
обучались (включая axis_tilt_over_5deg / roi_incorrect) -- пайплайн сознательно
ИГНОРИРУЕТ эти конкретные предсказания и подставляет вместо них результат
геометрии, потому что она эмпирически точнее для именно этих двух критериев
(см. validate_geometry.py и историю экспериментов с train_quality.py).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
from torchvision.models import resnet18

from backend.analysis.hip.prosthesis_detector import estimate_prosthesis_likelihood
from backend.analysis.hip.roi_geometry import estimate_hip_roi_margins
from backend.analysis.spine.axis_geometry import estimate_spine_axis_angle
from backend.data.manifest_dataset import (
    HIP_VIOLATION_CODES,
    IDX_TO_REGION,
    REGION_TO_IDX,
    SPINE_VIOLATION_CODES,
)
from backend.io.dicom_loader import DicomLoadError, load_dicom


@dataclass
class PipelineResult:
    path_to_study: str
    study_uid: str
    image_uid: str
    anatomical_region: str
    quality_class: int | None
    violation_type: str
    comment: (
        str  # человекочитаемое объяснение, что конкретно не так (или почему ошибка)
    )
    processing_status: str  # "Success" | "Failure"
    time_of_processing: float
    error_message: str = ""


def _to_tensor_3ch(arr: np.ndarray) -> torch.Tensor:
    """Тот же препроцессинг, что и при обучении (manifest_dataset._to_tensor_3ch) --
    критично, чтобы инференс видел данные в том же виде, что и во время обучения."""
    t = torch.from_numpy(arr).float()
    t = t.unsqueeze(0).repeat(3, 1, 1)
    t = (t - 0.5) / 0.5
    return t.unsqueeze(0)  # + batch-размерность


def _load_and_resize(pixel_array: np.ndarray, size: int) -> np.ndarray:
    return cv2.resize(pixel_array, (size, size), interpolation=cv2.INTER_AREA)


class RoutingPredictor:
    def __init__(
        self, checkpoint_path: str, device: torch.device, image_size: int = 224
    ):
        self.device = device
        self.image_size = image_size
        model = resnet18(weights=None)
        model.fc = nn.Linear(model.fc.in_features, 3)
        checkpoint = torch.load(
            checkpoint_path, map_location=device, weights_only=False
        )
        model.load_state_dict(checkpoint["model_state_dict"])
        model.eval()
        self.model = model.to(device)

    @torch.no_grad()
    def predict(self, pixel_array: np.ndarray) -> tuple[str, float]:
        arr = _load_and_resize(pixel_array, self.image_size)
        tensor = _to_tensor_3ch(arr).to(self.device)
        logits = self.model(tensor)
        probs = torch.softmax(logits, dim=1)[0]
        idx = int(probs.argmax().item())
        return IDX_TO_REGION[idx], float(probs[idx].item())


class QualityPredictor:
    """Обёртка над обученной multi-label quality-моделью (spine ИЛИ hip)."""

    def __init__(
        self, checkpoint_path: str, device: torch.device, image_size: int = 224
    ):
        self.device = device
        self.image_size = image_size
        checkpoint = torch.load(
            checkpoint_path, map_location=device, weights_only=False
        )
        self.violation_codes: list[str] = checkpoint["violation_codes"]
        self.group: str = checkpoint["group"]

        model = resnet18(weights=None)
        model.fc = nn.Linear(model.fc.in_features, len(self.violation_codes))
        model.load_state_dict(checkpoint["model_state_dict"])
        model.eval()
        self.model = model.to(device)

    @torch.no_grad()
    def predict(
        self, pixel_array: np.ndarray, mirror: bool = False
    ) -> dict[str, float]:
        arr = _load_and_resize(pixel_array, self.image_size)
        if mirror:
            arr = np.ascontiguousarray(arr[:, ::-1])
        tensor = _to_tensor_3ch(arr).to(self.device)
        logits = self.model(tensor)
        probs = torch.sigmoid(logits)[0].cpu().numpy()
        return dict(zip(self.violation_codes, probs.tolist()))


# Критерии, для которых финальное решение берётся из геометрии, а не из
# предсказания нейросети -- см. docstring модуля
GEOMETRY_OVERRIDES_SPINE = {"axis_tilt_over_5deg"}
GEOMETRY_OVERRIDES_HIP = {"roi_incorrect"}

_NN_CRITERION_LABELS_RU = {
    "incorrect_positioning": "признаки некорректной укладки",
    "foreign_object_or_artifact": "признаки постороннего предмета/артефакта на снимке",
    "rotation_error": "признаки некорректной ротации при позиционировании бедра",
}


def _explain_nn_criterion(code: str, probability: float) -> str:
    """Человекочитаемое объяснение для критерия, решённого нейросетью --
    название на русском + вероятность, с которой модель приняла решение,
    чтобы было видно, насколько она уверена, а не только да/нет."""
    label = _NN_CRITERION_LABELS_RU.get(code, code)
    return f"{label} (вероятность {probability:.0%})"


# Откалиброванные пороги (см. tools/tune_thresholds.py) -- умеренные значения,
# сознательно НЕ "идеальные по F1 на train" (это были бы 0.994+ для spine-критериев,
# явный признак переобучения на уже виденных моделью примерах).
DEFAULT_NN_THRESHOLDS = {
    "incorrect_positioning": 0.10,
    "foreign_object_or_artifact": 0.10,
    "rotation_error": 0.47,
}
DEFAULT_AXIS_TILT_THRESHOLD_DEGREES = 5.08
DEFAULT_HIP_ROI_MARGIN_THRESHOLD_MM = 21.5


class QualityPipeline:
    """Точка входа: process_file(path) -> PipelineResult.

    Ошибки на ЛЮБОМ этапе (чтение DICOM, инференс модели) ловятся здесь и
    превращаются в processing_status="Failure" -- ни одна ошибка не должна
    ронять обработку всего батча (п.2.7 ТЗ: "отсутствие необработанных
    исключений; все ошибки фиксируются в отчёте").
    """

    def __init__(
        self,
        routing_checkpoint: str,
        spine_quality_checkpoint: str,
        hip_quality_checkpoint: str,
        nn_thresholds: dict[str, float] | None = None,
        axis_tilt_threshold_degrees: float = DEFAULT_AXIS_TILT_THRESHOLD_DEGREES,
        hip_roi_margin_threshold_mm: float = DEFAULT_HIP_ROI_MARGIN_THRESHOLD_MM,
        device: str | None = None,
    ):
        """
        nn_thresholds: пороги вероятности по каждому нейросетевому критерию
            (incorrect_positioning, foreign_object_or_artifact, rotation_error).
            Если критерий не указан в словаре -- используется 0.5.
            ВНИМАНИЕ при калибровке через tune_thresholds.py: не берите порог,
            дающий "идеальный" F1=1.0 на train -- это почти всегда переобучение
            (модель уже видела эти примеры). Предпочитайте умеренные пороги из
            середины таблицы, даже если они формально не лучшие по F1 на train.
        axis_tilt_threshold_degrees: порог геометрии для наклона оси позвоночника.
        hip_roi_margin_threshold_mm: порог геометрии для отступа ROI бедра (мм).
        """
        self.device = torch.device(
            device or ("cuda" if torch.cuda.is_available() else "cpu")
        )
        self.nn_thresholds = (
            nn_thresholds if nn_thresholds is not None else DEFAULT_NN_THRESHOLDS
        )
        self.axis_tilt_threshold_degrees = axis_tilt_threshold_degrees
        self.hip_roi_margin_threshold_mm = hip_roi_margin_threshold_mm

        self.routing = RoutingPredictor(routing_checkpoint, self.device)
        self.spine_quality = QualityPredictor(spine_quality_checkpoint, self.device)
        self.hip_quality = QualityPredictor(hip_quality_checkpoint, self.device)

        print(f"[QualityPipeline] nn_thresholds = {self.nn_thresholds}")
        print(
            f"[QualityPipeline] axis_tilt_threshold_degrees = {self.axis_tilt_threshold_degrees}"
        )
        print(
            f"[QualityPipeline] hip_roi_margin_threshold_mm = {self.hip_roi_margin_threshold_mm}"
        )

    def _nn_threshold_for(self, code: str) -> float:
        return self.nn_thresholds.get(code, 0.5)

    def process_file(self, path: str) -> PipelineResult:
        start = time.monotonic()
        try:
            return self._process_file_impl(path, start)
        except (
            Exception
        ) as exc:  # noqa: BLE001 -- ловим ВСЁ, что не поймали ниже, чтобы батч не падал
            return PipelineResult(
                path_to_study=str(path),
                study_uid="",
                image_uid="",
                anatomical_region="",
                quality_class=None,
                violation_type="",
                comment="",
                processing_status="Failure",
                time_of_processing=time.monotonic() - start,
                error_message=str(exc),
            )

    def _process_file_impl(self, path: str, start: float) -> PipelineResult:
        try:
            study = load_dicom(path)
        except DicomLoadError as exc:
            return PipelineResult(
                path_to_study=str(path),
                study_uid="",
                image_uid="",
                anatomical_region="",
                quality_class=None,
                violation_type="",
                comment="",
                processing_status="Failure",
                time_of_processing=time.monotonic() - start,
                error_message=str(exc),
            )

        region, region_confidence = self.routing.predict(study.pixel_array)

        violations: list[str] = []
        explanations: list[str] = []

        if region == "spine":
            nn_probs = self.spine_quality.predict(study.pixel_array)
            for code in SPINE_VIOLATION_CODES:
                if code in GEOMETRY_OVERRIDES_SPINE:
                    continue  # решение по этому критерию -- ниже, геометрией
                if nn_probs.get(code, 0.0) >= self._nn_threshold_for(code):
                    violations.append(code)
                    explanations.append(_explain_nn_criterion(code, nn_probs[code]))

            axis_result = estimate_spine_axis_angle(
                study.pixel_array, threshold_degrees=self.axis_tilt_threshold_degrees
            )
            if axis_result.is_violation:
                violations.append("axis_tilt_over_5deg")
                explanations.append(
                    f"наклон оси позвоночника {axis_result.angle_degrees:.1f}° "
                    f"превышает допустимые {self.axis_tilt_threshold_degrees:.1f}°"
                )

        elif region in ("hip_left", "hip_right"):
            prosthesis_result = estimate_prosthesis_likelihood(study.pixel_array)
            if prosthesis_result.is_likely_prosthesis:
                # критерии rotation_error/roi_incorrect рассчитаны на естественную
                # анатомию и неприменимы к протезу -- ровно так же, как эксперт в
                # разметка.xlsx сознательно не проставлял для таких случаев 0/1
                # (см. excluded_reason=hip_endoprosthesis в build_manifest.py)
                return PipelineResult(
                    path_to_study=str(path),
                    study_uid=study.study_uid,
                    image_uid=study.image_uid,
                    anatomical_region=region,
                    quality_class=None,
                    violation_type="",
                    comment=(
                        f"обнаружены признаки эндопротеза "
                        f"(засветка кости {prosthesis_result.saturation_fraction:.0%}) -- "
                        f"стандартные критерии качества укладки/ROI неприменимы"
                    ),
                    processing_status="Success",
                    time_of_processing=time.monotonic() - start,
                )

            mirror = region == "hip_left"  # та же конвенция, что при обучении
            nn_probs = self.hip_quality.predict(study.pixel_array, mirror=mirror)
            for code in HIP_VIOLATION_CODES:
                if code in GEOMETRY_OVERRIDES_HIP:
                    continue
                if nn_probs.get(code, 0.0) >= self._nn_threshold_for(code):
                    violations.append(code)
                    explanations.append(_explain_nn_criterion(code, nn_probs[code]))

            roi_result = estimate_hip_roi_margins(
                study.pixel_array, study.pixel_spacing_mm
            )
            min_margin = min(roi_result.margin_left_mm, roi_result.margin_right_mm)
            if min_margin < self.hip_roi_margin_threshold_mm:
                violations.append("roi_incorrect")
                explanations.append(
                    f"недостаточный отступ области интереса: "
                    f"слева {roi_result.margin_left_mm:.0f}мм, "
                    f"справа {roi_result.margin_right_mm:.0f}мм "
                    f"(норма >= {self.hip_roi_margin_threshold_mm:.0f}мм с каждой стороны)"
                )

        quality_class = 1 if violations else 0
        comment = "; ".join(explanations) if explanations else "нарушений не обнаружено"

        return PipelineResult(
            path_to_study=str(path),
            study_uid=study.study_uid,
            image_uid=study.image_uid,
            anatomical_region=region,
            quality_class=quality_class,
            violation_type=";".join(violations),
            comment=comment,
            processing_status="Success",
            time_of_processing=time.monotonic() - start,
        )

    def process_batch(self, paths: list[str]) -> list[PipelineResult]:
        return [self.process_file(p) for p in paths]
