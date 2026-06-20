# InvoiceCity — Department routing

One front door for municipal invoicing: vendors route to the right department on submit; cities and vendors each get organized queues across many relationships.

## Start

```bash
cd invoicecity-demo
source .venv/bin/activate
pip install -r requirements.txt   # if needed
python seed_demo.py
python app.py
```

http://127.0.0.1:5001

| Login | Email | Password |
|-------|-------|----------|
| City desk | `ap@demo.city` | `demo123` |
| Vendor | `vendor@contractor.com` | `demo123` |

## Departments (demo)

Finance-AP · Transit · Fire · Public Works · Police · Parks and Rec

## Flow

1. **Vendor** → Submit → pick **Transit** (or Fire, Finance, etc.)
2. System logs **Routed to Transit**
3. **City desk** → Incoming → filter **Transit** tab → process

## Pitch

> Stop emailing everything to AP. Vendors send to the right department the first time. The city sees one organized queue per department.

## Deploy live (Render — free)

1. Push this repo to GitHub (see below).
2. Open [Deploy to Render](https://render.com/deploy?repo=https://github.com/davidgo24/invoicecity-demo) and connect your GitHub account.
3. Click **Deploy**. First boot seeds demo data automatically (~1 min).
4. Share the URL Render gives you (e.g. `https://invoicecity-demo.onrender.com`).

Demo logins work on the live site — same emails/passwords as above.

## Deploy on Railway (recommended if you have an account)

### Option A — GitHub (easiest)

1. Push this repo to GitHub (already at `davidgo24/invoicecity-demo`).
2. [Railway dashboard](https://railway.com/new) → **Deploy from GitHub repo** → select `invoicecity-demo`.
3. **Variables** tab → add:
   - `SECRET_KEY` — any long random string
   - `DATA_DIR` — `/data` (after step 4)
4. Service → **Volumes** → **Add volume** → mount path `/data`  
   (Premium: keeps SQLite + uploaded PDFs across redeploys.)
5. **Settings** → **Generate domain** → share that URL.

First deploy auto-seeds demo data. Cold start ~30s.

### Option B — CLI

```bash
cd invoicecity-demo
railway login
railway init          # new project, link this folder
railway volume add --mount-path /data
railway variables set SECRET_KEY=your-random-secret DATA_DIR=/data
railway up
railway domain        # generate public URL
```

Demo logins are the same on Railway.
