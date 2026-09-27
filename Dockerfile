FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Kolkata

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . \
    && pip install --no-cache-dir httpx streamlit plotly pandas

COPY apps ./apps
COPY services ./services
COPY database ./database
COPY scripts ./scripts
COPY data ./data

EXPOSE 8000 8501

# Overridden per service in docker-compose.yml
CMD ["uvicorn", "apps.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
