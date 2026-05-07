# Datachain — Roadmap

This roadmap translates the Datachain vision (hybrid Web2/Web3 CCTV integrity platform) into **epics**, **tasks**, and **user stories**. Order within an epic can be parallelized where dependencies allow; **Epic 1** is the foundation for everything else.

---

## Epic 1: Environment & DevOps Setup

**Goal**: Runnable monorepo with consistent tooling and CI.

Keep the **Status** column in this table aligned with the repository as work lands (see **Documentation updates** in `AGENTS.md`).


| Type | Item                                                               | Status                                                                                                                |
| ---- | ------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| Task | Initialize monorepo structure (`frontend`, `backend`, `contracts`) | Done — all three packages scaffolded; `contracts/` uses **Hardhat 3** (TypeScript, Viem, `node:test`); see `contracts/README.md` |
| Task | Next.js boilerplate with Tailwind CSS and routing                  | Done — `frontend/` App Router, Tailwind, `/` and `/project-status`; see `frontend/README.md`                          |
| Task | Python FastAPI boilerplate and virtual environment                 | Done — `backend/` (`GET /health`), `requirements.txt`, venv docs in `backend/README.md`                               |
| Task | PostgreSQL via Docker Compose                                      | Done — root `docker-compose.yml`, documented in `README.md`                                                           |
| Task | Hardhat environment for Solidity smart contracts                   | Done — **Hardhat 3** (`@nomicfoundation/hardhat-toolbox-viem`); `npm run compile` / `npm test` in `contracts/`        |
| Task | ESLint and Prettier (frontend)                                     | Done — `frontend/eslint.config.mjs`, Prettier config; scripts in `frontend/README.md`                                 |
| Task | Black and Flake8 (backend)                                         | Done — `backend/pyproject.toml`, `backend/.flake8`, documented in `backend/README.md`                                 |
| Task | GitHub Actions workflow for automated testing and linting          | Done — `.github/workflows/ci.yml` (frontend lint/format/build, backend Black/Flake8, contracts compile/test) on `main` PRs and pushes |


**Exit criteria**: Local dev can start DB, run API and frontend, compile contracts, and CI passes lint on sample workflow.

**Progress note**: Epic 1 **exit criteria met** for the current scaffold: **GitHub Actions** runs on pushes to **`main`** and **pull requests** targeting **`main`** (see `.github/workflows/ci.yml`). Dependency audits: see `contracts/README.md`.

---

## Epic 2: Database Schema & Models

**Goal**: Persistent relational model for users, cameras, and video records with migrations.


| Type | Item                                                                           | Status |
| ---- | ------------------------------------------------------------------------------ | ------ |
| Task | User schema (SQLAlchemy)                                                       | Done — `backend/app/models.py` (`users`) |
| Task | Camera schema (linked to User)                                                 | Done — `backend/app/models.py` (`cameras.user_id` FK → `users.id`) |
| Task | VideoRecord schema (IPFS CID, blockchain TxHash, timestamps, camera reference) | Done — `backend/app/models.py` (`video_records.camera_id` FK, `cid`, `tx_hash`, timestamps) |
| Task | Alembic configuration and migration workflow                                   | Done — `backend/alembic.ini`, `backend/alembic/env.py`, initial migration in `backend/alembic/versions/` |


**Exit criteria**: Migrations apply cleanly; models reflect relationships needed for CRUD and the video pipeline.

---

## Epic 3: Authentication & Authorization

**Goal**: Secure account lifecycle and API access with JWT.


| Story  | Description                                                              |
| ------ | ------------------------------------------------------------------------ |
| US-3.1 | As a user, I want to register with email and password.                   |
| US-3.2 | As the backend, I need to hash passwords with bcrypt before saving.      |
| US-3.3 | As a user, I want to log in and receive a secure JWT.                    |
| US-3.4 | As a user, I want UI error toasts for wrong password or duplicate email. |
| US-3.5 | As the system, I need JWT expiration handling and automatic logout.      |
| US-3.6 | As a user, I want to log out securely and clear session state.           |


**Exit criteria**: Registration, login, logout, and protected routes behave per stories; secrets not logged.

---

## Epic 4: Camera Management (CRUD)

**Goal**: Users manage IP cameras tied to their account with scalable listing.


| Story  | Description                                                            |
| ------ | ---------------------------------------------------------------------- |
| US-4.1 | As a user, I want a form to add a camera (Name, IP/URL, Location).     |
| US-4.2 | As an API, I need to validate and persist camera data to PostgreSQL.   |
| US-4.3 | As a user, I want a dashboard grid of all my cameras.                  |
| US-4.4 | As a user, I want to edit an existing camera.                          |
| US-4.5 | As a user, I want to delete a camera and remove it from the dashboard. |
| US-4.6 | As a user, I want an Online/Offline status indicator per camera.       |
| US-4.7 | As a user, I want pagination when I have more than 10 cameras.         |


**Exit criteria**: Full CRUD via API + UI; pagination and status indicators implemented per agreed rules (e.g., ping vs last-seen).

---

## Epic 5: Video Processing Pipeline

**Goal**: Reliable local/simulated ingest, chunking, temp storage, and cleanup.


| Type  | Item                                                                           |
| ----- | ------------------------------------------------------------------------------ |
| Task  | Python script to read a local `.mp4` and simulate a continuous CCTV-style feed |
| Story | Backend uses FFmpeg to chunk the stream into **1-minute** `.mp4` segments      |
| Story | Backend writes chunks to a local `temp/` directory                             |
| Task  | Background worker cleans `temp/` after successful processing                   |
| Story | System restarts FFmpeg gracefully if the simulated feed crashes                |


**Exit criteria**: Deterministic chunk duration; disk does not grow unbounded; recovery from process failure documented or automated.

---

## Epic 6: Web3 & Decentralized Storage

**Goal**: Pin IPFS CIDs and anchor metadata on Polygon Amoy; persist full provenance in PostgreSQL.


| Type  | Item                                                                                            |
| ----- | ----------------------------------------------------------------------------------------------- |
| Task  | Integrate Pinata IPFS SDK in FastAPI                                                            |
| Story | Backend uploads each 1-minute chunk to IPFS and retrieves the CID                               |
| Story | Backend implements retry logic for IPFS upload timeouts/failures                                |
| Task  | Implement `Datachain.sol` (mapping camera/video metadata to anchored hashes)                    |
| Task  | Hardhat deployment script; deploy to **Polygon Amoy** testnet                                   |
| Story | Backend uses Web3.py to submit transactions anchoring the CID to the contract                   |
| Story | Backend handles Web3 RPC timeouts and gas failures gracefully                                   |
| Story | Backend saves Web2 metadata (CameraID, Timestamp) and Web3 metadata (CID, TxHash) to PostgreSQL |


**Exit criteria**: End-to-end path from chunk file → CID → tx → DB row; contract address and ABI versioned for frontend verification.

---

## Epic 7: Video Dashboard & Retrieval

**Goal**: Drive-like browsing, filtering, and IPFS playback.


| Story  | Description                                                            |
| ------ | ---------------------------------------------------------------------- |
| US-7.1 | As a user, I want a “My Videos” page with a Google Drive–style layout. |
| US-7.2 | As a user, I want to filter videos by **date range**.                  |
| US-7.3 | As a user, I want to filter videos by **camera name**.                 |
| US-7.4 | As a user, I want **pagination** so large libraries stay performant.   |
| US-7.5 | As a user, I want **loading skeletons** while data loads.              |
| US-7.6 | As a user, I want to open a **video player modal** from a card.        |
| US-7.7 | As a user, I want playback streaming from an **IPFS gateway** via CID. |


**Exit criteria**: Filters compose sensibly with pagination; player uses gateway URL pattern documented in env config.

---

## Epic 8: Cryptographic Verification (Core Feature)

**Goal**: Explicit integrity UX: on-chain truth vs retrieved CID.


| Story  | Description                                                                                     |
| ------ | ----------------------------------------------------------------------------------------------- |
| US-8.1 | As a user, I want a **Verify Integrity** control per video.                                     |
| US-8.2 | As the frontend, I need **ethers.js** to query the smart contract on verify.                    |
| US-8.3 | As a user, I want a **green / 100% Verified** badge when chain CID matches DB/current file CID. |
| US-8.4 | As a user, I want a **red / Tampered** badge when CIDs diverge.                                 |
| US-8.5 | As a user, I want to click **TxHash** and open **Polygonscan** for the proof.                   |


**Exit criteria**: Verification path documented (RPC provider, contract ABI, network ID); mismatches explained in UI without leaking secrets.

---

## Epic 9: Testing & Quality Assurance

**Goal**: Automated confidence in contracts, API, and cross-layer pipeline.


| Type | Item                                                                  |
| ---- | --------------------------------------------------------------------- |
| Task | Unit tests (Chai/Mocha) for Solidity: metadata storage correctness    |
| Task | PyTest: registration and login API                                    |
| Task | PyTest: Camera CRUD API                                               |
| Task | Integration script/test: **IPFS upload → blockchain write → DB save** |


**Exit criteria**: CI runs unit suites; integration test runnable locally with documented env (test keys, testnet faucet).

---

## Epic 10: Academic Deliverables (Project Book)

**Goal**: Written and diagrammatic artifacts for coursework submission.


| Type | Item                                                                                    |
| ---- | --------------------------------------------------------------------------------------- |
| Task | Literature review: traditional IoT vulnerabilities vs. blockchain immutability          |
| Task | Methodology & architecture: hybrid Web2/Web3 data flow                                  |
| Task | UML use case diagrams (user and system personas)                                        |
| Task | UML class diagrams (PostgreSQL models and contract structs)                             |
| Task | UML sequence diagram: cryptographic verification flow                                   |
| Task | Risk management document (e.g., private key loss, RPC failure, operational mitigations) |


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


---

## Dependency notes (for planning)

- Epics **7–8** depend on **6** (CIDs and tx hashes in DB + deployed contract).
- Epic **6** depends on **5** (stable chunks) and **2** (VideoRecord storage).
- Epic **4** depends on **3** (authenticated user context).
- **Integration testing (Epic 9)** should follow a minimal vertical slice through **5–6**.

This file should stay aligned with `AGENTS.md` and the repository README as the implementation evolves.