"""
main.py
Runs the whole pipeline end to end:
  1. Ask Claude for a quote script (lines + image search keywords)
  2. Fetch a matching free stock photo per line from Pexels
  3. Render the vertical quote video (Ken Burns zoom + captions + music + watermark)
  4. Publish the .mp4 to a GitHub Release to get a public URL
  5. Post that video to Facebook / Instagram / TikTok

Every network-dependent step is wrapped so one failing platform doesn't
take down the others - you'll get a clear log either way.
"""

import os
import sys
import glob
import random
import traceback

from quote_generator import generate_quote_scenes
from image_fetcher import fetch_images_for_scenes
from voiceover import synthesize_scenes
from video_engine import build_video
from release_host import publish_video_get_public_url
from social_uploader import post_to_facebook, post_to_instagram, post_to_tiktok

ROOT = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(ROOT, "assets", "fonts", "Poppins-SemiBold.ttf")
MUSIC_DIR = os.path.join(ROOT, "assets", "music")
WORK_DIR = os.path.join(ROOT, "_work")
OUT_PATH = os.path.join(ROOT, "output.mp4")

WATERMARK_TEXT = os.environ.get("WATERMARK_TEXT", "@yourbrand")


def pick_music_track() -> str | None:
    tracks = [
        f for f in glob.glob(os.path.join(MUSIC_DIR, "*.mp3"))
        if not f.endswith("test_tone.mp3")
    ]
    return random.choice(tracks) if tracks else None


def run_step(label, fn, *args, **kwargs):
    print(f"\n=== {label} ===")
    try:
        result = fn(*args, **kwargs)
        print(f"OK: {label}")
        return result
    except Exception:
        print(f"FAILED: {label}")
        traceback.print_exc()
        return None


def main():
    os.makedirs(WORK_DIR, exist_ok=True)

    theme = os.environ.get("QUOTE_THEME")  # optional override
    script = run_step("Generating quote script with Claude", generate_quote_scenes, theme=theme)
    if not script:
        sys.exit("Could not generate a quote script - stopping.")

    scenes = run_step(
        "Fetching background photos from Pexels",
        fetch_images_for_scenes, script["scenes"], WORK_DIR,
    )
    if not scenes:
        sys.exit("Could not fetch background images - stopping.")

    scenes = run_step(
        "Generating spoken narration for each line",
        synthesize_scenes, scenes, WORK_DIR,
    )
    if not scenes:
        sys.exit("Could not generate narration - stopping.")

    music_path = pick_music_track()
    if not music_path:
        print("No music files found in assets/music/ - video will be silent. "
              "Add a royalty-free .mp3 there to fix this.")

    video_path = run_step(
        "Rendering video",
        build_video, scenes, FONT_PATH, WATERMARK_TEXT, music_path, OUT_PATH,
    )
    if not video_path:
        sys.exit("Video render failed - stopping.")

    caption = script.get("caption", "")

    public_url = run_step(
        "Hosting video as a GitHub Release asset (for the social APIs to fetch)",
        publish_video_get_public_url, video_path,
    )
    if not public_url:
        sys.exit("Could not get a public URL for the video - stopping before posting.")

    print(f"\nPublic video URL: {public_url}")

    if os.environ.get("FB_PAGE_ID") and os.environ.get("FB_PAGE_ACCESS_TOKEN"):
        run_step("Posting to Facebook", post_to_facebook, public_url, caption)
    else:
        print("\nSkipping Facebook - FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN not set.")

    if os.environ.get("IG_BUSINESS_ID") and os.environ.get("FB_PAGE_ACCESS_TOKEN"):
        run_step("Posting to Instagram", post_to_instagram, public_url, caption)
    else:
        print("Skipping Instagram - IG_BUSINESS_ID / FB_PAGE_ACCESS_TOKEN not set.")

    if os.environ.get("TIKTOK_ACCESS_TOKEN"):
        run_step("Posting to TikTok", post_to_tiktok, public_url, caption)
    else:
        print("Skipping TikTok - TIKTOK_ACCESS_TOKEN not set.")

    print("\nDone.")


if __name__ == "__main__":
    main()
