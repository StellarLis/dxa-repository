# Контейнеризация уже готового ИИ-сервиса контроля качества денситометрии.
# В новой multi-service архитектуре этот сервис -- "внешний ИИ-модуль" из
# раздела 7 ТЗ на fullstack-обвязку: backend-worker обращается к нему по HTTP,
# сам он остаётся без изменений в логике.

FROM python:3.11-slim

WORKDIR /app

# Системные зависимости для opencv-python-headless (libgl нужен даже headless-сборке)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/

# models/ НЕ копируется в образ -- веса большие и не хранятся в git (см. .gitignore
# исходного проекта); монтируются как volume при запуске (см. docker-compose.yml)

ENV ROUTING_CHECKPOINT=/app/models/routing_best.pt
ENV SPINE_CHECKPOINT=/app/models/quality_spine_best.pt
ENV HIP_CHECKPOINT=/app/models/quality_hip_best.pt

EXPOSE 8000

CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
