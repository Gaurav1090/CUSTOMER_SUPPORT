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
# Source data is NOT baked into the image -- it belongs in the GCS landing
# bucket (see infra/modules/gcp/storage), uploaded independently of the
# container so ingestion has no coupling to what image happens to be
# deployed. Previously this COPY'd the demo CSV in directly (gated by
# INGEST_LEGACY_CSV); that was a quick fix for dev's landing bucket
# starting empty, replaced by uploading the demo CSV to the bucket instead
# -- see infra/README.md's Redis/ingestion setup notes.

RUN pip install --no-cache-dir --prefer-binary --no-compile -r requirements.txt && \
    # gcsfs: fsspec's gs:// backend, needed by utils/object_store.py for the
    # ingestion job's LANDING_PATH/INDEX_PATH once those point at a real GCS
    # bucket (see infra/modules/gcp/storage) instead of a local folder. Not
    # in requirements.txt since local dev never touches gs://, but this
    # image *is* the GCP Cloud Run deployment artifact specifically, so it
    # always needs it. requirements-optional.txt has the other fsspec
    # backends (s3fs/adlfs) for if/when a non-GCP build is added.
    #
    # redis: utils/ops.py's SessionStore/ResponseCache/RateLimiter all
    # import this lazily and degrade to an in-memory fallback if it's
    # missing -- which silently defeated the whole point of wiring up
    # Memorystore (see infra/modules/gcp/networking) the first time this
    # image was deployed without it. Same reasoning as gcsfs: install it
    # explicitly here rather than pulling in all of requirements-optional.txt
    # (which also has ragas/langfuse -- heavier, and not both verified
    # working in this image yet).
    pip install --no-cache-dir --prefer-binary --no-compile gcsfs redis

# utils/pii.py's NER redaction needs this model; presidio-analyzer/spacy
# are in requirements.txt but the model itself is a separate download, not
# a pip dependency of either package.
RUN python -m spacy download en_core_web_sm

RUN mkdir -p /app/chroma_db /app/data && \
    adduser --disabled-password --gecos "" appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=3)"

# --proxy-headers: trust X-Forwarded-Proto/X-Forwarded-For from the
# fronting proxy -- Cloud Run terminates TLS at its load balancer and
# forwards to this container over plain HTTP. Without this, Starlette's
# url_for() (used by templates/chat.html for its own static/style.css,
# not the external CDN links) generates http:// URLs on an https:// page,
# which browsers block as mixed content -- the app's own styling silently
# fails to load while unrelated CDN assets still do, making the UI look
# broken/unstyled. --forwarded-allow-ips='*' because Cloud Run's proxy
# doesn't come from a fixed, allowlistable IP.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--proxy-headers", "--forwarded-allow-ips=*"]
