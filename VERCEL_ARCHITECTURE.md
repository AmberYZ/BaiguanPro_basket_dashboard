# Vercel target architecture

The current Streamlit prototype is useful for product iteration, but it should
not be deployed as-is to Vercel. Streamlit expects a persistent Python server
and writes basket YAML/parquet to local disk; Vercel Functions are ephemeral.

## Lightweight production shape

### Public read path

- Next.js App Router on Vercel.
- Public pages: overview, many-charts gallery, active basket detail.
- Pages read precomputed daily basket snapshots. They never call Tushare/EODHD
  during a reader request.
- Cache public reads and invalidate after the daily market-data job.

### Internal write path

- `/internal/*` routes protected by Clerk, Auth0, or Vercel Authentication.
- Only 3-4 internal users can propose, approve, edit, archive, or delete baskets.
- Simple lifecycle: `proposed -> active -> archived`.
- No separate approver role initially: any authenticated teammate can activate.

### Persistence

- Marketplace Postgres (for example Neon):
  - `baskets`: id, slug, name, thesis, status, inception, author, timestamps.
  - `basket_constituents`: basket id, ticker, name, weight, rationale, sort order.
  - `basket_watchpoints`: basket id, text, sort order, last AI update.
  - `basket_articles`: basket id, title, URL, published date.
  - `team_charts`: id, title, description, chart type/config, basket links.
  - `price_snapshots`: ticker, market date, adjusted close.
  - `fundamental_snapshots`: ticker, market date, PE/PB/PEG/EV-EBITDA/RSI fields.
  - `basket_snapshots`: basket id, market date, index level and return/risk metrics.
- Vercel Blob only for generated exports/images, not canonical basket state.
- Environment variables hold Tushare/EODHD credentials; never expose them to the
  browser.

### Daily update

1. A Vercel Cron route (or GitHub Action if Python provider libraries are easier)
   fetches EOD market data.
2. The job upserts ticker snapshots.
3. It recomputes basket levels, period returns, drawdown, volatility, and Sharpe.
4. It invalidates the public Next.js cache by basket tag.

This keeps reader pages fast and prevents API rate limits from scaling with
subscriber traffic.

## Migration order

1. Freeze the Streamlit product shape after team feedback.
2. Introduce Postgres and migrate YAML baskets into the normalized tables.
3. Build read-only Next.js public overview and basket detail.
4. Add internal auth and proposal/approval/edit screens.
5. Move daily data refresh to cron and retire parquet/local writes.
