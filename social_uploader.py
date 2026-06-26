"""
social_uploader.py
Posts the finished video to Facebook, Instagram, and (best-effort) TikTok.

All three platforms need the video reachable at a public URL (none of them
accept raw bytes from inside a short GitHub Actions job in a simple way).
We solve that by uploading the .mp4 to a GitHub Release on this repo first
(see release_host.py) and reusing that release asset's public URL.

Required secrets (set in your repo's Settings -> Secrets -> Actions):

  FB_PAGE_ID            Facebook Page ID
  FB_PAGE_ACCESS_TOKEN  Long-lived Page access token with pages_manage_posts +
                         pages_read_engagement (and instagram_basic /
                         instagram_content_publish if also posting to IG)
  IG_BUSINESS_ID        Instagram Business/Creator account ID linked to the FB Page
                         (only needed if posting to Instagram)
  TIKTOK_ACCESS_TOKEN   OAuth access token from a TikTok developer app
                         (only needed if posting to TikTok - see README caveats)
"""

import os
import time
import requests

GRAPH_API = "https://graph.facebook.com/v19.0"


def post_to_facebook(video_url: str, caption: str, page_id: str | None = None,
                      access_token: str | None = None) -> dict:
    page_id = page_id or os.environ["FB_PAGE_ID"]
    access_token = access_token or os.environ["FB_PAGE_ACCESS_TOKEN"]

    resp = requests.post(
        f"{GRAPH_API}/{page_id}/videos",
        data={
            "file_url": video_url,
            "description": caption,
            "access_token": access_token,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def post_to_instagram(video_url: str, caption: str, ig_business_id: str | None = None,
                       access_token: str | None = None, poll_seconds: int = 10,
                       max_polls: int = 30) -> dict:
    ig_business_id = ig_business_id or os.environ["IG_BUSINESS_ID"]
    access_token = access_token or os.environ["FB_PAGE_ACCESS_TOKEN"]

    # Step 1: create a media container (Reels)
    create_resp = requests.post(
        f"{GRAPH_API}/{ig_business_id}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": access_token,
        },
        timeout=60,
    )
    create_resp.raise_for_status()
    creation_id = create_resp.json()["id"]

    # Step 2: poll until Instagram has finished downloading/processing the video
    for _ in range(max_polls):
        status_resp = requests.get(
            f"{GRAPH_API}/{creation_id}",
            params={"fields": "status_code", "access_token": access_token},
            timeout=30,
        )
        status_resp.raise_for_status()
        status = status_resp.json().get("status_code")
        if status == "FINISHED":
            break
        if status == "ERROR":
            raise RuntimeError(f"Instagram failed to process video: {status_resp.json()}")
        time.sleep(poll_seconds)
    else:
        raise TimeoutError("Instagram container never finished processing in time")

    # Step 3: publish
    publish_resp = requests.post(
        f"{GRAPH_API}/{ig_business_id}/media_publish",
        data={"creation_id": creation_id, "access_token": access_token},
        timeout=60,
    )
    publish_resp.raise_for_status()
    return publish_resp.json()


def post_to_tiktok(video_url: str, caption: str, access_token: str | None = None) -> dict:
    """
    Best-effort TikTok upload using the Content Posting API's PULL_FROM_URL method.

    IMPORTANT CAVEATS (read before relying on this in production):
    - Unaudited TikTok developer apps can only publish to the poster's own
      account as a PRIVATE/draft post - TikTok requires an app review before
      videos can go directly public via the API.
    - video_url must be reachable by TikTok's servers AND match a domain you
      verified in the TikTok developer portal.
    - Access tokens expire (~24h) and must be refreshed with a refresh_token;
      this function does not handle refreshing, only the actual post call.
    """
    access_token = access_token or os.environ["TIKTOK_ACCESS_TOKEN"]

    resp = requests.post(
        "https://open.tiktokapis.com/v2/post/publish/video/init/",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json={
            "post_info": {
                "title": caption,
                "privacy_level": "SELF_ONLY",
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "video_url": video_url,
            },
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()
