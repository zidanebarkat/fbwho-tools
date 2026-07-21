"""GitHub Actions dispatch — triggers the restream workflow via PAT."""
import os
from curl_cffi import requests as curl_requests
from config import Config


def trigger_workflow(stream_key, rtmp_url, source_url, title, github_pat, cookies_b64="", preview="false"):
    token = github_pat or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return None, "GitHub PAT not configured"

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    wf_url = f"{Config.GITHUB_API}/repos/{Config.GITHUB_OWNER}/{Config.GITHUB_REPO}/actions/workflows/restream.yml/dispatches"

    wf_inputs = {
        "source_url": source_url,
        "output_url": rtmp_url,
        "title": title,
        "overlay_text": title,
        "github_token": token,
        "cookies_b64": cookies_b64,
        "preview": str(preview).lower(),
    }

    r = curl_requests.post(wf_url, json={"ref": "main", "inputs": wf_inputs}, headers=headers)
    if r.status_code not in (200, 204):
        return None, f"Workflow trigger failed: {r.status_code} {r.text[:200]}"

    return {"workflow": "triggered"}, None


def check_workflow_status():
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return {"active": False}

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    r = curl_requests.get(
        f"{Config.GITHUB_API}/repos/{Config.GITHUB_OWNER}/{Config.GITHUB_REPO}/actions/runs?status=in_progress&per_page=1",
        headers=headers,
    )
    if r.status_code == 200:
        runs = r.json().get("workflow_runs", [])
        if runs:
            return {"active": True, "run_id": runs[0]["id"], "status": runs[0]["status"], "created_at": runs[0]["created_at"]}
    return {"active": False}


def cancel_workflow():
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return False, "No GitHub token"

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    r = curl_requests.get(
        f"{Config.GITHUB_API}/repos/{Config.GITHUB_OWNER}/{Config.GITHUB_REPO}/actions/runs?status=in_progress&per_page=1",
        headers=headers,
    )
    if r.status_code == 200:
        runs = r.json().get("workflow_runs", [])
        if not runs:
            return False, "No active run found"
        run_id = runs[0]["id"]
        r = curl_requests.post(
            f"{Config.GITHUB_API}/repos/{Config.GITHUB_OWNER}/{Config.GITHUB_REPO}/actions/runs/{run_id}/cancel",
            headers=headers,
        )
        if r.status_code in (202, 204):
            return True, None
        return False, f"Cancel failed: {r.status_code}"
    return False, "No active runs"
