"""
image_fetcher.py
Pulls one free, vertical-friendly stock photo per scene from the Pexels API.

Pexels API key is free: https://www.pexels.com/api/ (sign up, copy key).
No payment, no credit card needed. Generous free-tier rate limit.
"""

import os
import random
import requests

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"


def fetch_image_for_query(query: str, save_path: str, api_key: str | None = None) -> str:
    api_key = api_key or os.environ.get("PEXELS_API_KEY")
    if not api_key:
        raise RuntimeError("PEXELS_API_KEY is not set")

    headers = {"Authorization": api_key}
    params = {
        "query": query,
        "orientation": "portrait",
        "size": "large",
        "per_page": 10,
    }

    resp = requests.get(PEXELS_SEARCH_URL, headers=headers, params=params, timeout=20)
    resp.raise_for_status()
    photos = resp.json().get("photos", [])

    if not photos:
        # Fall back to a more generic query so the pipeline never fully breaks
        params["query"] = "aesthetic nature"
        resp = requests.get(PEXELS_SEARCH_URL, headers=headers, params=params, timeout=20)
        resp.raise_for_status()
        photos = resp.json().get("photos", [])

    if not photos:
        raise RuntimeError(f"No Pexels results for query: {query}")

    photo = random.choice(photos)
    image_url = photo["src"]["large2x"]

    img_resp = requests.get(image_url, timeout=30)
    img_resp.raise_for_status()

    with open(save_path, "wb") as f:
        f.write(img_resp.content)

    return save_path


def fetch_images_for_scenes(scenes: list[dict], out_dir: str, api_key: str | None = None) -> list[dict]:
    """
    scenes: [{"text": ..., "image_query": ...}, ...]
    Returns the same list with an added "image_path" key per scene.
    """
    os.makedirs(out_dir, exist_ok=True)
    enriched = []
    for i, scene in enumerate(scenes):
        save_path = os.path.join(out_dir, f"scene_{i:02d}.jpg")
        fetch_image_for_query(scene["image_query"], save_path, api_key=api_key)
        enriched.append({**scene, "image_path": save_path})
    return enriched
