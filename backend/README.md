# Datachain backend

FastAPI service for Datachain. Epic 2 adds SQLAlchemy models and Alembic migrations.

## Prerequisites

- Python **3.11+** (`python --version`)

## Virtual environment

### Windows (PowerShell)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

### macOS / Linux

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

Deactivate anytime: `deactivate`

## Environment variables

Create `backend/.env` (or export in your shell) based on `backend/.env.example`.

Required for DB-connected workflows:

```bash
DATABASE_URL=postgresql+psycopg://datachain:datachain_dev@localhost:5432/datachain
```

## Run the API

From `backend/` with the venv activated:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- OpenAPI docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)  
- Health check: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

Quick check:

```bash
curl -s http://127.0.0.1:8000/health
```

Expected: `{"status":"ok"}`

### Register a user (Epic 3, US-3.1)

With Postgres running and migrations applied:

```bash
curl -s -X POST http://127.0.0.1:8000/auth/register \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"you@example.com\",\"password\":\"your-secure-pass\"}"
```

Expected on success: JSON with `id`, `email`, and `created_at`. Duplicate email returns HTTP **409**.

## Database migrations (Alembic)

From `backend/` with the venv activated:

```bash
# apply all migrations
alembic upgrade head

# create a new migration after model changes
alembic revision --autogenerate -m "describe change"

# rollback one migration
alembic downgrade -1
```

## Tests

From `backend/` with dev dependencies installed:

```bash
pytest -q
```

## Lint and format

From `backend/` with dev dependencies installed:

```bash
black .
flake8 .
```

CI-style check without writing files:

```bash
black --check .
flake8 .
```

