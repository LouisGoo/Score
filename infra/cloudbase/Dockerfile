FROM python:3.10-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
RUN apt-get update && apt-get install -y --no-install-recommends redis-server \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.lock backend/pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.lock
COPY backend/src ./src
COPY backend/alembic.ini ./
RUN pip install --no-cache-dir --no-deps --no-build-isolation . \
    && useradd --uid 10001 --no-create-home score
USER score
EXPOSE 8000
CMD ["python", "-m", "score_api.cloudrun"]
