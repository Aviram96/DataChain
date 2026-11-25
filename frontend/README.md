# Datachain frontend

Next.js dashboard (Epic 1 scaffold): **App Router**, **TypeScript**,
**Tailwind CSS**, **ESLint**, **Prettier**.

## Prerequisites

- **Node.js** 20+ or 22+ (LTS recommended) and **npm**

## Install

```bash
cd frontend
npm install
```

## Scripts

| Command                | Purpose                   |
| ---------------------- | ------------------------- |
| `npm run dev`          | Dev server (Turbopack)    |
| `npm run build`        | Production build          |
| `npm run start`        | Run production build      |
| `npm run lint`         | ESLint                    |
| `npm run format`       | Prettier write            |
| `npm run format:check` | Prettier check (CI-style) |

Dev server defaults to
[http://127.0.0.1:3000](http://127.0.0.1:3000).

## Environment variables

Copy `frontend/.env.example` to `frontend/.env.local` only if you need a custom API URL.

By default, the dev server proxies **`/api/*`** → `http://127.0.0.1:8000/*` (see `next.config.ts`), so login/register avoid browser CORS issues.

**Watch playback (CP-E.C5):** choosing a saved time plays the contiguous stretch as one sequence. Each segment is loaded from `GET /cameras/{id}/recordings/{record_id}/playback` after the API verifies it. The next segment is verified before it is preloaded. A segment that fails verification is not played. The page does not open a public IPFS gateway URL.

**Verification:** the camera page does not read the blockchain. Watch and Download ask the API to verify each segment. A segment that fails verification is not played. The page does not show a separate Verify button or a verification-history list.

**Download:** after Watch opens a range, **Download** in the player asks the API to verify that whole range and save an `.mp4` of the verified portions only. A range with no verified segment saves nothing. The backend needs FFmpeg on PATH.

**Before using `/login` or `/register`, start the backend:**

```bash
# from repo root — Postgres
docker compose up -d

# backend/.env with DATABASE_URL and JWT_SECRET_KEY (see backend/.env.example)
cd backend
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then `cd frontend && npm run dev` and open [http://127.0.0.1:3000/register](http://127.0.0.1:3000/register).

Quick API check: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) should return `{"status":"ok"}`.

## Routes

- `/` — Marketing landing (no top toolbar): project / problem / solution + Sign up / Log in; signed-in users redirect to `/cameras`
- `/login` — Log in (error toast on wrong password); header updates after sign-in
- `/register` — Sign up (error toast on duplicate email)
- Header (app pages) — Brand label **DataChain** (not a link). When signed in: **Cameras**, **Archive**, **Add camera**, and an account menu with the email and **Log out**. When signed out: Log in / Sign up
- `/cameras` — Camera dashboard (main app surface after auth)
- `/cameras/new`, `/cameras/[id]`, `/cameras/[id]/edit` — add, detail (recordings search, Watch, Verify, Download, verification history), edit
- Camera **Online/Offline** badge is whether the stream can be reached, or whether an older ingest run gave up after its FFmpeg restart cap (`offline_reason` `ingest_failed`, with **since** on the card). It does not mean a recording is in progress. Automatic recording is a separate supervisor: from `backend/`, `.venv/bin/python scripts/ingest_camera.py --supervise`. While that process is running, a new or restored active camera is recorded when its stream is available, and Archive stops that recording. Restore does not need a manual start. Historical playback and download stay available after Archive.
- `/project-status` — Internal/dev status page (not linked from landing)

Expired or invalid JWTs clear `datachain_access_token` in localStorage and redirect to `/login` (toast on protected pages). Session is checked on app load via `GET /auth/me` and on any authenticated API call that returns 401.

**Verify auto-logout:** set `JWT_ACCESS_TOKEN_EXPIRE_MINUTES=1` in `backend/.env`, restart the API, sign in, wait past expiry, then navigate or refresh — you should land on `/login` with an expiry toast.

## Proof (local)

```bash
npm run lint
npm run format:check
npm run build
```
