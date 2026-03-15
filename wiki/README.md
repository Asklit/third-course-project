# Wiki Service

FastAPI + MongoDB service for laboratory materials with:
- source-driven content pipeline (`materials/sources` -> `materials/curated`)
- section-based markdown materials with assets
- search by phrase/tags/section type

## Run local

```bash
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8001
```

On startup service:
1. parses `.docx` from `wiki/materials/sources`
2. builds curated markdown + assets in `wiki/materials/curated`
3. upserts structured materials into MongoDB
