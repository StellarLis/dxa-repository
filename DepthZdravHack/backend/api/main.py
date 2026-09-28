"""
Веб-сервис поверх QualityPipeline: загрузка DICOM через браузер, просмотр
превью и результата обработки, пакетная обработка, скачивание итоговой
таблицы -- реализует "полноценный веб-интерфейс для загрузки, просмотра и
пакетной обработки исследований" из доп. функционала ТЗ (п.2.6), а не
только программный API.

Модели грузятся ОДИН РАЗ при старте сервера (не на каждый запрос) -- это
критично для времени обработки одного исследования (п.8.4 ТЗ).

Запуск (для разработки):
    uvicorn backend.api.main:app --reload --port 8000

Пути к чекпоинтам читаются из переменных окружения (с разумными путями по
умолчанию, совпадающими со структурой проекта), чтобы не хардкодить их --
удобно и для локального запуска, и для контейнера.
"""

from __future__ import annotations

import base64
import io
import os
import sys
import tempfile
import uuid
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.io.dicom_loader import DicomLoadError, load_dicom  # noqa: E402
from backend.pipeline.quality_pipeline import (
    PipelineResult,
    QualityPipeline,
)  # noqa: E402

ROUTING_CHECKPOINT = os.environ.get("ROUTING_CHECKPOINT", "models/routing_best.pt")
SPINE_CHECKPOINT = os.environ.get("SPINE_CHECKPOINT", "models/quality_spine_best.pt")
HIP_CHECKPOINT = os.environ.get("HIP_CHECKPOINT", "models/quality_hip_best.pt")

app = FastAPI(title="DXA QC Service")

pipeline: QualityPipeline | None = None
# in-memory хранилище результатов последних батчей, по job_id -- этого
# достаточно для локального однопользовательского запуска (нет требования
# к персистентности между перезапусками сервера)
jobs: dict[str, list[PipelineResult]] = {}


@app.on_event("startup")
def load_models() -> None:
    global pipeline
    pipeline = QualityPipeline(
        routing_checkpoint=ROUTING_CHECKPOINT,
        spine_quality_checkpoint=SPINE_CHECKPOINT,
        hip_quality_checkpoint=HIP_CHECKPOINT,
    )


def make_thumbnail_b64(pixel_array: np.ndarray, size: int = 220) -> str:
    """Превью снимка для отображения в браузере -- PNG, закодированный в base64,
    чтобы отдавать прямо внутри JSON-ответа без отдельного файла/эндпоинта."""
    arr = cv2.resize(pixel_array, (size, size), interpolation=cv2.INTER_AREA)
    img_u8 = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
    ok, buf = cv2.imencode(".png", img_u8)
    return base64.b64encode(buf.tobytes()).decode("ascii")


@app.post("/api/process")
async def process_files(files: list[UploadFile] = File(...)) -> dict:
    if pipeline is None:
        raise HTTPException(
            503, "Модели ещё загружаются, попробуйте через несколько секунд"
        )

    job_id = str(uuid.uuid4())
    results_json = []
    result_objs = []

    for f in files:
        content = await f.read()
        with tempfile.NamedTemporaryFile(suffix=".dcm", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            result = pipeline.process_file(tmp_path)
            result.path_to_study = (
                f.filename or tmp_path
            )  # исходное имя файла, не временный путь
            result_objs.append(result)

            thumbnail = None
            try:
                study = load_dicom(tmp_path)
                thumbnail = make_thumbnail_b64(study.pixel_array)
            except DicomLoadError:
                pass  # файл не читается -- превью не будет, но результат (Failure) уже есть

            results_json.append(
                {
                    "filename": f.filename,
                    "study_uid": result.study_uid,
                    "image_uid": result.image_uid,
                    "anatomical_region": result.anatomical_region,
                    "quality_class": result.quality_class,
                    "violation_type": result.violation_type,
                    "comment": result.comment,
                    "processing_status": result.processing_status,
                    "error_message": result.error_message,
                    "time_of_processing": round(result.time_of_processing, 3),
                    "thumbnail_png_b64": thumbnail,
                }
            )
        finally:
            os.unlink(tmp_path)

    jobs[job_id] = result_objs
    return {"job_id": job_id, "results": results_json}


@app.get("/api/download/{job_id}")
def download_results(job_id: str) -> StreamingResponse:
    if job_id not in jobs:
        raise HTTPException(404, "Результаты не найдены (сервер мог перезапуститься)")

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "results"
    ws.append(
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
    for r in jobs[job_id]:
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

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=results_{job_id[:8]}.xlsx"
        },
    )


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "models_loaded": pipeline is not None}


# фронтенд -- отдаём статику; монтируем ПОСЛЕДНИМ, чтобы не перекрыть /api/* маршруты
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
