#!/usr/bin/env python3
"""
run_task.py — AI-Driven Content Generation & Data Monitoring
=============================================================

This script is the core of the automated pipeline. It:
  1. Fetches data from a free public API (no key required)
  2. Optionally enhances the summary using an LLM (if OPENAI_API_KEY is set)
  3. Falls back to a rule-based summary generator when no LLM key is present
     (ensuring $0/month operation with zero paid dependencies)
  4. Writes the generated content to the GitHub Pages site directory

Default free data source: CoinGecko public API (crypto market data, no key).
Swap the fetch_* function to monitor any public API you like.

Usage:
    python run_task.py --output-dir site --timestamp "2024-01-01T00:00:00Z"
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
COINGECKO_API = "https://api.coingecko.com/api/v3/simple/price"
COINS = ["bitcoin", "ethereum", "solana", "cardano"]
VS_CURRENCY = "usd"

# Optional LLM enhancement (only if OPENAI_API_KEY env var is set)
# Using OpenAI-compatible endpoint — swap base_url for GitHub Models, Ollama, etc.
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")


# ---------------------------------------------------------------------------
# Data Fetching (free, no API key)
# ---------------------------------------------------------------------------
def fetch_crypto_prices() -> dict:
    """Fetch current crypto prices from CoinGecko's free public API."""
    params = "?ids=" + ",".join(COINS) + f"&vs_currencies={VS_CURRENCY}&include_24hr_change=true"
    url = COINGECKO_API + params

    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "automated-pipeline/1.0",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return {"ok": True, "data": data}
    except urllib.error.URLError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# AI / LLM Summary (optional — only if API key present)
# ---------------------------------------------------------------------------
def llm_summarize(data: dict, timestamp: str) -> str:
    """Use an OpenAI-compatible LLM to generate a market summary."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return None  # Signal: no LLM available, use fallback

    prompt = (
        f"You are a concise financial data analyst. Based on the following "
        f"cryptocurrency market data snapshot (taken at {timestamp}), write a "
        f"2-3 sentence summary highlighting notable movers and overall sentiment.\n\n"
        f"{json.dumps(data, indent=2)}\n\nSummary:"
    )

    body = json.dumps({
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": "You are a concise financial data analyst."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 200,
        "temperature": 0.7,
    }).encode()

    req = urllib.request.Request(
        f"{LLM_BASE_URL}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"LLM call failed: {e}", file=sys.stderr)
        return None  # Fall back to rule-based


# ---------------------------------------------------------------------------
# Rule-Based Summary (free fallback — $0/month guaranteed)
# ---------------------------------------------------------------------------
def rule_based_summary(data: dict) -> str:
    """Generate a human-readable summary without any LLM. Always works."""
    if not data.get("ok"):
        return f"Data fetch failed: {data.get('error', 'unknown error')}. Will retry next cycle."

    lines = []
    prices = data["data"]
    for coin in COINS:
        info = prices.get(coin, {})
        price = info.get(VS_CURRENCY, "N/A")
        change = info.get(f"{VS_CURRENCY}_24h_change", 0)

        if isinstance(price, (int, float)):
            price_str = f"${price:,.2f}"
        else:
            price_str = str(price)

        if isinstance(change, (int, float)):
            arrow = "▲" if change >= 0 else "▼"
            change_str = f"{arrow} {abs(change):.2f}%"
        else:
            change_str = "N/A"

        lines.append(f"{coin.title()}: {price_str} ({change_str} 24h)")

    # Overall sentiment
    changes = [
        prices.get(c, {}).get(f"{VS_CURRENCY}_24h_change", 0)
        for c in COINS
        if isinstance(prices.get(c, {}).get(f"{VS_CURRENCY}_24h_change"), (int, float))
    ]
    if changes:
        avg = sum(changes) / len(changes)
        sentiment = "bullish" if avg > 0 else "bearish"
        lines.append(f"\nOverall market sentiment: {sentiment} (avg 24h change: {avg:+.2f}%)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML Dashboard Generation
# ---------------------------------------------------------------------------
def generate_html(summary: str, data: dict, timestamp: str, used_llm: bool) -> str:
    """Generate the GitHub Pages dashboard HTML."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Build price cards
    cards_html = ""
    if data.get("ok"):
        prices = data["data"]
        for coin in COINS:
            info = prices.get(coin, {})
            price = info.get(VS_CURRENCY, 0)
            change = info.get(f"{VS_CURRENCY}_24h_change", 0)

            if isinstance(change, (int, float)):
                color = "#22c55e" if change >= 0 else "#ef4444"
                arrow = "▲" if change >= 0 else "▼"
                change_html = f'<span class="change" style="color:{color}">{arrow} {abs(change):.2f}%</span>'
            else:
                change_html = '<span class="change">N/A</span>'

            if isinstance(price, (int, float)):
                price_html = f"${price:,.2f}"
            else:
                price_html = "N/A"

            cards_html += f"""
            <div class="card">
                <h3>{coin.title()}</h3>
                <div class="price">{price_html}</div>
                {change_html}
            </div>"""
    else:
        cards_html = '<div class="card"><h3>Data Unavailable</h3><div class="price">—</div></div>'

    llm_badge = '<span class="badge llm">LLM Enhanced</span>' if used_llm else '<span class="badge fallback">Rule-Based</span>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Automated Pipeline Dashboard</title>
    <style>
        :root {{
            --bg: #0f172a;
            --card-bg: #1e293b;
            --text: #f1f5f9;
            --text-muted: #94a3b8;
            --accent: #3b82f6;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            padding: 2rem;
        }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        header {{
            text-align: center;
            margin-bottom: 2rem;
        }}
        header h1 {{
            font-size: 1.75rem;
            margin-bottom: 0.5rem;
        }}
        header .meta {{
            color: var(--text-muted);
            font-size: 0.9rem;
        }}
        .badges {{ margin: 0.5rem 0; }}
        .badge {{
            display: inline-block;
            padding: 0.2rem 0.6rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
            margin: 0 0.2rem;
        }}
        .badge.llm {{ background: #1e3a5f; color: #60a5fa; }}
        .badge.fallback {{ background: #3b2f1e; color: #fbbf24; }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}
        .card {{
            background: var(--card-bg);
            border-radius: 12px;
            padding: 1.5rem;
            text-align: center;
            border: 1px solid #334155;
        }}
        .card h3 {{
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
            margin-bottom: 0.5rem;
        }}
        .card .price {{
            font-size: 1.5rem;
            font-weight: 700;
            margin-bottom: 0.3rem;
        }}
        .card .change {{ font-size: 0.85rem; font-weight: 600; }}
        .summary {{
            background: var(--card-bg);
            border-radius: 12px;
            padding: 1.5rem;
            border: 1px solid #334155;
            white-space: pre-wrap;
            line-height: 1.6;
        }}
        .summary h2 {{
            font-size: 1rem;
            color: var(--text-muted);
            margin-bottom: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        footer {{
            text-align: center;
            color: var(--text-muted);
            font-size: 0.8rem;
            margin-top: 2rem;
        }}
        footer a {{ color: var(--accent); text-decoration: none; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Automated AI Pipeline</h1>
            <div class="meta">
                Last updated: {now}<br>
                Pipeline run: {timestamp}
            </div>
            <div class="badges">{llm_badge}</div>
        </header>

        <div class="grid">
            {cards_html}
        </div>

        <div class="summary">
            <h2>AI Summary</h2>
            <p>{summary}</p>
        </div>

        <footer>
            <p>Powered by GitHub Actions &middot; Runs every 4 hours &middot; <a href="status.json">View raw status JSON</a></p>
        </footer>
    </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Status JSON (consumed by the dashboard and monitoring)
# ---------------------------------------------------------------------------
def write_status_json(output_dir: Path, status: dict):
    """Write a status.json file for the dashboard to consume."""
    status_path = output_dir / "status.json"
    with open(status_path, "w") as f:
        json.dump(status, f, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Run the AI-driven automated task")
    parser.add_argument("--output-dir", required=True, help="Directory for generated site content")
    parser.add_argument("--timestamp", required=True, help="Execution timestamp (ISO 8601)")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/4] Fetching market data from CoinGecko (free, no API key)...")
    data = fetch_crypto_prices()
    if data["ok"]:
        print(f"      Fetched prices for {len(data['data'])} coins")
    else:
        print(f"      WARNING: Data fetch failed: {data['error']}", file=sys.stderr)

    print(f"[2/4] Generating summary...")
    used_llm = False
    summary = None

    # Try LLM first if API key is available
    if os.environ.get("OPENAI_API_KEY"):
        print(f"      OPENAI_API_KEY detected — using LLM ({LLM_MODEL})")
        summary = llm_summarize(data, args.timestamp)
        if summary:
            used_llm = True
            print(f"      LLM summary generated ({len(summary)} chars)")
        else:
            print(f"      LLM call failed — falling back to rule-based")
    else:
        print(f"      No LLM key — using rule-based summary ($0/month mode)")

    if not summary:
        summary = rule_based_summary(data)
        print(f"      Rule-based summary generated ({len(summary)} chars)")

    print(f"[3/4] Generating HTML dashboard...")
    html = generate_html(summary, data, args.timestamp, used_llm)
    html_path = output_dir / "index.html"
    with open(html_path, "w") as f:
        f.write(html)
    print(f"      Written to {html_path}")

    print(f"[4/4] Writing status JSON...")
    status = {
        "timestamp": args.timestamp,
        "status": "success",
        "used_llm": used_llm,
        "data_source": "CoinGecko API",
        "coins_monitored": COINS,
        "data_ok": data["ok"],
        "summary": summary,
    }
    write_status_json(output_dir, status)

    print(f"\n✓ Task complete. Output written to {output_dir}/")


if __name__ == "__main__":
    main()
