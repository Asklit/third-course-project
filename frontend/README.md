# LMS Frontend

React + TypeScript + Vite frontend for student flow:
- login via JWT
- assignments list
- assignment details + file submission (`multipart/form-data`)

## Architecture

Layered feature-oriented structure:
- `src/app` - app bootstrap, routing, global providers
- `src/pages` - route-level pages
- `src/features` - business actions (`auth`, `submission`)
- `src/entities` - domain entities (`assignment`)
- `src/shared` - reusable infrastructure (API client, config, utils, types)

## Local run (without Docker)

```bash
npm install
npm run dev
```

## Docker run

From `lms` directory:

```bash
docker compose up --build frontend
```

Frontend will be available at `http://localhost:5173`.

## Environment

Use `VITE_API_BASE_URL` for core API base URL.
Default in compose: `http://localhost:8000`.
