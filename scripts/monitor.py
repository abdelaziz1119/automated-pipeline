#!/usr/bin/env python3
"""
monitor.py — Cross-Repository Status Logger
============================================

Logs pipeline execution status to a SEPARATE GitHub repository for
automated status tracking while you sleep.

What it does:
  1. Writes an immutable JSON log file to logs/YYYY-MM-DD/<run_id>-<stage>.json
  2. Updates latest.json with the most recent run's status
  3. Appends a row to runs.md (a human-readable audit trail)
  4. On failure: opens a GitHub Issue (deduplicated — won't spam duplicates)

Authentication:
  Uses STATUS_REPO_TOKEN (fine-grained PAT with contents:write + issues:write
  on the status repo). The default GITHUB_TOKEN cannot write to other repos.

Usage:
    python monitor.py \
        --status success \
        --timestamp "2024-01-01T00:00:00Z" \
        --run-id 12345678901 \
        --run-number 42 \
        --commit-sha abc123 \
        --summary "Task success" \
        --status-repo "your-username/pipeline-status" \
        --actor "github-actions[bot]" \
        --source-repo "your-username/automated-pipeline" \
        --stage "task"
"""

import argparse
import base64
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------
GITHUB_API = "https://api.github.com"


def gh_api(method: str, path: str, token: str, body: dict = None) -> dict:
    """Make an authenticated GitHub API request."""
    url = f"{GITHUB_API}/repos/{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        print(f"GitHub API error {e.code}: {error_body}", file=sys.stderr)
        return {"error": e.code, "body": error_body}
    except Exception as e:
        print(f"GitHub API request failed: {e}", file=sys.stderr)
        return {"error": str(e)}


def gh_get_file(repo: str, path: str, token: str) -> dict:
    """Get a file from a repo. Returns {content, sha} or {error}."""
    return gh_api("GET", f"{repo}/contents/{path}", token)


def gh_create_or_update_file(repo: str, path: str, token: str,
                             content: str, message: str, sha: str = None) -> dict:
    """Create or update a file in a repo via the Contents API."""
    body = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
    }
    if sha:
        body["sha"] = sha
    return gh_api("PUT", f"{repo}/contents/{path}", token, body)


# ---------------------------------------------------------------------------
# Logging: immutable per-run JSON + latest.json + runs.md
# ---------------------------------------------------------------------------
def log_status(args):
    """Write status logs to the separate status repository."""
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        print("ERROR: GH_TOKEN environment variable not set.", file=sys.stderr)
        print("       This should be STATUS_REPO_TOKEN from the workflow.", file=sys.stderr)
        sys.exit(1)

    if not args.status_repo or "/" not in args.status_repo:
        print(f"ERROR: --status-repo must be 'owner/repo-name', got: {args.status_repo}", file=sys.stderr)
        sys.exit(1)

    # Parse timestamp for directory structure
    try:
        dt = datetime.fromisoformat(args.timestamp.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.now(timezone.utc)

    date_str = dt.strftime("%Y-%m-%d")
    time_str = dt.strftime("%H:%M:%S")

    # Build the log entry
    log_entry = {
        "run_id": args.run_id,
        "run_number": args.run_number,
        "stage": args.stage,
        "status": args.status,
        "timestamp": args.timestamp,
        "date": date_str,
        "time": time_str,
        "commit_sha": args.commit_sha,
        "summary": args.summary,
        "actor": args.actor,
        "source_repo": args.source_repo,
    }

    log_json = json.dumps(log_entry, indent=2)

    # --- 1. Write immutable per-run log file ---
    log_path = f"logs/{date_str}/{args.run_id}-{args.stage}.json"
    print(f"[1/3] Writing immutable log: {log_path}")
    gh_create_or_update_file(
        args.status_repo, log_path, token,
        log_json,
        f"log: {args.status} — {args.stage} stage — run #{args.run_number} ({date_str})"
    )

    # --- 2. Update latest.json ---
    print(f"[2/3] Updating latest.json...")
    existing = gh_get_file(args.status_repo, "latest.json", token)
    latest_data = log_entry.copy()
    latest_data["history"] = []

    if "sha" in existing:
        # Merge with previous history
        try:
            prev = json.loads(base64.b64decode(existing["content"]).decode())
            if isinstance(prev.get("history"), list):
                latest_data["history"] = prev["history"][-19:]  # Keep last 19 + current = 20
        except Exception:
            pass

    latest_data["history"].append({
        "run_number": args.run_number,
        "status": args.status,
        "stage": args.stage,
        "timestamp": args.timestamp,
    })

    latest_json = json.dumps(latest_data, indent=2)
    latest_sha = existing.get("sha") if "sha" in existing else None
    gh_create_or_update_file(
        args.status_repo, "latest.json", token,
        latest_json,
        f"chore: update latest status — {args.status} ({args.stage})",
        sha=latest_sha,
    )

    # --- 3. Append to runs.md (human-readable audit trail) ---
    print(f"[3/3] Appending to runs.md...")
    existing_md = gh_get_file(args.status_repo, "runs.md", token)
    md_content = ""
    md_sha = None
    if "sha" in existing_md:
        try:
            md_content = base64.b64decode(existing_md["content"]).decode()
            md_sha = existing_md["sha"]
        except Exception:
            pass

    # Prepend the new entry (newest first)
    status_icon = "✅" if args.status == "success" else "❌"
    new_row = (
        f"| {args.run_number} | {date_str} {time_str} | {args.stage} | "
        f"{status_icon} {args.status} | {args.commit_sha[:8] if args.commit_sha else 'N/A'} | "
        f"{args.summary} |\n"
    )

    if "| Run #" in md_content:
        # Insert after the header separator line
        lines = md_content.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("|---"):
                lines.insert(i + 1, new_row.rstrip("\n"))
                break
        md_content = "\n".join(lines) + "\n"
    else:
        # Create the file with a header
        md_content = (
            "# Pipeline Run History\n\n"
            "| Run # | Timestamp (UTC) | Stage | Status | Commit | Summary |\n"
            "|-------|-----------------|-------|--------|--------|---------|\n"
            + new_row
        )

    gh_create_or_update_file(
        args.status_repo, "runs.md", token,
        md_content,
        f"docs: append run #{args.run_number} ({args.status})",
        sha=md_sha,
    )

    # --- 4. On failure: open a deduplicated GitHub Issue ---
    if args.status != "success":
        print(f"[!] Failure detected — checking for existing open issue...")
        create_or_update_failure_issue(args, token, log_entry)


def create_or_update_failure_issue(args, token, log_entry):
    """Open a GitHub Issue on failure, but deduplicate so we don't spam."""
    # Search for existing open issues with our label
    search_url = (
        f"{GITHUB_API}/search/issues?"
        f"q=repo:{args.status_repo}+is:issue+is:open+label:pipeline-failure"
    )
    req = urllib.request.Request(search_url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            if result.get("total_count", 0) > 0:
                # Comment on the existing issue instead of creating a new one
                existing_issue = result["items"][0]
                issue_number = existing_issue["number"]
                print(f"    Found existing failure issue #{issue_number} — adding comment")

                comment_body = (
                    f"## Recurring Failure — Run #{args.run_number}\n\n"
                    f"- **Stage:** {args.stage}\n"
                    f"- **Timestamp:** {args.timestamp}\n"
                    f"- **Commit:** `{args.commit_sha[:8] if args.commit_sha else 'N/A'}`\n"
                    f"- **Summary:** {args.summary}\n"
                    f"- **Source Repo:** `{args.source_repo}`\n\n"
                    f"---\n"
                )
                gh_api("POST", f"{args.status_repo}/issues/{issue_number}/comments", token,
                       {"body": comment_body})
                return
    except Exception as e:
        print(f"    Could not search issues: {e}", file=sys.stderr)

    # No existing issue — create a new one
    print(f"    Creating new failure issue...")
    issue_body = (
        f"## Pipeline Failure Detected\n\n"
        f"The automated pipeline has encountered a failure.\n\n"
        f"| Field | Value |\n|-------|-------|\n"
        f"| Run # | {args.run_number} |\n"
        f"| Stage | {args.stage} |\n"
        f"| Status | ❌ {args.status} |\n"
        f"| Timestamp | {args.timestamp} |\n"
        f"| Commit | `{args.commit_sha[:8] if args.commit_sha else 'N/A'}` |\n"
        f"| Actor | {args.actor} |\n"
        f"| Source Repo | `{args.source_repo}` |\n\n"
        f"### Summary\n{args.summary}\n\n"
        f"---\n"
        f"_This issue was created automatically by the pipeline monitor._\n"
        f"_Subsequent failures will be added as comments until this issue is closed._"
    )

    gh_api("POST", f"{args.status_repo}/issues", token, {
        "title": f"Pipeline Failure — {args.stage} (Run #{args.run_number})",
        "body": issue_body,
        "labels": ["pipeline-failure", "automated"],
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Log pipeline status to a separate repo")
    parser.add_argument("--status", required=True, help="Execution status (success/failure)")
    parser.add_argument("--timestamp", required=True, help="ISO 8601 timestamp")
    parser.add_argument("--run-id", required=True, help="GitHub Actions run ID")
    parser.add_argument("--run-number", required=True, help="GitHub Actions run number")
    parser.add_argument("--commit-sha", required=True, help="Git commit SHA")
    parser.add_argument("--summary", required=True, help="Human-readable summary")
    parser.add_argument("--status-repo", required=True, help="Status repo (owner/repo-name)")
    parser.add_argument("--actor", required=True, help="Triggering actor")
    parser.add_argument("--source-repo", required=True, help="Source repo (owner/repo-name)")
    parser.add_argument("--stage", default="task", help="Pipeline stage (task/deploy)")
    args = parser.parse_args()

    print(f"=== Pipeline Status Logger ===")
    print(f"  Status:     {args.status}")
    print(f"  Stage:      {args.stage}")
    print(f"  Run #:      {args.run_number}")
    print(f"  Timestamp:  {args.timestamp}")
    print(f"  Status repo: {args.status_repo}")
    print()

    log_status(args)
    print(f"\n✓ Status logged to {args.status_repo}")


if __name__ == "__main__":
    main()
