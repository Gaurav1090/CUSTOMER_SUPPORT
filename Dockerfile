FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8001

COPY requirements.txt setup.py pyproject.toml ./
COPY config ./config
COPY data_ingestion ./data_ingestion
COPY evaluation ./evaluation
COPY prompt_library ./prompt_library
COPY retriever ./retriever
COPY static ./static
COPY templates ./templates
COPY utils ./utils
COPY main.py ./

RUN pip install --no-cache-dir --prefer-binary --no-compile -r requirements.txt && \
    # gcsfs: fsspec's gs:// backend, needed by utils/object_store.py for the
    # ingestion job's LANDING_PATH/INDEX_PATH once those point at a real GCS
    # bucket (see infra/modules/gcp/storage) instead of a local folder. Not
    # in requirements.txt since local dev never touches gs://, but this
    # image *is* the GCP Cloud Run deployment artifact specifically, so it
    # always needs it. requirements-optional.txt has the other fsspec
    # backends (s3fs/adlfs) for if/when a non-GCP build is added.
    pip install --no-cache-dir --prefer-binary --no-compile gcsfs

RUN mkdir -p /app/chroma_db /app/data && \
    adduser --disabled-password --gecos "" appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=3)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
