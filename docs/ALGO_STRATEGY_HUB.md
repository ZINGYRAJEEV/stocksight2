# Algo Strategy Hub

Multi-horizon **best stock** selector: intraday, weekly, monthly, and long-term — pattern + regime scoring.

## Streamlit UI

**Sidebar → Algo Strategy → Algo Strategy Hub**

1. Choose market and universe.
2. Select horizons and **FIND BEST STOCKS**.
3. Download combined CSV from the bottom of the page.

## CLI

```bash
python scripts/run_algo_hub.py --universe "Nifty 50 (fast)" --top-n 8
python scripts/run_algo_hub.py --email   # requires [smtp] in .streamlit/secrets.toml
```

Outputs: `output/algo_hub/algo_<horizon>_*.csv` and `summary_*.json`.

## GitHub Actions

Workflow: `.github/workflows/algo-strategy-hub.yml`

- **Run workflow** manually from the Actions tab.
- Scheduled Mon–Fri (UTC) — download **Artifacts** for CSVs.

## SMTP email (optional)

In `.streamlit/secrets.toml`:

```toml
[smtp]
host = "smtp.gmail.com"
port = 587
user = "your@gmail.com"
password = "app-password"
from_addr = "your@gmail.com"
to_addrs = ["you@gmail.com"]
```

Then: `python scripts/run_algo_hub.py --email`

## Compliance

White-box research signals only. India live algos require broker hosting, exchange approval, and Algo IDs (SEBI). No auto-orders from this hub.
