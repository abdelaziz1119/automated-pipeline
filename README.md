# Automated AI Pipeline — $0/Month

A fully automated system using GitHub Actions that:

1. **Clones a repository** and runs an AI-driven task every 4 hours
2. **Monitors data** (crypto market prices by default — swap for any free API)
3. **Generates content** — an AI summary with an optional LLM, or a rule-based fallback that costs nothing
4. **Pushes results** to a live GitHub Pages dashboard
5. **Logs execution status** (success and failure) to a **separate** repository for automated status tracking

**Total cost: $0/month** when using public repos, GitHub's free Actions tier, and the rule-based summary (no paid AI API key).

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  MAIN REPO (automated-pipeline)                          │
│                                                          │
│  .github/workflows/                                      │
│  ├── automated-task.yml   ← runs every 4h at :17 UTC    │
│  └── deploy-pages.yml      ← manual/push fallback       │
│                                                          │
│  scripts/                                                │
│  ├── run_task.py          ← fetches data, generates HTML │
│  └── monitor.py           ← logs to separate status repo │
│                                                          │
│  site/                                                   │
│  ├── index.html           ← GitHub Pages dashboard       │
│  └── status.json          ← machine-readable status      │
│                                                          │
│  GitHub Pages → https://<username>.github.io/<repo>/     │
└──────────────┬───────────────────────────────────────────┘
               │
               │  STATUS_REPO_TOKEN (fine-grained PAT)
               ▼
┌──────────────────────────────────────────────────────────┐
│  STATUS REPO (pipeline-status)                            │
│                                                          │
│  logs/                                                   │
│  └── YYYY-MM-DD/                                         │
│      └── <run_id>-<stage>.json  ← immutable per-run logs │
│                                                          │
│  latest.json     ← most recent status (always up to date) │
│  runs.md         ← human-readable audit trail table       │
│                                                          │
│  Issues          ← opened on failure (deduplicated)       │
└──────────────────────────────────────────────────────────┘
```

---

## File Structure

```
automated-pipeline/
├── .github/
│   └── workflows/
│       ├── automated-task.yml    # Main pipeline (every 4h cron)
│       └── deploy-pages.yml      # Fallback Pages deployment
├── scripts/
│   ├── run_task.py               # AI-driven task (data fetch + content gen)
│   └── monitor.py                # Cross-repo status logger
├── site/
│   ├── index.html                # Dashboard (overwritten each run)
│   └── status.json               # Machine-readable status
├── requirements.txt              # No external deps needed
└── README.md
```

---

## Setup Guide (10 steps)

### Step 1: Create the main repository

Create a **public** GitHub repository named `automated-pipeline` (or any name you prefer). Public repos get unlimited GitHub Actions minutes and free GitHub Pages.

### Step 2: Push the code

Clone this repo, add your GitHub remote, and push:

```bash
git init
git remote add origin https://github.com/YOUR-USERNAME/automated-pipeline.git
git add .
git commit -m "Initial commit: automated AI pipeline"
git push -u origin main
```

### Step 3: Create the status-tracking repository

Create a **second** public repository named `pipeline-status`. This is where execution logs will be pushed.

### Step 4: Create a fine-grained Personal Access Token (PAT)

Go to: **GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**

Settings:
- **Token name:** `pipeline-status-logger`
- **Expiration:** 90 days (or custom)
- **Repository access:** Select `pipeline-status` only
- **Permissions:**
  - **Contents:** Read and write
  - **Issues:** Read and write

Copy the token immediately (you won't see it again).

### Step 5: Add the PAT as a repository secret

In the `automated-pipeline` repo, go to: **Settings → Secrets and variables → Actions → Secrets → New repository secret**

- **Name:** `STATUS_REPO_TOKEN`
- **Value:** (paste the PAT from Step 4)

### Step 6: Add the status repo name as a variable

In the same settings page, go to: **Variables → New variable**

- **Name:** `STATUS_REPO`
- **Value:** `YOUR-USERNAME/pipeline-status`

### Step 7: (Optional) Add an LLM API key for AI-enhanced summaries

If you want LLM-generated summaries instead of the rule-based fallback, add a secret:

- **Name:** `OPENAI_API_KEY`
- **Value:** Your API key

**Without this secret, the pipeline runs in $0/month mode** using a rule-based summary generator. The dashboard shows a "Rule-Based" badge. With the key, it shows "LLM Enhanced".

You can also set `LLM_BASE_URL` and `LLM_MODEL` variables to use any OpenAI-compatible API (GitHub Models, Ollama, etc.).

### Step 8: Enable GitHub Pages

In the `automated-pipeline` repo, go to: **Settings → Pages**

- **Source:** GitHub Actions
- The workflow will handle deployment automatically.

### Step 9: Test the pipeline

Go to: **Actions → Automated AI Pipeline → Run workflow**

This triggers a manual run. Check:
- The action completes successfully
- `site/index.html` is updated with real data
- `pipeline-status` repo has `latest.json`, `runs.md`, and `logs/` populated
- Your GitHub Pages site shows the dashboard

### Step 10: Verify the schedule

The cron `17 */4 * * *` runs at **:17 past every 4th hour** in UTC:
- 00:17, 04:17, 08:17, 12:17, 16:17, 20:17 UTC

The :17 offset avoids GitHub's top-of-hour schedule congestion, which can cause delays of 10-30+ minutes.

---

## What the Pipeline Does

### Task Script (`scripts/run_task.py`)

1. **Fetches data** from CoinGecko's free public API (no API key needed) — current prices for Bitcoin, Ethereum, Solana, and Cardano with 24h change percentages.

2. **Generates a summary:**
   - If `OPENAI_API_KEY` is set: calls the LLM for a 2-3 sentence market analysis
   - If not set: uses a rule-based summary that calculates average market sentiment, identifies movers, and formats a human-readable report — **completely free**

3. **Generates an HTML dashboard** (`site/index.html`) with:
   - Price cards for each monitored asset
   - Color-coded 24h change indicators (green/red)
   - The AI/rule-based summary
   - A badge showing whether LLM or rule-based mode was used

4. **Writes `status.json`** with the full run data for programmatic consumption.

### Monitoring Script (`scripts/monitor.py`)

Runs after both the task and deployment stages (via `if: always()`), and:

1. **Writes an immutable log file** to `logs/YYYY-MM-DD/<run_id>-<stage>.json` — one file per stage per run, preventing race conditions.

2. **Updates `latest.json`** — a single file with the most recent status and the last 20 runs as history.

3. **Appends to `runs.md`** — a human-readable Markdown table audit trail:
   ```
   | Run # | Timestamp (UTC) | Stage  | Status       | Commit   | Summary           |
   |-------|-----------------|--------|--------------|----------|-------------------|
   | 42    | 2024-01-01 00:17 | task   | ✅ success   | abc12345 | Task success      |
   | 42    | 2024-01-01 00:18 | deploy | ✅ success   | abc12345 | Pages deployment  |
   ```

4. **On failure: opens a GitHub Issue** in the status repo:
   - First failure: creates a new issue with `pipeline-failure` label
   - Subsequent failures: adds a comment to the **existing open issue** (deduplicated)
   - Close the issue to reset the dedup cycle

---

## Cost Breakdown

| Component              | Free Tier Limit                     | This Pipeline's Usage        |
|------------------------|-------------------------------------|------------------------------|
| GitHub Actions minutes | 2,000 min/month (private), unlimited (public) | ~2 min/run × 6 runs/day = ~360 min/month |
| GitHub Pages           | Free for public repos               | 1 site, static HTML          |
| GitHub API calls       | 5,000/hour per token                | ~5 calls per run             |
| CoinGecko API          | Free, no key, ~50 calls/minute      | 1 call per run               |
| LLM API (optional)     | Pay-per-use if OPENAI_API_KEY set   | $0 if not set                |

**With public repos and no LLM key: $0/month guaranteed.**

If you use private repos, you get 2,000 free Actions minutes/month. This pipeline uses ~360 minutes/month (6 runs/day × 30 days × ~2 min/run), well within the free tier.

---

## Customization

### Change the data source

Edit `scripts/run_task.py` and replace the `fetch_crypto_prices()` function with any free public API:

```python
def fetch_my_data() -> dict:
    # Example: fetch weather data
    url = "https://api.open-meteo.com/v1/forecast?latitude=59.4&longitude=18.1&current_weather=true"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return {"ok": True, "data": json.loads(resp.read().decode())}
```

Then update the `generate_html()` function to render the new data format.

### Change the schedule

Edit `.github/workflows/automated-task.yml`:

```yaml
on:
  schedule:
    - cron: "17 */4 * * *"   # Every 4 hours
    # Alternatives:
    # - cron: "17 * * * *"      # Every hour
    # - cron: "17 */6 * * *"    # Every 6 hours
    # - cron: "17 0 * * *"      # Daily at midnight UTC
```

### Change the monitored coins

Edit the `COINS` list in `scripts/run_task.py`:

```python
COINS = ["bitcoin", "ethereum", "dogecoin", "polkadot"]
```

### Use GitHub Models (free LLM alternative)

GitHub Models offers a free tier for AI inference. To use it:

1. Set `LLM_BASE_URL` variable to: `https://models.inference.ai.azure.com`
2. Set `LLM_MODEL` variable to: `gpt-4o-mini`
3. Set `OPENAI_API_KEY` secret to your GitHub token with `models:read` permission

The workflow already includes `models: read` permission.

---

## Monitoring While You Sleep

The status repo (`pipeline-status`) serves as your monitoring dashboard:

- **`latest.json`** — Always reflects the most recent run. Poll this with any monitoring tool.
- **`runs.md`** — Human-readable history. Browse it on GitHub directly.
- **GitHub Issues** — If a run fails, you get a GitHub Issue. Configure GitHub to send you email notifications for new issues in this repo (Settings → Notifications → Participating).
- **Immutable logs** — Each run's full JSON log is preserved at `logs/YYYY-MM-DD/<run_id>-<stage>.json` for auditing.

To get email alerts on failure:
1. Go to the `pipeline-status` repo
2. Click **Watch → Custom → Issues**
3. Ensure email is enabled in your GitHub notification settings

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `STATUS_REPO is not set` | Add the `STATUS_REPO` variable in repo settings (Step 6) |
| `STATUS_REPO_TOKEN is not set` | Add the PAT as a secret (Step 5) |
| Pages not deploying | Check Settings → Pages → Source is "GitHub Actions" |
| CoinGecko API rate limited | The free API allows ~50 calls/min; 1 call per 4h is fine |
| `403` on status repo commits | PAT needs `contents:write` permission on the status repo |
| Schedule not triggering | GitHub Actions schedules can delay 10-30 min during peak hours |
| LLM call failing | Check API key, or remove `OPENAI_API_KEY` to use free rule-based mode |

---

## License

MIT — Use this freely for any purpose.
