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
    "en-AU-NatashaNeural",  # Distinct, warm Australian tone - great for motivation
]

# ── Emotion / energy presets ──────────────────────────────────────────────────
# Each preset is (rate, pitch, volume).
# "motivational" is tuned for NatashaNeural but works well with all voices.
EMOTION_PRESETS = {
    "motivational": ("+18%", "+10Hz", "+20%"),   # Energetic, uplifting, punchy
    "calm":         ("-8%",  "-3Hz",  "+0%"),    # Thoughtful, reflective
    "powerful":     ("+8%",  "+5Hz",  "+25%"),   # Bold, authoritative
    "gentle":       ("-12%", "-5Hz",  "-5%"),    # Soft and warm
}

ACTIVE_PRESET = os.environ.get("TTS_EMOTION", "motivational")


def pick_voice() -> str:
    forced = os.environ.get("TTS_VOICE")
    return forced if forced else random.choice(DEFAULT_VOICE_POOL)


# ── Text coaching: guide the neural voice into emotional delivery ─────────────

# Words that deserve a strong beat — we place a comma BEFORE them so the voice
# pauses slightly and then hits the word with renewed energy.
_POWER_WORDS = {
    "never", "always", "every", "only", "now", "today", "rise", "fight",
    "believe", "become", "choose", "create", "start", "stop", "must",
    "will", "won't", "can", "cannot", "enough", "more", "you", "yourself",
    "stronger", "better", "harder", "possible", "impossible", "dream",
    "action", "change", "forward", "unstoppable", "greatness", "success",
    "purpose", "passion", "courage", "fear", "pain", "power", "truth",
    "decide", "commit", "push", "limit", "break", "build", "earn", "win",
}

# Sentence-ending words — add "..." so the voice trails powerfully before
# the next sentence kicks in (creates deliberate, emotional pacing).
_TRAILING_PUNCTUATION = {".", "!", "?"}


def _coach_text(text: str) -> str:
    """
    Massage the quote text so the neural TTS model delivers it with more
    emotion and punch. We don't change words — we only add commas, ellipses,
    and exclamation marks as coaching signals.

    Rules:
      1. Sentences ending with "." become "..." for a trailing, powerful pause.
      2. "." mid-sentence → keep as-is (TTS already pauses naturally).
      3. Known power words get a comma inserted before them (unless one already
         exists) so the voice breathes and then delivers with fresh energy.
      4. Short sentences (≤ 5 words) get an "!" appended if they don't already
         end with "?" or "!" — short punchy lines deserve maximum impact.
    """
    # Step 1: convert sentence-ending periods to ellipsis for trailing energy
    # Match period at end of a word that is followed by whitespace or end-of-str
    text = re.sub(r'\.(\s|$)', r'...\1', text)

    # Step 2: insert comma before power words for a breath-then-punch effect
    words = text.split(" ")
    coached = []
    for i, word in enumerate(words):
        core = re.sub(r"[^\w]", "", word).lower()
        if core in _POWER_WORDS and i > 0 and not coached[-1].endswith(","):
            coached.append(word)
            # swap: put comma at end of PREVIOUS token
            coached[-2] = coached[-2].rstrip() + ","
        else:
            coached.append(word)
    text = " ".join(coached)

    # Step 3: short punchy sentences get "!" if they don't already
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    boosted = []
    for sentence in sentences:
        word_count = len(sentence.split())
        last_char = sentence.rstrip()[-1] if sentence.rstrip() else ""
        if word_count <= 5 and last_char not in ("!", "?"):
            sentence = sentence.rstrip(".") + "!"
        boosted.append(sentence)
    text = " ".join(boosted)

    return text


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
                break
            if not target.startswith(acc):
                break

        merged.append({"text": word, "start": start, "end": end})

    return merged


async def _save_with_word_timing(
    text: str, out_path: str, voice: str, rate: str, pitch: str, volume: str
) -> list[dict]:
    # Coach the text first for emotional delivery
    coached_text = _coach_text(text)

    # Pass rate, pitch, volume directly — NO SSML. Edge-tts handles these as
    # native parameters so the voice reads the plain text naturally.
    communicate = edge_tts.Communicate(coached_text, voice, rate=rate, pitch=pitch, volume=volume)
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

    # Merge sub-word phoneme fragments back into whole words.
    # Use the ORIGINAL (uncoached) text for matching since that's what the
    # karaoke captions display — coached punctuation doesn't appear on screen.
    word_timings = _merge_word_timings(raw_timings, text)
    return word_timings


def synthesize_line(
    text: str,
    out_path: str,
    voice: str | None = None,
    rate: str | None = None,
    pitch: str | None = None,
    volume: str | None = None,
    emotion: str | None = None,
) -> tuple[str, list[dict]]:
    voice = voice or pick_voice()

    # Resolve emotion preset first, then allow individual overrides
    preset_emotion = emotion or ACTIVE_PRESET
    preset = EMOTION_PRESETS.get(preset_emotion, EMOTION_PRESETS["motivational"])
    preset_rate, preset_pitch, preset_volume = preset

    rate   = rate   or os.environ.get("TTS_RATE",   preset_rate)
    pitch  = pitch  or os.environ.get("TTS_PITCH",  preset_pitch)
    volume = volume or os.environ.get("TTS_VOLUME", preset_volume)

    word_timings = asyncio.run(
        _save_with_word_timing(text, out_path, voice, rate, pitch, volume)
    )
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
