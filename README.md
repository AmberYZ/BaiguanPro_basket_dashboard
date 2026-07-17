# Baiguan Pro Index

Internal dashboard for tracking Baiguan Pro investment baskets — thesis, constituents,
performance vs benchmarks, valuations, and the team's custom charts, all in one place.

**Team members only need a browser.** Propose baskets, approve them, edit constituents,
and refresh data from the web UI. No YAML or local install required for daily use.

## Share with the team (free path)

Recommended for 3–4 internal users: **Streamlit Community Cloud + GitHub**.

| Piece | Who owns it | What it does |
|---|---|---|
| Streamlit Cloud app | You deploy once | Shared URL + password gate |
| GitHub repo | Source of truth | `baskets/`, `custom_charts/`, and `data/` cache |
| GitHub Actions | Runs every Beijing midnight | Pulls market data, commits `data/` |
| `GITHUB_TOKEN` in Streamlit secrets | Web edits | Saves basket/chart changes back to GitHub |

### One-time setup (you)

1. Repo is already on GitHub: https://github.com/AmberYZ/BaiguanPro_basket_dashboard
2. **GitHub → Settings → Secrets and variables → Actions**  
   Add repository secrets:
   - `EODHD_API_KEY`
   - `TUSHARE_TOKEN`
3. **Actions** tab → *Update market data* → **Run workflow** once (first fill of `data/`).
4. Go to [share.streamlit.io](https://share.streamlit.io) → **New app**  
   - Repository: `AmberYZ/BaiguanPro_basket_dashboard`  
   - Branch: `main`  
   - Main file: `app.py`
5. In the app → **Settings → Secrets**, paste (see `.streamlit/secrets.toml.example`):

```toml
APP_PASSWORD = "your-team-password"
EODHD_API_KEY = "..."
TUSHARE_TOKEN = "..."
GITHUB_TOKEN = "ghp_..."   # PAT with repo write + Actions write
GITHUB_REPO = "AmberYZ/BaiguanPro_basket_dashboard"
GITHUB_BRANCH = "main"
```

6. Send teammates the Streamlit URL + the team password.

### How teammates use it (browser only)

1. Open the URL → enter the team password.
2. **Propose a Basket** — search stocks, click ＋ Add, submit.
3. **Basket Detail** — review, **Approve and activate**, edit thesis / constituents / tags.
4. New names get market data from the background refresh (or click **Data & Update → Update all data now**).
5. Overnight, GitHub Actions refreshes all prices/valuations at **Beijing 00:00**.

Password: set `APP_PASSWORD` in Streamlit secrets. Opening the URL shows a password box before the dashboard.

## Local quick start (developers)

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt

export TUSHARE_TOKEN=...
export EODHD_API_KEY=...
export APP_PASSWORD=...      # optional

.venv/bin/python update_data.py
.venv/bin/streamlit run app.py
```

Without `GITHUB_TOKEN`, local saves stay on your machine only (fine for solo work).

## How the shared data stays consistent

- **Market data** lives in `data/*.parquet` and is **committed to GitHub** by Actions every night. Streamlit Cloud redeploys from that commit, so everyone sees the same numbers — not your browser cache.
- **Basket / chart edits** from the web UI are written to GitHub via the API when `GITHUB_TOKEN` is set. After the push, Streamlit Cloud picks up the new files.
- Adding a constituent updates the basket immediately; prices for brand-new tickers appear after the data workflow finishes (manual Update or the nightly run).

## Paid alternative (optional)

`render.yaml` remains available if you later want a always-on host with a persistent disk (~$7/mo). For that path set `ENABLE_INPROCESS_SCHEDULER=1`. The free Streamlit Cloud path above is the default.

## Data sources & fallbacks

| Data | Primary | Fallback |
|---|---|---|
| A-share prices (qfq-adjusted) | Tushare (if token set) | akshare: eastmoney → sina |
| HK prices | EODHD (if key set) | akshare: sina |
| Benchmarks CSI300/CSI500/HSI | akshare index feeds | stooq |
| Benchmarks SPX/NDX | akshare (sina US) | stooq |
| Valuations (PE/PB/mkt cap) | eastmoney spot (one call) | Baidu Gushitong per stock (A + HK) |
| Forward PE / PEG / analyst / EV/EBITDA | EODHD fundamentals | blank if unavailable |
| RSI | local calculation from cached price history | blank if insufficient history |

## Known limitations (prototype)

- Basket indices are **price return** only — dividends not yet reinvested.
- Weights are fixed at inception (buy-and-hold). Changing constituents changes history retroactively.
- `APP_PASSWORD` is a simple shared password, not per-user auth.
- After a GitHub push, Streamlit Cloud may take a few minutes to redeploy.
