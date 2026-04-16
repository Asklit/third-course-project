# LMS Course Project

This project was developed by a third-year student as part of a course project and is intended as a component of a broader university course ecosystem aimed at improving learning management.

The system focuses on two practical areas:

- managing student submissions for laboratory assignments;
- providing structured access to course materials with search capabilities.

## Overview

The application supports the following workflow:

- a student signs in to the system;
- views the list of available laboratory assignments;
- opens an assignment and navigates to the corresponding wiki material;
- uploads a report, source code files, or a repository link;
- updates an existing submission if needed;
- searches across course materials.

In addition to submission management, the project includes a dedicated wiki service that transforms source `.docx` teaching materials into a format suitable for web delivery: structured sections, markdown content, assets, and searchable data.

## Implemented Components

The project follows a microservice-based structure and includes several services with distinct responsibilities.

### `core`

The main backend service built with `FastAPI`. It contains the minimum required system functionality for working with materials and user identification.

Implemented features:

- student authentication using JWT;
- refresh token handling and token revocation;
- assignment list and assignment details;
- submission status retrieval;
- multipart submission upload;
- storage of reports, code files, and submission metadata on disk;
- callback support after submission updates;
- proxy endpoints for wiki-related requests;
- structured JSON logging and healthcheck.

### `wiki`

A separate backend service responsible for course materials and search.

Implemented features:

- parsing source `.docx` documents;
- building curated material representations;
- extracting sections, tables, formulas, and images;
- storing materials in MongoDB;
- serving the list of labs and full lab content;
- serving static assets;
- full-text search across materials;
- integration with `Meilisearch`;
- fallback search when the search engine is unavailable.

### `frontend`

A client application built with `React`, `TypeScript`, and `Vite`.

The frontend is primarily intended to demonstrate the user flow and integration between services.

Implemented features:

- login page;
- assignment list page;
- assignment details page;
- submission form for reports and code;
- wiki pages;
- search across learning materials;
- navigation between assignments and corresponding wiki content.

### Infrastructure Services

The system relies on several storage and infrastructure components:

- `PostgreSQL` for relational data in the main service;
- `MongoDB` for wiki materials;
- `Meilisearch` for search;
- `Docker Compose` for local orchestration.

## Project Structure

```text
core/       main backend service
wiki/       materials and search service
frontend/   demonstration web client
lms/        docker compose, nginx, and project-related files
data/       directory for persisted runtime data
```

## Architecture Notes

The project is centered around separation of responsibilities between services:

- `core` acts as the main entry point for the client;
- `wiki` owns material processing, storage, and search logic;
- relational and document-oriented data are stored separately according to their use case;
- submitted files are stored on disk together with metadata.

This structure allows the project to demonstrate not only the client-side flow but also backend service interaction, multi-storage integration, and document processing.

## Running the Project

### Option 1. Run the full system with Docker Compose

This is the recommended way to start the project.

#### Requirements

- `Docker`
- `Docker Compose`

#### Start command

From the `lms` directory:

```bash
docker compose up --build
```

After startup, the services will be available at:

- frontend: `http://localhost:5173`
- core API: `http://localhost:8000`
- wiki API: `http://localhost:8001`
- Meilisearch: `http://localhost:7700`
- PostgreSQL: `localhost:5432`
- MongoDB: `localhost:27017`

### Option 2. Run services locally

This option is convenient for development and debugging.

#### `core`

```bash
cd core
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8000
```

#### `wiki`

```bash
cd wiki
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8001
```

#### `frontend`

```bash
cd frontend
npm install
npm run dev
```

For local execution, the following services must also be available:

- `PostgreSQL`
- `MongoDB`
- optionally `Meilisearch`

## Environment Variables

Default values are already defined in the services, but they can be overridden when needed.

### `core`

- `DATABASE_URL`
- `JWT_SECRET`
- `WIKI_BASE_URL`
- `CALLBACK_URL`
- `SUBMISSIONS_DIR`

### `wiki`

- `MONGO_URL`
- `MONGO_DB`
- `MONGO_COLLECTION`
- `MEILI_ENABLED`
- `MEILI_URL`
- `MEILI_INDEX`

### `frontend`

- `VITE_API_BASE_URL`

## Current Scope

The current version includes the student-side flow and the supporting backend functionality required for assignment submission and access to learning materials.

The repository also contains:

- Docker-based local infrastructure;
- tests for core backend and wiki logic;
- source materials used by the wiki pipeline.
