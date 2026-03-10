# Wiki Service

FastAPI + MongoDB service for laboratory materials.

## Run local

```bash
pip install -r requirements.txt
python scripts/seed_labs.py
uvicorn src.main:app --reload --port 8001
```

`seed_labs.py` upserts 16 laboratory materials (`lr01` ... `lr16`) from markdown files in `wiki/materials/labs`.
