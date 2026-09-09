# Datachain — Roadmap

This roadmap translates the Datachain vision (hybrid Web2/Web3 CCTV integrity platform) into **epics**, **sprints**, and **user stories**. Order within an epic can be parallelized where dependencies allow; **Epic 1** is the foundation for everything else.

---

## Epic 1: Environment & DevOps Setup

**Goal**: Runnable monorepo with consistent tooling and CI.

Keep the **Status** column in this table aligned with the repository as work lands (see **Documentation updates** in `AGENTS.md`).


| Story   | Description                                                                                              | Status                                                                                                                |
| ------- | -------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| US-1.1  | As a developer, I want a monorepo with `frontend`, `backend`, and `contracts` packages so the team can work in one repository. | Done — all three packages scaffolded; `contracts/` uses **Hardhat 3** (TypeScript, Viem, `node:test`); see `contracts/README.md` |
| US-1.2  | As a developer, I want a Next.js application scaffold so I can build the frontend.                         | Done — `frontend/` App Router; see `frontend/README.md`                                                                 |
| US-1.3  | As a developer, I want Tailwind CSS configured in the frontend so UI styling is consistent.              | Done — `frontend/tailwind.config.ts`, `globals.css`; see `frontend/README.md`                                          |
| US-1.4  | As a developer, I want App Router pages and navigation so users can move between screens.                | Done — `/`, `/project-status`, and later auth/camera routes; see `frontend/README.md`                                 |
| US-1.5  | As a developer, I want a FastAPI backend with a documented virtual environment so I can build the API.   | Done — `backend/` (`GET /health`), `requirements.txt`, venv docs in `backend/README.md`                               |
| US-1.6  | As a developer, I want PostgreSQL available via Docker Compose so I can run the database locally without manual setup. | Done — root `docker-compose.yml`, documented in `README.md`                                                           |
| US-1.7  | As a developer, I want a Hardhat environment for Solidity smart contracts so I can compile and test on-chain logic. | Done — **Hardhat 3** (`@nomicfoundation/hardhat-toolbox-viem`); `npm run compile` / `npm test` in `contracts/`        |
| US-1.8  | As a developer, I want ESLint and Prettier configured for the frontend so code style stays consistent.   | Done — `frontend/eslint.config.mjs`, Prettier config; scripts in `frontend/README.md`                                 |
| US-1.9  | As a developer, I want Black and Flake8 configured for the backend so Python formatting stays consistent. | Done — `backend/pyproject.toml`, `backend/.flake8`, documented in `backend/README.md`                                 |
| US-1.10 | As a developer, I want a GitHub Actions workflow that runs lint and tests on pull requests so regressions are caught early. | Done — `.github/workflows/ci.yml` (frontend lint/format/build, backend Black/Flake8, contracts compile/test) on `main` PRs and pushes |


**Exit criteria**: Local dev can start DB, run API and frontend, compile contracts, and CI passes lint on sample workflow.

**Progress note**: Epic 1 **exit criteria met** for the current scaffold: **GitHub Actions** runs on pushes to **`main`** and **pull requests** targeting **`main`** (see `.github/workflows/ci.yml`). Dependency audits: see `contracts/README.md`.

---

## Epic 2: Database Schema & Models

**Goal**: Persistent relational model for users, cameras, and video records with migrations.


| Story  | Description                                                                                              | Status |
| ------ | -------------------------------------------------------------------------------------------------------- | ------ |
| US-2.1 | As the system, I need to persist user accounts in PostgreSQL so authentication can reference them.       | Done — `backend/app/models.py` (`users`) |
| US-2.2 | As the system, I need to store cameras linked to users so each owner sees only their devices.            | Done — `backend/app/models.py` (`cameras.user_id` FK → `users.id`) |
| US-2.3 | As the system, I need each video record linked to a camera with segment start and end timestamps.         | Done — `backend/app/models.py` (`video_records.camera_id` FK, timestamps) |
| US-2.4 | As the system, I need each video record to store an IPFS CID and blockchain transaction hash.            | Done — `backend/app/models.py` (`video_records.cid`, `tx_hash`) |
| US-2.5 | As a developer, I want Alembic migrations so database schema changes are versioned and reproducible.    | Done — `backend/alembic.ini`, `backend/alembic/env.py`, initial migration in `backend/alembic/versions/` |


**Exit criteria**: Migrations apply cleanly; models reflect relationships needed for CRUD and the video pipeline.

---

## Epic 3: Authentication & Authorization

**Goal**: Secure account lifecycle and API access with JWT.


Keep the **Status** column in this table aligned with the repository as work lands (see **Documentation updates** in `AGENTS.md`).


| Story  | Description                                                              | Status |
| ------ | ------------------------------------------------------------------------ | ------ |
| US-3.1 | As a user, I want to register an account with email and password.        | Done — `POST /auth/register` in `backend/app/routers/auth.py`; email normalized; HTTP 409 on duplicate; `User` in `backend/app/models/user.py`; responses omit secrets |
| US-3.2 | As the system, I need to hash user passwords with bcrypt before saving.  | Done — `hash_password` / `verify_password` in `backend/app/security/password.py`; optional `BCRYPT_ROUNDS`; tests in `backend/tests/test_password.py` |
| US-3.3 | As a user, I want to log in and receive a secure JWT.                    | Done — `POST /auth/login`, `GET /auth/me`; JWT (HS256) in `backend/app/security/jwt_tokens.py`; `get_current_user` in `backend/app/deps_auth.py`; `JWT_SECRET_KEY` required at startup |
| US-3.4 | As a user, I want a UI error toast when I enter the wrong password at login. | Done — `/login` in `frontend/`; error toast on HTTP 401; `ToastProvider` in `frontend/components/toast-provider.tsx`; API via `frontend/lib/auth-api.ts` |
| US-3.5 | As a user, I want a UI error toast when I try to register with an email that is already in use. | Done — `/register` in `frontend/`; error toast on HTTP 409; CORS for dev in `backend/app/main.py` |
| US-3.6 | As the system, I need to detect JWT expiration on the client before protected requests fail silently. | Done — `frontend/lib/auth-token.ts`, `auth-session.ts`; client reads JWT `exp` on load |
| US-3.7 | As the system, I need to log the user out and redirect to login when the session is expired or invalid. | Done — `frontend/lib/auth-fetch.ts`; 401 clears token and redirects to `/login` with optional toast |
| US-3.8 | As a user, I want to log out securely and clear my session.            | Done — `AuthProvider` + `SiteHeader` (`Signed in as …`, Log out); `logout()` clears token and expiry timer; login calls `refreshSession()` for header state |


**Exit criteria**: Registration, login, logout, and protected routes behave per stories; secrets not logged.

**Progress note**: **US-3.1–US-3.8** complete on branch `epic3` (registration, login, JWT expiry handling, logout UX). Epic 3 exit criteria met for auth stories; refresh tokens remain out of scope.

---

## Epic 4: Camera Management (CRUD)

**Goal**: Users manage IP cameras tied to their account with scalable listing.


| Story  | Description                                                            | Status |
| ------ | ---------------------------------------------------------------------- | ------ |
| US-4.1 | As a user, I want a UI form to add a new camera (Name, IP/URL, Location). | Done — `/cameras/new`, `CameraForm` in `frontend/components/camera-form.tsx`, `createCamera` in `frontend/lib/cameras-api.ts`; JWT via `authFetch`; `RequireAuth` redirects guests to `/login` |
| US-4.2 | As the backend, I need to validate camera name, IP/URL, and location before saving. | Done — validation in `backend/app/schemas/camera.py` |
| US-4.3 | As the backend, I need owner-scoped camera CRUD endpoints backed by PostgreSQL. | Done — `Camera` in `backend/app/models/camera.py`; `POST/GET/PATCH/DELETE /cameras` in `backend/app/routers/cameras.py`; tests in `backend/tests/test_cameras_api.py` |
| US-4.4 | As a user, I want to view a dashboard grid of all my registered cameras. | Done — `/cameras`, `CamerasDashboard` + `CameraCard` in `frontend/components/`; `listCameras` in `frontend/lib/cameras-api.ts` |
| US-4.5 | As a user, I want to edit the details of an existing camera.          | Done — `/cameras/[id]/edit`, `getCamera` / `updateCamera` in `frontend/lib/cameras-api.ts`; `CameraForm` prefill via `initialValues`; Edit link on `CameraCard` |
| US-4.6 | As a user, I want to delete a camera and remove it from my dashboard. | Done — `deleteCamera` in `frontend/lib/cameras-api.ts`; inline confirm on `CameraCard`; dashboard removes card and updates count on success |
| US-4.7 | As the backend, I need to probe camera reachability so Online/Offline status can be determined. | Done — TCP reachability probe in `backend/app/services/camera_probe.py`; `status` on `CameraPublic`; documented in `backend/README.md` |
| US-4.8 | As a user, I want to see an Online/Offline status badge on each camera card. | Done — badge on `CameraCard` |
| US-4.9 | As a user, I want pagination on my camera list when I have more than 10 cameras. | Done — `CamerasDashboard` Previous/Next controls and page summary; uses API `page` / `pages`; reloads or steps back after delete on last item of a page |


**Exit criteria**: Full CRUD via API + UI; pagination and status indicators implemented per agreed rules (e.g., ping vs last-seen).

**Progress note**: **US-4.1–US-4.9** complete on branch `epic4`. Epic 4 exit criteria met for CRUD API + UI, pagination, and online/offline indicators.

---

## Epic 5: Video Processing Pipeline

**Goal**: Reliable local/simulated ingest, chunking, temp storage, and cleanup.


| Story  | Description                                                                                              | Status |
| ------ | -------------------------------------------------------------------------------------------------------- | ------ |
| US-5.1 | As a developer, I want to simulate a continuous CCTV feed from a local `.mp4` so I can test the pipeline without real RTSP hardware. | Done — `backend/scripts/simulate_cctv_feed.py`, `backend/app/services/cctv_feed_simulator.py`; FFmpeg loops source to stdout (`-re -stream_loop -1`); see `backend/README.md` |
| US-5.2 | As the backend, I need to use FFmpeg to chunk the video stream into exact 1-minute `.mp4` segments.      | Done — `backend/app/services/video_chunker.py`, `backend/scripts/chunk_cctv_feed.py`; FFmpeg segment muxer (`-segment_time 60`, `-segment_format mp4`); optional `--loop` for continuous ingest |
| US-5.3 | As the backend, I need to save the 1-minute chunks to a local `temp/` directory.                        | Done — default `backend/temp/` (`CCTV_TEMP_DIR` override); `chunk_%03d.mp4` naming; gitignored |
| US-5.4 | As the system, I need to delete processed temp chunks so local disk does not fill up.                     | Done — `backend/app/services/chunk_processing_worker.py`, `temp_chunk_cleanup.py`; `--cleanup-after-success` on chunk CLI; `scripts/process_temp_chunks.py`; stub processor until Epic 6 |
| US-5.5 | As the system, I need to gracefully restart the FFmpeg process if the simulated camera feed crashes.     | Done — `backend/app/services/ffmpeg_supervisor.py`; auto-restart on non-zero exit for feed simulator and `--loop` chunker; `CCTV_FFMPEG_RESTART_DELAY_SECONDS`, optional `CCTV_FFMPEG_MAX_RESTARTS` |


**Exit criteria**: Deterministic chunk duration; disk does not grow unbounded; recovery from process failure documented or automated.

**Progress note**: Epic 5 **exit criteria met** on branch `epic5` — simulated feed, 1-minute chunking, `temp/` output, cleanup worker, and FFmpeg crash restart for continuous modes.

---

## Epic 6: Web3 & Decentralized Storage

**Goal**: Pin IPFS CIDs and anchor metadata on Polygon Amoy; persist full provenance in PostgreSQL.


| Story   | Description                                                                                              |
| ------- | -------------------------------------------------------------------------------------------------------- |
| US-6.1  | As the backend, I need the Pinata IPFS SDK integrated so video chunks can be uploaded to decentralized storage. |
| US-6.2  | As the backend, I need to upload each 1-minute video chunk to IPFS and retrieve the cryptographic CID.   |
| US-6.3  | As the backend, I need retry logic when IPFS upload fails due to network timeout.                        |
| US-6.4  | As the system, I need a smart contract that maps camera video records to anchored IPFS CIDs so integrity can be verified on-chain. |
| US-6.5  | As a developer, I want a Hardhat deployment script for the Datachain contract.                           |
| US-6.6  | As a developer, I want the contract deployed to Polygon Amoy testnet so the app can use a live address.  |
| US-6.7  | As the backend, I need to use Web3.py to send a transaction anchoring the IPFS CID to the smart contract. |
| US-6.8  | As the backend, I need to handle Web3.py RPC timeout errors gracefully.                                  |
| US-6.9  | As the backend, I need to handle Web3.py gas failures gracefully.                                         |
| US-6.10 | As the backend, I need to save a video record with CameraID, Timestamp, and CID after a successful IPFS upload. |
| US-6.11 | As the backend, I need to update the video record with the TxHash after a successful on-chain anchor.     |


**Exit criteria**: End-to-end path from chunk file → CID → tx → DB row; contract address and ABI versioned for frontend verification.

---

## Epic 7: Video Dashboard & Retrieval

**Goal**: Drive-like browsing, filtering, and IPFS playback.


| Story   | Description                                                                                              |
| ------- | -------------------------------------------------------------------------------------------------------- |
| US-7.1  | As a user, I want a "My Videos" page with a Google Drive–style layout to browse my footage.              |
| US-7.2  | As the backend, I need an API endpoint that lists my video records for the authenticated user.           |
| US-7.3  | As the backend, I need an API endpoint that filters video records by date range.                         |
| US-7.4  | As the backend, I need an API endpoint that filters video records by camera.                             |
| US-7.5  | As the backend, I need paginated video record responses so large libraries stay performant.                |
| US-7.6  | As a user, I want to filter my videos by a specific date range on the dashboard.                         |
| US-7.7  | As a user, I want to filter my videos by a specific camera name on the dashboard.                        |
| US-7.8  | As a user, I want pagination on the video dashboard so the browser does not crash loading hundreds of videos. |
| US-7.9  | As a user, I want a loading skeleton UI while videos are being fetched from the database.                |
| US-7.10 | As a user, I want to click a video card and have it open a video player modal.                           |
| US-7.11 | As a user, I want the video player to stream the video directly from an IPFS gateway using the CID.      |


**Exit criteria**: Filters compose sensibly with pagination; player uses gateway URL pattern documented in env config.

---

## Epic 8: Cryptographic Verification (Core Feature)

**Goal**: Explicit integrity UX: on-chain truth vs retrieved CID.


| Story  | Description                                                                                     |
| ------ | ----------------------------------------------------------------------------------------------- |
| US-8.1 | As a user, I want a "Verify Integrity" button next to every video in my dashboard.              |
| US-8.2 | As the frontend, I need to connect to the deployed Polygon contract using ethers.js.            |
| US-8.3 | As the frontend, I need to read the anchored CID from the smart contract for the selected video. |
| US-8.4 | As a user, I want to see a visual green checkmark / 100% Verified badge when the blockchain CID matches the database CID. |
| US-8.5 | As a user, I want to see a visual red warning / Tampered badge when the CIDs do not match.      |
| US-8.6 | As a user, I want to click the transaction hash in the UI and be redirected to Polygonscan to view the blockchain ledger proof. |


**Exit criteria**: Verification path documented (RPC provider, contract ABI, network ID); mismatches explained in UI without leaking secrets.

---

## Epic 9: Testing & Quality Assurance

**Goal**: Automated confidence in contracts, API, and cross-layer pipeline.


| Story  | Description                                                                                              |
| ------ | -------------------------------------------------------------------------------------------------------- |
| US-9.1 | As a developer, I want automated contract tests so anchored metadata is stored correctly on-chain.       |
| US-9.2 | As a developer, I want API tests for user registration so the register endpoint stays correct.         |
| US-9.3 | As a developer, I want API tests for user login so the login endpoint stays correct.                     |
| US-9.4 | As a developer, I want API tests for camera CRUD operations so camera management stays correct.          |
| US-9.5 | As a developer, I want an integration test that verifies IPFS upload returns a CID for a chunk.          |
| US-9.6 | As a developer, I want an integration test that verifies blockchain anchor and database save after upload. |


**Exit criteria**: CI runs unit suites; integration test runnable locally with documented env (test keys, testnet faucet).

---

## Epic 10: Academic Deliverables (Project Book)

**Goal**: Written and diagrammatic artifacts for coursework submission.


| Story   | Description                                                                                              |
| ------- | -------------------------------------------------------------------------------------------------------- |
| US-10.1 | As a project author, I want a literature review chapter on traditional IoT vulnerabilities vs. blockchain immutability so the project is grounded in research. |
| US-10.2 | As a project author, I want a methodology chapter describing how the system was built and evaluated.   |
| US-10.3 | As a project author, I want an architecture chapter explaining the hybrid Web2/Web3 data flow.         |
| US-10.4 | As a project author, I want UML use case diagrams for user and system personas so stakeholders can see who interacts with the platform. |
| US-10.5 | As a project author, I want UML class diagrams mapping PostgreSQL models and smart contract structs so the data model is documented. |
| US-10.6 | As a project author, I want a UML sequence diagram showing the step-by-step cryptographic verification process so the integrity flow is clear. |
| US-10.7 | As a project author, I want a risk management document identifying risks such as private key loss and RPC node failure so mitigations are explicit. |


---

## Epic 11: Client / Programmer Requirements Audit & Delivery

**Goal**: Treat the teacher-facing client–programmer stories as the working checklist: trace each requirement against the repo, then implement gaps in order.

**Source of truth (stories):** [`docs/CLIENT_PROGRAMMER_USER_STORIES.md`](docs/CLIENT_PROGRAMMER_USER_STORIES.md) (organized rewrite of the `US.docx` draft).

Epics **1–10** above remain historical delivery notes for the original roadmap. Progress for the new format is tracked by story IDs (`CP-A.*` … `CP-E.*`) and Status columns in that document.


| Slice | Focus | Status |
| ----- | ----- | ------ |
| A | Register and Login | Done — all CP-A stories Implemented (see `docs/CLIENT_PROGRAMMER_USER_STORIES.md`) |
| B | Camera dashboard management | Done — all CP-B stories Implemented (search/filter/sort, soft delete, unique names, detail page) |
| C | Video processing pipeline | Done — CP-C.P1–P8 and CP-C.C1 Implemented |
| D | IPFS storage and blockchain anchoring | Not started — all stories TBD |
| E | Video management and verification | Not started — all stories TBD |


**Exit criteria**: Every story in `docs/CLIENT_PROGRAMMER_USER_STORIES.md` is Implemented, Deferred (with reason), or explicitly Declined; open decisions in that file are resolved.

**Progress note**: Slice A complete 2026-07-21 (including landing refinement: toolbar-free home, problem/solution, signed-in → `/cameras`). Slice B complete 2026-07-21 — apply Alembic revision `20260721_000002` for `deleted_at` + unique active name. Slice C complete 2026-09-09 — **CP-C.P1–P8** (simulate feed, receive stream, 1-minute chunks, camera+time filenames, pre-stage integrity check, stage under `temp/` until processing succeeds, delete temp files only after processing success, capped FFmpeg restart + ingest offline) and **CP-C.C1** (`offline_reason` `ingest_failed` vs `unreachable`; `ingest_offline_at` on the API so the card/detail can say **since** capture stopped); apply Alembic `20260824_000003` for `ingest_offline_at`; see `docs/CLIENT_PROGRAMMER_USER_STORIES.md`.

---

## Suggested milestone grouping


| Milestone              | Epics | Outcome                                   |
| ---------------------- | ----- | ----------------------------------------- |
| **M1 — Foundation**    | 1–2   | Repo, CI, DB models                       |
| **M2 — Product shell** | 3–4   | Auth + camera management                  |
| **M3 — Pipeline**      | 5–6   | Chunks, IPFS, chain anchor, DB provenance |
| **M4 — User value**    | 7–8   | Dashboard + verification                  |
| **M5 — Hardening**     | 9     | Tests and integration                     |
| **M6 — Academic**      | 10    | Book chapters and diagrams                |
| **M7 — CP requirements** | 11  | Client/programmer audit + gap delivery  |


---

## Dependency notes (for planning)

- Epics **7–8** depend on **6** (CIDs and tx hashes in DB + deployed contract).
- Epic **6** depends on **5** (stable chunks) and **2** (VideoRecord storage).
- Epic **4** depends on **3** (authenticated user context).
- **Integration testing (Epic 9)** should follow a minimal vertical slice through **5–6**.
- **Epic 11** depends on the story text in `docs/CLIENT_PROGRAMMER_USER_STORIES.md`; implement slices **A → E** in order unless a dependency forces a later slice first (e.g. Slice E needs D).

This file should stay aligned with `AGENTS.md` and the repository README as the implementation evolves.
