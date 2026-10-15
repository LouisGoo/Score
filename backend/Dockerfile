FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.lock backend/pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.lock
COPY backend/src ./src
COPY backend/alembic.ini ./
RUN pip install --no-cache-dir --no-deps --no-build-isolation . && useradd --uid 10001 --no-create-home score
USER score
CMD ["uvicorn", "score_api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "172.30.22.10"]
