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
