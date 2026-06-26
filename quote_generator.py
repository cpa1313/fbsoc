"""
quote_generator.py
Asks an LLM via Groq API for a short, aesthetic, "quote video" style
script: a handful of short lines that build to one emotional idea,
plus an image search keyword for each line (used to fetch a matching
background photo from Pexels).
"""

import json
import os
import random
from groq import Groq

THEMES = [
    "self-worth and knowing your value",
    "healing after heartbreak",
    "choosing peace over chaos",
    "growing into who you're meant to be",
    "letting go of people who don't appreciate you",
    "soft life / protecting your peace",
    "main character energy and self-respect",
    "lessons life teaches you quietly",
]

SYSTEM_PROMPT = """You write short scripts for vertical "aesthetic quote" videos \
(the kind posted on Instagram Reels / TikTok with slow zooming background art \
and one short line of text appearing per scene).

Rules:
- 3 to 6 scenes total.
- Each scene is ONE short line, max 9 words, no hashtags, no emoji, no quotation marks.
- Read together in order, the lines should flow as a single coherent thought,
  building to an emotional or empowering final line.
- Tone: reflective, gentle, a little poetic, emotionally resonant. Avoid cliché
  AI-sounding phrasing like "embrace the journey".
- For every line also give a short (2-5 word) English image search query that
  describes a calm, aesthetic, photographic scene that would pair well with
  that line as a background photo (e.g. "person looking at sunset", "empty road at night",
  "ocean waves shore", "woman walking city street"). Keep queries generic and photographable
  (no anime/illustration requests, no text-in-image requests).

Respond with ONLY valid JSON, no commentary, no markdown fences, in this exact shape:
{"scenes": [{"text": "...", "image_query": "..."}, ...], "caption": "a short Instagram caption with 3-5 relevant hashtags"}
"""


def generate_quote_scenes(theme: str | None = None, api_key: str | None = None) -> dict:
    """
    Returns: {"scenes": [{"text": ..., "image_query": ...}, ...], "caption": "..."}
    """
    api_key = api_key or os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set")

    chosen_theme = theme or random.choice(THEMES)
    client = Groq(api_key=api_key)

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",  # Fast, high-quality Groq model
        max_tokens=600,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Theme for today's video: {chosen_theme}"},
        ],
    )

    raw_text = response.choices[0].message.content.strip()

    # Be defensive in case the model wraps the JSON in a code fence anyway
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.startswith("json"):
            raw_text = raw_text[4:].strip()

    data = json.loads(raw_text)

    if "scenes" not in data or not isinstance(data["scenes"], list) or len(data["scenes"]) == 0:
        raise ValueError(f"Unexpected response shape from model: {data}")

    return data


if __name__ == "__main__":
    import sys
    result = generate_quote_scenes(theme=sys.argv[1] if len(sys.argv) > 1 else None)
    print(json.dumps(result, indent=2))
