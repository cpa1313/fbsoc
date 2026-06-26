"""
voiceover.py
Turns each quote line into spoken-word audio using edge-tts (Microsoft's
free, no-API-key-needed neural voices), and captures the exact start/end
time of every individual word as it's spoken - that per-word timing is
what drives the karaoke-style caption highlight in video_engine.py.

Needs outbound internet to speech.platform.bing.com at runtime, which is
open by default on GitHub Actions runners (nothing extra to configure
there). Pick a different voice with the TTS_VOICE secret/env var if you
want - browse options with: `edge-tts --list-voices`.
"""

import asyncio
import os
import random
import edge_tts

# A handful of warm, natural-sounding voices that fit this genre's reflective tone.
# Override with the TTS_VOICE env var to pin one specific voice instead.
DEFAULT_VOICE_POOL = [
    "en-US-AriaNeural",
    "en-US-AnaNeural",
    "en-GB-SoniaNeural",
    "en-US-JennyNeural",
]


def pick_voice() -> str:
    forced = os.environ.get("TTS_VOICE")
    return forced if forced else random.choice(DEFAULT_VOICE_POOL)


async def _save_with_word_timing(text: str, out_path: str, voice: str, rate: str) -> list[dict]:
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    word_timings = []
    with open(out_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                # offset/duration come back in 100-nanosecond ticks
                start = chunk["offset"] / 10_000_000
                end = (chunk["offset"] + chunk["duration"]) / 10_000_000
                word_timings.append({"text": chunk["text"], "start": start, "end": end})
    return word_timings


def synthesize_line(text: str, out_path: str, voice: str | None = None,
                     rate: str | None = None) -> tuple[str, list[dict]]:
    voice = voice or pick_voice()
    rate = rate or os.environ.get("TTS_RATE", "-6%")  # slightly slower = more reflective pace
    word_timings = asyncio.run(_save_with_word_timing(text, out_path, voice, rate))
    return out_path, word_timings


def synthesize_scenes(scenes: list[dict], out_dir: str, voice: str | None = None) -> list[dict]:
    """
    scenes: [{"text": ..., "image_path": ...}, ...]
    Returns the same list with "voice_path" and "word_timings" added per scene.
    All lines in one video use the same voice for consistency.
    """
    os.makedirs(out_dir, exist_ok=True)
    chosen_voice = voice or pick_voice()
    enriched = []
    for i, scene in enumerate(scenes):
        voice_path = os.path.join(out_dir, f"voice_{i:02d}.mp3")
        _, word_timings = synthesize_line(scene["text"], voice_path, voice=chosen_voice)
        enriched.append({**scene, "voice_path": voice_path, "word_timings": word_timings})
    return enriched
