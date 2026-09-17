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

Copy `frontend/.env.example` to `frontend/.env.local` only if you need a custom API URL, IPFS gateway, or Polygon RPC/contract.

By default, the dev server proxies **`/api/*`** → `http://127.0.0.1:8000/*` (see `next.config.ts`), so login/register avoid browser CORS issues.

**Watch playback (CP-E.C5):** the camera page streams each minute from a public IPFS HTTP gateway:

`{NEXT_PUBLIC_IPFS_GATEWAY}/ipfs/{cid}`

If `NEXT_PUBLIC_IPFS_GATEWAY` is unset, the app uses `https://gateway.pinata.cloud`. Set a dedicated gateway origin (no trailing slash, no `/ipfs` suffix) when you have one.

**Verify (CP-E.C7):** the camera page compares each expected minute’s API CID/hash/times to on-chain `getSegment` via **ethers.js**. The browser calls same-origin **`/amoy-rpc`**, rewritten to `NEXT_PUBLIC_POLYGON_RPC_URL` (default `https://polygon-amoy.drpc.org`). Contract default is the live Amoy Datachain address; override with `NEXT_PUBLIC_DATACHAIN_CONTRACT_ADDRESS` if you redeploy. Transaction hashes open on Polygonscan (`NEXT_PUBLIC_POLYGONSCAN_TX_BASE`). Restart `npm run dev` after changing `NEXT_PUBLIC_*` values.

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
- Header (app pages) — When signed in: **Signed in as** email + **Log out**; when signed out: Log in / Sign up
- `/cameras` — Camera dashboard (main app surface after auth)
- `/cameras/new`, `/cameras/[id]`, `/cameras/[id]/edit` — add, detail (recordings search, Watch from IPFS, Verify range), edit
- Camera **Online/Offline** badge; when ingest hits the FFmpeg restart cap, `offline_reason` is `ingest_failed`, `ingest_offline_at` is set, and the card/detail explain that footage may be missing **since** that time (CP-C.C1)
- `/project-status` — Internal/dev status page (not linked from landing)

Expired or invalid JWTs clear `datachain_access_token` in localStorage and redirect to `/login` (toast on protected pages). Session is checked on app load via `GET /auth/me` and on any authenticated API call that returns 401.

**Verify auto-logout:** set `JWT_ACCESS_TOKEN_EXPIRE_MINUTES=1` in `backend/.env`, restart the API, sign in, wait past expiry, then navigate or refresh — you should land on `/login` with an expiry toast.

## Proof (local)

```bash
npm run lint
npm run format:check
npm run build
```
