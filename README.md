# Spatial Intelligence · VTHacks14

A full-stack spatial intelligence dashboard and interactive 3D modeling workspace built for VTHacks 14.

The demo flow is real end-to-end: a React client sends a scan request to FastAPI, the reconstruction service produces scene JSON, and the frontend renders the returned geometry with Three.js.

## Run locally

Prerequisites: Node.js 22.12+, Python 3.11+, and [uv](https://docs.astral.sh/uv/).

Start the backend:

```bash
cd backend
uv sync --locked
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal, start the frontend:

```bash
cd frontend
npm ci
npm run dev
```

Open <http://127.0.0.1:5173>. API health is available at <http://127.0.0.1:8000/api/health>, with interactive API documentation at <http://127.0.0.1:8000/docs>.

## Project structure

```text
.
├── backend/               # FastAPI service, reconstruction logic, and API tests
│   ├── app/
│   ├── tests/
│   ├── pyproject.toml
│   └── uv.lock
├── frontend/              # React, TypeScript, Vite, Three.js, and browser tests
│   ├── src/
│   ├── tests/
│   ├── package.json
│   └── package-lock.json
├── dist/                  # Original static UI prototype
└── .openai/hosting.json   # Static prototype hosting configuration
```

## Verify

```bash
# Backend
cd backend
uv run pytest -q
uv run ruff check app tests
uv run ruff format --check app tests

# Frontend
cd ../frontend
npm run typecheck
npm run build
npm run test:e2e
```

The backend currently uses deterministic mock reconstruction data and in-memory storage. The HTTP transport, validation, scan lifecycle, scene contract, rendering, error handling, navigation, and JSON export are implemented end-to-end.
