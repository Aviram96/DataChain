# Datachain — Client / Programmer User Stories

Working requirements document derived from the draft `US.docx` (teacher-facing client–programmer format).

Use this file—not the raw Word draft—as the checklist for audit and implementation. Epics **1–10** in `ROADMAP.md` remain historical delivery notes; **Epic 11** tracks progress against this document.

---

## How to use this document

| Role | Meaning |
| ---- | ------- |
| **Client** | What the end user sees or does (product language). |
| **Programmer** | What the system / API / services must do to support it. |

| Status | Meaning |
| ------ | ------- |
| **TBD** | Not yet traced against the codebase. |
| **Implemented** | Behavior matches the story. |
| **Partial** | Scaffold or incomplete behavior. |
| **Missing** | Not built yet. |
| **Deferred** | Intentionally out of current slice (noted why). |

**Workflow:** for each story ID → confirm understanding → set Status → implement gaps only after maintainer approval.

**Open decisions** are listed at the end; do not treat draft notes as committed scope until resolved.

---

## Slice A — Register and Login

### Client stories


| ID | Story | Status |
| -- | ----- | ------ |
| CP-A.C1 | As a visitor, I want an opening page that briefly presents the **project**, the **problem**, and the **solution**, so I understand Datachain before I register or log in. | Implemented — richer landing at `/` (`frontend/components/landing-page.tsx`) |
| CP-A.C1a | As a visitor, I want the opening page **without a top navigation toolbar**, so the first screen focuses on the product story and CTAs. | Implemented — marketing layout has no `SiteHeader` |
| CP-A.C1b | As a visitor, I want to read a short **problem** section (centralized CCTV can be silently altered or deleted), so I understand why integrity matters. | Implemented — Problem section on landing |
| CP-A.C1c | As a visitor, I want to read a short **solution** section (video on IPFS, CIDs anchored on-chain, metadata in the app), so I understand how Datachain works at a high level. | Implemented — Solution section on landing |
| CP-A.C1d | As a visitor, I want **Sign up** and **Log in** buttons **below** that description (not in a top bar on this page), so I can start using the product. | Implemented — CTAs under hero copy (and again under solution) |
| CP-A.C1e | As a signed-in user who opens `/`, I want to be **auto-redirected to `/cameras`**, so I land on the main camera-management page. | Implemented — `router.replace('/cameras')` when session exists |
| CP-A.C1f | Project status link on the landing / site presentation. | Declined — not relevant for site presentation |
| CP-A.C1g | As a visitor on mobile, I want the same content and CTAs to remain readable and usable without a top bar. | Implemented — responsive stacked CTAs and fluid type |
| CP-A.C2 | As a user, I want a Sign up control that takes me to the registration page, so I can create an account. | Implemented — landing CTA + app header + login-page link → `/register` |
| CP-A.C3 | As a user, I want a Log in control that takes me to the login page, so I can access my account. | Implemented — landing CTA + app header + register-page link → `/login` |
| CP-A.C4 | As a user, I want to register with an email and password, so I can access the platform securely. | Implemented — `RegisterForm` + `POST /auth/register` |
| CP-A.C5 | As a user, I want to know the password requirements before submitting, so I can create a strong password. | Implemented — hint from `frontend/lib/password-requirements.ts` (8 chars, max 200, 72 UTF-8 bytes) |
| CP-A.C6 | As a user, I want an error message if my password does not meet the requirements, so I can correct it and register. | Implemented — client toast via `passwordRequirementsError`; server 422 still enforced |
| CP-A.C7 | As a user, I want a confirmation after successful registration and to be taken to the cameras page, so I can start using the system immediately. | Implemented — success toast; auto-login then `router.push("/cameras")` |
| CP-A.C8 | As a user, I want to log in with email and password, so I can access my account easily. | Implemented — `LoginForm` + `POST /auth/login` |
| CP-A.C9 | As a user, I want clear error messages when login fails, so I can fix the problem and try again. | Implemented — error toast on failed login |
| CP-A.C10 | As a user, I want to go to the cameras page after a successful login, so I can manage my cameras. | Implemented — `router.push("/cameras")` after login |
| CP-A.C11 | As a user, I want to stay securely logged in while I use the site, so continuous work stays convenient without exposing my account. | Implemented — JWT in `localStorage` + `AuthProvider` + `authFetch` |
| CP-A.C12 | As a user, I want my login session to expire after a limited time, so my account and camera data stay protected if I forget to log out. | Implemented — JWT `exp` (default 60 min) + client expiry handling |
| CP-A.C13 | As a user, I want a Log out control on the cameras page (and while signed in), so I can leave my session easily. | Implemented — Log out in `SiteHeader` (visible on `/cameras`) |
| CP-A.C14 | As a user, I want logout to clear my session securely, so others cannot use my account afterward. | Implemented — clears token, user state, redirects to `/login` |


### Programmer stories


| ID | Story | Status |
| -- | ----- | ------ |
| CP-A.P1 | As the system, I want passwords hashed with bcrypt (or equivalent) before storage, so a database leak does not expose original passwords. | Implemented — `backend/app/security/password.py` |
| CP-A.P2 | As the system, I want authenticated sessions via JWT with a defined expiry, so access is time-bounded and APIs can authorize requests. | Implemented — `jwt_tokens.py` + `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` |
| CP-A.P3 | As the system, I want the client to detect expired or invalid sessions and redirect to login, so protected actions do not fail silently. | Implemented — `auth-provider.tsx`, `auth-fetch.ts`, `require-auth.tsx` |
| CP-A.P4 | As a developer, I want PyTest coverage for registration and login APIs (success and failure cases), so auth behavior stays correct. | Implemented — `backend/tests/test_auth_api.py` |
| CP-A.P5 | As the frontend, I want the global site header **hidden on `/`** (and shown on app pages such as `/login`, `/register`, `/cameras`), so the landing page can be toolbar-free while the rest of the app stays navigable. | Implemented — `(marketing)` vs `(app)` route groups |
| CP-A.P6 | As the frontend, I want the home route to render a dedicated landing layout (brand, problem, solution, CTA group) without relying on the global header for primary auth entry. | Implemented — `landing-page.tsx` + marketing layout |
| CP-A.P7 | As the frontend, I want landing CTAs to reuse existing routes (`/register`, `/login`, `/cameras`) and auth state, so behavior stays consistent with Slice A. | Implemented — CTAs + signed-in redirect to `/cameras` |


### Slice A notes (from draft)

- Password requirements are defined and shown in the UI (aligned with backend `UserRegister`).
- Post-register and post-login destination: **cameras page** (main app surface for camera management).
- Landing decisions (2026-07-21): no top toolbar on `/`; richer atmosphere/hero; no project-status link; signed-in visitors to `/` auto-redirect to `/cameras`; mobile-usable (C1g).


## Slice B — Camera dashboard management

### Client stories


| ID | Story | Status |
| -- | ----- | ------ |
| CP-B.C1 | As a user, I want to see all my cameras on the Cameras page in a grid, so I can monitor and manage them in one place. | Implemented — `CamerasDashboard` grid |
| CP-B.C2 | As a user, I want a clear empty-state message when I have no cameras, so I know I can start by adding one. | Implemented — empty + “no matches” copy |
| CP-B.C3 | As a user, I want an Add camera control that opens the add-camera form, so I can register a new device. | Implemented — Add camera → `/cameras/new` |
| CP-B.C4 | As a user, I want to add a camera with name, IP address or URL, and location, so I can identify and manage it. | Implemented — `CameraForm` + `POST /cameras` |
| CP-B.C5 | As a user, I want a confirmation after a camera is added successfully. | Implemented — success toast |
| CP-B.C6 | As a user, I want an error message when adding a camera fails, so I know what went wrong. | Implemented — error toast (incl. duplicate name 409) |
| CP-B.C7 | As a user, I want cameras saved to my account, so they remain after logout and login. | Implemented — PostgreSQL owner-scoped rows |
| CP-B.C8 | As a user, I want to see whether each camera is online or offline. | Implemented — status badge (stream probe) |
| CP-B.C9 | As a user, I want to search cameras by name and filter by connection status, so I can find relevant cameras quickly. | Implemented — search + status controls; API `q` / `status` |
| CP-B.C10 | As a user, I want to choose how the camera list is ordered (for example by name or by date added), with a documented default. | Implemented — sort select; default **newest first** (`created_at_desc`) |
| CP-B.C11 | As a user, I want to edit an existing camera’s details, so information stays accurate. | Implemented — `/cameras/[id]/edit` |
| CP-B.C12 | As a user, I want to delete a camera from my dashboard, so unused cameras no longer appear in my active list. | Implemented — soft delete (hidden from list) |
| CP-B.C13 | As a user, I want a confirmation step before delete, so I do not remove a camera by accident. | Implemented — confirm on card + detail page |
| CP-B.C14 | As a user, I want to open a dedicated page for a selected camera, so I can access its recordings and related actions. | Implemented — `/cameras/[id]` (recordings placeholder for Slice E) |
| CP-B.C15 | As a user, I want the camera list paginated when there are many cameras, so browsing stays usable. | Implemented — page size 10 + Previous/Next |


### Programmer stories


| ID | Story | Status |
| -- | ----- | ------ |
| CP-B.P1 | As the backend, I want owner-scoped camera CRUD in PostgreSQL, so each user only manages their own cameras. | Implemented — `backend/app/routers/cameras.py` |
| CP-B.P2 | As the system, I want to reject a second camera with the same name for the same user, so cameras stay uniquely identifiable and searchable by name. | Implemented — case-insensitive check + partial unique index; HTTP 409 |
| CP-B.P3 | As the system, I want delete to **hide** the camera from the dashboard (**soft delete**) without destroying historical video records, so evidence and verification data remain available. | Implemented — `deleted_at`; `video_records` FK `ON DELETE RESTRICT` |
| CP-B.P4 | As the system, I want online/offline status based on whether the camera **stream is reachable**, so the badge reflects real availability. | Implemented — HTTP(S) request / RTSP OPTIONS (see `camera_probe.py`) |
| CP-B.P5 | As the backend, I want to receive / attach to the camera stream for registered cameras, so footage can be processed (see Slice C). | Implemented — `attach_camera_stream` for active cameras; continuous ingest remains Slice C |
| CP-B.P6 | As a developer, I want PyTest coverage for camera CRUD (authz, success, and error cases), so only owners can manage their cameras. | Implemented — `test_cameras_api.py` (+ unique name, soft delete, filters); `test_camera_stream.py` |


### Slice B open decisions

Resolved 2026-07-21:

1. **Default sort:** date added, **newest first** (`created_at_desc`).
2. **Sort UI:** user-selectable (newest/oldest / name A–Z / Z–A).
3. **Soft-delete UX:** camera vanishes from the active dashboard only; no deleted-camera history UI in Slice B. DB row + future video records remain for evidence flows.

---

## Slice C — Video processing pipeline

### Client stories

_(Continuity is mostly invisible; after repeated capture failures the dashboard explains why the camera is offline.)_


| ID | Story | Status |
| -- | ----- | ------ |
| CP-C.C1 | As a user, I want recording to continue reliably when capture fails briefly, and I want the camera marked offline after repeated failures, so I understand when footage may be missing. | Implemented — brief FFmpeg restarts keep recording without flipping the badge; after the restart cap, `offline_reason` is `ingest_failed` (vs `unreachable`); `ingest_offline_at` is returned so the card and detail can say when capture stopped |


### Programmer stories


| ID | Story | Status |
| -- | ----- | ------ |
| CP-C.P1 | As the system, I want to simulate a continuous CCTV stream from a local file, so the pipeline can be developed without live hardware. | Implemented — `backend/scripts/simulate_cctv_feed.py` loops a local `.mp4` via `cctv_feed_simulator.py`; tests in `backend/tests/test_cctv_feed_simulator.py` |
| CP-C.P2 | As the system, I want to receive the video stream from each connected camera, so footage can be processed continuously. | Implemented — `backend/scripts/ingest_camera.py` (`--camera-id` / `--all`) via `camera_ingest.py`; uses `attach_camera_stream`; tests in `backend/tests/test_camera_ingest.py` |
| CP-C.P3 | As the system, I want to split the stream into one-minute `.mp4` segments (FFmpeg), so each segment can be stored and verified independently. | Implemented — `ingest_camera.py` uses FFmpeg segment muxer (`-segment_time 60`) via `video_chunker.py`; writes `temp/<camera-id>/chunk_NNN.mp4` |
| CP-C.P4 | As the system, I want each segment named uniquely from camera ID and recording time, and associated with camera plus start/end timestamps. | Implemented — `{camera_id}_YYYYMMDDTHHMMSSZ.mp4` via FFmpeg `-strftime`; `parse_segment_path` in `segment_identity.py` yields camera + start/end |
| CP-C.P5 | As the system, I want a basic integrity check on each segment before the next stage. | Implemented — `segment_integrity.py` (complete MP4 + SHA-256 + video stream); ingest worker gates next stage; failures stay in `temp/` and are not handed on |
| CP-C.P6 | As the system, I want segments saved under `temp/` until processing succeeds. | Implemented — ingest stages under `temp/<camera-id>/` (`segment_staging.py`); worker `delete_on_success=False` until processing succeeds |
| CP-C.P7 | As the system, I want to delete temp files only after successful processing, and keep files that failed or are awaiting retry. | Implemented — worker deletes only after processor success (`delete_after_successful_processing`); failures stay in `temp/` and processing failures are retried; ingest stub does not count as success |
| CP-C.P8 | As the system, I want to detect unexpected FFmpeg / stream stop, restart with a capped attempt count, mark the camera offline after repeated failures, and log restart attempts. | Implemented — ingest restarts FFmpeg (default cap 10); logs include camera id; `ingest_offline_at` after cap; dashboard `status` offline |


### Slice C notes

- **CP-C.P1** uses the existing local-file simulator as the Slice C hardware-free entry point (not live RTSP). Run from `backend/`: `python scripts/simulate_cctv_feed.py --source path/to/sample.mp4` (or `CCTV_SOURCE_MP4`). See `backend/README.md`.
- **CP-C.P2–P8** attach FFmpeg to each active camera’s `stream_url` and split it into 1-minute `.mp4` files named `{camera_id}_{start}Z.mp4` under `backend/temp/<camera-id>/`. Each closed file is integrity-checked (complete MP4, video stream, SHA-256) before later processing; failures stay in `temp/` and are not handed on. Passing files **remain staged under `temp/` until processing succeeds**. Temp files are **deleted only after processing succeeds**; processing failures stay on disk and are retried. If FFmpeg stops unexpectedly, ingest **restarts** it (default cap 10, logged with camera id) and **marks the camera offline** after the cap (`ingest_offline_at`; apply Alembic `20260824_000003`). IPFS / chain / DB is still a stub, so camera ingest does not delete on staging-only success. Run from `backend/`: `python scripts/ingest_camera.py --camera-id UUID` or `--all`. Parse start/end with `app.services.segment_identity.parse_segment_path`.
- **CP-C.C1** — Brief capture failures restart FFmpeg without changing Online/Offline. After the restart cap, list and detail include `offline_reason`: `ingest_failed` when ingest gave up, `unreachable` when the live stream probe fails, or `null` when online. They also include `ingest_offline_at` (ISO timestamp when ingest gave up, else `null`). The camera card and camera detail keep the Online/Offline badge and, for `ingest_failed`, tell the user capture stopped after repeated failures (**since** that time) and footage for that period may be missing.


---

## Slice D — IPFS storage and blockchain anchoring

### Client stories

_(Users consume results via playback and verification in Slice E; anchoring itself is system work.)_


| ID | Story | Status |
| -- | ----- | ------ |
| CP-D.C1 | As a user, I want each recorded minute to be stored and anchored so I can later prove integrity (experienced via verification UI). | TBD |


### Programmer stories


| ID | Story | Status |
| -- | ----- | ------ |
| CP-D.P1 | As the system, I want each one-minute segment uploaded to IPFS and to receive its CID. | TBD |
| CP-D.P2 | As the system, I want each segment’s CID and recording details anchored on Polygon via a Datachain smart contract keyed by camera (and segment identity). | TBD |
| CP-D.P3 | As the backend, I want Web3.py to submit anchor transactions, with graceful handling of RPC timeouts and gas failures, logging, and retry without losing the segment. | TBD |
| CP-D.P4 | As a developer, I want a Hardhat deployment path for the contract on Polygon Amoy testnet. | TBD |
| CP-D.P5 | As the system, I want segment metadata readable from the smart contract even if the database is unavailable. | TBD |
| CP-D.P6 | As the backend, I want each finalized segment stored in PostgreSQL with camera ID, start time, end time, IPFS CID, segment hash, and transaction hash. | TBD |
| CP-D.P7 | As the system, I want anchoring failures detected so a segment is not treated as fully proven before a successful on-chain proof. | TBD |
| CP-D.P8 | As a developer, I want contract tests that store and return camera ID, CID, segment hash, start time, and end time. | TBD |
| CP-D.P9 | As a developer, I want an integration test for IPFS upload → chain anchor → PostgreSQL save with consistent CID and tx hash. | TBD |


### Slice D notes (from draft)

- Draft contained duplicate upload/DB/contract stories; **P1–P9** are the deduplicated set.
- Optional later: explicit recovery tooling to rebuild DB references from chain/IPFS (see Slice E programmer recovery story).

---

## Slice E — Video management and verification

### Client stories


| ID | Story | Status |
| -- | ----- | ------ |
| CP-E.C1 | As a user, I want a dedicated camera page with details and video-related actions. | TBD |
| CP-E.C2 | As a user, I want a video management area for that camera to search, watch, download, and verify recordings. | TBD |
| CP-E.C3 | As a user, I want to select a date and a start/end time for a camera, so I can find the recordings I care about. | TBD |
| CP-E.C4 | As a user, I want search results presented clearly, so I can choose watch, download, or verify. | TBD |
| CP-E.C5 | As a user, I want to watch the selected recording (time range / segments). | TBD |
| CP-E.C6 | As a user, I want to download the selected recording as a usable local file. | TBD |
| CP-E.C7 | As a user, I want to verify the entire selected recording. | TBD |
| CP-E.C8 | As a user, I want to verify only part of a selected recording (sub-range). | TBD |
| CP-E.C9 | As a user, I want a clear verification result: authentic, modified, missing, or failed to verify. | TBD |
| CP-E.C10 | As a user, I want a green Verified badge when DB metadata, IPFS CID, and blockchain record match. | TBD |
| CP-E.C11 | As a user, I want a red Tampered warning when metadata does not match the blockchain proof. | TBD |
| CP-E.C12 | As a user, I want to open a segment’s transaction hash on Polygonscan from the verification result. | TBD |


### Programmer stories


| ID | Story | Status |
| -- | ----- | ------ |
| CP-E.P1 | As the system, I want camera details and every video operation to validate ownership, so users only access their own cameras and footage. | TBD |
| CP-E.P2 | As the system, I want to search segments by camera ID, date, start time, and end time. | TBD |
| CP-E.P3 | As the system, I want to calculate which one-minute segments are **expected** for a selected range, so gaps can be detected. | TBD |
| CP-E.P4 | As the system, I want to check whether each expected segment is available in storage, distinguishing missing metadata from an unretrievable file. | TBD |
| CP-E.P5 | As the system, I want to compare each segment against stored hash, CID, and blockchain proof (cross-source consistency). | TBD |
| CP-E.P6 | As the system, I want to classify segment results into clear statuses for the UI. | TBD |
| CP-E.P7 | As the system, I want to aggregate segment results into one overall status for the selected range. | TBD |
| CP-E.P8 | As the system, I want to record verification attempts and outcomes for an audit trail. | TBD |
| CP-E.P9 | As the system, I want to map a partial time range to overlapping one-minute segments for partial verify. | TBD |
| CP-E.P10 | As the system, I want to combine selected one-minute segments into one downloadable file for the chosen range. | TBD |
| CP-E.P11 | As the system, I want a path to recover segment references from blockchain/IPFS when the DB is unavailable or corrupted. | TBD |


---

## Story ID index (quick count)

| Slice | Client | Programmer | Focus |
| ----- | ------ | ---------- | ----- |
| A | CP-A.C1–C14 (+ C1a–C1g); P1–P7 | Auth, session, landing |
| B | CP-B.C1–C15 | CP-B.P1–P6 | Cameras |
| C | CP-C.C1 | CP-C.P1–P8 | Ingest & chunking |
| D | CP-D.C1 | CP-D.P1–P9 | IPFS & chain |
| E | CP-E.C1–C12 | CP-E.P1–P11 | Browse, download, verify |

**Total:** 43 client + 38 programmer = **81** tracked stories (deduplicated from the Word draft).

---

## Explicitly out of this document (still in `ROADMAP.md`)

- Epic 1 DevOps / monorepo / CI scaffolding details  
- Epic 10 academic / project-book deliverables  
- Mainnet deployment and legal admissibility claims  

Add here only if the teacher requires them in the client–programmer pack.

---

## Change log

| Date | Change |
| ---- | ------ |
| 2026-07-21 | Initial organized doc from `US.docx`: deduplicated, client/programmer split, slices A–E, open decisions captured, statuses TBD. |
| 2026-07-21 | Slice A marked Implemented: home Sign up/Log in, redirects to `/cameras`, password-requirement UX, `test_auth_api.py`. |
| 2026-07-21 | Slice B marked Implemented: search/filter/sort, soft delete, unique names, camera detail page, stream probe + attach. |
| 2026-07-21 | Landing refinement: CP-A.C1a–C1g / P5–P7 — toolbar-free richer home, auto-redirect signed-in users to `/cameras`. |
| 2026-07-21 | App-wide UI aligned to landing palette (header, auth, cameras, toasts). |
| 2026-08-24 | Slice C started: CP-C.P1 Implemented (local `.mp4` continuous feed simulator). |
| 2026-08-24 | Slice C CP-C.P2 Implemented: FFmpeg receive for registered camera stream URLs. |
| 2026-08-24 | Slice C CP-C.P3 Implemented: 1-minute MP4 segments from each camera stream. |
| 2026-08-24 | Slice C CP-C.P4 Implemented: unique `{camera_id}_{start}Z.mp4` names and start/end parse. |
| 2026-08-24 | Slice C CP-C.P5 Implemented: basic integrity check (complete MP4, SHA-256, video stream) before the next stage. |
| 2026-08-24 | Slice C CP-C.P6 Implemented: camera ingest stages segments under `temp/<camera-id>/` until processing succeeds. |
| 2026-08-24 | Slice C CP-C.P7 Implemented: delete temp files only after processing succeeds; keep failures for retry. |
| 2026-08-24 | Slice C CP-C.P8 Implemented: capped FFmpeg restart on unexpected stop; mark camera offline after the cap. |
| 2026-09-09 | Slice C CP-C.C1 Implemented: `offline_reason` (`ingest_failed` vs `unreachable`); camera card and detail copy when capture stopped after the restart cap. Slice C complete. |
| 2026-09-09 | CP-C.C1 follow-up: API returns `ingest_offline_at`; camera card and detail include **since …** when capture stopped. |
