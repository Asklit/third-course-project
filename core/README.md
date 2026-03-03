# Core Service

FastAPI demo core for LMS:
- student auth (JWT login + refresh)
- assignments list/details
- submission upload (`multipart/form-data`)
- wiki proxy endpoints
- structured JSON logging with trace id

## Run local

```bash
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8000
```
