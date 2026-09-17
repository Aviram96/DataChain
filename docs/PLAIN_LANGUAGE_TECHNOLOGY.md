# Plain-language technology guide (project book)

Readable explanations of what we use and why—suitable for non-specialists and for reuse in a project book or report. Maintainers and agents should extend **this document** when new technologies land (see **Plain-language technology notes** under **Documentation updates** in `**AGENTS.md`**).

### Git and GitHub

**What it is:** **Git** is a tool that records every saved version of your project over time, so you can see what changed, compare versions, and go back if something breaks. **GitHub** is a website (and service) that stores a copy of that history online and helps a team share work, review changes, and run automated checks later (for example continuous integration).

**Why Datachain uses it:** The system handles evidence-related data and a hybrid Web2/Web3 stack; we need an **audit trail of code changes**, safe collaboration, and a single place where the official version of the project lives.

**Where it shows up:** The whole repository; remote history on GitHub; branch workflow described implicitly by how you merge work. **Continuous integration** jobs live under `.github/workflows/` (for example `ci.yml` runs lint and tests on `main` and related pull requests).

### Markdown documentation (`README.md`, `ROADMAP.md`, `AGENTS.md`)

**What it is:** **Markdown** is a simple text format for writing structured documents (headings, lists, tables) that is easy to read as plain text and easy to publish on sites like GitHub.

**Why Datachain uses it:** Everyone—developers, reviewers, and course markers—needs a **single, honest description** of goals (`ROADMAP.md`), how to work on the repo (`AGENTS.md`), and how to run the project locally (`README.md`).

**Where it shows up:** Repository root files; agents keep `ROADMAP.md` status aligned with reality as work progresses.

### Monorepo (one repository, multiple packages)

**What it is:** Instead of many separate codebases, a **monorepo** keeps related parts of one product—here **frontend**, **backend**, and **smart contracts**—in **one Git repository** with clear folders.

**Why Datachain uses it:** The video dashboard, API, and on-chain anchoring are **one product**. One repo reduces version skew (for example API and UI expecting different things), simplifies issue tracking, and matches how small teams ship hybrid Web2/Web3 systems.

**Where it shows up:** Folders `frontend/`, `backend/`, `contracts/` at the repo root.

### Docker and Docker Compose

**What it is:** **Docker** packages an application and its dependencies so it runs the same way on different computers. **Docker Compose** is a small **declaration file** (our `docker-compose.yml`) that says “start these services with these settings”—for example one command brings up a database.

**Why Datachain uses it:** PostgreSQL is required for metadata and future user/camera/video tables. Compose gives every developer the **same database** locally without manual installation steps, which cuts “works on my machine” problems.

**Where it shows up:** `docker-compose.yml` at the repo root; documented in `README.md`.

### PostgreSQL

**What it is:** **PostgreSQL** is a **relational database**: data is stored in tables with relationships (for example “this camera belongs to this user”). It is widely used when you need **reliable, queryable storage** with strong consistency.

**Why Datachain uses it:** Video **files** stay off-chain (IPFS), but the system still needs fast lists, filters, and joins—for users, cameras, CIDs, and transaction hashes. PostgreSQL is the **Web2 index** that makes the product usable day to day; the blockchain provides tamper-evidence, not spreadsheet-speed browsing.

**Where it shows up:** Defined for local dev via Docker Compose; future application schema will live in `backend/` (Epic 2 onward).

### Python

**What it is:** **Python** is a programming language known for clear syntax and a large ecosystem for **web services**, scripting, and integration with multimedia tools.

**Why Datachain uses it:** The **ingest and API layer** (FastAPI), future **FFmpeg** chunking, **IPFS** uploads, and **Web3** calls fit naturally in Python for a single backend service.

**Where it shows up:** `backend/` application code and tooling configuration.

### Virtual environments (`venv`)

**What it is:** A **virtual environment** is an **isolated folder** of Python packages for this project only, so different projects on the same laptop never fight over library versions.

**Why Datachain uses it:** Reproducible installs (“everyone runs the same FastAPI version”) and fewer mysterious errors when coursework deadlines approach.

**Where it shows up:** Documented in `backend/README.md` (create `backend/.venv`, activate, then install requirements).

### pip, `requirements.txt`, and `requirements-dev.txt`

**What it is:** **pip** is Python’s standard **package installer**. `**requirements.txt`** lists the libraries the **running app** needs; `**requirements-dev.txt`** adds **developer tools** (here: code formatters and linters) on top of the same base list.

**Why Datachain uses it:** Simple, transparent dependency listing that fits coursework and small teams; easy to review in Git diffs.

**Where it shows up:** `backend/requirements.txt`, `backend/requirements-dev.txt`.

### FastAPI

**What it is:** **FastAPI** is a Python framework for building **HTTP APIs** (URLs that return **JSON** for programs and browsers to consume). It emphasizes clear structure and automatic **interactive API docs** in the browser during development.

**Why Datachain uses it:** We need a **production-style API** for auth, cameras, video metadata, and pipeline control; FastAPI matches the stack described in the roadmap and pairs well with **async** operations for I/O-bound work (uploads, RPC calls) later.

**Where it shows up:** `backend/app/main.py` defines the app and auth routes; **CORS** middleware allows the Next.js dev server to call the API from the browser (see `CORS_ORIGINS` in `backend/.env.example`).

### bcrypt (password hashing)

**What it is:** **bcrypt** is a **password-hashing** algorithm: the system stores a **non-reversible** fingerprint of a password instead of the password itself. Checking a login means hashing the typed password the same way and comparing fingerprints.

**Why Datachain uses it:** Accounts protect cameras and evidence metadata; if the database were copied, **bcrypt** makes recovering original passwords much harder than storing plaintext or a simple hash.

**Where it shows up:** `backend/requirements.txt`; `backend/app/security/password.py` (`hash_password` before saving, `verify_password` for login checks); `backend/app/routers/auth.py` (registration and login). Optional **`BCRYPT_ROUNDS`** (4–31, default 12) in `backend/.env.example` tunes CPU cost versus brute-force resistance.

### JSON Web Tokens (JWT) and PyJWT

**What it is:** A **JSON Web Token (JWT)** is a compact, signed string the server gives the client after login. The client sends it on later requests (often in an **`Authorization: Bearer …`** header). The server **verifies the signature** and reads fields such as **who the user is** and **when the token expires**, without storing every session row for each tab.

**Why Datachain uses it:** **Stateless API authentication** fits the FastAPI service: each request proves identity for dashboards and future camera APIs. Tokens must stay off logs and be handled carefully on the client (expiry and logout are covered in later stories).

**Where it shows up:** `backend/requirements.txt` (**PyJWT**); `backend/app/security/jwt_tokens.py`; `backend/app/deps_auth.py` (`get_current_user`); `backend/app/routers/auth.py` (`/auth/login`, `/auth/me`); **`JWT_SECRET_KEY`** and optional lifetime in `backend/.env.example` and `backend/app/config.py`.

### email-validator (with Pydantic `EmailStr`)

**What it is:** **email-validator** is a small library that checks whether a string looks like a **valid email address** (format and basic rules). **Pydantic** (bundled with FastAPI) can use it for the `EmailStr` type on request bodies.

**Why Datachain uses it:** Registration rejects malformed emails **before** hitting the database, which keeps data cleaner and avoids silent bad rows.

**Where it shows up:** `backend/requirements.txt`; `backend/app/schemas/auth.py` (`UserRegister.email`).

### Uvicorn

**What it is:** **Uvicorn** is an **application server** that listens for network requests and runs the FastAPI application. Think of FastAPI as the **recipe** and Uvicorn as the **kitchen** that serves requests.

**Why Datachain uses it:** Standard, lightweight way to run FastAPI locally and in deployment; supports modern concurrent request handling.

**Where it shows up:** Started via the command in `backend/README.md` (`uvicorn app.main:app …`).

### Black

**What it is:** **Black** is an automatic **code formatter** for Python: it rewrites layout (indentation, line breaks) so all contributors’ code looks the same.

**Why Datachain uses it:** Saves debate about style and makes reviews focus on **behavior and security**, not spacing.

**Where it shows up:** Configured in `backend/pyproject.toml`; run from `backend/` per `backend/README.md`.

### Flake8

**What it is:** **Flake8** is a **linter**: it analyzes Python source for many common mistakes and style problems **without** running the program.

**Why Datachain uses it:** Catches issues early (unused imports, undefined names) in a project that will grow in surface area (auth, uploads, chain interactions).

**Where it shows up:** `backend/.flake8` and `backend/README.md`.

### Pytest

**What it is:** **Pytest** is a **test runner** for Python: you write small functions that **assert** expected behavior, and Pytest runs them and reports failures.

**Why Datachain uses it:** Auth, cameras, and pipeline code need **repeatable checks** (for example password hashing and API contracts) so regressions are caught locally and in CI.

**Where it shows up:** `backend/requirements-dev.txt`; tests under `backend/tests/`; `pytest -q` from `backend/` per `backend/README.md`; GitHub Actions backend job runs Pytest after Flake8.

### Cursor project rules (`.cursor/rules`)

**What it is:** **Cursor** is an AI-assisted code editor. **Project rules** are short instructions stored in the repo so the assistant follows this project’s **AGENTS.md** habits (roadmap updates, Git policy, attribution).

**Why Datachain uses it:** Keeps automated help aligned with **your** standards—not generic advice—especially for a graded or team project.

**Where it shows up:** `.cursor/rules/agents.mdc`; optional to cite in a project book as “team tooling,” not part of the runtime architecture.

### Next.js

**What it is:** **Next.js** is a **React**-based framework for building **web applications**. It handles **routing** (URLs and pages), **server and client components**, and **production builds** so you get a fast dashboard without wiring everything from scratch.

**Why Datachain uses it:** The product needs a **dashboard** (cameras, videos, verification UI). Next.js matches the roadmap and pairs well with **TypeScript** and **Tailwind** for a maintainable frontend.

**Where it shows up:** `frontend/` (App Router under `frontend/app/`).

### TypeScript

**What it is:** **TypeScript** is **JavaScript** with **static types**: the editor and compiler catch many mistakes (wrong property names, missing fields) before runtime.

**Why Datachain uses it:** As the UI grows, types reduce bugs in API shapes, props, and on-chain verification glue (**ethers.js** later).

**Where it shows up:** `frontend/**/*.tsx`, `frontend/tsconfig.json`; Hardhat config and tests under `contracts/` (`hardhat.config.ts`, `test/`).

### Tailwind CSS

**What it is:** **Tailwind CSS** is a **utility-first** styling system: you compose small classes (for example spacing, colors) in markup instead of writing large custom CSS files for every screen.

**Why Datachain uses it:** Fast, consistent UI for dashboards and forms; fits the **Next.js** stack in the roadmap.

**Where it shows up:** `frontend/app/globals.css`, `frontend/tailwind.config.ts`, class names in components.

### ESLint

**What it is:** **ESLint** checks **JavaScript/TypeScript** source for common mistakes and style rules (for example unused variables, risky patterns).

**Why Datachain uses it:** Keeps the React/Next codebase consistent and safer as features accumulate.

**Where it shows up:** `frontend/eslint.config.mjs`; run via `npm run lint` in `frontend/` (see `frontend/README.md`).

### Prettier

**What it is:** **Prettier** is an **opinionated formatter**: it rewrites layout (line breaks, quotes) so formatting is consistent across the team.

**Why Datachain uses it:** Less time debating style; diffs stay focused on behavior.

**Where it shows up:** `frontend/.prettierrc`, `npm run format` / `format:check` in `frontend/README.md`.

### Hardhat 3 (Hardhat Runner)

**What it is:** **Hardhat** is a **development environment** for Ethereum-style smart contracts: it runs a local simulation for tests, compiles **Solidity**, and loads plugins for verification, deployment (**Hardhat Ignition**), and network helpers. This repository uses **Hardhat 3** with the recommended **Viem**-based toolbox.

**Why Datachain uses it:** We need a **standard, repeatable** way to compile `Datachain.sol`, run automated tests, and deploy to **Polygon Amoy** (`scripts/deploy.ts`) without hand-wiring compilers.

**Where it shows up:** `contracts/package.json`, `contracts/hardhat.config.ts`, `contracts/scripts/deploy.ts`, `contracts/test/`; maintainer notes in `contracts/README.md`.

### Viem (in `contracts/` tests and scripts)

**What it is:** **Viem** is a **TypeScript library** for talking to Ethereum-compatible networks: reading state, sending transactions, and working with contract ABIs in a type-safe way.

**Why Datachain uses it:** Hardhat 3’s default toolbox uses Viem (instead of **ethers.js**) for **compile-time** test and script code in `contracts/`. The **Next.js** app can still use **ethers.js** later for wallet and browser verification, as in `ROADMAP.md`—the two libraries serve different layers of the stack.

**Where it shows up:** `contracts/` (via `@nomicfoundation/hardhat-toolbox-viem`); not required in `frontend/` unless you choose to adopt it there.

### Solidity

**What it is:** **Solidity** is a programming language for **smart contracts** that run on blockchains compatible with the Ethereum Virtual Machine (EVM), such as **Polygon**.

**Why Datachain uses it:** On-chain storage is for **anchors and metadata pointers** (for example CIDs), not raw video; Solidity expresses those rules and lets anyone verify what was committed on-chain.

**Where it shows up:** `contracts/contracts/Datachain.sol` — stores each minute’s **CID**, **segment hash**, and **start/end times**, keyed by camera id and start time. Tests in `contracts/test/Datachain.ts`. Deploy path: `contracts/scripts/deploy.ts` (Polygon Amoy). Backend wiring is a later slice.

### Polygon Amoy (testnet)

**What it is:** **Polygon** is an Ethereum-compatible blockchain that is cheaper to use than Ethereum mainnet. **Amoy** is Polygon’s current **test network** (chain id 80002): fake POL, no real money, used to try contracts before any mainnet deploy.

**Why Datachain uses it:** Anchoring a CID on-chain should be practiced on a testnet first. Amoy is what the roadmap names for this project; mainnet is out of scope unless explicitly approved.

**Where it shows up:** `contracts/hardhat.config.ts` network `polygonAmoy`; `npm run deploy:amoy`. A live Amoy address exists only after someone runs that command with a funded testnet key.

### npm audit (contracts)

**What it is:** `**npm audit`** reports known security issues in the JavaScript dependency tree; `**npm audit fix**` applies compatible version bumps without breaking semver ranges.

**Why Datachain mentions it:** The **Hardhat** stack pulls in **transitive** dependencies; some advisory fixes may only appear with `**npm audit fix --force`**, which can jump major versions. Prefer `**npm audit fix**` without `--force` first; review remaining items and upgrade deliberately.

**Where it shows up:** Run from `contracts/`; see `contracts/README.md`.

### FFmpeg

**What it is:** **FFmpeg** is a widely used **command-line toolkit** for working with video and audio. It can read files, change format, split streams into timed segments, and stream output to files or pipes.

**Why Datachain uses it:** CCTV ingest needs **fixed-duration chunks** (about one minute) for IPFS uploads and chain anchors. FFmpeg is the standard way to turn a continuous feed (real RTSP or a **looped sample MP4**) into those segments without storing one giant file in the API process.

**Where it shows up:** Epic 5 starts with `backend/scripts/simulate_cctv_feed.py` and `backend/app/services/cctv_feed_simulator.py` (loop a local `.mp4` at real-time pace to stdout). **Slice C / CP-C.P2–P8** receive each registered camera URL via `backend/scripts/ingest_camera.py` and write **1-minute** `.mp4` files under `backend/temp/<camera-id>/` using `backend/app/services/video_chunker.py`. Closed segments are checked with **ffprobe** (a companion tool in the FFmpeg install) plus a SHA-256 fingerprint in `backend/app/services/segment_integrity.py` before later stages, and stay staged in `temp/` until processing succeeds (`backend/app/services/segment_staging.py`). If FFmpeg stops unexpectedly, `backend/app/services/ffmpeg_supervisor.py` restarts it (capped for camera ingest) and ingest can mark the camera offline. **`backend/scripts/chunk_cctv_feed.py`** can still chunk a local file the same way. Install FFmpeg on the host; see `backend/README.md`.

### SHA-256 (segment fingerprint)

**What it is:** **SHA-256** is a **cryptographic hash**: a short fingerprint of a file’s bytes. Changing even one bit produces a different fingerprint.

**Why Datachain uses it:** Before a one-minute clip is uploaded or anchored, the pipeline records a SHA-256 so later stages (and verification) can tell if that file was altered.

**Where it shows up:** `backend/app/services/segment_integrity.py` (Slice C / CP-C.P5). Storing that hash in PostgreSQL and on-chain is Slice D.

### Simulated CCTV feed (development)

**What it is:** For local development, a **simulated feed** replays one **`.mp4` file in a loop** at real-time speed instead of connecting to a physical camera or RTSP URL. That lets you test the pipeline without hardware.

**Why Datachain uses it:** Slice C needs a **repeatable** input before live camera ingest. Looping a sample clip exercises FFmpeg, chunking, and later upload/anchor steps the same way every run.

**Where it shows up:** `CCTV_SOURCE_MP4` in `backend/.env.example`; CLI `python scripts/simulate_cctv_feed.py` from `backend/`.

### Temp chunk cleanup worker

**What it is:** A **background worker** watches the **`temp/`** folder for new video chunk files. When processing succeeds (upload and database write in production), it **deletes that file** so old segments do not fill the disk.

**Why Datachain uses it:** Chunks are **temporary staging** until IPFS and the chain record exist. Automatic cleanup keeps laptops and servers healthy during long-running CCTV ingest. Camera ingest (Slice C) keeps staged files in `temp/` until processing succeeds, then deletes them; failed files stay for retry. The Epic 5 file-chunk path still deletes on stub success.

**Where it shows up:** `backend/app/services/chunk_processing_worker.py`, `backend/app/services/temp_chunk_cleanup.py` (`delete_after_successful_processing`), `backend/app/services/segment_staging.py` (ingest keep-until-success), `--cleanup-after-success` on `chunk_cctv_feed.py`, and `scripts/process_temp_chunks.py`. Slice D Pinata upload is `pinata_ipfs.py` (not yet the ingest processor).

### Pinata (IPFS pinning)

**What it is:** **IPFS** (InterPlanetary File System) stores files by a cryptographic fingerprint called a **CID** (content identifier). **Pinata** is a hosted service that **pins** (keeps available) those files so a laptop or server does not have to run an IPFS node. There is no official Pinata Python SDK; Datachain calls Pinata’s **pinFileToIPFS** HTTP API with a secret **JWT**.

**Why Datachain uses it:** One-minute CCTV clips stay **off-chain**. The CID uniquely identifies the bytes; later the same CID is stored in PostgreSQL and on Polygon so verification can detect a swapped file.

**Where it shows up:** `backend/app/services/pinata_ipfs.py`, `backend/scripts/upload_segment_ipfs.py`, ingest via `ingest_segment_processor.py`, `PINATA_JWT` in `backend/.env.example`. Playback uses a public **IPFS HTTP gateway** (`NEXT_PUBLIC_IPFS_GATEWAY`, default Pinata gateway) on the camera recordings page (`frontend/lib/ipfs-gateway.ts`).

### Web3.py (Polygon anchoring)

**What it is:** **Web3.py** is a Python library for talking to Ethereum-compatible blockchains (send transactions, read contracts). Datachain uses it to call `anchorSegment` and `getSegment` on Polygon **Amoy**.

**Why Datachain uses it:** The backend must record each minute’s CID and hash on-chain. If the RPC times out or gas is too low, the write helper **retries** and **does not treat the segment as proven**; the temp file can stay for another attempt. A separate **read** helper can load the same metadata from the contract **without PostgreSQL**.

**Where it shows up:** `backend/app/services/chain_anchor.py` (`anchor_segment`, `get_segment`), `backend/scripts/anchor_segment.py`, ingest via `ingest_segment_processor.py`, ABI in `backend/app/contracts/datachain_abi.py`. The **user** Verify button uses **ethers.js** in the browser, not this Python helper.

### ethers.js (browser verification)

**What it is:** **ethers.js** is a JavaScript library the web app uses to talk to an Ethereum-compatible chain from the **browser**. Datachain uses it only to **read** `getSegment` on Polygon **Amoy** (no wallet signature, no private key in the frontend).

**Why Datachain uses it:** Integrity is something a user can check themselves: the page loads each minute’s CID and hash from the API, then asks the smart contract for the same fields and compares them. A green **Verified** badge means they match; a red **Tampered** badge means they do not. If the RPC node cannot be reached, the result is **Failed to verify**, not tampered.

**Where it shows up:** `frontend/lib/verify-chain.ts`, `frontend/lib/datachain-abi.ts`, camera recordings Verify UI (`frontend/components/camera-recordings.tsx`). RPC is proxied at `/amoy-rpc` (see `frontend/next.config.ts` and `frontend/.env.example`).

### Development mocks for IPFS and blockchain (later slices)

**What it is:** A **mock** (fake stand-in) lets the backend **pretend** an external service succeeded—returning a made-up **CID** or **transaction hash**—so the rest of the pipeline can be exercised without Pinata or Polygon keys.

**Why Datachain uses it:** Local and college environments can stay secret-free. Unit tests already **mock HTTP** for Pinata; a `MOCK_IPFS` runtime flag is still later.

**Where it shows up:** `backend/tests/test_pinata_ipfs.py`, `backend/tests/test_chain_anchor.py`, mocked pipeline in `backend/tests/test_ingest_ipfs_chain_db.py`. Runtime mocks are **not** in the repo yet.

### Technologies on the roadmap but not fully in the repo yet

The product vision still needs remaining Slice E work (partial-range verify, download, verification audit log). Ingest can use a maintainer-deployed Amoy contract address.