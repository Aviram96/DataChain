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

**JWT (Epic 3):** set **`JWT_SECRET_KEY`** to a long random string (for example `openssl rand -hex 32`). The API process exits on startup if it is missing or blank. Optional: **`JWT_ACCESS_TOKEN_EXPIRE_MINUTES`** (default `60`, capped at one week).

**CORS (Epic 3 frontend):** optional **`CORS_ORIGINS`** comma-separated list (default `http://127.0.0.1:3000,http://localhost:3000`) so the Next.js app can call the API from the browser.

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

### Log in and call a protected route (Epic 3, US-3.3)

Set **`JWT_SECRET_KEY`** in your environment (see `backend/.env.example`); the app refuses to start without it.

```bash
curl -s -X POST http://127.0.0.1:8000/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"you@example.com\",\"password\":\"your-secure-pass\"}"
```

Expected on success: `{"access_token":"...","token_type":"bearer"}`. Wrong email or password returns HTTP **401** with the same error message (no user enumeration).

```bash
curl -s http://127.0.0.1:8000/auth/me \
  -H "Authorization: Bearer <paste_access_token_here>"
```

Expected on success: same shape as register response (`id`, `email`, `created_at`). Missing or invalid token returns HTTP **401**.

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

## Camera online/offline (Slice B / CP-B.P4)

List and detail responses include a **`status`** field: `"online"` or `"offline"`. Status is **offline** if either:

- the live **`stream_url` probe** fails (HTTP/HTTPS request or RTSP OPTIONS / TCP), or
- camera ingest marked the camera down after FFmpeg hit its restart cap (`ingest_offline_at`; Slice C / CP-C.P8). A new ingest run clears that flag when it starts.

When `status` is `"offline"`, **`offline_reason`** distinguishes the cause (Slice C / CP-C.C1):

- `"ingest_failed"` — ingest stopped after the FFmpeg restart cap (even if the URL still answers a probe)
- `"unreachable"` — the live stream probe failed
- `null` — camera is online

If both apply, `ingest_failed` wins so the dashboard can explain that footage may be missing.

List and detail also include **`ingest_offline_at`**: an ISO-8601 timestamp when ingest hit the restart cap, or `null` otherwise. The camera card and detail page use it to say **since …** when capture stopped.

Probe details (not stored in the database):

- **HTTP/HTTPS:** short request to the stream URL (HEAD, then ranged GET). Any HTTP response (including 401/404) counts as **online**; network failures → **offline**.
- **RTSP:** TCP connect to the RTSP port, then a minimal `OPTIONS` request when possible. An open RTSP port counts as reachable.
- **Default ports** when omitted: `http` → 80, `https` → 443, `rtsp` → 554.
- **Not validated:** whether a full video stream is playable end-to-end (codec/auth beyond basic reachability).
- **Timeout:** `CAMERA_PROBE_TIMEOUT_SECONDS` (default `2`, clamped 0.5–10). List endpoints probe in parallel (up to 10 workers).

### Camera list query params

| Param | Meaning |
| ----- | ------- |
| `page`, `page_size` | Pagination (default page size 10, max 50) |
| `q` | Case-insensitive name search |
| `status` | `online` or `offline` (live probe **or** ingest restart-cap flag) |
| `sort` | Default `created_at_desc` (newest first). Also `created_at_asc`, `name_asc`, `name_desc` |

### Soft delete and unique names

- `DELETE /cameras/{id}` sets **`deleted_at`** (soft delete). The camera disappears from the dashboard; the row remains so historical `video_records` are not destroyed (`ON DELETE RESTRICT` on `video_records.camera_id`).
- Active cameras must have a **unique name per user** (case-insensitive); duplicates return HTTP 409.

### Stream attach for ingest (CP-B.P5)

`app.services.camera_stream.attach_camera_stream(db, camera_id)` returns the `stream_url` for an **active** (non-deleted) camera. Continuous FFmpeg receive is Slice C / **CP-C.P2** (`scripts/ingest_camera.py`).

After changing `.env`, restart uvicorn; reload may not pick up new values.

## Simulated CCTV feed (Slice C / CP-C.P1)

This is the **Slice C hardware-free entry point**: **loop a local `.mp4` at real-time speed** as if it were a live camera feed, so ingest can be developed without RTSP cameras. This uses **FFmpeg** on your machine (install separately; not a Python package).

**Prerequisites:** FFmpeg on `PATH` ([download](https://ffmpeg.org/download.html)).

From `backend/` with the venv activated:

```powershell
# Option A: explicit file
python scripts/simulate_cctv_feed.py --source C:\path\to\sample.mp4

# Option B: environment variable (see backend/.env.example)
$env:CCTV_SOURCE_MP4 = "C:\path\to\sample.mp4"
python scripts/simulate_cctv_feed.py
```

The process writes a continuous **MPEG-TS** stream to **stdout** (suitable for piping into the chunking step in the next slice). Press **Ctrl+C** to stop; the script terminates FFmpeg cleanly.

**Note:** Use a short sample clip for testing; the file loops forever until you stop the script.

## Camera stream ingest (Slice C / CP-C.P2–P8)

Receive the **live `stream_url`** of a registered camera with FFmpeg (HTTP/HTTPS or RTSP) and split it into **1-minute `.mp4` segments** under `backend/temp/<camera-id>/`. Each file is named `{camera-uuid}_{YYYYMMDDTHHMMSS}Z.mp4` (camera ID + recording start). End time is start plus the segment duration (default 60s); parse with `app.services.segment_identity.parse_segment_path`. After a file is closed, a **basic integrity check** runs before later stages: complete MP4 (`ftyp` + `moov`), a video stream (ffprobe), and a SHA-256 fingerprint. Failed files stay in `temp/` and are not handed on. **Passing files stay under `temp/<camera-id>/` until processing succeeds.** Temp files are **deleted only after processing succeeds**; processing failures stay on disk and are retried. IPFS / chain / DB is still a stub, so this ingest path does not delete on staging-only success. Soft-deleted cameras are skipped.

If FFmpeg exits unexpectedly, ingest **restarts it** (delay `CCTV_FFMPEG_RESTART_DELAY_SECONDS`, default 2s) up to **`CCTV_FFMPEG_MAX_RESTARTS` (default 10 for camera ingest)**. Each attempt is logged with the camera id. After the cap, ingest stops and sets **`ingest_offline_at`** so the camera shows **offline** on the dashboard even if the URL still answers a probe (`offline_reason`: `ingest_failed`). A later ingest run clears that flag when it starts. Apply Alembic revision `20260824_000003`.

From `backend/` with the venv activated, Postgres running, and migrations applied:

```powershell
# One camera
python scripts/ingest_camera.py --camera-id 00000000-0000-0000-0000-000000000001

# Every active camera (one FFmpeg process per camera)
python scripts/ingest_camera.py --all
```

Ctrl+C stops ingest. RTSP uses TCP transport. Requires FFmpeg on `PATH`. Optional `--temp-dir` and `--duration` (default 60 seconds).

## Video chunking (Epic 5, slice 2)

Split a local `.mp4` into **1-minute** segments written to **`backend/temp/`** (gitignored). Uses FFmpeg’s **segment muxer** with `-segment_time 60`.

From `backend/` with the venv activated:

```powershell
# One pass: chunk the whole file, then exit (good for short test clips)
python scripts/chunk_cctv_feed.py --source C:\path\to\sample.mp4

# Continuous CCTV-style loop: keeps chunking until Ctrl+C
python scripts/chunk_cctv_feed.py --source C:\path\to\sample.mp4 --loop
```

Output files: `backend/temp/chunk_000.mp4`, `chunk_001.mp4`, … (directory created automatically).

Optional flags: `--temp-dir DIR`, `--duration SECONDS` (default **60**), or env vars `CCTV_TEMP_DIR` / `CCTV_CHUNK_DURATION_SECONDS` (see `backend/.env.example`).

**Tip:** For a 2–3 minute sample without `--loop`, you should see 2–3 chunk files and the process exits on its own.

## Temp cleanup worker (Epic 5, slice 3)

After a chunk is **successfully processed**, a background worker **deletes it from `temp/`** so disk use stays bounded. Epic 6 will replace the stub processor with IPFS upload + chain anchor + DB write; until then the worker logs and deletes (stub success).

This Epic 5 file-chunk path is separate from **camera ingest** (`ingest_camera.py`), which **stages** segments under `temp/<camera-id>/` until processing succeeds. Ingest **deletes a temp file only after processing succeeds** and keeps failed / retry files; the current ingest processor is still a stub, so those files are not deleted yet.

**With chunking** — process and delete each segment as it lands:

```powershell
python scripts/chunk_cctv_feed.py --source C:\path\to\sample.mp4 --cleanup-after-success
```

**After chunking** — drain existing files in `temp/` once:

```powershell
python scripts/process_temp_chunks.py
```

The worker only deletes files matching `chunk_*.mp4` **inside** the configured temp directory (never arbitrary paths).

## FFmpeg crash recovery (Epic 5, slice 4 / Slice C CP-C.P8)

Continuous ingest **restarts FFmpeg automatically** after a non-zero exit. One-pass chunking does not restart (normal end of file is exit 0).

- **Delay before restart:** `CCTV_FFMPEG_RESTART_DELAY_SECONDS` (default **2**)
- **Cap retries:** `CCTV_FFMPEG_MAX_RESTARTS` — **camera ingest** defaults to **10**, then marks the camera offline. Feed simulator and `chunk_cctv_feed.py --loop` stay unlimited unless this env var is set.
- **Stop:** Ctrl+C still terminates the current FFmpeg process and exits cleanly

Implementation: `backend/app/services/ffmpeg_supervisor.py` (shared by feed simulator, loop chunker, and `ingest_camera.py`).

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

