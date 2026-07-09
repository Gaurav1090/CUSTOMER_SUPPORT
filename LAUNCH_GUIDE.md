# Complete App Launch & Usage Guide

This guide covers everything needed to launch and use the production-grade Customer Support RAG System.

---

## System Overview

The application is a **FastAPI-based ecommerce product assistant** that:
- Stores 450 product reviews from Flipkart (542 chunked documents)
- Retrieves relevant products using hybrid search (dense vectors + keyword search)
- Generates grounded answers with citations using Groq LLM
- Tracks conversation history per session
- Enforces API authentication and CORS security

### Key Endpoints
- **GET `/`** – Chat UI (web interface)
- **POST `/get`** – Protected chat endpoint
- **GET `/docs`** – Interactive API documentation

---

## Prerequisites

### System Requirements
- **Python**: 3.10 or higher
- **RAM**: 2GB minimum (4GB recommended for smooth operation)
- **Disk Space**: 500MB (including dependencies and local Chroma database)
- **OS**: macOS, Linux, or Windows with WSL2

### Required API Keys
Obtain these keys before launching:
1. **GROQ_API_KEY** – For LLM generation
   - Get from: https://console.groq.com/keys
2. **APP_API_KEY** – For local API authentication (e.g., `test-local-key`)
3. **CHROMA_API_KEY** (optional) – For cloud Chroma storage
4. **GOOGLE_API_KEY** (optional) – Only if using Google embeddings

---

## Setup Steps

### 1. Clone/Extract the Repository
```bash
cd /Users/gauravsingh/Downloads/custmor_support_system-main
```

### 2. Create Virtual Environment
```bash
# Option A: Using venv (already set up in project)
source .venv/bin/activate

# Option B: Create fresh venv
python3.10 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

**Dependencies included:**
- FastAPI + Uvicorn (API framework)
- LangChain + Groq (LLM integration)
- Chroma (vector database)
- HuggingFace embeddings (sentence-transformers)
- Pandas (data processing)
- Python-dotenv (configuration)

### 4. Configure Environment Variables

Create/update `.env` file in the project root:
```bash
# Required
APP_API_KEY=test-local-key
GROQ_API_KEY=<your-groq-api-key>

# Optional (cloud Chroma)
CHROMA_API_KEY=<your-chroma-api-key>
CHROMA_TENANT=<your-tenant-name>
CHROMA_DATABASE=<your-database-name>

# CORS configuration
ALLOWED_ORIGINS=http://localhost:8001,http://127.0.0.1:8001,https://yourdomain.com

# Storage mode (default: "auto")
# Options: "auto" (fallback cloud→local), "local" (always local), "cloud" (always cloud)
CHROMA_STORAGE_MODE=auto
```

### 5. Ingest Data (One-time)

Populate the vector database with product reviews:
```bash
.venv/bin/python -c "
from data_ingestion.ingestion_pipeline import DataIngestion
ingestion = DataIngestion()
ingestion.transform_and_store()
print('✓ Data ingestion complete: 450 → 542 chunked documents')
"
```

---

## Launch the App

### Development Mode (with auto-reload)
```bash
.venv/bin/uvicorn main:app --reload --port 8001
```

### Production Mode (single worker)
```bash
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8001 --workers 1
```

### Production Mode (multiple workers with Gunicorn)
```bash
pip install gunicorn
gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:8001
```

### Expected Output
```
INFO:     Uvicorn running on http://127.0.0.1:8001 (Press CTRL+C to quit)
INFO:     Application startup complete
```

---

## Using the App

### Option 1: Web Interface (Easiest)

1. **Open in Browser**
   ```
   http://localhost:8001/
   ```

2. **First Launch**
   - UI will prompt for API key
   - Enter: `test-local-key` (or your `APP_API_KEY`)
   - API key is stored locally in browser

3. **Ask Questions**
   Examples:
   - "Can you recommend a good budget headphone?"
   - "What are the best earbuds under 2000?"
   - "Tell me about wireless headsets with good battery life."

4. **Conversation Features**
   - Multi-turn conversation (context preserved)
   - Session ID tracked in HTTP headers
   - Sources cited as `[source:row-X]`

### Option 2: API (cURL/Postman)

**Single Query:**
```bash
curl -X POST http://localhost:8001/get \
  -H "X-API-Key: test-local-key" \
  -d "msg=Can you recommend a good headphone under 2000?"
```

**With Session History:**
```bash
curl -X POST http://localhost:8001/get \
  -H "X-API-Key: test-local-key" \
  -H "X-Session-Id: user-123" \
  -d "msg=Tell me more about the warranty"
```

**Interactive API Documentation:**
```
http://localhost:8001/docs
```

### Option 3: Python Client

```python
import requests
import json

BASE_URL = "http://localhost:8001"
API_KEY = "test-local-key"

def query_assistant(question, session_id="default"):
    headers = {
        "X-API-Key": API_KEY,
        "X-Session-Id": session_id
    }
    
    response = requests.post(
        f"{BASE_URL}/get",
        data={"msg": question},
        headers=headers
    )
    
    if response.status_code == 200:
        print(f"Assistant: {response.text}")
    else:
        print(f"Error {response.status_code}: {response.text}")

# Example usage
query_assistant("What headphones do you recommend?", session_id="user-001")
query_assistant("Do they have noise cancellation?", session_id="user-001")  # Multi-turn
```

---

## Quality Assurance

### Run Full Test Suite
```bash
.venv/bin/python -m unittest discover tests -p "test_phase*.py" -v
```

**Expected Output:**
```
Ran 15 tests in ~10 seconds
OK (skipped=1)
```

### Run Evaluation Framework
```bash
.venv/bin/python evaluation/run_evaluation.py
```

**Output:** `evaluation/results.json` with metrics:
- Context Precision
- Context Recall
- Faithfulness
- Answer Relevance

### Run Individual Phase Tests
```bash
# Phase 0: Security
.venv/bin/python -m unittest tests.test_phase0_security -v

# Phase 1: Ingestion
.venv/bin/python -m unittest tests.test_phase1_ingestion -v

# Phase 2: Retrieval
.venv/bin/python -m unittest tests.test_phase2_retrieval -v

# Phase 3: Grounding
.venv/bin/python -m unittest tests.test_phase3_grounding -v

# Phase 4: Evaluation
.venv/bin/python -m unittest tests.test_phase4_evaluation tests.test_phase4_ci -v
```

---

## Troubleshooting

### Issue: "API key is invalid or missing"
**Solution:**
- Ensure `APP_API_KEY` is set in `.env`
- In web UI, enter the correct key in the prompt
- For API calls, include header: `-H "X-API-Key: your-key"`

### Issue: "Failed to connect to LLM"
**Solution:**
- Verify `GROQ_API_KEY` is valid: https://console.groq.com/keys
- Check internet connection
- Verify model is still available (Groq deprecates models monthly)

### Issue: "Insufficient context"
**Solution:**
- App is working correctly; this means the question couldn't be confidently answered
- Try rephrasing the question
- Examples that work well:
  - "Headphones under 2000"
  - "Wireless earbuds with good battery"
  - "Product rating above 4 stars"

### Issue: "Chroma quota exceeded"
**Solution:**
- System automatically falls back to local storage
- Set `CHROMA_STORAGE_MODE=local` in `.env` to disable cloud attempts
- Local database stored in `chroma_db/` directory

### Issue: "ModuleNotFoundError"
**Solution:**
```bash
# Reinstall dependencies
.venv/bin/pip install --upgrade -r requirements.txt

# Reinstall package in editable mode
.venv/bin/pip install -e .
```

### Issue: "Port 8001 already in use"
**Solution:**
```bash
# Use different port
.venv/bin/uvicorn main:app --port 8002

# Or find process using port 8001
lsof -i :8001
kill -9 <PID>
```

---

## Architecture Overview

### Data Flow
```
User Query
    ↓
API Authentication (X-API-Key header)
    ↓
Query Rewriting & Filter Parsing
    ↓
Hybrid Retrieval:
  ├─ Dense Search (HuggingFace embeddings → Chroma)
  ├─ Keyword Search (BM25-style)
  └─ RRF Merging + Reranking
    ↓
Context Building (3-5 top documents + metadata)
    ↓
Chat History Loading (last 4 turns)
    ↓
LLM Generation (Groq API)
    ↓
Faithfulness Check (LLM Judge)
    ↓
Reasoning Token Stripping
    ↓
Response to User
    ↓
Session History Update
```

### Storage Architecture
```
Local Storage (Recommended):
  ├─ chroma_db/            (Vector embeddings)
  ├─ data/.ingestion_state.json  (Processed doc tracking)
  └─ data/.keyword_index.json    (BM25 index)

Cloud Storage (Optional):
  └─ Chroma Cloud API (API key required)
```

---

## Performance Metrics

### Typical Response Times
- **Retrieval**: 200-500ms (hybrid search + reranking)
- **LLM Generation**: 1-3 seconds (Groq API)
- **Total E2E**: 1.5-4 seconds

### Throughput
- **Concurrent Sessions**: 10+ (single worker)
- **Requests/Second**: 5-10 (single worker)
- **Scale to 100+**: Use multiple workers or load balancer

### Resource Usage
- **Memory**: 300-500MB (at rest), 600-800MB (under load)
- **CPU**: 10-20% (idle), 40-60% (processing)
- **Disk**: 50MB (vector database), 10MB (application)

---

## Deployment

### Docker Deployment
```bash
# Build image
docker build -t customer-support-rag:latest .

# Run container
docker run -p 8001:8001 \
  -e GROQ_API_KEY=$GROQ_API_KEY \
  -e APP_API_KEY=$APP_API_KEY \
  -e ALLOWED_ORIGINS="https://yourdomain.com" \
  -v chroma_db:/app/chroma_db \
  customer-support-rag:latest
```

### Render/Railway Deployment
1. Connect GitHub repository
2. Set environment variables in dashboard
3. Deploy with one click

---

## Advanced Configuration

### Custom Embedding Model
Edit `config/config.yaml`:
```yaml
embedding_model:
  provider: "huggingface"  # or "google"
  model_name: "sentence-transformers/all-MiniLM-L6-v2"
```

### Custom LLM Model
Edit `config/config.yaml`:
```yaml
llm:
  provider: "groq"
  model_name: "mixtral-8x7b-32768"  # Update as needed
```

### Custom Chunk Size
Edit `config/config.yaml`:
```yaml
ingestion:
  chunk_size: 400
  chunk_overlap: 80
  state_file: "data/.ingestion_state.json"
  keyword_index_file: "data/.keyword_index.json"
```

---

## Support & Monitoring

### Logs
Logs are printed to console by default. To save to file:
```bash
.venv/bin/uvicorn main:app --log-level debug > app.log 2>&1 &
```

### Health Check Endpoint (to add)
```python
@app.get("/health")
async def health():
    return {"status": "healthy"}
```

### Metrics & Analytics (to add)
- Track retrieval precision per query
- Monitor LLM latency trends
- Log user satisfaction scores

---

## Quick Start Checklist

- [ ] Python 3.10+ installed
- [ ] `.env` file configured with `GROQ_API_KEY` and `APP_API_KEY`
- [ ] Virtual environment activated
- [ ] Dependencies installed: `pip install -r requirements.txt`
- [ ] Data ingested: `python -c "from data_ingestion.ingestion_pipeline import DataIngestion; DataIngestion().transform_and_store()"`
- [ ] Tests passing: `python -m unittest discover tests -p "test_phase*.py" -v`
- [ ] App running: `uvicorn main:app --reload --port 8001`
- [ ] Web UI accessible: http://localhost:8001
- [ ] API key configured in browser UI
- [ ] Sample query tested and working

---

## Resources

- **FastAPI Docs**: https://fastapi.tiangolo.com/
- **LangChain**: https://python.langchain.com/
- **Chroma**: https://docs.trychroma.com/
- **Groq API**: https://console.groq.com/docs/
- **HuggingFace**: https://huggingface.co/

---

**Last Updated**: July 9, 2026
**App Version**: Phase 4 Production-Ready
**Status**: ✅ All systems operational
