# Datachain — College server operator guide

Save this file (or copy the text below) for yourself. **Do not put SSH or database passwords in Git.** Use the credentials from the college deployment email / `README_STUDENTS.md` on the server.

---

## 1. What you have

You have **two separate copies** of Datachain:

| Place | Role |
| ----- | ---- |
| **Your laptop** | Where you write code (Docker Postgres, local API, `npm run dev`). |
| **College VM** | Public demo at **http://178.105.250.63** |

They do **not** share users, cameras, or data. An account on the website is only in the college database. An account on your laptop is only in local Docker.

---

## 2. Use the product (no SSH)

In a browser, open:

**http://178.105.250.63**

- Landing page → **Sign up** or **Log in**
- After login you go to **Cameras** (list, add, edit, delete, online/offline)
- API health (optional check): **http://178.105.250.63/api/health**  
  Expected: `{"status":"ok"}`

If the page shows **502 Bad Gateway**, the app processes are down (often after a **reboot**). See section 5.

---

## 3. How the server is wired

```
Internet
    → nginx port 80 (public)
         /        → Next.js on 127.0.0.1:3000
         /api/    → FastAPI on 127.0.0.1:8000

Postgres 127.0.0.1:5432  — only the server itself can connect
SSH      port 22         — you, with the student account
```

Visitors never talk to Postgres. Do not try to open the database from your laptop without an SSH tunnel (and you normally do not need that).

---

## 4. SSH (when you need the machine)

```bash
ssh student@178.105.250.63
```

- Username: `student`
- Password: from the **college guide** (not stored in this repo)

You **cannot** use `sudo`. You **can** write under `/var/www/datachain` and run the app.

### Important paths

| Path | Meaning |
| ---- | ------- |
| `/var/www/datachain` | Deployed project (git clone) |
| `/var/www/datachain/backend` | FastAPI, Python venv, `.env` |
| `/var/www/datachain/frontend` | Next.js (production build) |
| `/var/www/datachain/temp_video` | Temp FFmpeg segments (ingest) |
| `/var/www/datachain/backend/.env` | Secrets — never commit, never paste into Git |
| `/home/student/start-datachain.sh` | Restart API + website |
| `/var/www/datachain/README_STUDENTS.md` | College’s original instructions (includes secrets) |

---

## 5. If the website is down

Processes run in **tmux**. They keep running after you **log out of SSH**. They **stop if the VM reboots**.

SSH in, then:

```bash
bash /home/student/start-datachain.sh
```

Wait a few seconds, then open **http://178.105.250.63** again.

Quick checks on the server:

```bash
curl -s http://127.0.0.1/api/health
tmux ls
```

You want `{"status":"ok"}` and sessions named `datachain-api` and `datachain-web`.

### Logs (do not kill the app)

```bash
tmux attach -t datachain-api
tmux attach -t datachain-web
```

Leave the session **without stopping** the process: press **Ctrl+b**, then **d**.

---

## 6. Programming vs the live demo

| Goal | What to do |
| ---- | ---------- |
| Change code and test | Work on your **laptop** as usual (`docker compose`, backend venv, `frontend` `npm run dev`). |
| See changes on **http://178.105.250.63** | Deploy to the VM: `git pull` on the server, install/migrate/rebuild if needed, run `start-datachain.sh`. The live site does **not** update when you save files on the laptop. |
| Git commits | Only when you choose; you name the commit message. |

Current deploy (Slice 2): branch **`epic11-client-programmer`**, app root **`/var/www/datachain`**.

Typical update (after you have pushed to GitHub):

```bash
ssh student@178.105.250.63
cd /var/www/datachain
git pull
cd backend
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
cd ../frontend
npm install
npm run build
bash /home/student/start-datachain.sh
```

Skip `pip` / `npm` / `alembic` if that update did not change dependencies or the database.

---

## 7. Cameras and recording

Cameras you add **on the college website** are stored in the **college** database.

**Online/Offline** (and any future ingest) is measured **from the college server**, not from your laptop.

- A stream URL that only works on your home Wi‑Fi will show **offline** on the college site.
- When ingest is started, run it **on the VM** (or on a machine that can reach the cameras). Temp files: `/var/www/datachain/temp_video`.

IPFS (Pinata) and Polygon anchoring are **not** enabled on this server yet.

---

## 8. Database (college)

- Host: `127.0.0.1` (on the server only)
- Port: `5432`
- Database: `datachain_db`
- User: `datachain_user`
- Password: from the **college guide**

The backend `.env` uses:

`postgresql+psycopg://…`  

(that `+psycopg` part is required for this project; the college template without it is wrong for our code.)

---

## 9. What not to do

- Do not commit `.env` or passwords.
- Do not expect laptop Docker and the college DB to stay in sync.
- Do not expose Postgres to the internet.
- Do not use the college template commands `uvicorn main:app` or `TEMP_VIDEO_PATH` — this repo uses `uvicorn app.main:app` and `CCTV_TEMP_DIR`.

---

## 10. Short checklist

1. Use the app: **http://178.105.250.63**
2. 502 / after reboot: SSH → `bash /home/student/start-datachain.sh`
3. Code on the laptop; deploy to the VM only when you want the public URL updated
4. Camera URLs must be reachable **from the college server**
