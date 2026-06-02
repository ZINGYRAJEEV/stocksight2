# Intraday cycle automation

Run the same workflow as the **Intraday / ICICI Breeze screener** without opening Streamlit: gap scan → intraday strategies → gap-overlap list → CSV + JSON.

**This does not place broker orders.** Use **ICICI Breeze Screener → Live Trade** for real buys.

## Local (Windows)

```bat
cd stocksight2
pip install -r requirements.txt
scripts\run_intraday_cycle.bat
```

Optional flags:

```bat
scripts\run_intraday_cycle.bat --universe "Nifty 50 (fast)" --data-source yahoo
scripts\run_intraday_cycle.bat --phase gap --gap-min-pct 1.5
scripts\run_intraday_cycle.bat --phase intraday --strategies BROAD,MOMENTUM,VWAP,ORB,GAP
scripts\run_intraday_cycle.bat --max-tickers 50
```

## Local (Mac / Linux)

```bash
chmod +x scripts/run_intraday_cycle.sh
./scripts/run_intraday_cycle.sh --universe "Nifty 50 (fast)"
```

## Outputs

Written to `output/intraday/`:

| File | Content |
|------|---------|
| `gaps_YYYYMMDD_HHMM.csv` | Gap scanner rows + Quality Gate |
| `intraday_all_YYYYMMDD_HHMM.csv` | All strategy matches |
| `intraday_gap_overlap_YYYYMMDD_HHMM.csv` | Intraday names that also gapped |
| `summary_YYYYMMDD_HHMM.json` | Counts, session timing, top rows |

With `--history`, snapshots append to `stocksight/.scan_history.jsonl`.

## GitHub Actions

Workflow: **`.github/workflows/intraday-cycle.yml`**

1. Push this repo to GitHub.
2. **Actions → Intraday cycle → Run workflow** (manual).
3. Or use the built-in schedule (Mon–Fri UTC, aligned to NSE morning).
4. Download **Artifacts** → `intraday-cycle-<run_id>`.

### Optional secrets (ICICI Breeze live data)

Repository **Settings → Secrets → Actions**:

| Secret | Purpose |
|--------|---------|
| `BREEZE_API_KEY` | Breeze API key |
| `BREEZE_API_SECRET` | Breeze secret |
| `BREEZE_SESSION_TOKEN` | Daily `apisession` (expires every day) |

Set workflow input **data_source** to `breeze`. Otherwise the job uses **yahoo** (no secrets).

### Limits on GitHub runners

- Runners are **UTC**; scheduled times approximate IST open — adjust cron in the YAML if needed.
- Large universes (Nifty 500) may hit the **45 min** job timeout — use `--max-tickers` or a smaller universe in workflow inputs.
- **No auto-trading** in CI — review CSVs, trade manually in the app.

## Typical day (NSE)

| Time (IST) | Phase | Command |
|------------|-------|---------|
| ~9:00 | Gap battle map | `--phase gap` |
| ~9:35 | Open ORB / momentum | `--phase intraday` |
| ~10:30 | VWAP pullbacks | `--phase intraday` (or full) |
| Any | High-conviction overlap | `--phase full` (includes overlap CSV) |

## Data source

| Value | Behaviour |
|-------|-----------|
| `yahoo` | Best for GitHub Actions and offline runs |
| `breeze` | Live NSE bars; needs valid session token |
| `auto` | Breeze if configured, else Yahoo |
