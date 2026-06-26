"""
release_host.py
Facebook / Instagram / TikTok all want to fetch the finished video from a
public URL - they don't accept raw file uploads from a script easily.

Since this whole thing already lives in a GitHub repo, the simplest free
"host" is a GitHub Release: we create one tagged with a timestamp, attach
the .mp4 as a release asset, and use that asset's public download URL.

Needs: GITHUB_TOKEN (already provided automatically inside GitHub Actions,
no extra secret needed) and the repo's "owner/name" (also provided
automatically as GITHUB_REPOSITORY).
"""

import os
import time
import requests

API_ROOT = "https://api.github.com"


def publish_video_get_public_url(video_path: str, token: str | None = None,
                                  repo: str | None = None) -> str:
    token = token or os.environ["GITHUB_TOKEN"]
    repo = repo or os.environ["GITHUB_REPOSITORY"]  # e.g. "yourname/yourrepo"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    tag = f"video-{int(time.time())}"

    create_resp = requests.post(
        f"{API_ROOT}/repos/{repo}/releases",
        headers=headers,
        json={
            "tag_name": tag,
            "name": tag,
            "body": "Auto-generated quote video build.",
            "draft": False,
            "prerelease": False,
        },
        timeout=30,
    )
    create_resp.raise_for_status()
    release = create_resp.json()
    upload_url = release["upload_url"].split("{")[0]

    with open(video_path, "rb") as f:
        upload_resp = requests.post(
            upload_url,
            headers={**headers, "Content-Type": "video/mp4"},
            params={"name": os.path.basename(video_path)},
            data=f,
            timeout=300,
        )
    upload_resp.raise_for_status()
    asset = upload_resp.json()

    return asset["browser_download_url"]
