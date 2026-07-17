# Baiguan Pro Index

Internal dashboard for tracking Baiguan Pro investment baskets — thesis, constituents,
performance vs benchmarks, valuations, and the team's custom charts, all in one place.

## Quick start

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt

# optional: prefer paid providers over free fallbacks
export TUSHARE_TOKEN=...     # A-share prices via Tushare Pro
export EODHD_API_KEY=...     # HK prices via EODHD
export APP_PASSWORD=...      # optional internal shared-password gate

.venv/bin/python update_data.py      # pull prices + fundamentals into data/
.venv/bin/streamlit run app.py       # open the dashboard
```

## How the team uses it

1. **Propose** — use the *Propose a Basket* page (or write a YAML file by hand).
   The basket lands in `baskets/` with status `proposed`.
2. **Review together** — refine the constituent list and thesis, then edit the YAML:
   set `status: active` and set `inception` to the go-live date. The index is
   base-100 from that date, buy-and-hold with weights fixed at inception.
3. **Track** — the *Overview* page shows all baskets vs benchmarks; *Basket Detail*
   shows the thesis, linked newsletters, performance chart and per-name valuation
   table (PE/PB/YTD etc.).
4. **Update data** — click *Update all data now* on the Data & Update page, or run
   `update_data.py` from cron / GitHub Actions.
5. **Share your charts** — use the *Team Charts* page to create/update chart code
   from a template. It saves a small Python file in `custom_charts/` and renders
   immediately in the shared gallery. Chart code can import `src.data` helpers and
   use the centralized `EODHD_API_KEY` / `TUSHARE_TOKEN` environment variables.

## Tiny-team deployment

For 3-4 internal users, the simplest version is:

- Deploy the Streamlit app to Render, Fly, Streamlit Cloud, or another long-running
  Python host. Vercel is excellent for a future Next.js version, but it is not the
  natural fit for a Streamlit server.
- Set `APP_PASSWORD`, `EODHD_API_KEY`, and `TUSHARE_TOKEN` as deployment
  environment variables. Do not commit real keys.
- Keep `baskets/` in git. Proposed baskets are YAML files, so changes are reviewable.

When this becomes subscriber-facing, move toward a Next.js/Vercel frontend with
Clerk/Auth0 and scheduled Python data jobs behind APIs.

## Basket YAML schema

```yaml
id: my-basket            # unique slug
name: My Basket
status: proposed         # proposed | active | archived
author: who proposed it
created: 2026-07-17
inception: 2026-07-17    # index base date (base = 100)
tags: [theme, sector]
thesis: >
  Why this basket exists, the catalyst, and what would make us wrong.
benchmarks: [CSI300, SPX, NDX]   # universal dashboard benchmarks
newsletters:
  - {title: ..., url: ..., date: ...}
constituents:
  - ticker: 600900.SH    # .SH / .SZ / .BJ / .HK
    name: 长江电力
    weight: null         # null = equal weight; or 0.15 etc.
    note: one-line rationale
```

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

Cached under `data/` as parquet (gitignored). Basket definitions in `baskets/` are
the source of truth and should be committed.

## Known limitations (prototype)

- Basket indices are **price return** only — dividends not yet reinvested, which
  understates the shareholder-return basket. Total-return via Tushare dividend data
  is the top roadmap item.
- Weights are fixed at inception (buy-and-hold). No rebalancing or constituent
  change history yet; changing a YAML changes history retroactively.
- HK valuation depth is still thinner than A-shares for dividend-yield style fields.
- `APP_PASSWORD` is intentionally simple; subscriber-facing auth should use a real
  auth provider.
