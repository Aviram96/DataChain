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

- `/` — Home
- `/login` — Sign in (error toast on wrong password)
- `/register` — Create account (error toast on duplicate email)
- `/project-status` — Example secondary page

## Proof (local)

```bash
npm run lint
npm run format:check
npm run build
```
