# Aesthetic Quote Video Bot

Auto-generates a vertical (1080x1920) "aesthetic quote" video every day —
slow zooming background photo, short line of text per scene, soft music,
your watermark — then posts it to Facebook, Instagram, and (best-effort)
TikTok. Runs entirely on GitHub Actions, no server needed.

## How it works

1. **Claude (Anthropic API)** writes a short script: 3-6 short lines that
   build to one emotional idea, plus an image search keyword per line.
2. **Pexels** (free stock photo API) finds one matching photo per line.
3. **edge-tts** (free, no API key) turns each line into spoken narration
   in a natural-sounding voice, and reports the exact start/end time of
   every word as it's spoken.
4. **video_engine.py** (moviepy) builds the video: Ken Burns zoom on each
   photo, the line of text lighting up **word-by-word in sync with the
   narration** (karaoke style), your watermark, and background music
   ducked quietly under the voice.
5. The finished `.mp4` is attached to a **GitHub Release** in this repo —
   that gives it a public URL, which Facebook/Instagram/TikTok need in
   order to "pull" the video.
6. The video gets posted to whichever platforms you've configured.

## One-time setup

### 1. Add this repo to GitHub, then add secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Required for | How to get it |
|---|---|---|
| `ANTHROPIC_API_KEY` | quote generation | console.anthropic.com → API Keys |
| `PEXELS_API_KEY` | background photos | pexels.com/api → sign up, free, instant |
| `FB_PAGE_ID` | Facebook posting | Your Facebook Page's "About" page |
| `FB_PAGE_ACCESS_TOKEN` | Facebook + Instagram posting | See below |
| `IG_BUSINESS_ID` | Instagram posting | See below |
| `TIKTOK_ACCESS_TOKEN` | TikTok posting (limited, see caveats) | TikTok for Developers |
| `WATERMARK_TEXT` | optional | e.g. `@yourbrand` (defaults to `@yourbrand`) |

You don't need every secret — skip a platform's secrets and `main.py`
just skips posting there (it still renders the video either way).

### 2. Getting a Facebook Page access token + Instagram Business ID
1. Create a Meta developer app at developers.facebook.com.
2. Link your Instagram account to your Facebook Page as a Business/Creator
   account (Instagram app → Settings → Account type).
3. Use the **Graph API Explorer** (developers.facebook.com/tools/explorer)
   to generate a User token with `pages_show_list`, `pages_manage_posts`,
   `pages_read_engagement`, `instagram_basic`, `instagram_content_publish`.
4. Exchange it for a long-lived Page token (Meta's docs: "Long-Lived Access
   Tokens"). That long-lived token is `FB_PAGE_ACCESS_TOKEN`.
5. Call `GET /{page-id}?fields=instagram_business_account` with that token
   to get `IG_BUSINESS_ID`.

Long-lived Page tokens last ~60 days and need refreshing periodically —
this script does not auto-refresh them.

### 3. TikTok — important limitations
TikTok's Content Posting API only allows **fully public, audited apps**
to publish directly to a feed. A brand-new/unaudited developer app can
only post videos as **private drafts** to the account that authorized it
(`privacy_level: SELF_ONLY` is what's wired up in `social_uploader.py`).
Also, TikTok access tokens expire roughly every 24 hours and need a
refresh-token flow this project doesn't automate. Treat the TikTok
integration as a starting point, not a finished auto-poster — for real
TikTok automation you'd want to apply for API audit and add token refresh.

### 4. Add background music
Drop a few royalty-free `.mp3` files into `assets/music/`. The script
picks one at random each run. (YouTube Audio Library, Pixabay Music, and
Free Music Archive all have CC0 / royalty-free tracks you can download
and commit here.)

## Running it

- **On schedule**: the workflow runs daily at 13:00 UTC
  (`.github/workflows/post_quote_video.yml` — change the cron line to suit you).
- **Manually**: GitHub repo → Actions → "Post Aesthetic Quote Video" →
  Run workflow. You can optionally type a theme override.
- **Locally** (for testing before you trust it with real secrets):
  ```bash
  pip install -r requirements.txt
  export ANTHROPIC_API_KEY=...
  export PEXELS_API_KEY=...
  python main.py
  ```
  Without `GITHUB_TOKEN`/`GITHUB_REPOSITORY` set, the release-hosting and
  posting steps will fail gracefully — you'll still get `output.mp4`
  locally to check it looks right.

## Customizing the look

- `QUOTE_THEME` env var (or the workflow's manual "theme" input) steers
  what the quote is about for that run.
- `TTS_VOICE` env var/secret pins one specific edge-tts voice (otherwise a
  random one from a small warm-voice pool is picked each run). List all
  available voices with `edge-tts --list-voices` after `pip install edge-tts`.
- `TTS_RATE` env var/secret controls speaking speed (default `-6%`, slightly
  slower/more reflective than normal).
- `karaoke_captions.py` → `HIGHLIGHT_COLOR` (default warm gold) controls the
  color the active word lights up; `TEXT_COLOR` is the default white.
- `video_engine.py` → `LEAD_IN`, `TAIL_PAD`, `ZOOM_PER_SECOND`, font size,
  and colors are all easy to tweak.
- Swap `assets/fonts/Poppins-SemiBold.ttf` for any other `.ttf` you like.
- `WATERMARK_TEXT` secret/env var controls the bottom-of-screen watermark.

Note: edge-tts needs outbound internet to Microsoft's speech endpoint at
run time. That's open by default on GitHub Actions runners, so nothing
extra to configure there - it just won't work from a heavily locked-down
local sandbox/corporate network.

## A note on the original videos you showed me

The sample clips use a specific artist's illustrated art style and their
own watermark/handle — that art belongs to them, so this bot does **not**
copy it. It recreates the same *format* (zoom + line-by-line captions +
music + watermark) using your own AI-written quotes and free, legally
licensed stock photography instead.
