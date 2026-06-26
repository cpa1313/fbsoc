"""
voiceover.py
Turns each quote line into spoken-word audio using edge-tts (Microsoft's
free, no-API-key-needed neural voices), and captures the exact start/end
time of every individual word as it's spoken - that per-word timing is
what drives the karaoke-style caption highlight in video_engine.py.

Needs outbound internet to speech.platform.bing.com at runtime, which is
open by default on GitHub Actions runners (nothing extra to configure
there). Pick a different voice with the TTS_VOICE secret/env var if you
want - browse options with: `edge-tts --list-voices`
"""

import asyncio
import os
import re
import random
import edge_tts

# Warm, expressive, natural-sounding voices that fit this genre's reflective tone.
# These are selected for emotional range, not just clarity.
# Override with the TTS_VOICE env var to pin one specific voice instead.
DEFAULT_VOICE_POOL = [
    "en-US-AriaNeural",     # Warm, expressive, great emotional range
    "en-US-JennyNeural",    # Soft, conversational, gentle delivery
    "en-GB-SoniaNeural",    # Slightly breathy, poetic feel
    "en-US-MichelleNeural", # Rich, calm, very natural
    "en-AU-NatashaNeural",  # Distinct, warm Australian tone
]


def pick_voice() -> str:
    forced = os.environ.get("TTS_VOICE")
    return forced if forced else random.choice(DEFAULT_VOICE_POOL)


def _merge_word_timings(raw_timings: list[dict], original_text: str) -> list[dict]:
    """
    edge-tts WordBoundary events can return sub-word phoneme fragments
    instead of whole words — e.g. "for" comes back as ["fo", "r"] and
    "myself" as ["myse", "lf"]. This causes the karaoke layout to treat
    fragments as separate words, breaking mid-word across lines.

    Fix: greedily consume raw timing tokens until their stripped+lowercased
    concatenation matches each original word, then emit a single merged
    entry spanning the full start→end range of those tokens.
    """
    orig_words = re.findall(r"\S+", original_text)
    if not orig_words or not raw_timings:
        return raw_timings

    def clean(s: str) -> str:
        """Strip punctuation for comparison only."""
        return re.sub(r"[^\w'-]", "", s).lower()

    merged = []
    t_idx = 0

    for word in orig_words:
        target = clean(word)
        if not target or t_idx >= len(raw_timings):
            continue

        acc = ""
        start = raw_timings[t_idx]["start"]
        end = raw_timings[t_idx]["end"]

        while t_idx < len(raw_timings):
            tok = clean(raw_timings[t_idx]["text"])
            end = raw_timings[t_idx]["end"]
            acc += tok
            t_idx += 1
            if acc == target:
                break                  # perfect match — done
            if not target.startswith(acc):
                break                  # diverged — accept what we have

        merged.append({"text": word, "start": start, "end": end})

    return merged


async def _save_with_word_timing(
    text: str, out_path: str, voice: str, rate: str, pitch: str
) -> list[dict]:
    # Pass rate and pitch directly — NO SSML. Edge-tts handles these as
    # native parameters so the voice reads the plain text naturally without
    # accidentally reading out XML tags aloud.
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    raw_timings = []
    with open(out_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                # offset/duration come back in 100-nanosecond ticks
                start = chunk["offset"] / 10_000_000
                end = (chunk["offset"] + chunk["duration"]) / 10_000_000
                raw_timings.append({"text": chunk["text"], "start": start, "end": end})

    # Merge any sub-word phoneme fragments back into whole words.
    word_timings = _merge_word_timings(raw_timings, text)
    return word_timings


def synthesize_line(
    text: str,
    out_path: str,
    voice: str | None = None,
    rate: str | None = None,
    pitch: str | None = None,
) -> tuple[str, list[dict]]:
    voice = voice or pick_voice()
    # Slower rate = more thoughtful, emotional delivery
    rate = rate or os.environ.get("TTS_RATE", "-8%")
    # Slight pitch drop = warmth and sincerity
    pitch = pitch or os.environ.get("TTS_PITCH", "-3Hz")
    word_timings = asyncio.run(_save_with_word_timing(text, out_path, voice, rate, pitch))
    return out_path, word_timings


def synthesize_scenes(
    scenes: list[dict], out_dir: str, voice: str | None = None
) -> list[dict]:
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
