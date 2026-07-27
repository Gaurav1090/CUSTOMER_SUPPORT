# Landing folder (local dev)

Drop source PDFs here. `python -m data_ingestion.ingestion_pipeline` picks up
anything new or changed on each run (incremental, safe to re-run).

This folder plays the role of a cloud bucket in local development. In
staging/prod, set `LANDING_PATH=gs://your-bucket/landing` (or `s3://...`,
`abfs://...`) instead -- the ingestion code is unchanged either way.

The `_index/` subfolder is where the ingestion job writes its own state
(processed-file manifest, BM25 index). Don't edit it by hand; delete it if
you want to force a full re-ingest.
